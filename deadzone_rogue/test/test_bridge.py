import os
import shutil
import tempfile
import threading
import unittest

from .. import bridge
from ..items import item_name_to_id
from ..locations import location_name_to_id


class TestBridge(unittest.TestCase):
    data = bridge.load_data()
    slot_data = {"goal_zone": 4, "goal_missions": ["Mission_Zone1_Story", "Mission_Zone2_Story"],
                 "difficulties": [1, 2, 3], "objectives": {"sectors": [10, 30], "kills": [300, 900], "scrap": [0, 0]},
                 "lock_free": ["perk"], "packs": {}}

    def test_location_ids_match_the_world(self) -> None:
        self.assertEqual(bridge.mission_location(self.data, "Mission_Zone1_Story", 2),
                         location_name_to_id["Who am I? (Normal)"])
        self.assertEqual(bridge.objective_locations("kills", 650, 300, 900),
                         [location_name_to_id["Enemies Killed: 300"], location_name_to_id["Enemies Killed: 600"]])
        self.assertEqual(len(bridge.objective_locations("sectors", 500, 10, 30)), 3)  # capped by the seed's total
        self.assertEqual(bridge.objective_locations("scrap", 50000, 0, 0), [])  # objective off
        # sector checks keep the ids of the old "Rooms Cleared" checks
        self.assertEqual(location_name_to_id["Sectors Cleared: 5"], self.data["location_base"] + 1001)

    def test_checks_from_outbox(self) -> None:
        events = bridge.parse_outbox("mission Mission_Zone1_Story 2\nmission Mission_Zone1_Story 5\n"
                                     "sectors 12\nkills 320\nrooms 21\ndeath 100\ndeath 300\n")
        locations, completed, deaths = bridge.checks_from_events(self.data, self.slot_data, events, since=200)
        self.assertIn(bridge.mission_location(self.data, "Mission_Zone1_Story", 2), locations)
        self.assertNotIn(bridge.mission_location(self.data, "Mission_Zone1_Story", 5), locations)  # not enabled
        self.assertIn(location_name_to_id["Enemies Killed: 300"], locations)
        self.assertIn(location_name_to_id["Sectors Cleared: 20"], locations)  # old "rooms" lines still count
        self.assertEqual(completed, {"Mission_Zone1_Story"})  # difficulty 5 still counts for the goal
        self.assertEqual(deaths, 1)  # the one before `since` is old

    def test_goal_needs_every_goal_mission(self) -> None:
        self.assertFalse(bridge.goal_complete(self.slot_data, {"Mission_Zone1_Story"}))
        self.assertTrue(bridge.goal_complete(self.slot_data, {"Mission_Zone1_Story", "Mission_Zone2_Story", "x"}))
        self.assertFalse(bridge.goal_complete({}, {"Mission_Zone1_Story"}))

    def test_grants(self) -> None:
        received = [item_name_to_id["Perk: Plasma"], item_name_to_id["Progressive Loot Orb Tech Reroll"],
                    item_name_to_id["Progressive Loot Orb Tech Reroll"], item_name_to_id["Tech Cache"],
                    item_name_to_id["Zone 2 Access"]]
        lines = bridge.grant_lines(self.data, self.slot_data, received)
        paths = [(i, mode, amount, path.rsplit(".", 1)[1]) for i, mode, amount, path in lines]
        self.assertIn((0, "once", 1, "ItemUnlock_PlasmaElement"), paths)
        self.assertIn((0, "once", 1, "Perk_Plasma_Parent"), paths)
        self.assertIn((1, "once", 1, "ItemUnlock_RerollLootOrb_TechA"), paths)
        self.assertIn((2, "once", 1, "ItemUnlock_RerollLootOrb_TechB"), paths)
        self.assertIn((3, "add", 50, "Item_Currency_Tech"), paths)
        self.assertFalse([p for p in paths if p[0] == 4])  # zone access has nothing to grant in-game

    def test_pack_grants_and_locks(self) -> None:
        pack_id = str(item_name_to_id["Item Pack 1"])
        slot_data = dict(self.slot_data, packs={pack_id: ["Item_ADSSpeed", "Item_CritChance"]})
        lines = bridge.grant_lines(self.data, slot_data, [int(pack_id)])
        self.assertEqual([p.rsplit(".", 1)[1] for _, _, _, p in lines], ["Item_ADSSpeed", "Item_CritChance"])
        locks = bridge.lock_paths(self.data, slot_data)
        self.assertTrue(any(p.endswith("Perk_Fire_Parent") for p in locks))  # perk lock_free
        self.assertFalse(any(p.endswith("Perk_Plasma_Parent") for p in locks))  # locked by the game already
        self.assertTrue(any(p.endswith("Item_ADSSpeed") for p in locks))  # pack contents

    def test_leveled_pack_copies_raise_levels_in_chunks(self) -> None:
        pack_id = str(item_name_to_id["Mastery Pack 1"])
        superior_id = str(item_name_to_id["Superior Item Pack 1"])
        slot_data = dict(self.slot_data, packs={pack_id: ["Component_Tech_MaxShield"],
                                                superior_id: ["Component_SuperItem_HealthBasedDamage"]},
                         pack_levels={pack_id: 3, superior_id: 3})
        received = [int(pack_id)] * 5 + [int(superior_id)] * 2
        levels = [(i, amount, path.rsplit(".", 1)[1]) for i, mode, amount, path
                  in bridge.grant_lines(self.data, slot_data, received) if mode == "level"]
        self.assertEqual([amount for _, amount, name in levels if name == "Upgrade_MaxShield"], [3, 6, 9, 10, 10])
        self.assertEqual([amount for _, amount, name in levels if name.startswith("SuperItem_")], [3, 4])
        unlocks = [p for _, mode, _, p in bridge.grant_lines(self.data, slot_data, received[:1]) if mode == "once"]
        self.assertTrue(unlocks[0].endswith("Component_Tech_MaxShield"))
        self.assertIn("noupgradebuy superior tech\n", bridge.render_inbox(1, "s", slot_data, [], []))
        only_tech = dict(slot_data, pack_levels={pack_id: 3})
        self.assertIn("noupgradebuy tech\n", bridge.render_inbox(1, "s", only_tech, [], []))
        self.assertNotIn("noupgradebuy", bridge.render_inbox(1, "s", self.slot_data, [], []))

    def test_reward_blocks_cover_only_the_seeds_unlocks(self) -> None:
        crit = [k for k, v in self.data["items"].items() if v["name"] == "Augment: Short Range: Crit"]
        pack_id = str(item_name_to_id["Item Pack 1"])
        slot_data = dict(self.slot_data, vanilla_mission_rewards=False, packs={pack_id: ["Item_ADSSpeed"]},
                         pool_items=[int(crit[0]) if crit else item_name_to_id["Perk: Plasma"],
                                     item_name_to_id["Tech Cache"], int(pack_id)])
        paths = bridge.reward_block_paths(self.data, slot_data)
        self.assertFalse([p for p in paths if "Currency" in p])  # currency rewards stay
        self.assertTrue(any(p.endswith("Item_ADSSpeed") for p in paths))  # pack contents
        self.assertFalse(any(p.endswith("Perk_Fire_Parent") for p in paths))  # not in this seed: stays a reward
        self.assertEqual(bridge.reward_block_paths(self.data, dict(slot_data, vanilla_mission_rewards=True)), [])
        self.assertEqual(bridge.reward_block_paths(self.data, self.slot_data), [])  # older seeds: unchanged
        text = bridge.render_inbox(1, "s", slot_data, [], [])
        self.assertIn("noreward " + paths[0] + "\n", text)

    def test_gating(self) -> None:
        gated = dict(self.slot_data, zone_gating=True)
        lines = bridge.gating_lines(self.data, gated, [])
        self.assertIn("zones 1", lines)
        self.assertIn("missionzone BA906212-4BCC84E3-B8A43895-0AA008D7 4", lines)  # Prelude (zone 4)
        lines = bridge.gating_lines(self.data, gated, [item_name_to_id["Zone 3 Access"]])
        self.assertIn("zones 1 3", lines)
        # zone 4 has no access item with a zone 3 goal, so it is never gated
        self.assertIn("zones 1 4", bridge.gating_lines(self.data, dict(gated, goal_zone=3), []))
        entries = [line for line in bridge.gating_lines(self.data, gated, []) if line.startswith("zoneentry")]
        self.assertEqual(len(entries), 3)  # Keep it Together, Get Out of My Head, Prelude
        self.assertIn("zoneentry BA906212-4BCC84E3-B8A43895-0AA008D7", entries)
        self.assertEqual(len([line for line in bridge.gating_lines(self.data, dict(gated, goal_zone=3), [])
                              if line.startswith("zoneentry")]), 2)
        ungated = bridge.gating_lines(self.data, self.slot_data, [])
        self.assertFalse([line for line in ungated if line.startswith("zones")])

    def test_notes_are_one_line_each(self) -> None:
        text = bridge.render_inbox(1, "s", self.slot_data, [], [], notes=[(5, "Alice sent\nPlasma  to Ethan")])
        self.assertIn("note 5 Alice sent Plasma to Ethan\n", text)
        text = bridge.render_inbox(1, "s", self.slot_data, [], [], deathlinks=[(7, "lose_scrap", "Alice  B")])
        self.assertIn("deathlink 7 lose_scrap Alice B\n", text)

    @unittest.skipUnless(os.name == "nt", "Windows refuses to replace an open file; other systems don't")
    def test_write_atomic_waits_out_a_reader(self) -> None:
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "inbox.txt")
        bridge.write_atomic(path, "rev 1\n")
        reader = open(path, encoding="utf-8")  # the mod's once-a-second read holds the file like this
        threading.Timer(0.05, reader.close).start()
        bridge.write_atomic(path, "rev 2\n")  # refused at first, succeeds once the reader lets go
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "rev 2\n")
        with open(path, encoding="utf-8"):
            with self.assertRaises(PermissionError):
                bridge.write_atomic(path, "rev 3\n", attempts=3, wait=0.01)  # held the whole time: gives up

    def test_inbox_format(self) -> None:
        text = bridge.render_inbox(3, "seed-Ethan", self.slot_data, ["/Game/A.A"], [(0, "once", 1, "/Game/B.B")])
        self.assertEqual(text, "version 1\nrev 3\nsession seed-Ethan\ngoal 4\n"
                               "lock /Game/A.A\ngrant 0 once 1 /Game/B.B\n")
