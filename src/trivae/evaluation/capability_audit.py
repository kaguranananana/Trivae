"""Audit private reference packets and summarize reviews without promoting provisional truth."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationReview,
    EvaluationRun,
    EvaluationSuite,
)
from .frozen_data import _metadata
from .reporting import run_report

CAPABILITY_AXES = (
    "task_completion", "factual_correctness", "evidence_recall",
    "citation_faithfulness", "unsupported_claims",
)


def reference_confirmed(case: EvaluationCaseBundle) -> bool:
    """Human confirmation must be explicit for the case and each finding and source."""
    return bool(
        "review:confirmed" in case.suite_tags
        and case.reference_findings
        and all(
            finding.provenance.adjudicated and finding.reference_evidence
            and all(evidence.provenance.adjudicated for evidence in finding.reference_evidence)
            for finding in case.reference_findings
        )
    )


def audit_evidence(
    *, suite: EvaluationSuite, cases: Mapping[str, EvaluationCaseBundle], packet: Mapping[str, Any],
    freeze: Mapping[str, Any], database: Path,
) -> dict[str, Any]:
    """Check source identity, time, scope and exact text; do not judge semantic entailment."""
    snapshot = DatasetSnapshot.from_database(database)
    if (not isinstance(freeze.get("freeze_id"), str) or packet.get("snapshot_id") != snapshot.snapshot_id
            or packet.get("freeze_id") != freeze.get("freeze_id")
            or not isinstance(freeze.get("snapshot"), Mapping)):
        raise EvaluationContractError("evidence packet snapshot differs from database")
    frozen = DatasetSnapshot.from_dict(freeze["snapshot"])
    if (frozen.snapshot_id != snapshot.snapshot_id or
            frozen.deterministic_fingerprint != snapshot.deterministic_fingerprint):
        raise EvaluationContractError("freeze snapshot differs from database")
    semantic_name = freeze.get("semantic_file")
    semantic = database.parent / semantic_name if isinstance(semantic_name, str) else None
    if _metadata(database, semantic) != freeze.get("index_state"):
        raise EvaluationContractError("frozen data or index revision differs from database")
    entries = packet.get("cases")
    if not isinstance(entries, list):
        raise EvaluationContractError("evidence packet requires cases")
    indexed: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        identity = entry.get("case_id")
        if not isinstance(identity, str) or identity in indexed:
            raise EvaluationContractError("evidence packet has invalid or duplicate case")
        indexed[identity] = entry
    details = []
    con = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        for ref in suite.case_references:
            case = cases.get(ref.identity)
            if case is None or case.identity != ref.identity:
                raise EvaluationContractError("suite case is missing")
            if (case.dataset_snapshot.snapshot_id != snapshot.snapshot_id or
                    case.dataset_snapshot.deterministic_fingerprint != snapshot.deterministic_fingerprint):
                raise EvaluationContractError(f"case {case.case_id} snapshot differs from database")
            entry = indexed.get(case.case_id)
            if entry is None or entry.get("case_version") != case.version or not isinstance(entry.get("evidence"), list):
                raise EvaluationContractError(f"case {case.case_id} evidence packet is missing")
            records = entry["evidence"]
            by_id = {record["internal_message_id"]: record for record in records}
            if len(by_id) != len(records):
                raise EvaluationContractError(f"case {case.case_id} has duplicate packet evidence")
            referenced: set[str] = set()
            for finding in case.reference_findings:
                for evidence in finding.reference_evidence:
                    message_id = evidence.locator.get("internal_message_id")
                    if evidence.source_type != "message" or not isinstance(message_id, str):
                        raise EvaluationContractError(f"case {case.case_id} requires message evidence")
                    referenced.add(message_id)
            if not referenced or referenced != set(by_id):
                raise EvaluationContractError(f"case {case.case_id} packet and reference IDs differ")
            for message_id, record in by_id.items():
                row = con.execute(
                    "SELECT session_id,timestamp,sender_user_id,content_text FROM messages WHERE internal_message_id=?",
                    (message_id,),
                ).fetchone()
                if row is None:
                    forwarded = con.execute(
                        "SELECT session_id,timestamp,sender_user_id,content_text,root_message_id,parent_message_id,path,original_timestamp "
                        "FROM forwarded_messages WHERE internal_message_id=?",
                        (message_id,),
                    ).fetchone()
                    if forwarded is not None:
                        if forwarded[4:] != (record.get("root_message_id"), record.get("parent_message_id"),
                                             record.get("path"), record.get("original_timestamp")):
                            raise EvaluationContractError(f"case {case.case_id} forwarded source metadata differs")
                        row = forwarded[:4]
                if row is None:
                    raise EvaluationContractError(f"case {case.case_id} source message is missing")
                expected = (record.get("session_id"), record.get("timestamp"), record.get("sender_user_id"), record.get("content_text"))
                if row != expected:
                    raise EvaluationContractError(f"case {case.case_id} source metadata or text differs")
                quotes = record.get("quotes", [])
                if not isinstance(quotes, list) or any(not isinstance(q, str) or not q or q not in row[3] for q in quotes):
                    raise EvaluationContractError(f"case {case.case_id} quote does not match source")
                scope = case.data_access_scope
                if (scope.allowed_session_ids is not None and row[0] not in scope.allowed_session_ids or
                    scope.start_timestamp is not None and row[1] < scope.start_timestamp or
                    scope.end_timestamp is not None and row[1] >= scope.end_timestamp):
                    raise EvaluationContractError(f"case {case.case_id} source is outside scope")
            details.append({"case": case.identity, "source_messages": len(by_id),
                            "reference_status": "human_confirmed" if reference_confirmed(case) else "human_pending"})
    finally:
        con.close()
    return {"cases": details, "cases_checked": len(details),
            "sources_checked": sum(row["source_messages"] for row in details),
            "human_pending": sum(row["reference_status"] == "human_pending" for row in details),
            "note": "Identity, scope and exact source text checked; semantic support and completeness still require review."}


def capability_report(database: Path, suite: EvaluationSuite, cases: Mapping[str, EvaluationCaseBundle]) -> dict[str, Any]:
    """Reuse run_report; keep human-confirmed and model-assisted quality denominators separate."""
    base = run_report(database, suite_id=suite.suite_id)
    metrics: dict[str, dict[str, Counter[str]]] = {
        axis: {"human_confirmed": Counter(), "model_assisted_provisional": Counter()}
        for axis in CAPABILITY_AXES
    }
    usage = Counter[str]()
    latency_ms = 0.0
    latency_samples = tool_samples = 0
    tool_calls = 0
    con = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT payload_json FROM evaluation_runs WHERE suite_id=? AND suite_version=? ORDER BY started_at,run_id",
                           (suite.suite_id, suite.version)).fetchall()
        if len(base["runs"]) != len(rows):
            raise EvaluationContractError("evaluation database contains another version of this suite")
        suite_refs = {ref.identity for ref in suite.case_references}
        for (payload,) in rows:
            run = EvaluationRun.from_dict(json.loads(payload))
            identity = f"{run.case_id}@v{run.case_version}"
            case = cases.get(identity)
            if identity not in suite_refs or case is None or run.snapshot_id != case.dataset_snapshot.snapshot_id:
                raise EvaluationContractError("run does not match the selected suite case or snapshot")
            m = run.operational_measurements
            latency = m.get("latency_ms")
            if isinstance(latency, (int, float)):
                latency_ms += latency
                latency_samples += 1
            calls = m.get("tool_calls")
            if isinstance(calls, int):
                tool_calls += calls
                tool_samples += 1
            run_usage = m.get("usage")
            if isinstance(run_usage, Mapping):
                usage["runs_with_usage"] += 1
                for name in ("input_tokens", "output_tokens", "requests"):
                    value = run_usage.get(f"known_{name}", run_usage.get(name))
                    if isinstance(value, int):
                        usage[f"known_{name}"] += value
                if isinstance(run_usage.get("responses_without_usage"), int):
                    usage["responses_without_usage"] += run_usage["responses_without_usage"]
            else:
                usage["runs_without_usage"] += 1
            if run.terminal_status != "completed":
                continue
            review_rows = con.execute("SELECT payload_json FROM evaluation_reviews WHERE run_id=? ORDER BY created_at,review_id",
                                      (run.run_id,)).fetchall()
            latest: dict[tuple[str, str], tuple[str, bool]] = {}
            for (review_payload,) in review_rows:
                review = EvaluationReview.from_dict(json.loads(review_payload))
                for axis in CAPABILITY_AXES:
                    assessment = review.quality_axes.get(axis, {})
                    label = assessment.get("label")
                    if label in ("pass", "fail", "mixed", "unknown", "not_reviewed"):
                        latest[(review.reviewer_type, axis)] = (label, review.needs_adjudication)
            for (reviewer_type, axis), (label, needs_adjudication) in latest.items():
                if reviewer_type == "model_assisted":
                    metrics[axis]["model_assisted_provisional"][label] += 1
                elif not needs_adjudication and reference_confirmed(case):
                    metrics[axis]["human_confirmed"][label] += 1
    finally:
        con.close()
    result_metrics: dict[str, dict[str, dict[str, int]]] = {}
    for axis, groups in metrics.items():
        result_metrics[axis] = {}
        for group, values in groups.items():
            result_metrics[axis][group] = {"numerator": values["pass"], "denominator": values["pass"] + values["fail"],
                                           "mixed": values["mixed"], "unknown": values["unknown"] + values["not_reviewed"]}
    return {"run_report": base, "quality": result_metrics, "usage": dict(usage),
            "latency_ms_sum": latency_ms, "latency_samples": latency_samples,
            "tool_calls_sum": tool_calls, "tool_calls_samples": tool_samples,
            "note": "Quality excludes failed runs; provisional reviews are not formal accuracy. Cost is unavailable unless observed."}
