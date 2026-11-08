import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta

from tt.hotkey import parse_hotkey
from tt import storage


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.old_transcript_dir = os.environ.get("TT_TRANSCRIPT_DIR")
        os.environ["TT_TRANSCRIPT_DIR"] = str(Path(self.directory.name) / "transcripts")
        self.old_sessions = storage.SESSIONS_DIR
        storage.SESSIONS_DIR = Path(self.directory.name) / "sessions"
        self.old_app_dir = storage.APP_DIR
        storage.APP_DIR = Path(self.directory.name)
        self.old_openai_key = storage.OPENAI_KEY_FILE
        storage.OPENAI_KEY_FILE = Path(self.directory.name) / "openai.key"

    def tearDown(self):
        storage.SESSIONS_DIR = self.old_sessions
        storage.APP_DIR = self.old_app_dir
        storage.OPENAI_KEY_FILE = self.old_openai_key
        if self.old_transcript_dir is None:
            os.environ.pop("TT_TRANSCRIPT_DIR", None)
        else:
            os.environ["TT_TRANSCRIPT_DIR"] = self.old_transcript_dir
        self.directory.cleanup()

    def test_progressive_transcript_sorting_and_rename(self):
        transcript = storage.Transcript()
        now = datetime.now().astimezone()
        transcript.append(now + timedelta(seconds=2), "remote:A", "Second")
        self.assertIn("Person1: Second", transcript.path.read_text(encoding="utf-8"))
        transcript.append(now, "Antonio", "First")
        transcript.rename("remote:A", "Eric")
        lines = transcript.path.read_text(encoding="utf-8").splitlines()
        self.assertIn("Antonio: First", lines[0])
        self.assertIn("Eric: Second", lines[1])
        self.assertTrue(transcript.meta_path.exists())

    def test_hotkey_validation(self):
        self.assertEqual(parse_hotkey("Ctrl+Alt+Q")[1], ord("Q"))
        with self.assertRaises(ValueError):
            parse_hotkey("Q")

    def test_profile_rename_updates_saved_transcripts(self):
        first = storage.Transcript()
        second = storage.Transcript()
        stamp = datetime.now().astimezone()
        first.append(stamp, "remote:A", "Good morning")
        second.append(stamp, "remote:B", "Hello again")
        first.link_profile("remote:A", "voice-1", "Eric")
        second.link_profile("remote:B", "voice-1", "Eric")
        storage.rename_historical("voice-1", "Tony")
        self.assertIn("Tony: Good morning", first.path.read_text(encoding="utf-8"))
        self.assertIn("Tony: Hello again", second.path.read_text(encoding="utf-8"))

    def test_openai_key_is_protected_on_disk(self):
        storage.save_openai_api_key("test-key-only")
        self.assertNotIn(b"test-key-only", storage.OPENAI_KEY_FILE.read_bytes())
        self.assertEqual(storage.load_openai_api_key(), "test-key-only")


if __name__ == "__main__":
    unittest.main()
