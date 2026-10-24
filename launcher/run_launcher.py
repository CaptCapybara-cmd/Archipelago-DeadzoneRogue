"""Entry point for PyInstaller (and for running the launcher from source: python launcher/run_launcher.py).

`--selftest <report.json>` checks the bundled files without opening the window (used after building the exe)."""
import json
import os
import sys


def selftest(report_path: str) -> None:
    from dzr_launcher import VERSION, installer, locate, yamlgen
    schema = yamlgen.load_schema()
    report = {
        "version": VERSION,
        "options": len(schema["options"]),
        "yaml_ok": not yamlgen.validate(schema, "Selftest", yamlgen.defaults(schema)),
        "bundled_apclient": installer.apclient_version(installer.resource("APClient", "Scripts", "main.lua")),
        "bundled_files": {name: os.path.isfile(installer.resource(*name.split("/")))
                          for name in ("VTableLayout.ini", "APClient/Scripts/main.lua", "deadzone_rogue.apworld")},
        "game_found": locate.find_game_win64(),
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    else:
        from dzr_launcher.app import main
        main()
