from typing import Any, Dict, List, Tuple

from BaseClasses import ItemClassification, Location, Region, Tutorial
from Options import OptionError
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, Type, components, launch as launch_component

from .game_data import GROUP_POOLS, MISSIONS
from .items import FILLER_ITEMS, PACK_POOLS, DeadzoneRogueItem, item_name_groups, item_name_to_id, item_table
from .locations import (DIFFICULTY_NAMES, OBJECTIVES, DeadzoneRogueLocation, location_name_groups,
                        location_name_to_id, mission_location, objective_location)
from .options import DeadzoneRogueOptions, option_groups
from .rules import set_rules

# When there are more items than checks, useful items are dropped from these categories first (in order).
TRIM_ORDER = ["synergy_component", "item_group", "superior_group", "mastery_group", "unlock",
              "augment", "weapon", "perk"]


def launch_client(*args: str) -> None:
    from .client import launch
    launch_component(launch, name="DeadzoneRogueClient", args=args)


components.append(Component("Deadzone Rogue Client", func=launch_client, component_type=Type.CLIENT,
                            game_name="Deadzone Rogue", supports_uri=True))


class DeadzoneRogueWeb(WebWorld):
    theme = "partyTime"
    option_groups = option_groups
    tutorials = [Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up Deadzone Rogue for Archipelago.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Ethan"],
    )]


class DeadzoneRogueWorld(World):
    """
    Deadzone: Rogue is a roguelite FPS set on a derelict space station. Fight through
    zones of enemies, collect gear and grow stronger with each run.
    """
    game = "Deadzone Rogue"
    web = DeadzoneRogueWeb()
    options_dataclass = DeadzoneRogueOptions
    options: DeadzoneRogueOptions
    topology_present = True

    item_name_to_id = item_name_to_id
    location_name_to_id = location_name_to_id
    item_name_groups = item_name_groups
    location_name_groups = location_name_groups

    goal_missions: List[dict]  # every one must be completed (any difficulty) for the goal
    missions: List[dict]  # missions with checks
    milestones: Dict[str, Tuple[int, int]]  # objective -> (interval, total); total 0 = off
    difficulties: List[int]  # enabled difficulty indexes, easiest first
    mission_checks: List[Tuple[dict, int, Location]]
    victory_location: Location
    starting_kit: List[str]
    packs: Dict[str, List[str]]  # pack item name -> asset keys it unlocks

    def generate_early(self) -> None:
        opts = self.options
        enabled = {name for name in opts.mission_difficulties.value}
        if not enabled:
            raise OptionError(f"{self.player_name}: mission_difficulties must list at least one difficulty.")
        self.difficulties = sorted(d for d, name in DIFFICULTY_NAMES.items() if name in enabled)

        goal_zone = opts.goal.value
        # a mission that only exists on difficulties without checks (e.g. Ultra Nightmare) is left out entirely
        playable = [m for m in MISSIONS
                    if m["zone"] <= goal_zone
                    and (m["story"] or opts.include_challenge_missions)
                    and any(d in self.difficulties for d in m["difficulties"])]
        self.missions = [m for m in playable if not m["endless"] or opts.include_endless_missions]
        self.goal_missions = [m for m in playable if not m["endless"]]
        self.milestones = {}
        for key, (total, interval) in {"sectors": (opts.sectors_cleared_total, opts.sectors_cleared_interval),
                                        "kills": (opts.enemies_killed_total, opts.enemies_killed_interval),
                                        "scrap": (opts.scrap_gathered_total, opts.scrap_gathered_interval)}.items():
            unit = OBJECTIVES[key].unit
            step = max(unit, interval.value // unit * unit)
            self.milestones[key] = (step, total.value // step * step)
        self.starting_kit = self.pick_starting_kit()
        self.packs = self.make_packs()

    def shuffled(self, category: str) -> bool:
        """Whether a category's normally-free entries are shuffled too (and so get locked by the client)."""
        option = {"weapon": self.options.weapon_shuffle, "perk": self.options.perk_shuffle,
                  "augment": self.options.augment_shuffle}[category]
        return option.value == option.option_all

    def pick_starting_kit(self) -> List[str]:
        """Normally-free weapons, perks and augments to start with when those are locked, so runs stay playable."""
        def free(category: str, slot: str = None) -> List[str]:
            return sorted(name for name, data in item_table.items()
                          if data.category == category and not data.default_locked and (slot is None or data.slot == slot))

        kit = []
        if self.shuffled("weapon"):
            kit += self.random.sample(free("weapon", "primary"), self.options.starting_kit_weapons.value)
            kit += [self.random.choice(free("weapon", "secondary")), self.random.choice(free("weapon", "melee"))]
        for category in ("perk", "augment"):
            if self.shuffled(category):
                kit += self.random.sample(free(category), self.options.starting_kit_perks.value)
        return kit

    def make_packs(self) -> Dict[str, List[str]]:
        """Splits each grouped pool into random packs; the pack items are named '<Label> 1', '<Label> 2', ..."""
        sizes = {"item_group": self.options.item_pack_size.value, "mastery_group": self.options.mastery_pack_size.value,
                 "superior_group": self.options.superior_item_pack_size.value}
        packs = {}
        for category, pool in PACK_POOLS.items():
            size = sizes[category]
            if size == 0:
                continue
            keys = list(GROUP_POOLS[pool])
            self.random.shuffle(keys)
            names = sorted((n for n, d in item_table.items() if d.category == category), key=lambda n: item_table[n].code)
            for i in range(0, len(keys), size):
                packs[names[i // size]] = keys[i:i + size]
        return packs

    def create_item(self, name: str) -> DeadzoneRogueItem:
        data = item_table[name]
        return DeadzoneRogueItem(name, data.classification, data.code, self.player)

    def get_filler_item_name(self) -> str:
        return self.random.choice(FILLER_ITEMS)

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        station = Region("Deadzone Station", self.player, self.multiworld)
        self.mission_checks = []
        for mission in self.missions:
            for d in mission["difficulties"]:
                if d not in self.difficulties:
                    continue
                name = mission_location(mission, d)
                location = DeadzoneRogueLocation(self.player, name, location_name_to_id[name], station)
                station.locations.append(location)
                self.mission_checks.append((mission, d, location))
        for key, (step, total) in self.milestones.items():
            for amount in range(step, total + 1, step):
                name = objective_location(key, amount)
                station.locations.append(DeadzoneRogueLocation(self.player, name, location_name_to_id[name], station))

        # Goal event: every goal mission completed on any difficulty. The client reports it with
        # StatusUpdate(CLIENT_GOAL); the server never sees the event itself.
        self.victory_location = DeadzoneRogueLocation(
            self.player, f"Goal: All Missions Through Zone {self.options.goal.value}", None, station)
        self.victory_location.place_locked_item(
            DeadzoneRogueItem("Victory", ItemClassification.progression, None, self.player))
        station.locations.append(self.victory_location)

        self.multiworld.regions += [menu, station]
        menu.connect(station, "Start")

    def wanted_items(self) -> List[str]:
        opts = self.options
        names = []
        if opts.zone_gating:
            names += [f"Zone {z} Access" for z in range(2, opts.goal.value + 1)]
        names += list(self.packs)
        for name, data in item_table.items():
            if name in self.starting_kit:
                continue
            if data.category in ("weapon", "perk", "augment"):
                option = {"weapon": opts.weapon_shuffle, "perk": opts.perk_shuffle, "augment": opts.augment_shuffle}[data.category]
                if option.value == option.option_none or (not data.default_locked and option.value != option.option_all):
                    continue
            elif data.category == "synergy_component" and not opts.include_synergy_components:
                continue
            elif data.category != "unlock":
                continue
            names += [name] * data.count
        return names

    def create_items(self) -> None:
        for name in self.starting_kit:
            self.multiworld.push_precollected(self.create_item(name))

        names = self.wanted_items()
        slots = len(self.multiworld.get_unfilled_locations(self.player))
        for category in TRIM_ORDER:
            if len(names) <= slots:
                break
            droppable = [n for n in names if item_table[n].category == category]
            self.random.shuffle(droppable)
            for n in droppable[:len(names) - slots]:
                names.remove(n)
                self.packs.pop(n, None)  # a dropped pack's contents stay as in the base game
        if len(names) > slots:
            raise OptionError(f"{self.player_name}: {len(names)} items but only {slots} checks. "
                              f"Add mission difficulties or objective checks, or enable challenge missions.")
        names += [self.get_filler_item_name() for _ in range(slots - len(names))]
        self.multiworld.itempool += [self.create_item(n) for n in names]

    def set_rules(self) -> None:
        set_rules(self)

    def fill_slot_data(self) -> Dict[str, Any]:
        # Everything the client mod needs about this seed; item/location meanings come from client/ap_data.json.
        opts = self.options
        return {
            "goal_zone": opts.goal.value,
            "goal_missions": [m["key"] for m in self.goal_missions],
            "difficulties": self.difficulties,
            "zone_gating": bool(opts.zone_gating),
            # objective -> [interval, total]: a check at every interval up to total
            "objectives": {key: list(value) for key, value in self.milestones.items()},
            "vanilla_mission_rewards": bool(opts.vanilla_mission_rewards),
            # categories the client must lock at start (their normally-free entries are shuffled)
            "lock_free": [c for c in ("weapon", "perk", "augment") if self.shuffled(c)],
            "packs": {str(item_name_to_id[name]): keys for name, keys in self.packs.items()},
            "death_link": bool(opts.death_link),
            "death_link_mode": opts.death_link_mode.current_key,
        }
