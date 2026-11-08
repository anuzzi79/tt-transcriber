from __future__ import annotations

import ctypes
from ctypes import wintypes
import queue
import threading

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_ALT = 0x0001
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000


def parse_hotkey(value: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in value.split("+")]
    if not parts or len(parts[-1]) != 1 or not parts[-1].isalnum():
        raise ValueError("Use a shortcut such as Ctrl+Alt+Q")
    modifiers = MOD_NOREPEAT
    for part in parts[:-1]:
        if part in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        else:
            raise ValueError("Only Ctrl, Alt and Shift modifiers are supported")
    if not (modifiers & (MOD_CONTROL | MOD_ALT)):
        raise ValueError("Use Ctrl and/or Alt with a letter or digit")
    return modifiers, ord(parts[-1])


class Hotkey:
    def __init__(self, events: queue.Queue):
        self.events = events
        self.thread = None
        self.thread_id = None
        self.ready = threading.Event()
        self.error = None

    def start(self, shortcut: str) -> None:
        self.stop()
        modifiers, key = parse_hotkey(shortcut)
        self.ready.clear()
        self.error = None
        self.thread = threading.Thread(target=self._loop, args=(modifiers, key), daemon=True)
        self.thread.start()
        self.ready.wait(timeout=2)
        if self.error:
            raise RuntimeError(self.error)

    def _loop(self, modifiers: int, key: int) -> None:
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not ctypes.windll.user32.RegisterHotKey(None, 1, modifiers, key):
            self.error = "This shortcut is already in use. Choose another in Options."
            self.ready.set()
            return
        self.ready.set()
        message = wintypes.MSG()
        try:
            while ctypes.windll.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    self.events.put(("hotkey", None))
        finally:
            ctypes.windll.user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread:
            self.thread.join(timeout=1)
        self.thread = None
        self.thread_id = None
