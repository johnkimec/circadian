"""Write a versioned handoff. It does not open a Cursor session. Decision D4."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from circadian.detector import Call
from circadian.session import Event, Session

# I-PASS (Starmer et al., NEJM 2014) mapped onto the four sections D4 named.
# Illness severity and the current task → Situation.
# Patient summary, including constraints and divergence → Background.
# Situation awareness → Assessment.
# Action list, contingency, and receiver synthesis → Recommendation.

_BEHAVIOR_WORDS = {
    "reread": "re-reads",
    "repeated_failure": "repeated failed commands",
    "loop": "loops",
}

_PROHIBITION = re.compile(r"(?i)\b(?:do not|don't|never|must not)\b.{0,180}")
_WORD = re.compile(r"[A-Za-z0-9_./-]+")


def write_handoff(session: Session, call: Call, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    handoff_id = str(uuid.uuid4())
    path = directory / f"{session.conversation_id}-{call.moment_index}-{handoff_id}.md"
    path.write_text(render(session, call, handoff_id))
    return path


def render(session: Session, call: Call, handoff_id: str) -> str:
    behavior = _BEHAVIOR_WORDS[call.behavior]
    users = [message.text or "" for message in session.messages() if message.role == "user" and message.text]
    task = _one_line(users[-1]) if users else "The record has no user message naming the task."
    pairs = _divergences(users, session.tool_events())
    constraint = users[0] if users else ""
    repeat_target = _repeat_target(session.tool_events(), call)
    lines = [
        "---",
        "handoff_version: 1",
        f"id: {handoff_id}",
        f"session: {session.conversation_id}",
        f"moment_index: {call.moment_index}",
        "---",
        "",
        "## Situation",
        "",
        "Illness severity: deteriorating. A counted behavior shifted before compaction.",
        "",
        f"Task now: {task}",
        "",
        "## Background",
        "",
        "Constraints quoted from the session:",
        "",
    ]
    if constraint:
        lines.extend(_quote(constraint))
    else:
        lines.append("> (no constraint text was in the record)")
    lines.append("")
    if pairs:
        lines.append("Later actions that diverge from a stated prohibition:")
        lines.append("")
        for prohibition, action in pairs:
            lines.extend(_quote(prohibition))
            lines.extend(_quote(action))
            lines.append("")
    else:
        lines.append("No later action matched a stated prohibition.")
        lines.append("")
    lines.extend(
        [
            "## Assessment",
            "",
            f"Behavior that jumped: {behavior}.",
            "",
            (
                f"Earlier rate: {call.earlier_count}/{call.earlier_total} "
                f"({call.earlier_rate:.4f})."
            ),
            (
                f"Later rate: {call.later_count}/{call.later_total} "
                f"({call.later_rate:.4f})."
            ),
            "",
            "Compaction had not happened at this moment.",
            "",
            "## Recommendation",
            "",
            f"Action list: {task}",
            "",
            f"Do not repeat: {repeat_target}.",
            "",
            "Synthesis: restate the task in one line before the next tool call.",
            "",
        ]
    )
    return "\n".join(lines)


def _divergences(user_texts: list[str], tool_events: list[Event]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for text in user_texts:
        for match in _PROHIBITION.finditer(text):
            prohibition = " ".join(match.group(0).split())
            words = [word.lower() for word in _WORD.findall(match.group(0)) if len(word) > 2]
            words = [word for word in words if word not in {"not", "do", "don't", "never", "must"}]
            if not words:
                continue
            for event in tool_events:
                if any(word in event.target.lower() for word in words):
                    action = f"{event.kind} {event.target}"
                    key = (prohibition, action)
                    if key not in seen:
                        seen.add(key)
                        pairs.append(key)
                    break
    return pairs


def _repeat_target(tool_events: list[Event], call: Call) -> str:
    if call.moment_index < len(tool_events):
        event = tool_events[call.moment_index]
        if event.target:
            return event.target
    return call.behavior


def _quote(text: str) -> list[str]:
    body = text.strip() or "(empty)"
    return ["> " + line for line in body.splitlines()]


def _one_line(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) > 240:
        return flat[:237] + "..."
    return flat
