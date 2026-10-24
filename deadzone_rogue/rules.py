from typing import TYPE_CHECKING

from BaseClasses import CollectionState

from .locations import MISSIONS_BY_KEY, is_zone_entry

if TYPE_CHECKING:
    from . import DeadzoneRogueWorld


def can_unlock(state: CollectionState, world: "DeadzoneRogueWorld", mission: dict) -> bool:
    """The mission is selectable: its zone is open and every prerequisite mission can be completed (the game
    requires them, on any difficulty). With zone gating, a zone's entry mission needs only its Zone Access: the
    mod opens it whatever the story order."""
    if world.options.zone_gating and mission["zone"] > 1:
        if not state.has(f"Zone {mission['zone']} Access", world.player):
            return False
        if is_zone_entry(mission):
            return True
    return all(can_unlock(state, world, MISSIONS_BY_KEY[p]) for p in mission["prereqs"])


def can_play(state: CollectionState, world: "DeadzoneRogueWorld", mission: dict, difficulty: int) -> bool:
    # Difficulties aren't gated; each one is just a separate check (the game's own "beat Normal before Hard"
    # order is always satisfiable once the mission is open).
    return can_unlock(state, world, mission)


def set_rules(world: "DeadzoneRogueWorld") -> None:
    for mission, difficulty, location in world.mission_checks:
        location.access_rule = lambda state, m=mission, d=difficulty: can_play(state, world, m, d)
    world.victory_location.access_rule = lambda state: all(can_unlock(state, world, m) for m in world.goal_missions)
    world.multiworld.completion_condition[world.player] = lambda state: state.has("Victory", world.player)
