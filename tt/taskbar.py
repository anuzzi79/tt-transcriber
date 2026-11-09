"""Red recording pulse behind the app's Windows taskbar button."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk
import uuid


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def _guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


class _TaskbarProgress:
    """Minimal ITaskbarList3 wrapper; all calls stay on Tk's UI thread."""

    _CLSID = _guid("56fdf344-fd6d-11d0-958a-006097c9a090")
    _IID = _guid("ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf")
    _NO_PROGRESS = 0
    _ERROR = 4

    def __init__(self, root: tk.Tk):
        self.root = root
        self.interface = ctypes.c_void_p()
        self.initialized = False

        ole32 = ctypes.OleDLL("ole32")
        ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoCreateInstance.argtypes = (ctypes.POINTER(_GUID), ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(_GUID),
                                           ctypes.POINTER(ctypes.c_void_p))
        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = ()
        result = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
        if result < 0:
            raise OSError(f"COM initialization failed: {result:#x}")
        self.initialized = True
        try:
            result = ole32.CoCreateInstance(ctypes.byref(self._CLSID), None, 1,
                                            ctypes.byref(self._IID),
                                            ctypes.byref(self.interface))
            if result < 0:
                raise OSError(f"Windows taskbar API unavailable: {result:#x}")
        except Exception:
            self.close()
            raise

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetParent.argtypes = (wintypes.HWND,)
        user32.GetParent.restype = wintypes.HWND
        self.hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()

    def _call(self, index: int, *args, argtypes=()):
        vtable = ctypes.cast(self.interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
        result = method(self.interface, *args)
        if result < 0:
            raise OSError(f"Windows taskbar call failed: {result:#x}")

    def show_red(self, value: int):
        self._call(10, self.hwnd, self._ERROR,
                   argtypes=(wintypes.HWND, wintypes.DWORD))
        self._call(9, self.hwnd, value, 100,
                   argtypes=(wintypes.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong))

    def clear(self):
        if self.interface:
            self._call(10, self.hwnd, self._NO_PROGRESS,
                       argtypes=(wintypes.HWND, wintypes.DWORD))

    def close(self):
        if self.interface:
            self._call(2)  # IUnknown::Release
            self.interface = ctypes.c_void_p()
        if self.initialized:
            ctypes.OleDLL("ole32").CoUninitialize()
            self.initialized = False


class TaskbarPulse:
    PERIOD_MS = 330
    FRAME_COUNT = 6
    FRAME_MS = PERIOD_MS // FRAME_COUNT
    VALUES = (15, 40, 70, 100, 70, 40)

    def __init__(self, root: tk.Tk):
        self.root = root
        self.progress: _TaskbarProgress | None = None
        self.active = False
        self.frame = 0
        self.after_id: str | None = None

    def set_active(self, active: bool):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.active = active
        self.frame = 0
        if active:
            try:
                if self.progress is None:
                    self.root.update_idletasks()
                    self.progress = _TaskbarProgress(self.root)
                self._tick()
            except OSError:
                self.active = False
                if self.progress:
                    self.progress.close()
                    self.progress = None
        elif self.progress:
            try:
                self.progress.clear()
            except OSError:
                pass

    def _tick(self):
        if not self.active or self.progress is None:
            return
        try:
            self.progress.show_red(self.VALUES[self.frame])
        except OSError:
            self.active = False
            self.progress.close()
            self.progress = None
            return
        self.frame = (self.frame + 1) % self.FRAME_COUNT
        self.after_id = self.root.after(self.FRAME_MS, self._tick)

    def close(self):
        self.set_active(False)
        if self.progress:
            self.progress.close()
            self.progress = None
