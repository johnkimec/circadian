"""Normalized session record. The detector reads this, not Cursor's transcript."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Event:
    kind: str
    target: str = ""
    failed: bool | None = None
    role: str | None = None
    text: str | None = None

    def to_json(self) -> dict:
        data: dict = {"kind": self.kind, "target": self.target, "failed": self.failed}
        if self.role is not None:
            data["role"] = self.role
        if self.text is not None:
            data["text"] = self.text
        return data

    @classmethod
    def from_json(cls, data: dict) -> Event:
        return cls(
            kind=data["kind"],
            target=data.get("target") or "",
            failed=data.get("failed"),
            role=data.get("role"),
            text=data.get("text"),
        )


@dataclass
class Session:
    conversation_id: str
    events: list[Event] = field(default_factory=list)
    # False: preCompact has not fired. True: it has. None: the source never said.
    compaction_happened: bool | None = None

    def tool_events(self) -> list[Event]:
        return [event for event in self.events if event.kind != "message"]

    def messages(self) -> list[Event]:
        return [event for event in self.events if event.kind == "message"]


def session_dir(root: Path, conversation_id: str) -> Path:
    _check_id(conversation_id)
    return root / ".circadian" / "sessions" / conversation_id


def _check_id(conversation_id: str) -> None:
    if (
        not conversation_id
        or conversation_id in {".", ".."}
        or "/" in conversation_id
        or "\\" in conversation_id
    ):
        raise ValueError(f"bad conversation id: {conversation_id!r}")


def load_session(root: Path, conversation_id: str) -> Session:
    directory = session_dir(root, conversation_id)
    compaction = None
    meta_path = directory / "session.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        compaction = meta.get("compaction_happened")
    events: list[Event] = []
    events_path = directory / "events.jsonl"
    if events_path.exists():
        for line in events_path.read_text().splitlines():
            if line.strip():
                events.append(Event.from_json(json.loads(line)))
    return Session(conversation_id, events, compaction)


def save_session(root: Path, session: Session) -> Path:
    directory = session_dir(root, session.conversation_id)
    directory.mkdir(parents=True, exist_ok=True)
    meta_path = directory / "session.json"
    events_path = directory / "events.jsonl"
    meta = {
        "conversation_id": session.conversation_id,
        "compaction_happened": session.compaction_happened,
    }
    _write_exclusive(meta_path, json.dumps(meta) + "\n")
    body = "".join(json.dumps(event.to_json()) + "\n" for event in session.events)
    _write_exclusive(events_path, body)
    return directory


def _write_exclusive(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o644)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)
