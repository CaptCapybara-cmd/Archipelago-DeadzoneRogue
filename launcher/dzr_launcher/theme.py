"""Dark theme for the launcher (ttk 'clam' restyled), in the spirit of the game's charcoal-and-orange UI."""
import tkinter as tk
from tkinter import font, ttk

BG = "#121418"        # window
PANEL = "#1b1f26"     # cards
FIELD = "#252b34"     # inputs
BORDER = "#2e3540"
TEXT = "#e8ebf0"
MUTED = "#8c96a5"
ACCENT = "#ff7a1a"    # primary buttons, highlights
ACCENT_HOVER = "#ff9142"
OK = "#3ecf8e"
WARN = "#f5b942"
BAD = "#ff5c5c"

UI_FONT = ("Segoe UI", 10)


def enable_high_dpi() -> None:
    """Sharp text on scaled displays (call before creating the Tk root)."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def _checkbox_images(root: tk.Tk, size: int = 18):
    """An empty box and an accent-filled box with a dark tick, drawn pixel by pixel (no image files needed)."""
    def box(fill: str, edge: str) -> tk.PhotoImage:
        image = tk.PhotoImage(master=root, width=size, height=size)
        image.put(fill, to=(0, 0, size, size))
        for i in range(size):
            for x, y in ((i, 0), (i, size - 1), (0, i), (size - 1, i)):
                image.put(edge, (x, y))
        return image
    unchecked = box(FIELD, "#4a5361")
    checked = box(ACCENT, ACCENT)
    ink = "#16110c"
    for x, y in ((4, 9), (5, 10), (6, 11), (7, 12), (8, 11), (9, 10), (10, 9), (11, 8), (12, 7), (13, 6), (14, 5)):
        for dy in (-1, 0, 1):
            checked.put(ink, (x, y + dy))
    root._checkbox_images = (unchecked, checked)  # keep references, or Tk drops the images
    return unchecked, checked


def window_icon(root: tk.Tk) -> None:
    """A small orange 'D' badge for the title bar and taskbar."""
    size = 32
    icon = tk.PhotoImage(master=root, width=size, height=size)
    icon.put(ACCENT, to=(0, 0, size, size))
    ink = "#16110c"
    for box in ((8, 6, 12, 26), (8, 6, 18, 10), (8, 22, 18, 26), (20, 10, 24, 22), (17, 8, 21, 12), (17, 20, 21, 24)):
        icon.put(ink, to=box)
    root._window_icon = icon
    root.iconphoto(True, icon)


def apply(root: tk.Tk) -> None:
    root.configure(background=BG)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        font.nametofont(name).configure(family=UI_FONT[0], size=UI_FONT[1])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, bordercolor=BORDER, darkcolor=BG, lightcolor=BG,
                    troughcolor=PANEL, focuscolor=ACCENT, font=UI_FONT)

    # Frames and cards
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL)
    style.configure("Header.TFrame", background=PANEL)

    # Text
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
    style.configure("CardTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 12))
    style.configure("Title.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Black", 18))
    style.configure("Subtitle.TLabel", background=PANEL, foreground=ACCENT, font=("Segoe UI Semibold", 10))
    style.configure("Option.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 10))
    for name, color in (("Ok", OK), ("Warn", WARN), ("Bad", BAD)):
        style.configure(f"{name}.TLabel", background=PANEL, foreground=color, font=("Segoe UI", 11))

    # Buttons
    style.configure("TButton", background=FIELD, foreground=TEXT, bordercolor=BORDER, padding=(12, 6),
                    relief="flat", focusthickness=0)
    style.map("TButton", background=[("pressed", BORDER), ("active", "#30363f")])
    style.configure("Accent.TButton", background=ACCENT, foreground="#16110c", bordercolor=ACCENT,
                    font=("Segoe UI Semibold", 10), padding=(16, 7))
    style.map("Accent.TButton", background=[("pressed", "#e86a10"), ("active", ACCENT_HOVER)])

    # Inputs
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, bordercolor=BORDER,
                    padding=5)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, background=FIELD,
                    arrowcolor=TEXT, bordercolor=BORDER, padding=4)
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)])
    style.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT, background=FIELD, arrowcolor=TEXT,
                    bordercolor=BORDER, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)],
              bordercolor=[("focus", ACCENT)])
    unchecked, checked = _checkbox_images(root)
    style.element_create("Tick.indicator", "image", unchecked, ("selected", checked))
    style.layout("Card.TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
        ("Tick.indicator", {"side": "left", "sticky": ""}),
        ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
            ("Checkbutton.label", {"sticky": "nswe"})]})]})])
    style.configure("Card.TCheckbutton", background=PANEL, foreground=TEXT, focuscolor=PANEL, padding=(0, 2))
    style.map("Card.TCheckbutton", background=[("active", PANEL)])

    # Tabs
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(16, 10, 16, 0), lightcolor=BG,
                    darkcolor=BG, bordercolor=BG)
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(20, 9), borderwidth=0,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG, font=("Segoe UI Semibold", 10))
    style.map("TNotebook.Tab", background=[("selected", PANEL), ("active", "#1a1d23")],
              foreground=[("selected", ACCENT), ("active", TEXT)], lightcolor=[("selected", PANEL)],
              bordercolor=[("selected", PANEL)], padding=[("selected", (20, 9))],
              expand=[("selected", (0, 0, 0, 0))])

    style.configure("Vertical.TScrollbar", background=FIELD, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                    gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", BORDER)])
