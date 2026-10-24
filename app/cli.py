"""Headless runner — useful for CI, for screenshots, and for a quick sanity check.

    python -m app.cli --case CASE-003
    python -m app.cli --question "Customer claims corrosion on NX-1042 from WO-1004"
    python -m app.cli --eval
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import run_case, run_eval
from .config import EVAL_CASES_PATH, SETTINGS
from .llm import get_provider


def load_cases() -> list[dict]:
    if not EVAL_CASES_PATH.exists():
        raise SystemExit("Evaluation cases missing. Run: python scripts/seed_data.py")
    return json.loads(Path(EVAL_CASES_PATH).read_text(encoding="utf-8"))


def print_result(payload: dict) -> None:
    print(f"\n=== {payload['case_id']} ===")
    print(f"question: {payload['question'][:150]}")
    for stage in payload["stages"]:
        mark = {"passed": "OK  ", "failed": "FAIL", "running": "...."}.get(stage["status"], "?")
        note = " | ".join(stage.get("notes", []))
        print(f"  [{mark}] {stage['stage']:<9} {note}")
    print(f"  decision   : {payload['decision'].get('decision')}  (rule {payload['decision'].get('rule_id')})")
    print(f"  confidence : {payload['confidence']}")
    print(f"  escalated  : {payload['escalated']}  {payload['escalation_reason']}")
    print(f"  tool calls : {len(payload['tool_calls'])}")
    print(f"  evidence   : {[e['id'] for e in payload['evidence']][:6]}")
    print(f"  audit      : {payload['audit_path']}")
    print(f"  elapsed    : {payload['elapsed_ms']} ms · tokens {payload['usage']}")
    print("\n  justification:")
    for line in _wrap(payload["justification"], 96):
        print(f"    {line}")


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="TriageOps headless runner")
    parser.add_argument("--case", help="eval case id, e.g. CASE-003")
    parser.add_argument("--question", help="free-text claim")
    parser.add_argument("--eval", action="store_true", help="run all evaluation cases")
    parser.add_argument("--provider", default=None, help="mock | openai | anthropic")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    args = parser.parse_args()

    provider = get_provider(args.provider)
    print(f"provider: {provider.name} · confidence threshold {SETTINGS.confidence_threshold}")

    if args.eval:
        report = run_eval(load_cases(), provider)
        print("\nmetrics:")
        for key, value in report["metrics"].items():
            print(f"  {key:>22}: {value}")
        print(f"\n{'case':<10}{'expected':<18}{'actual':<18}{'match':<7}{'conf':<7}{'tools':<7}{'ms'}")
        for row in report["rows"]:
            print(
                f"{row['case_id']:<10}{row['expected']:<18}{str(row['actual']):<18}"
                f"{str(row['match']):<7}{row['confidence']:<7}{row['tool_calls']:<7}{row['elapsed_ms']}"
            )
        return

    if args.case:
        cases = {c["case_id"]: c for c in load_cases()}
        if args.case not in cases:
            raise SystemExit(f"unknown case {args.case}; available: {sorted(cases)[:5]} ...")
        question = cases[args.case]["question"]
        case_id = args.case
    elif args.question:
        question = args.question
        case_id = "CASE-LIVE"
    else:
        parser.error("one of --case, --question or --eval is required")

    result = run_case(question, case_id=case_id, provider=provider)
    payload = result.as_dict()
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print_result(payload)


if __name__ == "__main__":
    main()
