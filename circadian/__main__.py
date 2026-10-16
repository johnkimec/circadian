"""Command line. `hook` reads one Cursor hook payload from stdin."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from circadian.detector import detect
from circadian.handoff import write_handoff
from circadian.install import install
from circadian.session import load_session
from circadian.trace import handle_hook, session_from_transcript


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "hook"
    if command == "hook":
        raw = sys.stdin.read()
        try:
            event = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            event = {}
        json.dump(handle_hook(event), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if command == "detect":
        root = Path(args[1])
        conversation_id = args[2]
        call = detect(load_session(root, conversation_id))
        json.dump(None if call is None else call.to_json(), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if command == "handoff":
        root = Path(args[1])
        conversation_id = args[2]
        out = Path(args[3]) if len(args) > 3 else root / ".circadian" / "handoffs"
        session = load_session(root, conversation_id)
        call = detect(session)
        if call is None:
            print("no call", file=sys.stderr)
            return 1
        print(write_handoff(session, call, out))
        return 0
    if command == "install":
        target = Path(args[1]) if len(args) > 1 else Path.cwd()
        try:
            install(target)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        print(target.resolve())
        return 0
    if command == "backfill":
        transcript = Path(args[1])
        conversation_id = args[2]
        root = Path(args[3])
        from circadian.session import save_session

        save_session(root, session_from_transcript(transcript, conversation_id))
        return 0
    print("commands: hook, detect, handoff, backfill, install", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
