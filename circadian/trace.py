"""Turn Cursor hook payloads, or a transcript file, into a session record."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

from circadian.detector import detect
from circadian.handoff import write_handoff
from circadian.session import Event, Session, load_session, save_session


# postToolUse and postToolUseFailure accept additional_context. beforeReadFile
# shows user_message only when the read is denied, so a re-read fire stays allowed.
_CONTEXT_EVENTS = {"postToolUse", "postToolUseFailure"}

_BEHAVIOR_WORDS = {
    "reread": "re-reads",
    "repeated_failure": "repeated failed commands",
    "loop": "loops",
}


def handle_hook(event: dict, root: Path | None = None) -> dict:
    """Record one hook payload. A read is always allowed. Failures here do not block the tool."""
    name = event.get("hook_event_name")
    response = {"permission": "allow"} if name == "beforeReadFile" else {}
    try:
        notice = record_hook(event, root)
    except Exception:
        return response
    if notice and name in _CONTEXT_EVENTS:
        response["additional_context"] = notice
    return response


def record_hook(event: dict, root: Path | None = None) -> str | None:
    conversation_id = event.get("conversation_id")
    if not conversation_id:
        return None
    project = _project_root(event, root)
    name = event.get("hook_event_name")

    def mutate(session: Session) -> None:
        if name == "preCompact":
            session.compaction_happened = True
            return
        _ingest_user_messages(session, event.get("transcript_path"))
        new_event = event_from_hook(event)
        if new_event is not None and not _drops_duplicate_read(session, new_event, name):
            session.events.append(new_event)

    return _locked_update(project, conversation_id, mutate, name)


def event_from_hook(event: dict) -> Event | None:
    name = event.get("hook_event_name")
    if name == "beforeReadFile":
        return Event("file_read", event.get("file_path") or "", False)
    if name == "afterAgentResponse":
        return Event("message", "", None, role="assistant", text=event.get("text") or "")
    if name == "postToolUse":
        return _tool_event(event, failed_override=None)
    if name == "postToolUseFailure":
        return _tool_event(event, failed_override=True)
    return None


def session_from_transcript(path: Path, conversation_id: str) -> Session:
    """Backfill a transcript file. Compaction stays unknown: the file has no such field."""
    session = Session(conversation_id, [], None)
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        role = record.get("role")
        content = (record.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        if role == "user":
            text = _text_parts(content)
            if text:
                session.events.append(Event("message", "", None, role="user", text=text))
            continue
        if role != "assistant":
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "tool_use":
                continue
            tool_event = _event_from_tool_use(part.get("name") or "", part.get("input") or {})
            if tool_event is None:
                continue
            # Each tool_use in the file is its own action. The file has no paired
            # before/after record the way the live hooks do.
            session.events.append(tool_event)
    return session


def _event_from_tool_use(tool_name: str, tool_input: dict) -> Event | None:
    data = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "Read":
        return Event("file_read", data.get("path") or data.get("file_path") or "", None)
    if tool_name == "Shell":
        # The transcript stores the command and not its result.
        return Event("command", data.get("command") or "", None)
    if not tool_name:
        return None
    return Event("action", action_target(tool_name, data), None)


def _tool_event(event: dict, failed_override: bool | None) -> Event | None:
    tool_name = event.get("tool_name") or ""
    data = _parse_input(event.get("tool_input"))
    if tool_name == "Read":
        failed = True if failed_override else False
        return Event("file_read", data.get("path") or data.get("file_path") or "", failed)
    if tool_name == "Shell":
        failed = failed_override if failed_override is not None else exit_failed(event.get("tool_output"))
        return Event("command", data.get("command") or "", failed)
    if not tool_name:
        return None
    failed = True if failed_override else False
    return Event("action", action_target(tool_name, data), failed)


def action_target(tool_name: str, tool_input: dict) -> str:
    for key in ("path", "file_path", "command", "pattern", "glob_pattern"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return f"{tool_name}:{value}"
    return tool_name


def exit_failed(tool_output) -> bool | None:
    """True when the tool result names a non-zero exit. None when it does not say."""
    data = tool_output
    if isinstance(tool_output, str):
        if not tool_output.strip():
            return None
        try:
            data = json.loads(tool_output)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    for key in ("exitCode", "exit_code"):
        code = data.get(key)
        if isinstance(code, int):
            return code != 0
    return None


def _drops_duplicate_read(session: Session, new_event: Event, hook_name: str | None) -> bool:
    """postToolUse Read repeats the beforeReadFile event for the same read."""
    if hook_name != "postToolUse" or new_event.kind != "file_read":
        return False
    previous = _previous_tool(session)
    return _same_read(previous, new_event)


def _same_read(previous: Event | None, new_event: Event) -> bool:
    return (
        previous is not None
        and previous.kind == "file_read"
        and new_event.kind == "file_read"
        and previous.target == new_event.target
    )


def _previous_tool(session: Session) -> Event | None:
    for event in reversed(session.events):
        if event.kind != "message":
            return event
    return None


def _ingest_user_messages(session: Session, transcript_path) -> None:
    if not transcript_path:
        return
    path = Path(transcript_path)
    if not path.is_file():
        return
    texts = _user_texts(path)
    existing = [message.text for message in session.messages() if message.role == "user"]
    if texts[: len(existing)] == existing:
        fresh = texts[len(existing) :]
    else:
        fresh = [text for text in texts if text not in existing]
    for text in fresh:
        session.events.append(Event("message", "", None, role="user", text=text))


def _user_texts(path: Path) -> list[str]:
    texts: list[str] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("role") != "user":
            continue
        content = (record.get("message") or {}).get("content")
        if isinstance(content, list):
            text = _text_parts(content)
            if text:
                texts.append(text)
        elif isinstance(content, str) and content:
            texts.append(content)
    return texts


def _text_parts(content: list) -> str:
    chunks = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            chunks.append(part["text"])
    return "\n".join(chunks)


def _parse_input(tool_input) -> dict:
    if isinstance(tool_input, dict):
        return tool_input
    if isinstance(tool_input, str):
        try:
            data = json.loads(tool_input)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            return data
    return {}


def _project_root(event: dict, root: Path | None) -> Path:
    if root is not None:
        return root
    roots = event.get("workspace_roots") or []
    if roots:
        return Path(roots[0])
    return Path.cwd()


def _locked_update(root: Path, conversation_id: str, mutate, hook_name: str | None) -> str | None:
    directory = root / ".circadian" / "sessions" / conversation_id
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / ".lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        session = _load_or_new(root, conversation_id, compaction_happened=False)
        mutate(session)
        save_session(root, session)
        created = _maybe_handoff(root, session)
        return _claim_notice(root, session, created, hook_name)


def _load_or_new(root: Path, conversation_id: str, compaction_happened: bool | None) -> Session:
    directory = root / ".circadian" / "sessions" / conversation_id
    if (directory / "session.json").exists():
        return load_session(root, conversation_id)
    return Session(conversation_id, [], compaction_happened)


def _maybe_handoff(root: Path, session: Session) -> Path | None:
    directory = root / ".circadian" / "sessions" / session.conversation_id
    if (directory / "call.json").exists():
        return None
    call = detect(session)
    if call is None:
        return None
    (directory / "call.json").write_text(json.dumps(call.to_json()) + "\n")
    return write_handoff(session, call, root / ".circadian" / "handoffs")


def _claim_notice(root: Path, session: Session, created: Path | None, hook_name: str | None) -> str | None:
    directory = root / ".circadian" / "sessions" / session.conversation_id
    notice_path = directory / "notice.json"
    if created is not None:
        call = json.loads((directory / "call.json").read_text())
        text = _notice_text(root, created, call)
        delivered = hook_name in _CONTEXT_EVENTS
        notice_path.write_text(json.dumps({"text": text, "delivered": delivered}) + "\n")
        return text if delivered else None
    if not notice_path.is_file():
        return None
    payload = json.loads(notice_path.read_text())
    if payload.get("delivered") or hook_name not in _CONTEXT_EVENTS:
        return None
    payload["delivered"] = True
    notice_path.write_text(json.dumps(payload) + "\n")
    return payload["text"]


def _notice_text(root: Path, handoff: Path, call: dict) -> str:
    relative = handoff.relative_to(root).as_posix()
    behavior = _BEHAVIOR_WORDS.get(call["behavior"], call["behavior"])
    return (
        "Circadian reset. "
        f"{behavior}. "
        f"Earlier {call['earlier_count']}/{call['earlier_total']}. "
        f"Later {call['later_count']}/{call['later_total']}. "
        f"Open a new Cursor session and point it at {relative}."
    )
