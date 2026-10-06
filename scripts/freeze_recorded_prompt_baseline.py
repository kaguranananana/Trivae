"""显式导入旧real_pair生产baseline记录；不重跑查询、不构造Provider。"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path

from trivae.capabilities import ExecutionScope
from trivae.evaluation.contracts import (
    CaseProvenance,
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationRun,
)
from trivae.evaluation.prompt_screening import read_artifact, screening_conditions, write_artifact
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.projection import project_trace
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride
from trivae.query.runtime.prompt import SYSTEM_PROMPT


def freeze_recorded_cell(
    cell: Path, *, snapshot: DatasetSnapshot, commit: str, policy_tags: tuple[str, ...],
) -> tuple[EvaluationCaseBundle, dict]:
    """从已记录事实生成versioned case和baseline artifact，不捏造历史GT或checks。"""
    recorded = read_artifact(cell / "result.json")
    initial = read_artifact(cell / "initial_contract.json")
    # 原数据是明确baseline side；旧candidate即使completed也不能变成baseline。
    if recorded["variant"] != "baseline" or not initial["instructions"].startswith(SYSTEM_PROMPT):
        raise EvaluationContractError("recorded cell is not the current production prompt baseline")
    if initial["query"] != recorded["query"] or recorded["forced_route"] != "standard_execution":
        raise EvaluationContractError("recorded query or route is inconsistent")
    # 完整settings与SDK contract取原记录，不用当前默认值替换历史事实。
    settings = initial["settings"]
    if settings != recorded["settings"]:
        raise EvaluationContractError("recorded settings are inconsistent")
    match = re.search(r"of (\d+) total\. Multiple tool calls", initial["instructions"])
    if match is None:
        raise EvaluationContractError("recorded tool budget is unavailable")
    tool_budget = int(match[1])
    raw_scope = initial["scope"]
    scope = ExecutionScope(allowed_session_ids=None if raw_scope["sessions"] is None else tuple(raw_scope["sessions"]),
                           start_timestamp=raw_scope["start"], end_timestamp=raw_scope["end"],
                           max_results=raw_scope["max_results"])
    # 没有旧人工reference GT时明确保留空标注；完整答案/证据供人工筛选，不伪造分数。
    case = EvaluationCaseBundle(case_id=f"frozen-{recorded['case']}", version=1, suite_tags=policy_tags,
        dataset_snapshot=snapshot, data_access_scope=scope, query=recorded["query"], reference_findings=(),
        provenance=CaseProvenance(source="recorded production real_pair baseline",
            method="explicit historical import; exposed development case, no new GT annotation",
            created_at=snapshot.created_at))
    tools = tuple(tool["name"] for tool in initial["tools"])
    conditions = screening_conditions(case, provider=settings["provider"], model=settings["model_name"],
                                      settings=settings, tool_budget=tool_budget, tools=tools)
    conditions["tool_contract"] = initial["tools"]
    conditions["model_settings"] = initial["model_settings"]
    variant = ControlledVariant(variant_id=f"frozen-baseline:{cell.name}", code_version=commit,
        provider=settings["provider"], model=settings["model_name"], role="last_stable",
        prompt_identity=f"production:{commit}", available_tools=tools,
        runtime_configuration={"trace_profile": "debug"}, budget={"max_tool_rounds": tool_budget},
        execution_override=ExecutionOverride(forced_route="standard_execution"))
    store = SQLiteTraceStore(cell / "trace.sqlite3")
    try:
        trace = project_trace(store.read_trace(recorded["query_result"]["trace_id"]))
    finally:
        store.close()
    # EvaluationRun承载既有结构；不将历史pytest/finalizer状态变成答案质量判定。
    from trivae.evaluation.contracts import scope_identity
    run = EvaluationRun(run_id=f"frozen-run:{cell.name}", case_id=case.case_id, case_version=case.version,
        suite_id="frozen-prompt-development", suite_version=1, snapshot_id=snapshot.snapshot_id,
        scope_identity=scope_identity(scope), variant_id=variant.variant_id, query_request_id=trace.request_id,
        query_request={"query": case.query, "scope": case.to_dict()["data_access_scope"],
                       "data_snapshot": {}, "historical_cell": cell.name},
        terminal_status=recorded["query_result"]["termination"], query_result=recorded["query_result"],
        answer_artifact_reference=f"historical-cell:{cell.name}/conversation.sqlite3",
        trace_id=trace.trace_id, deterministic_checks=(),
        operational_measurements={"usage": recorded["usage"], "latency_ms": recorded["latency_ms"],
                                  "provider_calls": recorded["http_requests"]},
        started_at=trace.started_at, completed_at=trace.terminal_at,
        execution_override=variant.execution_override.to_dict())
    requests = [json.loads(line) for line in (cell / "provider_requests.jsonl").read_text().splitlines()]
    artifact = {"kind": "frozen_baseline", "commit": commit, "prompt": SYSTEM_PROMPT,
        "conditions": conditions, "variant": variant.to_dict(), "run": run.to_dict(), "trace": asdict(trace),
        "answer": (cell / "answer.md").read_text(), "evidence": recorded["query_result"]["evidence_sources"],
        "provider_requests": requests, "provider_calls": recorded["http_requests"],
        "semantic_review": "historical exposed development; no fresh review", "currency_cost": None,
        "historical_cell": str(cell), "import_provider_calls": 0}
    return case, artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--baseline-commit", required=True)
    parser.add_argument("--policy", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case, artifact = freeze_recorded_cell(args.cell, snapshot=DatasetSnapshot.from_database(args.snapshot),
                                         commit=args.baseline_commit, policy_tags=tuple(args.policy))
    write_artifact(args.output / "cases" / f"{case.case_id}.json", case.to_dict())
    write_artifact(args.output / "baselines" / f"{case.case_id}.json", artifact)
    print(json.dumps({"case": case.identity, "import_provider_calls": 0}))


if __name__ == "__main__":
    main()
