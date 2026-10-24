from typing import Dict, List, NamedTuple

from BaseClasses import Location

from .game_data import LOCATION_BASE, MISSIONS

# Game difficulty index (EValGameDifficulty) -> name used in checks and in the mission_difficulties option.
DIFFICULTY_NAMES = {1: "Adventure", 2: "Normal", 3: "Hard", 4: "Difficulty 4", 5: "Difficulty 5"}


class Objective(NamedTuple):
    """A save-wide running total with milestone checks ("Enemies Killed: 500", ...). Milestones are multiples of
    `unit`; the table holds MAX_MILESTONES of them so location ids never change, and options pick a subset."""
    label: str
    unit: int
    id_offset: int


MAX_MILESTONES = 100
OBJECTIVES = {
    # sectors (the game's name for cleared rooms/encounters) keep the ids of the former "Rooms Cleared" checks
    "sectors": Objective("Sectors Cleared", 5, 1000),
    "kills": Objective("Enemies Killed", 100, 2000),
    "scrap": Objective("Scrap Gathered", 1000, 3000),
}


class DeadzoneRogueLocation(Location):
    game = "Deadzone Rogue"


def mission_location(mission: dict, difficulty: int) -> str:
    return f"{mission['name']} ({DIFFICULTY_NAMES[difficulty]})"


def objective_location(key: str, amount: int) -> str:
    return f"{OBJECTIVES[key].label}: {amount}"


def objective_location_id(key: str, amount: int) -> int:
    objective = OBJECTIVES[key]
    return LOCATION_BASE + objective.id_offset + amount // objective.unit


def _build_table() -> Dict[str, int]:
    table: Dict[str, int] = {}
    for i, mission in enumerate(MISSIONS):
        for d in mission["difficulties"]:
            table[mission_location(mission, d)] = LOCATION_BASE + i * 10 + d
    for key, objective in OBJECTIVES.items():
        for n in range(1, MAX_MILESTONES + 1):
            amount = n * objective.unit
            table[objective_location(key, amount)] = objective_location_id(key, amount)
    return table


location_name_to_id: Dict[str, int] = _build_table()

MISSIONS_BY_KEY = {m["key"]: m for m in MISSIONS}


def is_zone_entry(mission: dict) -> bool:
    """The story mission that starts a zone (Keep it Together, Get Out of My Head, Prelude). With zone gating,
    its Zone Access item opens it directly, even when the earlier zones' story missions aren't done."""
    return (mission["zone"] > 1 and mission["story"]
            and all(MISSIONS_BY_KEY[p]["zone"] < mission["zone"] for p in mission["prereqs"]))


def mission_locations(mission: dict) -> List[str]:
    return [mission_location(mission, d) for d in mission["difficulties"]]


location_name_groups = {
    **{f"Zone {z}": {loc for m in MISSIONS if m["zone"] == z for loc in mission_locations(m)} for z in (1, 2, 3, 4)},
    "Story Missions": {loc for m in MISSIONS if m["story"] for loc in mission_locations(m)},
    "Challenge Missions": {loc for m in MISSIONS if not m["story"] for loc in mission_locations(m)},
    **{o.label: {objective_location(k, n * o.unit) for n in range(1, MAX_MILESTONES + 1)} for k, o in OBJECTIVES.items()},
}
