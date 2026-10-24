"""Turning option values from the launcher's form into an Archipelago player YAML."""
import json
import os
from typing import Dict, List, Optional

from . import VERSION

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "options_schema.json")
MAX_NAME_LENGTH = 16  # Archipelago's slot name limit


def load_schema(path: str = SCHEMA_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def defaults(schema: dict) -> Dict[str, object]:
    return {o["name"]: o["default"] for o in schema["options"]}


def validate(schema: dict, name: str, values: Dict[str, object]) -> List[str]:
    """Problems that would make Archipelago reject the YAML (empty list = fine)."""
    problems = []
    if not name.strip():
        problems.append("Enter a slot name (the name you'll connect with).")
    elif len(name) > MAX_NAME_LENGTH:
        problems.append(f"The slot name can be at most {MAX_NAME_LENGTH} characters.")
    for option in schema["options"]:
        value = values.get(option["name"], option["default"])
        if option["kind"] == "range" and not (option["min"] <= int(value) <= option["max"]):
            problems.append(f"{option['label']} must be between {option['min']} and {option['max']}.")
        elif option["kind"] == "choice" and value not in option["choices"]:
            problems.append(f"{option['label']}: pick one of {', '.join(option['choices'])}.")
        elif option["kind"] == "set" and option["name"] == "mission_difficulties" and not value:
            problems.append("Pick at least one mission difficulty.")
    return problems


def _yaml_value(option: dict, value: object) -> str:
    if option["kind"] == "toggle":
        return "true" if value else "false"
    if option["kind"] == "range":
        return str(int(value))
    if option["kind"] == "set":
        ordered = [c for c in option["choices"] if c in value]
        return "[" + ", ".join(json.dumps(c) for c in ordered) + "]"
    return str(value)


def render(schema: dict, name: str, values: Dict[str, object], description: Optional[str] = None) -> str:
    """The YAML text. Strings are written JSON-quoted, which is valid YAML for any slot name."""
    lines = [f"# {schema['game']} options, made with the Deadzone Rogue Launcher v{VERSION}",
             f"name: {json.dumps(name.strip())}",
             f"description: {json.dumps(description or 'Made with the Deadzone Rogue Launcher')}",
             f"game: {json.dumps(schema['game'])}",
             "requires:",
             f"  version: {schema['requires_version']}",
             f"{json.dumps(schema['game'])}:"]
    group = None
    for option in schema["options"]:
        if option["group"] != group:
            group = option["group"]
            lines.append(f"  # {group}")
        lines.append(f"  {option['name']}: {_yaml_value(option, values.get(option['name'], option['default']))}")
    return "\n".join(lines) + "\n"
