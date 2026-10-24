from dataclasses import dataclass

from Options import (Choice, DeathLink, DefaultOnToggle, OptionGroup, OptionSet, PerGameCommonOptions, Range,
                     Toggle)

from .locations import DIFFICULTY_NAMES, MAX_MILESTONES, OBJECTIVES


class Goal(Choice):
    """Complete every story and challenge mission in zones 1 up to this zone (on any difficulty) to finish.
    Endless-wave missions (Gauntlet, Crossfire, Last Stand) never count, and a challenge that only exists on one
    difficulty counts only if that difficulty is in mission_difficulties."""
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


class IncludeEndlessMissions(Toggle):
    """The endless-wave missions (Gauntlet, Crossfire, Last Stand) have checks too. Off by default: an endless run
    may never register as "completed". They never count towards the goal."""
    display_name = "Include Endless Missions"


# Save-wide objectives: running totals across every run on your Archipelago save, with a check at every interval
# ("Enemies Killed: 300", "Enemies Killed: 600", ...). Total 0 turns an objective off.
class SectorsClearedTotal(Range):
    """Sectors cleared (across all runs) at which the last Sectors Cleared check is reached. 0: no sector checks."""
    display_name = "Sectors Cleared Total"
    range_start = 0
    range_end = MAX_MILESTONES * OBJECTIVES["sectors"].unit
    default = 150


class SectorsClearedInterval(Range):
    """A Sectors Cleared check every this many sectors (rounded down to a multiple of 5)."""
    display_name = "Sectors Cleared Interval"
    range_start = OBJECTIVES["sectors"].unit
    range_end = 50
    default = 10


class EnemiesKilledTotal(Range):
    """Enemies you've killed (across all runs) at which the last Enemies Killed check is reached. 0: no kill checks."""
    display_name = "Enemies Killed Total"
    range_start = 0
    range_end = MAX_MILESTONES * OBJECTIVES["kills"].unit
    default = 3000


class EnemiesKilledInterval(Range):
    """An Enemies Killed check every this many kills (rounded down to a multiple of 100)."""
    display_name = "Enemies Killed Interval"
    range_start = OBJECTIVES["kills"].unit
    range_end = 2000
    default = 300


class ScrapGatheredTotal(Range):
    """Scrap picked up (across all runs; spending doesn't count against it) at which the last Scrap Gathered check
    is reached. 0: no Scrap checks."""
    display_name = "Scrap Gathered Total"
    range_start = 0
    range_end = MAX_MILESTONES * OBJECTIVES["scrap"].unit
    default = 20000


class ScrapGatheredInterval(Range):
    """A Scrap Gathered check every this much Scrap (rounded down to a multiple of 1000)."""
    display_name = "Scrap Gathered Interval"
    range_start = OBJECTIVES["scrap"].unit
    range_end = 10000
    default = 2000


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
    Each pack is progressive: the first copy unlocks its upgrades, every copy raises them by Tech Levels Per Copy.
    While they're shuffled, Tech upgrades can't be bought in the game. 0: not shuffled."""
    display_name = "Mastery Pack Size"
    default = 5


class SuperiorItemPackSize(PackSize):
    """Superior items (SuperItem upgrades: Heat Coil, Rabbit Foot, ...) are shuffled in random packs of this size.
    Each pack is progressive: the first copy unlocks its superior items, every copy raises them by Superior Levels
    Per Copy. While they're shuffled, superior items can't be upgraded in the game. 0: not shuffled."""
    display_name = "Superior Item Pack Size"
    default = 10


class TechLevelsPerCopy(Range):
    """Levels (out of 10) each copy of a Mastery Pack adds to every Tech upgrade in it. Smaller chunks mean more
    copies: 10 / this, rounded up, per pack."""
    display_name = "Tech Levels Per Copy"
    range_start = 1
    range_end = 10
    default = 3


class SuperiorLevelsPerCopy(Range):
    """Levels each copy of a Superior Item Pack adds to every superior item in it. They start at level 1 and go up
    to 5, so 4 levels in all: 4 / this, rounded up, copies per pack."""
    display_name = "Superior Levels Per Copy"
    range_start = 1
    range_end = 4
    default = 2


class IncludeSynergyComponents(Toggle):
    """Synergy Components are individual items."""
    display_name = "Include Synergy Components"


class DeathLinkMode(Choice):
    """What happens when you receive a DeathLink. Your own run ends normally when you die.
    lose_perk: lose a random element perk from the current run. lose_item: lose a random item from the current run.
    Unlocks are never touched, only what you picked up this run.
    lose_scrap: lose half your Scrap. take_damage: drop to a quarter of your health (can't kill you).
    push_back_room: not possible yet, so it costs half your Scrap instead. kill: the run ends."""
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
    include_endless_missions: IncludeEndlessMissions
    sectors_cleared_total: SectorsClearedTotal
    sectors_cleared_interval: SectorsClearedInterval
    enemies_killed_total: EnemiesKilledTotal
    enemies_killed_interval: EnemiesKilledInterval
    scrap_gathered_total: ScrapGatheredTotal
    scrap_gathered_interval: ScrapGatheredInterval
    vanilla_mission_rewards: VanillaMissionRewards
    weapon_shuffle: WeaponShuffle
    perk_shuffle: PerkShuffle
    augment_shuffle: AugmentShuffle
    starting_kit_weapons: StartingKitWeapons
    starting_kit_perks: StartingKitPerks
    item_pack_size: ItemPackSize
    mastery_pack_size: MasteryPackSize
    superior_item_pack_size: SuperiorItemPackSize
    tech_levels_per_copy: TechLevelsPerCopy
    superior_levels_per_copy: SuperiorLevelsPerCopy
    include_synergy_components: IncludeSynergyComponents
    death_link: DeathLink
    death_link_mode: DeathLinkMode


option_groups = [
    OptionGroup("Checks", [MissionDifficulties, IncludeChallengeMissions, IncludeEndlessMissions, VanillaMissionRewards]),
    OptionGroup("Save-wide Objectives", [SectorsClearedTotal, SectorsClearedInterval, EnemiesKilledTotal,
                                         EnemiesKilledInterval, ScrapGatheredTotal, ScrapGatheredInterval]),
    OptionGroup("Progression", [Goal, ZoneGating]),
    OptionGroup("Unlocks", [WeaponShuffle, PerkShuffle, AugmentShuffle, StartingKitWeapons, StartingKitPerks,
                            ItemPackSize, MasteryPackSize, SuperiorItemPackSize, TechLevelsPerCopy,
                            SuperiorLevelsPerCopy, IncludeSynergyComponents]),
    OptionGroup("DeathLink", [DeathLinkMode]),
]
