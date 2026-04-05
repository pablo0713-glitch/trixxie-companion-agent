// ================================================================
// Trixxie Carissa — Sensory Companion HUD
// Phase 2 — Environmental Awareness
// ================================================================
// Wear this HUD on Trixxie's avatar. Touch to open sensor controls.
// Channel 42 conversations work as before.
//
// SETUP:
//   1. Set SERVER_URL to your bridge's public URL
//   2. Set SECRET to match SL_BRIDGE_SECRET in your .env (or leave empty)
//   3. Attach to Trixxie as a HUD
// ================================================================

// --- Config ---
string  SERVER_URL     = "https://toe-highly-leasing-epic.trycloudflare.com";
string  SECRET         = "death1";
string  GRID           = "sl";      // "sl" for Second Life, "opensim" for OpenSimulator
integer LISTEN_CHANNEL = 42;
integer UI_CHANNEL     = -7654321;  // private dialog channel
integer CHAT_BUF_SIZE  = 10;        // ambient chat lines to buffer

// --- Sensor toggles ---
integer s_avatars = TRUE;
integer s_chat    = TRUE;
integer s_env     = TRUE;
integer s_objects = TRUE;

// --- Avatar scan: returns the closest avatars in the region (hard cap) ---
integer AV_MAX      = 25;

// --- Timer ---
float   TICK_SECS  = 30.0;
integer tick       = 0;
integer AV_TICKS   = 5;    // avatar scan every  5 ticks =  150s
integer OBJ_TICKS  = 10;   // object scan every 10 ticks =  300s
integer ENV_TICKS  = 20;   // env scan every    20 ticks =  600s (time-of-day drift)

// --- Region/parcel tracking (env scan fires on region OR parcel change) ---
string  last_region = "";
string  last_parcel = "";

// --- HTTP keys: reply flow ---
key reply_http   = NULL_KEY;
key reply_sender = NULL_KEY;

// --- HTTP keys: sensor posts (fire and forget) ---
key sk_av  = NULL_KEY;
key sk_env = NULL_KEY;
key sk_obj = NULL_KEY;
key sk_clo = NULL_KEY;

// --- Ambient chat buffer (sent as context with /42 messages) ---
list nearby_chat = [];

// --- Clothing scan state machine ---
// 0=idle  1=find-agent (AGENT sweep)  2=find-attachments (PASSIVE|ACTIVE sweep)
integer scan_mode  = 0;
key     clo_target = NULL_KEY;
string  clo_name   = "";


// ================================================================
// Helpers
// ================================================================

// Escape a string for embedding inside a JSON "..." value
string json_s(string s)
{
    s = llReplaceSubString(s, "\\", "\\\\", 0);
    s = llReplaceSubString(s, "\"", "\\\"", 0);
    s = llReplaceSubString(s, "\n", "\\n",  0);
    s = llReplaceSubString(s, "\t", "\\t",  0);
    return s;
}

// Send a long string as one or more IMs, breaking at sentence boundaries.
// SL llInstantMessage has a hard 1023-char limit; we stay safely under it.
send_chunked(key target, string text)
{
    integer limit = 1000;
    while (llStringLength(text) > limit)
    {
        integer cut = limit;   // fallback: hard cut at limit
        integer i;
        // Scan backwards up to 200 chars for ". ", "! ", "? " or end-of-string
        for (i = limit - 1; i > limit - 200 && i >= 0; i--)
        {
            string c  = llGetSubString(text, i,     i    );
            string nx = llGetSubString(text, i + 1, i + 1);
            if ((c == "." || c == "!" || c == "?") &&
                (nx == " " || nx == "\n" || nx == ""))
            {
                cut = i + 1;  // include the punctuation in this chunk
                i   = -1;     // exit loop
            }
        }
        llInstantMessage(target, llGetSubString(text, 0, cut - 1));
        text = llGetSubString(text, cut, -1);
        if (llGetSubString(text, 0, 0) == " ")
            text = llGetSubString(text, 1, -1);
    }
    if (text != "")
        llInstantMessage(target, text);
}

// Fire-and-forget POST to /sl/sensor
// data_json must be a valid JSON value (object or array string)
key sensor_post(string stype, string data_json)
{
    string region = llGetRegionName();
    string body = "{\"type\":\"" + stype
                + "\",\"region\":\"" + json_s(region)
                + "\",\"user_id\":\"" + (string)llGetOwner()
                + "\",\"data\":" + data_json + "}";

    list p = [
        HTTP_METHOD, "POST",
        HTTP_MIMETYPE, "application/json",
        HTTP_VERIFY_CERT, TRUE
    ];
    if (SECRET != "")
        p += [HTTP_CUSTOM_HEADER, "X-SL-Secret", SECRET];

    return llHTTPRequest(SERVER_URL + "/sl/sensor", p, body);
}


// ================================================================
// Sensor: Avatars
// ================================================================

do_avatar_scan()
{
    if (!s_avatars) return;

    list    agents = llGetAgentList(AGENT_LIST_REGION, []);
    vector  my_pos = llGetPos();
    key     owner  = llGetOwner();
    list    nearby = [];   // strided [dist, name, dist, name, ...]
    integer i;
    integer count  = llGetListLength(agents);

    for (i = 0; i < count; i++)
    {
        key id = llList2Key(agents, i);
        if (id != owner)
        {
            list det = llGetObjectDetails(id, [OBJECT_POS, OBJECT_NAME]);
            if (llGetListLength(det) == 2)
            {
                float dist = llVecDist(llList2Vector(det, 0), my_pos);
                nearby += [dist, llList2String(det, 1)];
            }
        }
    }
    agents = [];

    if (llGetListLength(nearby) == 0) return;

    // Sort nearest-first, trim to AV_MAX, then build JSON
    nearby = llListSort(nearby, 2, TRUE);

    integer total = llGetListLength(nearby) / 2;
    if (total > AV_MAX)
    {
        nearby = llList2List(nearby, 0, AV_MAX * 2 - 1);
        total  = AV_MAX;
    }

    string arr = "[";
    for (i = 0; i < total; i++)
    {
        float  rd    = (float)llRound(llList2Float(nearby, i * 2) * 10) / 10.0;
        string aname = llList2String(nearby, i * 2 + 1);
        if (i > 0) arr += ",";
        arr += "{\"name\":\"" + json_s(aname) + "\",\"distance\":" + (string)rd + "}";
    }
    arr += "]";
    nearby = []; // free before sensor_post to avoid double-copy peak

    sk_av = sensor_post("avatars", arr);
}


// ================================================================
// Sensor: Environment
// ================================================================

do_env_scan()
{
    if (!s_env) return;

    string region   = llGetRegionName();
    list   pd       = llGetParcelDetails(llGetPos(),
                        [PARCEL_DETAILS_NAME, PARCEL_DETAILS_DESC]);
    string parcel      = llList2String(pd, 0);
    string parcel_desc = llList2String(pd, 1);
    pd = [];
    if (llStringLength(parcel_desc) > 400)
        parcel_desc = llGetSubString(parcel_desc, 0, 399);
    integer nav = llGetRegionAgentCount();
    string tod      = llGetEnv("time_of_day");
    string sun      = llGetEnv("sun_altitude");

    string data = "{";
    data += "\"region\":\"" + json_s(region) + "\",";
    data += "\"parcel\":\"" + json_s(parcel) + "\",";
    data += "\"parcel_desc\":\"" + json_s(parcel_desc) + "\",";
    data += "\"time_of_day\":\"" + json_s(tod) + "\",";
    data += "\"sun_altitude\":" + sun + ",";
    data += "\"avatar_count\":" + (string)nav;
    data += "}";

    last_parcel = parcel;
    sk_env = sensor_post("environment", data);
}


// ================================================================
// Sensor: Object Proximity (triggers LSL sensor sweep)
// ================================================================

do_object_scan()
{
    if (!s_objects) return;
    scan_mode = 3;
    llSensor("", NULL_KEY, PASSIVE | ACTIVE, 25.0, PI);
}


// ================================================================
// Sensor: Clothing Scanner (two-step: find agent, then attachments)
// ================================================================

do_clothing_scan()
{
    scan_mode = 1;
    llOwnerSay("Scanning for nearest avatar...");
    llSensor("", NULL_KEY, AGENT, 30.0, PI);
}


// ================================================================
// UI
// ================================================================

show_menu()
{
    llDialog(llGetOwner(),
        "Trixxie Sensory HUD\nAv:" + (string)s_avatars
        + " Ch:" + (string)s_chat
        + " En:" + (string)s_env
        + " Ob:" + (string)s_objects,
        ["Avatars", "Chat", "Environment", "Objects",
         "Scan Target", "Status", "Close"],
        UI_CHANNEL);
}

show_status()
{
    llOwnerSay(
        "=== Sensory HUD ===\n"
        + "Avatars : " + (string)s_avatars + "  [closest " + (string)AV_MAX + " in region]\n"
        + "Chat    : " + (string)s_chat    + "  [last 10 messages]\n"
        + "Env     : " + (string)s_env     + "\n"
        + "Objects : " + (string)s_objects + "\n"
        + "Region  : " + llGetRegionName()
    );
}


// ================================================================
// Sensor result processors (called from sensor() event)
// llDetected* are valid in user functions called within sensor()
// ================================================================

process_clothing_hits(integer num)
{
    integer idx;
    integer att_count;
    key     obj;
    list    det;
    integer apt;
    key     own;
    string  iname;
    string  creator;
    string  post_data;

    att_count = 0;
    post_data = "{\"target\":\"" + json_s(clo_name) + "\",\"items\":[";
    for (idx = 0; idx < num; idx++)
    {
        obj = llDetectedKey(idx);
        det = llGetObjectDetails(obj,
            [OBJECT_ATTACHED_POINT, OBJECT_OWNER, OBJECT_NAME, OBJECT_CREATOR]);
        apt = llList2Integer(det, 0);
        own = llList2Key(det, 1);
        if (apt > 0 && own == clo_target)
        {
            iname   = llList2String(det, 2);
            creator = llKey2Name(llList2Key(det, 3));
            if (att_count > 0) post_data += ",";
            post_data += "{\"item\":\"" + json_s(iname)
                       + "\",\"creator\":\"" + json_s(creator) + "\"}";
            att_count++;
        }
    }
    post_data += "]}";
    sk_clo = sensor_post("clothing", post_data);
    llOwnerSay("Scan sent: " + clo_name
        + " — " + (string)att_count + " attachment(s) found.");
    clo_target = NULL_KEY;
    clo_name   = "";
}

process_object_hits(integer num)
{
    integer idx;
    integer count;
    string  arr;

    if (num > 20) num = 20;

    arr = "[";
    count = 0;
    for (idx = 0; idx < num; idx++)
    {
        if (!(llDetectedType(idx) & 1))
        {
            float rd = (float)llRound(llVecDist(llDetectedPos(idx), llGetPos()) * 10) / 10.0;
            if (count > 0) arr += ",";
            arr += "{\"name\":\"" + json_s(llDetectedName(idx))
                 + "\",\"distance\":" + (string)rd
                 + ",\"scripted\":" + (string)((llDetectedType(idx) & 2) != 0) + "}";
            count++;
        }
    }
    arr += "]";

    if (count == 0) return;
    sk_obj = sensor_post("objects", arr);
}


// ================================================================
// default state
// ================================================================

default
{
    state_entry()
    {
        llListen(LISTEN_CHANNEL, "", NULL_KEY, "");
        llListen(0, "", NULL_KEY, "");
        llListen(UI_CHANNEL, "", llGetOwner(), "");
        llSetTimerEvent(TICK_SECS);

        last_region = llGetRegionName();
        last_parcel = llList2String(llGetParcelDetails(llGetPos(), [PARCEL_DETAILS_NAME]), 0);
        do_env_scan();
        llOwnerSay("Trixxie Sensory HUD active. Touch to open controls.");
    }

    touch_start(integer n)
    {
        if (llDetectedKey(0) == llGetOwner())
            show_menu();
    }

    timer()
    {
        tick++;

        // Region change → re-scan everything, reset tick counter
        string r = llGetRegionName();
        if (r != last_region)
        {
            last_region = r;
            last_parcel = "";   // cleared so the env scan below sets it fresh
            tick = 0;
            do_env_scan();
            if (s_objects) do_object_scan();
            return;
        }

        // Parcel border crossing → re-scan environment + objects
        string p = llList2String(llGetParcelDetails(llGetPos(), [PARCEL_DETAILS_NAME]), 0);
        if (p != last_parcel)
        {
            do_env_scan();          // sets last_parcel inside do_env_scan
            if (s_objects) do_object_scan();
        }

        // Avatar scan on interval
        if (s_avatars && (tick % AV_TICKS) == 0)
            do_avatar_scan();

        // Object scan on slow interval (position within parcel may have changed)
        if (s_objects && (tick % OBJ_TICKS) == 0)
            do_object_scan();

        // Environment slow interval — captures time-of-day drift without a border crossing
        if (s_env && (tick % ENV_TICKS) == 0)
            do_env_scan();
    }

    listen(integer channel, string name, key id, string message)
    {
        // ── Local chat: buffer all speakers, sent as context with /42 messages ──
        if (channel == 0)
        {
            if (s_chat)
            {
                string raw = name + ": " + message;
                if (llStringLength(raw) > 200)
                    raw = llGetSubString(raw, 0, 199);
                string entry = json_s(raw);
                nearby_chat += [entry];
                if (llGetListLength(nearby_chat) > CHAT_BUF_SIZE)
                    nearby_chat = llList2List(nearby_chat, -CHAT_BUF_SIZE, -1);
            }
            return;
        }

        // ── UI dialog responses ──
        if (channel == UI_CHANNEL)
        {
            if      (message == "Avatars")     { s_avatars = !s_avatars; show_menu(); }
            else if (message == "Chat")        { s_chat    = !s_chat;    show_menu(); }
            else if (message == "Environment") { s_env     = !s_env;     show_menu(); }
            else if (message == "Objects")
            {
                s_objects = !s_objects;
                if (s_objects) do_object_scan();
                show_menu();
            }
            else if (message == "Scan Target") { do_clothing_scan(); }
            else if (message == "Status")      { show_status(); }
            else if (message == "Close")       { }
            return;
        }

        // ── Channel 42: reply flow ──
        if (channel == LISTEN_CHANNEL)
        {
            if (reply_http != NULL_KEY)
            {
                llInstantMessage(id, "*still thinking...*");
                return;
            }

            reply_sender = id;

            string body = "{"
                + "\"user_id\":\""      + (string)id               + "\","
                + "\"display_name\":\"" + json_s(name)              + "\","
                + "\"message\":\""      + json_s(message)           + "\","
                + "\"region\":\""       + json_s(llGetRegionName()) + "\","
                + "\"channel\":"        + (string)LISTEN_CHANNEL    + ","
                + "\"grid\":\""         + GRID                      + "\","
                + "\"nearby_chat\":[";
            integer ci;
            integer cn = llGetListLength(nearby_chat);
            for (ci = 0; ci < cn; ci++)
            {
                if (ci > 0) body += ",";
                body += "\"" + llList2String(nearby_chat, ci) + "\"";
            }
            body += "]}";

            list p = [
                HTTP_METHOD, "POST",
                HTTP_MIMETYPE, "application/json",
                HTTP_VERIFY_CERT, TRUE
            ];
            if (SECRET != "")
                p += [HTTP_CUSTOM_HEADER, "X-SL-Secret", SECRET];

            reply_http = llHTTPRequest(SERVER_URL + "/sl/message", p, body);
        }
    }

    // ── LSL sensor results ──
    sensor(integer num)
    {
        // Step 1: Clothing scan — find nearest non-owner agent.
        // llSensor results are sorted nearest-first, so index 0 is closest.
        if (scan_mode == 1)
        {
            scan_mode = 0;
            if (num > 0 && llDetectedKey(0) != llGetOwner())
            {
                clo_target = llDetectedKey(0);
                clo_name   = llDetectedName(0);
                llOwnerSay("Found: " + clo_name + ". Scanning attachments...");
                scan_mode = 2;
                llSensor("", NULL_KEY, PASSIVE | ACTIVE, 30.0, PI);
            }
            else
            {
                llOwnerSay("No nearby avatars found to scan.");
            }
            return;
        }

        // Step 2: Clothing scan — collect attachments owned by clo_target
        if (scan_mode == 2)
        {
            scan_mode = 0;
            process_clothing_hits(num);
            return;
        }

        // Object proximity scan
        if (scan_mode == 3)
        {
            scan_mode = 0;
            process_object_hits(num);
        }
    }

    no_sensor()
    {
        if (scan_mode == 1 || scan_mode == 2)
            llOwnerSay("Nothing detected in range.");
        scan_mode  = 0;
        clo_target = NULL_KEY;
        clo_name   = "";
    }

    // ── HTTP responses ──
    http_response(key req, integer status, list meta, string body)
    {
        // Sensor posts — fire and forget, just clear the key
        if (req == sk_av)  { sk_av  = NULL_KEY; return; }
        if (req == sk_env) { sk_env = NULL_KEY; return; }
        if (req == sk_obj) { sk_obj = NULL_KEY; return; }
        if (req == sk_clo) { sk_clo = NULL_KEY; return; }

        // Reply flow
        if (req != reply_http) return;
        reply_http = NULL_KEY;

        key sender = reply_sender;
        reply_sender = NULL_KEY;

        if (status != 200)
        {
            llInstantMessage(sender, "Something went sideways on my end. Try again?");
            return;
        }

        string reply = llJsonGetValue(body, ["reply"]);
        if (reply != JSON_INVALID && reply != "")
            send_chunked(sender, reply);

        integer idx = 0;
        while (idx < 5)
        {
            string atype = llJsonGetValue(body, ["actions", idx, "action_type"]);
            if (atype == JSON_INVALID) return;
            string text = llJsonGetValue(body, ["actions", idx, "text"]);
            if (text == JSON_INVALID) text = "";
            if (atype == "emote" || atype == "im")
            {
                if (atype == "emote" && llGetSubString(text, 0, 0) != "*")
                    text = "*" + text + "*";
                llInstantMessage(sender, text);
            }
            idx++;
        }
    }
}
