import unittest
from pathlib import Path

from circadian.detector import detect
from circadian.handoff import render, write_handoff
from circadian.session import Event, Session


def firing_session() -> Session:
    events = [
        Event(
            "message",
            "",
            None,
            role="user",
            text="Finish the parser. Do not read /tmp/SECRET.md again.",
        )
    ]
    events += [Event("file_read", path, False) for path in ("/tmp/SECRET.md", "B", "C", "D", "E")]
    events += [Event("file_read", "/tmp/SECRET.md", False) for _ in range(5)]
    return Session("handoff-demo", events, False)


class HandoffTests(unittest.TestCase):
    def test_schema_rates_quotes_and_unique_names(self):
        session = firing_session()
        call = detect(session)
        self.assertIsNotNone(call)
        text = render(session, call, "fixed-id")
        for heading in ("## Situation", "## Background", "## Assessment", "## Recommendation"):
            self.assertIn(heading, text)
        self.assertIn("handoff_version: 1", text)
        self.assertIn("re-reads", text)
        self.assertIn(f"{call.earlier_count}/{call.earlier_total}", text)
        self.assertIn(f"{call.later_count}/{call.later_total}", text)
        self.assertIn("> Finish the parser. Do not read /tmp/SECRET.md again.", text)
        self.assertIn("> file_read /tmp/SECRET.md", text)
        source = Path(__file__).resolve().parents[1] / "circadian" / "handoff.py"

        self.assertNotIn("subprocess", source.read_text())
        root = Path(self._tmp())
        first = write_handoff(session, call, root)
        second = write_handoff(session, call, root)
        self.assertNotEqual(first.name, second.name)
        self.assertTrue(first.name.startswith("handoff-demo-"))
        self.assertIn("handoff_version: 1", first.read_text())

    def _tmp(self) -> str:
        import tempfile

        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        return directory


if __name__ == "__main__":
    unittest.main()
