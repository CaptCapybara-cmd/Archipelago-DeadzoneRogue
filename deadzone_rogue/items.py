from typing import Dict, List, NamedTuple, Optional, Set

from BaseClasses import Item, ItemClassification

from .game_data import ITEMS


class DeadzoneRogueItem(Item):
    game = "Deadzone Rogue"


class ItemData(NamedTuple):
    code: int
    category: str
    classification: ItemClassification
    count: int  # copies in the pool (0 = filler, added as needed)
    default_locked: bool  # False = available in the base game unless the client locks it (lock_default_content)
    slot: Optional[str]  # weapons only: primary / secondary / melee


CLASSIFICATIONS = {"progression": ItemClassification.progression, "useful": ItemClassification.useful,
                   "filler": ItemClassification.filler}

item_table: Dict[str, ItemData] = {
    it["name"]: ItemData(it["id"], it["category"], CLASSIFICATIONS[it["classification"]], it["count"],
                         it["default_locked"], it["slot"])
    for it in ITEMS
}
item_name_to_id: Dict[str, int] = {name: data.code for name, data in item_table.items()}

FILLER_ITEMS: List[str] = [name for name, data in item_table.items() if data.category == "filler"]


def names_in(category: str) -> Set[str]:
    return {name for name, data in item_table.items() if data.category == category}


item_name_groups = {
    "Zone Access": {f"Zone {z} Access" for z in (2, 3, 4)},
    "Perks": names_in("perk"),
    "Augments": names_in("augment"),
    "Weapons": names_in("weapon"),
    "Unlocks": names_in("unlock"),
    "Synergy Components": names_in("synergy_component"),
    "Item Packs": names_in("item_group"),
    "Mastery Packs": names_in("mastery_group"),
    "Superior Item Packs": names_in("superior_group"),
}

# Group item category -> pool in GROUP_POOLS
PACK_POOLS = {"item_group": "items", "mastery_group": "masteries", "superior_group": "superior_items"}
