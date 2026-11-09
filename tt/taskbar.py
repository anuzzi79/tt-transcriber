"""Small animated window icon for the Windows taskbar."""

from __future__ import annotations

import math
import tkinter as tk


class TaskbarPulse:
    PERIOD_MS = 330
    FRAME_COUNT = 6
    FRAME_MS = PERIOD_MS // FRAME_COUNT

    def __init__(self, root: tk.Tk):
        self.root = root
        self.idle_icon = self._make_icon("#2b7498")
        self.recording_icons = [
            self._make_icon(self._red_at(frame))
            for frame in range(self.FRAME_COUNT)
        ]
        self.active = False
        self.frame = 0
        self.after_id: str | None = None
        self.root.iconphoto(False, self.idle_icon)

    @staticmethod
    def _red_at(frame: int) -> str:
        brightness = (1 - math.cos(2 * math.pi * frame / TaskbarPulse.FRAME_COUNT)) / 2
        red = round(105 + 150 * brightness)
        green = round(18 + 34 * brightness)
        blue = round(29 + 42 * brightness)
        return f"#{red:02x}{green:02x}{blue:02x}"

    def _make_icon(self, color: str) -> tk.PhotoImage:
        icon = tk.PhotoImage(master=self.root, width=32, height=32)
        icon.put("#17324d", to=(0, 0, 32, 32))
        for y in range(4, 28):
            half_width = math.sqrt(max(0, 12 * 12 - (y - 15.5) ** 2))
            left = max(0, math.ceil(15.5 - half_width))
            right = min(32, math.floor(15.5 + half_width) + 1)
            if left < right:
                icon.put(color, to=(left, y, right, y + 1))
        # Two white T glyphs remain readable at taskbar size.
        for x in (*range(8, 15), *range(18, 25)):
            icon.put("#ffffff", to=(x, 11, x + 1, 13))
        for x in (11, 21):
            icon.put("#ffffff", to=(x, 13, x + 2, 22))
        return icon

    def set_active(self, active: bool):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.active = active
        self.frame = 0
        if active:
            self._tick()
        else:
            self.root.iconphoto(False, self.idle_icon)

    def _tick(self):
        if not self.active:
            return
        self.root.iconphoto(False, self.recording_icons[self.frame])
        self.frame = (self.frame + 1) % self.FRAME_COUNT
        self.after_id = self.root.after(self.FRAME_MS, self._tick)

    def close(self):
        self.set_active(False)
