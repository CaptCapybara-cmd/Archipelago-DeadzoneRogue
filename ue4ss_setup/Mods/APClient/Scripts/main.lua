-- APClient: the in-game half of the Deadzone Rogue Archipelago client.
-- Talks to the Python client through files in Win64/APBridge (format: deadzone_rogue/bridge.py):
--   inbox.txt  -> what to lock and grant      outbox.txt <- missions completed, rooms cleared, deaths
-- Received items are tracked per AP session and per game save slot in APBridge/state_<session>_slot<n>.txt.
local BRIDGE = "APBridge/"
local POLL_MS = 1000
local ENSURE_EVERY_S = 30       -- re-check one-time unlocks against the save this often
local GRANTS_PER_TICK = 25      -- spread big batches over a few ticks to avoid hitches

local function log(msg) print("[APClient] " .. msg .. "\n") end

local function str(v)
    if v == nil then return "nil" end
    local ok, s = pcall(function() return v:ToString() end)
    if ok and s then return s end
    return tostring(v)
end

local function readFile(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local text = f:read("a")
    f:close()
    return text
end

local function emit(line)
    local f = io.open(BRIDGE .. "outbox.txt", "a")
    if f then f:write(line .. "\n"); f:close() end
    log("sent: " .. line)
end

local function nonDefault(className)
    for _, o in ipairs(FindAllOf(className) or {}) do
        if o:IsValid() and not str(o:GetFName()):find("Default__") then return o end
    end
end

-- Assets are cached so the lock flag set on them survives (an unreferenced asset can be reloaded with defaults).
local assets = {}
local function asset(path)
    local a = assets[path]
    if a and a:IsValid() then return a end
    a = LoadAsset(path)
    if a and a:IsValid() then assets[path] = a; return a end
    log("could not load " .. path)
end

-- Inbox ---------------------------------------------------------------------------------------------------------

local inbox = { rev = nil, session = nil, goal = nil, locks = {}, byIndex = {}, maxIndex = -1,
                zones = nil, missionZones = {} }

local function parseInbox(text)
    local new = { locks = {}, byIndex = {}, maxIndex = -1, zones = nil, missionZones = {} }
    for line in text:gmatch("[^\n]+") do
        local kind, rest = line:match("^(%S+)%s*(.*)$")
        if kind == "rev" then new.rev = rest
        elseif kind == "zones" then
            new.zones = {}
            for z in rest:gmatch("%d+") do new.zones[tonumber(z)] = true end
        elseif kind == "missionzone" then
            local key, z = rest:match("^(%S+) (%d+)$")
            if key then new.missionZones[key] = tonumber(z) end
        elseif kind == "session" then new.session = rest
        elseif kind == "goal" then new.goal = rest
        elseif kind == "lock" then new.locks[#new.locks + 1] = rest
        elseif kind == "grant" then
            local index, mode, amount, path = rest:match("^(%d+) (%S+) (%d+) (%S+)$")
            if index then
                index = tonumber(index)
                new.byIndex[index] = new.byIndex[index] or {}
                table.insert(new.byIndex[index], { mode = mode, amount = tonumber(amount), path = path })
                if index > new.maxIndex then new.maxIndex = index end
            end
        end
    end
    return new
end

-- Per-session, per-save-slot progress -----------------------------------------------------------------------------

local state = { key = nil, applied = -1, rooms = 0 }

local function stateFile() return BRIDGE .. "state_" .. state.key .. ".txt" end

local function loadState(key)
    state.key, state.applied, state.rooms = key, -1, 0
    local text = readFile(stateFile())
    if text then
        state.applied = tonumber(text:match("applied (%-?%d+)")) or -1
        state.rooms = tonumber(text:match("rooms (%d+)")) or 0
    end
    log(string.format("session %s: %d items applied before, %d rooms cleared", key, state.applied + 1, state.rooms))
end

local function saveState()
    local f = io.open(stateFile(), "w")
    if f then f:write(string.format("applied %d\nrooms %d\n", state.applied, state.rooms)); f:close() end
end

-- The active save slot, or nil until the save system has finished loading (before that it reports slot 0,
-- which would point at the wrong save).
local function activeSaveSlot()
    local slot = nil
    pcall(function()
        local saves = nonDefault("ValSaveGameSubsystem")
        if saves and saves.bSubsystemLoadComplete then slot = tostring(saves:GetActiveSlot()) end
    end)
    return slot
end

-- Each AP session is bound to the first save slot it is used on; the mod does nothing on any other slot,
-- so a player's normal saves are never changed.
local function boundSlot(session, slot)
    local path = BRIDGE .. "binding_" .. session .. ".txt"
    local text = readFile(path)
    if text and text:match("%d+") then return text:match("%d+") end
    local f = io.open(path, "w")
    if f then f:write(slot); f:close() end
    log("bound this Archipelago session to save slot " .. slot)
    return slot
end

-- Locks and grants -----------------------------------------------------------------------------------------------

local originalFlags = {} -- path -> bRequireOwnership before we touched it

local function applyLocks()
    local n = 0
    for _, path in ipairs(inbox.locks) do
        local a = asset(path)
        if a then
            if originalFlags[path] == nil then originalFlags[path] = a.bRequireOwnership end
            a.bRequireOwnership = true -- owned assets stay usable; unowned ones stop being offered
            n = n + 1
        end
    end
    if #inbox.locks > 0 then log(string.format("locked %d/%d normally-free assets", n, #inbox.locks)) end
end

local function restoreLocks()
    local n = 0
    for path, flag in pairs(originalFlags) do
        local a = asset(path)
        if a then a.bRequireOwnership = flag; n = n + 1 end
    end
    originalFlags = {}
    if n > 0 then log("restored " .. n .. " locked assets to normal") end
end

local function inventory()
    local inv = nonDefault("ValInventoryComponent")
    if inv == nil then return nil end
    local ready = true
    pcall(function() ready = inv:IsComponentReady() end)
    return ready and inv or nil
end

-- AddInventoryCount isn't reflected by GetItemCount straight away, so a path granted in the last minute
-- counts as owned; otherwise two passes in quick succession grant it twice.
local GRANT_SETTLE_S = 60
local recentlyGranted = {}

local function owns(inv, a, path)
    if recentlyGranted[path] and os.time() - recentlyGranted[path] < GRANT_SETTLE_S then return true end
    return inv:GetItemCount(a.ItemId) >= 1
end

local function grantOnce(inv, a, path)
    inv:AddInventoryCount(a.AssetId, 1)
    recentlyGranted[path] = os.time()
    log("granted " .. str(a.DisplayName) .. " (" .. str(a:GetFName()) .. ")")
end

-- One-time unlocks: grant anything received that the save doesn't have (idempotent, so safe to repeat).
local function ensureUnlocks(inv)
    local added = 0
    for index = 0, inbox.maxIndex do
        for _, g in ipairs(inbox.byIndex[index] or {}) do
            if g.mode == "once" then
                local a = asset(g.path)
                if a and not owns(inv, a, g.path) then
                    grantOnce(inv, a, g.path)
                    added = added + 1
                end
            end
        end
    end
    return added
end

-- Repeatable grants (currency): applied once per received index, tracked in the state file.
local function applyNewGrants(inv)
    local done = 0
    while state.applied < inbox.maxIndex and done < GRANTS_PER_TICK do
        local index = state.applied + 1
        for _, g in ipairs(inbox.byIndex[index] or {}) do
            local a = asset(g.path)
            if a then
                if g.mode == "add" then
                    inv:AddInventoryCount(a.AssetId, g.amount)
                    log(string.format("granted %d x %s", g.amount, str(a.DisplayName)))
                elseif not owns(inv, a, g.path) then
                    grantOnce(inv, a, g.path)
                end
            end
        end
        state.applied = index
        done = done + 1
    end
    if done > 0 then saveState() end
end

-- Main loop ------------------------------------------------------------------------------------------------------

local lastEnsure, lastBeat = 0, 0
local onBoundSlot = false   -- true while the active save is this session's slot
local locksDirty = false
local warnedSlot = nil
local rebuildMissions = true -- ask the game to rebuild mission options (on load and when open zones change)

local function zonesSignature(zones)
    if zones == nil then return "off" end
    local s = ""
    for z = 1, 9 do if zones[z] then s = s .. z end end
    return s
end

-- The game rebuilds its mission options from scratch (all its own rules); the post-hook then re-applies
-- zone gating. This is how a newly received Zone Access opens up without leaving the hub.
local function requestMissionRebuild(inv)
    local component = nonDefault("ValMissionComponent")
    if component == nil or not component:IsValid() then return false end
    component:UpdateHostMissionOptions(inv)
    log("asked the game to rebuild mission options (zones open: " .. zonesSignature(inbox.zones) .. ")")
    return true
end

local function tick()
    local now = os.time()
    if now - lastBeat >= 5 then
        local f = io.open(BRIDGE .. "heartbeat.txt", "w")
        if f then f:write(tostring(now)); f:close() end
        lastBeat = now
    end

    local text = readFile(BRIDGE .. "inbox.txt")
    if text then
        local new = parseInbox(text)
        if new.rev ~= inbox.rev then
            if zonesSignature(new.zones) ~= zonesSignature(inbox.zones) then rebuildMissions = true end
            inbox = new
            lastEnsure = 0
            locksDirty = true
        end
    end
    if inbox.session == nil then return end

    local slot = activeSaveSlot()
    if slot == nil then return end
    if slot ~= boundSlot(inbox.session, slot) then
        if onBoundSlot or warnedSlot ~= slot then
            restoreLocks()
            log("save slot " .. slot .. " isn't this Archipelago session's slot; doing nothing on it")
            warnedSlot = slot
        end
        onBoundSlot = false
        return
    end
    if not onBoundSlot then onBoundSlot = true; locksDirty = true end
    if locksDirty then applyLocks(); locksDirty = false end -- cheap after the first time: assets are cached

    local key = inbox.session .. "_slot" .. slot
    if key ~= state.key then loadState(key); lastEnsure = 0 end

    local inv = inventory()
    if inv == nil then return end
    if rebuildMissions then
        local ok, done = pcall(requestMissionRebuild, inv)
        if not ok then log("mission rebuild error: " .. tostring(done)) end
        if not ok or done then rebuildMissions = false end
    end
    if now - lastEnsure >= ENSURE_EVERY_S then
        lastEnsure = now
        ensureUnlocks(inv)
    end
    applyNewGrants(inv)
end

LoopAsync(POLL_MS, function()
    ExecuteInGameThread(function()
        local ok, err = pcall(tick)
        if not ok then log("tick error: " .. tostring(err)) end
    end)
    return false
end)

-- Checks ---------------------------------------------------------------------------------------------------------

local function hook(path, fn)
    local ok, err = pcall(function()
        RegisterHook(path, function(ctx, ...)
            local args = { ... }
            local ok2, err2 = pcall(fn, ctx:get(), table.unpack(args))
            if not ok2 then log("handler error for " .. path .. ": " .. tostring(err2)) end
        end)
    end)
    if not ok then log("HOOK FAILED " .. path .. ": " .. tostring(err)) end
end

hook("/Script/Valhalla.ValMissionComponent:OnMissionCompleted", function(self, mission)
    if not onBoundSlot then return end -- other save slots never send checks
    local p = mission:get().r_MissionParameters
    emit("mission " .. str(p.MissionData:GetFName()) .. " " .. tostring(p.Difficulty))
end)

hook("/Script/Valhalla.ValGameState_SpaceDungeon:IncrementEncountersCleared", function(self, amount)
    if not onBoundSlot or state.key == nil then return end -- rooms only count on the session's own save slot
    state.rooms = state.rooms + amount:get()
    saveState()
    emit("rooms " .. state.rooms)
end)

hook("/Script/Valhalla.ValMissionComponent:OnFrontierState", function(self, frontierState)
    if onBoundSlot and frontierState:get() == 1 then emit("death " .. os.time()) end -- EFrontierState::Died
end)

-- Zone gating ----------------------------------------------------------------------------------------
-- Mission options are built by the game (story order, "beat Normal before Hard") into
-- UValMissionComponent.r_MissionOptions; for missions in zones without Zone Access we turn bAvailable off.
local DEBUG_GATING = false -- true: log every gating pass with the full mission list (F9 always logs)

-- Missions are identified by their MissionId GUID (stored inline in the option). Never go through
-- option.MissionData here: it can still be null while the hub loads, and touching it crashes inside UE4SS.
local function missionKey(option)
    local g = option.MissionId
    return string.format("%08X-%08X-%08X-%08X", g.A & 0xFFFFFFFF, g.B & 0xFFFFFFFF, g.C & 0xFFFFFFFF, g.D & 0xFFFFFFFF)
end

local function describeOptions(component)
    local lines = {}
    component.r_MissionOptions:ForEach(function(_, o)
        local opt = o:get()
        local diffs = {}
        opt.TierOptions:ForEach(function(_, t)
            t:get().DifficultyOptions:ForEach(function(_, d)
                local dd = d:get()
                diffs[#diffs + 1] = tostring(dd.Difficulty) .. (dd.bAvailable and "+" or "-") .. (dd.bCompleted and "c" or "")
            end)
        end)
        lines[#lines + 1] = string.format("%s %s [%s]", missionKey(opt), opt.bAvailable and "open" or "LOCKED", table.concat(diffs, " "))
    end)
    return lines
end

-- Returns how many options were changed.
local function applyGating(component)
    if inbox.zones == nil then return 0 end
    local changed = 0
    component.r_MissionOptions:ForEach(function(_, o)
        local opt = o:get()
        local zone = inbox.missionZones[missionKey(opt)]
        local zoneOpen = inbox.zones == nil or zone == nil or inbox.zones[zone]
        if not zoneOpen and opt.bAvailable then opt.bAvailable = false; changed = changed + 1 end
        opt.TierOptions:ForEach(function(_, t)
            local tier = t:get()
            if not zoneOpen and tier.bAvailable then tier.bAvailable = false; changed = changed + 1 end
            tier.DifficultyOptions:ForEach(function(_, d)
                local dd = d:get()
                if not zoneOpen and dd.bAvailable then dd.bAvailable = false; changed = changed + 1 end
            end)
        end)
    end)
    return changed
end

local function gate(source, component)
    if not onBoundSlot then return end
    component = component or nonDefault("ValMissionComponent")
    if component == nil or not component:IsValid() then return end
    local changed = applyGating(component)
    if DEBUG_GATING and (changed > 0 or source == "F9") then
        log(string.format("gating via %s: %d changed", source, changed))
        for _, line in ipairs(describeOptions(component)) do log("  " .. line) end
    end
    if changed > 0 then pcall(function() component:OnRep_MissionOptions() end) end -- refresh listeners/UI
end

local gatePending = false
for _, fn in ipairs({ "UpdateHostMissionOptions", "OnRep_MissionOptions", "OnMissionOptionDataLoaded",
                      "GetMissionOptions", "BuildMissionDetailsForPlayer", "RequestMissionParameters",
                      "ServerRequestMissionParameters", "LoadMissionOptionData" }) do
    local path = "/Script/Valhalla.ValMissionComponent:" .. fn
    hook(path, function(self)
        if DEBUG_GATING and fn ~= "GetMissionOptions" then log("probe: " .. fn .. " fired") end
        if fn == "UpdateHostMissionOptions" or fn == "OnMissionOptionDataLoaded" or fn == "GetMissionOptions" then
            -- run after the game has finished its own update, on the component the hook was called on;
            -- GetMissionOptions fires on every UI read, so at most one pending gate at a time
            if gatePending then return end
            gatePending = true
            ExecuteWithDelay(250, function() ExecuteInGameThread(function()
                gatePending = false
                local ok, err = pcall(gate, fn, self)
                if not ok then log("gate error: " .. tostring(err)) end
            end) end)
        end
    end)
end
RegisterKeyBind(Key.F9, function() ExecuteInGameThread(function() gate("F9") end) end)

-- Locks are re-applied when a mission starts, in case an asset was reloaded in between.
hook("/Script/Valhalla.ValMissionComponent:OnMissionReady", function(self, mission)
    if onBoundSlot then applyLocks() end
end)

log("loaded (bridge folder: " .. BRIDGE .. ")")
