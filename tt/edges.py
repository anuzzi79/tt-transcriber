"""Click-through red screen-border pulse while recording on Windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import math
import tkinter as tk


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _Rect),
                ("rcWork", _Rect), ("dwFlags", wintypes.DWORD)]


def _monitor_rectangles() -> list[tuple[int, int, int, int]]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    monitors = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.POINTER(_Rect),
                                      ctypes.c_ssize_t)
    user32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(_MonitorInfo))
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    def visit(handle, _hdc, _rectangle, _data):
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            rect = info.rcMonitor
            monitors.append((rect.left, rect.top,
                             rect.right - rect.left, rect.bottom - rect.top))
        return 1

    callback = callback_type(visit)
    user32.EnumDisplayMonitors.argtypes = (ctypes.c_void_p, ctypes.c_void_p,
                                           callback_type, ctypes.c_ssize_t)
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return monitors


class ScreenEdgePulse:
    PERIOD_MS = 330
    FRAME_COUNT = 6
    FRAME_MS = PERIOD_MS // FRAME_COUNT
    THICKNESS = 9

    _GWL_EXSTYLE = -20
    _WS_EX_TRANSPARENT = 0x20
    _WS_EX_TOOLWINDOW = 0x80
    _WS_EX_LAYERED = 0x80000
    _WS_EX_NOACTIVATE = 0x08000000
    _SWP_NOACTIVATE = 0x10
    _SWP_SHOWWINDOW = 0x40
    _HWND_TOPMOST = -1

    def __init__(self, root: tk.Tk):
        self.root = root
        self.windows: list[tk.Toplevel] = []
        self.active = False
        self.frame = 0
        self.after_id: str | None = None
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetParent.argtypes = (wintypes.HWND,)
        self.user32.GetParent.restype = wintypes.HWND
        self.user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
        self.user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        self.user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND,
                                           ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.UINT)
        self.user32.SetWindowPos.restype = wintypes.BOOL

    def _make_edge(self, x: int, y: int, width: int, height: int):
        edge = tk.Toplevel(self.root)
        edge.withdraw()
        edge.overrideredirect(True)
        edge.configure(bg="#ff2028")
        edge.attributes("-topmost", True)
        edge.attributes("-alpha", 0.05)
        edge.geometry(f"{width}x{height}+0+0")
        edge.update_idletasks()
        hwnd = self.user32.GetParent(edge.winfo_id()) or edge.winfo_id()
        style = self.user32.GetWindowLongPtrW(hwnd, self._GWL_EXSTYLE)
        style |= (self._WS_EX_TRANSPARENT | self._WS_EX_TOOLWINDOW |
                  self._WS_EX_LAYERED | self._WS_EX_NOACTIVATE)
        self.user32.SetWindowLongPtrW(hwnd, self._GWL_EXSTYLE, style)
        edge.deiconify()
        if not self.user32.SetWindowPos(hwnd, self._HWND_TOPMOST, x, y, width, height,
                                        self._SWP_NOACTIVATE | self._SWP_SHOWWINDOW):
            edge.destroy()
            raise ctypes.WinError(ctypes.get_last_error())
        self.windows.append(edge)

    def _create_edges(self):
        for x, y, width, height in _monitor_rectangles():
            thickness = min(self.THICKNESS, width // 2, height // 2)
            if thickness < 1:
                continue
            for bounds in ((x, y, width, thickness),
                           (x, y + height - thickness, width, thickness),
                           (x, y + thickness, thickness, height - 2 * thickness),
                           (x + width - thickness, y + thickness,
                            thickness, height - 2 * thickness)):
                if bounds[2] > 0 and bounds[3] > 0:
                    self._make_edge(*bounds)

    def set_active(self, active: bool):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.active = active
        self.frame = 0
        if active:
            try:
                if not self.windows:
                    self._create_edges()
                self._tick()
            except (OSError, tk.TclError):
                self.set_active(False)
        else:
            for edge in self.windows:
                edge.destroy()
            self.windows.clear()

    def _tick(self):
        if not self.active:
            return
        brightness = (1 - math.cos(2 * math.pi * self.frame / self.FRAME_COUNT)) / 2
        alpha = 0.12 + 0.74 * brightness
        for edge in self.windows:
            edge.attributes("-alpha", alpha)
        self.frame = (self.frame + 1) % self.FRAME_COUNT
        self.after_id = self.root.after(self.FRAME_MS, self._tick)

    def close(self):
        self.set_active(False)
