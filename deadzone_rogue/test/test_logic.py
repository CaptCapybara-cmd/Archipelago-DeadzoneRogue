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

    def test_zone_4_needs_zone_3_for_prerequisite(self) -> None:
        # Prelude (zone 4) requires Get Out of My Head (zone 3) to be completed first.
        self.collect_by_name(["Zone 4 Access"])
        self.assertFalse(self.can_reach_location("Prelude (Adventure)"))
        self.collect_by_name(["Zone 2 Access", "Zone 3 Access"])
        self.assertTrue(self.can_reach_location("Prelude (Adventure)"))

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
               "room_clear_checks": 200, "include_synergy_components": True, "item_pack_size": 1}


class TestSmallestSeed(DeadzoneRogueTestBase):
    options = {"goal": "zone_3", "mission_difficulties": ["Hard"], "include_challenge_missions": False,
               "room_clear_checks": 0}
