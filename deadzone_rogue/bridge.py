"""File bridge between the Python client and the APClient Lua mod (UE4SS Lua has no sockets).

Folder: <game>/Valhalla/Binaries/Win64/APBridge/
  inbox.txt      written by the client (atomically replaced), read by the mod. Line-based so Lua can parse it:
                   version 1
                   rev <n>
                   session <id>
                   goal <zone>
                   zones <open zones...> / missionzone <mission guid> <zone>   (zone gating)
                   zoneentry <mission guid>                       (opened by its zone's access, story order aside)
                   lock <asset object path>                       (one per asset the mod must lock)
                   grant <index> <once|add|level> <amount> <asset path>  (index = position in ReceivedItems;
                                                                   level: raise the count to at least amount)
                   noupgradebuy <tech|superior...>                (those upgrades can't be bought in the hub)
                   noreward <asset path>                          (take this back when a mission rewards it)
                   note <id> <text>                               (in-game chat message; ids only ever increase)
                   deathlink <id> <mode> <source>                 (a received DeathLink, applied once per id)
  outbox_<session>.txt   appended by the mod, tailed by the client (one file per AP session):
                   mission <mission key> <difficulty>
                   sectors|kills|scrap <save-wide total so far>
                   death <unix time>
  heartbeat.txt  unix time, rewritten by the mod every few seconds.

Kept free of client/network imports so it can be unit tested.
"""
import json
import os
import pkgutil
import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .locations import MISSIONS_BY_KEY, is_zone_entry, objective_location_id

BRIDGE_DIR = "APBridge"
DEFAULT_GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Deadzone Rogue\Valhalla\Binaries\Win64"


def load_data() -> dict:
    return json.loads(pkgutil.get_data(__name__, "ap_data.json").decode("utf-8"))


def session_id(seed_name: str, slot_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"{seed_name}-{slot_name}")


def mission_location(data: dict, key: str, difficulty: int) -> Optional[int]:
    for index, mission in enumerate(data["missions"]):
        if mission["key"] == key:
            return data["location_base"] + index * 10 + difficulty
    return None


def objective_locations(key: str, amount_so_far: int, interval: int, total: int) -> List[int]:
    """Every milestone of an objective ("Enemies Killed: 300", ...) reached by a save-wide running total."""
    if interval <= 0:
        return []
    return [objective_location_id(key, a) for a in range(interval, min(amount_so_far, total) + 1, interval)]


def lock_paths(data: dict, slot_data: dict) -> List[str]:
    """Normally-free assets the mod must lock: every category whose free entries are shuffled, and the run items
    dealt out in packs. Owned assets stay usable while locked, so received ones need no special case."""
    paths = []
    lock_free = set(slot_data.get("lock_free", []))
    for item in data["items"].values():
        if item["category"] in lock_free and not item["default_locked"]:
            paths += item["lock"]
    if any(item_id in slot_data.get("packs", {}) for item_id, item in data["items"].items()
           if item["category"] == "item_group"):
        paths += list(data["group_pools"]["items"].values())
    return sorted(set(paths))


def grant_lines(data: dict, slot_data: dict, received_ids: Sequence[int]) -> List[Tuple[int, str, int, str]]:
    """(index, mode, amount, asset path) for every received item, in ReceivedItems order."""
    lines = []
    progressive_seen: Dict[int, int] = {}
    pool_paths = {key: path for pool in data["group_pools"].values() for key, path in pool.items()}
    for index, item_id in enumerate(received_ids):
        item = data["items"].get(str(item_id))
        if item is None:
            continue
        if item["mode"] == "progressive":
            k = progressive_seen.get(item_id, 0)
            progressive_seen[item_id] = k + 1
            if k < len(item["grants"]):
                lines.append((index, "once", 1, item["grants"][k]))
        elif str(item_id) in slot_data.get("packs", {}):
            copy = progressive_seen.get(item_id, 0) + 1  # leveled packs are progressive
            progressive_seen[item_id] = copy
            chunk = slot_data.get("pack_levels", {}).get(str(item_id))
            for key in slot_data["packs"][str(item_id)]:
                if key in pool_paths:
                    lines.append((index, "once", 1, pool_paths[key]))
                upgrade = data.get("upgrade_levels", {}).get(key)
                if chunk and upgrade:
                    lines.append((index, "level", min(upgrade["points"], copy * chunk), upgrade["path"]))
        else:
            for path in item["grants"]:
                lines.append((index, item["mode"], item["amount"], path))
    return lines


def gating_lines(data: dict, slot_data: dict, received_ids: Sequence[int]) -> List[str]:
    """Which zones are open, from the Zone Access items received. No zones line means zone gating is off."""
    names = [data["items"].get(str(i), {}).get("name") for i in received_ids]
    # keyed by MissionId GUID: the mod reads it inline from the mission option (MissionData may not be loaded yet)
    lines = [f"missionzone {m['guid']} {m['zone']}" for m in data["missions"]]
    if slot_data.get("zone_gating"):
        goal_zone = slot_data.get("goal_zone", 4)
        zones = [z for z in (1, 2, 3, 4) if z == 1 or z > goal_zone or f"Zone {z} Access" in names]
        lines.append("zones " + " ".join(map(str, zones)))
        # zones past the goal have no access item and keep the game's own order
        lines += [f"zoneentry {m['guid']}" for m in data["missions"] if m["zone"] <= goal_zone
                  and m["key"] in MISSIONS_BY_KEY and is_zone_entry(MISSIONS_BY_KEY[m["key"]])]
    return lines


LEVELED_CATEGORIES = {"mastery_group": "tech", "superior_group": "superior"}


def upgrade_purchase_blocks(slot_data: dict) -> List[str]:
    """Upgrade kinds whose levels come from Archipelago in this seed, so the game mustn't sell them."""
    data = load_data()
    kinds = {LEVELED_CATEGORIES.get(data["items"].get(item_id, {}).get("category"))
             for item_id in slot_data.get("pack_levels", {})}
    return sorted(k for k in kinds if k)


def reward_block_paths(data: dict, slot_data: dict) -> List[str]:
    """Unlocks the game's own mission rewards mustn't give, because this seed hands them out through the
    multiworld: every one-time grant of the seed's items, including pack contents. Currency is left alone, and
    anything the seed doesn't shuffle stays a normal reward (otherwise it couldn't be had at all)."""
    if slot_data.get("vanilla_mission_rewards", True):
        return []
    pool_paths = {key: path for pool in data["group_pools"].values() for key, path in pool.items()}
    paths = set()
    for item_id in slot_data.get("pool_items", []):
        item = data["items"].get(str(item_id))
        if item is None or item["mode"] == "add":
            continue
        paths.update(item["grants"])
        for key in slot_data.get("packs", {}).get(str(item_id), []):
            if key in pool_paths:
                paths.add(pool_paths[key])
    return sorted(paths)


def render_inbox(rev: int, session: str, slot_data: dict, locks: Iterable[str],
                 grants: Iterable[Tuple[int, str, int, str]], gating: Iterable[str] = (),
                 notes: Iterable[Tuple[int, str]] = (),
                 deathlinks: Iterable[Tuple[int, str, str]] = ()) -> str:
    out = ["version 1", f"rev {rev}", f"session {session}", f"goal {slot_data.get('goal_zone', '')}"]
    out += list(gating)
    out += [f"noreward {path}" for path in reward_block_paths(load_data(), slot_data)]
    blocked = upgrade_purchase_blocks(slot_data)
    if blocked:
        out.append("noupgradebuy " + " ".join(blocked))
    out += [f"lock {path}" for path in locks]
    out += [f"grant {index} {mode} {amount} {path}" for index, mode, amount, path in grants]
    out += [f"note {note_id} {' '.join(text.split())}" for note_id, text in notes]
    out += [f"deathlink {death_id} {mode} {' '.join(source.split())}" for death_id, mode, source in deathlinks]
    return "\n".join(out) + "\n"


def write_atomic(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def parse_outbox(text: str) -> List[Tuple[str, List[str]]]:
    events = []
    for line in text.splitlines():
        parts = line.split()
        if parts:
            events.append((parts[0], parts[1:]))
    return events


def checks_from_events(data: dict, slot_data: dict, events: Iterable[Tuple[str, List[str]]],
                       since: float) -> Tuple[Set[int], Set[str], int]:
    """Location ids to send, missions completed (any difficulty, for the goal), and how many new deaths
    (after `since`) occurred."""
    locations: Set[int] = set()
    completed: Set[str] = set()
    deaths = 0
    objectives = slot_data.get("objectives", {})
    for kind, args in events:
        if kind == "mission" and len(args) == 2:
            key, difficulty = args[0], int(args[1])
            completed.add(key)
            if difficulty in slot_data.get("difficulties", []):
                loc = mission_location(data, key, difficulty)
                if loc is not None:
                    locations.add(loc)
        elif kind in ("sectors", "rooms", "kills", "scrap") and args:
            key = "sectors" if kind == "rooms" else kind  # "rooms" from mod versions before 0.5.0
            interval, total = objectives.get(key, (0, 0))
            locations.update(objective_locations(key, int(args[0]), interval, total))
        elif kind == "death" and args and float(args[0]) > since:
            deaths += 1
    return locations, completed, deaths


def goal_complete(slot_data: dict, completed: Set[str]) -> bool:
    goal = slot_data.get("goal_missions", [])
    return bool(goal) and all(key in completed for key in goal)
