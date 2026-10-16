import json
import subprocess
import sys
import unittest
from pathlib import Path

from eval.grade import aggregate, format_report, prompts

ROOT = Path(__file__).resolve().parents[1]


class GradeTests(unittest.TestCase):
    def test_swapped_order_agreement(self):
        judgments = [
            {
                "order": ["continued", "handoff"],
                "scores": {
                    "a": {"bounds": 2, "library": 5, "tests": 2, "scope": 4},
                    "b": {"bounds": 5, "library": 5, "tests": 5, "scope": 5},
                },
            },
            {
                "order": ["handoff", "continued"],
                "scores": {
                    "a": {"bounds": 5, "library": 5, "tests": 5, "scope": 5},
                    "b": {"bounds": 2, "library": 5, "tests": 2, "scope": 4},
                },
            },
        ]
        result = aggregate(judgments)
        self.assertEqual(result["continued"], 13)
        self.assertEqual(result["handoff"], 20)
        self.assertEqual(result["agreement"], 1)
        self.assertEqual(result["winner"], "handoff")
        text = format_report(result)
        self.assertIn("continued: 13", text)
        self.assertIn("handoff: 20", text)
        self.assertIn("agreement: 1", text)

    def test_script_prints_grades(self):
        import tempfile

        rubric = ROOT / "eval" / "rubric.json"
        with tempfile.TemporaryDirectory() as directory:
            judgments = Path(directory) / "judgments.json"
            judgments.write_text(
                json.dumps(
                    [
                        {
                            "order": ["continued", "handoff"],
                            "reply": '{"a": {"bounds": 1, "library": 5, "tests": 1, "scope": 5}, "b": {"bounds": 5, "library": 5, "tests": 5, "scope": 5}}',
                        },
                        {
                            "order": ["handoff", "continued"],
                            "reply": 'Note.\n{"a": {"bounds": 5, "library": 5, "tests": 5, "scope": 5}, "b": {"bounds": 1, "library": 5, "tests": 1, "scope": 5}}',
                        },
                    ]
                )
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "eval" / "grade.py"),
                    "--rubric",
                    str(rubric),
                    "--judgments",
                    str(judgments),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertIn("continued: 12", completed.stdout)
        self.assertIn("handoff: 20", completed.stdout)
        self.assertIn("agreement: 1", completed.stdout)

    def test_product_does_not_read_the_rubric(self):
        for path in (ROOT / "circadian").glob("*.py"):
            text = path.read_text()
            self.assertNotIn("rubric", text, path.name)
            self.assertNotIn("eval.grade", text, path.name)

    def test_prompts_swap_order_and_hide_nothing_from_the_grader_only(self):
        rubric = json.loads((ROOT / "eval" / "rubric.json").read_text())
        built = prompts(rubric, "ARM_CONTINUED", "ARM_HANDOFF")
        self.assertEqual(built[0]["order"], ["continued", "handoff"])
        self.assertEqual(built[1]["order"], ["handoff", "continued"])
        self.assertLess(built[0]["prompt"].index("ARM_CONTINUED"), built[0]["prompt"].index("ARM_HANDOFF"))
        self.assertLess(built[1]["prompt"].index("ARM_HANDOFF"), built[1]["prompt"].index("ARM_CONTINUED"))
        task = (ROOT / "eval" / "task.txt").read_text()
        for banned in ("rubric", "judge", "handoff", "fatigue"):
            self.assertNotIn(banned, task.lower())


if __name__ == "__main__":
    unittest.main()
