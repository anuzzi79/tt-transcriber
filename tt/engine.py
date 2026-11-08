from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import json
import os
import queue
import threading
import time
from urllib.parse import urlencode
import uuid

import numpy as np

# SoundCard 0.4.5 still uses NumPy's removed binary fromstring path.
_numpy_fromstring = np.fromstring
def _soundcard_fromstring(data, dtype=float, count=-1, sep=""):
    if not sep:
        try:
            # NumPy's old binary fromstring copied the WASAPI buffer. A view may
            # point at memory SoundCard releases immediately after this call.
            return np.frombuffer(data, dtype=dtype, count=count).copy()
        except TypeError:
            pass
    return _numpy_fromstring(data, dtype=dtype, count=count, sep=sep)
np.fromstring = _soundcard_fromstring

import soundcard as sc
import websockets

from .storage import Transcript
from .storage import rename_historical
from .voices import VoiceProfiles, voice_vector
from .diagnostics import log


SAMPLE_RATE = 16000
FRAMES = 3200  # 200 ms of PCM16, inside AssemblyAI's accepted chunk range.
MAX_BACKLOG = 5 * 60 * SAMPLE_RATE // FRAMES
URL = "wss://streaming.assemblyai.com/v3/ws"


class AudioSource:
    def __init__(self, kind: str, on_status):
        self.kind = kind
        self.on_status = on_status
        self.chunks: queue.Queue[tuple[float, bytes]] = queue.Queue(maxsize=MAX_BACKLOG)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.dropped_at: float | None = None
        self.history = deque(maxlen=200) if kind == "output" else None
        self.history_lock = threading.Lock()
        self.capture_count = 0

    def start(self) -> None:
        self.thread = threading.Thread(target=self._capture, daemon=True, name=f"TT-{self.kind}-capture")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _device(self):
        if self.kind == "output":
            speaker = sc.default_speaker()
            if speaker is None:
                raise RuntimeError("No default Windows output device")
            return speaker.id, sc.get_microphone(id=speaker.id, include_loopback=True)
        mic = sc.default_microphone()
        if mic is None:
            raise RuntimeError("No default Windows microphone")
        return mic.id, mic

    def _capture(self) -> None:
        while not self.stop_event.is_set():
            try:
                device_id, device = self._device()
                self.on_status(f"{self.kind.capitalize()}: {device.name}")
                with device.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=FRAMES) as recorder:
                    device_poll = 0
                    while not self.stop_event.is_set():
                        raw = recorder.record(numframes=FRAMES)
                        mono = np.asarray(raw, dtype=np.float32).reshape(-1)
                        pcm = (np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes()
                        self.capture_count += 1
                        if self.capture_count % 25 == 0:
                            log(f"capture {self.kind} packets={self.capture_count} rms={float(np.sqrt(np.mean(mono * mono))):.4f}")
                        now = time.time()
                        if self.history is not None:
                            with self.history_lock:
                                self.history.append((now, pcm))
                        try:
                            self.chunks.put_nowait((now, pcm))
                        except queue.Full:
                            try:
                                self.chunks.get_nowait()
                            except queue.Empty:
                                pass
                            self.chunks.put_nowait((now, pcm))
                            if self.dropped_at is None:
                                self.dropped_at = now
                        device_poll += 1
                        if device_poll >= 5:
                            device_poll = 0
                            current_id, _ = self._device()
                            if current_id != device_id:
                                self.on_status(f"{self.kind.capitalize()} device changed; switching")
                                break
            except Exception as exc:
                self.on_status(f"{self.kind.capitalize()} capture unavailable: {exc}")
                self.stop_event.wait(1)

    def audio_between(self, start: float, end: float) -> bytes:
        if self.history is None:
            return b""
        with self.history_lock:
            return b"".join(chunk for captured_at, chunk in self.history
                            if captured_at >= start and captured_at <= end + FRAMES / SAMPLE_RATE)


class MeetingEngine:
    def __init__(self, api_key: str, transcript: Transcript, event_sink):
        self.api_key = api_key
        self.transcript = transcript
        self.event_sink = event_sink
        self.stop_event = threading.Event()
        self.sources = {kind: AudioSource(kind, lambda msg, k=kind: self.event_sink("status", msg))
                        for kind in ("output", "microphone")}
        self.thread: threading.Thread | None = None
        self.speaker_aliases: dict[str, str] = {}
        self._file_lock = threading.Lock()
        self._voice_lock = threading.Lock()
        self.voice_profiles = VoiceProfiles()
        self.voice_samples: dict[str, list[np.ndarray]] = {}
        self.voice_seconds: dict[str, float] = {}
        self.pending_names: dict[str, str] = {}

    def start(self) -> None:
        for source in self.sources.values():
            source.start()
        self.thread = threading.Thread(target=self._run, daemon=True, name="TT-streaming")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        for source in self.sources.values():
            source.stop()
        if self.thread:
            self.thread.join(timeout=8)

    def assign_name(self, speaker: str, name: str) -> None:
        profile_id = None
        with self._voice_lock:
            profile_id = self.transcript.speaker_links.get(speaker)
            if profile_id and profile_id in self.voice_profiles.profiles:
                self.voice_profiles.rename(profile_id, name)
            elif self.voice_seconds.get(speaker, 0) >= 5:
                profile_id = uuid.uuid4().hex
                vector = np.median(np.stack(self.voice_samples[speaker]), axis=0)
                self.voice_profiles.add(profile_id, name, vector)
            else:
                self.pending_names[speaker] = name
        with self._file_lock:
            if profile_id:
                self.transcript.link_profile(speaker, profile_id, name)
                rename_historical(profile_id, name)
            else:
                self.transcript.rename(speaker, name)
        self.event_sink("refresh", None)

    async def _observe_voice(self, speaker: str, start: float, end: float, source: AudioSource) -> None:
        if end - start < 2:
            return
        audio = source.audio_between(start, end)
        vector = await asyncio.to_thread(voice_vector, audio)
        if vector is None:
            return
        profile_id = None
        name = None
        with self._voice_lock:
            self.voice_samples.setdefault(speaker, []).append(vector)
            self.voice_seconds[speaker] = self.voice_seconds.get(speaker, 0) + (end - start)
            if self.voice_seconds[speaker] < 5:
                return
            average = np.median(np.stack(self.voice_samples[speaker]), axis=0)
            if speaker in self.pending_names:
                name = self.pending_names.pop(speaker)
                profile_id = uuid.uuid4().hex
                self.voice_profiles.add(profile_id, name, average)
            elif speaker not in self.transcript.speaker_links:
                found = self.voice_profiles.match(average)
                if found:
                    profile_id, name = found
        if profile_id and name:
            with self._file_lock:
                self.transcript.link_profile(speaker, profile_id, name)
            self.event_sink("refresh", None)

    def _run(self) -> None:
        try:
            asyncio.run(self._run_async())
        except Exception as exc:
            self.event_sink("error", str(exc))
        finally:
            self.stop_event.set()
            for source in self.sources.values():
                source.stop()
            self.event_sink("stopped", str(self.transcript.path))

    async def _run_async(self) -> None:
        await asyncio.gather(*(self._stream(kind, source) for kind, source in self.sources.items()))

    async def _stream(self, kind: str, source: AudioSource) -> None:
        failure_started = None
        generation = 0
        while not self.stop_event.is_set():
            model = os.environ.get("TT_SPEECH_MODEL", "universal-3-6-pro")
            params = {"sample_rate": SAMPLE_RATE, "speech_model": model, "encoding": "pcm_s16le"}
            if model == "universal-3-6-pro":
                params.update({"mode": "balanced", "prompt": "English software engineering meeting."})
            if kind == "output" and model == "universal-3-6-pro":
                params["speaker_labels"] = "true"
            log(f"opening_connection {kind} model={model} encoding=pcm_s16le")
            try:
                async with websockets.connect(URL + "?" + urlencode(params),
                                               additional_headers={"Authorization": self.api_key},
                                               max_size=2_000_000, open_timeout=10) as socket:
                    if failure_started:
                        self.event_sink("status", f"{kind.capitalize()} reconnected")
                        failure_started = None
                    else:
                        self.event_sink("status", f"{kind.capitalize()} connected")
                    generation += 1
                    log(f"connected {kind} generation={generation}")
                    await self._connected(socket, kind, source, generation)
            except Exception as exc:
                log(f"connection_error {kind} {type(exc).__name__} {str(exc)[:200]}")
                if self.stop_event.is_set():
                    break
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (401, 403):
                    self.stop_event.set()
                    raise RuntimeError("AssemblyAI rejected the API key or account access") from exc
                if failure_started is None:
                    failure_started = time.time()
                    with self._file_lock:
                        self.transcript.marker(f"{kind.capitalize()} transcription interrupted; reconnecting")
                self.event_sink("status", f"{kind.capitalize()} connection lost; reconnecting: {exc}")
                await asyncio.sleep(1)

    async def _connected(self, socket, kind: str, source: AudioSource, generation: int) -> None:
        opening = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
        log(f"opening {kind} type={opening.get('type')}")
        if opening.get("type") != "Begin":
            raise RuntimeError(f"Unexpected AssemblyAI opening event: {opening.get('type')}")
        stream_started_at = None
        async def send_audio():
            nonlocal stream_started_at
            # Pace against a fixed monotonic timeline. Resetting this deadline
            # after every send would add network/scheduler overhead to each
            # 200 ms packet and make latency grow for the entire meeting.
            next_send_at = asyncio.get_running_loop().time()
            sent_chunks = 0
            while not self.stop_event.is_set():
                try:
                    captured_at, pcm = await asyncio.to_thread(source.chunks.get, True, 0.3)
                except queue.Empty:
                    continue
                if source.dropped_at is not None:
                    self.event_sink("status", f"{kind.capitalize()}: audio gap after five-minute buffer overflow")
                    with self._file_lock:
                        self.transcript.marker(f"{kind.capitalize()} audio gap: buffer limit exceeded")
                    source.dropped_at = None
                if stream_started_at is None:
                    stream_started_at = captured_at
                now = asyncio.get_running_loop().time()
                if next_send_at > now:
                    await asyncio.sleep(next_send_at - now)
                await socket.send(pcm)
                sent_chunks += 1
                if sent_chunks % 25 == 0:
                    self.event_sink("status", f"{kind.capitalize()} streaming audio ({sent_chunks} packets)")
                    log(f"sent {kind} packets={sent_chunks} queue={source.chunks.qsize()} audio_age_s={max(0, time.time() - captured_at):.2f}")
                next_send_at += len(pcm) / (2 * SAMPLE_RATE)
            await socket.send(json.dumps({"type": "Terminate"}))

        async def receive():
            while True:
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=2)
                except asyncio.TimeoutError:
                    if self.stop_event.is_set():
                        break
                    continue
                data = json.loads(message)
                log(f"recv {kind} type={data.get('type')} end={data.get('end_of_turn')} chars={len(data.get('transcript') or '')}")
                if data.get("type") == "Termination":
                    break
                if data.get("type") == "Error":
                    raise RuntimeError(f"AssemblyAI stream error: {data.get('message', 'unknown error')}")
                if data.get("type") != "Turn":
                    continue
                content = data.get("transcript", "").strip()
                if not content:
                    continue
                label = data.get("speaker_label") if kind == "output" else "Antonio"
                if kind == "output":
                    label = f"remote:{generation}:{label or 'UNKNOWN'}"
                if data.get("end_of_turn"):
                    words = data.get("words") or []
                    first_ms = words[0].get("start") if words else None
                    last_ms = words[-1].get("end") if words else None
                    if stream_started_at is not None and first_ms is not None:
                        when = datetime.fromtimestamp(stream_started_at + float(first_ms) / 1000).astimezone()
                    else:
                        when = datetime.now().astimezone()
                    with self._file_lock:
                        self.transcript.append(when, label, content)
                    self.event_sink("final", {"speaker": label, "text": content, "when": when})
                    if kind == "output" and not label.endswith(":UNKNOWN") and stream_started_at is not None and first_ms is not None and last_ms is not None:
                        asyncio.create_task(self._observe_voice(
                            label, stream_started_at + float(first_ms) / 1000,
                            stream_started_at + float(last_ms) / 1000, source))
                else:
                    self.event_sink("partial", {"speaker": label, "text": content})

        sender = asyncio.create_task(send_audio())
        receiver = asyncio.create_task(receive())
        done, pending = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_EXCEPTION)
        if self.stop_event.is_set():
            try:
                await asyncio.wait_for(asyncio.gather(sender, receiver), timeout=3)
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                pass
        else:
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
            raise ConnectionError(f"{kind} stream ended unexpectedly")
