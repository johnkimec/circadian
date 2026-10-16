"""Detector labels were fixed in tests/fixtures/cases.json before this assertion."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from circadian.detector import detect, labels_for
from circadian.session import Event, Session

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests" / "fixtures" / "cases.json").read_text())


def session_from_case(name: str) -> Session:
    case = CASES[name]
    events = [Event.from_json(item) for item in case["events"]]
    return Session("case-" + name, events, case["compaction_happened"])


class DetectorTests(unittest.TestCase):
    def test_frozen_cases(self):
        for name, case in CASES.items():
            with self.subTest(name=name):
                call = detect(session_from_case(name))
                expect = case["expect"]
                if not expect["fire"]:
                    self.assertIsNone(call)
                    continue
                self.assertIsNotNone(call)
                self.assertEqual(call.behavior, expect["behavior"])
                self.assertEqual(call.moment_index, expect["moment_index"])
                self.assertEqual(call.earlier_count, expect["earlier_count"])
                self.assertEqual(call.earlier_total, expect["earlier_total"])
                self.assertEqual(call.later_count, expect["later_count"])
                self.assertEqual(call.later_total, expect["later_total"])
                if "min_z" in expect:
                    self.assertIsNotNone(call.z)
                    self.assertGreater(call.z, expect["min_z"])

    def test_one_event_does_not_increment_two_counts(self):
        events = [Event("file_read", "A", False) for _ in range(4)]
        labels = labels_for(events)
        self.assertEqual(labels, [None, "reread", "reread", "reread"])
        self.assertEqual(sum(label == "loop" for label in labels), 0)
        self.assertLessEqual(
            sum(label is not None for label in labels),
            len(events),
        )

    def test_messages_are_outside_the_counted_sequence(self):
        session = session_from_case("drift_only")
        self.assertEqual(len(labels_for(session.events)), len(session.tool_events()))
        self.assertEqual(len(session.tool_events()), 10)

    def test_real_transcripts_do_not_fire(self):
        from circadian.trace import session_from_transcript

        fixture_dir = ROOT / "tests" / "fixtures" / "real"
        labels = list(fixture_dir.glob("*.label.json"))
        self.assertGreaterEqual(len(labels), 2)
        for label_path in labels:
            transcript = label_path.with_suffix("").with_suffix(".jsonl")
            # name.label.json -> with_suffix twice removes .json then .label
            transcript = Path(str(label_path).replace(".label.json", ".jsonl"))
            label = json.loads(label_path.read_text())
            session = session_from_transcript(transcript, label["conversation_id"])
            self.assertIsNone(session.compaction_happened, label_path.name)
            self.assertIsNone(detect(session), label["reason"])
            self.assertFalse(label["expect_fire"])


if __name__ == "__main__":
    unittest.main()
