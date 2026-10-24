# Deadzone: Rogue – hook candidates for the Archipelago client

Game 1.4.2, build `Valhalla-5.6.1-261064+++Valhalla+Rogue-Release-1.4` (Unreal 5.6.1). Game C++ module: `/Script/Valhalla`.
Sources: `dumps/CXXHeaderDump/Valhalla.hpp` (UE4SS C++ header dump) and `dumps/APCatalog.tsv` (every mission, item and upgrade asset, with GUIDs and display names).

> Status: these come from the headers and the asset catalog. The two core hooks were **verified live on 2026-10-24** (solo, save slot 2) with `ue4ss_setup/Mods/APHookTest`; the log is in `dumps/APHookTest.log`. The rest haven't been tested yet.

## Live test results (2026-10-24)

| Hook | Result |
|---|---|
| `UValMissionComponent::OnMissionCompleted(AValMission*)` | ✅ Fires once per completion and carries everything a check needs: `MissionId` GUID, `Tier`, `Difficulty`, `MissionData` (`Mission_Zone1_Story`, "Who am I?"). Seen at difficulties 2 and 3. `AValMission::SetCompleted` fires just before it. |
| `UValMissionComponent::OnMissionReady(AValMission*)` | ✅ Fires on mission start with the same parameters (tracks which mission/tier/difficulty is being played). |
| `AValMission::ForceComplete()` (called from Lua) | ✅ Completes the mission properly: rewards are granted and the slot saves. Useful for testing. |
| `UValInventoryComponent::AddInventoryCount(AssetId, Count)` (called from Lua) | ⚠️ **Saved to data, but not confirmed in the game itself.** The inventory count changes and is saved: slot 2's file stores `Plasma = 2`, alongside `Tech = 250`, which matches the logged Tech reward. An item whose asset is loaded applies immediately; an unloaded one waits in `PendingInventoryMap` for about 4 s. **However, the player didn't see the Plasma unlock in-game**, so the UI or the unlock logic may read something else (an "owned" flag, a cached view, or a refresh on returning to the hub). **Scrap isn't in the save at all**; it seems to be a per-run currency held elsewhere (see `AValGameMode::AwardCurrency`). No limits are enforced (the unlock reached 2), so check `IsItemAtLimit` first. **Next:** find where the game reads unlocks for display and use. |
| `UValPlayerUpgradeComponent::OnInventoryChanged` | ✅ Reports real inventory changes (`Tech` +50 / +100 from mission rewards, the Plasma grant). Good for detecting the game's own unlocks. |
| **Element perk unlock (A/B tested)** | ✅ **The perk generator checks ownership of the parent perk asset (`Perk_Plasma_Parent`), not the unlock item.** Locked parents have `bRequireOwnership = true` (Plasma, Psionic); starter ones like `Perk_Fire_Parent` don't. Draws of 3 parent perks via F2 (`SpawnAugmentBundle`) gave: parent owned → Plasma in 4 of 11 draws (including 3 of 4 with the unlock item removed); parent removed → Plasma in 0 of 8 draws. Granting `ItemUnlock_PlasmaElement` with `AddInventoryCount` also made the game add `Perk_Plasma_Parent` (count 1, never granted directly), but removing the unlock doesn't remove the perk. **AP client:** grant the unlock item (UI and save consistency), then check that `GetItemCount(Perk_<Element>_Parent.ItemId) ≥ 1` and grant the parent perk directly if it isn't. |
| **Locking default content (runtime)** | ✅ Setting `bRequireOwnership = true` on a normally-free asset from Lua locks it: with `Perk_Fire_Parent` flipped and not owned, Fire appeared in 0 of 6 draws (8 of 19 before); flipped back, it returned in 3 of 6. Keep a Lua reference to the asset so it isn't reloaded with its default flag, and re-apply on mission start to be safe. |
| Perk bundle flow | `PerkConfig_Long_Default`: pick 1 = augment (once per run), picks 2–4 = parent perks (`ID.Perk.Type.Parent`), pick 5+ = child perks. Calling `UValAugmentComponent::SpawnAugmentBundle(PlayerState, Pawn, out)` at pick 2–4 spawns a real `BP_Pickup_Bundle_Perks` with 3 parents; it doesn't advance the pick count until one is taken. In-run families seen on a fresh slot: Fire, Cryo, Lightning, Void, Pet, Grenade, Ninja, Health, WeaponMaster (+ Plasma when owned). |
| Reroll unlock | `ItemUnlock_RerollPerk` ("Intentional Fate") granted with `AddInventoryCount` (count 1). Bundles that already exist keep `GetRerollsRemaining() = 0`; it should apply to bundles spawned afterwards (not yet confirmed). | Note that **augments are a separate system**: `UValAugmentComponent::GenerateAugmentItems` only rolls `Augment_*` weapon modifiers, and the Plasma unlock didn't affect them (40 + 40 rolls). Augments are offered **once per run**. Spawning augment bundles from Lua uses up that run's offer, so the real augment room then spawns nothing (log: "Unable to generate any augment ids"). The client must never spawn augment bundles. |
| `AValGameState_SpaceDungeon::IncrementEncountersCleared` | ✅ Fired +1 on every room clear across two runs (8 rooms), followed about 1 s later by that room's reward bundle (equipment, items or augment). Usable for "Room N cleared" checks. |
| `UValCheatComponent` (`AddCurrency` / `AddItemCount` / `ActivateUpgrade`) | ❌ No instance exists in the shipping game, so it can't be used. |
| `BroadcastBossDied` | Not reached yet (no boss fought). Still untested. |

## Getting UE4SS to run (done)

The stock UE4SS experimental build crashes on this game at start-up ([UE4SS issue #1048](https://github.com/UE4SS-RE/RE-UE4SS/issues/1048), open since Oct 2025). The game's `FMalloc` vtable has one more `Exec` slot than UE4SS expects, so UE4SS's `Free` lands on `TryRealloc` → "Ran out of memory allocating <pointer> bytes".

Fix: `ue4ss_setup/VTableLayout.ini`, copied into `Valhalla/Binaries/Win64/ue4ss/`. It was derived by reading the live `GMalloc` vtable (`ue4ss_setup/vtable.py`). It gives `Malloc` = +0x30 and `Free` = +0x50; note that UE4SS counts `__vecDelDtor` as two slots.

Launch windowed: `bash ue4ss_setup/launch.sh` → `DeadzoneSteam.exe -windowed -ResX=1280 -ResY=720`. The script waits for any previous instance to fully exit first; starting while Steam still sees the old one running makes the new one quit silently.

## Locations (things the player does → send a check)

| Event | Hook | Notes |
|---|---|---|
| **Mission completed** | `UValMissionComponent::OnMissionCompleted(AValMission*)` or `AValMission::SetCompleted()` | `AValMission.r_MissionParameters` (`FValMissionParameters`) gives `MissionId` (GUID), `Tier`, `Difficulty`, `MissionData`. This is the main location source. |
| Mission failed | `UValMissionComponent::OnMissionFailed(AValMission*)` | For DeathLink, or to ignore. |
| Mission rewards granted | `UValMissionComponent.OnMissionRewards` delegate `(Params, MissionsUnlocked[], RewardEntries[] …)` | Shows what the game itself unlocks, which we suppress or replace. |
| Encounter / room cleared | `AValGameState_SpaceDungeon::IncrementEncountersCleared(int32)` / `GetNumberOfEncountersCleared()` | For "Encounter N cleared" checks within a run. |
| Boss killed | `AValGameState_SpaceDungeon::BroadcastBossDied(APawn* BossPawn)` | Five `ValBossBotData` assets exist. |
| Waves complete | `AValGameState_DungeonWaves::SetWavesComplete(bool)` | Wave-type missions. |
| Player died / extracted | `EFrontierState` (`Died`, `Extracted`, `TeamEliminated` …) via `UValMissionComponent::OnFrontierState` | DeathLink, both sending and receiving. |
| Activity (achievement) done | `UValActivity.OnCompleted` (81 `Activity_*` classes, each with `ActivityId` GUID) | Optional bonus checks; they mirror Steam achievements. |
| Bonus objective / bonus room | `AValBonusRoom_Objective`, `FValMissionBonusObjective` | Optional. |

## Items (AP sends something → grant it in game)

| Grant | Hook | Notes |
|---|---|---|
| **Add any item / currency** | `UValInventoryComponent::AddInventoryCount(FPrimaryAssetId AssetId, int32 Count)` | Inventory is `TMap<FGuid,int32>`. Every `UValDataAsset` has `ItemId` (GUID) and `AssetId`. |
| Read ownership | `GetItemCount(FGuid)`, `BLUEPRINT_GetInventory(TMap&)`, `OnInventoryChanged` delegate | For resync, and to tell whether an unlock came from AP. |
| Meta upgrades | `UValPlayerUpgradeComponent::SetUpgradeValue(FGuid UpgradeId, int32 Value)` / `RequestPurchase(FGuid)` | 103 `ValPlayerUpgradeAsset`s. `SetUpgradeValue` can apply "Progressive X" items directly. |
| Mission gating | `UValMissionComponent.r_MissionOptions` (`FValMissionOption.bAvailable`), `UValMissionData.MissionPrerequisites`, `GetItemUnlockMission(ItemId → difficulty, milestone)` | To make zones and missions depend on AP items, force `bAvailable=false` until the item arrives. |

## Real content (from `dumps/APCatalog.tsv`)

- **Missions (32):** 6 story missions in a chain (Zone 1 "Who am I?" → Zone 2 "Keep it Together" → Zone 3 "Get Out of My Head" → Zone 4 "Prelude" → "Distress Call" → "Getting Answers"), plus 26 challenge missions ("Close Quarters", "Headhunter", "Gauntlet", "Ultra Nightmare" …). Each challenge unlocks from a story mission. Most are playable at difficulties 1–5; a few only at one.
- **Weapons (31):** for example AR-70 Vanguard, M-150 Headhunter, Titan-10 Hellstorm, Plasma Cycler, Energy Axe, Arc Lance.
- **Unlocks (17, `Items/Unlocks`):** Element Unlock: Plasma/Psionic/Radiation, the "… Fate" rerolls, Fabricator restocks, Tier 10 Tech Upgrades, Epic Beginnings.
- **Meta upgrades (103):** Maximum Health, Maximum Shields, Weapon Damage, Rabbit Foot, Space Whiskey …
- Also: 36 epic items, 19 tech components, 44 synergies, and the currencies Scrap, Tech and Nanite Vial (`Items/Currencies`).

### Suggested AP mapping (to replace the placeholder world)

- **Locations:** each mission × difficulty (about 130), plus optional encounter, boss and activity checks.
- **Progression items:** zone and story-mission access, element unlocks, and maybe key weapons.
- **Useful items:** weapons, Fate and restock unlocks, "Progressive <upgrade>" items.
- **Filler:** Scrap, Tech, Nanite Vials.
- **Goal:** complete every story and challenge mission through zone 3 or 4. The 3 endless-wave missions
  (`BP_Mission_Endless`: Gauntlet, Crossfire, Last Stand) are excluded.

## Persistence and safety

- Saves are local: `%LOCALAPPDATA%/Valhalla/Saved/SaveGames/ValSaveGame@steam3228590#<id>-<slot>.sav`, synced by Steam Cloud. AP play should use a dedicated slot (or a backed-up copy) so your real progress isn't changed.
- The game also talks to RallyHere (an online backend), but offline it logs "missing auth context" and keeps working.
- Test solo. Co-op means other players' inventories, which is out of scope for now.

## Client to-do

What the client mod has to do for the v0.2.0 world. The status column says how much of each is already proven.

| Job | How | Status |
|---|---|---|
| Send mission checks | `OnMissionCompleted` → `mission <key> <difficulty>` in the outbox → location id | ✅ **done** (APClient + client): live mission completion reached the outbox, and outbox → server is tested |
| Save-wide objectives | Sectors: `IncrementEncountersCleared` ("sectors cleared" is the game's own name, see `UI_Game_SectorTracker`). Kills: `UValPlayerUpgradeComponent::OnBotKilled` where the killer is the local player's pawn. Scrap: increases of `Item_Currency_Scrap` in `OnInventoryChanged`. Totals are kept per session and save slot in the state file, and sent every 5 s as `sectors|kills|scrap <total>` | ✅ counting verified live |
| Goal | The client rebuilds the set of completed missions (any difficulty) from this session's outbox and sends `StatusUpdate(CLIENT_GOAL)` once every goal mission is in it | ✅ done in code (tested offline) |
| Grant weapons / perks / augments / unlocks | `AddInventoryCount` per resolved asset path. One-time unlocks are re-checked every 30 s and restored if missing (this survived a live save reset). Currency is applied once per received index | ✅ **done**: 13 live grants (weapons, perks, augments, unlocks), no duplicates on reload |
| Lock normally-free content | `bRequireOwnership = true` on every free asset in shuffled categories, reapplied on mission start | ✅ **done, verified in a real run**: with a 2-weapon / 3-augment / 5-perk kit, the weapon bundle offered only the 2 owned weapons, the augment room exactly the 3 owned augments, and the perk room only owned families (Bot Companion, Fire, Ironblood Engine). Bundles show fewer than 3 options when fewer are owned |
| Packs | `slot_data.packs`: AP item id → asset keys (paths in `ap_data.json → group_pools`). Grant all on receipt, and lock the unreceived ones the same way | ⚠️ items/Tech/SuperItem gating via ownership not yet tested |
| Suppress vanilla mission rewards | Unless `vanilla_mission_rewards`: stop `GiveFirstAttemptRewards` / milestone rewards (or remove what they add) | ❌ not investigated |
| Zone gating | After the game builds `UValMissionComponent.r_MissionOptions` (post-hooks on `UpdateHostMissionOptions` / `GetMissionOptions`, deferred 250 ms), set `bAvailable = false` on missions (matched by `MissionId` GUID) in zones without Zone Access. When the open zones change, call `UpdateHostMissionOptions(inventory)` so the game rebuilds and the gate re-applies | ✅ **done, verified live**: Keep it Together showed locked, then became selectable in the hub the moment Zone 2 Access arrived |
| Zone entry missions | Inbox `zoneentry <guid>` lines (each zone's first story mission, zones up to the goal). When that zone is open, the gate also sets `bAvailable = true` on the option, its tiers and each tier's lowest difficulty, so Zone Access opens it without the earlier story missions | ✅ verified live: Prelude selectable with Zone 4 Access and zone 2/3 story not done. ⚠️ completing it out of order not yet tested |
| In-game messages | `ClientReceiveTextChatMessage(pc.PlayerState, "[Archipelago] …")` on the local `ValPlayerController`, after forcing `bTextChatEnabled` (off in solo). The client writes `note <id> <text>` lines for item sends/receives; the mod posts unseen ones (5 at most) and stores the last id in the state file. F10 posts a status line | ✅ verified live |
| Difficulty gating | Removed by design: difficulties are separate checks, not gated | — |
| DeathLink send | `OnFrontierState` → `Died` | ✅ hook registered, not yet seen firing |
| DeathLink receive | Per `death_link_mode`: remove a run perk or item, halve Scrap, apply damage, move back a room, or kill | ❌ not investigated. `push_back_room` may not be feasible |
| Never spawn augment bundles | Each run gets one augment offer; spawning bundles uses it up | ⚠️ rule |

| Save-slot binding | Each AP session binds to the first save slot it's used on (`APBridge/binding_<session>.txt`). On any other slot the mod restores its locks, doesn't gate and sends no checks. It waits for `ValSaveGameSubsystem.bSubsystemLoadComplete`, because before that the active slot reads as 0 | ✅ done, verified (bound to slot 2) |
| ⚠️ Never touch `MissionOption.MissionData` from Lua | It can be null while the hub loads, and dereferencing it crashed the game inside UE4SS. Use the inline `MissionId` GUID | rule || Launcher (planned) | One app for players: locate the game, install UE4SS + `VTableLayout.ini` + APClient, and a GUI for the player YAML options | ❌ not started |
| Launcher | `DeadzoneRogueLauncher.exe`: finds the game through Steam, installs UE4SS (official release, SHA-256 checked), the crash fix and APClient while keeping the player's UE4SS settings and mod list; installs the world into Archipelago; options form generated from the world, saves the YAML | ✅ done: YAML accepted by Archipelago's generator, UE4SS download + install tested in a scratch folder |
