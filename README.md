# Deadzone Rogue – Archipelago

An Archipelago integration has two halves:

| Half | What it does | Status |
|---|---|---|
| **APWorld** (`deadzone_rogue/`, Python) | Tells the generator what items and locations exist and what the logic is | v0.5.0: built from the game's real data, passes AP's tests, generates seeds |
| **Client** (Python, in the apworld) + **APClient** (Lua mod) | Talks to the AP server: sends checks, grants received items, locks unreceived content, reports the goal | v0.5.0: mission and save-wide objective checks, grants, locking and zone gating work live, protected by save-slot binding. Reward suppression and DeathLink effects not done yet |

## Files

| Path | What it is |
|---|---|
| [Releases](https://github.com/CaptCapybara-cmd/Archipelago-DeadzoneRogue/releases) | `deadzone_rogue.apworld` (world + client), `APClient-<version>.zip` (in-game mod + UE4SS crash fix) and the template YAML. Install steps: [setup guide](deadzone_rogue/docs/setup_en.md) |
| [Deadzone Rogue.yaml](Deadzone%20Rogue.yaml) | Template player options, to fill in and give to the host |
| `deadzone_rogue/` | World source. `game_data.py` is generated; don't edit it by hand |
| `tools/gen_data.py` | Rebuilds `game_data.py` and `client/ap_data.json` from `dumps/APCatalog.tsv` |
| `client/ap_data.json` | For the client mod: AP id → asset paths to grant or lock, mission GUIDs, pack pools |
| `ue4ss_setup/` | UE4SS crash fix (`VTableLayout.ini`), the catalog/dump/test Lua mods, and the windowed launch script |
| `dumps/` | Header dump, object dump, `.usmap`, asset catalog, hook test log |
| [HOOKS.md](HOOKS.md) | What's verified in-game and how |

## The game, technically

- **Unreal Engine 5.6.1** (internal project name `Valhalla`), game version 1.4.2, by Prophecy Games. No anti-cheat.
- UE4SS needs `ue4ss_setup/VTableLayout.ini` to start (it fixes [UE4SS-RE/RE-UE4SS#1048](https://github.com/UE4SS-RE/RE-UE4SS/issues/1048)).
- Saves are local: `%LOCALAPPDATA%\Valhalla\Saved\SaveGames`, one file per slot. Use a separate slot for AP.

## The APWorld

**Checks**
- Each mission × each difficulty in `mission_difficulties` (Adventure/Normal/Hard by default, up to 5 levels).
  There are 32 missions: 6 story and 26 challenge, across 4 zones.
- Save-wide objectives, counted across every run on your Archipelago save: **Sectors Cleared**, **Enemies Killed**
  (your own kills) and **Scrap Gathered** (pickups; spending doesn't count). Each has a total and an interval
  option, for example a check every 300 kills up to 3000. Total 0 turns one off.
- Endless-wave missions (Gauntlet, Crossfire, Last Stand) only have checks with `include_endless_missions`.

**Items**
- Weapons, perk families and augments as individual items. `*_shuffle` is `none` / `locked_only` / `all`; `all` also
  locks the normally-free ones and gives a starting kit.
- Item / Mastery (Tech upgrade) / Superior Item (SuperItem upgrade) **packs**: random groups per seed, with
  `*_pack_size` options (0 = off). The pack contents go to the client in slot data.
- Unlocks: the Fate rerolls, Fabricator restocks (two progressive chains), Tier 10 Tech Upgrades, Epic Beginnings.
- Optional `Zone N Access` items (zone gating). Difficulties are never gated; each is just a separate check. Logic also follows the game's own mission prerequisites.
- If there are more items than checks, the lowest-priority items are left out (they stay as in the base game):
  synergies, then packs, unlocks, augments, weapons, perks.

**Goal:** complete every story and challenge mission in zones 1 through the chosen zone (`goal: zone_3` or `zone_4`),
on any difficulty. Endless-wave missions never count. A challenge that only exists on one difficulty counts only if
that difficulty has checks. `/goal` in the client lists what's left.

**DeathLink:** `death_link_mode` = lose_perk (default) / lose_item / lose_scrap / take_damage / push_back_room / kill.

### Rebuilding

1. Clone https://github.com/ArchipelagoMW/Archipelago and copy `deadzone_rogue/` into `worlds/`.
2. `pip install -r requirements.txt`
3. If the game updates: rerun the APCatalog mod **with APClient disabled** (its locks would otherwise be recorded as
   the game's defaults), copy the new `APCatalog.tsv` into `dumps/`, then run `python tools/gen_data.py`.
   **Check the item ids it prints. Ids must never change once seeds exist.**
4. Tests: `python -m pytest worlds/deadzone_rogue test/general`
5. Build: `python Launcher.py "Build APWorlds" -- "Deadzone Rogue"`

## The client

- **Deadzone Rogue Client** (`deadzone_rogue/client.py`) shows up in the Archipelago Launcher. It connects to the
  server and exchanges plain-text files with the game in `Win64/APBridge/` (format in `deadzone_rogue/bridge.py`).
- **APClient** (`ue4ss_setup/Mods/APClient`) is the in-game half: hooks for checks, `AddInventoryCount` grants,
  `bRequireOwnership` locks, and per-session/per-save-slot state.
- Install steps for players: `deadzone_rogue/docs/setup_en.md`. What's done and what's left:
  [HOOKS.md](HOOKS.md#client-to-do).

## License

MIT, see [LICENSE](LICENSE). Deadzone: Rogue belongs to Prophecy Games; this project ships no game files.
