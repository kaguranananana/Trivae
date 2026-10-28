"""Validate a private capability evidence packet or summarize a saved suite run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trivae.evaluation.capability_audit import audit_evidence, capability_report
from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationSuite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "report"))
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--cases-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True,
                        help="Canonical DB for verify; Evaluation DB for report")
    parser.add_argument("--packet", type=Path, help="Private evidence packet for verify")
    parser.add_argument("--freeze-manifest", type=Path, help="Frozen data manifest for verify")
    parser.add_argument("--output", type=Path, help="Optional JSON output; keep private if diagnoses contain private data")
    args = parser.parse_args()
    suite = EvaluationSuite.from_json(args.suite)
    cases = {}
    for path in args.cases_dir.glob("*.json"):
        case = EvaluationCaseBundle.from_json(path)
        cases[case.identity] = case
    if args.action == "verify":
        if args.packet is None or args.freeze_manifest is None:
            parser.error("verify requires --packet and --freeze-manifest")
        result = audit_evidence(suite=suite, cases=cases,
                                packet=json.loads(args.packet.read_text(encoding="utf-8")),
                                freeze=json.loads(args.freeze_manifest.read_text(encoding="utf-8")), database=args.database)
    else:
        result = capability_report(args.database, suite, cases)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
