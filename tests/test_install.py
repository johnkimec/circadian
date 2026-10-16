import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from circadian.install import install


class InstallTests(unittest.TestCase):
    def test_install_copies_hooks_and_keeps_existing_ones(self):
        root = Path(self._tmp())
        cursor = root / ".cursor"
        cursor.mkdir()
        (cursor / "hooks.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "hooks": {"beforeShellExecution": [{"command": "hooks/other.sh"}]},
                }
            )
        )
        (root / ".gitignore").write_text("build/\n")
        install(root)
        install(root)

        config = json.loads((cursor / "hooks.json").read_text())
        self.assertEqual(config["hooks"]["beforeShellExecution"], [{"command": "hooks/other.sh"}])
        stop = config["hooks"]["stop"]
        self.assertEqual(stop, [{"command": ".cursor/hooks/trace.py", "timeout": 10, "loop_limit": 1}])
        self.assertEqual(len(config["hooks"]["postToolUseFailure"]), 1)
        self.assertTrue((cursor / "circadian" / "trace.py").is_file())
        self.assertIn(".circadian/\n", (root / ".gitignore").read_text())
        self.assertEqual((root / ".gitignore").read_text().count(".circadian/"), 1)

        completed = subprocess.run(
            [sys.executable, str(cursor / "hooks" / "trace.py")],
            input=json.dumps(
                {"hook_event_name": "beforeReadFile", "conversation_id": "installed", "file_path": "a.py"}
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"permission": "allow"})

    def test_install_refuses_a_broken_hooks_file(self):
        root = Path(self._tmp())
        cursor = root / ".cursor"
        cursor.mkdir()
        (cursor / "hooks.json").write_text("{")
        with self.assertRaises(ValueError):
            install(root)

    def _tmp(self) -> str:
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        return directory
