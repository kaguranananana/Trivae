"""Run one explicit offline model-assisted capability review, after the Agent run."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from scripts.verify_capability_bundle import verify
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.evaluation.capability_judge import JUDGE_PROMPT, RUBRIC_VERSION, parse_review, prepare_review_input
from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError
from trivae.evaluation.store import SQLiteEvaluationStore
from trivae.query.runtime.model_completion import complete_json, completion_record


async def main_async(args: argparse.Namespace) -> None:
    # Verify references independently before exposing the saved answer to the judge.
    verify(args.bundle_dir, args.suite, args.freeze_manifest, args.database)
    load_environment_file(args.env_file)
    settings = load_settings(model_id=args.judge_model, role="judge", config_path=args.models_config)
    if not args.evaluation_database.is_file():
        raise EvaluationContractError("evaluation database does not exist")
    store = SQLiteEvaluationStore(args.evaluation_database)
    try:
        run = store.get_run(args.run_id)
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
            "rubric_version": RUBRIC_VERSION,
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
                system_prompt=JUDGE_PROMPT,
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
                judge_identity=f"{settings.provider}:{completion.model}:{RUBRIC_VERSION}",
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
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evaluation-database", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--record-dir", type=Path, required=True)
    parser.add_argument("--judge-model", help="Named model profile; defaults to evaluation.judge")
    parser.add_argument("--models-config", type=Path, help="Model registry YAML; defaults to config/models.yaml")
    parser.add_argument("--env-file", type=Path)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
