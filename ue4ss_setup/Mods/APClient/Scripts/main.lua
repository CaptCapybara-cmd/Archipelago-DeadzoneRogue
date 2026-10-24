-- APClient v0.7.0: the in-game half of the Deadzone Rogue Archipelago client.
-- Talks to the Python client through files in Win64/APBridge (format: deadzone_rogue/bridge.py):
--   inbox.txt -> what to lock and grant     outbox_<session>.txt <- missions completed, save-wide totals, deaths
-- Received items and save-wide totals (sectors, kills, Scrap) are tracked per AP session and per game save slot in
-- APBridge/state_<session>_slot<n>.txt.
local BRIDGE = "APBridge/"
local MOD_VERSION = "0.7.0"
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

local sessionId = nil -- set from the inbox; events go to that session's own outbox

local function emit(line, quiet)
    if sessionId == nil then return end
    local f = io.open(BRIDGE .. "outbox_" .. sessionId .. ".txt", "a")
    if f then f:write(line .. "\n"); f:close() end
    if not quiet then log("sent: " .. line) end
end

local function nonDefault(className)
    for _, o in ipairs(FindAllOf(className) or {}) do
        if o:IsValid() and not str(o:GetFName()):find("Default__") then return o end
    end
end

-- On-screen messages, shown through the game's own text chat (the client RPC the server uses to deliver chat).
-- Only the in-game ValPlayerController has it (the main menu's controller doesn't), so messages sent before the
-- player is in the hub or a run wait in a queue.
local pendingNotes = {}

local function chatController()
    local valController = StaticFindObject("/Script/Valhalla.ValPlayerController")
    if valController == nil or not valController:IsValid() then return nil end
    for _, pc in ipairs(FindAllOf("PlayerController") or {}) do
        if pc:IsValid() and pc:IsLocalController() and pc:IsA(valController) then return pc end
    end
end

local function flushNotes()
    if #pendingNotes == 0 then return end
    local pc = chatController()
    if pc == nil then return end
    for _, message in ipairs(pendingNotes) do
        local ok, err = pcall(function()
            if not pc.bTextChatEnabled then pc.bTextChatEnabled = true end -- solo play keeps the chat box off
            pc:ClientReceiveTextChatMessage(pc.PlayerState, "[Archipelago] " .. message)
        end)
        log("chat: " .. message .. (ok and "" or ("  (not shown: " .. tostring(err) .. ")")))
    end
    pendingNotes = {}
end

local function notify(message)
    pendingNotes[#pendingNotes + 1] = message
    if #pendingNotes > 20 then table.remove(pendingNotes, 1) end
    flushNotes()
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
                zones = nil, missionZones = {}, zoneEntries = {}, notes = {}, deathlinks = {}, noBuy = {} }

local function parseInbox(text)
    local new = { locks = {}, byIndex = {}, maxIndex = -1, zones = nil, missionZones = {}, zoneEntries = {}, notes = {},
                  deathlinks = {}, noBuy = {} }
    for line in text:gmatch("[^\n]+") do
        local kind, rest = line:match("^(%S+)%s*(.*)$")
        if kind == "rev" then new.rev = rest
        elseif kind == "zones" then
            new.zones = {}
            for z in rest:gmatch("%d+") do new.zones[tonumber(z)] = true end
        elseif kind == "missionzone" then
            local key, z = rest:match("^(%S+) (%d+)$")
            if key then new.missionZones[key] = tonumber(z) end
        elseif kind == "zoneentry" then new.zoneEntries[rest] = true
        elseif kind == "noupgradebuy" then
            for k in rest:gmatch("%a+") do new.noBuy[k] = true end
        elseif kind == "session" then new.session = rest
        elseif kind == "goal" then new.goal = rest
        elseif kind == "lock" then new.locks[#new.locks + 1] = rest
        elseif kind == "note" then
            local id, text = rest:match("^(%d+) (.+)$")
            if id then new.notes[#new.notes + 1] = { id = tonumber(id), text = text } end
        elseif kind == "deathlink" then
            local id, mode, text = rest:match("^(%d+) (%S+) ?(.*)$")
            if id then new.deathlinks[#new.deathlinks + 1] = { id = tonumber(id), mode = mode, text = text } end
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

-- sectors / kills / scrap are save-wide running totals across every run on this session's save slot
local state = { key = nil, applied = -1, sectors = 0, kills = 0, scrap = 0, lastNote = 0, lastDeath = 0 }
local totalsDirty = false -- totals changed since they were last written to the outbox

local function stateFile() return BRIDGE .. "state_" .. state.key .. ".txt" end

local function loadState(key)
    state.key, state.applied, state.sectors, state.kills, state.scrap = key, -1, 0, 0, 0
    state.lastNote, state.lastDeath = 0, 0
    local text = readFile(stateFile())
    if text then
        state.applied = tonumber(text:match("applied (%-?%d+)")) or -1
        state.sectors = tonumber(text:match("sectors (%d+)") or text:match("rooms (%d+)")) or 0 -- "rooms" before 0.5.0
        state.kills = tonumber(text:match("kills (%d+)")) or 0
        state.scrap = tonumber(text:match("scrap (%d+)")) or 0
        state.lastNote = tonumber(text:match("lastnote (%d+)")) or 0
        state.lastDeath = tonumber(text:match("lastdeath (%d+)")) or 0
    end
    log(string.format("session %s: %d items applied before; %d sectors cleared, %d kills, %d Scrap gathered",
        key, state.applied + 1, state.sectors, state.kills, state.scrap))
end

local function saveState()
    local f = io.open(stateFile(), "w")
    if f then
        f:write(string.format("applied %d\nsectors %d\nkills %d\nscrap %d\nlastnote %d\nlastdeath %d\n",
            state.applied, state.sectors, state.kills, state.scrap, state.lastNote, state.lastDeath))
        f:close()
    end
end

-- Totals are written at most every few seconds (kills and Scrap pickups come in bursts).
local function flushTotals()
    if not totalsDirty then return end
    totalsDirty = false
    saveState()
    emit("sectors " .. state.sectors, true)
    emit("kills " .. state.kills, true)
    emit("scrap " .. state.scrap, true)
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

-- Upgrades whose levels come from Archipelago can't be bought: every level of their hub price group costs more
-- shards and Tech than anyone has. Groups are keyed by zone tag (verified: zone 1 = the 19 Tech upgrades,
-- zone 2 = the 40 superior items, zone 3 = synergies, never touched).
local PRICE_GROUPS = { tech = "Mission.Zone.1", superior = "Mission.Zone.2" }
local UNAFFORDABLE = 999999
local originalPrices = {} -- group name -> level -> { shards, values }
local pricesBlocked = {} -- group name -> true once blocked (the price config only exists once the hub has loaded)

local function forEachPriceGroup(fn)
    for _, cfg in ipairs(FindAllOf("ValPlayerUpgradeConfig") or {}) do
        if not str(cfg:GetFName()):find("Default__") then
            cfg.GroupConfigsByType:ForEach(function(tag, group) fn(str(tag:get().TagName), group:get()) end)
        end
    end
end

local function blockUpgradePurchases()
    local blocked = {}
    for kind, tag in pairs(PRICE_GROUPS) do
        if inbox.noBuy[kind] then blocked[tag] = kind end
    end
    if next(blocked) == nil then return end
    forEachPriceGroup(function(tag, group)
        if not blocked[tag] then return end
        local name = str(group:GetFName())
        originalPrices[name] = originalPrices[name] or {}
        group.UpgradeLevelPricing:ForEach(function(level, price)
            local p, lvl = price:get(), level:get()
            if originalPrices[name][lvl] == nil then
                local values = {}
                p.BasePrice.CurrencyData:ForEach(function(i, c) values[i] = c:get().Value end)
                originalPrices[name][lvl] = { shards = p.ShardCost, values = values }
            end
            p.ShardCost = UNAFFORDABLE
            p.BasePrice.CurrencyData:ForEach(function(_, c) c:get().Value = UNAFFORDABLE end)
        end)
        if not pricesBlocked[name] then log("upgrades can't be bought: " .. blocked[tag] .. " (" .. name .. ")") end
        pricesBlocked[name] = true
    end)
end

local function restoreUpgradePrices()
    if next(originalPrices) == nil then return end
    forEachPriceGroup(function(_, group)
        local saved = originalPrices[str(group:GetFName())]
        if saved == nil then return end
        group.UpgradeLevelPricing:ForEach(function(level, price)
            local orig = saved[level:get()]
            if orig then
                local p = price:get()
                p.ShardCost = orig.shards
                p.BasePrice.CurrencyData:ForEach(function(i, c) c:get().Value = orig.values[i] or c:get().Value end)
            end
        end)
    end)
    originalPrices, pricesBlocked = {}, {}
    log("upgrade prices back to normal")
end

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
    local ok, err = pcall(blockUpgradePurchases)
    if not ok then log("upgrade purchase block failed: " .. tostring(err)) end
end

local function restoreLocks()
    local n = 0
    for path, flag in pairs(originalFlags) do
        local a = asset(path)
        if a then a.bRequireOwnership = flag; n = n + 1 end
    end
    originalFlags = {}
    if n > 0 then log("restored " .. n .. " locked assets to normal") end
    local ok, err = pcall(restoreUpgradePrices)
    if not ok then log("restoring upgrade prices failed: " .. tostring(err)) end
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

-- Tech and superior upgrade levels are the upgrade asset's inventory count (superior items show one level more).
-- A level grant raises the count to its target; like AddInventoryCount above, the count lags, so a target set in
-- the last minute counts as reached (two copies arriving together must not stack).
local recentLevels = {} -- path -> { target, time }

local function topUp(inv, a, path, target)
    local have = inv:GetItemCount(a.ItemId)
    local recent = recentLevels[path]
    if recent and os.time() - recent.time < GRANT_SETTLE_S then have = math.max(have, recent.target) end
    if have >= target then return false end
    inv:AddInventoryCount(a.AssetId, target - have)
    recentLevels[path] = { target = target, time = os.time() }
    log(string.format("raised %s to %d (was %d)", str(a:GetFName()), target, have))
    return true
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
            elseif g.mode == "level" then
                local a = asset(g.path)
                if a and topUp(inv, a, g.path, g.amount) then added = added + 1 end
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
                elseif g.mode == "level" then
                    topUp(inv, a, g.path, g.amount)
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

-- Dev menu overrides (zone -> true/false), on top of the Zone Access items; only while gating is on.
local zoneOverride = {}

local function zoneIsOpen(zone)
    if inbox.zones == nil or zone == nil then return true end
    if zoneOverride[zone] ~= nil then return zoneOverride[zone] end
    return inbox.zones[zone] == true
end

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
    local open = ""
    for z = 1, 4 do if zoneIsOpen(z) then open = open .. z end end
    log("asked the game to rebuild mission options (zones open: " .. (inbox.zones == nil and "all, gating off" or open) .. ")")
    return true
end

-- Name of the local player's character, so only the player's own kills count.
local localPawn = nil
local function refreshLocalPawn()
    localPawn = nil
    pcall(function()
        for _, pc in ipairs(FindAllOf("PlayerController") or {}) do
            if pc:IsValid() and pc:IsLocalController() and pc.Pawn:IsValid() then localPawn = str(pc.Pawn:GetFName()) end
        end
    end)
end

local lastFlush = 0

local lastSlotSeen = nil -- for the heartbeat
local MAX_BACKLOG_NOTES = 5 -- after a long time away, only the latest few messages are posted

-- Item messages from the client (received / sent), posted to chat once each.
function showNewNotes()
    local fresh = {}
    for _, note in ipairs(inbox.notes) do
        if note.id > state.lastNote then fresh[#fresh + 1] = note end
    end
    if #fresh == 0 then return end
    for i = math.max(1, #fresh - MAX_BACKLOG_NOTES + 1), #fresh do notify(fresh[i].text) end
    state.lastNote = fresh[#fresh].id
    saveState()
end

local function tick()
    local now = os.time()
    if now - lastBeat >= 5 then
        -- line 1 is the time (all the client needs); the rest is for the launcher's status display
        local f = io.open(BRIDGE .. "heartbeat.txt", "w")
        if f then
            f:write(string.format("%d\nversion %s\nsession %s\nslot %s\nbound %s\n", now, MOD_VERSION,
                inbox.session or "-", lastSlotSeen or "-", tostring(onBoundSlot)))
            f:close()
        end
        lastBeat = now
    end
    flushNotes()

    local text = readFile(BRIDGE .. "inbox.txt")
    if text then
        local new = parseInbox(text)
        if new.rev ~= inbox.rev then
            if zonesSignature(new.zones) ~= zonesSignature(inbox.zones) then rebuildMissions = true end
            inbox = new
            sessionId = new.session
            lastEnsure = 0
            locksDirty = true
        end
    end
    handleDebug()
    if inbox.session == nil then return end

    local slot = activeSaveSlot()
    if slot == nil then return end
    lastSlotSeen = slot
    if slot ~= boundSlot(inbox.session, slot) then
        if onBoundSlot or warnedSlot ~= slot then
            restoreLocks()
            log("save slot " .. slot .. " isn't this Archipelago session's slot; doing nothing on it")
            warnedSlot = slot
        end
        onBoundSlot = false
        return
    end
    if not onBoundSlot then
        onBoundSlot = true
        locksDirty = true
        notify("connected: save slot " .. slot .. " is your Archipelago save")
    end
    if locksDirty then applyLocks(); locksDirty = false end -- cheap after the first time: assets are cached

    local key = inbox.session .. "_slot" .. slot
    if key ~= state.key then loadState(key); lastEnsure = 0 end
    refreshLocalPawn()
    showNewNotes()
    handleDeathLinks()
    if now - lastFlush >= 5 then lastFlush = now; flushTotals() end

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
    -- the upgrade price config loads with the hub, after the mod starts: keep trying until it's blocked
    if next(inbox.noBuy) ~= nil and next(pricesBlocked) == nil then
        local ok, err = pcall(blockUpgradePurchases)
        if not ok then log("upgrade purchase block failed: " .. tostring(err)) end
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

-- Save-wide objectives (only on the session's own save slot) ---------------------------------------------------
local SCRAP_ID = "F92B0D82-41C68D42-B990048B-2A1267DE" -- Item_Currency_Scrap

hook("/Script/Valhalla.ValGameState_SpaceDungeon:IncrementEncountersCleared", function(self, amount)
    if not onBoundSlot or state.key == nil then return end
    state.sectors = state.sectors + amount:get()
    totalsDirty = true
    flushTotals() -- sectors are rare, send right away
end)

hook("/Script/Valhalla.ValPlayerUpgradeComponent:OnBotKilled", function(self, victim, killer)
    if not onBoundSlot or state.key == nil or localPawn == nil then return end
    local k = nil
    pcall(function() k = str(killer:get():GetFName()) end)
    if k == localPawn then
        state.kills = state.kills + 1
        totalsDirty = true
    end
end)

-- Scrap gathered = every increase of the Scrap count; spending (decreases) doesn't count against it.
hook("/Script/Valhalla.ValPlayerUpgradeComponent:OnInventoryChanged", function(self, itemId, initial, old, new)
    if not onBoundSlot or state.key == nil or initial:get() then return end
    local g = itemId:get()
    local id = string.format("%08X-%08X-%08X-%08X", g.A & 0xFFFFFFFF, g.B & 0xFFFFFFFF, g.C & 0xFFFFFFFF, g.D & 0xFFFFFFFF)
    local gained = new:get() - old:get()
    if id == SCRAP_ID and gained > 0 then
        state.scrap = state.scrap + gained
        totalsDirty = true
    end
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

-- A zone's entry mission opens with its Zone Access even when the game's story order would keep it shut:
-- the option, its tiers and each tier's lowest difficulty (the game opens the next ones as they're beaten).
local function forceOpen(opt)
    local changed = 0
    if not opt.bAvailable then opt.bAvailable = true; changed = changed + 1 end
    opt.TierOptions:ForEach(function(_, t)
        local tier = t:get()
        if not tier.bAvailable then tier.bAvailable = true; changed = changed + 1 end
        local lowest = nil
        tier.DifficultyOptions:ForEach(function(_, d)
            local dd = d:get()
            if lowest == nil or dd.Difficulty < lowest.Difficulty then lowest = dd end
        end)
        if lowest ~= nil and not lowest.bAvailable then lowest.bAvailable = true; changed = changed + 1 end
    end)
    return changed
end

-- Returns how many options were changed.
local function applyGating(component)
    if inbox.zones == nil then return 0 end
    local changed = 0
    component.r_MissionOptions:ForEach(function(_, o)
        local opt = o:get()
        local key = missionKey(opt)
        local zone = inbox.missionZones[key]
        local zoneOpen = zoneIsOpen(zone)
        if zoneOpen and inbox.zoneEntries[key] then changed = changed + forceOpen(opt) end
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

-- Run state, DeathLink effects -----------------------------------------------------------------------------------

local SCRAP_PATH = "/Game/Items/Currencies/Item_Currency_Scrap.Item_Currency_Scrap"

local function guidKey(g)
    return string.format("%08X-%08X-%08X-%08X", g.A & 0xFFFFFFFF, g.B & 0xFFFFFFFF, g.C & 0xFFFFFFFF, g.D & 0xFFFFFFFF)
end

local function localPawnObject()
    local pc = chatController()
    if pc == nil then return nil end
    local pawn = pc.Pawn
    if pawn ~= nil and pawn:IsValid() then return pawn end
end

-- What the player picked up this run: transient inventory entries (the game drops them when the run ends), so
-- removing one never touches the save's permanent unlocks. Returns { asset, name, class, count } entries.
local function runItems(inv)
    local transient = {}
    inv.TransientItemIds:ForEach(function(_, g) transient[guidKey(g:get())] = true end)
    local items = {}
    inv.InventoryAssetMap:ForEach(function(k, v)
        local g = k:get()
        if transient[guidKey(g)] then
            local a = v:get()
            if a ~= nil and a:IsValid() then
                local count = inv:GetItemCount(g)
                if count > 0 then
                    items[#items + 1] = { asset = a, name = str(a.DisplayName), id = str(a:GetFName()),
                                          class = str(a:GetClass():GetFName()), count = count }
                end
            end
        end
    end)
    return items
end

local function pickRandom(list) if #list > 0 then return list[math.random(#list)] end end

-- Run pickups aren't inventory entries; they're lists on the player state, mirrored on the character:
--   r_PerkIds    - run items (Item_*)
--   r_AugmentIds - augments (Augment_*) and element perks (Perk_*_Parent)
-- Removing one from the list and re-sending it to the character drops its effect (verified for items).
local RUN_LISTS = {
    items = { field = "r_PerkIds", rep = "OnRep_PerkIds", loaded = "OnPerkAssetsLoaded",
              changed = "OnPerkIdsChanged", equipped = "EquippedPerkIds" },
    augments = { field = "r_AugmentIds", rep = "OnRep_AugmentIds", loaded = "OnAugmentAssetsLoaded",
                 changed = "OnAugmentIdsChanged", equipped = "EquippedAugmentIds" },
}

local function runIds(ps, list)
    local ids = {}
    ps[list.field]:ForEach(function(_, id)
        local v = id:get()
        ids[#ids + 1] = { type = str(v.PrimaryAssetType.Name), name = str(v.PrimaryAssetName) }
    end)
    return ids
end

local function names(ids)
    local t = {}
    for _, id in ipairs(ids) do t[#t + 1] = id.name end
    return table.concat(t, ", ")
end

-- Takes one copy of `victim` out of the run list and lets the character re-sync its effects.
local function removeRunEntry(ps, pawn, list, victim)
    local before = runIds(ps, list)
    local keep, removed = {}, false
    for _, id in ipairs(before) do
        if not removed and id.name == victim.name then
            removed = true
        else
            keep[#keep + 1] = { PrimaryAssetType = { Name = FName(id.type) }, PrimaryAssetName = FName(id.name) }
        end
    end
    ps[list.field] = keep
    pcall(function() ps[list.rep](ps) end)
    -- the HUD listens to the player state's "ids changed" event, which the game fires once the assets have loaded
    local okLoaded, errLoaded = pcall(function() ps[list.loaded](ps, keep) end)
    if not okLoaded then log(list.loaded .. " failed: " .. tostring(errLoaded)) end
    pcall(function() pawn[list.changed](pawn, keep) end)
    local after = runIds(ps, list)
    local equipped = {}
    pcall(function() pawn[list.equipped]:ForEach(function(_, id) equipped[#equipped + 1] = str(id:get().PrimaryAssetName) end) end)
    log(string.format("removed %s from %s: now [%s], character has [%s]", victim.name, list.field, names(after),
        table.concat(equipped, ", ")))
    return #after < #before
end

local function displayName(name)
    local shown = name
    pcall(function()
        local a = FindObject("ValItemAsset", name) or FindObject("ValPerkAsset", name)
        if a and a:IsValid() and str(a.DisplayName) ~= "" then shown = str(a.DisplayName) end
    end)
    shown = shown:gsub("_Parent$", ""):gsub("^Perk_", ""):gsub("^Item_", "")
    return shown
end

-- Loses a random entry of `list` whose asset name matches `pattern`.
local function loseRunEntry(list, pattern, nothing)
    local pc = chatController()
    local pawn = localPawnObject()
    if pc == nil or pawn == nil then return nil, "not in a run" end
    local ps = pc.PlayerState
    local candidates = {}
    for _, id in ipairs(runIds(ps, list)) do
        if id.name:find(pattern) then candidates[#candidates + 1] = id end
    end
    local victim = pickRandom(candidates)
    if victim == nil then return nil, nothing end
    local shown = displayName(victim.name)
    if not removeRunEntry(ps, pawn, list, victim) then return nil, "couldn't remove " .. shown end
    return shown
end

-- Each returns a short description of what happened, for the chat line.
local effects = {}

function effects.lose_perk()
    local name, why = loseRunEntry(RUN_LISTS.augments, "^Perk_", "no run perks to lose")
    return name and ("lost the perk " .. name) or why
end

function effects.lose_item()
    local name, why = loseRunEntry(RUN_LISTS.items, "^Item_", "no run items to lose")
    return name and ("lost " .. name) or why
end

function effects.lose_scrap(inv)
    local a = asset(SCRAP_PATH)
    if a == nil then return "Scrap asset not found" end
    local have = inv:GetItemCount(a.ItemId)
    local lose = have // 2
    if lose <= 0 then return "no Scrap to lose" end
    inv:RemoveInventoryCount(a.AssetId, lose)
    return string.format("lost %d Scrap (of %d)", lose, have)
end

function effects.take_damage()
    local pawn = localPawnObject()
    if pawn == nil then return "not in a run" end
    local health = pawn:GetTotalHealth()
    local left = math.max(1, math.floor(health * 0.25))
    pawn:SetHealth(left)
    return string.format("took heavy damage (%d -> %d health)", math.floor(health), left)
end

function effects.kill()
    local pawn = localPawnObject()
    if pawn == nil then return "not in a run" end
    pawn:Suicide({ TagName = FName("None") })
    return "was killed"
end

-- Not found a safe way to move the player back a room yet; it costs Scrap instead.
function effects.push_back_room(inv)
    return "push back isn't supported yet, so: " .. effects.lose_scrap(inv)
end

local function inRun()
    return localPawnObject() ~= nil and nonDefault("ValGameState_SpaceDungeon") ~= nil
end

local recentDeathLinkAt = 0 -- a kill from a DeathLink must not be reported back as our own death

local function applyDeathLink(mode, source)
    local effect = effects[mode]
    if effect == nil then return "unknown DeathLink mode " .. tostring(mode) end
    if not inRun() then return "DeathLink from " .. source .. " ignored: not in a run" end
    local inv = inventory()
    if inv == nil then return "inventory not ready" end
    recentDeathLinkAt = os.time()
    local ok, result = pcall(effect, inv)
    if not ok then return "DeathLink " .. mode .. " failed: " .. tostring(result) end
    return "DeathLink from " .. source .. ": " .. result
end

-- Deaths received through the client; each one is applied once (the last id is kept in the state file).
function handleDeathLinks()
    for _, d in ipairs(inbox.deathlinks) do
        if d.id > state.lastDeath then
            state.lastDeath = d.id
            saveState()
            notify(applyDeathLink(d.mode, d.text ~= "" and d.text or "another player"))
        end
    end
end

hook("/Script/Valhalla.ValMissionComponent:OnFrontierState", function(self, frontierState)
    -- EFrontierState::Died. Skipped right after a DeathLink kill, so deaths don't bounce between players.
    if onBoundSlot and frontierState:get() == 1 and os.time() - recentDeathLinkAt > 10 then
        emit("death " .. os.time())
    end
end)

-- Dev menu ---------------------------------------------------------------------------------------------------------
-- The launcher's DEV tab writes APBridge/debug.txt, one command per line: "<id> <command> <args...>" with ids
-- that only increase. Each is run once; results go to the chat and to APBridge/debug_log.txt.

local DEBUG_FILE, DEBUG_LOG = BRIDGE .. "debug.txt", BRIDGE .. "debug_log.txt"
local debugLastId = nil -- nil until the first read: commands already in the file when the game starts are skipped

local function debugReply(id, text)
    local f = io.open(DEBUG_LOG, "a")
    if f then
        for line in text:gmatch("[^\n]+") do f:write(id .. " " .. line .. "\n") end
        f:close()
    end
    log("dev: " .. text:gsub("\n", " | "))
end

local function statusLines()
    local lines = {}
    local function add(fmt, ...) lines[#lines + 1] = string.format(fmt, ...) end
    add("APClient v%s", MOD_VERSION)
    add("session: %s", inbox.session or "no client connected yet")
    add("save slot: %s (%s)", tostring(lastSlotSeen), onBoundSlot and "your Archipelago save" or "not bound")
    local zones = {}
    for z = 1, 4 do if zoneIsOpen(z) then zones[#zones + 1] = tostring(z) end end
    add("zones open: %s%s", inbox.zones == nil and "all (gating off)" or table.concat(zones, " "),
        next(zoneOverride) and " (dev overrides active)" or "")
    add("items applied: %d of %d received", state.applied + 1, inbox.maxIndex + 1)
    add("locks: %d assets", #inbox.locks)
    add("totals: %d sectors, %d kills, %d Scrap", state.sectors, state.kills, state.scrap)
    add("in a run: %s", inRun() and "yes" or "no")
    return lines
end

local function probeLines()
    local lines = {}
    local inv = inventory()
    if inv == nil then return { "inventory not ready" } end
    local pawn = localPawnObject()
    if pawn ~= nil then
        local ok, h = pcall(function() return pawn:GetTotalHealth() end)
        lines[#lines + 1] = "pawn " .. str(pawn:GetFName()) .. ", health " .. (ok and tostring(h) or ("? " .. tostring(h)))
    else
        lines[#lines + 1] = "no pawn"
    end
    local ok, items = pcall(runItems, inv)
    if not ok then return { lines[1], "run items failed: " .. tostring(items) } end
    lines[#lines + 1] = #items .. " run items:"
    for _, it in ipairs(items) do
        lines[#lines + 1] = string.format("  %s x%d  [%s] %s", it.id, it.count, it.class, it.name)
    end
    pcall(function()
        local all = FindAllOf("ValInventoryComponent") or {}
        local assetsKnown = 0
        inv.InventoryAssetMap:ForEach(function() assetsKnown = assetsKnown + 1 end)
        lines[#lines + 1] = string.format("%d inventory components; this one: %d transient ids, %d assets", #all,
            inv.TransientItemIds:GetArrayNum(), assetsKnown)
        for _, c in ipairs(all) do lines[#lines + 1] = "  inv " .. c:GetFullName() end
    end)
    local pc = chatController()
    local ps = pc and pc.PlayerState
    if ps ~= nil and ps:IsValid() then
        for _, field in ipairs({ "r_PerkIds", "r_AugmentIds", "r_SynergyIds", "r_SpecialtyIds" }) do
            local ok2, err = pcall(function()
                local ids = {}
                ps[field]:ForEach(function(_, id)
                    local v = id:get()
                    ids[#ids + 1] = str(v.PrimaryAssetType.Name) .. ":" .. str(v.PrimaryAssetName)
                end)
                lines[#lines + 1] = field .. ": " .. table.concat(ids, ", ")
            end)
            if not ok2 then lines[#lines + 1] = field .. " failed: " .. tostring(err) end
        end
        pcall(function()
            -- where each run perk/item lives in the inventory, if anywhere
            local transient = {}
            inv.TransientItemIds:ForEach(function(_, g) transient[guidKey(g:get())] = true end)
            local byName = {}
            inv.InventoryAssetMap:ForEach(function(k, v)
                local a = v:get()
                if a ~= nil and a:IsValid() then
                    byName[str(a:GetFName())] = { guid = k:get(), asset = a, transient = transient[guidKey(k:get())] }
                end
            end)
            ps.r_PerkIds:ForEach(function(_, id)
                local name = str(id:get().PrimaryAssetName)
                local e = byName[name]
                if e then
                    lines[#lines + 1] = string.format("  %s: in inventory x%d%s [%s]", name, inv:GetItemCount(e.guid),
                        e.transient and " (transient)" or "", str(e.asset:GetClass():GetFName()))
                else
                    local a = nil
                    pcall(function() a = StaticFindObject("/Game/Items/" .. name) end)
                    lines[#lines + 1] = "  " .. name .. ": not in the inventory"
                end
            end)
        end)
        pcall(function()
            local ok3, ids = pcall(function()
                local out = {}
                ps.r_ActivatedIds:ForEach(function(_, g) out[#out + 1] = guidKey(g:get()) end)
                return out
            end)
            lines[#lines + 1] = "r_ActivatedIds: " .. (ok3 and table.concat(ids, ", ") or tostring(ids))
            local pawn2 = localPawnObject()
            if pawn2 then
                local eq2 = {}
                pawn2.EquippedPerkIds:ForEach(function(_, id) eq2[#eq2 + 1] = str(id:get().PrimaryAssetName) end)
                lines[#lines + 1] = "character EquippedPerkIds: " .. table.concat(eq2, ", ")
            end
        end)
        pcall(function()
            local eq = {}
            ps.r_Equipment:ForEach(function(_, s)
                local slot = s:get()
                eq[#eq + 1] = tostring(slot.SlotId) .. "=" .. str(slot.Item.AssetId.PrimaryAssetName) .. " x" .. tostring(slot.Item.Quantity)
            end)
            lines[#lines + 1] = "r_Equipment: " .. table.concat(eq, ", ")
        end)
    end
    return lines
end

local commands = {}

function commands.status() return table.concat(statusLines(), "\n") end
function commands.probe() return table.concat(probeLines(), "\n") end
function commands.chat(args) notify(args); return "posted" end

function commands.deathlink(args)
    return applyDeathLink(args:match("^(%S+)"), "the dev menu")
end

function commands.mission(args)
    local key, difficulty = args:match("^(%S+) (%d+)$")
    if key == nil then return "usage: mission <key> <difficulty>" end
    if not onBoundSlot then return "not on the Archipelago save slot" end
    emit("mission " .. key .. " " .. difficulty)
    return "sent a completion of " .. key .. " on difficulty " .. difficulty
end

function commands.add(args)
    local what, n = args:match("^(%a+) (%-?%d+)$")
    if what == nil or state[what] == nil or what == "applied" then return "usage: add sectors|kills|scrap <n>" end
    if not onBoundSlot or state.key == nil then return "not on the Archipelago save slot" end
    state[what] = math.max(0, state[what] + tonumber(n))
    totalsDirty = true
    flushTotals()
    return string.format("%s total is now %d", what, state[what])
end

-- Grants straight into the save, outside Archipelago (for testing locks and grants).
function commands.grant(args)
    local inv = inventory()
    if inv == nil then return "inventory not ready" end
    local a = asset(args)
    if a == nil then return "could not load " .. args end
    inv:AddInventoryCount(a.AssetId, 1)
    return "granted " .. str(a.DisplayName) .. " (outside Archipelago)"
end

function commands.revoke(args)
    local inv = inventory()
    if inv == nil then return "inventory not ready" end
    local a = asset(args)
    if a == nil then return "could not load " .. args end
    local have = inv:GetItemCount(a.ItemId)
    if have <= 0 then return str(a.DisplayName) .. " isn't owned" end
    inv:RemoveInventoryCount(a.AssetId, have)
    recentlyGranted[args] = nil
    return "removed " .. str(a.DisplayName) .. " (Archipelago grants it back within " .. ENSURE_EVERY_S .. " s if received)"
end

function commands.zone(args)
    local z, how = args:match("^(%d) (%a+)$")
    z = tonumber(z)
    if z == nil or (how ~= "open" and how ~= "close" and how ~= "reset") then return "usage: zone <1-4> open|close|reset" end
    if inbox.zones == nil then return "zone gating is off in this seed" end
    if how == "reset" then zoneOverride[z] = nil else zoneOverride[z] = (how == "open") end
    rebuildMissions = true
    return "zone " .. z .. ": " .. (how == "reset" and "back to Archipelago" or how)
end

-- Drops one of the game's own perk-choice pickups at the player. The game's generator picks what's in it, and it
-- can use up the run's single augment offer (an augment room later in the run may then be empty).
function commands.bundle()
    local pc, pawn = chatController(), localPawnObject()
    if pc == nil or pawn == nil or not inRun() then return "not in a run" end
    local augments = nonDefault("ValAugmentComponent")
    if augments == nil then return "no augment component in this level" end
    augments:SpawnAugmentBundle(pc.PlayerState, pawn, {})
    return "spawned a perk bundle at your feet"
end

-- Tech upgrade and superior item levels: what the upgrade component reports next to the inventory count.
function commands.upgrades(args)
    local inv = inventory()
    local comp = nonDefault("ValPlayerUpgradeComponent")
    if inv == nil or comp == nil then return "inventory or upgrade component not ready" end
    local lines = {}
    for _, a in ipairs(FindAllOf("ValPlayerUpgradeAsset") or {}) do
        local name = str(a:GetFName())
        if a:IsValid() and not name:find("Default__") and (args == "" or name:find(args)) then
            local okLevel, level = pcall(function() return comp:GetUpgradeLevelById(a.ItemId) end)
            lines[#lines + 1] = string.format("%s: level %s, inventory %d", name,
                okLevel and tostring(level) or ("? " .. tostring(level)), inv:GetItemCount(a.ItemId))
        end
    end
    table.sort(lines)
    return #lines .. " upgrades\n" .. table.concat(lines, "\n")
end

-- Test: raise one upgrade by n levels through the inventory, e.g. "uplevel Upgrade_MaxShield 2".
function commands.uplevel(args)
    local name, n = args:match("^(%S+) (%d+)$")
    if name == nil then return "usage: uplevel <asset name> <levels>" end
    local inv = inventory()
    local comp = nonDefault("ValPlayerUpgradeComponent")
    if inv == nil or comp == nil then return "inventory or upgrade component not ready" end
    local a = nil
    for _, o in ipairs(FindAllOf("ValPlayerUpgradeAsset") or {}) do
        if o:IsValid() and str(o:GetFName()) == name then a = o end
    end
    if a == nil then return name .. " isn't loaded" end
    local before = comp:GetUpgradeLevelById(a.ItemId)
    local ok, err = pcall(function() comp:AddUpgradeValue(a.ItemId, tonumber(n)) end)
    local after = comp:GetUpgradeLevelById(a.ItemId)
    return string.format("%s: AddUpgradeValue %s; level %s -> %s right away, inventory %d", name,
        ok and "ok" or ("failed: " .. tostring(err)), tostring(before), tostring(after), inv:GetItemCount(a.ItemId))
end

-- The upgrade price groups: their tag, config and price per level (to see what the purchase block touches).
function commands.upgradegroups()
    local lines = {}
    for _, cfg in ipairs(FindAllOf("ValPlayerUpgradeConfig") or {}) do
        if not str(cfg:GetFName()):find("Default__") then
            cfg.GroupConfigsByType:ForEach(function(tag, group)
                local g = group:get()
                local prices = {}
                pcall(function()
                    g.UpgradeLevelPricing:ForEach(function(level, price)
                        local p = price:get()
                        local cost = {}
                        p.BasePrice.CurrencyData:ForEach(function(_, c)
                            cost[#cost + 1] = tostring(c:get().Value) .. " " .. str(c:get().Asset:GetFName())
                        end)
                        prices[#prices + 1] = string.format("L%d: %d shards + %s", level:get(), p.ShardCost,
                            table.concat(cost, " + "))
                    end)
                end)
                local members = {}
                pcall(function()
                    g.UpgradeAssets:ForEach(function(_, soft)
                        local s = soft:get()
                        local ok, path = pcall(function() return s:ToString() end)
                        if not ok then ok, path = pcall(function() return str(s:Get():GetFName()) end) end
                        members[#members + 1] = ok and tostring(path):match("([%w_]+)$") or "?"
                    end)
                end)
                lines[#lines + 1] = string.format("%s -> %s: %d upgrades [%s]: %s", str(tag:get().TagName),
                    str(g:GetFName()), #members, table.concat(members, ", "), table.concat(prices, "; "))
            end)
        end
    end
    return #lines .. " groups\n" .. table.concat(lines, "\n")
end

function commands.regate() rebuildMissions = true; return "rebuilding mission options" end
function commands.relock() applyLocks(); return "locks reapplied" end
function commands.unlock() restoreLocks(); return "locks lifted until the next relock, mission start or reload" end

function handleDebug()
    local text = readFile(DEBUG_FILE)
    if text == nil then debugLastId = debugLastId or 0; return end
    local maxSeen = debugLastId or 0
    for line in text:gmatch("[^\n]+") do
        local id, name, args = line:match("^(%d+) (%S+) ?(.*)$")
        id = tonumber(id)
        if id and debugLastId and id > debugLastId then
            local command = commands[name]
            local ok, result = true, "unknown command " .. name
            if command then ok, result = pcall(command, args) end
            result = ok and tostring(result) or ("error: " .. tostring(result))
            debugReply(id, result)
            if name ~= "status" and name ~= "probe" then notify("[dev] " .. result) end
        end
        if id and id > maxSeen then maxSeen = id end
    end
    debugLastId = maxSeen
end

RegisterKeyBind(Key.F10, function() ExecuteInGameThread(function()
    for _, line in ipairs(statusLines()) do notify(line) end
end) end)

log("loaded (bridge folder: " .. BRIDGE .. ")")
notify("APClient v" .. MOD_VERSION .. " loaded") -- shown once the player is in the hub or a run
