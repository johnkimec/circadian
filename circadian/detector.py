"""Name the moment a session should be reset. Decisions D12 and D13."""

from __future__ import annotations

import math
from dataclasses import dataclass

from circadian.rule import (
    COMMAND_FAILURES_TO_FIRE,
    LOOP_LENGTHS,
    MIN_EVENTS,
    RATE_BEHAVIORS,
    Z_LIMIT,
)
from circadian.session import Event, Session


@dataclass(frozen=True)
class Call:
    moment_index: int
    behavior: str
    earlier_count: int
    earlier_total: int
    later_count: int
    later_total: int
    z: float | None

    @property
    def earlier_rate(self) -> float:
        return self.earlier_count / self.earlier_total

    @property
    def later_rate(self) -> float:
        return self.later_count / self.later_total

    def to_json(self) -> dict:
        return {
            "moment_index": self.moment_index,
            "behavior": self.behavior,
            "earlier_count": self.earlier_count,
            "earlier_total": self.earlier_total,
            "later_count": self.later_count,
            "later_total": self.later_total,
            "earlier_rate": self.earlier_rate,
            "later_rate": self.later_rate,
            "z": self.z,
        }


def two_proportion_z(k0: int, n0: int, k1: int, n1: int) -> float | None:
    """Western Electric rule 1 in two-proportion form. None means do not fire."""
    if n0 <= 0 or n1 <= 0:
        return None
    pool = (k0 + k1) / (n0 + n1)
    if pool <= 0.0 or pool >= 1.0:
        return None
    standard_error = math.sqrt(pool * (1.0 - pool) * (1.0 / n0 + 1.0 / n1))
    if standard_error == 0.0:
        return None
    return ((k1 / n1) - (k0 / n0)) / standard_error


def labels_for(events: list[Event]) -> list[str | None]:
    """Label tool events only. One event gets at most one label."""
    tool_events = [event for event in events if event.kind != "message"]
    labels: list[str | None] = []
    failed_commands: set[str] = set()
    read_paths: set[str] = set()
    keys: list[tuple[str, str]] = []
    for event in tool_events:
        key = (event.kind, event.target)
        label: str | None = None
        if event.kind == "command" and event.failed is True:
            if event.target in failed_commands:
                label = "repeated_failure"
            else:
                failed_commands.add(event.target)
        elif event.kind == "file_read":
            if event.target in read_paths:
                label = "reread"
            else:
                read_paths.add(event.target)
        keys.append(key)
        if label is None and _completes_loop(keys):
            label = "loop"
        labels.append(label)
    return labels


def _completes_loop(keys: list[tuple[str, str]]) -> bool:
    index = len(keys) - 1
    for length in LOOP_LENGTHS:
        if index + 1 < 2 * length:
            continue
        previous = keys[index - 2 * length + 1 : index - length + 1]
        current = keys[index - length + 1 : index + 1]
        if previous == current and len(previous) == length:
            return True
    return False


def detect(session: Session) -> Call | None:
    """Fire on the third failure of one command, or a z > 3 re-read or loop shift.

    Compaction must be known and still false. A missing flag does not fire.
    """
    if session.compaction_happened is not False:
        return None
    tool_events = session.tool_events()
    for count in range(1, len(tool_events) + 1):
        prefix = tool_events[:count]
        failure = _command_failure_call(prefix)
        if failure is not None:
            return failure
        if count < MIN_EVENTS:
            continue
        rate_call = _rate_call(prefix)
        if rate_call is not None:
            return rate_call
    return None


def _command_failure_call(events: list[Event]) -> Call | None:
    last = events[-1]
    if last.kind != "command" or last.failed is not True:
        return None
    failures = [
        event
        for event in events
        if event.kind == "command" and event.failed is True and event.target == last.target
    ]
    if len(failures) != COMMAND_FAILURES_TO_FIRE:
        return None
    earlier_total = len(events) // 2
    later_total = len(events) - earlier_total
    earlier = events[:earlier_total]
    later = events[earlier_total:]
    earlier_count = _failure_count(earlier, last.target)
    later_count = _failure_count(later, last.target)
    return Call(
        moment_index=len(events) - 1,
        behavior="repeated_failure",
        earlier_count=earlier_count,
        earlier_total=earlier_total,
        later_count=later_count,
        later_total=later_total,
        z=two_proportion_z(earlier_count, earlier_total, later_count, later_total),
    )


def _failure_count(events: list[Event], command: str) -> int:
    return sum(
        1
        for event in events
        if event.kind == "command" and event.failed is True and event.target == command
    )


def _rate_call(events: list[Event]) -> Call | None:
    labels = labels_for(events)
    earlier_total = len(events) // 2
    later_total = len(events) - earlier_total
    best: Call | None = None
    for behavior in RATE_BEHAVIORS:
        earlier_count = sum(label == behavior for label in labels[:earlier_total])
        later_count = sum(label == behavior for label in labels[earlier_total:])
        score = two_proportion_z(earlier_count, earlier_total, later_count, later_total)
        if score is None or score <= Z_LIMIT:
            continue
        candidate = Call(
            moment_index=len(events) - 1,
            behavior=behavior,
            earlier_count=earlier_count,
            earlier_total=earlier_total,
            later_count=later_count,
            later_total=later_total,
            z=score,
        )
        if best is None or (candidate.z or 0) > (best.z or 0):
            best = candidate
    return best
