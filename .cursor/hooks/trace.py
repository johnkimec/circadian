#!/usr/bin/env python3
"""Cursor hook entry. Always prints valid JSON so a read or prompt is not blocked."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {}
    name = event.get("hook_event_name")
    response = {"permission": "allow"} if name == "beforeReadFile" else {}
    try:
        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root))
        from circadian.trace import handle_hook

        response = handle_hook(event, root=root)
    except Exception:
        pass
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
