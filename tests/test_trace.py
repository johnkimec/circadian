import json
import unittest
from pathlib import Path

from circadian.session import load_session
from circadian.trace import handle_hook, session_from_transcript


class TraceTests(unittest.TestCase):
    def test_read_is_allowed_when_recording_fails(self):
        response = handle_hook(
            {"hook_event_name": "beforeReadFile", "file_path": "/tmp/a", "content": "secret"},
            root=Path("/nope"),
        )
        self.assertEqual(response["permission"], "allow")

    def test_file_read_command_failure_and_compaction(self):
        root = Path(self._tmp())
        conversation = "live-1"
        first = handle_hook(
            {
                "hook_event_name": "beforeReadFile",
                "conversation_id": conversation,
                "file_path": "/tmp/notes.md",
                "content": "SECRET_CONTENT_XYZ",
            },
            root=root,
        )
        self.assertEqual(first["permission"], "allow")
        handle_hook(
            {
                "hook_event_name": "postToolUse",
                "conversation_id": conversation,
                "tool_name": "Read",
                "tool_input": {"path": "/tmp/notes.md"},
                "tool_output": "{}",
            },
            root=root,
        )
        handle_hook(
            {
                "hook_event_name": "beforeReadFile",
                "conversation_id": conversation,
                "file_path": "/tmp/notes.md",
            },
            root=root,
        )
        handle_hook(
            {
                "hook_event_name": "postToolUse",
                "conversation_id": conversation,
                "tool_name": "Shell",
                "tool_input": {"command": "pytest -q"},
                "tool_output": json.dumps({"exitCode": 1, "stdout": ""}),
            },
            root=root,
        )
        handle_hook(
            {
                "hook_event_name": "postToolUse",
                "conversation_id": conversation,
                "tool_name": "Shell",
                "tool_input": {"command": "true"},
                "tool_output": "not json",
            },
            root=root,
        )
        session = load_session(root, conversation)
        kinds = [(event.kind, event.target, event.failed) for event in session.tool_events()]
        self.assertEqual(
            kinds,
            [
                ("file_read", "/tmp/notes.md", False),
                ("file_read", "/tmp/notes.md", False),
                ("command", "pytest -q", True),
                ("command", "true", None),
            ],
        )
        self.assertFalse(session.compaction_happened)
        blob = "".join(path.read_text() for path in (root / ".circadian").rglob("*") if path.is_file())
        self.assertNotIn("SECRET_CONTENT_XYZ", blob)

        handle_hook(
            {
                "hook_event_name": "preCompact",
                "conversation_id": conversation,
                "context_tokens": 999999,
                "context_usage_percent": 90,
                "trigger": "auto",
                "is_first_compaction": True,
            },
            root=root,
        )
        session = load_session(root, conversation)
        self.assertTrue(session.compaction_happened)
        blob = "".join(path.read_text() for path in (root / ".circadian").rglob("*") if path.is_file())
        self.assertNotIn("999999", blob)

    def test_live_reread_shift_writes_a_handoff_only_before_compaction(self):
        root = Path(self._tmp())
        conversation = "shift-1"
        paths = list("ABCDE") + ["A"] * 5
        for path in paths:
            handle_hook(
                {
                    "hook_event_name": "beforeReadFile",
                    "conversation_id": conversation,
                    "file_path": path,
                },
                root=root,
            )
        call_path = root / ".circadian" / "sessions" / conversation / "call.json"
        self.assertTrue(call_path.exists())
        call = json.loads(call_path.read_text())
        self.assertEqual(call["behavior"], "reread")
        self.assertEqual(call["earlier_count"], 0)
        self.assertEqual(call["later_count"], 5)
        handoffs = list((root / ".circadian" / "handoffs").glob("*.md"))
        self.assertEqual(len(handoffs), 1)
        self.assertIn("## Assessment", handoffs[0].read_text())

    def test_reread_fire_allows_the_read_and_notifies_on_the_next_tool(self):
        root = Path(self._tmp())
        conversation = "notice-reread"
        paths = list("ABCDE") + ["A"] * 5
        responses = []
        for path in paths:
            responses.append(
                handle_hook(
                    {
                        "hook_event_name": "beforeReadFile",
                        "conversation_id": conversation,
                        "file_path": path,
                    },
                    root=root,
                )
            )
        self.assertEqual(responses[-1], {"permission": "allow"})
        self.assertNotIn("additional_context", responses[-1])
        follow = handle_hook(
            {
                "hook_event_name": "postToolUse",
                "conversation_id": conversation,
                "tool_name": "Shell",
                "tool_input": {"command": "true"},
                "tool_output": json.dumps({"exitCode": 0}),
            },
            root=root,
        )
        notice = follow["additional_context"]
        handoff = next((root / ".circadian" / "handoffs").glob("*.md"))
        self.assertIn(handoff.relative_to(root).as_posix(), notice)
        self.assertIn("Earlier 0/5", notice)
        self.assertIn("Later 5/5", notice)
        self.assertIn("re-reads", notice)
        again = handle_hook(
            {
                "hook_event_name": "postToolUse",
                "conversation_id": conversation,
                "tool_name": "Shell",
                "tool_input": {"command": "true"},
                "tool_output": json.dumps({"exitCode": 0}),
            },
            root=root,
        )
        self.assertNotIn("additional_context", again)

    def test_command_failure_notice_is_on_the_firing_response(self):
        root = Path(self._tmp())
        conversation = "notice-fail"
        events = [
            ("edit", False),
            ("pytest -q", True),
            ("edit", False),
            ("pytest -q", True),
            ("edit", False),
            ("pytest -q", True),
        ]
        responses = []
        for target, failed in events:
            if target == "edit":
                event = {
                    "hook_event_name": "postToolUse",
                    "conversation_id": conversation,
                    "tool_name": "Write",
                    "tool_input": {"path": "ledger.py"},
                }
            else:
                event = {
                    "hook_event_name": "postToolUse" if not failed else "postToolUseFailure",
                    "conversation_id": conversation,
                    "tool_name": "Shell",
                    "tool_input": {"command": target},
                    "tool_output": json.dumps({"exitCode": 1 if failed else 0}),
                    "failure_type": "error",
                    "error_message": "failed",
                }
            responses.append(handle_hook(event, root=root))
        self.assertNotIn("additional_context", responses[1])
        self.assertNotIn("additional_context", responses[3])
        notice = responses[5]["additional_context"]
        handoff = next((root / ".circadian" / "handoffs").glob("*.md"))
        self.assertIn(handoff.relative_to(root).as_posix(), notice)
        self.assertIn("repeated failed commands", notice)
        self.assertIn("Earlier 1/3", notice)
        self.assertIn("Later 2/3", notice)
        stopped = handle_hook(
            {"hook_event_name": "stop", "conversation_id": conversation, "status": "completed", "loop_count": 0},
            root=root,
        )
        self.assertEqual(stopped["followup_message"], notice)
        again = handle_hook(
            {"hook_event_name": "stop", "conversation_id": conversation, "status": "completed", "loop_count": 1},
            root=root,
        )
        self.assertNotIn("followup_message", again)

    def test_reread_stop_posts_the_notice_without_another_tool(self):
        root = Path(self._tmp())
        conversation = "notice-reread-stop"
        for path in list("ABCDE") + ["A"] * 5:
            response = handle_hook(
                {
                    "hook_event_name": "beforeReadFile",
                    "conversation_id": conversation,
                    "file_path": path,
                },
                root=root,
            )
        self.assertEqual(response, {"permission": "allow"})
        stopped = handle_hook(
            {"hook_event_name": "stop", "conversation_id": conversation, "status": "completed", "loop_count": 0},
            root=root,
        )
        handoff = next((root / ".circadian" / "handoffs").glob("*.md"))
        self.assertIn(handoff.relative_to(root).as_posix(), stopped["followup_message"])
        again = handle_hook(
            {"hook_event_name": "stop", "conversation_id": conversation, "status": "completed", "loop_count": 1},
            root=root,
        )
        self.assertNotIn("followup_message", again)

    def test_stop_shows_a_notice_that_only_has_the_old_delivered_flag(self):
        root = Path(self._tmp())
        conversation = "notice-old"
        for _ in range(3):
            handle_hook(
                {
                    "hook_event_name": "postToolUseFailure",
                    "conversation_id": conversation,
                    "tool_name": "Shell",
                    "tool_input": {"command": "python3 scratch/demo/fail.py"},
                    "failure_type": "error",
                    "error_message": "failed",
                },
                root=root,
            )
        notice_path = root / ".circadian" / "sessions" / conversation / "notice.json"
        text = json.loads(notice_path.read_text())["text"]
        notice_path.write_text(json.dumps({"text": text, "delivered": True}) + "\n")
        stopped = handle_hook(
            {"hook_event_name": "stop", "conversation_id": conversation, "status": "completed", "loop_count": 0},
            root=root,
        )
        self.assertEqual(stopped["followup_message"], text)

    def test_stop_that_writes_the_handoff_posts_the_notice(self):
        root = Path(self._tmp())
        conversation = "notice-on-stop"
        directory = root / ".circadian" / "sessions" / conversation
        directory.mkdir(parents=True)
        (directory / "session.json").write_text(
            json.dumps({"conversation_id": conversation, "compaction_happened": False}) + "\n"
        )
        command = {"kind": "command", "target": "python3 scratch/demo/fail.py", "failed": True}
        (directory / "events.jsonl").write_text("".join(json.dumps(command) + "\n" for _ in range(3)))
        stopped = handle_hook(
            {"hook_event_name": "stop", "conversation_id": conversation, "status": "completed", "loop_count": 0},
            root=root,
        )
        self.assertIn("repeated failed commands", stopped["followup_message"])
        again = handle_hook(
            {"hook_event_name": "stop", "conversation_id": conversation, "status": "completed", "loop_count": 1},
            root=root,
        )
        self.assertNotIn("followup_message", again)

    def test_transcript_backfill_leaves_failure_unknown(self):
        path = Path(self._tmp()) / "session.jsonl"
        record = {
            "role": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Shell", "input": {"command": "pytest -q"}},
                    {"type": "tool_use", "name": "Read", "input": {"path": "docs/circadian.md"}},
                ]
            },
        }
        path.write_text(json.dumps(record) + "\n")
        session = session_from_transcript(path, "backfill")
        self.assertIsNone(session.compaction_happened)
        self.assertIsNone(session.tool_events()[0].failed)
        self.assertEqual(session.tool_events()[1].kind, "file_read")

    def _tmp(self) -> str:
        import tempfile

        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        return directory


if __name__ == "__main__":
    unittest.main()
