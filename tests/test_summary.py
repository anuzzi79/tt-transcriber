import json
import unittest
from unittest.mock import patch

from tt.summary import (analyze_topics, answer_question, line_at, merge_topics, model_options,
                        parse_topics, question_input, summarize, summary_input,
                        topic_input, topic_range)


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

    def test_gpt4o_request_has_no_reasoning_setting(self):
        self.assertNotIn("reasoning", model_options("gpt-4o"))
        self.assertEqual(model_options("gpt-6-luna")["reasoning"], {"effort": "low"})
        class FakeResponses:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return type("Result", (), {"output_text": "Riassunto"})()
        responses = FakeResponses()
        class FakeClient:
            def __init__(self, **kwargs):
                self.responses = responses
        with patch("openai.OpenAI", FakeClient):
            summarize("test-key", ["Hello"], 0, 0, model="gpt-4o")
        self.assertEqual(responses.kwargs["model"], "gpt-4o")
        self.assertNotIn("reasoning", responses.kwargs)

    def test_topic_revision_and_last_marker_snapshot(self):
        initial = parse_topics(json.dumps({"topics": [
            {"start_line": 1, "title": "Presentazione"},
            {"start_line": 3, "title": "Agenda"},
            {"start_line": 5, "title": "Discussione"},
        ]}), 0, 6)
        self.assertEqual(topic_range(initial, 4, 6), (4, 5))
        revised = parse_topics(json.dumps({"topics": [
            {"start_line": 1, "title": "Presentazione e agenda"},
            {"start_line": 5, "title": "Discussione"},
        ]}), 0, 8)
        merged = merge_topics(initial, revised, 0, 8)
        self.assertEqual([topic["start"] for topic in merged], [0, 4])
        self.assertEqual(topic_range(merged, 4, 8), (4, 7))
        self.assertEqual(topic_range(initial, 4, 6), (4, 5))

    def test_recent_topic_window_preserves_older_markers(self):
        previous = [{"start": 0, "title": "Introduzione"},
                    {"start": 2, "title": "Piano"},
                    {"start": 5, "title": "Budget"}]
        incoming = parse_topics(json.dumps({"topics": [
            {"start_line": 5, "title": "Piano"},
            {"start_line": 7, "title": "Budget aggiornato"},
        ]}), 4, 8)
        merged = merge_topics(previous, incoming, 4, 8)
        self.assertEqual([topic["start"] for topic in merged], [0, 2, 6])
        payload = json.loads(topic_input(["a", "b", "c"], previous, 1))
        self.assertEqual(payload["previous_topic_boundaries"][0]["start_line"], 1)
        self.assertEqual(payload["numbered_final_transcript"][0]["line"], 2)
        at_existing_boundary = parse_topics(json.dumps({"topics": [
            {"start_line": 3, "title": "Piano aggiornato"},
            {"start_line": 7, "title": "Budget"},
        ]}), 2, 8)
        merged = merge_topics(previous, at_existing_boundary, 2, 8)
        self.assertEqual([topic["start"] for topic in merged], [0, 2, 6])
        self.assertEqual(merged[1]["title"], "Piano aggiornato")

    def test_topic_analysis_uses_selected_model_and_validates_result(self):
        class FakeResponses:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return type("Result", (), {"output_text": json.dumps({"topics": [
                    {"start_line": 1, "title": "Introduzione"},
                    {"start_line": 3, "title": "Budget"},
                ]})})()
        responses = FakeResponses()
        class FakeClient:
            def __init__(self, **kwargs):
                self.responses = responses
        with patch("openai.OpenAI", FakeClient):
            topics = analyze_topics("test-key", ["first", "second", "third"], [], 0,
                                    model="gpt-4o")
        self.assertEqual(topics[-1]["start"], 2)
        self.assertNotIn("reasoning", responses.kwargs)
        with self.assertRaises(ValueError):
            parse_topics('{"topics":[{"start_line":99,"title":"Wrong"}]}', 0, 3)


if __name__ == "__main__":
    unittest.main()
