-- ================================================================
-- Trixxie — Friendly Companion Agent — Cool VL Viewer Automation Script
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
local SERVER_URL    = "YOUR_TUNNEL_URL"
local SECRET        = "YOUR_BRIDGE_SECRET"
local GRID          = "sl"       -- "sl" or "opensim"
local IM_CHUNK_SIZE = 1000       -- max chars per SendIM call

-- --- State ---
local pending_ims = {}    -- [handle] = {session_id, origin_id}


-- ================================================================
-- Helpers
-- ================================================================

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

    -- Chat context is delivered via the HUD's sensor pipeline (/sl/sensor type="chat"),
    -- not piggybacked on this request. The HUD must be worn and running.
    local payload = {
        user_id      = origin_id,
        display_name = name,
        message      = text,
        region       = region,
        channel      = 42,
        grid         = GRID,
        client       = "lua",
    }

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

    -- Deliver any action lines (im / emote / mute / unmute).
    local raw_actions = data["actions"]
    -- CoolVL's DecodeJSON unwraps single-element JSON arrays into the object itself.
    -- Normalize to an ipairs-compatible list regardless of how many actions there are.
    local action_list = {}
    if type(raw_actions) == "table" then
        if raw_actions["action_type"] ~= nil then
            -- Single action was decoded as a plain object (array wrapper stripped).
            action_list[1] = raw_actions
        else
            -- Multiple actions: try 0-based first, then 1-based.
            local i = 0
            while raw_actions[i] ~= nil do
                action_list[#action_list + 1] = raw_actions[i]
                i = i + 1
            end
            if #action_list == 0 then
                i = 1
                while raw_actions[i] ~= nil do
                    action_list[#action_list + 1] = raw_actions[i]
                    i = i + 1
                end
            end
        end
    end
    print("OnHTTPReply: processing " .. tostring(#action_list) .. " action(s)")
    if #action_list > 0 then
        for idx, action in ipairs(action_list) do
            local atype = action["action_type"] or "im"
            local atext = action["text"] or ""
            print("OnHTTPReply: action[" .. tostring(idx) .. "] type=" .. atype .. " text=" .. atext)
            if atype == "mute_avatar" then
                -- type=1 (avatar by Id) requires UUID, not display name.
                local uuid = action["target_key"] or ctx.origin_id or ""
                local label = action["text"] or uuid
                print("OnHTTPReply: calling AddMute uuid=" .. uuid)
                if uuid ~= "" then AddMute(uuid, 1) end
                print("OnHTTPReply: AddMute returned")
            elseif atype == "unmute_avatar" then
                local uuid = action["target_key"] or ctx.origin_id or ""
                local label = action["text"] or uuid
                print("OnHTTPReply: calling RemoveMute uuid=" .. uuid)
                if uuid ~= "" then RemoveMute(uuid, 1) end
                print("OnHTTPReply: RemoveMute returned")
            elseif atype == "is_muted" then
                local uuid = action["target_key"] or ctx.origin_id or ""
                local label = action["text"] or uuid
                print("OnHTTPReply: calling IsMuted uuid=" .. uuid)
                if uuid ~= "" then
                    local muted = IsMuted(uuid, 1)
                    print("OnHTTPReply: IsMuted=" .. tostring(muted))
                    SendIM(ctx.session_id, label .. " is " .. (muted and "muted" or "not muted"))
                end
            elseif atext ~= "" then
                if atype == "emote" then
                    -- Wrap in asterisks if not already.
                    if string.sub(atext, 1, 1) ~= "*" then
                        atext = "*" .. atext .. "*"
                    end
                end
                SendIM(ctx.session_id, atext)
            end
        end
    else
        print("OnHTTPReply: actions field is nil/absent in response")
    end
end


-- OnReceivedChat is intentionally not implemented here.
-- Nearby chat is captured by the LSL HUD's channel 0 listener, flushed to
-- /sl/sensor every 90s, and delivered via SensorStore.get_changes() on the
-- next message. The HUD must be worn and running alongside this script.
