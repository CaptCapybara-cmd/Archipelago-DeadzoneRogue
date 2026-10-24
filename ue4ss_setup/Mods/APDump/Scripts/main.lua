-- Runs UE4SS's dumpers once the game has had time to reach the main menu.
-- The built-in Keybinds mod still works for re-dumping mid-run (Ctrl+J objects, Ctrl+H headers).
local DELAY_MS = 45000

local function mark(msg)
    print("[APDump] " .. msg .. "\n")
    local f = io.open("APDump_status.txt", "a")
    if f then f:write(os.date("%H:%M:%S ") .. msg .. "\n"); f:close() end
end

mark("loaded, dumping in " .. DELAY_MS / 1000 .. "s")
ExecuteWithDelay(DELAY_MS, function()
    ExecuteInGameThread(function()
        mark("DumpUSMAP start");      DumpUSMAP();      mark("DumpUSMAP done")
        mark("DumpAllObjects start"); DumpAllObjects(); mark("DumpAllObjects done")
        mark("GenerateSDK start");    GenerateSDK();    mark("GenerateSDK done")
        mark("ALL DONE")
    end)
end)
