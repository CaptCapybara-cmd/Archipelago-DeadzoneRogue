"""Finding Deadzone: Rogue (through Steam's library list) and an Archipelago install."""
import os
import re
from typing import List, Optional

APP_ID = "3228590"
WIN64_SUBDIR = os.path.join("Valhalla", "Binaries", "Win64")
GAME_EXE = "DeadzoneSteam-Win64-Shipping.exe"
DEFAULT_STEAM = r"C:\Program Files (x86)\Steam"


def steam_path() -> Optional[str]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            return os.path.normpath(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return DEFAULT_STEAM if os.path.isdir(DEFAULT_STEAM) else None


def library_folders(vdf_text: str) -> List[str]:
    """Library paths from steamapps/libraryfolders.vdf ("path" entries, with VDF's escaped backslashes)."""
    return [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', vdf_text)]


def manifest_installdir(acf_text: str) -> Optional[str]:
    found = re.search(r'"installdir"\s+"([^"]+)"', acf_text)
    return found.group(1) if found else None


def find_game_win64(steam: Optional[str] = None) -> Optional[str]:
    """The game's Valhalla/Binaries/Win64 folder (where the exe and UE4SS go), or None."""
    steam = steam or steam_path()
    if not steam:
        return None
    libraries = []
    try:
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8") as f:
            libraries += library_folders(f.read())  # these keep the real capitalisation; the registry's is lowercase
    except OSError:
        pass
    libraries.append(steam)
    seen = set()
    for library in (os.path.normpath(p) for p in libraries):
        if os.path.normcase(library) in seen:
            continue
        seen.add(os.path.normcase(library))
        manifest = os.path.join(library, "steamapps", f"appmanifest_{APP_ID}.acf")
        try:
            with open(manifest, encoding="utf-8") as f:
                installdir = manifest_installdir(f.read())
        except OSError:
            continue
        if installdir:
            win64 = os.path.join(library, "steamapps", "common", installdir, WIN64_SUBDIR)
            if is_game_win64(win64):
                return win64
    return None


def is_game_win64(folder: str) -> bool:
    return bool(folder) and os.path.isfile(os.path.join(folder, GAME_EXE))


def normalize_game_folder(folder: str) -> Optional[str]:
    """Accepts the game's root folder or its Win64 folder; returns the Win64 folder."""
    for candidate in (folder, os.path.join(folder, WIN64_SUBDIR)):
        if is_game_win64(candidate):
            return os.path.normpath(candidate)
    return None


def find_archipelago() -> Optional[str]:
    """Archipelago's install folder (the one with ArchipelagoLauncher.exe), or None."""
    candidates = [r"C:\ProgramData\Archipelago", os.path.expandvars(r"%LOCALAPPDATA%\Archipelago"),
                  os.path.expandvars(r"%PROGRAMFILES%\Archipelago")]
    return next((c for c in candidates if is_archipelago(c)), None)


def is_archipelago(folder: str) -> bool:
    return bool(folder) and os.path.isfile(os.path.join(folder, "ArchipelagoLauncher.exe"))
