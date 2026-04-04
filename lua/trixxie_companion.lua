-- ================================================================
-- Trixxie Carissa — Cool VL Viewer Automation Script
-- ================================================================
-- Place this file at: <viewer>/user_settings/automation.lua
--
-- SETUP:
--   1. Set SERVER_URL to your bridge's public HTTPS base URL (no trailing slash)
--      Same value as SERVER_URL in the LSL HUD — e.g. https://your-tunnel.trycloudflare.com
--   2. Set SECRET to match SL_BRIDGE_SECRET in your .env (or leave empty)
--   3. Set GRID to "opensim" if running on OpenSimulator
-- ================================================================

-- --- Config ---
local SERVER_URL    = "https://your-tunnel.trycloudflare.com"
local SECRET        = ""
local GRID          = "sl"       -- "sl" or "opensim"
local CHAT_BUF_SIZE = 10         -- ambient chat lines to buffer
local IM_CHUNK_SIZE = 1000       -- max chars per SendIM call

-- --- State ---
local pending_ims = {}    -- [handle] = {session_id, origin_id}
local nearby_chat = {}    -- rolling buffer of recent local chat lines


-- ================================================================
-- Helpers
-- ================================================================

-- Append a line to the nearby_chat buffer, dropping the oldest if full.
local function append_chat(line)
    nearby_chat[#nearby_chat + 1] = line
    if #nearby_chat > CHAT_BUF_SIZE then
        table.remove(nearby_chat, 1)
    end
end

-- Split text into chunks of at most IM_CHUNK_SIZE chars, breaking at the last
-- sentence boundary (". ", "! ", "? ", "\n") in the second half of the chunk.
local function split_chunks(text)
    local chunks = {}
    local start  = 1
    local len    = string.len(text)

    while start <= len do
        local finish = start + IM_CHUNK_SIZE - 1
        if finish >= len then
            chunks[#chunks + 1] = string.sub(text, start)
            break
        end

        -- Try to break at a sentence boundary in the back half of the chunk.
        local boundary = nil
        local half     = start + math.floor(IM_CHUNK_SIZE / 2)
        local window   = string.sub(text, half, finish)

        -- Search right-to-left for ". ", "! ", "? ", "\n"
        for _, sep in ipairs({". ", "! ", "? ", "\n"}) do
            local pos = 1
            local last_found = nil
            while true do
                local s, e = string.find(window, sep, pos, true)
                if not s then break end
                last_found = half + s - 1  -- map back to full-string position
                pos = e + 1
            end
            if last_found and (not boundary or last_found > boundary) then
                boundary = last_found + string.len(sep) - 1
            end
        end

        if boundary then
            chunks[#chunks + 1] = string.sub(text, start, boundary)
            start = boundary + 1
        else
            chunks[#chunks + 1] = string.sub(text, start, finish)
            start = finish + 1
        end
    end

    return chunks
end

-- Deliver a (potentially long) reply as successive SendIM calls.
local function send_chunked(session_id, text)
    local chunks = split_chunks(text)
    for _, chunk in ipairs(chunks) do
        SendIM(session_id, chunk)
    end
end


-- ================================================================
-- OnInstantMsg — fires on every received IM
-- type == 0 : peer-to-peer (private IM)
-- ================================================================
function OnInstantMsg(session_id, origin_id, msg_type, name, text)
    -- Only handle peer-to-peer IMs.
    if msg_type ~= 0 then return end

    -- Ignore messages sent by this avatar (Trixxie herself).
    local self_info = GetAgentInfo()
    if self_info and origin_id == self_info["id"] then return end

    -- Build the POST payload.
    local region = ""
    local grid_info = GetGridSimAndPos()
    if grid_info then
        region = grid_info["region"] or ""
    end

    local payload = {
        user_id      = origin_id,
        display_name = name,
        message      = text,
        region       = region,
        channel      = 42,
        grid         = GRID,
    }
    if #nearby_chat > 0 then
        payload["nearby_chat"] = nearby_chat
    end

    -- Include secret in body (PostHTTP does not support custom headers).
    if SECRET and SECRET ~= "" then
        payload["secret"] = SECRET
    end

    local body = EncodeJSON(payload)

    -- Show typing indicator, fire async POST, stash handle → session mapping.
    SetAgentTyping(true)
    local handle = PostHTTP(SERVER_URL .. "/sl/message", body, 60, "application/json", "application/json")
    pending_ims[handle] = {session_id = session_id, origin_id = origin_id}
end


-- ================================================================
-- OnHTTPReply — fires when PostHTTP completes
-- ================================================================
function OnHTTPReply(handle, success, reply)
    local ctx = pending_ims[handle]
    if not ctx then return end

    -- Always clear the typing indicator and the pending entry.
    SetAgentTyping(false)
    pending_ims[handle] = nil

    if not success then
        SendIM(ctx.session_id, "*Something went sideways on my end. Try again in a moment.*")
        return
    end

    local data = DecodeJSON(reply)
    if not data then
        SendIM(ctx.session_id, "*I got a garbled reply from my brain. Try again.*")
        return
    end

    -- Deliver direct reply text (chunked to respect 1023-char IM limit).
    local reply_text = data["reply"] or ""
    if reply_text ~= "" then
        send_chunked(ctx.session_id, reply_text)
    end

    -- Deliver any action lines (im / emote).
    local actions = data["actions"]
    if actions then
        for _, action in ipairs(actions) do
            local atype = action["action_type"] or "im"
            local atext = action["text"] or ""
            if atext ~= "" then
                if atype == "emote" then
                    -- Wrap in asterisks if not already.
                    if string.sub(atext, 1, 1) ~= "*" then
                        atext = "*" .. atext .. "*"
                    end
                end
                SendIM(ctx.session_id, atext)
            end
        end
    end
end


-- ================================================================
-- OnReceivedChat — feeds the ambient nearby-chat buffer
-- type == 1 : normal avatar speech on channel 0
-- ================================================================
function OnReceivedChat(chat_type, from_id, is_avatar, name, text)
    -- Only capture normal open-channel speech from avatars.
    if chat_type ~= 1 then return end
    if not is_avatar then return end

    -- text already includes the speaker name in the viewer's format;
    -- build the same "Name: message" format the LSL HUD produces.
    append_chat(name .. ": " .. text)
end
