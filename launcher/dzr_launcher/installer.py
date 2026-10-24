"""Installing UE4SS, the crash fix and the APClient mod into the game, and the world into Archipelago.

Everything here is plain functions so it can be tested against a temporary folder."""
import hashlib
import json
import os
import re
import shutil
import urllib.request
import zipfile
from typing import Callable, Dict, Optional

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
UE4SS_RELEASE_API = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/tags/experimental-latest"
# The main UE4SS package ("UE4SS_v3.0.1-1181-g83330635.zip"), not the zDEV / zCustomGameConfigs extras.
UE4SS_ASSET = re.compile(r"^UE4SS_v[0-9][^/]*\.zip$")
# Files a UE4SS update must not overwrite: the player's settings and mod list.
KEEP_IF_PRESENT = {"ue4ss/UE4SS-settings.ini", "ue4ss/Mods/mods.txt", "ue4ss/Mods/mods.json"}
APCLIENT_VERSION = re.compile(r"^-- APClient v([0-9][0-9A-Za-z.\-]*)", re.M)

Progress = Callable[[str], None]


def resource(*parts: str) -> str:
    return os.path.join(RESOURCES, *parts)


# Status ----------------------------------------------------------------------------------------------------------

def apclient_version(main_lua_path: str) -> Optional[str]:
    try:
        with open(main_lua_path, encoding="utf-8") as f:
            found = APCLIENT_VERSION.search(f.read(4096))
    except OSError:
        return None
    return found.group(1) if found else "unknown"


def status(win64: str) -> Dict[str, object]:
    ue4ss = os.path.join(win64, "ue4ss")
    fix = os.path.join(ue4ss, "VTableLayout.ini")
    bundled_fix = resource("VTableLayout.ini")
    return {
        "ue4ss": os.path.isfile(os.path.join(win64, "dwmapi.dll")) and os.path.isfile(os.path.join(ue4ss, "UE4SS.dll")),
        "crash_fix": os.path.isfile(fix) and (not os.path.isfile(bundled_fix) or _same_file(fix, bundled_fix)),
        "apclient": apclient_version(os.path.join(ue4ss, "Mods", "APClient", "Scripts", "main.lua")),
        "bundled_apclient": apclient_version(resource("APClient", "Scripts", "main.lua")),
    }


def _same_file(a: str, b: str) -> bool:
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read().replace(b"\r\n", b"\n") == fb.read().replace(b"\r\n", b"\n")


# UE4SS -----------------------------------------------------------------------------------------------------------

def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                  "User-Agent": "DeadzoneRogueLauncher"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def latest_ue4ss_asset(release: Optional[dict] = None) -> dict:
    """{name, url, sha256, size} of the UE4SS package in the official experimental release."""
    release = release or _get_json(UE4SS_RELEASE_API)
    for asset in release.get("assets", []):
        if UE4SS_ASSET.match(asset["name"]):
            digest = asset.get("digest") or ""
            if not digest.startswith("sha256:"):
                raise RuntimeError(f"GitHub didn't publish a checksum for {asset['name']}; not installing it.")
            return {"name": asset["name"], "url": asset["browser_download_url"],
                    "sha256": digest.split(":", 1)[1].lower(), "size": asset["size"]}
    raise RuntimeError("No UE4SS package found in the official experimental release.")


def download_verified(asset: dict, dest_dir: str, progress: Progress = print) -> str:
    """Downloads an asset and checks its SHA-256 against the published digest; raises if it doesn't match."""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, asset["name"])
    progress(f"Downloading {asset['name']} ({asset['size'] // 1024 // 1024} MB) from github.com/UE4SS-RE...")
    request = urllib.request.Request(asset["url"], headers={"User-Agent": "DeadzoneRogueLauncher"})
    sha = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, open(path, "wb") as out:
        while chunk := response.read(1 << 16):
            sha.update(chunk)
            out.write(chunk)
    if sha.hexdigest() != asset["sha256"]:
        os.remove(path)
        raise RuntimeError(f"Checksum mismatch for {asset['name']}; the download was discarded.")
    progress("Download verified (SHA-256 matches GitHub's published digest).")
    return path


def install_ue4ss(win64: str, zip_path: str, progress: Progress = print) -> None:
    """Extracts dwmapi.dll and the ue4ss folder next to the game exe. Keeps the player's settings and mod list."""
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            name = member.filename.replace("\\", "/")
            if member.is_dir() or name.startswith("/") or ".." in name.split("/"):
                continue
            if not (name == "dwmapi.dll" or name.startswith("ue4ss/")):
                continue
            target = os.path.join(win64, *name.split("/"))
            if name in KEEP_IF_PRESENT and os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    progress("UE4SS installed.")


# Crash fix and APClient --------------------------------------------------------------------------------------------

def install_crash_fix(win64: str, progress: Progress = print) -> None:
    shutil.copyfile(resource("VTableLayout.ini"), os.path.join(win64, "ue4ss", "VTableLayout.ini"))
    progress("Crash fix (VTableLayout.ini) installed.")


def install_apclient(win64: str, progress: Progress = print) -> None:
    mod = os.path.join(win64, "ue4ss", "Mods", "APClient")
    os.makedirs(os.path.join(mod, "Scripts"), exist_ok=True)
    shutil.copyfile(resource("APClient", "Scripts", "main.lua"), os.path.join(mod, "Scripts", "main.lua"))
    open(os.path.join(mod, "enabled.txt"), "w").close()
    _enable_in_mods_txt(os.path.join(win64, "ue4ss", "Mods", "mods.txt"))
    progress(f"APClient mod v{apclient_version(os.path.join(mod, 'Scripts', 'main.lua'))} installed.")


def _enable_in_mods_txt(path: str) -> None:
    """enabled.txt switches the mod on, but an explicit 'APClient : 0' in mods.txt would override it."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    fixed = re.sub(r"(?m)^APClient\s*:\s*0\s*$", "APClient : 1", text)
    if fixed != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(fixed)


def install_all(win64: str, work_dir: str, reinstall_ue4ss: bool = False, progress: Progress = print) -> None:
    if reinstall_ue4ss or not status(win64)["ue4ss"]:
        install_ue4ss(win64, download_verified(latest_ue4ss_asset(), work_dir, progress), progress)
    else:
        progress("UE4SS already installed (kept).")
    install_crash_fix(win64, progress)
    install_apclient(win64, progress)


def uninstall(win64: str, progress: Progress = print) -> None:
    """Removes UE4SS (dwmapi.dll and the ue4ss folder, including APClient). Keeps APBridge, which holds the
    per-save Archipelago progress (received items, objective totals)."""
    dll = os.path.join(win64, "dwmapi.dll")
    if os.path.isfile(dll):
        os.remove(dll)
    shutil.rmtree(os.path.join(win64, "ue4ss"), ignore_errors=True)
    progress("UE4SS and the APClient mod were removed. Your Archipelago progress (APBridge folder) was kept.")


# Archipelago -------------------------------------------------------------------------------------------------------

def install_apworld(archipelago: str, progress: Progress = print) -> str:
    target_dir = os.path.join(archipelago, "custom_worlds")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "deadzone_rogue.apworld")
    shutil.copyfile(resource("deadzone_rogue.apworld"), target)
    progress(f"World installed to {target}.")
    return target
