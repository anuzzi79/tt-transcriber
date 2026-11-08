"""Small local acoustic voice profiles; matching needs live validation."""
from __future__ import annotations

import numpy as np

from .storage import load_settings, save_settings

RATE = 16000


def _mel(hz):
    return 2595 * np.log10(1 + hz / 700)


def _hz(mel):
    return 700 * (10 ** (mel / 2595) - 1)


def voice_vector(pcm: bytes) -> np.ndarray | None:
    """Return coarse timbre features; never persist the PCM audio."""
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    if samples.size < RATE * 2:
        return None
    frame = 400
    hop = 160
    frames = np.lib.stride_tricks.sliding_window_view(samples, frame)[::hop]
    if frames.size == 0:
        return None
    energy = np.sqrt(np.mean(frames * frames, axis=1))
    frames = frames[energy > max(0.012, float(np.percentile(energy, 40)))]
    if len(frames) < 70:
        return None
    frames = frames[::3][:400]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(frame), n=512)) ** 2
    mel_points = _hz(np.linspace(_mel(80), _mel(7600), 28))
    bins = np.floor((513 / RATE) * mel_points).astype(int)
    filters = np.zeros((26, 257), dtype=np.float32)
    for i in range(26):
        left, center, right = bins[i:i+3]
        for j in range(left, center):
            filters[i, j] = (j - left) / max(1, center - left)
        for j in range(center, right):
            filters[i, j] = (right - j) / max(1, right - center)
    logs = np.log(np.maximum(spectrum @ filters.T, 1e-7))
    index = np.arange(1, 14)[:, None]
    bank = np.arange(26)[None, :]
    dct = np.cos(np.pi * index * (bank + 0.5) / 26)
    mfcc = logs @ dct.T
    mean = mfcc.mean(axis=0)
    spread = mfcc.std(axis=0)
    # Normalize by the stable population-scale values rather than each vector's norm.
    features = np.concatenate((mean / 50, spread / 30))
    return features.astype(np.float32)


class VoiceProfiles:
    def __init__(self):
        self.settings = load_settings()
        self.profiles = self.settings.setdefault("profiles", {})

    def save(self):
        current = load_settings()
        current["profiles"] = self.profiles
        save_settings(current)

    def add(self, profile_id: str, name: str, vector: np.ndarray):
        self.profiles[profile_id] = {"name": name, "vector": vector.tolist()}
        self.save()

    def rename(self, profile_id: str, name: str):
        self.profiles[profile_id]["name"] = name
        self.save()

    def delete(self, profile_id: str):
        self.profiles.pop(profile_id, None)
        self.save()

    def match(self, vector: np.ndarray) -> tuple[str, str] | None:
        if not self.profiles:
            return None
        scores = []
        for profile_id, profile in self.profiles.items():
            saved = np.asarray(profile["vector"], dtype=np.float32)
            if saved.shape != vector.shape:
                continue
            distance = float(np.linalg.norm(vector - saved))
            scores.append((distance, profile_id, profile["name"]))
        scores.sort()
        if not scores:
            return None
        best = scores[0]
        if best[0] > 0.20:
            return None
        if len(scores) > 1 and scores[1][0] - best[0] < 0.06:
            return None
        return best[1], best[2]
