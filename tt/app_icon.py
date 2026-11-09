"""TT window/taskbar icon with a red recording glow."""

from __future__ import annotations

import base64
import ctypes
import math
import struct
import tkinter as tk
import zlib


APP_ID = "AntonioNuzzi.TTTranscriber"


def set_app_id():
    """Keep TT separate from the Python launcher in the Windows taskbar."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = (ctypes.c_wchar_p,)
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    result = shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    if result < 0:
        raise OSError(f"Could not set TT taskbar identity: {result:#x}")


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def icon_png(size: int, glow: float, recording: bool) -> bytes:
    """Generate one RGBA icon without adding an image library dependency."""
    scale = size / 32
    center = (size - 1) / 2
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)  # PNG filter: none
        for x in range(size):
            dx = (x - center) / scale
            dy = (y - center) / scale
            radius = math.hypot(dx, dy)
            if radius > 15.6:
                rgba = (0, 0, 0, 0)
            elif radius > 12.7:
                strength = max(0.0, 1.0 - (radius - 12.7) / 2.9)
                if recording:
                    rgba = (255, 35, 48, round(225 * glow * strength))
                else:
                    rgba = (43, 145, 193, round(150 * strength))
            else:
                rgba = (20, 39, 57, 255)
                if 11.3 < radius <= 12.7:
                    rgba = ((round(85 + 170 * glow), round(12 + 42 * glow),
                             round(20 + 45 * glow), 255)
                            if recording else (54, 170, 216, 255))

            # Two compact white T glyphs, crisp at taskbar size.
            glyph_x = dx + 15.5
            glyph_y = dy + 15.5
            first_t = (7.0 <= glyph_x < 14.0 and 11.0 <= glyph_y < 13.0) or (
                10.0 <= glyph_x < 12.0 and 13.0 <= glyph_y < 21.0)
            second_t = (18.0 <= glyph_x < 25.0 and 11.0 <= glyph_y < 13.0) or (
                21.0 <= glyph_x < 23.0 and 13.0 <= glyph_y < 21.0)
            if first_t or second_t:
                rgba = (255, 255, 255, 255)
            pixels.extend(rgba)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(
        b"IDAT", zlib.compress(bytes(pixels), 6)) + _chunk(b"IEND", b"")


class TaskbarIconPulse:
    PERIOD_MS = 330
    FRAME_COUNT = 6
    FRAME_MS = PERIOD_MS // FRAME_COUNT

    def __init__(self, root: tk.Tk):
        self.root = root
        self.idle = self._images(0, recording=False)
        self.frames = [
            self._images(0.14 + 0.86 * (1 - math.cos(2 * math.pi * frame /
                                                  self.FRAME_COUNT)) / 2,
                         recording=True)
            for frame in range(self.FRAME_COUNT)
        ]
        self.active = False
        self.frame = 0
        self.after_id: str | None = None
        self._show(self.idle)

    def _images(self, glow: float, recording: bool) -> tuple[tk.PhotoImage, tk.PhotoImage]:
        return tuple(
            tk.PhotoImage(master=self.root,
                          data=base64.b64encode(icon_png(size, glow, recording)),
                          format="png")
            for size in (32, 64)
        )

    def _show(self, images: tuple[tk.PhotoImage, tk.PhotoImage]):
        self.root.iconphoto(False, *images)

    def set_active(self, active: bool):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.active = active
        self.frame = 0
        if active:
            self._tick()
        else:
            self._show(self.idle)

    def _tick(self):
        if not self.active:
            return
        self._show(self.frames[self.frame])
        self.frame = (self.frame + 1) % self.FRAME_COUNT
        self.after_id = self.root.after(self.FRAME_MS, self._tick)

    def close(self):
        self.set_active(False)
