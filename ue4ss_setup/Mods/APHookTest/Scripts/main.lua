-- Live test of the Archipelago hook candidates in Deadzone: Rogue.
-- Logs mission / encounter / boss / inventory events to APHookTest.log (next to the game exe).
-- Test actions: F6 = grant test items via AddInventoryCount, F7 = force-complete the current mission.
-- AUTO: once a mission has been in progress for GRANT_AFTER_S, run F6; FORCE_COMPLETE_AFTER_S later, run F7.
local AUTO = false
local GRANT_AFTER_S = 20
local FORCE_COMPLETE_AFTER_S = 40 -- leaves time for the 7-step grant battery (4 s per step)

-- Items granted by the test: a currency and a permanent unlock.
local TEST_GRANTS = {
    { path = "/Game/Items/Currencies/Item_Currency_Scrap.Item_Currency_Scrap", count = 500 },
    { path = "/Game/Items/Unlocks/ItemUnlock_PlasmaElement.ItemUnlock_PlasmaElement", count = 1 },
}

local function log(msg)
    local line = os.date("%H:%M:%S ") .. msg
    print("[APHookTest] " .. msg .. "\n")
    local f = io.open("APHookTest.log", "a")
    if f then f:write(line .. "\n"); f:close() end
end

local function str(v)
    if v == nil then return "nil" end
    local ok, s = pcall(function() return v:ToString() end)
    if ok and s then return s end
    ok, s = pcall(function() return v:GetFullName() end)
    if ok and s then return s end
    return tostring(v)
end

local function guid(g)
    local ok, s = pcall(function()
        return string.format("%08X-%08X-%08X-%08X", g.A & 0xFFFFFFFF, g.B & 0xFFFFFFFF, g.C & 0xFFFFFFFF, g.D & 0xFFFFFFFF)
    end)
    return ok and s or "?"
end

local function describeParams(p)
    local parts = {}
    pcall(function() parts[#parts + 1] = "missionId=" .. guid(p.MissionId) end)
    pcall(function() parts[#parts + 1] = "tier=" .. tostring(p.Tier) end)
    pcall(function() parts[#parts + 1] = "difficulty=" .. tostring(p.Difficulty) end)
    pcall(function() parts[#parts + 1] = "data=" .. str(p.MissionData:GetFName()) end)
    pcall(function() parts[#parts + 1] = "name=" .. str(p.MissionData.DisplayName) end)
    return table.concat(parts, " ")
end

local function describeMission(m)
    if m == nil or not m:IsValid() then return "<invalid mission>" end
    local s = str(m:GetFName())
    pcall(function() s = s .. " status=" .. tostring(m.r_MissionStatus) end)
    pcall(function() s = s .. " " .. describeParams(m.r_MissionParameters) end)
    return s
end

local function hook(path, fn)
    local ok, err = pcall(function()
        RegisterHook(path, function(ctx, ...)
            local args = { ... }
            local ok2, err2 = pcall(fn, ctx:get(), table.unpack(args))
            if not ok2 then log("handler error for " .. path .. ": " .. tostring(err2)) end
        end)
    end)
    log((ok and "hooked " or "HOOK FAILED ") .. path .. (ok and "" or (": " .. tostring(err))))
end

-- Finds the local player's inventory component (skips class default objects).
local function inventory()
    local all = FindAllOf("ValInventoryComponent")
    if all == nil then return nil end
    for _, c in ipairs(all) do
        if c:IsValid() and not str(c:GetFName()):find("Default__") then return c end
    end
end

local function currentMission()
    local all = FindAllOf("ValMission")
    if all == nil then return nil end
    for _, m in ipairs(all) do
        if m:IsValid() and not str(m:GetFName()):find("Default__") then return m end
    end
end

-- Locations ------------------------------------------------------------------------------------

hook("/Script/Valhalla.ValMissionComponent:OnMissionCompleted", function(self, mission)
    log("LOCATION mission completed (component): " .. describeMission(mission:get()))
end)
hook("/Script/Valhalla.ValMissionComponent:OnMissionFailed", function(self, mission)
    log("mission FAILED (component): " .. describeMission(mission:get()))
end)
hook("/Script/Valhalla.ValMissionComponent:OnMissionReady", function(self, mission)
    log("mission ready: " .. describeMission(mission:get()))
end)
hook("/Script/Valhalla.ValMission:SetCompleted", function(self)
    log("AValMission::SetCompleted on " .. describeMission(self))
end)
hook("/Script/Valhalla.ValMission:ForceComplete", function(self)
    log("AValMission::ForceComplete on " .. describeMission(self))
end)
hook("/Script/Valhalla.ValGameState_SpaceDungeon:IncrementEncountersCleared", function(self, amount)
    log("LOCATION encounters cleared +" .. tostring(amount:get()))
end)
hook("/Script/Valhalla.ValGameState_SpaceDungeon:BroadcastBossDied", function(self, boss)
    log("LOCATION boss died: " .. str(boss:get()))
end)
hook("/Script/Valhalla.ValMissionComponent:OnFrontierState", function(self, state)
    log("frontier state -> " .. tostring(state:get()))
end)

-- Items: every inventory change the upgrade component is told about (bound to the inventory delegate)
hook("/Script/Valhalla.ValPlayerUpgradeComponent:OnInventoryChanged", function(self, itemId, initial, old, new)
    if initial:get() then return end -- skip the flood of initial values on load
    log("inventory changed: item=" .. guid(itemId:get()) .. " " .. tostring(old:get()) .. " -> " .. tostring(new:get()))
end)
hook("/Script/Valhalla.ValInventoryComponent:AddInventoryCount", function(self, assetId, count)
    local a = assetId:get()
    log("AddInventoryCount called: " .. str(a.PrimaryAssetType.Name) .. ":" .. str(a.PrimaryAssetName) .. " x" .. tostring(count:get()))
end)

-- Test actions ---------------------------------------------------------------------------------

local function grantTest()
    local inv = inventory()
    if inv == nil then log("grant test: no ValInventoryComponent found"); return end
    log("grant test using " .. str(inv))
    for _, g in ipairs(TEST_GRANTS) do
        local ok, err = pcall(function()
            local asset = LoadAsset(g.path)
            if asset == nil or not asset:IsValid() then error("LoadAsset failed") end
            local before = inv:GetItemCount(asset.ItemId)
            inv:AddInventoryCount(asset.AssetId, g.count)
            local after = inv:GetItemCount(asset.ItemId)
            log(string.format("GRANT %s (%s, id %s): count %s -> %s (requested +%d)",
                str(asset.DisplayName), str(asset:GetFName()), guid(asset.ItemId), tostring(before), tostring(after), g.count))
        end)
        if not ok then log("GRANT FAILED for " .. g.path .. ": " .. tostring(err)) end
    end
end

-- Tries each candidate grant path in turn, 4 s apart, reading counts back before and after each one.
local SCRAP = "/Game/Items/Currencies/Item_Currency_Scrap.Item_Currency_Scrap"
local PLASMA = "/Game/Items/Unlocks/ItemUnlock_PlasmaElement.ItemUnlock_PlasmaElement"
local UPGRADE_HEALTH_NAME = "Maximum Health"

local function counts(inv)
    local s, p = "?", "?"
    pcall(function() s = tostring(inv:GetItemCount(LoadAsset(SCRAP).ItemId)) end)
    pcall(function() p = tostring(inv:GetItemCount(LoadAsset(PLASMA).ItemId)) end)
    local pending = 0
    pcall(function() inv.PendingInventoryMap:ForEach(function() pending = pending + 1 end) end)
    return "scrap=" .. s .. " plasma=" .. p .. " pendingEntries=" .. pending
end

local function cheat()
    local all = FindAllOf("ValCheatComponent")
    if all == nil then return nil end
    for _, c in ipairs(all) do
        if c:IsValid() and not str(c:GetFName()):find("Default__") then return c end
    end
end

local function grantBattery()
    local inv = inventory()
    if inv == nil then log("battery: no inventory component"); return end
    local scrap, plasma = LoadAsset(SCRAP), LoadAsset(PLASMA)
    local scrapGuid = guid(scrap.ItemId)
    local attempts = {
        { "AddInventoryCount(Scrap AssetId, 500)", function() inv:AddInventoryCount(scrap.AssetId, 500) end },
        { "AddInventoryCount(Plasma AssetId, 1)", function() inv:AddInventoryCount(plasma.AssetId, 1) end },
        { "Cheat AddCurrency('Scrap', 500)", function() cheat():AddCurrency(FName("Scrap"), 500) end },
        { "Cheat AddCurrency('Item_Currency_Scrap', 500)", function() cheat():AddCurrency(FName("Item_Currency_Scrap"), 500) end },
        { "Cheat AddItemCount('ItemUnlock_PlasmaElement', 1)", function() cheat():AddItemCount(FName("ItemUnlock_PlasmaElement"), 1) end },
        { "Cheat AddItemCount(<scrap guid>, 500)", function() cheat():AddItemCount(FName(scrapGuid), 500) end },
        { "Cheat ActivateUpgrade('" .. UPGRADE_HEALTH_NAME .. "' lookup, 1)", function()
            for _, u in ipairs(FindAllOf("ValPlayerUpgradeAsset") or {}) do
                if str(u.DisplayName) == UPGRADE_HEALTH_NAME then
                    cheat():ActivateUpgrade(str(u.AssetId.PrimaryAssetType.Name) .. ":" .. str(u.AssetId.PrimaryAssetName), 1)
                    return
                end
            end
            error("upgrade asset not loaded")
        end },
    }
    log("battery start: cheat component = " .. str(cheat()) .. "; " .. counts(inv))
    local i = 0
    local function step()
        i = i + 1
        if i > #attempts then log("battery done: " .. counts(inv)); return end
        local name, fn = attempts[i][1], attempts[i][2]
        local before = counts(inv)
        local ok, err = pcall(fn)
        log(string.format("[%d] %s -> %s | before %s | now %s", i, name, ok and "called" or ("ERROR " .. tostring(err)), before, counts(inv)))
        ExecuteWithDelay(4000, function() ExecuteInGameThread(function()
            log(string.format("[%d] after 4s: %s", i, counts(inv)))
            step()
        end) end)
    end
    step()
end

-- (grantBattery is no longer bound; F8 now toggles Plasma parent perk ownership, see below)

local function forceComplete()
    local m = currentMission()
    if m == nil then log("force complete: no mission actor found"); return end
    log("force completing " .. describeMission(m))
    local ok, err = pcall(function() m:ForceComplete() end)
    if not ok then log("ForceComplete FAILED: " .. tostring(err)) end
end

RegisterKeyBind(Key.F6, function() ExecuteInGameThread(grantTest) end)
RegisterKeyBind(Key.F7, function() ExecuteInGameThread(forceComplete) end)

if AUTO then
    local seenSince = nil
    local granted, completed = false, false
    LoopAsync(2000, function()
        ExecuteInGameThread(function()
            local m = currentMission()
            local inProgress = false
            pcall(function() inProgress = (m ~= nil and m.r_MissionStatus == 0) end)
            if not inProgress then seenSince = nil; return end
            if seenSince == nil then
                seenSince = os.time(); granted, completed = false, false
                log("AUTO: mission in progress: " .. describeMission(m))
            end
            local t = os.time() - seenSince
            if not granted and t >= GRANT_AFTER_S then granted = true; grantBattery() end
            if granted and not completed and t >= GRANT_AFTER_S + FORCE_COMPLETE_AFTER_S then completed = true; forceComplete() end
        end)
        return false -- keep looping
    end)
end

-- Perk A/B test (F9): does owning "Element Unlock: Plasma" control whether Plasma perks are offered?
-- Rolls perk offers with the game's own GenerateAugmentItems with Plasma owned, removes the unlock and
-- rolls again, restores it, then spawns a real perk-choice pickup at the player for a visual check.
local PERK_AUTO = false     -- run once, PERK_AFTER_S into each mission (off: it rolls weapon augments, not element perks)
local PERK_AFTER_S = 15
local PERK_ROLLS = 40

local function nonDefault(className)
    for _, o in ipairs(FindAllOf(className) or {}) do
        if o:IsValid() and not str(o:GetFName()):find("Default__") then return o end
    end
end

local function playerState()
    local pc = nonDefault("BP_ValPlayerController_Dungeon_C") or nonDefault("PlayerController")
    local ps = pc and pc.PlayerState
    if ps and ps:IsValid() then return ps, pc end
end

-- Iterates an out-param array whichever shape UE4SS hands back.
local function eachOut(arr, fn)
    if arr == nil then return end
    local function unwrap(e)
        local ok, inner = pcall(function() return e:get() end)
        if ok and inner ~= nil then return inner end
        return e
    end
    if type(arr) == "table" then
        for _, e in ipairs(arr) do fn(unwrap(e)) end
    else
        arr:ForEach(function(_, e) fn(unwrap(e)) end)
    end
end

-- "Perk_Plasma_Child1" -> "Plasma"
local function family(assetName)
    return assetName:match("^Perk_([^_]+)") or assetName
end

local function rollPerks(augments, ps, label)
    local tally, offers, firstErr = {}, 0, nil
    for _ = 1, PERK_ROLLS do
        local out = {}
        local ok, err = pcall(function() augments:GenerateAugmentItems(ps, out) end)
        if not ok then firstErr = firstErr or tostring(err) end
        eachOut(out, function(item)
            offers = offers + 1
            local name = "?"
            pcall(function() name = str(item.AssetId.PrimaryAssetName) end)
            local fam = family(name)
            tally[fam] = (tally[fam] or 0) + 1
        end)
    end
    local parts = {}
    for fam, n in pairs(tally) do parts[#parts + 1] = fam .. "=" .. n end
    table.sort(parts)
    log(string.format("PERK %s: %d rolls, %d offers; Plasma=%d | %s%s", label, PERK_ROLLS, offers, tally["Plasma"] or 0,
        table.concat(parts, " "), firstErr and (" | first error: " .. firstErr) or ""))
    return tally["Plasma"] or 0
end

local function perkTest()
    local inv = inventory()
    local augments = nonDefault("ValAugmentComponent")
    local ps, pc = playerState()
    log("PERK test: inventory=" .. str(inv) .. " augments=" .. str(augments) .. " playerState=" .. str(ps))
    if not (inv and augments and ps) then log("PERK test aborted: missing component"); return end
    local plasma = LoadAsset(PLASMA)
    local function plasmaCount() return inv:GetItemCount(plasma.ItemId) end

    pcall(function()
        local n = 0
        augments.AugmentConfig.AvailableAssets:ForEach(function() n = n + 1 end)
        log("PERK config: " .. str(augments.AugmentConfig) .. " availableAssets=" .. n)
    end)

    if plasmaCount() < 1 then inv:AddInventoryCount(plasma.AssetId, 1) end
    local withPlasma = rollPerks(augments, ps, "WITH unlock (count=" .. plasmaCount() .. ")")

    inv:RemoveInventoryCount(plasma.AssetId, plasmaCount())
    ExecuteWithDelay(3000, function() ExecuteInGameThread(function()
        local withoutPlasma = rollPerks(augments, ps, "WITHOUT unlock (count=" .. plasmaCount() .. ")")
        inv:AddInventoryCount(plasma.AssetId, 1)
        ExecuteWithDelay(3000, function() ExecuteInGameThread(function()
            log(string.format("PERK verdict: Plasma offered %d times with the unlock, %d without -> %s; unlock restored to %d",
                withPlasma, withoutPlasma,
                (withPlasma > 0 and withoutPlasma == 0) and "UNLOCK CONTROLS PLASMA PERKS"
                    or (withPlasma == 0 and withoutPlasma == 0) and "Plasma never offered (inconclusive)"
                    or "unlock does NOT gate Plasma perks", plasmaCount()))
            -- Visual check: spawn real perk-choice pickups at the player until one contains a Plasma perk (max 4).
            local pawn = pc.Pawn
            for i = 1, 4 do
                local ok, err = pcall(function() augments:SpawnAugmentBundle(ps, pawn, {}) end)
                if not ok then log("SpawnAugmentBundle FAILED: " .. tostring(err)); break end
            end
            ExecuteWithDelay(1500, function() ExecuteInGameThread(function()
                for _, b in ipairs(FindAllOf("ValPickup_Bundle") or {}) do
                    if b:IsValid() and not str(b:GetFName()):find("Default__") then
                        local names = {}
                        pcall(function() b.BundleItems:ForEach(function(_, it) names[#names + 1] = str(it:get().AssetId.PrimaryAssetName) end) end)
                        log("PERK pickup " .. str(b:GetFName()) .. ": " .. table.concat(names, ", "))
                    end
                end
            end) end)
        end) end)
    end) end)
end

-- (perkTest is no longer bound: it drained the run's augment offer; F9 now toggles the Plasma unlock, see below)

if PERK_AUTO then
    local runFor = nil
    local since = nil
    LoopAsync(2000, function()
        ExecuteInGameThread(function()
            local m = currentMission()
            local inProgress = false
            pcall(function() inProgress = (m ~= nil and m.r_MissionStatus == 0) end)
            if not inProgress then since = nil; return end
            local key = str(m:GetFName())
            if since == nil then since = os.time() end
            if runFor ~= key and os.time() - since >= PERK_AFTER_S then runFor = key; perkTest() end
        end)
        return false
    end)
end

-- Element perk observation ---------------------------------------------------------------------
-- Logs the contents of every real perk-choice bundle the game spawns (BP_Pickup_Bundle_Perks_C and the
-- other bundle types), so normal play shows whether Plasma perks get offered.
local seenBundles = {}
local function bundleItems(b)
    local names = {}
    pcall(function() b.BundleItems:ForEach(function(_, it) names[#names + 1] = str(it:get().AssetId.PrimaryAssetName) end) end)
    return names
end
LoopAsync(1500, function()
    ExecuteInGameThread(function()
        for _, b in ipairs(FindAllOf("ValPickup_Bundle") or {}) do
            if b:IsValid() then
                local key = str(b:GetFName())
                local names = (not key:find("Default__")) and bundleItems(b) or {}
                local signature = table.concat(names, ",")
                -- log new bundles and any change in contents (rerolls)
                if #names > 0 and seenBundles[key] ~= signature then
                    local rerolled = seenBundles[key] ~= nil
                    do
                        seenBundles[key] = signature
                        if rerolled then key = key .. " (REROLLED)" end
                        local plasma = false
                        for _, n in ipairs(names) do if n:find("Plasma") then plasma = true end end
                        log("BUNDLE spawned " .. key .. " group=" .. str(b.ItemGroupType.TagName) .. ": "
                            .. table.concat(names, ", ") .. (plasma and "   <-- PLASMA" or ""))
                    end
                end
            end
        end
    end)
    return false
end)
hook("/Script/Valhalla.ValPickup_Bundle:RerollItems", function(self)
    log("BUNDLE reroll on " .. str(self:GetFName()))
end)

-- F10: live gating fields on the Plasma perk, a comparison perk, and the unlock item.
local function tags(container)
    local out = {}
    pcall(function() container.GameplayTags:ForEach(function(_, t) out[#out + 1] = str(t:get().TagName) end) end)
    return "[" .. table.concat(out, ",") .. "]"
end
local function gatingFields()
    for _, path in ipairs({
        "/Game/Items/Perks/Perk_Plasma_Parent.Perk_Plasma_Parent",
        "/Game/Items/Perks/Perk_Plasma_Child1.Perk_Plasma_Child1",
        "/Game/Items/Perks/Perk_Fire_Parent.Perk_Fire_Parent",
        "/Game/Items/Perks/Perk_Psionic_Parent.Perk_Psionic_Parent",
        PLASMA,
    }) do
        local ok, err = pcall(function()
            local a = LoadAsset(path)
            local extra = ""
            pcall(function() extra = " augmentType=" .. str(a.AugmentType.TagName) end)
            log(string.format("FIELDS %s: requireOwnership=%s gameplayTags=%s allowedLootTags=%s%s",
                str(a:GetFName()), tostring(a.bRequireOwnership), tags(a.GameplayTags), tags(a.AllowedLootTags), extra))
        end)
        if not ok then log("FIELDS failed for " .. path .. ": " .. tostring(err)) end
    end
    pcall(function()
        local gm = nonDefault("ValGameMode")
        log("FIELDS game mode dynamic loot types: " .. tags(gm.DynamicLootTypes))
    end)
end
RegisterKeyBind(Key.F10, function() ExecuteInGameThread(gatingFields) end)

-- F11: report ownership of the unlock items and the gated perks. F4: grant ownership of Perk_Plasma_Parent itself.
local PERK_PLASMA = "/Game/Items/Perks/Perk_Plasma_Parent.Perk_Plasma_Parent"
local OWNERSHIP = {
    PLASMA, PERK_PLASMA,
    "/Game/Items/Unlocks/ItemUnlock_PsionicElement.ItemUnlock_PsionicElement", "/Game/Items/Perks/Perk_Psionic_Parent.Perk_Psionic_Parent",
    "/Game/Items/Unlocks/ItemUnlock_RadiationElement.ItemUnlock_RadiationElement", "/Game/Items/Perks/Perk_Radiation_Parent.Perk_Radiation_Parent",
}
local function ownership()
    local inv = inventory()
    if inv == nil then log("OWN: no inventory component"); return end
    local parts = {}
    for _, path in ipairs(OWNERSHIP) do
        pcall(function()
            local a = LoadAsset(path)
            parts[#parts + 1] = str(a:GetFName()) .. "=" .. tostring(inv:GetItemCount(a.ItemId))
        end)
    end
    log("OWN " .. table.concat(parts, " "))
end
RegisterKeyBind(Key.F11, function() ExecuteInGameThread(ownership) end)

-- F2: spawn a bundle through the game's own augment/perk generator at the player, after logging how
-- the generator decides between augment and perk bundles. (Test slot only: it changes this run's offers.)
local function spawnPerkBundle()
    local augments = nonDefault("ValAugmentComponent")
    local ps, pc = playerState()
    if not (augments and ps and pc) then log("SPAWN: missing augment component or player"); return end
    pcall(function()
        local cfg = augments.AugmentConfig
        local map = {}
        cfg.BundleTypesByAugmentType:ForEach(function(k, v) map[#map + 1] = str(k:get().TagName) .. "->" .. str(v:get().TagName) end)
        local levels = {}
        cfg.ConfigsByLevel:ForEach(function(lvl, lc)
            local odds = {}
            lc:get().SelectionChancesByType:ForEach(function(t, c) odds[#odds + 1] = str(t:get().TagName) .. "=" .. tostring(c:get()) end)
            levels[#levels + 1] = "L" .. tostring(lvl:get()) .. "{" .. table.concat(odds, " ") .. "}"
        end)
        log("SPAWN config " .. str(cfg:GetFName()) .. " selectionCount=" .. tostring(cfg.SelectionCount)
            .. " bundleTypes=[" .. table.concat(map, ", ") .. "] levels=" .. table.concat(levels, " "))
    end)
    local ok, err = pcall(function() augments:SpawnAugmentBundle(ps, pc.Pawn, {}) end)
    log("SPAWN SpawnAugmentBundle -> " .. (ok and "called (bundle contents follow from the logger)" or ("ERROR " .. tostring(err))))
end
RegisterKeyBind(Key.F2, function() ExecuteInGameThread(spawnPerkBundle) end)

-- F9 toggles ownership of the Plasma unlock item, F8 toggles ownership of the Plasma parent perk.
-- Each reports ownership 3 s later, so F2 draws can be compared with and without each one.
local function toggleOwnership(path)
    local inv, a = inventory(), LoadAsset(path)
    local n = inv:GetItemCount(a.ItemId)
    if n > 0 then
        inv:RemoveInventoryCount(a.AssetId, n)
        log("TOGGLE removed " .. str(a:GetFName()) .. " (was " .. n .. ")")
    else
        inv:AddInventoryCount(a.AssetId, 1)
        log("TOGGLE granted " .. str(a:GetFName()))
    end
    ExecuteWithDelay(3000, function() ExecuteInGameThread(ownership) end)
end
RegisterKeyBind(Key.F9, function() ExecuteInGameThread(function() toggleOwnership(PLASMA) end) end)
RegisterKeyBind(Key.F8, function() ExecuteInGameThread(function() toggleOwnership(PERK_PLASMA) end) end)

-- F5: lock/unlock a DEFAULT perk at runtime by flipping its bRequireOwnership flag (Fire is free by default).
-- Locked = flag true and not owned; F2 draws should then never offer Fire.
local PERK_FIRE = "/Game/Items/Perks/Perk_Fire_Parent.Perk_Fire_Parent"
local fireRef = nil -- keep a reference so the asset isn't unloaded and reloaded with its default flag
RegisterKeyBind(Key.F5, function() ExecuteInGameThread(function()
    local inv, a = inventory(), LoadAsset(PERK_FIRE)
    fireRef = a
    a.bRequireOwnership = not a.bRequireOwnership
    log(string.format("LOCK Perk_Fire_Parent bRequireOwnership=%s owned=%s", tostring(a.bRequireOwnership), tostring(inv:GetItemCount(a.ItemId))))
end) end)

-- F3: grant the perk reroll unlock ("Intentional Fate") once, then report rerolls available on bundles in the world.
local REROLL_PERK = "/Game/Items/Unlocks/ItemUnlock_RerollPerk.ItemUnlock_RerollPerk"
local function rerollReport()
    local inv, a = inventory(), LoadAsset(REROLL_PERK)
    log("REROLL unlock " .. str(a.DisplayName) .. " count=" .. tostring(inv:GetItemCount(a.ItemId)))
    for _, b in ipairs(FindAllOf("ValPickup_Bundle") or {}) do
        if b:IsValid() and not str(b:GetFName()):find("Default__") then
            local n = "?"
            pcall(function() n = tostring(b:GetRerollsRemaining()) end)
            log("REROLL " .. str(b:GetFName()) .. " rerollsRemaining=" .. n)
        end
    end
end
RegisterKeyBind(Key.F3, function() ExecuteInGameThread(function()
    local inv, a = inventory(), LoadAsset(REROLL_PERK)
    if inv:GetItemCount(a.ItemId) < 1 then inv:AddInventoryCount(a.AssetId, 1) end
    ExecuteWithDelay(3000, function() ExecuteInGameThread(rerollReport) end)
end) end)
RegisterKeyBind(Key.F4, function() ExecuteInGameThread(function()
    local inv, a = inventory(), LoadAsset(PERK_PLASMA)
    if inv:GetItemCount(a.ItemId) < 1 then inv:AddInventoryCount(a.AssetId, 1) end
    ExecuteWithDelay(3000, function() ExecuteInGameThread(ownership) end)
end) end)

log("APHookTest loaded (AUTO=" .. tostring(AUTO) .. ", PERK_AUTO=" .. tostring(PERK_AUTO) .. ", bundle logging on, F10 = gating fields, F11 = ownership, F4 = own Perk_Plasma_Parent)")
