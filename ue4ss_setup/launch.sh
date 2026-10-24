# Launch Deadzone: Rogue windowed at 1280x720. Waits for any previous instance to fully exit first,
# because starting while Steam still sees the old one running makes the new one quit immediately.
ROOT="/c/Program Files (x86)/Steam/steamapps/common/Deadzone Rogue"
taskkill //F //IM DeadzoneSteam-Win64-Shipping.exe >/dev/null 2>&1
while tasklist | grep -qi "DeadzoneSteam"; do sleep 1; done
sleep 5
rm -f "$ROOT/Valhalla/Binaries/Win64/APDump_status.txt" "$ROOT/Valhalla/Binaries/Win64/ue4ss/APDump_status.txt"
cd "$ROOT" && cmd //c start "" "DeadzoneSteam.exe" -windowed -ResX=1280 -ResY=720 -WinX=40 -WinY=40
