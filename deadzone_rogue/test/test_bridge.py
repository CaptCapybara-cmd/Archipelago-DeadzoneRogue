import unittest

from .. import bridge
from ..items import item_name_to_id


class TestBridge(unittest.TestCase):
    data = bridge.load_data()
    slot_data = {"goal_mission": "Mission_Zone4_Story2", "difficulties": [1, 2, 3], "room_check_step": 5,
                 "room_clear_checks": 20, "lock_free": ["perk"], "packs": {}}

    def test_mission_location_ids_match_the_world(self) -> None:
        from ..locations import location_name_to_id
        self.assertEqual(bridge.mission_location(self.data, "Mission_Zone1_Story", 2),
                         location_name_to_id["Who am I? (Normal)"])
        self.assertEqual(bridge.room_locations(self.data, 12, 5, 20),
                         [location_name_to_id["Rooms Cleared: 5"], location_name_to_id["Rooms Cleared: 10"]])
        self.assertEqual(len(bridge.room_locations(self.data, 500, 5, 20)), 4)  # capped by the seed's setting

    def test_checks_from_outbox(self) -> None:
        events = bridge.parse_outbox("mission Mission_Zone1_Story 2\nmission Mission_Zone1_Story 5\n"
                                     "rooms 7\nmission Mission_Zone4_Story2 1\ndeath 100\ndeath 300\n")
        locations, goal, deaths = bridge.checks_from_events(self.data, self.slot_data, events, since=200)
        self.assertIn(bridge.mission_location(self.data, "Mission_Zone1_Story", 2), locations)
        self.assertNotIn(bridge.mission_location(self.data, "Mission_Zone1_Story", 5), locations)  # not enabled
        self.assertTrue(goal)
        self.assertEqual(deaths, 1)  # the one before `since` is old

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
        zone3_goal = dict(gated, goal_mission="Mission_Zone3_Story")
        self.assertIn("zones 1 4", bridge.gating_lines(self.data, zone3_goal, []))
        ungated = bridge.gating_lines(self.data, self.slot_data, [])
        self.assertFalse([line for line in ungated if line.startswith("zones")])

    def test_inbox_format(self) -> None:
        text = bridge.render_inbox(3, "seed-Ethan", self.slot_data, ["/Game/A.A"], [(0, "once", 1, "/Game/B.B")])
        self.assertEqual(text, "version 1\nrev 3\nsession seed-Ethan\ngoal Mission_Zone4_Story2\n"
                               "lock /Game/A.A\ngrant 0 once 1 /Game/B.B\n")
