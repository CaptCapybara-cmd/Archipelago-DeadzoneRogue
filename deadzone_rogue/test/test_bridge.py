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

    def test_inbox_format(self) -> None:
        text = bridge.render_inbox(3, "seed-Ethan", self.slot_data, ["/Game/A.A"], [(0, "once", 1, "/Game/B.B")])
        self.assertEqual(text, "version 1\nrev 3\nsession seed-Ethan\ngoal 4\n"
                               "lock /Game/A.A\ngrant 0 once 1 /Game/B.B\n")
