"""Export local evaluation facts using LangSmith's documented HTTP APIs.

No network call is made from the query path. Full Trace payloads stay local.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from .contracts import EvaluationCaseBundle, EvaluationContractError, EvaluationReview, EvaluationRun, EvaluationSuite
from .variant import ControlledVariant

_ID = re.compile(r"[A-Za-z0-9_.:@/+-]{1,256}\Z")


def _identifier(value: str) -> str:
    if not _ID.fullmatch(value):
        raise EvaluationContractError("export identifier contains unsupported characters")
    return value


def _read_db(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise EvaluationContractError("evaluation or trace database does not exist")
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _json_file(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvaluationContractError("export input JSON cannot be read") from exc


def _redacted_content(path: Path | None) -> dict[str, Any]:
    data = _json_file(path)
    if data is None:
        return {"cases": {}, "runs": {}}
    if not isinstance(data, dict) or set(data) - {"cases", "runs"}:
        raise EvaluationContractError("redacted content must contain only cases and runs")
    for group, fields in (("cases", {"question", "reference"}), ("runs", {"answer"})):
        items = data.get(group, {})
        if not isinstance(items, dict):
            raise EvaluationContractError("redacted content section must be an object")
        for key, value in items.items():
            _identifier(key)
            if not isinstance(value, dict) or set(value) - fields or any(not isinstance(v, str) for v in value.values()):
                raise EvaluationContractError("redacted content entry has unsupported fields")
    encoded = json.dumps(data, ensure_ascii=False)
    for name, value in os.environ.items():
        if len(value) >= 8 and any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            if value in encoded:
                raise EvaluationContractError("redacted content contains a configured secret")
    return data


def _index_records(path: Path | None) -> dict[str, dict[str, Any]]:
    data = _json_file(path)
    if data is None:
        return {}
    if not isinstance(data, list):
        raise EvaluationContractError("benchmark records must be a JSON array")
    result: dict[str, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("run_id"), str):
            raise EvaluationContractError("benchmark record requires a run_id")
        if item["run_id"] in result:
            raise EvaluationContractError("benchmark records contain duplicate run_id")
        result[item["run_id"]] = item
    return result


def _score(key: str, value: object, *, status: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {"key": _identifier(key)}
    if isinstance(value, bool):
        entry["score"] = int(value)
    elif isinstance(value, (int, float)):
        entry["score"] = value
    elif isinstance(value, str):
        entry["value"] = _identifier(value)
    else:
        raise EvaluationContractError("unsupported feedback value")
    if status is not None:
        entry["comment"] = _identifier(status)
    return entry


def _feedback(run: EvaluationRun, reviews: Sequence[EvaluationReview], record: Mapping[str, Any] | None,
              judgment: Mapping[str, Any] | None) -> list[dict[str, object]]:
    scores: list[dict[str, object]] = []
    for check in run.deterministic_checks:
        value: object = check.status == "passed" if check.status in ("passed", "failed") else check.status
        scores.append(_score(f"deterministic.{check.name}", value, status=check.severity))
    if record is not None:
        metrics = record.get("metrics", [])
        if not isinstance(metrics, list):
            raise EvaluationContractError("benchmark metrics must be an array")
        for metric in metrics:
            if not isinstance(metric, dict) or not isinstance(metric.get("name"), str):
                raise EvaluationContractError("benchmark metric is invalid")
            value = metric.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                scope = metric.get("scope")
                scores.append(_score("benchmark." + metric["name"], value,
                                     status=scope if isinstance(scope, str) else None))
    if judgment is not None:
        verification = judgment.get("verification_status")
        if not isinstance(verification, str):
            status = judgment.get("status")
            if not isinstance(status, str):
                raise EvaluationContractError("judge record has no verification status or failure status")
            scores.append(_score("judge.execution_status", status))
        else:
            for axis in ("grounded_claim_rate", "citation_correctness"):
                value = judgment.get(axis)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    scores.append(_score("judge." + axis, value, status=verification))
    for review in reviews:
        scores.extend(_review_feedback(review))
    return scores


def _review_feedback(review: EvaluationReview) -> list[dict[str, object]]:
    source = "human" if review.reviewer_type == "human" else "llm_assisted"
    scores = []
    for axis, assessment in review.quality_axes.items():
        value = assessment.get("score", assessment.get("label"))
        if isinstance(value, (bool, int, float, str)):
            scores.append(_score(f"{source}.{axis}", value,
                                 status="needs_adjudication" if review.needs_adjudication else review.rubric_version))
    return scores


def _trace_facts(con: sqlite3.Connection | None, trace_id: str | None) -> dict[str, object]:
    if con is None or trace_id is None:
        return {"availability": "not_requested" if con is None else "no_trace_id"}
    row = con.execute("SELECT terminal_outcome FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
    if row is None:
        return {"availability": "not_found"}
    events = con.execute(
        "SELECT stage, operation, phase, outcome, duration_ms, failure_json FROM trace_events "
        "WHERE trace_id=? ORDER BY sequence",
        (trace_id,),
    ).fetchall()
    event_facts = []
    for event in events:
        fact = {"stage": _identifier(event["stage"]), "operation": _identifier(event["operation"]),
                "phase": _identifier(event["phase"]), "outcome": event["outcome"], "duration_ms": event["duration_ms"]}
        if event["failure_json"]:
            try:
                failure = json.loads(event["failure_json"])
                fact["failure"] = {key: failure.get(key) for key in
                                   ("error_code", "origin_stage", "observed_stage", "category", "handling",
                                    "cause_event_id", "cause_operation_id")}
            except (ValueError, AttributeError) as exc:
                raise EvaluationContractError("trace failure record is invalid") from exc
        event_facts.append(fact)
    return {
        "availability": "available",
        "terminal_outcome": row["terminal_outcome"],
        "events": event_facts,
    }


class ExportLedger:
    """Separate local mapping; historical evaluation records are never modified."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS external_datasets (suite TEXT PRIMARY KEY, dataset_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS external_examples (suite TEXT, case_identity TEXT, example_id TEXT NOT NULL,
                inputs_json TEXT NOT NULL, outputs_json TEXT NOT NULL, PRIMARY KEY(suite, case_identity));
            CREATE TABLE IF NOT EXISTS external_exports (experiment TEXT PRIMARY KEY, suite TEXT NOT NULL,
                state TEXT NOT NULL, dataset_id TEXT, project_id TEXT, started_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS external_runs (experiment TEXT, local_run_id TEXT, example_id TEXT,
                remote_run_id TEXT, PRIMARY KEY(experiment, local_run_id));
            CREATE TABLE IF NOT EXISTS external_reviews (experiment TEXT, review_id TEXT, feedback_key TEXT,
                feedback_id TEXT, state TEXT, PRIMARY KEY(experiment, review_id, feedback_key));
        """)
        self.con.commit()

    def close(self) -> None:
        self.con.close()


def lookup_mapping(ledger_path: Path, run_id: str) -> list[dict[str, Any]]:
    con = _read_db(ledger_path)
    try:
        rows = con.execute(
            "SELECT r.experiment,r.local_run_id,r.remote_run_id,r.example_id,e.dataset_id,e.project_id,"
            "e.state AS export_state FROM external_runs r JOIN external_exports e ON e.experiment=r.experiment "
            "WHERE r.local_run_id=? ORDER BY r.experiment", (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as exc:
        raise EvaluationContractError("LangSmith ledger is invalid") from exc
    finally:
        con.close()


def _connection(api_key: str | None = None) -> tuple[str, str]:
    key = api_key if api_key is not None else os.environ.get("LANGSMITH_API_KEY", "")
    if not key:
        raise EvaluationContractError("LANGSMITH_API_KEY is missing")
    base = os.environ.get("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com"
    if not base.startswith("https://"):
        raise EvaluationContractError("LangSmith endpoint must use HTTPS")
    return base.rstrip("/"), key


def export_experiment(*, evaluation_db: Path, suite: EvaluationSuite, run_ids: Sequence[str], experiment: str,
                      ledger_path: Path, trace_db: Path | None = None, content_path: Path | None = None,
                      records_path: Path | None = None, judgments_path: Path | None = None,
                      cases: Mapping[str, EvaluationCaseBundle] | None = None, include_content: bool = False,
                      manifest_path: Path | None = None, variant_path: Path | None = None, import_time: bool = False,
                      endpoint: str | None = None, api_key: str | None = None,
                      transport: httpx.BaseTransport | None = None) -> dict[str, object]:
    """Import persisted runs with the documented external-experiment endpoint; never run a model."""
    _identifier(experiment)
    if not run_ids or len(set(run_ids)) != len(run_ids):
        raise EvaluationContractError("select one or more distinct run IDs")
    key = api_key if api_key is not None else os.environ.get("LANGSMITH_API_KEY", "")
    if not key:
        raise EvaluationContractError("LANGSMITH_API_KEY is missing")
    base = (endpoint or os.environ.get("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com").rstrip("/")
    if not base.startswith("https://"):
        raise EvaluationContractError("LangSmith endpoint must use HTTPS")
    content = _redacted_content(content_path)
    records, judgments = _index_records(records_path), _index_records(judgments_path)
    suite_id = _identifier(suite.identity)
    content_mode = "redacted" if content_path else "content" if include_content else "metadata"
    dataset_key = suite_id + ":" + content_mode
    allowed = {ref.identity for ref in suite.case_references}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    variants: set[str] = set()
    con = _read_db(evaluation_db)
    trace_con = _read_db(trace_db) if trace_db else None
    try:
        for run_id in run_ids:
            _identifier(run_id)
            row = con.execute("SELECT payload_json FROM evaluation_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise EvaluationContractError("selected run does not exist")
            run = EvaluationRun.from_dict(json.loads(row[0]))
            identity = _identifier(f"{run.case_id}@v{run.case_version}")
            record = records.get(run_id)
            same_suite = (run.suite_id, run.suite_version) == (suite.suite_id, suite.version)
            # Existing benchmark orchestrators called run_case(), recording "single_case" locally.
            recorded_single_case = (run.suite_id == "single_case" and record is not None
                                    and record.get("case_id") == run.case_id
                                    and record.get("variant_id") == run.variant_id)
            if identity not in allowed or not (same_suite or recorded_single_case):
                raise EvaluationContractError("run does not belong to the selected suite version")
            if identity in seen:
                raise EvaluationContractError("an experiment can contain only one run per case; use separate repetitions")
            seen.add(identity)
            variants.add(_identifier(run.variant_id))
            review_rows = con.execute("SELECT payload_json FROM evaluation_reviews WHERE run_id=? ORDER BY created_at",
                                      (run_id,)).fetchall()
            reviews = [EvaluationReview.from_dict(json.loads(item[0])) for item in review_rows]
            case_content = content.get("cases", {}).get(identity, {})
            run_content = content.get("runs", {}).get(run_id, {})
            case = cases.get(identity) if cases is not None else None
            if include_content and case is None:
                raise EvaluationContractError("content export requires the versioned case")
            if case is not None and case.dataset_snapshot.snapshot_id != run.snapshot_id:
                raise EvaluationContractError("case snapshot differs from persisted run")
            trace_id = _identifier(run.trace_id) if run.trace_id else None
            actual: dict[str, object] = {"local_run_id": run_id, "trace_id": trace_id,
                                         "terminal_status": _identifier(run.terminal_status),
                                         "recorded_local_suite": f"{run.suite_id}@v{run.suite_version}",
                                         "original_started_at": run.started_at,
                                         "original_completed_at": run.completed_at,
                                         "original_duration_seconds": (
                                             datetime.fromisoformat(run.completed_at)
                                             - datetime.fromisoformat(run.started_at)).total_seconds(),
                                         "failed_checks": [{"name": check.name, "severity": check.severity,
                                                            "message": check.message if include_content else None}
                                                           for check in run.deterministic_checks
                                                           if check.status == "failed"],
                                         "trace": _trace_facts(trace_con, trace_id)}
            diagnosis_rows = con.execute("SELECT payload_json FROM evaluation_diagnoses WHERE run_id=? ORDER BY diagnosis_id",
                                         (run_id,)).fetchall()
            diagnoses = [json.loads(item[0]) for item in diagnosis_rows]
            actual["diagnoses"] = diagnoses if include_content else [
                {"primary_cause": item.get("primary_cause"), "status": item.get("status")} for item in diagnoses]
            if include_content and run.exception_message is not None:
                actual["exception_message"] = run.exception_message
            inputs: dict[str, object] = {"case": identity}
            expected: dict[str, object] = {"review_status": "see_local_case_and_reviews"}
            if include_content and case is not None:
                inputs["question"] = case.query
                expected["reference_findings"] = [finding.to_dict() for finding in case.reference_findings]
                expected["case_provenance"] = case.provenance.to_dict()
                if run.query_result is not None:
                    actual["answer"] = run.query_result.get("answer_text")
            if "question" in case_content:
                inputs["question"] = case_content["question"]
            if "reference" in case_content:
                expected["reference"] = case_content["reference"]
            if "answer" in run_content:
                actual["answer"] = run_content["answer"]
            rows.append({"case": identity, "inputs": inputs, "expected": expected, "actual": actual,
                         "scores": _feedback(run, reviews, records.get(run_id), judgments.get(run_id)),
                         "reviews": reviews, "run": run})
    finally:
        con.close()
        if trace_con is not None:
            trace_con.close()
    if len(variants) != 1:
        raise EvaluationContractError("an experiment must contain a single variant")
    project_metadata: dict[str, object] = {"suite": suite_id, "variant": next(iter(variants)),
                                           "content": content_mode, "reproducibility": "not_recorded",
                                           "time_semantics": "import_time" if import_time else "original_execution_time"}
    if variant_path is not None:
        variant = ControlledVariant.from_dict(_json_file(variant_path))
        if variant.variant_id != next(iter(variants)):
            raise EvaluationContractError("declared variant differs from selected runs")
        project_metadata["declared_variant_configuration"] = variant.to_dict()
        project_metadata["variant_provenance"] = "provided_file_not_independently_verified"
    if manifest_path is not None:
        manifest = _json_file(manifest_path)
        if not isinstance(manifest, dict) or manifest.get("suite") != suite.to_dict():
            raise EvaluationContractError("experiment manifest suite differs from export")
        manifest_runs = {item.get("run_id") for item in manifest.get("runs", []) if isinstance(item, dict)}
        if not set(run_ids).issubset(manifest_runs):
            raise EvaluationContractError("export contains runs absent from experiment manifest")
        if not isinstance(manifest.get("variant"), dict) or manifest["variant"].get("variant_id") != next(iter(variants)):
            raise EvaluationContractError("experiment manifest variant differs from export")
        project_metadata.update({"reproducibility": manifest.get("status"), "git_commit": manifest.get("git_commit"),
                                 "freeze_id": manifest.get("freeze_id"), "judge_version": manifest.get("judge_version"),
                                 "variant_configuration": manifest.get("variant"),
                                 "runtime_settings": manifest.get("runtime_settings"),
                                 "router_settings": manifest.get("router_settings")})
    serialized = json.dumps({"rows": [{k: v for k, v in row.items() if k not in ("run", "reviews")}
                                       for row in rows], "metadata": project_metadata}, ensure_ascii=False)
    for name, value in os.environ.items():
        if len(value) >= 8 and any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            if value in serialized:
                raise EvaluationContractError("export data contains a configured secret")
    if key in serialized:
        raise EvaluationContractError("export data contains the LangSmith API key")
    started = (datetime.now(timezone.utc) if import_time else
               min(datetime.fromisoformat(row["run"].started_at) for row in rows).astimezone(timezone.utc)).isoformat()
    ended = (started if import_time else
             max(datetime.fromisoformat(row["run"].completed_at) for row in rows).astimezone(timezone.utc).isoformat())
    ledger = ExportLedger(ledger_path)
    try:
        previous = ledger.con.execute("SELECT state,dataset_id,project_id FROM external_exports WHERE experiment=?",
                                      (experiment,)).fetchone()
        if previous:
            if previous[0] == "completed":
                return {"status": "already_synced", "dataset_id": previous[1], "experiment_id": previous[2]}
            raise EvaluationContractError("export already attempted; inspect LangSmith and the local ledger before retrying")
        dataset_row = ledger.con.execute("SELECT dataset_id FROM external_datasets WHERE suite=?", (dataset_key,)).fetchone()
        dataset_id = str(dataset_row[0]) if dataset_row else str(uuid.uuid4())
        if dataset_row is None:
            ledger.con.execute("INSERT INTO external_datasets VALUES (?,?)", (dataset_key, dataset_id))
        for row in rows:
            inputs_json = json.dumps(row["inputs"], ensure_ascii=False, sort_keys=True)
            outputs_json = json.dumps(row["expected"], ensure_ascii=False, sort_keys=True)
            existing = ledger.con.execute("SELECT example_id,inputs_json,outputs_json FROM external_examples "
                                          "WHERE suite=? AND case_identity=?", (dataset_key, row["case"])).fetchone()
            if existing:
                if existing[1] != inputs_json or existing[2] != outputs_json:
                    raise EvaluationContractError("same Case version has different content; create a new version")
                row["example_id"] = str(existing[0])
            else:
                row["example_id"] = str(uuid.uuid4())
                ledger.con.execute("INSERT INTO external_examples VALUES (?,?,?,?,?)",
                                   (dataset_key, row["case"], row["example_id"], inputs_json, outputs_json))
            conflict = ledger.con.execute(
                "SELECT e.experiment FROM external_exports e JOIN external_runs r ON r.experiment=e.experiment "
                "WHERE e.suite=? AND e.started_at=? AND r.example_id=? AND e.state != 'rejected'",
                (dataset_key, started, row["example_id"]),
            ).fetchone()
            if conflict:
                raise EvaluationContractError("LangSmith external API cannot import the same Example with the same "
                                              "experiment start time; original times were preserved")
        if import_time:
            # The endpoint requires a non-empty time interval. Both times describe this
            # actual import preparation, while the original execution times stay in outputs.
            ended = datetime.now(timezone.utc).isoformat()
        payload_rows = []
        for row in rows:
            run = row["run"]
            remote_error = run.exception_type or (f"Trivae termination: {run.terminal_status}"
                                                   if run.terminal_status != "completed" else None)
            payload_rows.append({"row_id": row["example_id"], "inputs": row["inputs"],
                                 "expected_outputs": row["expected"], "actual_outputs": row["actual"],
                                 "evaluation_scores": row["scores"], "start_time": started if import_time else run.started_at,
                                 "end_time": ended if import_time else run.completed_at,
                                 "run_name": row["case"], "error": remote_error,
                                 "run_metadata": {"local_run_id": run.run_id, "trace_id": run.trace_id,
                                                  "variant": run.variant_id}})
        body = {"dataset_id": dataset_id, "dataset_name": "Trivae external " + suite_id + " (" + content_mode + ")",
                "experiment_name": experiment, "experiment_start_time": started, "experiment_end_time": ended,
                "experiment_metadata": project_metadata, "results": payload_rows}
        ledger.con.execute("INSERT INTO external_exports VALUES (?,?,?,?,?,?)",
                           (experiment, dataset_key, "pending", dataset_id, None, started))
        for row in rows:
            ledger.con.execute("INSERT INTO external_runs VALUES (?,?,?,NULL)",
                               (experiment, row["run"].run_id, row["example_id"]))
        ledger.con.commit()
        try:
            with httpx.Client(timeout=30, transport=transport) as client:
                response = client.post(base + "/api/v1/datasets/upload-experiment", json=body,
                                       headers={"x-api-key": key})
            response.raise_for_status()
            result = response.json()
            remote_dataset = str(result["dataset"]["id"])
            project_id = str(result["experiment"]["id"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            state = "rejected" if status is not None and 400 <= status < 500 and status != 408 else "unknown"
            ledger.con.execute("UPDATE external_exports SET state=? WHERE experiment=?", (state, experiment))
            ledger.con.commit()
            raise EvaluationContractError(f"LangSmith upload failed or outcome unknown (type={type(exc).__name__}, "
                                          f"http_status={status}); inspect remote and local ledger") from exc
        ledger.con.execute("UPDATE external_exports SET state='completed',dataset_id=?,project_id=? WHERE experiment=?",
                           (remote_dataset, project_id, experiment))
        for row in rows:
            for review in row["reviews"]:
                for score in _review_feedback(review):
                    ledger.con.execute("INSERT INTO external_reviews VALUES (?,?,?,NULL,'completed')",
                                       (experiment, review.review_id, score["key"]))
        ledger.con.commit()
        return {"status": "synced", "dataset_id": remote_dataset, "experiment_id": project_id,
                "experiment": experiment, "runs": len(rows), "remote_run_ids": "resolve_after_ingestion"}
    finally:
        ledger.close()


def resolve_remote(*, ledger_path: Path, experiment: str, api_key: str | None = None,
                   transport: httpx.BaseTransport | None = None) -> dict[str, object]:
    """Resolve remote run IDs through the documented v2 experiment-runs query."""
    ledger = ExportLedger(ledger_path)
    try:
        export = ledger.con.execute("SELECT dataset_id,project_id,state FROM external_exports WHERE experiment=?",
                                    (experiment,)).fetchone()
        if export is None or export[2] != "completed":
            raise EvaluationContractError("completed LangSmith export not found")
        base, key = _connection(api_key)
        examples = []
        try:
            with httpx.Client(timeout=30, transport=transport) as client:
                cursor = None
                while True:
                    body: dict[str, Any] = {"experiment_ids": [export[1]], "page_size": 100,
                                            "selects": ["ID", "OUTPUTS", "REFERENCE_EXAMPLE_ID"]}
                    if cursor:
                        body["cursor"] = cursor
                    response = client.post(f"{base}/api/v2/datasets/{export[0]}/experiment-runs",
                                           json=body, headers={"x-api-key": key})
                    response.raise_for_status()
                    page = response.json()
                    examples.extend(page["items"])
                    cursor = page.get("next_cursor")
                    if not cursor:
                        break
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise EvaluationContractError(f"LangSmith result lookup failed (type={type(exc).__name__})") from exc
        matched = 0
        for example in examples:
            for run in example.get("runs", []):
                local_id = (run.get("outputs") or {}).get("local_run_id")
                remote_id = run.get("id")
                if not isinstance(local_id, str) or not isinstance(remote_id, str):
                    continue
                cursor = ledger.con.execute("UPDATE external_runs SET remote_run_id=? WHERE experiment=? "
                                            "AND local_run_id=? AND example_id=?",
                                            (remote_id, experiment, local_id, example.get("id")))
                matched += cursor.rowcount
        ledger.con.commit()
        total = ledger.con.execute("SELECT count(*) FROM external_runs WHERE experiment=?", (experiment,)).fetchone()[0]
        return {"status": "resolved" if matched == total else "pending_ingestion", "resolved": matched, "total": total}
    finally:
        ledger.close()


def sync_review(*, evaluation_db: Path, ledger_path: Path, experiment: str, review_id: str,
                api_key: str | None = None, transport: httpx.BaseTransport | None = None) -> dict[str, object]:
    """Append a later local review to a resolved LangSmith run, once per review axis."""
    con = _read_db(evaluation_db)
    try:
        row = con.execute("SELECT payload_json FROM evaluation_reviews WHERE review_id=?", (review_id,)).fetchone()
        if row is None:
            raise EvaluationContractError("review not found")
        review = EvaluationReview.from_dict(json.loads(row[0]))
    finally:
        con.close()
    scores = _review_feedback(review)
    if not scores:
        raise EvaluationContractError("review has no exportable axis assessments")
    base, key = _connection(api_key)
    ledger = ExportLedger(ledger_path)
    try:
        mapping = ledger.con.execute(
            "SELECT r.remote_run_id,e.project_id FROM external_runs r JOIN external_exports e "
            "ON e.experiment=r.experiment WHERE r.experiment=? AND r.local_run_id=? AND e.state='completed'",
            (experiment, review.run_id),
        ).fetchone()
        if mapping is None or mapping[0] is None:
            raise EvaluationContractError("remote run mapping is unavailable; run langsmith-resolve first")
        uploaded = 0
        for score in scores:
            existing = ledger.con.execute(
                "SELECT state FROM external_reviews WHERE experiment=? AND review_id=? AND feedback_key=?",
                (experiment, review_id, score["key"]),
            ).fetchone()
            if existing:
                if existing[0] != "completed":
                    raise EvaluationContractError("feedback outcome unknown; inspect LangSmith and ledger")
                continue
            feedback_id = str(uuid.uuid4())
            ledger.con.execute("INSERT INTO external_reviews VALUES (?,?,?,?,?)",
                               (experiment, review_id, score["key"], feedback_id, "pending"))
            ledger.con.commit()
            try:
                body = {"run_id": mapping[0], "session_id": mapping[1], "id": feedback_id,
                        "feedback_source": {"type": "api", "metadata": {}}, **score}
                with httpx.Client(timeout=30, transport=transport) as client:
                    response = client.post(base + "/feedback", json=body, headers={"x-api-key": key})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise EvaluationContractError(f"LangSmith feedback failed or outcome unknown (type={type(exc).__name__})") from exc
            ledger.con.execute("UPDATE external_reviews SET state='completed' WHERE experiment=? AND review_id=? "
                               "AND feedback_key=?", (experiment, review_id, score["key"]))
            ledger.con.commit()
            uploaded += 1
        return {"status": "synced" if uploaded else "already_synced", "axes_uploaded": uploaded}
    finally:
        ledger.close()
