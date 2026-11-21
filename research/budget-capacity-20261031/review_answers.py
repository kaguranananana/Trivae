"""Review only delivered controlled answers with the existing v2.1 Judge.

Uses the same cumulative OAuth request allowance and raw frozen source hydration.
Failed Runtime/Finalizer slots are recorded as excluded, never assigned fake scores.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research/agent-quality-20261029"))
from model_request_meter import install_meter  # noqa: E402

from trivae.config.dotenv import load_environment_file  # noqa: E402
from trivae.config.settings import load_settings  # noqa: E402
from trivae.evaluation.capability_judge import judge_prompt_for, parse_review  # noqa: E402
from trivae.evaluation.contracts import EvaluationCaseBundle  # noqa: E402
from trivae.query.runtime.model_completion import complete_json, completion_record  # noqa: E402

BUNDLE = ROOT / "data/evaluation/eval-v1-20261028"
FROZEN = ROOT / "data/evaluation/frozen-20261028-validated/trivae.sqlite3"


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=Path, nargs="+", default=[])
    parser.add_argument("--prepared-inputs", type=Path, nargs="+", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location(
        "projection_source_hydration", ROOT / "data/evaluation/prompt-ab-eval-v1-20261029/judge-from-run-projections.py",
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    truth = json.loads((BUNDLE / "ground-truth-v1.json").read_text())["cases"]
    packets = json.loads((BUNDLE / "evidence.json").read_text())["cases"]
    con = sqlite3.connect(f"file:{FROZEN}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    pending, excluded = [], []
    for answer_dir in args.answers:
        for file in sorted(answer_dir.glob("*/result.json")):
            result = json.loads(file.read_text())
            if result["termination"] != "completed" or result["artifact"] is None:
                excluded.append({"source": str(file), "runtime": result["runtime_error"], "finalizer": result["finalization_error"]})
                continue
            case = EvaluationCaseBundle.from_json(BUNDLE / "cases" / f"{file.parent.name}.json")
            artifact = result["artifact"]
            groups = [{"evidence_id": item["evidence_id"], "message_ids": [s["reference"]["internal_message_id"]
                       for s in item["sources"] if s["reference"]["type"] == "message"]}
                      for item in artifact["evidence_items"]]
            cited, limits = helper._cited_messages(con, case, {"sources": groups})
            payload = {"case_id": case.case_id, "case_version": case.version, "as_of": case.time_context,
                       "query": case.query, "ground_truth": next(t for t in truth if t["case_id"] == case.case_id),
                       "reference_evidence": next(p for p in packets if p["case_id"] == case.case_id)["evidence"],
                       "answer_artifact": artifact, "answer_cited_messages": cited,
                       "limitations": "Controlled historical retrieval prefix; live production synthesis. "
                                       "Full host-validated artifact and frozen cited sources; " + "; ".join(limits)}
            label = f"{answer_dir.name}-{case.case_id}"
            out = args.output / label
            out.mkdir()
            (out / "input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            pending.append((label, out, payload))
    con.close()
    for source in args.prepared_inputs:
        label = source.parent.name
        out = args.output / label
        out.mkdir()
        (out / "input.json").write_text(source.read_text())
        pending.append((label, out, json.loads(source.read_text())))
    (args.output / "excluded.json").write_text(json.dumps(excluded, ensure_ascii=False, indent=2))
    load_environment_file(None)
    settings = load_settings(model_id="gpt-plus", role="judge")
    assert settings.provider == "chatgpt-plan"
    install_meter("judge", "budget-C-v2.1", args.output)
    for label, out, payload in pending:
        try:
            response = await complete_json(settings, system_prompt=judge_prompt_for("eval-rubric-v2.1"),
                                           user_prompt=json.dumps(payload, ensure_ascii=False), session_id=label)
        except Exception as exc:
            (out / "error.json").write_text(json.dumps({"type": type(exc).__name__, "message": str(exc)}))
            raise
        (out / "response.json").write_text(json.dumps(completion_record(response), ensure_ascii=False, indent=2))
        review = parse_review(response.content, run_id=label, judge_identity=f"{settings.provider}:{response.model}",
                              rubric_version="eval-rubric-v2.1")
        (out / "review.json").write_text(json.dumps(review.to_dict(), ensure_ascii=False, indent=2))
        print(label, review.quality_axes, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
