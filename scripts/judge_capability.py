"""Run one explicit offline model-assisted capability review, after the Agent run."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from openai import AsyncOpenAI

from scripts.verify_capability_bundle import verify
from trivae.config.dotenv import load_environment_file
from trivae.config.model_capabilities import resolve_reasoning_effort
from trivae.config.settings import load_settings
from trivae.evaluation.capability_judge import JUDGE_PROMPT, RUBRIC_VERSION, parse_review, prepare_review_input
from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError
from trivae.evaluation.store import SQLiteEvaluationStore


async def main_async(args: argparse.Namespace) -> None:
    # Verify references independently before exposing the saved answer to the judge.
    verify(args.bundle_dir, args.suite, args.freeze_manifest, args.database)
    load_environment_file(args.env_file)
    settings = load_settings()
    if settings.provider == "chatgpt-plan":
        raise EvaluationContractError("offline judge requires an explicit OpenAI-compatible API provider")
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
        reasoning_effort = resolve_reasoning_effort(provider=settings.provider, model_name=settings.model_name)
        configuration = {"rubric_version": RUBRIC_VERSION, "provider": settings.provider, "model": settings.model_name,
                         "temperature": 0, "max_output_tokens": settings.max_output_tokens,
                         "base_url": settings.base_url, "reasoning_effort": reasoning_effort}
        (args.record_dir / "configuration.json").write_text(json.dumps(configuration, ensure_ascii=False, indent=2) + "\n")
        try:
            headers = ({"x-opencode-session": run.run_id, "User-Agent": "trivae/0.1.0"}
                       if settings.provider == "opencode-go" else None)
            async with AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url, default_headers=headers) as client:
                response = await client.chat.completions.create(
                    model=settings.model_name,
                    messages=[{"role": "system", "content": JUDGE_PROMPT},
                              {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                    response_format={"type": "json_object"}, temperature=0, max_tokens=settings.max_output_tokens,
                    reasoning_effort=reasoning_effort,
                )
            if not response.choices or not response.choices[0].message.content:
                raise EvaluationContractError("capability judge returned no content")
            content = response.choices[0].message.content
            observed = {"model": response.model, "finish_reason": response.choices[0].finish_reason,
                        "usage": None if response.usage is None else response.usage.model_dump(), "content": content}
            (args.record_dir / "response.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2) + "\n")
            if response.choices[0].finish_reason != "stop":
                raise EvaluationContractError("capability judge response did not finish normally")
            review = parse_review(content, run_id=run.run_id, judge_identity=f"{settings.provider}:{response.model}")
            store.save_review(review)
            (args.record_dir / "review.json").write_text(json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"review_id": review.review_id, "run_id": run.run_id, "judge": response.model,
                              "reviewer_type": review.reviewer_type}, ensure_ascii=False))
        except Exception as exc:
            (args.record_dir / "error.json").write_text(json.dumps({"type": type(exc).__name__, "message": str(exc)},
                                                                     ensure_ascii=False, indent=2) + "\n")
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
    parser.add_argument("--env-file", type=Path)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
