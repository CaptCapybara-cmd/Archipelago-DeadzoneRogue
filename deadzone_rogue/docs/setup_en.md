# Deadzone Rogue Setup Guide

## Required software

- Deadzone: Rogue (Steam, PC)
- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases) 0.6.6 or newer
- [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS/releases) experimental build (the `UE4SS_v3.0.1-…zip` from
  "experimental-latest"). The 3.0.1 stable release doesn't support the game's Unreal version.
- From this project's [releases](https://github.com/CaptCapybara-cmd/Archipelago-DeadzoneRogue/releases):
  `deadzone_rogue.apworld` and `APClient-<version>.zip`

## Installing

1. **UE4SS:** extract the UE4SS zip into `Steam\steamapps\common\Deadzone Rogue\Valhalla\Binaries\Win64`, so that
   `dwmapi.dll` and the `ue4ss` folder sit next to `DeadzoneSteam-Win64-Shipping.exe`.
2. **APClient:** extract `APClient-<version>.zip` into the same `Win64` folder. It adds
   `ue4ss\VTableLayout.ini` (without it, UE4SS crashes this game on startup) and the `ue4ss\Mods\APClient` mod,
   which is enabled automatically by its `enabled.txt`.
3. **World:** double-click `deadzone_rogue.apworld`, or put it in Archipelago's `custom_worlds` folder.

## Save slots

Archipelago changes your unlocks. Start a **new save slot** in the game's save menu for each multiworld, and keep
your normal progress in another slot.

The first save slot you play while the client is connected becomes that multiworld's slot. On every other slot
the mod does nothing: no items, no locks, no checks. That keeps your normal saves safe even with the client running.

## Creating a YAML

Use "Generate Template Options" in the Archipelago Launcher, or start from `Deadzone Rogue.yaml` in this
project, and send the result to your host.

## Connecting

1. Open the Archipelago Launcher and start **Deadzone Rogue Client**. Connect with the room's address and your
   slot name.
   - If the game isn't in the default Steam folder, run `/gamedir <path to Valhalla\Binaries\Win64>`.
2. Start the game and pick your Archipelago save slot. `/game` in the client tells you whether the mod is
   talking to it.
3. Received items are granted within a second or two of arriving. Normally-free content you haven't received
   yet is locked.
