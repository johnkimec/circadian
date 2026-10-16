"""Copy Circadian's hooks into another project's `.cursor/` directory."""

from __future__ import annotations

import json
import stat
from pathlib import Path

HOOK_COMMAND = ".cursor/hooks/trace.py"

HOOKS = (
    ("beforeReadFile", {"command": HOOK_COMMAND, "timeout": 10}),
    ("postToolUse", {"command": HOOK_COMMAND, "timeout": 10}),
    ("postToolUseFailure", {"command": HOOK_COMMAND, "timeout": 10}),
    ("preCompact", {"command": HOOK_COMMAND, "timeout": 10}),
    ("afterAgentResponse", {"command": HOOK_COMMAND, "timeout": 10}),
    ("stop", {"command": HOOK_COMMAND, "timeout": 10, "loop_limit": 1}),
)

HOOK_SCRIPT = '''#!/usr/bin/env python3
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
        here = Path(__file__).resolve()
        project = here.parents[2]
        sys.path.insert(0, str(here.parents[1]))
        from circadian.trace import handle_hook

        response = handle_hook(event, root=project)
    except Exception:
        pass
    json.dump(response, sys.stdout)
    sys.stdout.write("\\n")


if __name__ == "__main__":
    main()
'''


def install(target: Path) -> None:
    """Write the hook script, the package copy, and the hook entries into `target`."""
    root = target.resolve()
    cursor = root / ".cursor"
    _copy_package(cursor / "circadian")
    script = cursor / "hooks" / "trace.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(HOOK_SCRIPT)
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    _write_hooks(cursor / "hooks.json")
    _ignore_runtime(root / ".gitignore")


def _copy_package(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    for path in source.glob("*.py"):
        (destination / path.name).write_text(path.read_text())


def _write_hooks(path: Path) -> None:
    if path.is_file():
        try:
            config = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} is not valid JSON") from error
        if not isinstance(config, dict):
            raise ValueError(f"{path} is not a JSON object")
    else:
        config = {}
    config["version"] = config.get("version", 1)
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    for event, entry in HOOKS:
        current = hooks.get(event)
        if not isinstance(current, list):
            current = []
        for index, item in enumerate(current):
            if isinstance(item, dict) and item.get("command") == HOOK_COMMAND:
                current[index] = entry
                break
        else:
            current.append(entry)
        hooks[event] = current
    config["hooks"] = hooks
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")


def _ignore_runtime(path: Path) -> None:
    line = ".circadian/"
    existing = path.read_text() if path.is_file() else ""
    if any(item.strip() == line or item.strip() == ".circadian" for item in existing.splitlines()):
        return
    suffix = "" if existing.endswith("\n") or existing == "" else "\n"
    path.write_text(existing + suffix + line + "\n")
