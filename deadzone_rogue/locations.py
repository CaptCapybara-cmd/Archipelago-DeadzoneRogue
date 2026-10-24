from typing import Dict, List

from BaseClasses import Location

from .game_data import LOCATION_BASE, MISSIONS

# Game difficulty index (EValGameDifficulty) -> name used in checks and in the mission_difficulties option.
DIFFICULTY_NAMES = {1: "Adventure", 2: "Normal", 3: "Hard", 4: "Difficulty 4", 5: "Difficulty 5"}
# Cumulative room clears across all runs ("Rooms Cleared: 5", "... 10", ...). Fixed max so ids are stable.
ROOM_CHECK_STEP = 5
MAX_ROOM_CHECKS = 40


class DeadzoneRogueLocation(Location):
    game = "Deadzone Rogue"


def mission_location(mission: dict, difficulty: int) -> str:
    return f"{mission['name']} ({DIFFICULTY_NAMES[difficulty]})"


def room_location(index: int) -> str:
    return f"Rooms Cleared: {index * ROOM_CHECK_STEP}"


def _build_table() -> Dict[str, int]:
    table: Dict[str, int] = {}
    for i, mission in enumerate(MISSIONS):
        for d in mission["difficulties"]:
            table[mission_location(mission, d)] = LOCATION_BASE + i * 10 + d
    for n in range(1, MAX_ROOM_CHECKS + 1):
        table[room_location(n)] = LOCATION_BASE + 1000 + n
    return table


location_name_to_id: Dict[str, int] = _build_table()

MISSIONS_BY_KEY = {m["key"]: m for m in MISSIONS}


def mission_locations(mission: dict) -> List[str]:
    return [mission_location(mission, d) for d in mission["difficulties"]]


location_name_groups = {
    **{f"Zone {z}": {loc for m in MISSIONS if m["zone"] == z for loc in mission_locations(m)} for z in (1, 2, 3, 4)},
    "Story Missions": {loc for m in MISSIONS if m["story"] for loc in mission_locations(m)},
    "Challenge Missions": {loc for m in MISSIONS if not m["story"] for loc in mission_locations(m)},
    "Room Clears": {room_location(n) for n in range(1, MAX_ROOM_CHECKS + 1)},
}
