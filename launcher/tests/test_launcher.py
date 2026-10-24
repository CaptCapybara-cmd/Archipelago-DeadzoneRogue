import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dzr_launcher import installer, locate, yamlgen  # noqa: E402

VDF = '''"libraryfolders"
{
\t"0"\t{ "path"\t\t"C:\\\\Program Files (x86)\\\\Steam" }
\t"1"\t{ "path"\t\t"D:\\\\SteamLibrary" }
}'''


class TempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, *parts: str, text: str = "") -> str:
        path = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path


class TestLocate(TempDirTest):
    def test_parse_steam_files(self) -> None:
        self.assertEqual(locate.library_folders(VDF), [r"C:\Program Files (x86)\Steam", r"D:\SteamLibrary"])
        self.assertEqual(locate.manifest_installdir('"AppState" { "installdir"  "Deadzone Rogue" }'), "Deadzone Rogue")

    def test_find_game_in_second_library(self) -> None:
        steam = os.path.join(self.tmp, "Steam")
        library = os.path.join(self.tmp, "Lib2")
        self.write("Steam", "steamapps", "libraryfolders.vdf", text=f'"path" "{library.replace(os.sep, chr(92) * 2)}"')
        self.write("Lib2", "steamapps", f"appmanifest_{locate.APP_ID}.acf", text='"installdir" "Deadzone Rogue"')
        exe = self.write("Lib2", "steamapps", "common", "Deadzone Rogue", locate.WIN64_SUBDIR, locate.GAME_EXE)
        self.assertEqual(os.path.normcase(locate.find_game_win64(steam)), os.path.normcase(os.path.dirname(exe)))
        # the game root folder is accepted too
        root = os.path.join(library, "steamapps", "common", "Deadzone Rogue")
        self.assertEqual(locate.normalize_game_folder(root), os.path.normpath(os.path.dirname(exe)))
        self.assertIsNone(locate.normalize_game_folder(self.tmp))


class TestInstaller(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.win64 = os.path.join(self.tmp, "Win64")
        os.makedirs(self.win64)
        resources = os.path.join(self.tmp, "resources")
        self.write("resources", "VTableLayout.ini", text="[FMalloc]\n__vecDelDtor\n")
        self.write("resources", "APClient", "Scripts", "main.lua", text="-- APClient v9.9.9: test\n")
        self.write("resources", "deadzone_rogue.apworld", text="world")
        self.old_resources, installer.RESOURCES = installer.RESOURCES, resources

    def tearDown(self) -> None:
        installer.RESOURCES = self.old_resources

    def fake_ue4ss_zip(self) -> str:
        path = os.path.join(self.tmp, "UE4SS_v3.0.1-test.zip")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("dwmapi.dll", "dll")
            z.writestr("ue4ss/UE4SS.dll", "core")
            z.writestr("ue4ss/UE4SS-settings.ini", "fresh settings")
            z.writestr("ue4ss/Mods/mods.txt", "Keybinds : 1\n")
            z.writestr("../escape.txt", "must not be written")
            z.writestr("README.md", "not copied")
        return path

    def test_install_keeps_player_settings_and_blocks_escapes(self) -> None:
        self.write("Win64", "ue4ss", "UE4SS-settings.ini", text="my settings")
        installer.install_ue4ss(self.win64, self.fake_ue4ss_zip(), progress=lambda m: None)
        with open(os.path.join(self.win64, "ue4ss", "UE4SS-settings.ini")) as f:
            self.assertEqual(f.read(), "my settings")
        self.assertTrue(os.path.isfile(os.path.join(self.win64, "ue4ss", "Mods", "mods.txt")))  # absent before
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.win64, "README.md")))
        self.assertTrue(installer.status(self.win64)["ue4ss"])

    def test_crash_fix_apclient_and_status(self) -> None:
        installer.install_ue4ss(self.win64, self.fake_ue4ss_zip(), progress=lambda m: None)
        self.write("Win64", "ue4ss", "Mods", "mods.txt", text="APClient : 0\nKeybinds : 1\n")
        installer.install_crash_fix(self.win64, progress=lambda m: None)
        installer.install_apclient(self.win64, progress=lambda m: None)
        s = installer.status(self.win64)
        self.assertTrue(s["crash_fix"])
        self.assertEqual(s["apclient"], "9.9.9")
        self.assertTrue(os.path.isfile(os.path.join(self.win64, "ue4ss", "Mods", "APClient", "enabled.txt")))
        with open(os.path.join(self.win64, "ue4ss", "Mods", "mods.txt")) as f:
            self.assertIn("APClient : 1", f.read())

    def test_uninstall_keeps_progress(self) -> None:
        installer.install_ue4ss(self.win64, self.fake_ue4ss_zip(), progress=lambda m: None)
        self.write("Win64", "APBridge", "state_x.txt", text="applied 3")
        installer.uninstall(self.win64, progress=lambda m: None)
        self.assertFalse(installer.status(self.win64)["ue4ss"])
        self.assertTrue(os.path.isfile(os.path.join(self.win64, "APBridge", "state_x.txt")))

    def test_release_asset_selection_requires_checksum(self) -> None:
        def asset(name: str, digest: str = "sha256:ABC") -> dict:
            return {"name": name, "browser_download_url": f"https://example/{name}", "size": 1, "digest": digest}
        release = {"assets": [asset("zDEV-UE4SS_v3.0.1-1.zip"), asset("zCustomGameConfigs.zip"),
                              asset("UE4SS_v3.0.1-1181-g83330635.zip")]}
        chosen = installer.latest_ue4ss_asset(release)
        self.assertEqual(chosen["name"], "UE4SS_v3.0.1-1181-g83330635.zip")
        self.assertEqual(chosen["sha256"], "abc")
        with self.assertRaises(RuntimeError):
            installer.latest_ue4ss_asset({"assets": [asset("UE4SS_v3.0.1-1.zip", digest="")]})

    def test_install_apworld(self) -> None:
        target = installer.install_apworld(os.path.join(self.tmp, "Archipelago"), progress=lambda m: None)
        self.assertTrue(target.endswith(os.path.join("custom_worlds", "deadzone_rogue.apworld")))


class TestYaml(unittest.TestCase):
    schema = yamlgen.load_schema()

    def test_defaults_are_valid(self) -> None:
        self.assertEqual(yamlgen.validate(self.schema, "Ethan", yamlgen.defaults(self.schema)), [])

    def test_validation(self) -> None:
        values = yamlgen.defaults(self.schema)
        self.assertTrue(yamlgen.validate(self.schema, "", values))
        self.assertTrue(yamlgen.validate(self.schema, "x" * 17, values))
        self.assertTrue(yamlgen.validate(self.schema, "Ethan", dict(values, enemies_killed_total=10 ** 9)))
        self.assertTrue(yamlgen.validate(self.schema, "Ethan", dict(values, mission_difficulties=[])))

    def test_render(self) -> None:
        values = dict(yamlgen.defaults(self.schema), goal="zone_3", mission_difficulties=["Hard", "Adventure"])
        text = yamlgen.render(self.schema, 'Ethan "Capy"', values)
        self.assertIn('name: "Ethan \\"Capy\\""', text)
        self.assertIn("  goal: zone_3", text)
        self.assertIn('  mission_difficulties: ["Adventure", "Hard"]', text)  # easiest first
        self.assertIn("  zone_gating: true", text)


if __name__ == "__main__":
    unittest.main()
