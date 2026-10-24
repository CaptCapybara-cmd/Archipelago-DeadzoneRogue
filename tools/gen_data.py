"""Generates the Deadzone Rogue APWorld's game data from the in-game asset catalog.

Reads dumps/APCatalog.tsv (written by the APCatalog UE4SS mod) and writes:
  deadzone_rogue/game_data.py  - missions and items for the world (names, AP ids, logic data)
  client/ap_data.json          - the same tables keyed by AP id, with asset paths for the client mod

AP ids must never change once seeds exist. Each category has a fixed id block and items inside it are
ordered by asset name, so new game content gets appended by bumping the block's next free id by hand
(see ID_BLOCKS) rather than regenerating everything blindly.
"""
import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "dumps", "APCatalog.tsv")

ITEM_BASE = 7_310_000
LOCATION_BASE = 7_320_000
ID_BLOCKS = {  # category -> offset from ITEM_BASE
    "progression": 0, "perk": 100, "augment": 200, "weapon": 300, "unlock": 400,
    "synergy_component": 700, "filler": 900,
    "item_group": 1000, "mastery_group": 1200, "superior_group": 1300,
}
GROUPS = {  # group category -> (AP item name prefix, pool)
    "item_group": ("Item Pack", "items"),
    "mastery_group": ("Mastery Pack", "masteries"),
    "superior_group": ("Superior Item Pack", "superior_items"),
}

# Content that is only obtained/used inside missions or is cosmetic; never an AP item.
SKIP_AUGMENT = re.compile(r"_Mission$|^Augment_Specialty_")
ELEMENT_UNLOCK = {"Perk_Plasma_Parent": "ItemUnlock_PlasmaElement",
                  "Perk_Psionic_Parent": "ItemUnlock_PsionicElement",
                  "Perk_Radiation_Parent": "ItemUnlock_RadiationElement"}
# Unlock items that share a display name become one progressive item (granted in this order).
PROGRESSIVE_UNLOCKS = {
    "Progressive Loot Orb Tech Reroll": ["ItemUnlock_RerollLootOrb_TechA", "ItemUnlock_RerollLootOrb_TechB", "ItemUnlock_RerollLootOrb_TechC"],
    "Progressive Fabricator Tech Restock": ["ItemUnlock_ShopRestock_TechA", "ItemUnlock_ShopRestock_TechB", "ItemUnlock_ShopRestock_TechC"],
}


def load_catalog():
    rows = {}
    with open(CATALOG, encoding="utf-8") as f:
        for r in csv.reader(f, delimiter="\t"):
            if not r or r[0] == "class":
                continue
            cls, pkg, asset, item_id, display = (r + [""] * 5)[:5]
            extra = {}
            for field in r[5:]:
                if "=" in field:
                    k, v = field.split("=", 1)
                    extra[k] = v
            rows.setdefault(asset, {"class": cls, "package": pkg, "asset": asset, "item_id": item_id,
                                    "display": display.strip(), "extra": extra})
    return rows


def object_path(row):
    return f"{row['package']}.{row['asset']}"


def mission_table(rows):
    missions = []
    for row in rows.values():
        if row["class"] != "ValMissionData":
            continue
        tiers = row["extra"].get("tiers", "")
        diffs = sorted({int(d) for part in tiers.split() for d in part.split(":", 1)[1].split(",") if d})
        prereqs = [p for p in row["extra"].get("prereqs", "").split(",") if p]
        missions.append({"key": row["asset"], "name": row["display"], "guid": row["item_id"],
                         "difficulties": diffs, "prereqs": prereqs,
                         "endless": "Endless" in row["extra"].get("class", ""),
                         "story": "_Story" in row["asset"] or "_Introduction" in row["asset"]})
    by_key = {m["key"]: m for m in missions}

    def zone(m):
        found = re.search(r"Zone(\d)", m["key"])
        if found:
            return int(found.group(1))
        return max(zone(by_key[p]) for p in m["prereqs"])  # challenges unlock in their prerequisite's zone

    for m in missions:
        m["zone"] = zone(m)
    missions.sort(key=lambda m: (m["zone"], not m["story"], m["key"]))
    return missions


def group_pools(rows):
    """Things handed out in packs rather than one AP item each: items, masteries (Tech upgrades, unlocked by
    their Tech Component) and superior items (SuperItem upgrades, unlocked by their Item Component)."""
    def pool(match):
        return [{"key": a, "name": rows[a]["display"] or a, "path": object_path(rows[a])}
                for a in sorted(a for a, r in rows.items() if match(r))]
    return {
        "items": pool(lambda r: r["class"] == "ValAbilityAsset" and "/Items/Items/" in r["package"] + "/"
                      and "/Unused/" not in r["package"] + "/"),
        "masteries": pool(lambda r: "/Components/Tech/" in r["package"] + "/"),
        "superior_items": pool(lambda r: "/Components/SuperItems/" in r["package"] + "/"),
    }


def items_table(rows, pools):
    items = []
    next_id = dict(ID_BLOCKS)

    def add(category, name, grants, classification, default_locked, count=1, lock=None):
        items.append({"id": ITEM_BASE + next_id[category], "name": name, "category": category,
                      "classification": classification, "count": count, "default_locked": default_locked,
                      "grants": grants, "lock": lock or []})
        next_id[category] += 1

    def locked(row):
        return row["extra"].get("own") == "true"

    # Progression items that the client enforces itself (mission availability).
    for z in (2, 3, 4):
        add("progression", f"Zone {z} Access", [], "progression", True)
    add("progression", "Progressive Difficulty", [], "progression", True, count=4)

    # Parent perks: owning the parent asset is what lets its family be offered (verified for Plasma).
    for asset in sorted(a for a in rows if re.fullmatch(r"Perk_[A-Za-z]+_Parent", a)):
        row = rows[asset]
        grants = [object_path(row)]
        if asset in ELEMENT_UNLOCK:
            grants.insert(0, object_path(rows[ELEMENT_UNLOCK[asset]]))
        add("perk", f"Perk: {row['display']}", grants, "useful", locked(row), lock=[object_path(row)])

    for asset in sorted(a for a in rows if a.startswith("Augment_") and not SKIP_AUGMENT.search(a)):
        row = rows[asset]
        add("augment", f"Augment: {row['display']}", [object_path(row)], "useful", locked(row), lock=[object_path(row)])

    for asset in sorted(a for a in rows if re.fullmatch(r"Item_Gun_\w+_Upgradeable|Item_QuickMelee_\w+", a)):
        row = rows[asset]
        add("weapon", f"Weapon: {row['display']}", [object_path(row)], "useful", locked(row), lock=[object_path(row)])
        items[-1]["slot"] = {"EquipSlot.WeaponSlot.1": "primary", "EquipSlot.WeaponSlot.2": "secondary",
                             "EquipSlot.QuickMelee": "melee"}.get(row["extra"].get("slot"), "other")

    progressive_assets = {a for chain in PROGRESSIVE_UNLOCKS.values() for a in chain}
    for asset in sorted(a for a in rows if a.startswith("ItemUnlock_")):
        if asset in progressive_assets or asset in ELEMENT_UNLOCK.values():
            continue
        row = rows[asset]
        add("unlock", row["display"], [object_path(row)], "useful", True)
    for name, chain in PROGRESSIVE_UNLOCKS.items():
        add("unlock", name, [object_path(rows[a]) for a in chain], "useful", True, count=len(chain))
        items[-1]["mode"] = "progressive"  # the k-th copy received grants chain[k]

    for asset in sorted(a for a, r in rows.items() if "Components/Synergies/" in r["package"] + "/"):
        row = rows[asset]
        add("synergy_component", row["display"], [object_path(row)], "useful", True)

    # Grouped categories: the seed splits each pool into random packs; contents go to the client in slot data.
    for category, (label, pool) in GROUPS.items():
        for n in range(1, len(pools[pool]) + 1):
            add(category, f"{label} {n}", [], "useful", True)

    for name, asset, amount in (("Tech Cache", "Item_Currency_Tech", 50), ("Nanite Vial", "Item_Currency_SanctityToken", 1)):
        add("filler", name, [object_path(rows[asset])], "filler", True, count=0)
        items[-1]["amount"] = amount
        items[-1]["mode"] = "add"  # currency: added every time, not just once
    return items


def write_python(missions, items, pools, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write('"""Generated by tools/gen_data.py from the in-game asset catalog. Do not edit by hand."""\n\n')
        f.write(f"ITEM_BASE = {ITEM_BASE}\nLOCATION_BASE = {LOCATION_BASE}\n\n")
        f.write("# Pools split into packs per seed (asset keys; the client maps keys to assets via ap_data.json)\n")
        f.write("GROUP_POOLS = {\n")
        for name, entries in pools.items():
            f.write(f"    {name!r}: {[e['key'] for e in entries]!r},\n")
        f.write("}\n\n")
        f.write("MISSIONS = [\n")
        for m in missions:
            f.write(f"    {{'key': {m['key']!r}, 'name': {m['name']!r}, 'zone': {m['zone']}, 'story': {m['story']}, "
                    f"'endless': {m['endless']}, 'difficulties': {m['difficulties']}, 'prereqs': {m['prereqs']}}},\n")
        f.write("]\n\nITEMS = [\n")
        for it in items:
            f.write(f"    {{'id': {it['id']}, 'name': {it['name']!r}, 'category': {it['category']!r}, "
                    f"'classification': {it['classification']!r}, 'count': {it['count']}, "
                    f"'default_locked': {it['default_locked']}, 'slot': {it.get('slot')!r}}},\n")
        f.write("]\n")


def main():
    rows = load_catalog()
    missions = mission_table(rows)
    pools = group_pools(rows)
    items = items_table(rows, pools)
    names = [i["name"] for i in items]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        sys.exit(f"duplicate item names: {sorted(dupes)}")
    write_python(missions, items, pools, os.path.join(ROOT, "deadzone_rogue", "game_data.py"))
    # Client data ships inside the apworld (the Python client reads it with pkgutil).
    with open(os.path.join(ROOT, "deadzone_rogue", "ap_data.json"), "w", encoding="utf-8") as f:
        json.dump({"item_base": ITEM_BASE, "location_base": LOCATION_BASE,
                   "group_pools": {name: {e["key"]: e["path"] for e in entries} for name, entries in pools.items()},
                   "missions": [{k: m[k] for k in ("key", "name", "guid", "zone", "difficulties", "endless")} for m in missions],
                   "items": {str(i["id"]): {"name": i["name"], "category": i["category"], "grants": i["grants"],
                                            "lock": i["lock"], "default_locked": i["default_locked"],
                                            "mode": i.get("mode", "once"), "amount": i.get("amount", 1)}
                             for i in items}}, f, indent=1)
    per_cat = {}
    for i in items:
        per_cat.setdefault(i["category"], [0, 0])
        per_cat[i["category"]][0 if i["default_locked"] else 1] += 1
    print(f"{len(missions)} missions, {sum(len(m['difficulties']) for m in missions)} mission x difficulty checks")
    for cat, (locked_n, free_n) in per_cat.items():
        print(f"  {cat}: {locked_n} locked by default, {free_n} available by default")


if __name__ == "__main__":
    main()
