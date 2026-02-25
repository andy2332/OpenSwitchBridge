#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import select
import threading
import termios
import tty
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Set

try:
    import tkinter as tk  # type: ignore
except ModuleNotFoundError:
    tk = None

try:
    from pynput import keyboard as pynput_keyboard  # type: ignore
except ModuleNotFoundError:
    pynput_keyboard = None

BUTTON_ORDER = [
    "Y", "X", "B", "A",
    "L", "R", "ZL", "ZR",
    "MINUS", "PLUS",
    "L_STICK", "R_STICK",
    "HOME", "CAPTURE",
    "UP", "DOWN", "LEFT", "RIGHT",
]

# Tk keysym -> Switch button
KEY_TO_BUTTON: Dict[str, str] = {
    "j": "Y",
    "i": "X",
    "k": "B",
    "l": "A",
    "q": "L",
    "e": "R",
    "1": "ZL",
    "3": "ZR",
    "BackSpace": "MINUS",
    "Return": "PLUS",
    "z": "L_STICK",
    "c": "R_STICK",
    "h": "HOME",
    "p": "CAPTURE",
    "Up": "UP",
    "Down": "DOWN",
    "Left": "LEFT",
    "Right": "RIGHT",
}

STICK_CENTER = 2048
STICK_MIN = 0
STICK_MAX = 4095

# Tk/pynput keysym -> stick direction
# L stick: WASD
# R stick: 8/5/4/6 (up/down/left/right)
KEY_TO_STICK_DIR: Dict[str, tuple[str, str]] = {
    "w": ("L", "UP"),
    "s": ("L", "DOWN"),
    "a": ("L", "LEFT"),
    "d": ("L", "RIGHT"),
    "8": ("R", "UP"),
    "5": ("R", "DOWN"),
    "4": ("R", "LEFT"),
    "6": ("R", "RIGHT"),
}


class HttpClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path: str, params: dict | None = None) -> None:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}{query}"
        req = urllib.request.Request(url=url, method="GET")
        with self.opener.open(req, timeout=self.timeout):
            return


class KeyboardBridge:
    def __init__(self, host: str, port: int, timeout: float):
        self.client = HttpClient(f"http://{host}:{port}", timeout)
        self.pressed_keys: Set[str] = set()
        self.active_buttons: Set[str] = set()
        self.left_stick = (STICK_CENTER, STICK_CENTER)
        self.right_stick = (STICK_CENTER, STICK_CENTER)
        self._lock = threading.Lock()

    def _compose_buttons(self) -> str:
        ordered = [btn for btn in BUTTON_ORDER if btn in self.active_buttons]
        return "+".join(ordered)

    def _compose_input_params(self) -> dict:
        params: dict[str, str | int] = {}
        buttons = self._compose_buttons()
        if buttons:
            params["buttons"] = buttons
        params["lx"] = self.left_stick[0]
        params["ly"] = self.left_stick[1]
        params["rx"] = self.right_stick[0]
        params["ry"] = self.right_stick[1]
        return params

    @staticmethod
    def _axis_value(neg: bool, pos: bool) -> int:
        if neg == pos:
            return STICK_CENTER
        return STICK_MAX if pos else STICK_MIN

    @staticmethod
    def _is_mapped_key(key: str) -> bool:
        return key in KEY_TO_BUTTON or key in KEY_TO_STICK_DIR

    def _push_state(self) -> None:
        has_stick_move = (
            self.left_stick != (STICK_CENTER, STICK_CENTER)
            or self.right_stick != (STICK_CENTER, STICK_CENTER)
        )
        buttons = self._compose_buttons()
        try:
            if buttons or has_stick_move:
                params = self._compose_input_params()
                self.client.get("/input", params)
                print(f"[INPUT] {params}")
            else:
                self.client.get("/release")
                print("[RELEASE]")
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"[WARN] request failed: {exc}")

    def _refresh_buttons(self) -> None:
        new_buttons: Set[str] = set()
        l_dirs: Set[str] = set()
        r_dirs: Set[str] = set()
        for key in self.pressed_keys:
            if key in KEY_TO_BUTTON:
                new_buttons.add(KEY_TO_BUTTON[key])
            elif key in KEY_TO_STICK_DIR:
                stick, direction = KEY_TO_STICK_DIR[key]
                if stick == "L":
                    l_dirs.add(direction)
                else:
                    r_dirs.add(direction)
            elif key.startswith("btn:"):
                new_buttons.add(key[4:])
        new_left = (
            self._axis_value("LEFT" in l_dirs, "RIGHT" in l_dirs),
            self._axis_value("UP" in l_dirs, "DOWN" in l_dirs),
        )
        new_right = (
            self._axis_value("LEFT" in r_dirs, "RIGHT" in r_dirs),
            self._axis_value("UP" in r_dirs, "DOWN" in r_dirs),
        )

        if (
            new_buttons == self.active_buttons
            and new_left == self.left_stick
            and new_right == self.right_stick
        ):
            return
        self.active_buttons = new_buttons
        self.left_stick = new_left
        self.right_stick = new_right
        self._push_state()

    def press_keysym(self, key: str) -> None:
        if not self._is_mapped_key(key):
            return
        with self._lock:
            if key in self.pressed_keys:
                return
            self.pressed_keys.add(key)
            self._refresh_buttons()

    def release_keysym(self, key: str) -> None:
        if not self._is_mapped_key(key):
            return
        with self._lock:
            if key not in self.pressed_keys:
                return
            self.pressed_keys.remove(key)
            self._refresh_buttons()

    def toggle_keysym(self, key: str) -> None:
        if not self._is_mapped_key(key):
            return
        with self._lock:
            if key in self.pressed_keys:
                self.pressed_keys.remove(key)
            else:
                self.pressed_keys.add(key)
            self._refresh_buttons()

    def on_press(self, event: tk.Event) -> None:
        self.press_keysym(event.keysym)

    def on_release(self, event: tk.Event) -> None:
        self.release_keysym(event.keysym)

    def shutdown(self) -> None:
        try:
            self.client.get("/release")
        except (urllib.error.URLError, TimeoutError):
            pass


class CliKeyboardReader:
    def __init__(self, bridge: KeyboardBridge):
        self.bridge = bridge
        self.fd = None
        self.old_term = None

    def _handle_arrow(self, arrow_seq: str) -> str | None:
        # ANSI arrows: ESC [ A/B/C/D
        mapping = {
            "A": "Up",
            "B": "Down",
            "C": "Right",
            "D": "Left",
        }
        return mapping.get(arrow_seq)

    def _setup_raw_mode(self) -> None:
        self.fd = os.open("/dev/tty", os.O_RDONLY)
        self.old_term = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)

    def _restore_terminal(self) -> None:
        if self.fd is not None and self.old_term is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_term)
        if self.fd is not None:
            os.close(self.fd)
        self.fd = None
        self.old_term = None

    def loop(self) -> int:
        if not os.path.exists("/dev/tty"):
            raise RuntimeError("No controlling TTY found")

        print("CLI mode (no tkinter).")
        print("操作说明：")
        print("- 按键切换按下/松开状态（toggle）")
        print("- 回车=PLUS, 退格=MINUS, 方向键=DPAD")
        print("- 按 r 可一键释放全部，按 q 退出")
        print("")
        print(build_help_text("CLI", 0))
        print("")

        self._setup_raw_mode()
        try:
            while True:
                rlist, _, _ = select.select([self.fd], [], [], 0.2)
                if not rlist:
                    continue
                ch = os.read(self.fd, 1)
                if not ch:
                    continue
                b = ch[0]

                if b == 3:  # Ctrl+C
                    break
                if b == ord("q"):
                    break
                if b == ord("r"):
                    self.bridge.pressed_keys.clear()
                    self.bridge._refresh_buttons()
                    continue
                if b in (8, 127):
                    self.bridge.toggle_keysym("BackSpace")
                    continue
                if b in (10, 13):
                    self.bridge.toggle_keysym("Return")
                    continue
                if b == 27:
                    seq = os.read(self.fd, 2)
                    if len(seq) == 2 and seq[0] == ord("["):
                        keysym = self._handle_arrow(chr(seq[1]))
                        if keysym:
                            self.bridge.toggle_keysym(keysym)
                    continue

                ch_str = chr(b)
                self.bridge.toggle_keysym(ch_str.lower())
        finally:
            self._restore_terminal()
            self.bridge.shutdown()
            print("\nExited.")
        return 0


class PynputKeyboardReader:
    SPECIAL_KEY_MAP = {
        "Key.up": "Up",
        "Key.down": "Down",
        "Key.left": "Left",
        "Key.right": "Right",
        "Key.enter": "Return",
        "Key.backspace": "BackSpace",
    }

    def __init__(self, bridge: KeyboardBridge):
        self.bridge = bridge

    def _to_keysym(self, key) -> str | None:
        if hasattr(key, "char") and key.char:
            return key.char.lower()
        key_name = str(key)
        return self.SPECIAL_KEY_MAP.get(key_name)

    def loop(self) -> int:
        if pynput_keyboard is None:
            raise RuntimeError("pynput is not installed")

        print("CLI press/release mode (pynput).")
        print("按住=按下，松开=释放；按 ESC 退出。")

        def on_press(key):
            keysym = self._to_keysym(key)
            if keysym:
                self.bridge.press_keysym(keysym)
            if str(key) == "Key.esc":
                return False
            return None

        def on_release(key):
            keysym = self._to_keysym(key)
            if keysym:
                self.bridge.release_keysym(keysym)
            return None

        try:
            with pynput_keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                listener.join()
        finally:
            self.bridge.shutdown()
            print("Exited.")
        return 0


def build_help_text(host: str, port: int) -> str:
    return (
        f"Target: http://{host}:{port}\n"
        "Focus this window, then press keys:\n\n"
        "J/Y, I/X, K/B, L/A\n"
        "Q/L, E/R, 1/ZL, 3/ZR\n"
        "Backspace/MINUS, Enter/PLUS\n"
        "Z/L_STICK, C/R_STICK\n"
        "WASD -> Left Stick (LX/LY)\n"
        "8/5/4/6 -> Right Stick (RX/RY)\n"
        "H/HOME, P/CAPTURE\n"
        "Arrow keys -> D-Pad\n\n"
        "Close window or Ctrl+C to stop (auto release)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="PC keyboard to OpenSwitchBridge HTTP input")
    parser.add_argument("--host", default="192.168.4.1", help="ESP host/IP")
    parser.add_argument("--port", type=int, default=80, help="ESP HTTP port")
    parser.add_argument("--timeout", type=float, default=0.6, help="HTTP timeout seconds")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Force non-tk mode",
    )
    parser.add_argument(
        "--cli-toggle",
        action="store_true",
        help="Use terminal toggle mode (fallback mode)",
    )
    args = parser.parse_args()

    bridge = KeyboardBridge(args.host, args.port, args.timeout)
    use_cli = args.cli or tk is None
    if use_cli:
        if not args.cli_toggle and pynput_keyboard is not None:
            return PynputKeyboardReader(bridge).loop()
        if not args.cli_toggle and pynput_keyboard is None:
            print("[WARN] pynput not installed; falling back to toggle mode.")
            print("[WARN] Install with: python3 -m pip install pynput")
        return CliKeyboardReader(bridge).loop()

    root = tk.Tk()
    root.title("OpenSwitchBridge Keyboard Mapper")
    root.geometry("520x320")

    label = tk.Label(
        root,
        text=build_help_text(args.host, args.port),
        justify="left",
        anchor="nw",
        font=("Menlo", 12),
        padx=12,
        pady=12,
    )
    label.pack(fill="both", expand=True)

    root.bind("<KeyPress>", bridge.on_press)
    root.bind("<KeyRelease>", bridge.on_release)

    def on_close() -> None:
        bridge.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        bridge.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
