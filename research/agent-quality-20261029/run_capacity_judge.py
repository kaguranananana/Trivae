"""Review complete saved answers using the existing v2.1 projection preparation."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sqlite3
from pathlib import Path

from model_request_meter import install_meter

from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.evaluation.capability_judge import judge_prompt_for, parse_review
from trivae.evaluation.contracts import DatasetSnapshot
from trivae.evaluation.store import SQLiteEvaluationStore
from trivae.query.runtime.model_completion import complete_json, completion_record

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "data/evaluation/eval-v1-20261028"
FROZEN_DB = ROOT / "data/evaluation/frozen-20261028-validated/trivae.sqlite3"


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "saved_projection_judge", ROOT / "data/evaluation/prompt-ab-eval-v1-20261029/judge-from-run-projections.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((args.record_dir / "experiment.json").read_text())
    snapshot = DatasetSnapshot.from_dict(manifest["snapshot"])
    connection = sqlite3.connect(f"file:{FROZEN_DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    prepared = []
    excluded = []
    try:
        for item in manifest["runs"]:
            run = module._load_run(args.record_dir / "evaluation.sqlite3", item["run_id"])
            if run.terminal_status != "completed":
                excluded.append({"run_id": run.run_id, "terminal_status": run.terminal_status,
                                 "reason": "No completed answer; do not invent a Judge review"})
                continue
            payload, limitations = module.prepare_projection_input(
                run=run, record_dir=args.record_dir, database=FROZEN_DB,
                bundle_dir=BUNDLE, snapshot=snapshot, connection=connection,
            )
            prepared.append((run, payload, limitations))
    finally:
        connection.close()
    if args.dry_run:
        print(json.dumps({"eligible": len(prepared), "excluded": excluded,
                          "projection_limitations": [p[2] for p in prepared]}))
        return
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "excluded-runs.json").write_text(json.dumps(excluded, indent=2) + "\n")
    load_environment_file(None)
    settings = load_settings(model_id="gpt-plus", role="judge", config_path=ROOT / "config/models.yaml")
    assert settings.provider == "chatgpt-plan", "Judge must use the authorized OAuth profile"
    install_meter("judge", args.record_dir.name, args.output)
    store = SQLiteEvaluationStore(args.output / "evaluation.sqlite3")
    try:
        for run, payload, limitations in prepared:
            out = args.output / run.run_id
            out.mkdir()
            (out / "input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            (out / "configuration.json").write_text(json.dumps({
                "rubric": "eval-rubric-v2.1", "settings": settings.to_safe_dict(), "limitations": limitations,
            }, ensure_ascii=False, indent=2) + "\n")
            try:
                completion = await complete_json(
                    settings, system_prompt=judge_prompt_for("eval-rubric-v2.1"),
                    user_prompt=json.dumps(payload, ensure_ascii=False), session_id=run.run_id,
                )
                (out / "response.json").write_text(json.dumps(completion_record(completion), ensure_ascii=False, indent=2) + "\n")
                assert completion.finish_reason in {"stop", "completed"}, completion.finish_reason
                review = parse_review(completion.content, run_id=run.run_id,
                                      judge_identity=f"{settings.provider}:{completion.model}:eval-rubric-v2.1",
                                      rubric_version="eval-rubric-v2.1")
                store.save_run(run)
                store.save_review(review)
                (out / "review.json").write_text(json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n")
                print(f"reviewed {run.case_id} {run.run_id}", flush=True)
            except Exception as exc:
                # The provider boundary already redacts secrets; preserve failure and stop.
                (out / "error.json").write_text(json.dumps({"type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False) + "\n")
                raise
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
