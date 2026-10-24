"""Dev menu plumbing: commands for the APClient mod (APBridge/debug.txt) and its replies (APBridge/debug_log.txt).

Each command line is "<id> <command> <args>", ids only increasing; the mod runs each new id once.
"""
import json
import os
import time
import zipfile
from typing import Dict, List, Optional, Tuple

from . import installer

COMMANDS_FILE, REPLIES_FILE = "debug.txt", "debug_log.txt"
KEEP_COMMANDS = 50
DEATHLINK_MODES = ["lose_perk", "lose_item", "lose_scrap", "take_damage", "push_back_room", "kill"]
DIFFICULTIES = {"Adventure": 1, "Normal": 2, "Hard": 3, "Difficulty 4": 4, "Difficulty 5": 5}
TOTALS = ["sectors", "kills", "scrap"]


def load_game_data(apworld: Optional[str] = None) -> dict:
    """The world's ap_data.json (missions, items and their asset paths), read from the bundled apworld."""
    with zipfile.ZipFile(apworld or os.path.join(installer.RESOURCES, "deadzone_rogue.apworld")) as z:
        return json.loads(z.read("deadzone_rogue/ap_data.json"))


def missions(data: dict) -> List[Tuple[str, str, List[int]]]:
    """(label, key, difficulties) for every mission, in game order."""
    return [(f"Zone {m['zone']}: {m['name']}", m["key"], m["difficulties"]) for m in data["missions"]]


def grantable_items(data: dict) -> Dict[str, List[str]]:
    """AP item name -> asset paths it grants, for items that grant something one time (no currency)."""
    return {i["name"]: i["grants"] for i in sorted(data["items"].values(), key=lambda i: i["name"])
            if i["grants"] and i["mode"] == "once"}


def _bridge(win64: str) -> str:
    return os.path.join(win64, "APBridge")


def send(win64: str, *commands: str) -> List[int]:
    """Queue commands for the mod; returns their ids. The file is replaced atomically, so the mod never reads a
    half-written line."""
    folder = _bridge(win64)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, COMMANDS_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
    except OSError:
        lines = []
    last = max((int(line.split(" ", 1)[0]) for line in lines if line.split(" ", 1)[0].isdigit()), default=0)
    ids = []
    for command in commands:
        last = max(int(time.time() * 1000), last + 1)
        ids.append(last)
        lines.append(f"{last} {' '.join(command.split())}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines[-KEEP_COMMANDS:]) + "\n")
    os.replace(tmp, path)
    return ids


def replies(win64: str, after: int = 0) -> List[Tuple[int, str]]:
    """(id, text) reply lines from the mod for command ids greater than `after`."""
    try:
        with open(os.path.join(_bridge(win64), REPLIES_FILE), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        head, _, text = line.partition(" ")
        if head.isdigit() and int(head) > after:
            out.append((int(head), text))
    return out
