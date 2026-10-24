-- Catalogs Deadzone: Rogue's data assets (missions, items, upgrades, ...) via the Asset Registry
-- and writes APCatalog.tsv next to the game exe, for building the Archipelago item/location tables.
local DELAY_MS = 40000
local OUT = "APCatalog.tsv"

local CLASSES = {
    "ValMissionData", "ValMissionGroup", "ValItemAsset", "ValPlayerUpgradeAsset", "ValPlayerUpgradeGroupConfig",
    "ValPlayerUpgradeConfig", "ValPlayerSynergyAsset", "ValLoadoutAsset", "ValActivityConfig", "ValSecurityLevel",
    "ValDungeonConfig", "ValDifficultyMapping", "ValAssetBundle", "ValFabricatorData", "ValBossBotData",
}
-- Classes whose assets get loaded so their fields can be read (others are listed by name only).
local LOAD = { ValMissionData = true, ValPlayerUpgradeAsset = true, ValItemAsset = true, ValPlayerSynergyAsset = true,
               ValMissionGroup = true, ValLoadoutAsset = true, ValSecurityLevel = true, ValPlayerUpgradeGroupConfig = true }

-- Upgrade group: activation flag, free levels, and which upgrade assets it contains.
function describeUpgradeGroup(obj)
    local parts = {}
    pcall(function() parts[#parts + 1] = "requireActivation=" .. tostring(obj.bRequireActivation) end)
    pcall(function() parts[#parts + 1] = "baseLevels=" .. tostring(obj.BaseUpgradeLevelsAvailable) end)
    local names = {}
    pcall(function()
        obj.UpgradeAssets:ForEach(function(_, soft)
            local s = "?"
            pcall(function() s = soft:get():ToString() end)
            if s == "?" then pcall(function() s = soft:get():GetFName():ToString() end) end
            names[#names + 1] = s
        end)
    end)
    parts[#parts + 1] = "upgrades=" .. table.concat(names, ",")
    return table.concat(parts, "\t")
end

local lines = {}
local function out(...) lines[#lines + 1] = table.concat({ ... }, "\t") end
local function log(msg)
    print("[APCatalog] " .. msg .. "\n")
    local f = io.open("APCatalog_status.txt", "a")
    if f then f:write(os.date("%H:%M:%S ") .. msg .. "\n"); f:close() end
end
local function flush()
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n"), "\n"); f:close() end
end

local function str(v)
    if v == nil then return "" end
    local ok, s = pcall(function() return v:ToString() end)
    if ok and s then return s end
    return tostring(v)
end
local function guid(g)
    local ok, s = pcall(function() return string.format("%08X-%08X-%08X-%08X", g.A & 0xFFFFFFFF, g.B & 0xFFFFFFFF, g.C & 0xFFFFFFFF, g.D & 0xFFFFFFFF) end)
    return ok and s or "?"
end
local function try(label, fn)
    local ok, err = pcall(fn)
    if not ok then log(label .. " FAILED: " .. tostring(err)) end
    return ok
end

local function getAssetsByClass(registry, getByClass, className)
    local results = {}
    local path = { PackageName = FName("/Script/Valhalla"), AssetName = FName(className) }
    local ok, err = pcall(function() getByClass(registry, path, results, true) end)
    if not ok then
        ok, err = pcall(function() registry:GetAssetsByClass(path, results, true) end)
    end
    if not ok then log("GetAssetsByClass(" .. className .. ") failed: " .. tostring(err)) end
    return results
end

local described = false
local function describe(label, v)
    local parts = { label .. ": type=" .. type(v) .. " tostring=" .. tostring(v) }
    if type(v) == "table" then
        for k, x in pairs(v) do parts[#parts + 1] = tostring(k) .. "=" .. type(x) .. ":" .. tostring(x) end
    end
    for _, f in ipairs({ "PackageName", "AssetName", "AssetClassPath", "PackagePath", "AssetClass" }) do
        local ok, x = pcall(function() return v[f] end)
        parts[#parts + 1] = f .. "->" .. (ok and (type(x) .. ":" .. tostring(x)) or ("ERR " .. tostring(x)))
    end
    log(table.concat(parts, " | "))
end

-- Out-param arrays can come back as a plain Lua table, a TArray wrapper, or a table keyed by the param name.
local function eachArray(arr, fn)
    if arr == nil then return end
    if type(arr) == "table" and arr.OutAssetData ~= nil then arr = arr.OutAssetData end
    local function unwrap(e)
        if type(e) == "userdata" or type(e) == "table" then
            local ok, inner = pcall(function() return e:get() end)
            if ok and inner ~= nil then return inner end
        end
        return e
    end
    local function visit(e)
        e = unwrap(e)
        if not described then described = true; describe("first element", e) end
        fn(e)
    end
    if type(arr) == "table" then
        if not described then describe("results table", arr) end
        for _, e in ipairs(arr) do visit(e) end
        return
    end
    arr:ForEach(function(_, e) visit(e) end)
end

local function describeMission(obj)
    local tiers = {}
    try("TierData", function()
        obj.TierData:ForEach(function(tier, data)
            local diffs = {}
            data:get().DifficultyData:ForEach(function(d, _) diffs[#diffs + 1] = tostring(d:get()) end)
            tiers[#tiers + 1] = "T" .. tostring(tier:get()) .. ":" .. table.concat(diffs, ",")
        end)
    end)
    local prereqs = {}
    try("MissionPrerequisites", function()
        obj.MissionPrerequisites:ForEach(function(_, m) prereqs[#prereqs + 1] = str(m:get():GetFName()) end)
    end)
    local milestones = {}
    try("MilestoneRewards", function()
        obj.MilestoneRewards:ForEach(function(k, v)
            local n = 0
            v:get().RewardMap:ForEach(function() n = n + 1 end)
            milestones[#milestones + 1] = tostring(k:get()) .. "(" .. n .. ")"
        end)
    end)
    local class = "?"
    pcall(function()
        local c = obj.MissionClass
        if c and c:IsValid() then class = str(c:GetFName()) end
    end)
    return "tiers=" .. table.concat(tiers, " ") .. "\tprereqs=" .. table.concat(prereqs, ",")
        .. "\tmilestones=" .. table.concat(milestones, ",") .. "\tmap=" .. str(obj.MapAbsolutePath)
        .. "\tclass=" .. class
end

local function run()
    log("starting")
    local helpers = StaticFindObject("/Script/AssetRegistry.Default__AssetRegistryHelpers")
    local registry, getByClass
    try("GetAssetRegistry", function() registry = helpers:GetAssetRegistry() end)
    if registry == nil or not registry:IsValid() then
        registry = FindFirstOf("AssetRegistryImpl")
        log("using FindFirstOf(AssetRegistryImpl): " .. tostring(registry and registry:IsValid()))
    end
    getByClass = StaticFindObject("/Script/AssetRegistry.AssetRegistry:GetAssetsByClass")
    log("registry=" .. tostring(registry and registry:GetFullName()) .. " fn=" .. tostring(getByClass and getByClass:IsValid()))

    out("class", "package", "asset", "item_id", "display_name", "extra")
    for _, cls in ipairs(CLASSES) do
        local assets = getAssetsByClass(registry, getByClass, cls)
        local count = 0
        eachArray(assets, function(ad)
            count = count + 1
            local pkg, name = str(ad.PackageName), str(ad.AssetName)
            local realClass = cls
            pcall(function() realClass = str(ad.AssetClassPath.AssetName) end)
            local id, display, extra = "", "", ""
            if LOAD[cls] then
                try("load " .. pkg, function()
                    local obj = LoadAsset(pkg .. "." .. name)
                    if obj and obj:IsValid() then
                        id = guid(obj.ItemId)
                        display = str(obj.DisplayName)
                        if realClass == "ValMissionData" then extra = describeMission(obj)
                        elseif realClass == "ValPlayerUpgradeGroupConfig" then extra = describeUpgradeGroup(obj)
                        elseif obj.Rarity ~= nil then
                            extra = "rarity=" .. tostring(obj.Rarity) .. "\tslot=" .. str(obj.EquipSlot.TagName)
                        end
                        -- ownership gate (what decides whether granting the item changes anything)
                        pcall(function() extra = extra .. "\town=" .. tostring(obj.bRequireOwnership) end)
                        pcall(function()
                            local n = 0
                            obj.UpgradeLevels:ForEach(function() n = n + 1 end)
                            extra = extra .. "\tlevels=" .. n
                        end)
                    end
                end)
            end
            out(realClass, pkg, name, id, display, extra)
        end)
        log(cls .. ": " .. count)
        flush()
    end
    log("ALL DONE (" .. (#lines - 1) .. " rows)")
end

log("loaded, cataloging in " .. DELAY_MS / 1000 .. "s")
ExecuteWithDelay(DELAY_MS, function()
    ExecuteInGameThread(function()
        local ok, err = pcall(run)
        if not ok then log("run FAILED: " .. tostring(err)) end
        flush()
    end)
end)
