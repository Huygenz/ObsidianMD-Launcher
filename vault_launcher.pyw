#!/usr/bin/env python3
"""Minimaler Obsidian-Vault-Launcher.

Ein Klick auf einen Vault öffnet ihn in Obsidian und beendet den Launcher.
Konfiguration: config.json neben dieser Datei (wird beim ersten Start angelegt).
Farben: Zahnrad oben rechts oder F2 -> Color Picker, live Vorschau, "Speichern" schreibt in die config.json.
Optional: --config PFAD
"""
import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from urllib.parse import quote

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

THEMES = {
    "dark": {
        "bg": "#1e1e2e", "fg": "#cdd6f4", "dim": "#6c7086",
        "hover": "#313244", "accent": "#b4a0ff", "border": "#45475a",
    },
    "light": {
        "bg": "#fafafa", "fg": "#2e2e3a", "dim": "#8a8a99",
        "hover": "#ececf3", "accent": "#7c5cff", "border": "#d0d0da",
    },
}

COLOR_LABELS = [
    ("bg", "Hintergrund"), ("fg", "Text"), ("dim", "Titel / Hinweise"),
    ("hover", "Auswahl"), ("accent", "Akzent"), ("border", "Rahmen"),
]

DEFAULT_CONFIG = {
    # Vaults aus Obsidians eigener Liste (obsidian.json) automatisch übernehmen
    "auto_discover": True,
    # Einzelne Vault-Ordner explizit angeben
    "vault_locations": [],
    # Ordner, die nach Vaults (Unterordner mit .obsidian) durchsucht werden
    "scan_folders": [],
    "scan_depth": 2,
    # Vault-Namen oder Pfade, die ausgeblendet werden
    "exclude": [],
    # "recent" (zuletzt geöffnet zuerst, laut Obsidian) oder "name"
    "sort": "recent",
    # Optional: eigene Anzeigenamen  {"C:/Pfad/zum/Vault": "Mein Name"}
    "aliases": {},
    # Nach dem Start schließen
    "close_after_launch": True,
    "window": {"width": 320, "row_height": 36, "max_visible": 10, "show_title": True, "title": "Vaults",
               "show_path": True},   # Ordnerpfad dezent unter dem Namen anzeigen
    "theme": {
        "preset": "dark",          # "dark" | "light"
        "font": "Segoe UI",
        "font_size": 11,
        # Einzelne Farben überschreiben (bg, fg, dim, hover, accent, border),
        # z. B. "accent": "#ff8800" – oder bequem über den Color Picker (F2).
    },
}


# ---------------------------------------------------------------- Konfiguration
def deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config_path():
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        if i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).expanduser()
    return APP_DIR / "config.json"


def load_config(path):
    if not path.exists():
        try:
            path.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return DEFAULT_CONFIG
    try:
        return deep_merge(DEFAULT_CONFIG, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return DEFAULT_CONFIG


def save_theme(path, preset, colors):
    """Schreibt Preset und abweichende Farben in die config.json.

    Gibt None bei Erfolg zurück, sonst eine Fehlermeldung. Eine kaputte
    config.json wird nie überschrieben.
    """
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "config.json nicht lesbar"
        if not isinstance(data, dict):
            return "config.json hat ein unerwartetes Format"
    theme = data.get("theme")
    if not isinstance(theme, dict):
        theme = data["theme"] = {}
    theme["preset"] = preset
    base = THEMES[preset]
    for k, v in colors.items():
        if v.lower() == base[k].lower():
            theme.pop(k, None)
        else:
            theme[k] = v
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return "Speichern fehlgeschlagen"
    return None


# ---------------------------------------------------------------- Vault-Suche
def obsidian_json_candidates():
    home = Path.home()
    if sys.platform.startswith("win"):
        yield Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "obsidian" / "obsidian.json"
    elif sys.platform == "darwin":
        yield home / "Library/Application Support/obsidian/obsidian.json"
    else:
        yield home / ".config/obsidian/obsidian.json"
        yield home / ".var/app/md.obsidian.Obsidian/config/obsidian/obsidian.json"


def key(p):
    return os.path.normcase(os.path.normpath(str(p)))


def scan(folder, depth):
    """Findet Ordner mit .obsidian bis zur gegebenen Tiefe (steigt nicht in Vaults ab)."""
    found = []
    try:
        with os.scandir(folder) as it:
            entries = [e for e in it if e.is_dir(follow_symlinks=False)]
    except OSError:
        return found
    for e in entries:
        if e.name.startswith("."):
            continue
        if os.path.isdir(os.path.join(e.path, ".obsidian")):
            found.append(e.path)
        elif depth > 1:
            found.extend(scan(e.path, depth - 1))
    return found


def discover(cfg):
    vaults = {}

    def add(path, ts=0):
        p = os.path.normpath(os.path.expanduser(str(path)))
        if not os.path.isdir(p):
            return
        k = key(p)
        if k in vaults:
            vaults[k]["ts"] = max(vaults[k]["ts"], ts)
        else:
            name = cfg["aliases"].get(p) or cfg["aliases"].get(str(path)) or os.path.basename(p) or p
            vaults[k] = {"name": name, "path": p, "ts": ts}

    if cfg["auto_discover"]:
        for cand in obsidian_json_candidates():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for v in data.get("vaults", {}).values():
                if isinstance(v, dict) and "path" in v:
                    add(v["path"], v.get("ts", 0) or 0)
            break

    for p in cfg["vault_locations"]:
        add(p)
    for folder in cfg["scan_folders"]:
        for p in scan(os.path.expanduser(folder), max(1, int(cfg["scan_depth"]))):
            add(p)

    excl = {key(x) for x in cfg["exclude"]} | {str(x).lower() for x in cfg["exclude"]}
    result = [v for k, v in vaults.items() if k not in excl and v["name"].lower() not in excl]
    if cfg["sort"] == "name":
        result.sort(key=lambda v: v["name"].lower())
    else:
        result.sort(key=lambda v: (-v["ts"], v["name"].lower()))
    return result


# ---------------------------------------------------------------- Start
def open_vault(path):
    uri = "obsidian://open?path=" + quote(path, safe="")
    if sys.platform.startswith("win"):
        os.startfile(uri)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])


def contrast_fg(hex_color):
    """Schwarz oder Weiß, je nachdem was auf der Farbe lesbarer ist."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "#000000"
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


# ---------------------------------------------------------------- UI
class Launcher:
    def __init__(self, cfg, vaults, cfg_path):
        self.cfg, self.all, self.cfg_path = cfg, vaults, cfg_path
        th = cfg["theme"]
        self.preset = th.get("preset") if th.get("preset") in THEMES else "dark"
        self.c = dict(THEMES[self.preset])
        self.c.update({k: v for k, v in th.items() if k in THEMES["dark"]})
        self.font = (th["font"], int(th["font_size"]))
        w = cfg["window"]
        self.width, self.rh, self.maxv = int(w["width"]), int(w["row_height"]), max(1, int(w["max_visible"]))

        self.mode = "list"          # "list" | "settings"
        self.modal = False          # True, solange der Color-Picker-Dialog offen ist
        self.status = ""
        self.filter, self.sel, self.off = "", 0, 0
        self.shown = list(vaults)

        r = self.root = tk.Tk()
        r.withdraw()
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        self.pos = None             # Fensterposition; None = beim ersten Mal zentrieren
        self._drag = (0, 0)
        self.body = tk.Frame(r)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)

        r.bind("<Key>", self.on_key)
        r.bind("<Escape>", self.on_escape)
        r.bind("<F2>", lambda e: self.toggle_settings())
        r.bind("<Up>", lambda e: self.move(-1))
        r.bind("<Down>", lambda e: self.move(1))
        r.bind("<Return>", lambda e: self.launch(self.sel) if self.mode == "list" else None)
        r.bind("<MouseWheel>", lambda e: self.scroll(-1 if e.delta > 0 else 1))
        r.bind("<Button-4>", lambda e: self.scroll(-1))
        r.bind("<Button-5>", lambda e: self.scroll(1))
        r.bind("<FocusOut>", self.on_focus_out)

        self.render()
        r.deiconify()
        r.update_idletasks()
        r.focus_force()

    # ---- Fenster
    def center(self):
        r = self.root
        r.update_idletasks()
        h = r.winfo_reqheight()
        if self.pos is None:
            self.pos = ((r.winfo_screenwidth() - self.width) // 2,
                        (r.winfo_screenheight() - h) // 3)
        x, y = self.pos
        r.geometry(f"{self.width}x{h}+{x}+{y}")

    # ---- Verschieben (rahmenloses Fenster: Kopfzeile ziehen)
    def make_draggable(self, *widgets):
        for w in widgets:
            w.bind("<ButtonPress-1>", self.drag_start, add="+")
            w.bind("<B1-Motion>", self.drag_move, add="+")

    def drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def drag_move(self, e):
        self.pos = (e.x_root - self._drag[0], e.y_root - self._drag[1])
        self.root.geometry(f"+{self.pos[0]}+{self.pos[1]}")

    def on_focus_out(self, e):
        # Nur in der Vault-Liste schließen, sobald der Fokus das Fenster verlässt
        if e.widget is self.root and self.mode == "list" and not self.modal:
            self.root.after(150, self._maybe_close)

    def _maybe_close(self):
        try:
            if self.mode == "list" and not self.modal and self.root.focus_displayof() is None:
                self.root.destroy()
        except tk.TclError:
            pass

    def on_escape(self, _e=None):
        if self.mode == "settings":
            self.toggle_settings()
        else:
            self.root.destroy()

    # ---- Rendering
    def render(self):
        c = self.c
        self.root.configure(bg=c["border"])
        self.body.configure(bg=c["bg"])
        for ch in self.body.winfo_children():
            ch.destroy()

        show_title = self.cfg["window"].get("show_title", True)
        if self.mode == "settings" or show_title:
            head = tk.Frame(self.body, bg=c["bg"])
            head.pack(fill="x")
            if self.mode == "settings":
                text = "Farben"
            elif self.filter:
                text = "/" + self.filter
            else:
                text = self.cfg["window"].get("title", "Vaults")
            title = tk.Label(head, text=text, bg=c["bg"], fg=c["dim"], anchor="w", padx=14, pady=8,
                             font=(self.font[0], max(8, self.font[1] - 2)), cursor="fleur")
            title.pack(side="left", fill="x", expand=True)
            self.make_draggable(head, title)
            if self.mode == "list":
                gear = tk.Label(head, text="\u2699", bg=c["bg"], fg=c["dim"], padx=12, cursor="hand2",
                                font=(self.font[0], self.font[1]))
                gear.pack(side="right")
                gear.bind("<Button-1>", lambda e: self.toggle_settings())
                gear.bind("<Enter>", lambda e: gear.configure(fg=c["accent"]))
                gear.bind("<Leave>", lambda e: gear.configure(fg=c["dim"]))
        else:
            # Ohne Titel: schmaler, unsichtbarer Griff zum Verschieben am oberen Rand
            grip = tk.Frame(self.body, bg=c["bg"], height=8, cursor="fleur")
            grip.pack(fill="x")
            self.make_draggable(grip)

        if self.mode == "list":
            self.render_list()
        else:
            self.render_settings()
        self.center()

    def render_list(self):
        c = self.c
        box = tk.Frame(self.body, bg=c["bg"])
        box.pack(fill="both", expand=True, pady=(0, 6))
        if not self.shown:
            msg = "Keine Treffer" if self.filter else f"Keine Vaults gefunden.\nKonfiguration:\n{self.cfg_path}"
            tk.Label(box, text=msg, bg=c["bg"], fg=c["dim"], font=self.font, justify="left",
                     wraplength=self.width - 28, padx=14, pady=10, anchor="w").pack(fill="x")
            return
        self.sel = min(self.sel, len(self.shown) - 1)
        self.off = max(0, min(self.off, len(self.shown) - self.maxv))
        if self.sel < self.off:
            self.off = self.sel
        elif self.sel >= self.off + self.maxv:
            self.off = self.sel - self.maxv + 1
        pad = max(4, (self.rh - self.font[1] * 2) // 2)
        show_path = self.cfg["window"].get("show_path", True)
        small = (self.font[0], max(7, self.font[1] - 3))
        for i in range(self.off, min(len(self.shown), self.off + self.maxv)):
            v = self.shown[i]
            active = i == self.sel
            bg = c["hover"] if active else c["bg"]
            fg = c["accent"] if active else c["fg"]
            if show_path:
                row = tk.Frame(box, bg=bg, cursor="hand2")
                row.pack(fill="x")
                name = tk.Label(row, text=v["name"], bg=bg, fg=fg, font=self.font, anchor="w",
                                padx=14, cursor="hand2")
                name.pack(fill="x", pady=(max(2, pad // 2), 0))
                sub = tk.Label(row, text=self.short_path(v["path"], small[1]), bg=bg, fg=c["dim"],
                               font=small, anchor="w", padx=14, cursor="hand2")
                sub.pack(fill="x", pady=(0, max(2, pad // 2)))
                parts = (row, name, sub)
            else:
                row = tk.Label(box, text=v["name"], bg=bg, fg=fg, font=self.font, anchor="w",
                               padx=14, cursor="hand2")
                row.pack(fill="x", ipady=pad)
                parts = (row,)
            for w in parts:
                w.bind("<Button-1>", lambda e, i=i: self.launch(i))
                w.bind("<Enter>", lambda e, i=i: self.hover(i))

    def short_path(self, p, size):
        """Pfad mit ~ für das Home-Verzeichnis, vorne gekürzt, damit der Ordnerende sichtbar bleibt."""
        home = str(Path.home())
        if p.lower().startswith(home.lower()):
            p = "~" + p[len(home):]
        maxc = max(12, int((self.width - 28) / (size * 0.75)))
        return p if len(p) <= maxc else "…" + p[-(maxc - 1):]

    def render_settings(self):
        c = self.c
        box = tk.Frame(self.body, bg=c["bg"])
        box.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        small = (self.font[0], max(8, self.font[1] - 1))

        # Presets
        pre = tk.Frame(box, bg=c["bg"])
        pre.pack(fill="x", pady=(0, 8))
        tk.Label(pre, text="Preset", bg=c["bg"], fg=c["fg"], font=self.font, anchor="w").pack(side="left")
        for name in THEMES:
            on = name == self.preset
            b = tk.Label(pre, text=name, font=small, padx=10, pady=2, cursor="hand2",
                         bg=c["accent"] if on else c["hover"],
                         fg=contrast_fg(c["accent"]) if on else c["fg"])
            b.pack(side="right", padx=(6, 0))
            b.bind("<Button-1>", lambda e, n=name: self.set_preset(n))

        # Farben
        for k, label in COLOR_LABELS:
            row = tk.Frame(box, bg=c["bg"], cursor="hand2")
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=c["bg"], fg=c["fg"], font=self.font, anchor="w",
                     cursor="hand2").pack(side="left")
            sw = tk.Label(row, text=c[k].lower(), bg=c[k], fg=contrast_fg(c[k]), font=small, width=9,
                          pady=3, cursor="hand2", highlightthickness=1, highlightbackground=c["border"])
            sw.pack(side="right")
            for wgt in (row, sw, *row.winfo_children()):
                wgt.bind("<Button-1>", lambda e, k=k: self.pick(k))

        # Fußzeile
        foot = tk.Frame(box, bg=c["bg"])
        foot.pack(fill="x", pady=(12, 0))
        save = tk.Label(foot, text="Speichern", font=small, padx=12, pady=4, cursor="hand2",
                        bg=c["accent"], fg=contrast_fg(c["accent"]))
        save.pack(side="right")
        save.bind("<Button-1>", lambda e: self.save())
        back = tk.Label(foot, text="Zurück", font=small, padx=12, pady=4, cursor="hand2",
                        bg=c["hover"], fg=c["fg"])
        back.pack(side="right", padx=(0, 6))
        back.bind("<Button-1>", lambda e: self.toggle_settings())
        if self.status:
            tk.Label(foot, text=self.status, bg=c["bg"], fg=c["dim"], font=small).pack(side="left")

    # ---- Einstellungen
    def toggle_settings(self):
        self.mode = "list" if self.mode == "settings" else "settings"
        self.status = ""
        self.filter, self.sel, self.off = "", 0, 0
        self.shown = list(self.all)
        self.render()
        self.root.focus_force()

    def set_preset(self, name):
        self.preset = name
        self.c = dict(THEMES[name])
        self.status = ""
        self.render()

    def pick(self, k):
        from tkinter import colorchooser  # erst bei Bedarf laden -> schneller Start
        self.modal = True
        self.root.attributes("-topmost", False)
        try:
            _rgb, hexv = colorchooser.askcolor(color=self.c[k], parent=self.root,
                                               title=dict(COLOR_LABELS)[k])
        finally:
            self.modal = False
            self.root.attributes("-topmost", True)
        if hexv:
            self.c[k] = hexv
            self.status = "nicht gespeichert"
            self.render()
        self.root.focus_force()

    def save(self):
        err = save_theme(self.cfg_path, self.preset, self.c)
        self.status = err or "gespeichert"
        self.render()

    # ---- Liste
    def hover(self, i):
        if i != self.sel:
            self.sel = i
            self.render()

    def move(self, d):
        if self.mode == "list" and self.shown:
            self.sel = (self.sel + d) % len(self.shown)
            self.render()

    def scroll(self, d):
        if self.mode == "list" and len(self.shown) > self.maxv:
            self.off = max(0, min(self.off + d, len(self.shown) - self.maxv))
            self.sel = max(self.off, min(self.sel, self.off + self.maxv - 1))
            self.render()

    def on_key(self, e):
        if self.mode != "list":
            return
        if e.keysym == "BackSpace":
            self.filter = self.filter[:-1]
        elif e.char and e.char.isprintable() and e.char.strip():
            self.filter += e.char
        else:
            return
        f = self.filter.lower()
        self.shown = [v for v in self.all if f in v["name"].lower()]
        self.sel = self.off = 0
        self.render()

    def launch(self, i):
        if self.mode == "list" and 0 <= i < len(self.shown):
            try:
                open_vault(self.shown[i]["path"])
            except OSError as err:
                print(err, file=sys.stderr)
                return
            if self.cfg["close_after_launch"]:
                self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    path = config_path()
    cfg = load_config(path)
    vaults = discover(cfg)
    Launcher(cfg, vaults, path).run()


if __name__ == "__main__":
    main()
