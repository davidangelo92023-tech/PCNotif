import ctypes
import json
import os
import sqlite3
import sys
import time
import winreg
import xml.etree.ElementTree as ET
from ctypes import wintypes
import tkinter as tk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Notifications", "wpndatabase.db")
SEEN_PATH = os.path.join(APP_DIR, "seen.json")
SAVED_PATH = os.path.join(APP_DIR, "saved.json")
ERR_PATH = os.path.join(APP_DIR, "error.log")
NOTIF_DIR = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "Notifications")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "PCNotif"
POLL_MS = 5000
MAX_SHOW = 15

BG = "#1b1d24"
BG_HOVER = "#252a38"
BG2 = "#23262f"
FG = "#e8eaf2"
MUTED = "#8b90a3"
ACCENT = "#e03e50"
BORDER = "#3a3f52"
ITEM_BG = "#1f2230"

KNOWN = {
    "Discord": "Discord",
    "Proton.VPN": "Proton VPN",
    "C27EB4BA.DropboxOEM_xbfy0k16fey96!App": "Dropbox",
    "Microsoft.YourPhone_8wekyb3d8bbwe!App": "Your Phone",
    "MicrosoftWindows.Client.WebExperience_cw5n1h2txyewy!Widgets": "Widgets",
    "OperaSoftware.OperaWebBrowser.1786444838": "Opera",
    "AD2F1837.OMENCommandCenter_v10z8vjag6ke6!AD2F1837.OMENCommandCenter": "OMEN Command Center",
    "Microsoft.Windows.Explorer": "Windows Explorer",
}


def friendly(appid):
    if not appid:
        return "Unknown"
    if appid in KNOWN:
        return KNOWN[appid]
    after = appid.split("!")[-1]
    if len(after) <= 3 or after == "App":
        base = appid.split("!")[0]
    else:
        base = after
    base = base.split("_")[0]
    parts = [p for p in base.split(".") if p and not p.isdigit()]
    return parts[-1] if parts else (base or "Unknown")


def parse_payload(payload):
    if not payload:
        return "", ""
    try:
        root = ET.fromstring(payload)
        texts = []
        for el in root.iter():
            if el.tag.split("}")[-1] == "text" and el.get("placement") != "attribution":
                if el.text and el.text.strip():
                    texts.append(el.text.strip())
        if not texts:
            return "", ""
        return texts[0], " ".join(texts[1:])
    except Exception:
        return "", ""


def fmt_time(at):
    if not at:
        return ""
    try:
        local = time.localtime((at / 10000000) - 11644473600)
    except Exception:
        return ""
    now = time.localtime()
    if local.tm_yday == now.tm_yday and local.tm_year == now.tm_year:
        return time.strftime("%H:%M", local)
    return time.strftime("%b %d %H:%M", local)


def connect_ro():
    return sqlite3.connect("file:" + DB_PATH + "?mode=ro", uri=True)


def max_notif_id():
    try:
        con = connect_ro()
        try:
            row = con.execute("SELECT MAX(Id) FROM Notification").fetchone()
            return row[0] or 0
        finally:
            con.close()
    except Exception:
        return 0


def _rows(query, params):
    if not os.path.exists(DB_PATH):
        return []
    try:
        con = connect_ro()
        try:
            rows = con.execute(query, params).fetchall()
        finally:
            con.close()
    except Exception:
        return []
    out = []
    for rid, appid, at, payload in rows:
        title, body = parse_payload(payload)
        out.append({
            "id": rid,
            "app": friendly(appid),
            "title": title or "",
            "body": body,
            "time": fmt_time(at),
        })
    return out


def fetch_newer(watermark, limit=200):
    rows = _rows(
        "SELECT n.Id, h.PrimaryId, n.ArrivalTime, n.Payload "
        "FROM Notification n LEFT JOIN NotificationHandler h "
        "ON n.HandlerId = h.RecordId WHERE n.Id > ? ORDER BY n.Id DESC LIMIT ?",
        (watermark, limit),
    )
    rows.reverse()
    return rows


def fetch_recent(limit=MAX_SHOW):
    rows = _rows(
        "SELECT n.Id, h.PrimaryId, n.ArrivalTime, n.Payload "
        "FROM Notification n LEFT JOIN NotificationHandler h "
        "ON n.HandlerId = h.RecordId ORDER BY n.Id DESC LIMIT ?",
        (limit,),
    )
    rows.reverse()
    return rows


def load_watermark():
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            return int(json.load(f).get("watermark", 0))
    except Exception:
        return 0


def save_watermark(wm):
    try:
        with open(SEEN_PATH, "w", encoding="utf-8") as f:
            json.dump({"watermark": int(wm)}, f)
    except Exception:
        pass


def fetch_all():
    rows = _rows(
        "SELECT n.Id, h.PrimaryId, n.ArrivalTime, n.Payload "
        "FROM Notification n LEFT JOIN NotificationHandler h "
        "ON n.HandlerId = h.RecordId ORDER BY n.Id",
        (),
    )
    return rows


def load_saved():
    try:
        with open(SAVED_PATH, encoding="utf-8") as f:
            return int(json.load(f).get("saved", 0))
    except Exception:
        return 0


def save_saved(wm):
    try:
        with open(SAVED_PATH, "w", encoding="utf-8") as f:
            json.dump({"saved": int(wm)}, f)
    except Exception:
        pass


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except Exception:
        return False


def set_autostart(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.exists(exe):
                    exe = sys.executable
                cmd = '"%s" "%s"' % (exe, os.path.abspath(__file__))
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except Exception:
                    pass
    except Exception:
        pass


def _safe_name(s):
    s = "".join(c if c.isalnum() or c in " -_()[]" else "_" for c in s)
    s = s.strip(" ._")
    return s[:60] or "notification"


def cleanup_folder(days=7):
    if not os.path.isdir(NOTIF_DIR):
        return
    cutoff = time.time() - days * 86400
    for fn in os.listdir(NOTIF_DIR):
        if not fn.lower().endswith(".txt"):
            continue
        p = os.path.join(NOTIF_DIR, fn)
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
        except Exception:
            pass


def mark_folder_seen():
    if not os.path.isdir(NOTIF_DIR):
        return
    for fn in os.listdir(NOTIF_DIR):
        if fn.startswith("NEW - "):
            try:
                os.rename(os.path.join(NOTIF_DIR, fn), os.path.join(NOTIF_DIR, fn[6:]))
            except Exception:
                pass


def save_to_folder(items, new_from=0):
    if not os.path.isdir(NOTIF_DIR):
        try:
            os.makedirs(NOTIF_DIR)
        except Exception:
            return
    for it in items:
        try:
            base = "%06d - %s - %s.txt" % (it["id"], _safe_name(it["app"]), _safe_name(it["title"]))
            path = os.path.join(NOTIF_DIR, base)
            if it["id"] > new_from:
                path = os.path.join(NOTIF_DIR, "NEW - " + base)
            if os.path.exists(path):
                continue
            lines = ["App: " + it["app"], "Time: " + it["time"]]
            if it["title"]:
                lines.append("Title: " + it["title"])
            if it["body"]:
                lines.append("")
                lines.append(it["body"])
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass


class NotifWidget:
    def __init__(self):
        self.hover = False
        self.popup = None
        self.wm = load_watermark()
        if not os.path.exists(SEEN_PATH):
            self.wm = max_notif_id()
            save_watermark(self.wm)
        saved = load_saved()
        if not os.path.exists(SAVED_PATH):
            all_items = fetch_all()
            pending_save = [i for i in all_items if i["id"] > saved]
            save_to_folder(pending_save, saved)
            save_saved(max([i["id"] for i in all_items] + [saved]))
            mark_folder_seen()
        cleanup_folder()
        mark_folder_seen()
        set_autostart(True)
        self.pending = []
        self.pollwm = self.wm

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.root.attributes("-transparentcolor", None)

        self.lbl = tk.Label(
            self.root,
            text="",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 11, "bold"),
            padx=16,
            pady=7,
        )
        self.lbl.pack(fill="both", expand=True)

        self.lbl.bind("<Button-1>", lambda e: self.toggle())
        self.lbl.bind("<Button-3>", self.menu)
        self.lbl.bind("<Enter>", self._on_enter)
        self.lbl.bind("<Leave>", self._on_leave)

        self._place_widget()
        self.update_count()
        self._new_items()

    def _place_widget(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        rc = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rc), 0)
        w, h = 160, 40
        x = rc.left
        y = rc.bottom - h
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _on_enter(self, e):
        self.hover = True
        self.lbl.config(bg=BG_HOVER)

    def _on_leave(self, e):
        self.hover = False
        self.lbl.config(bg=BG)

    def update_count(self):
        n = len(self.pending)
        self.lbl.config(text="\U0001F514  " + (str(n) if n else "\u2014"))
        self.lbl.config(fg="#ff5c6c" if n else MUTED)

    def _new_items(self):
        items = fetch_newer(self.pollwm)
        if items:
            prev = self.pollwm
            self.pollwm = max(self.pollwm, items[-1]["id"])
            self.pending.extend(items)
            save_to_folder(items, prev)
            save_saved(self.pollwm)
            if len(self.pending) > 200:
                self.pending = self.pending[-200:]
            self.update_count()
            self._flash()
            self._toast(items)
            if self.popup and self.popup.winfo_exists():
                self.refresh_popup()
            return True
        return False

    def _flash(self):
        self.lbl.config(bg=ACCENT, fg="#ffffff")
        self.root.after(700, lambda: self.lbl.config(
            bg=BG_HOVER if self.hover else BG,
            fg="#ff5c6c" if self.pending else MUTED,
        ))

    def _toast(self, items):
        try:
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            w.configure(bg=BG2, highlightthickness=1, highlightbackground=BORDER)
            if len(items) == 1:
                it = items[0]
                head = "\U0001F514  " + it["app"]
                sub = it["title"] or it["body"]
            else:
                head = "\U0001F514  %d new notifications" % len(items)
                sub = items[-1]["app"] + (": " + items[-1]["title"] if items[-1]["title"] else "")
            tk.Label(w, text=head, bg=BG2, fg="#ff7d8b", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
            if sub:
                tk.Label(w, text=sub, bg=BG2, fg=FG, font=("Segoe UI", 10), wraplength=280, justify="left").pack(anchor="w", padx=12, pady=(2, 8))
            w.update_idletasks()
            ww = max(w.winfo_reqwidth(), 240)
            wh = w.winfo_reqheight()
            rc = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rc), 0)
            w.geometry("%dx%d+%d+%d" % (ww, wh, rc.right - ww - 12, rc.bottom - wh - 12))
            w.bind("<Button-1>", lambda e: self._toast_click(w))
            for c in w.winfo_children():
                c.bind("<Button-1>", lambda e: self._toast_click(w))
            self.root.after(6000, lambda: self._close_toast(w))
        except Exception:
            pass

    def _toast_click(self, w):
        self._close_toast(w)
        self.open_popup()

    def _close_toast(self, w):
        try:
            w.destroy()
        except Exception:
            pass

    def poll(self):
        self._new_items()
        self.root.after(POLL_MS, self.poll)

    def mark_read(self):
        if self.pending:
            self.wm = max(self.wm, self.pending[-1]["id"])
            save_watermark(self.wm)
            self.pending = []
            self.update_count()

    def toggle(self):
        if self.popup and self.popup.winfo_exists():
            self.close_popup()
        else:
            self.open_popup()

    def close_popup(self):
        if self.popup:
            try:
                self.popup.destroy()
            except Exception:
                pass
        self.popup = None

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _row(self, parent, it):
        fr = tk.Frame(parent, bg=ITEM_BG)
        fr.pack(fill="x", padx=8, pady=3)
        tk.Label(fr, text=it["app"], bg=ITEM_BG, fg="#ff7d8b", font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Label(fr, text=it["title"], bg=ITEM_BG, fg=FG, font=("Segoe UI", 9, "bold"), wraplength=340, justify="left").pack(anchor="w", padx=8, pady=(1, 0))
        if it["body"]:
            tk.Label(fr, text=it["body"], bg=ITEM_BG, fg=MUTED, font=("Segoe UI", 9), wraplength=340, justify="left").pack(anchor="w", padx=8)
        tk.Label(fr, text=it["time"], bg=ITEM_BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="e", padx=8, pady=(0, 6))

    def open_popup(self):
        self.close_popup()
        self.mark_read()
        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.attributes("-topmost", True)
        self.popup.configure(bg=BG2)
        self.popup.bind("<MouseWheel>", self._wheel)

        head = tk.Frame(self.popup, bg=BG2)
        head.pack(fill="x")
        tk.Label(head, text="\U0001F514  Notifications", bg=BG2, fg=FG, font=("Segoe UI", 10, "bold")).pack(side="left", padx=12, pady=(10, 6))
        tk.Label(head, text="\u2715", bg=BG2, fg=MUTED, font=("Segoe UI", 10)).pack(side="right", padx=12, pady=(10, 6))
        tk.Frame(head, bg=BORDER, height=1).pack(side="bottom", fill="x")

        self.canvas = tk.Canvas(self.popup, bg=BG2, highlightthickness=0)
        sb = tk.Scrollbar(self.popup, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.items_frame = tk.Frame(self.canvas, bg=BG2)
        win = self.canvas.create_window((0, 0), window=self.items_frame, anchor="nw")
        self.items_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.refresh_popup()

        ph = min(560, 90 + len(self.items_frame.winfo_children()) * 84)
        x = self.root.winfo_x()
        y = self.root.winfo_y() - ph
        if y < 0:
            y = self.root.winfo_y() + self.root.winfo_height()
        self.popup.geometry("400x%d+%d+%d" % (ph, x, y))

    def refresh_popup(self):
        if not (self.popup and self.popup.winfo_exists()):
            return
        for w in self.items_frame.winfo_children():
            w.destroy()
        items = fetch_recent(MAX_SHOW)
        if not items:
            tk.Label(self.items_frame, text="No notifications yet.", bg=BG2, fg=MUTED, font=("Segoe UI", 10)).pack(pady=14)
        for it in items:
            self._row(self.items_frame, it)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def menu(self, e):
        m = tk.Menu(self.root, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT, activeforeground="#fff")
        m.add_command(label="Mark all read", command=self.mark_read)
        m.add_command(label="Open notifications folder", command=self.open_folder)
        m.add_command(label="Open notification settings", command=lambda: os.startfile("ms-settings:notifications"))
        m.add_separator()
        m.add_command(label="Start with Windows" + ("  \u2714" if autostart_enabled() else ""), command=self.toggle_autostart)
        m.add_separator()
        m.add_command(label="Quit", command=self.root.destroy)
        m.tk_popup(e.x_root, e.y_root)

    def open_folder(self):
        mark_folder_seen()
        os.startfile(NOTIF_DIR)

    def toggle_autostart(self):
        set_autostart(not autostart_enabled())

    def run(self):
        self.poll()
        self.root.mainloop()


def main():
    try:
        NotifWidget().run()
    except Exception:
        import traceback
        try:
            with open(ERR_PATH, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
