from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
from pathlib import Path
import uuid


APP_DIR = Path(os.environ.get("TT_DATA_DIR") or (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "TTTranscriber"))
SETTINGS_FILE = APP_DIR / "settings.json"
KEY_FILE = APP_DIR / "assemblyai.key"
OPENAI_KEY_FILE = APP_DIR / "openai.key"
SESSIONS_DIR = APP_DIR / "sessions"


def documents_dir() -> Path:
    if os.name != "nt":
        return Path.home() / "Documents"
    from uuid import UUID
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
    raw = UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le
    guid = GUID.from_buffer_copy(raw)
    result = ctypes.c_wchar_p()
    hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(result))
    if hr != 0:
        return Path.home() / "Documents"
    try:
        return Path(result.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(result)


def transcript_dir() -> Path:
    path = Path(os.environ.get("TT_TRANSCRIPT_DIR") or (documents_dir() / "3transcript"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"hotkey": "Ctrl+Alt+Q", "profiles": {}}


def save_settings(settings: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(SETTINGS_FILE)


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, object]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows protected storage is required")
    source, owner = _blob(data)
    destination = DATA_BLOB()
    function = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if protect:
        ok = function(ctypes.byref(source), "TT AssemblyAI key", None, None, None, 0, ctypes.byref(destination))
    else:
        ok = function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.pbData)


def save_api_key(key: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_bytes(base64.b64encode(_dpapi(key.strip().encode("utf-8"), True)))


def load_api_key() -> str:
    try:
        return _dpapi(base64.b64decode(KEY_FILE.read_bytes()), False).decode("utf-8")
    except FileNotFoundError:
        return ""


def save_openai_api_key(key: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    OPENAI_KEY_FILE.write_bytes(base64.b64encode(_dpapi(key.strip().encode("utf-8"), True)))


def load_openai_api_key() -> str:
    try:
        return _dpapi(base64.b64decode(OPENAI_KEY_FILE.read_bytes()), False).decode("utf-8")
    except FileNotFoundError:
        return ""


class Transcript:
    def __init__(self, started: datetime | None = None):
        self.started = started or datetime.now().astimezone()
        self.id = uuid.uuid4().hex
        folder = transcript_dir()
        base = f"TT_{self.started:%Y-%m-%d_%H-%M-%S}"
        self.path = folder / f"{base}.txt"
        duplicate = 2
        while self.path.exists():
            self.path = folder / f"{base}_{duplicate}.txt"
            duplicate += 1
        self.meta_path = SESSIONS_DIR / f"{self.id}.json"
        self.lines: list[dict] = []
        self.speaker_names: dict[str, str] = {}
        self.speaker_links: dict[str, str] = {}
        self.speaker_numbers: dict[str, int] = {}
        self.path.touch(exist_ok=False)
        self.persist()

    def label(self, speaker: str) -> str:
        if speaker == "Antonio":
            return "Antonio"
        if speaker == "SYSTEM":
            return "SYSTEM"
        if speaker not in self.speaker_numbers:
            self.speaker_numbers[speaker] = len(self.speaker_numbers) + 1
        return self.speaker_names.get(speaker) or f"Person{self.speaker_numbers[speaker]}"

    def append(self, when: datetime, speaker: str, text: str) -> None:
        self.label(speaker)
        item = {"when": when.isoformat(), "speaker": speaker, "text": text.strip()}
        position = len(self.lines)
        while position and self.lines[position - 1]["when"] > item["when"]:
            position -= 1
        self.lines.insert(position, item)
        if position == len(self.lines) - 1:
            with self.path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(self.format_line(item) + "\n")
                file.flush()
                os.fsync(file.fileno())
            self.persist()
        else:
            self.rewrite()

    def marker(self, text: str) -> None:
        self.append(datetime.now().astimezone(), "SYSTEM", text)

    def format_line(self, item: dict) -> str:
        when = datetime.fromisoformat(item["when"])
        if item["speaker"] == "SYSTEM":
            return f"[{when:%H:%M:%S}] [{item['text']}]"
        return f"[{when:%H:%M:%S}] {self.label(item['speaker'])}: {item['text']}"

    def rename(self, speaker: str, name: str) -> None:
        self.speaker_names[speaker] = name.strip()
        self.rewrite()

    def link_profile(self, speaker: str, profile_id: str, name: str) -> None:
        self.speaker_links[speaker] = profile_id
        self.speaker_names[speaker] = name
        self.rewrite()

    def rewrite(self) -> None:
        temporary = self.path.with_suffix(".txt.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            for item in self.lines:
                file.write(self.format_line(item) + "\n")
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.path)
        self.persist()

    def persist(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        data = {"id": self.id, "path": str(self.path), "started": self.started.isoformat(), "lines": self.lines,
                "speaker_names": self.speaker_names, "speaker_numbers": self.speaker_numbers,
                "speaker_links": self.speaker_links}
        temp = self.meta_path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.meta_path)


def rename_historical(profile_id: str, name: str) -> None:
    for path in SESSIONS_DIR.glob("*.json") if SESSIONS_DIR.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            speaker_names = data.get("speaker_names", {})
            links = data.get("speaker_links", {})
            linked = [speaker for speaker, linked_id in links.items() if linked_id == profile_id]
            if not linked:
                continue
            for speaker in linked:
                speaker_names[speaker] = name
            output = Path(data["path"])
            if not output.exists():
                continue
            def label(speaker: str) -> str:
                if speaker == "Antonio":
                    return "Antonio"
                return speaker_names.get(speaker) or f"Person{data['speaker_numbers'].get(speaker, 1)}"
            temp = output.with_suffix(".txt.tmp")
            with temp.open("w", encoding="utf-8", newline="\n") as file:
                for item in data["lines"]:
                    stamp = datetime.fromisoformat(item["when"]).strftime("%H:%M:%S")
                    if item["speaker"] == "SYSTEM":
                        file.write(f"[{stamp}] [{item['text']}]\n")
                    else:
                        file.write(f"[{stamp}] {label(item['speaker'])}: {item['text']}\n")
            temp.replace(output)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError, KeyError):
            continue
