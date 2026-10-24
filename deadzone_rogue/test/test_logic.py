from . import DeadzoneRogueTestBase


class TestDefault(DeadzoneRogueTestBase):
    def test_zone_1_story_open(self) -> None:
        self.assertTrue(self.can_reach_location("Who am I? (Adventure)"))

    def test_difficulties_are_separate_checks_not_gated(self) -> None:
        for difficulty in ("Adventure", "Normal", "Hard"):
            self.assertTrue(self.can_reach_location(f"Who am I? ({difficulty})"))
        self.assertNotIn("Progressive Difficulty", {item.name for item in self.multiworld.itempool})

    def test_zone_access(self) -> None:
        self.assertFalse(self.can_reach_location("Keep it Together (Adventure)"))
        self.collect_by_name(["Zone 2 Access"])
        self.assertTrue(self.can_reach_location("Keep it Together (Adventure)"))

    def test_zone_access_opens_the_entry_mission_out_of_story_order(self) -> None:
        # Prelude normally needs Get Out of My Head (zone 3); with gating the mod opens it on Zone 4 Access alone.
        self.collect_by_name(["Zone 4 Access"])
        self.assertTrue(self.can_reach_location("Prelude (Adventure)"))
        self.assertTrue(self.can_reach_location("Distress Call (Adventure)"))
        self.assertFalse(self.can_reach_location("Get Out of My Head (Adventure)"))

    def test_starting_kit_and_free_content_shuffled(self) -> None:
        kit = [item.name for item in self.multiworld.precollected_items[self.player]]
        self.assertEqual(len(kit), 1 + 1 + 1 + 3 + 3)  # primary, secondary, melee, 3 perks, 3 augments
        pool = {item.name for item in self.multiworld.itempool}
        self.assertTrue(pool.isdisjoint(kit))

    def test_packs_cover_their_pools_without_overlap(self) -> None:
        world = self.multiworld.worlds[self.player]
        keys = [k for contents in world.packs.values() for k in contents]
        self.assertEqual(len(keys), len(set(keys)))
        pool = {item.name for item in self.multiworld.itempool}
        self.assertTrue(set(world.packs) <= pool)


class TestLockedOnly(DeadzoneRogueTestBase):
    options = {"weapon_shuffle": "locked_only", "perk_shuffle": "locked_only", "augment_shuffle": "none"}

    def test_only_locked_content(self) -> None:
        pool = {item.name for item in self.multiworld.itempool}
        self.assertIn("Perk: Plasma", pool)
        self.assertNotIn("Perk: Fire", pool)
        self.assertNotIn("Augment: Aiming: Crit", pool)
        self.assertEqual(self.multiworld.precollected_items[self.player], [])


class TestNoGating(DeadzoneRogueTestBase):
    options = {"zone_gating": False}

    def test_everything_open(self) -> None:
        self.assertTrue(self.can_reach_location("Getting Answers (Hard)"))


class TestZone3Goal(DeadzoneRogueTestBase):
    options = {"goal": "zone_3"}

    def test_no_zone_4(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn("Prelude (Adventure)", names)
        self.assertNotIn("Zone 4 Access", {item.name for item in self.multiworld.itempool})


class TestAllDifficulties(DeadzoneRogueTestBase):
    options = {"mission_difficulties": ["Adventure", "Normal", "Hard", "Difficulty 4", "Difficulty 5"],
               "include_endless_missions": True, "sectors_cleared_total": 500, "sectors_cleared_interval": 5,
               "enemies_killed_total": 10000, "enemies_killed_interval": 100, "scrap_gathered_total": 100000,
               "scrap_gathered_interval": 1000, "include_synergy_components": True, "item_pack_size": 1}

    def test_endless_have_checks_but_not_goal(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn("Gauntlet (Normal)", names)
        self.assertIn("Ultra Nightmare (Difficulty 5)", names)
        self.assertIn("Scrap Gathered: 100000", names)
        goal = {m["key"] for m in self.multiworld.worlds[self.player].goal_missions}
        self.assertNotIn("Mission_Challenge_Mission13", goal)  # Gauntlet is endless
        self.assertIn("Mission_Challenge_Mission28", goal)  # Ultra Nightmare counts: Difficulty 5 has checks
        self.assertEqual(len(goal), 29)  # 32 missions minus the 3 endless ones


class TestSmallestSeed(DeadzoneRogueTestBase):
    options = {"goal": "zone_3", "mission_difficulties": ["Hard"], "include_challenge_missions": False,
               "sectors_cleared_total": 0, "enemies_killed_total": 0, "scrap_gathered_total": 0}


class TestGoalAndObjectives(DeadzoneRogueTestBase):
    options = {"goal": "zone_3", "enemies_killed_total": 1000, "enemies_killed_interval": 250}

    def test_goal_missions(self) -> None:
        goal = {m["name"] for m in self.multiworld.worlds[self.player].goal_missions}
        self.assertIn("Get Out of My Head", goal)
        self.assertIn("Close Quarters", goal)
        self.assertNotIn("Prelude", goal)  # zone 4
        self.assertNotIn("Gauntlet", goal)  # endless
        self.assertNotIn("Ultra Nightmare", goal)  # only on Difficulty 5, which has no checks here

    def test_goal_needs_all_zones(self) -> None:
        self.assertFalse(self.can_reach_location("Goal: All Missions Through Zone 3"))
        self.collect_by_name(["Zone 2 Access"])
        self.assertFalse(self.can_reach_location("Goal: All Missions Through Zone 3"))
        self.collect_by_name(["Zone 3 Access"])
        self.assertTrue(self.can_reach_location("Goal: All Missions Through Zone 3"))

    def test_objective_milestones(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        # interval 250 rounds down to 200: 200, 400, 600, 800, 1000
        self.assertEqual(sorted(n for n in names if n.startswith("Enemies Killed")),
                         sorted(f"Enemies Killed: {a}" for a in (200, 400, 600, 800, 1000)))
        self.assertIn("Sectors Cleared: 150", names)  # defaults: total 150, interval 10
        self.assertNotIn("Sectors Cleared: 160", names)
        self.assertIn("Scrap Gathered: 20000", names)  # defaults: total 20000, interval 2000
        self.assertNotIn("Gauntlet (Normal)", names)  # endless missions are off by default
