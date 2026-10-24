from dataclasses import dataclass

from Options import (Choice, DeathLink, DefaultOnToggle, OptionGroup, OptionSet, PerGameCommonOptions, Range,
                     Toggle)

from .locations import DIFFICULTY_NAMES, MAX_ROOM_CHECKS, ROOM_CHECK_STEP


class Goal(Choice):
    """Which story mission you must complete (on any difficulty) to finish.
    zone_3: Get Out of My Head. zone_4: Getting Answers (the final story mission)."""
    display_name = "Goal"
    option_zone_3 = 3
    option_zone_4 = 4
    default = option_zone_4


class MissionDifficulties(OptionSet):
    """Which difficulties give a check for completing each mission. Every mission completed on each listed
    difficulty is a separate check (e.g. "Who am I? (Normal)")."""
    display_name = "Mission Difficulties"
    valid_keys = frozenset(DIFFICULTY_NAMES.values())
    default = frozenset({"Adventure", "Normal", "Hard"})


class ZoneGating(DefaultOnToggle):
    """Zones 2-4 are locked behind Zone Access items. Off: zones open as in the base game (story order only)."""
    display_name = "Zone Gating"


class IncludeChallengeMissions(DefaultOnToggle):
    """Challenge missions (Close Quarters, Headhunter, Ultra Nightmare, ...) have checks."""
    display_name = "Include Challenge Missions"


class RoomClearChecks(Range):
    """Total rooms cleared across all runs that give checks, one check every 5 rooms. 0 disables them."""
    display_name = "Room Clear Checks"
    range_start = 0
    range_end = MAX_ROOM_CHECKS * ROOM_CHECK_STEP
    default = 100


class VanillaMissionRewards(Toggle):
    """Keep the game's own mission rewards (first-time and milestone unlocks). Off: those unlocks only come from
    the multiworld."""
    display_name = "Vanilla Mission Rewards"


class ContentShuffle(Choice):
    """none: not shuffled. locked_only: only the ones the base game makes you unlock.
    all: also the ones available from the start; the client locks them until received (see Starting Kit)."""
    option_none = 0
    option_locked_only = 1
    option_all = 2
    default = option_all


class WeaponShuffle(ContentShuffle):
    __doc__ = "Weapons are individual items. " + ContentShuffle.__doc__
    display_name = "Weapon Shuffle"


class PerkShuffle(ContentShuffle):
    __doc__ = "Perk families (Fire, Plasma, Ghost Blade, ...) are individual items. " + ContentShuffle.__doc__
    display_name = "Perk Shuffle"


class AugmentShuffle(ContentShuffle):
    __doc__ = "Augments (Aiming: Crit, Long Range: Weakpoint, ...) are individual items. " + ContentShuffle.__doc__
    display_name = "Augment Shuffle"


class StartingKitWeapons(Range):
    """With Weapon Shuffle 'all': how many primary weapons you start with. One secondary and one melee weapon
    are always added."""
    display_name = "Starting Kit Weapons"
    range_start = 1
    range_end = 4
    default = 1


class StartingKitPerks(Range):
    """With Perk/Augment Shuffle 'all': how many perk families and augments you start with. Each offer shows
    3 choices, so 3 keeps every offer full."""
    display_name = "Starting Kit Perks"
    range_start = 3
    range_end = 6
    default = 3


class PackSize(Range):
    """0: not shuffled."""
    range_start = 0
    range_end = 10


class ItemPackSize(PackSize):
    """Items (Monocle, Mag Clip, ...) are shuffled in random packs of this size. 0: not shuffled."""
    display_name = "Item Pack Size"
    default = 5


class MasteryPackSize(PackSize):
    """Masteries (Tech upgrades: Maximum Health, Weapon Damage, ...) are shuffled in random packs of this size.
    0: not shuffled."""
    display_name = "Mastery Pack Size"
    default = 4


class SuperiorItemPackSize(PackSize):
    """Superior items (SuperItem upgrades: Heat Coil, Rabbit Foot, ...) are shuffled in random packs of this size.
    0: not shuffled."""
    display_name = "Superior Item Pack Size"
    default = 4


class IncludeSynergyComponents(Toggle):
    """Synergy Components are individual items."""
    display_name = "Include Synergy Components"


class DeathLinkMode(Choice):
    """What happens when you receive a DeathLink. Your own run ends normally when you die.
    lose_perk: lose a random perk from the current run. lose_item: lose a random item from the current run.
    lose_scrap: lose half your Scrap. take_damage: take heavy damage (can't kill you).
    push_back_room: sent back to the previous room (experimental). kill: the run ends."""
    display_name = "DeathLink Mode"
    option_lose_perk = 0
    option_lose_item = 1
    option_lose_scrap = 2
    option_take_damage = 3
    option_push_back_room = 4
    option_kill = 5
    default = option_lose_perk


@dataclass
class DeadzoneRogueOptions(PerGameCommonOptions):
    goal: Goal
    mission_difficulties: MissionDifficulties
    zone_gating: ZoneGating
    include_challenge_missions: IncludeChallengeMissions
    room_clear_checks: RoomClearChecks
    vanilla_mission_rewards: VanillaMissionRewards
    weapon_shuffle: WeaponShuffle
    perk_shuffle: PerkShuffle
    augment_shuffle: AugmentShuffle
    starting_kit_weapons: StartingKitWeapons
    starting_kit_perks: StartingKitPerks
    item_pack_size: ItemPackSize
    mastery_pack_size: MasteryPackSize
    superior_item_pack_size: SuperiorItemPackSize
    include_synergy_components: IncludeSynergyComponents
    death_link: DeathLink
    death_link_mode: DeathLinkMode


option_groups = [
    OptionGroup("Checks", [MissionDifficulties, IncludeChallengeMissions, RoomClearChecks, VanillaMissionRewards]),
    OptionGroup("Progression", [Goal, ZoneGating]),
    OptionGroup("Unlocks", [WeaponShuffle, PerkShuffle, AugmentShuffle, StartingKitWeapons, StartingKitPerks,
                            ItemPackSize, MasteryPackSize, SuperiorItemPackSize, IncludeSynergyComponents]),
    OptionGroup("DeathLink", [DeathLinkMode]),
]
