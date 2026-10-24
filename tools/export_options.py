"""Exports the world's player options as JSON for the launcher's YAML form.

Run from an Archipelago source checkout that has deadzone_rogue in worlds/:
    python <this repo>/tools/export_options.py <output.json>
"""
import inspect
import json
import os
import sys

sys.path.insert(0, os.getcwd())

import ModuleUpdate  # noqa: F401,E402  (Archipelago's import-time setup)
import Options  # noqa: E402
from worlds.deadzone_rogue import DeadzoneRogueWorld  # noqa: E402
from worlds.deadzone_rogue.locations import DIFFICULTY_NAMES  # noqa: E402
from worlds.deadzone_rogue.options import option_groups  # noqa: E402

# Common Archipelago options worth showing; the rest (item links, plando, hint lists) are for advanced YAMLs.
COMMON = {"progression_balancing": "Archipelago", "accessibility": "Archipelago"}


def describe(name: str, cls) -> dict:
    entry = {"name": name, "label": getattr(cls, "display_name", name), "help": inspect.cleandoc(cls.__doc__ or "")}
    if issubclass(cls, Options.Toggle):
        entry.update(kind="toggle", default=bool(cls.default))
    elif issubclass(cls, Options.Choice):
        names = [cls.name_lookup[value] for value in sorted(cls.name_lookup)]
        entry.update(kind="choice", choices=names, default=cls.name_lookup[cls.default])
    elif issubclass(cls, Options.Range):
        entry.update(kind="range", min=cls.range_start, max=cls.range_end, default=int(cls.default))
    elif issubclass(cls, Options.OptionSet):
        order = list(DIFFICULTY_NAMES.values())  # difficulties easiest first; anything else alphabetically
        key = (lambda k: (order.index(k) if k in order else len(order), k))
        entry.update(kind="set", choices=sorted(cls.valid_keys, key=key), default=sorted(cls.default, key=key))
    else:
        return {}
    return entry


def main(out_path: str) -> None:
    group_of = {cls: group.name for group in option_groups for cls in group.options}
    options = []
    for name, cls in DeadzoneRogueWorld.options_dataclass.type_hints.items():
        own = name in DeadzoneRogueWorld.options_dataclass.__annotations__ or name == "death_link"
        if not own and name not in COMMON:
            continue
        entry = describe(name, cls)
        if entry:
            entry["group"] = group_of.get(cls, COMMON.get(name, "DeathLink" if name == "death_link" else "Other"))
            options.append(entry)
    order = [g.name for g in option_groups] + ["DeathLink", "Archipelago", "Other"]
    options.sort(key=lambda o: order.index(o["group"]) if o["group"] in order else len(order))
    schema = {"game": DeadzoneRogueWorld.game, "requires_version": "0.6.6", "options": options}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=1)
    print(f"{len(options)} options exported to {out_path}")


if __name__ == "__main__":
    main(sys.argv[1])
