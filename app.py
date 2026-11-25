"""Graphene Heater - system tray controller for the Xiaomi Smart Graphene Heater."""
import ctypes
import json
import socket
import sys
import threading
import time
import winreg
from pathlib import Path

import pystray
import webview
from PIL import Image, ImageDraw

import logging

from heater.device import Heater, app_dir, resource

logging.basicConfig(
    filename=str(app_dir() / "app.log"),
    level=logging.INFO,
    format="%(asctime)s %(threadName)s %(levelname)s %(message)s",
)
log = logging.getLogger("heater")

APP_NAME = "Graphene Heater"
INSTANCE_PORT = 47615
POLL_SECONDS = 5
WIN_W, WIN_H = 380, 800
CONFIG_FILE = app_dir() / "config.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# --------------------------------------------------------------------------- config
def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"ip": "", "token": ""}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --hidden'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pyw}" "{Path(__file__).resolve()}" --hidden'


def get_autostart() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


# --------------------------------------------------------------------------- tray icon
def make_icon(on: bool, online: bool) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if not online:
        body, wave = (110, 110, 118, 255), (170, 170, 178, 255)
    elif on:
        body, wave = (255, 112, 40, 255), (255, 196, 120, 255)
    else:
        body, wave = (88, 96, 112, 255), (190, 198, 214, 255)
    # heater body (rounded panel) with three heat waves on top
    d.rounded_rectangle((8, 30, 56, 60), radius=8, fill=body)
    for i, x in enumerate((20, 32, 44)):
        d.line([(x, 8), (x - 4, 14), (x, 20), (x - 4, 26)], fill=wave if on else body, width=4, joint="curve")
    for x in (18, 26, 34, 42):
        d.line([(x + 2, 37), (x + 2, 53)], fill=(255, 255, 255, 110), width=2)
    return img


# --------------------------------------------------------------------------- controller
class Controller:
    def __init__(self):
        self.cfg = load_config()
        self.heater = None
        self.state = {}
        self.error = None
        self.online = False
        self.lock = threading.Lock()
        self.window = None
        self.icon = None
        self.stop = threading.Event()
        self.wake = threading.Event()

    # connection ------------------------------------------------------------
    def connect(self):
        ip, token = self.cfg.get("ip"), self.cfg.get("token")
        if not ip or not token:
            self.heater, self.online = None, False
            self.error = "Enter the heater's IP address and token in Settings."
            return False
        try:
            h = Heater(ip, token)
            h.connect()
            with self.lock:
                self.heater = h
                self.state = h.read_state()
                self.online, self.error = True, None
            return True
        except Exception as e:
            log.warning("connect to %s failed: %s", ip, e)
            with self.lock:
                self.heater, self.online, self.error = None, False, str(e)
            return False
        finally:
            self.update_tray()

    def refresh(self):
        if not self.heater:
            if not self.connect():
                return
        try:
            st = self.heater.read_state()
            with self.lock:
                self.state, self.online, self.error = st, True, None
        except Exception as e:
            log.warning("refresh failed: %s", e)
            with self.lock:
                self.online, self.error = False, str(e)
        self.update_tray()

    def poll_loop(self):
        try:
            self.connect()
        except Exception:
            log.exception("initial connect failed")
        while not self.stop.is_set():
            self.wake.wait(POLL_SECONDS)
            self.wake.clear()
            if self.stop.is_set():
                break
            try:
                self.refresh()
            except Exception:
                log.exception("poll failed")

    # tray ---------------------------------------------------------------------
    def update_tray(self):
        try:
            self._update_tray()
        except Exception:
            log.exception("tray update failed")

    def _update_tray(self):
        if not self.icon:
            return
        on = bool(self.state.get("power"))
        self.icon.icon = make_icon(on, self.online)
        if not self.online:
            tip = f"{APP_NAME}: offline"
        else:
            t = self.state.get("temperature")
            tgt = self.state.get("target_temp")
            tip = f"{APP_NAME}: {'On' if on else 'Off'}"
            if t is not None:
                tip += f" · room {t:.1f}°C"
            if on and tgt is not None:
                tip += f" · target {tgt}°C"
        self.icon.title = tip[:127]
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def toggle_window(self, *_):
        if not self.window:
            return
        if getattr(self, "visible", False):
            self.hide_window()
        else:
            self.show_window()

    def show_window(self, *_):
        x, y = window_position()
        self.window.move(x, y)
        self.window.show()
        self.window.restore()
        self.visible = True
        try:
            self.window.evaluate_js("window.onShown && window.onShown()")
        except Exception:
            pass

    def hide_window(self, *_):
        self.window.hide()
        self.visible = False

    def tray_power(self, *_):
        if self.heater:
            try:
                self.heater.set("power", not self.state.get("power"))
            except Exception:
                pass
            self.refresh()

    def quit(self, *_):
        self.stop.set()
        self.wake.set()
        if self.icon:
            self.icon.stop()
        if self.window:
            self.window.destroy()

    def run_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open", self.toggle_window, default=True),
            pystray.MenuItem(
                lambda _: "Turn off" if self.state.get("power") else "Turn on",
                self.tray_power,
                enabled=lambda _: self.online,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit),
        )
        self.icon = pystray.Icon("graphene_heater", make_icon(False, False), APP_NAME, menu)
        self.update_tray()
        self.icon.run()


# --------------------------------------------------------------------------- JS API
class Api:
    """Methods callable from the web UI via window.pywebview.api.*"""

    def __init__(self, ctl: Controller):
        self._ctl = ctl

    def _snapshot(self):
        c = self._ctl
        with c.lock:
            h = c.heater
            return {
                "online": c.online,
                "error": c.error,
                "state": dict(c.state),
                "schema": h.schema["features"] if h else None,
                "info": h.device_info if h else None,
            }

    def get_status(self):
        return self._snapshot()

    def refresh(self):
        self._ctl.refresh()
        return self._snapshot()

    def set(self, feature, value):
        c = self._ctl
        if not c.heater:
            return {**self._snapshot(), "error": "Not connected"}
        log.info("set %s = %r", feature, value)
        try:
            c.heater.set(feature, value)
            time.sleep(0.25)  # give the heater a moment before reading back
        except Exception as e:
            c.refresh()
            return {**self._snapshot(), "error": f"Could not change setting: {e}"}
        c.refresh()
        return self._snapshot()

    def get_settings(self):
        cfg = self._ctl.cfg
        return {"ip": cfg.get("ip", ""), "token": cfg.get("token", ""), "autostart": get_autostart()}

    def save_settings(self, ip, token, autostart):
        token = (token or "").strip().lower()
        ip = (ip or "").strip()
        if len(token) != 32 or any(ch not in "0123456789abcdef" for ch in token):
            return {**self._snapshot(), "error": "The token must be 32 hexadecimal characters."}
        try:
            set_autostart(bool(autostart))
        except OSError:
            pass
        self._ctl.cfg = {"ip": ip, "token": token}
        save_config(self._ctl.cfg)
        self._ctl.connect()
        return self._snapshot()

    def hide(self):
        self._ctl.hide_window()

    def quit(self):
        threading.Thread(target=self._ctl.quit, daemon=True).start()


# --------------------------------------------------------------------------- window helpers
def window_position():
    """Bottom-right corner of the work area (above the taskbar), in logical pixels."""
    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

    r = RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    try:
        scale = ctypes.windll.user32.GetDpiForSystem() / 96
    except Exception:
        scale = 1
    margin = 12
    h = window_height()
    return int(r.r / scale - WIN_W - margin), int(r.b / scale - h - margin)


def window_height() -> int:
    """Preferred height, shrunk to fit small or highly scaled screens (content then scrolls)."""
    try:
        work_h = ctypes.windll.user32.GetSystemMetrics(17)  # SM_CYFULLSCREEN
        scale = ctypes.windll.user32.GetDpiForSystem() / 96
        return int(min(WIN_H, work_h / scale - 40))
    except Exception:
        return WIN_H


def single_instance_or_signal() -> socket.socket | None:
    """Return a listening socket if we're the first instance; otherwise ask it to show."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", INSTANCE_PORT))
        s.listen(1)
        return s
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2) as c:
                c.sendall(b"show")
        except OSError:
            pass
        return None


def instance_listener(sock: socket.socket, ctl: Controller):
    while True:
        try:
            conn, _ = sock.accept()
            with conn:
                if conn.recv(16) == b"show" and ctl.window:
                    ctl.show_window()
        except OSError:
            break


def main():
    sock = single_instance_or_signal()
    if sock is None:
        return
    start_hidden = "--hidden" in sys.argv

    ctl = Controller()
    api = Api(ctl)
    x, y = window_position()
    ctl.window = webview.create_window(
        APP_NAME,
        url=str(resource("ui/index.html")),
        js_api=api,
        width=WIN_W,
        height=window_height(),
        x=x,
        y=y,
        resizable=False,
        frameless=True,
        easy_drag=False,
        hidden=start_hidden,
        background_color="#14161b",
    )
    ctl.visible = not start_hidden

    def on_closing():
        # The close box hides to tray instead of exiting
        if not ctl.stop.is_set():
            ctl.hide_window()
            return False
        return True

    ctl.window.events.closing += on_closing

    threading.Thread(target=instance_listener, args=(sock, ctl), daemon=True).start()
    threading.Thread(target=ctl.poll_loop, daemon=True).start()
    threading.Thread(target=ctl.run_tray, daemon=True).start()

    webview.start(private_mode=False, storage_path=str(app_dir() / "webview"))
    ctl.stop.set()
    if ctl.icon:
        ctl.icon.stop()


if __name__ == "__main__":
    main()
