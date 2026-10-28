"""Run one explicit offline model-assisted capability review, after the Agent run."""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

from scripts.verify_capability_bundle import verify
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.evaluation.capability_judge import (
    RUBRIC_VERSION,
    RUBRIC_VERSIONS,
    judge_prompt_for,
    parse_review,
    prepare_review_input,
)
from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError, EvaluationRun
from trivae.evaluation.store import SQLiteEvaluationStore
from trivae.query.runtime.model_completion import complete_json, completion_record


async def main_async(args: argparse.Namespace) -> None:
    # Verify references independently before exposing the saved answer to the judge.
    if not args.skip_bundle_verification:
        verify(args.bundle_dir, args.suite, args.freeze_manifest, args.database)
    load_environment_file(args.env_file)
    settings = load_settings(model_id=args.judge_model, role="judge", config_path=args.models_config)
    rubric_version = args.rubric_version
    judge_prompt = judge_prompt_for(rubric_version)
    source_database = args.source_evaluation_database or args.evaluation_database
    if not source_database.is_file():
        raise EvaluationContractError("source evaluation database does not exist")
    source = sqlite3.connect(source_database.resolve().as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    store = SQLiteEvaluationStore(args.evaluation_database)
    try:
        row = source.execute("SELECT payload_json FROM evaluation_runs WHERE run_id = ?", (args.run_id,)).fetchone()
        if row is None:
            raise EvaluationContractError(f"source evaluation run not found: {args.run_id}")
        run = EvaluationRun.from_dict(json.loads(row["payload_json"]))
        # The output Store is independent from the Baseline Store and keeps its own Run reference.
        store.save_run(run)
        case = EvaluationCaseBundle.from_json(args.bundle_dir / "cases" / f"{run.case_id}.json")
        truth = json.loads((args.bundle_dir / "ground-truth-v1.json").read_text(encoding="utf-8"))
        packet = json.loads((args.bundle_dir / "evidence.json").read_text(encoding="utf-8"))
        truth_case = next(x for x in truth["cases"] if x["case_id"] == run.case_id)
        evidence_case = next(x for x in packet["cases"] if x["case_id"] == run.case_id)
        payload = prepare_review_input(case=case, truth=truth_case, packet=evidence_case, run=run,
                                       database=args.database)
        args.record_dir.mkdir(parents=True, exist_ok=False)
        (args.record_dir / "input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        configuration = {
            "rubric_version": rubric_version,
            "model_profile": settings.model_profile,
            "provider": settings.provider,
            "model": settings.model_name,
            "auth_mode": settings.auth_mode or ("chatgpt_oauth" if settings.provider == "chatgpt-plan" else "api_key"),
            "configuration": settings.to_safe_dict(),
            "models_config": str(args.models_config or Path("config/models.yaml")),
        }
        (args.record_dir / "configuration.json").write_text(json.dumps(configuration, ensure_ascii=False, indent=2) + "\n")
        try:
            completion = await complete_json(
                settings,
                system_prompt=judge_prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                session_id=run.run_id,
            )
            (args.record_dir / "response.json").write_text(
                json.dumps(completion_record(completion), ensure_ascii=False, indent=2) + "\n"
            )
            if completion.finish_reason not in {"stop", "completed"}:
                raise EvaluationContractError("capability judge response did not finish normally")
            review = parse_review(
                completion.content,
                run_id=run.run_id,
                judge_identity=f"{settings.provider}:{completion.model}:{rubric_version}",
                rubric_version=rubric_version,
            )
            store.save_review(review)
            (args.record_dir / "review.json").write_text(json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"review_id": review.review_id, "run_id": run.run_id, "judge": completion.model,
                              "reviewer_type": review.reviewer_type}, ensure_ascii=False))
        except Exception as exc:
            message = str(exc)
            if settings.api_key:
                message = message.replace(settings.api_key, "[REDACTED]")
            safe_observation = getattr(exc, "observation", None)
            if not isinstance(safe_observation, dict):
                safe_observation = getattr(exc, "safe_observation", None)
            error: dict[str, object] = {"type": type(exc).__name__, "message": message}
            if isinstance(safe_observation, dict):
                error["observation"] = safe_observation
            (args.record_dir / "error.json").write_text(json.dumps(error, ensure_ascii=False, indent=2) + "\n")
            raise
    finally:
        source.close()
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evaluation-database", type=Path, required=True)
    parser.add_argument("--source-evaluation-database", type=Path,
                        help="Baseline Run Store to read; defaults to --evaluation-database")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--record-dir", type=Path, required=True)
    parser.add_argument("--judge-model", help="Named model profile; defaults to evaluation.judge")
    parser.add_argument("--rubric-version", choices=RUBRIC_VERSIONS, default=RUBRIC_VERSION)
    parser.add_argument("--models-config", type=Path, help="Model registry YAML; defaults to config/models.yaml")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--skip-bundle-verification", action="store_true",
                        help="Skip only when a campaign runner has just verified the same frozen bundle")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
