"""Recheck private capability references, search records, and saved message context."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from trivae.evaluation.capability_audit import audit_evidence
from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError, EvaluationSuite


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify(bundle: Path, suite_path: Path, freeze_path: Path, database: Path) -> dict[str, Any]:
    questions = _read(bundle / "questions-frozen.json")
    gt = _read(bundle / "ground-truth-v1.json")
    packet = _read(bundle / "evidence.json")
    initial = _read(bundle / "search-initial.json")
    review = _read(bundle / "search-review.json")
    revisions = _read(bundle / "revision-log.json")
    suite = EvaluationSuite.from_json(suite_path)
    cases = {}
    for path in (bundle / "cases").glob("*.json"):
        case = EvaluationCaseBundle.from_json(path)
        cases[case.identity] = case
    source_audit = audit_evidence(suite=suite, cases=cases, packet=packet,
                                  freeze=_read(freeze_path), database=database)
    if (gt["suite_id"], gt["suite_version"], gt["gt_version"], gt["as_of"]) != (
        suite.suite_id, suite.version, packet["gt_version"], questions["as_of"]
    ):
        raise EvaluationContractError("suite, GT, packet or as-of identity differs")
    times = [datetime.fromisoformat(x) for x in (
        questions["frozen_at"], initial["searched_at"], review["review_search_completed_at"], gt["created_at"]
    )]
    if not (times[0] <= times[1] <= times[2] <= times[3]):
        raise EvaluationContractError("question freeze, searches and GT chronology differs")
    expected = [ref.case_id for ref in suite.case_references]
    collections = [questions["cases"], gt["cases"], packet["cases"], initial["cases"], review["cases"],
                   revisions["revisions"]]
    for values in collections:
        if [item["case_id"] for item in values] != expected:
            raise EvaluationContractError("bundle case order or identity differs from suite")
    context_rows = source_rows = 0
    unique_sources: set[str] = set()
    sessions: set[str] = set()
    details = []
    con = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        for q, truth, evidence, first, second in zip(*collections[:5], strict=True):
            case = cases[f"{q['case_id']}@v{q['version']}"]
            if case.query != q["query"] or truth["query"] != q["query"]:
                raise EvaluationContractError("frozen question differs from case or GT")
            if case.time_context is None or case.time_context.get("as_of") != questions["as_of"]:
                raise EvaluationContractError("case as-of differs from frozen question set")
            if f"gt:{gt['gt_version']}" not in case.suite_tags:
                raise EvaluationContractError("case ground truth identity differs")
            if not truth["user_need"] or not truth["must_answer"] or not truth["evidence_limitations"]:
                raise EvaluationContractError("GT need, requirements or uncertainty is missing")
            if not truth["reasonable_other_answers"] or not truth["review"]["revision_reason"]:
                raise EvaluationContractError("GT alternatives or review record is missing")
            if truth["evidence_status"] not in ("充分", "部分充分", "未检得相关证据"):
                raise EvaluationContractError("GT evidence status is invalid")
            first_terms = {item["fts_expression"] for item in first["searches"]}
            second_terms = {item["fts_expression"] for item in second["searches"]}
            if not first_terms or not second_terms - first_terms:
                raise EvaluationContractError("independent review search expressions missing")
            facts = truth["candidate_facts"]
            case_facts = [finding.expected_semantics for finding in case.reference_findings
                          if finding.criterion == "capability.reference-example"]
            if (case_facts != [fact["claim"] for fact in facts]
                    or case.critical_requirements != (truth["must_answer"],)
                    or truth["evidence_limitations"] not in case.uncertainty_constraints):
                raise EvaluationContractError("case and GT scoring semantics differ")
            fact_ids: set[str] = set()
            for fact in facts:
                if not fact["claim"] or not fact["epistemic_type"] or not fact["message_ids"]:
                    raise EvaluationContractError("GT fact is missing its source or information type")
                fact_ids.update(fact["message_ids"])
            records = evidence["evidence"]
            if fact_ids != {item["internal_message_id"] for item in records}:
                raise EvaluationContractError("GT facts and evidence packet differ")
            if truth["evidence_status"] == "未检得相关证据" and records:
                raise EvaluationContractError("no-evidence status contains reference sources")
            for record in records:
                table = "forwarded_messages" if record["kind"] == "forwarded" else "messages"
                row = con.execute(f"SELECT reply_to_source_message_id FROM {table} WHERE internal_message_id=?",
                                  (record["internal_message_id"],)).fetchone()
                if row is None or row[0] != record["reply_to_source_message_id"]:
                    raise EvaluationContractError("source reply relationship differs")
                session = con.execute("SELECT name FROM chat_sessions WHERE session_id=?",
                                      (record["session_id"],)).fetchone()
                if session is None or session[0] != record["session_name"]:
                    raise EvaluationContractError("source session name differs")
                if record["kind"] == "forwarded":
                    parent = record["parent_message_id"]
                    exists = con.execute("SELECT 1 FROM messages WHERE internal_message_id=? UNION ALL "
                                         "SELECT 1 FROM forwarded_messages WHERE internal_message_id=?",
                                         (parent, parent)).fetchone()
                    if exists is None:
                        raise EvaluationContractError("forwarded parent is missing")
                for context in record["context"]:
                    row = con.execute("SELECT session_id,timestamp,sender_user_id,content_text,reply_to_source_message_id "
                                      "FROM messages WHERE internal_message_id=?", (context["internal_message_id"],)).fetchone()
                    expected_row = tuple(context[k] for k in ("session_id", "timestamp", "sender_user_id",
                                                              "content_text", "reply_to_source_message_id"))
                    if row != expected_row:
                        raise EvaluationContractError("saved context differs from frozen database")
                    context_rows += 1
                source_rows += 1
                unique_sources.add(record["internal_message_id"])
                sessions.add(record["session_id"])
            details.append({"case": case.identity, "sources": len(records), "facts": len(facts),
                            "initial_queries": len(first["searches"]), "review_queries": len(second["searches"]),
                            "distinct_review_queries": len(second_terms - first_terms),
                            "evidence_status": truth["evidence_status"],
                            "scoring_eligibility": truth["scoring_eligibility"]})
    finally:
        con.close()
    return {"status": "passed", "cases_checked": len(details), "source_occurrences": source_rows,
            "distinct_sources": len(unique_sources), "sessions": len(sessions), "context_rows_checked": context_rows,
            "source_audit": source_audit, "cases": details,
            "limitations": "Deterministic checks do not establish semantic support, search completeness, or current external validity."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.bundle_dir, args.suite, args.freeze_manifest, args.database)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
