"""Grade the two evaluation arms. This is not part of the product. Decision D7.

The protocol is Zheng et al., 2023 (MT-Bench): the same rubric, the two arms
shown in swapped order, agreement reported across those presentations.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def prompts(rubric: dict, continued: str, handoff: str) -> list[dict]:
    return [
        {"order": ["continued", "handoff"], "prompt": _prompt(rubric, continued, handoff)},
        {"order": ["handoff", "continued"], "prompt": _prompt(rubric, handoff, continued)},
    ]


def aggregate(judgments: list[dict]) -> dict:
    totals = {"continued": [], "handoff": []}
    winners = []
    for judgment in judgments:
        order = judgment["order"]
        score_a = sum(judgment["scores"]["a"].values())
        score_b = sum(judgment["scores"]["b"].values())
        totals[order[0]].append(score_a)
        totals[order[1]].append(score_b)
        if score_a == score_b:
            winners.append("tie")
        else:
            winners.append(order[0] if score_a > score_b else order[1])
    means = {arm: sum(values) / len(values) for arm, values in totals.items()}
    if means["continued"] == means["handoff"]:
        overall = "tie"
    else:
        overall = "continued" if means["continued"] > means["handoff"] else "handoff"
    agreement = sum(winner == overall for winner in winners) / len(winners)
    return {
        "continued": means["continued"],
        "handoff": means["handoff"],
        "agreement": agreement,
        "winner": overall,
    }


def format_report(result: dict) -> str:
    return (
        f"continued: {result['continued']}\n"
        f"handoff: {result['handoff']}\n"
        f"agreement: {result['agreement']}\n"
    )


def scores_from_reply(reply: str, criteria: list[str]) -> dict:
    data = _extract_json(reply)
    scores = {}
    for side in ("a", "b"):
        raw = data[side]
        scores[side] = {criterion: int(raw[criterion]) for criterion in criteria}
    return scores


def _prompt(rubric: dict, output_a: str, output_b: str) -> str:
    lines = [
        "Score each output on every criterion from 1 to 5.",
        "Do not prefer the output shown first.",
        "Reply with JSON only, shaped as",
        '{"a": {"<id>": <int>}, "b": {"<id>": <int>}}.',
        "",
        "Criteria:",
    ]
    for item in rubric["criteria"]:
        lines.append(f"- {item['id']}: {item['text']}")
    lines.extend(["", "Output A:", output_a, "", "Output B:", output_b])
    return "\n".join(lines)


def _extract_json(reply: str) -> dict:
    start = reply.find("{")
    if start < 0:
        raise ValueError("judge reply has no JSON object")
    data, _ = json.JSONDecoder().raw_decode(reply[start:])
    if not isinstance(data, dict):
        raise ValueError("judge reply JSON is not an object")
    return data


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    rubric_path = Path(args[args.index("--rubric") + 1])
    judgments_path = Path(args[args.index("--judgments") + 1])
    rubric = json.loads(rubric_path.read_text())
    criteria = [item["id"] for item in rubric["criteria"]]
    raw = json.loads(judgments_path.read_text())
    judgments = []
    for item in raw:
        scores = item["scores"] if "scores" in item else scores_from_reply(item["reply"], criteria)
        judgments.append({"order": item["order"], "scores": scores})
    sys.stdout.write(format_report(aggregate(judgments)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
