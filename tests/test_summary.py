import json
import unittest
from unittest.mock import patch

from tt.summary import answer_question, line_at, question_input, summarize, summary_input


class SummaryTests(unittest.TestCase):
    def test_timeline_covers_all_finalized_lines(self):
        self.assertEqual(line_at(-10, 100, [1, 1, 1, 1]), 0)
        self.assertEqual(line_at(49, 100, [1, 1, 1, 1]), 1)
        self.assertEqual(line_at(100, 100, [1, 1, 1, 1]), 3)
        self.assertEqual(line_at(500, 100, [1, 1, 1, 1]), 3)
        self.assertEqual(line_at(20, 100, [1, 8, 1]), 1)

    def test_request_includes_global_context_and_exact_selection(self):
        lines = ["[10:00] Person1: First", "[10:01] Antonio: Second", "[10:02] Person2: Third"]
        prompt = summary_input(lines, 1, 1)
        self.assertIn("FULL MEETING TRANSCRIPT", prompt)
        self.assertIn(lines[0], prompt)
        selected = prompt.split("SELECTED EXCERPT", 1)[1]
        self.assertIn(lines[1], selected)
        self.assertNotIn(lines[0], selected)
        self.assertNotIn(lines[2], selected)

    def test_openai_receives_only_current_selection_as_target(self):
        class FakeResponses:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return type("Result", (), {"output_text": "Riassunto di prova"})()
        responses = FakeResponses()
        class FakeClient:
            def __init__(self, **kwargs):
                self.responses = responses
        with patch("openai.OpenAI", FakeClient):
            result = summarize("test-key", ["first", "second", "third"], 1, 2)
        self.assertEqual(result, "Riassunto di prova")
        self.assertEqual(responses.kwargs["model"], "gpt-6-luna")
        self.assertFalse(responses.kwargs["store"])
        self.assertIn("second\nthird", responses.kwargs["input"])

    def test_question_uses_latest_full_transcript_and_previous_dialogue(self):
        lines = ["[00:02] Person1: Earlier fact", "[00:06] Person2: Selected part",
                 "[00:08] Person1: Newly arrived fact"]
        previous = [{"selection": "00:03–00:05", "summary": "Old summary",
                     "questions_and_answers": [{"question": "Old question?", "answer": "Old answer."}]}]
        payload = json.loads(question_input(lines, "What happened later?", "Selected summary", [], previous))
        self.assertEqual(payload["full_transcript_at_question_time"], lines)
        self.assertEqual(payload["new_question"], "What happened later?")
        self.assertEqual(payload["dialogues_from_earlier_selections"], previous)
        self.assertEqual(payload["current_selected_section_summary"], "Selected summary")

    def test_question_request_is_stateless_and_reads_response_text(self):
        class FakeResponses:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return type("Result", (), {"output_text": "La risposta è nel minuto 2."})()
        responses = FakeResponses()
        class FakeClient:
            def __init__(self, **kwargs):
                self.responses = responses
        with patch("openai.OpenAI", FakeClient):
            result = answer_question("test-key", ["[00:02] Person1: Earlier fact"],
                                     "What happened?", "A summary", [], [])
        self.assertIn("minuto 2", result)
        self.assertFalse(responses.kwargs["store"])
        self.assertIn("full_transcript_at_question_time", responses.kwargs["input"])


if __name__ == "__main__":
    unittest.main()
