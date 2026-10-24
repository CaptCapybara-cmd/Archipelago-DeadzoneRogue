"""Builds DeadzoneRogueLauncher.exe.

Needs the built deadzone_rogue.apworld (in the repo root) and PyInstaller:
    python -m pip install pyinstaller
    python tools/build_launcher.py
Output: build/launcher/dist/DeadzoneRogueLauncher.exe
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(ROOT, "launcher")
PACKAGE = os.path.join(LAUNCHER, "dzr_launcher")
RESOURCES = os.path.join(PACKAGE, "resources")
BUILD = os.path.join(ROOT, "build", "launcher")


def versions() -> dict:
    with open(os.path.join(PACKAGE, "__init__.py"), encoding="utf-8") as f:
        launcher = re.search(r'VERSION = "([^"]+)"', f.read()).group(1)
    with open(os.path.join(ROOT, "deadzone_rogue", "archipelago.json"), encoding="utf-8") as f:
        world = json.load(f)["world_version"]
    with open(os.path.join(ROOT, "ue4ss_setup", "Mods", "APClient", "Scripts", "main.lua"), encoding="utf-8") as f:
        mod = re.search(r"^-- APClient v([0-9][0-9A-Za-z.\-]*)", f.read(), re.M).group(1)
    return {"launcher": launcher, "world": world, "APClient mod": mod}


def copy_resources() -> None:
    apworld = os.path.join(ROOT, "deadzone_rogue.apworld")
    if not os.path.isfile(apworld):
        sys.exit("deadzone_rogue.apworld not found in the repo root; build it first (see README).")
    shutil.rmtree(RESOURCES, ignore_errors=True)
    os.makedirs(os.path.join(RESOURCES, "APClient", "Scripts"))
    shutil.copyfile(os.path.join(ROOT, "ue4ss_setup", "VTableLayout.ini"), os.path.join(RESOURCES, "VTableLayout.ini"))
    shutil.copyfile(os.path.join(ROOT, "ue4ss_setup", "Mods", "APClient", "Scripts", "main.lua"),
                    os.path.join(RESOURCES, "APClient", "Scripts", "main.lua"))
    shutil.copyfile(apworld, os.path.join(RESOURCES, "deadzone_rogue.apworld"))


def main() -> None:
    found = versions()
    if len(set(found.values())) != 1:
        sys.exit(f"Version mismatch, bump them together first: {found}")
    copy_resources()
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
                    "--name", "DeadzoneRogueLauncher",
                    "--distpath", os.path.join(BUILD, "dist"), "--workpath", os.path.join(BUILD, "work"),
                    "--specpath", BUILD, "--paths", LAUNCHER,
                    "--add-data", f"{RESOURCES}{os.pathsep}dzr_launcher/resources",
                    "--add-data", f"{os.path.join(PACKAGE, 'options_schema.json')}{os.pathsep}dzr_launcher",
                    os.path.join(LAUNCHER, "run_launcher.py")], check=True)
    print(f"Built {os.path.join(BUILD, 'dist', 'DeadzoneRogueLauncher.exe')} (v{found['launcher']})")


if __name__ == "__main__":
    main()
