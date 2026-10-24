"""The launcher window: Setup (mod install), Options (player YAML) and Play."""
import json
import os
import queue
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Tuple

from . import VERSION, installer, locate, theme, yamlgen

SETTINGS_PATH = os.path.join(os.path.expandvars("%APPDATA%"), "DeadzoneRogueLauncher", "settings.json")
DOT = "●"


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=1)


def card(parent: tk.Widget, title: str, subtitle: str = "", expand: bool = False) -> ttk.Frame:
    """A titled panel; returns the frame to put content in."""
    outer = ttk.Frame(parent, style="Card.TFrame", padding=(18, 14))
    outer.pack(fill="both" if expand else "x", expand=expand, padx=16, pady=(12, 0))
    ttk.Label(outer, text=title, style="CardTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(outer, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
    body = ttk.Frame(outer, style="Card.TFrame")
    body.pack(fill="both", expand=True, pady=(6, 0))
    return body


class StatusList:
    """Rows of a coloured dot plus text, e.g. '● UE4SS installed'."""

    def __init__(self, parent: tk.Widget) -> None:
        self.frame = ttk.Frame(parent, style="Card.TFrame")
        self.frame.pack(fill="x", pady=(2, 8))
        self.rows: List[Tuple[ttk.Label, ttk.Label]] = []

    def show(self, items: List[Tuple[str, str]]) -> None:
        """items: (level, text) with level ok / warn / bad."""
        while len(self.rows) < len(items):
            dot = ttk.Label(self.frame, text=DOT)
            text = ttk.Label(self.frame, style="Card.TLabel")
            dot.grid(row=len(self.rows), column=0, sticky="w", padx=(0, 8), pady=1)
            text.grid(row=len(self.rows), column=1, sticky="w", pady=1)
            self.rows.append((dot, text))
        for (dot, text), (level, message) in zip(self.rows, items):
            dot.configure(style={"ok": "Ok.TLabel", "warn": "Warn.TLabel", "bad": "Bad.TLabel"}[level])
            text.configure(text=message)
        for dot, text in self.rows[len(items):]:
            dot.configure(text="")
            text.configure(text="")


class ScrollFrame(ttk.Frame):
    """A vertically scrolling frame for the long options form."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0, background=theme.BG, borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))


class LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = load_settings()
        self.events: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self.busy = False
        root.title(f"Deadzone Rogue – Archipelago Launcher v{VERSION}")
        root.geometry("900x760")
        root.minsize(760, 600)

        self.build_header()
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        self.setup_tab = ttk.Frame(notebook)
        self.options_tab = ttk.Frame(notebook)
        self.play_tab = ttk.Frame(notebook)
        notebook.add(self.setup_tab, text="SETUP")
        notebook.add(self.options_tab, text="OPTIONS")
        notebook.add(self.play_tab, text="PLAY")

        self.build_setup()
        self.build_options()
        self.build_play()
        notebook.select(int(os.environ.get("DZR_TAB", "0")))  # dev aid: open a given tab (for screenshots)
        self.refresh_status()
        root.after(100, self.pump_events)

    def build_header(self) -> None:
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(20, 14))
        header.pack(fill="x")
        ttk.Label(header, text="DEADZONE: ROGUE", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"   ARCHIPELAGO LAUNCHER  ·  v{VERSION}", style="Subtitle.TLabel").pack(
            side="left", pady=(8, 0))
        tk.Frame(self.root, height=2, background=theme.ACCENT).pack(fill="x")

    # Background work ---------------------------------------------------------------------------------------------

    def pump_events(self) -> None:
        while not self.events.empty():
            self.events.get()()
        self.root.after(100, self.pump_events)

    def log(self, message: str) -> None:
        def write() -> None:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", message + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.events.put(write)

    def run_in_background(self, title: str, work: Callable[[], None]) -> None:
        if self.busy:
            return
        self.busy = True
        self.log(f"— {title} —")

        def runner() -> None:
            try:
                work()
            except PermissionError:
                self.log("Windows refused access to the game folder. Close the game, or run the launcher as "
                         "administrator if the game is installed somewhere protected.")
            except Exception as e:  # shown to the player rather than crashing the window
                self.log(f"Failed: {e}")
            finally:
                def done() -> None:
                    self.busy = False
                    self.refresh_status()
                self.events.put(done)
        threading.Thread(target=runner, daemon=True).start()

    # Setup tab ---------------------------------------------------------------------------------------------------

    def folder_row(self, parent: tk.Widget, var: tk.StringVar, browse: Callable[[], None],
                   detect: Callable[[], None]) -> None:
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 8))
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=browse).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Detect", command=detect).pack(side="left", padx=(8, 0))

    def build_setup(self) -> None:
        tab = self.setup_tab
        game = card(tab, "Game mod", "UE4SS, the startup crash fix and the APClient mod, installed into Deadzone: Rogue.")
        # prefer the freshly detected path (correct capitalisation) when it's the same folder as the saved one
        saved, found = self.settings.get("game_dir") or "", locate.find_game_win64() or ""
        same = saved and found and os.path.normcase(saved) == os.path.normcase(found)
        self.game_var = tk.StringVar(value=found if (same or not saved) else saved)
        self.folder_row(game, self.game_var, self.browse_game, self.detect_game)
        self.game_status = StatusList(game)
        buttons = ttk.Frame(game, style="Card.TFrame")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Install / update mod", style="Accent.TButton", command=self.install_mod).pack(side="left")
        ttk.Button(buttons, text="Reinstall UE4SS", command=lambda: self.install_mod(True)).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Uninstall…", command=self.uninstall_mod).pack(side="right")

        ap = card(tab, "Archipelago", "Adds the Deadzone Rogue world to your Archipelago install.")
        self.ap_var = tk.StringVar(value=self.settings.get("archipelago_dir") or locate.find_archipelago() or "")
        self.folder_row(ap, self.ap_var, self.browse_ap, self.detect_ap)
        self.ap_status = StatusList(ap)
        ttk.Button(ap, text="Install world into Archipelago", style="Accent.TButton",
                   command=self.install_world).pack(anchor="w")

        log = card(tab, "Activity", expand=True)
        self.log_box = tk.Text(log, height=6, state="disabled", wrap="word", background=theme.FIELD,
                               foreground=theme.MUTED, insertbackground=theme.TEXT, relief="flat",
                               borderwidth=0, font=("Consolas", 9), padx=10, pady=8)
        self.log_box.pack(fill="both", expand=True)
        ttk.Frame(tab).pack(pady=8)

    def game_dir(self) -> str:
        return locate.normalize_game_folder(self.game_var.get().strip()) or ""

    def browse_game(self) -> None:
        folder = filedialog.askdirectory(title="Select the Deadzone Rogue folder")
        if folder:
            self.game_var.set(locate.normalize_game_folder(folder) or folder)
            self.refresh_status()

    def detect_game(self) -> None:
        found = locate.find_game_win64()
        if found:
            self.game_var.set(found)
        else:
            messagebox.showinfo("Not found", "Couldn't find Deadzone: Rogue in your Steam libraries. Use Browse… "
                                             "to pick its folder.")
        self.refresh_status()

    def browse_ap(self) -> None:
        folder = filedialog.askdirectory(title="Select your Archipelago folder (with ArchipelagoLauncher.exe)")
        if folder:
            self.ap_var.set(os.path.normpath(folder))
            self.refresh_status()

    def detect_ap(self) -> None:
        found = locate.find_archipelago()
        if found:
            self.ap_var.set(found)
        else:
            messagebox.showinfo("Not found", "Couldn't find Archipelago in its usual places. Install it from "
                                             "github.com/ArchipelagoMW/Archipelago/releases, or use Browse….")
        self.refresh_status()

    def refresh_status(self) -> None:
        win64 = self.game_dir()
        if not win64:
            self.game_status.show([("bad", "Game not found. Pick the Deadzone Rogue folder.")])
        else:
            s = installer.status(win64)
            bundled = s["bundled_apclient"]
            if not s["apclient"]:
                apclient = ("bad", "APClient mod not installed")
            elif s["apclient"] != bundled:
                older = "an older version" if s["apclient"] == "unknown" else f"v{s['apclient']}"
                apclient = ("warn", f"APClient mod is {older}; v{bundled} is available")
            else:
                apclient = ("ok", f"APClient mod v{bundled}")
            self.game_status.show([
                ("ok", "UE4SS installed") if s["ue4ss"] else ("bad", "UE4SS not installed"),
                ("ok", "Crash fix installed") if s["crash_fix"] else ("bad", "Crash fix missing or outdated"),
                apclient])
        ap = self.ap_var.get().strip()
        if not locate.is_archipelago(ap):
            self.ap_status.show([("bad", "Archipelago not found. Pick its folder (it has ArchipelagoLauncher.exe).")])
        else:
            world = os.path.isfile(os.path.join(ap, "custom_worlds", "deadzone_rogue.apworld"))
            self.ap_status.show([("ok", "Archipelago found"),
                                 ("ok", "Deadzone Rogue world installed") if world else
                                 ("warn", "Deadzone Rogue world not installed yet")])
        self.update_ready_check(win64, ap)
        self.settings.update(game_dir=win64 or self.settings.get("game_dir", ""), archipelago_dir=ap)
        save_settings(self.settings)

    def update_ready_check(self, win64: str, ap: str) -> None:
        s = installer.status(win64) if win64 else {}
        mod_ready = bool(s) and s["ue4ss"] and s["crash_fix"] and s["apclient"] == s["bundled_apclient"]
        world_ready = locate.is_archipelago(ap) and os.path.isfile(
            os.path.join(ap, "custom_worlds", "deadzone_rogue.apworld"))
        self.ready_status.show([
            ("ok", "Game mod is installed and up to date") if mod_ready else
            ("bad", "Game mod: install or update it on the Setup tab"),
            ("ok", "World is installed in Archipelago") if world_ready else
            ("bad", "World: install it into Archipelago on the Setup tab"),
            ("ok", "YAML saved") if self.settings.get("yaml_saved") else
            ("warn", "YAML: save one on the Options tab and send it to the host")])

    def install_mod(self, reinstall_ue4ss: bool = False) -> None:
        win64 = self.game_dir()
        if not win64:
            messagebox.showwarning("Game not found", "Pick the Deadzone Rogue folder first.")
            return
        work = os.path.join(tempfile.gettempdir(), "DeadzoneRogueLauncher")
        self.run_in_background("Installing the mod", lambda: installer.install_all(
            win64, work, reinstall_ue4ss=reinstall_ue4ss, progress=self.log))

    def uninstall_mod(self) -> None:
        win64 = self.game_dir()
        if not win64:
            return
        if messagebox.askyesno("Uninstall", "Remove UE4SS and the APClient mod from the game?\n\n"
                                            f"This deletes {os.path.join(win64, 'dwmapi.dll')} and the ue4ss "
                                            "folder, including any other UE4SS mods you have.\n"
                                            "Your Archipelago progress (APBridge folder) is kept."):
            self.run_in_background("Uninstalling", lambda: installer.uninstall(win64, progress=self.log))

    def install_world(self) -> None:
        ap = self.ap_var.get().strip()
        if not locate.is_archipelago(ap):
            messagebox.showwarning("Archipelago not found", "Pick your Archipelago folder first.")
            return
        self.run_in_background("Installing the world", lambda: installer.install_apworld(ap, progress=self.log))

    # Options tab -------------------------------------------------------------------------------------------------

    def build_options(self) -> None:
        self.schema = yamlgen.load_schema()
        self.vars: Dict[str, object] = {}

        slot = card(self.options_tab, "Player", "The slot name is what you'll connect with. "
                                                f"Up to {yamlgen.MAX_NAME_LENGTH} characters.")
        self.name_var = tk.StringVar(value=self.settings.get("slot_name", ""))
        ttk.Entry(slot, textvariable=self.name_var, width=24).pack(anchor="w")

        bottom = ttk.Frame(self.options_tab, style="Card.TFrame", padding=(16, 10))
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="Save YAML…", style="Accent.TButton", command=self.save_yaml).pack(side="right")
        ttk.Button(bottom, text="Copy YAML", command=self.copy_yaml).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="Reset to defaults", command=self.reset_options).pack(side="left")

        scroll = ScrollFrame(self.options_tab)
        scroll.pack(fill="both", expand=True, pady=(4, 12))
        groups: Dict[str, ttk.Frame] = {}
        for option in self.schema["options"]:
            if option["group"] not in groups:
                groups[option["group"]] = card(scroll.inner, option["group"])
                groups[option["group"]].columnconfigure(1, weight=1)
            self.option_row(groups[option["group"]], option)

    def option_row(self, frame: ttk.Frame, option: dict) -> None:
        row = frame.grid_size()[1]
        ttk.Label(frame, text=option["label"], style="Option.TLabel").grid(
            row=row, column=0, sticky="nw", pady=(10, 0))
        holder = ttk.Frame(frame, style="Card.TFrame")
        holder.grid(row=row, column=1, sticky="w", padx=(16, 0), pady=(8, 0))
        kind, default = option["kind"], option["default"]
        if kind == "toggle":
            var = tk.BooleanVar(value=default)
            ttk.Checkbutton(holder, variable=var, style="Card.TCheckbutton").pack(side="left")
        elif kind == "choice":
            var = tk.StringVar(value=default)
            ttk.Combobox(holder, textvariable=var, values=option["choices"], state="readonly", width=22).pack(side="left")
        elif kind == "range":
            var = tk.IntVar(value=default)
            ttk.Spinbox(holder, from_=option["min"], to=option["max"], textvariable=var, width=10,
                        increment=max(1, (option["max"] - option["min"]) // 100 or 1)).pack(side="left")
            ttk.Label(holder, text=f"   {option['min']:,} – {option['max']:,}", style="Muted.TLabel").pack(side="left")
        else:  # set
            var = {choice: tk.BooleanVar(value=choice in default) for choice in option["choices"]}
            for choice, v in var.items():
                ttk.Checkbutton(holder, text=" " + choice, variable=v, style="Card.TCheckbutton").pack(side="left", padx=(0, 12))
        self.vars[option["name"]] = var
        if option["help"]:
            # reflow the docstring's hard line breaks, keeping paragraph breaks
            text = "\n\n".join(" ".join(p.split()) for p in option["help"].split("\n\n"))
            ttk.Label(frame, text=text, style="Muted.TLabel", wraplength=600, justify="left").grid(
                row=row + 1, column=0, columnspan=2, sticky="w", pady=(2, 4))

    def values(self) -> Dict[str, object]:
        out = {}
        for option in self.schema["options"]:
            var = self.vars[option["name"]]
            if option["kind"] == "set":
                out[option["name"]] = [c for c, v in var.items() if v.get()]
            else:
                try:
                    out[option["name"]] = var.get()
                except tk.TclError:  # a non-number typed into a number box
                    out[option["name"]] = option["min"] - 1 if option["kind"] == "range" else option["default"]
        return out

    def reset_options(self) -> None:
        for option in self.schema["options"]:
            var = self.vars[option["name"]]
            if option["kind"] == "set":
                for choice, v in var.items():
                    v.set(choice in option["default"])
            else:
                var.set(option["default"])

    def yaml_text(self) -> str:
        name = self.name_var.get().strip()
        values = self.values()
        problems = yamlgen.validate(self.schema, name, values)
        if problems:
            messagebox.showwarning("Check your options", "\n".join(problems))
            return ""
        self.settings["slot_name"] = name
        save_settings(self.settings)
        return yamlgen.render(self.schema, name, values)

    def save_yaml(self) -> None:
        text = self.yaml_text()
        if not text:
            return
        path = filedialog.asksaveasfilename(title="Save your player YAML", defaultextension=".yaml",
                                            initialfile=f"{self.name_var.get().strip()}.yaml",
                                            filetypes=[("YAML", "*.yaml")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.settings["yaml_saved"] = path
            save_settings(self.settings)
            self.refresh_status()
            messagebox.showinfo("Saved", f"Saved {path}.\nSend this file to whoever hosts the multiworld.")

    def copy_yaml(self) -> None:
        text = self.yaml_text()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo("Copied", "The YAML is on your clipboard.")

    # Play tab ----------------------------------------------------------------------------------------------------

    def build_play(self) -> None:
        steps = card(self.play_tab, "Getting started")
        for number, title, detail in (
                ("1", "Set up", "Install the mod into the game and the world into Archipelago (Setup tab)."),
                ("2", "Make your YAML", "Pick your options and save the YAML (Options tab). Send it to the host."),
                ("3", "Connect", "When the room is up, start the client and connect with the room address and "
                                 "your slot name."),
                ("4", "Play", "Start the game and play on a new save slot. Your normal saves are never touched.")):
            row = ttk.Frame(steps, style="Card.TFrame")
            row.pack(fill="x", pady=6)
            tk.Label(row, text=number, background=theme.ACCENT, foreground="#16110c", width=3,
                     font=("Segoe UI Black", 12)).pack(side="left", anchor="n")
            text = ttk.Frame(row, style="Card.TFrame")
            text.pack(side="left", fill="x", padx=(14, 0))
            ttk.Label(text, text=title, style="Option.TLabel").pack(anchor="w")
            ttk.Label(text, text=detail, style="Muted.TLabel", wraplength=600, justify="left").pack(anchor="w")

        ready = card(self.play_tab, "Ready check")
        self.ready_status = StatusList(ready)

        launch = card(self.play_tab, "Launch")
        buttons = ttk.Frame(launch, style="Card.TFrame")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Start Deadzone Rogue Client", style="Accent.TButton",
                   command=self.start_client).pack(side="left")
        ttk.Button(buttons, text="Start Deadzone: Rogue", command=lambda: os.startfile(
            f"steam://rungameid/{locate.APP_ID}")).pack(side="left", padx=(8, 0))

    def start_client(self) -> None:
        ap = self.ap_var.get().strip()
        if not locate.is_archipelago(ap):
            messagebox.showwarning("Archipelago not found", "Set your Archipelago folder on the Setup tab first.")
            return
        subprocess.Popen([os.path.join(ap, "ArchipelagoLauncher.exe"), "Deadzone Rogue Client"], cwd=ap)


def main() -> None:
    theme.enable_high_dpi()
    root = tk.Tk()
    theme.apply(root)
    theme.window_icon(root)
    LauncherApp(root)
    root.mainloop()
