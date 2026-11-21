"""Frozen-pool capacity and Host budget replay; no model calls, no master writes.

Private inputs and outputs remain under ignored data/evaluation. Run from repo root:
uv run python research/budget-capacity-20261031/offline.py --output-dir <new-dir>
"""
from __future__ import annotations

import argparse
import json
import pickle
import sqlite3
import sys
from collections import Counter
from dataclasses import fields, replace
from functools import lru_cache
from pathlib import Path
from statistics import median
from time import perf_counter
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / "research/agent-quality-20261029"
sys.path.insert(0, str(HISTORY))
from replay_semantic_capacity import NoEmbedding, SavedPool  # noqa: E402

from trivae.capabilities.contracts import ExecutionScope, ToolEnvelope  # noqa: E402
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository  # noqa: E402
from trivae.query.evidence import (  # noqa: E402
    ToolResultProjectionError,
    _projected_source_ids,
    build_tool_result_record,
    project_tool_result_for_model,
)
from trivae.retrieval.semantic.contracts import (  # noqa: E402
    SemanticIndexCandidate,
    SemanticIndexIdentity,
    SemanticQuery,
)
from trivae.retrieval.semantic.retrieval import SemanticRetrieval  # noqa: E402
from trivae.retrieval.structured import message_sort_key  # noqa: E402

FROZEN = ROOT / "data/evaluation/frozen-20261028-validated"
STUDY = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
OLD = ROOT / "data/evaluation/agent-quality-codex-20261030"


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def targets(repo):
    result, corrections = {}, []
    for case in json.loads((STUDY / "fact-checklist.json").read_text())["cases"]:
        ids = set()
        for criterion in case["criteria"]:
            for mid in criterion["evidence"]:
                if repo.read_message_by_id(mid) is None:
                    source = mid.split(":")[2].split("#")[0]
                    found = repo._connection.execute(
                        "SELECT internal_message_id FROM messages WHERE source_message_id=?", (source,),
                    ).fetchall()
                    assert len(found) == 1, mid
                    resolved = found[0][0] + ("#" + mid.split("#", 1)[1] if "#" in mid else "")
                    assert repo.read_message_by_id(resolved) is not None
                    corrections.append({"original": mid, "resolved": resolved})
                    mid = resolved
                ids.add(mid)
        result[case["case_id"]] = ids
    return result, corrections


def recorded_requests():
    maps = {}
    for arm in ("a", "b"):
        for item in json.loads((STUDY / f"source-map-{arm}.json").read_text())["selected"]:
            maps[item["run_id"]] = item["source"]
    result = {}
    for cid, case in json.loads((STUDY / "study-data.json").read_text())["cases"].items():
        for arm, runs in case["runs"].items():
            for idx, run in enumerate(runs):
                path = (run["trace"]["trace_path"] if run["source"] == "new-agent-run"
                        else maps[run["run_id"]]["trace_record"])
                timeline = json.loads((ROOT / path).read_text())["timeline"]
                completed = {e["payload"]["tool_call_id"]: e["payload"] for e in timeline
                             if e["operation"] == "runtime.tool.completed"}
                result[f"{arm}{idx}-{cid}"] = [
                    (e["payload"]["request"], completed[e["operation_id"]]) for e in timeline
                    if e["operation"] == "tool.call.started" and e["payload"]["tool_name"] == "semantic_search"
                ]
    return result


def envelope(result):
    return ToolEnvelope(status="partial" if result.partial else "ok", data=result,
                        meta={"truncated": result.truncated, "total_hits": result.total_hits,
                              "returned_messages": result.returned_messages}, error=None)


def project(env, runtime, budget):
    record = build_tool_result_record(
        run_id=runtime["run_id"], tool_call_id=runtime["tool_call_id"],
        tool_result_id=f"{runtime['tool_call_id']}/result", tool_name="semantic_search",
        envelope=env, scope=ExecutionScope(max_results=100),
    )
    try:
        payload = project_tool_result_for_model(env, record, token_budget=budget)
    except ToolResultProjectionError as exc:
        return {"error": str(exc), "visible_ids": []}
    handles = _projected_source_ids(payload["data"])
    ids = [item.message.internal_message_id for i, item in enumerate(record.message_items)
           if f"m{record.model_scope_id}-{i + 1}" in handles]
    assert len(handles) == len(ids)
    assert payload["model_projection"]["estimated_tokens"] <= budget
    return {"metrics": payload["model_projection"], "visible_ids": ids,
            "json_bytes": len(json.dumps(payload, ensure_ascii=False).encode())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    repo = SQLiteCanonicalReadRepository(FROZEN / "trivae.sqlite3")
    # Frozen canonical range reads are identical across all three arms. Cache only
    # these immutable reads; elapsed time is descriptive, not an arm speed comparison.
    repo.read_message_range = lru_cache(maxsize=None)(repo.read_message_range)
    sem = sqlite3.connect(f"file:{FROZEN}/trivae.semantic.sqlite3?mode=ro", uri=True)
    sem.row_factory = sqlite3.Row
    row = dict(sem.execute("SELECT * FROM semantic_index_state WHERE state_id=1").fetchone())
    identity = SemanticIndexIdentity.from_dict(json.loads(row.pop("identity_json")))
    state = SimpleNamespace(**row, identity=identity)
    gt, corrections = targets(repo)
    requests, positions = recorded_requests(), Counter()
    calls = json.loads((HISTORY / "rounds/outputs/replay-calls.json").read_text())
    a_rows, b_rows, saved = [], [], []
    for call in calls:
        if call["tool"] != "semantic":
            continue
        label = call["label"]
        request, runtime = requests[label][positions[label]]
        positions[label] += 1
        candidates = []
        for item in call["pool_rows"]:
            chunk = dict(sem.execute("SELECT * FROM semantic_chunks WHERE chunk_id=?", (item["chunk_id"],)).fetchone())
            chunk.update(distance=item["distance"], dense_rank=item["dense_rank"])
            candidates.append(SemanticIndexCandidate(**{f.name: chunk[f.name] for f in fields(SemanticIndexCandidate)}))
        qargs = {k: v for k, v in request.items() if k in {f.name for f in fields(SemanticQuery)} and k != "time_range"}
        qargs.update(start_timestamp=call["resolved_start"], end_timestamp=call["resolved_end"])
        query = SemanticQuery(**qargs)
        results = {}
        for cap in (100, 200, 500):
            started = perf_counter()
            result = SemanticRetrieval(repo, SavedPool(state, tuple(candidates)), NoEmbedding(identity.embedding),
                                       database_identity=identity.database_identity, expansion_message_limit=cap).search(query)
            elapsed = (perf_counter() - started) * 1000
            ids = {m.internal_message_id for m in result.expanded_messages}
            assert list(result.expanded_messages) == sorted(result.expanded_messages, key=message_sort_key)
            if results:
                assert result.hits == results[100].hits, "selected chunks must remain identical"
                assert {m.internal_message_id for m in results[100].expanded_messages} <= ids
            results[cap] = result
            core = set(result.primary_message_ids)
            row = {"label": label, "case": call["case"], "capacity": cap, "effective_bound": min(cap, query.limit * 32),
                   "messages": len(ids), "core_messages": len(core), "context_messages": len(ids - core),
                   "gt_ids": sorted(ids & gt[call["case"]]), "gt_all": len(gt[call["case"]]),
                   "partial": result.partial, "truncated": result.truncated, "latency_ms": elapsed,
                   "envelope_bytes": len(json.dumps(envelope(result).to_dict(), ensure_ascii=False).encode()),
                   "selected_chunks": [h.chunk_id for h in result.hits],
                   "expanded_candidate_messages": result.metadata.details["expanded_candidate_messages"],
                   "ids": sorted(ids)}
            a_rows.append(row)
        env = envelope(results[100])
        # Fixed envelope and historical preceding spend. This is a conditional Host replay,
        # not a counterfactual full Run (earlier results could consume different amounts).
        for pool in (32000, 64000, 128000):
            budget = min(128000, runtime["tool_result_budget"]["effective_per_call_tool_result_budget"] + pool - 32000)
            projected = project(env, runtime, budget)
            b_rows.append({"label": label, "case": call["case"], "pool": pool, "call_budget": budget,
                           "gt_ids": sorted(set(projected["visible_ids"]) & gt[call["case"]]), **projected})
        saved.append({"label": label, "case": call["case"], "request": request, "runtime": runtime,
                      "envelopes": {cap: envelope(result) for cap, result in results.items()}})
        print(f"replayed {len(saved)}/51", flush=True)
    with (args.output_dir / "semantic-envelopes.pickle").open("xb") as stream:
        pickle.dump(saved, stream)
    summaries = {}
    for cap in (100, 200, 500):
        rows = [r for r in a_rows if r["capacity"] == cap]
        summaries[str(cap)] = {
            "calls": len(rows), "messages": sum(r["messages"] for r in rows),
            "core_messages": sum(r["core_messages"] for r in rows),
            "context_messages": sum(r["context_messages"] for r in rows),
            "gt_occurrences": sum(len(r["gt_ids"]) for r in rows),
            "unique_gt": len({mid for r in rows for mid in r["gt_ids"]}),
            "truncated_calls": sum(r["truncated"] for r in rows),
            "envelope_bytes": sum(r["envelope_bytes"] for r in rows),
            "median_latency_ms": median(r["latency_ms"] for r in rows),
            "max_messages": max(r["messages"] for r in rows),
        }
    b_summary = {}
    for pool in (32000, 64000, 128000):
        rows = [r for r in b_rows if r["pool"] == pool]
        ok = [r for r in rows if "error" not in r]
        b_summary[str(pool)] = {"calls": len(rows), "projection_errors": len(rows) - len(ok),
                               "gt_occurrences": sum(len(r["gt_ids"]) for r in rows),
                               **{key: sum(r["metrics"][key] for r in ok) for key in
                                  ("estimated_tokens", "projected_messages", "omitted_hit_messages", "omitted_context_messages")},
                               "truncated_calls": sum(r["metrics"]["truncated"] for r in ok)}
    # The original saved R6 envelope predates primary-order propagation. Recover only
    # its selected primary ordering, exactly as the original R6 replay did.
    with (OLD / "host-budget-envelope.pickle").open("rb") as stream:
        original = pickle.load(stream)
    primary = set(original.data.primary_message_ids)
    order = dict.fromkeys(original.data.metadata.details["literal_message_ids"])
    for hit in original.data.hits:
        for message in repo.read_message_range(hit.session_id, hit.start_message_id, hit.end_message_id, 1000):
            if message.internal_message_id in primary:
                order[message.internal_message_id] = None
    assert set(order) == primary
    original = replace(original, data=replace(original.data, primary_message_ids=tuple(order)))
    fixed = [{"pool": pool, **project(original, {"run_id": "saved-r6", "tool_call_id": "saved-r6/tool-call/1"},
                                      min(128000, 10933 + pool - 32000))} for pool in (32000, 64000, 128000)]
    write(args.output_dir / "capacity.json", {"summary": summaries, "gt_corrections": corrections, "calls": a_rows})
    write(args.output_dir / "host.json", {"context_window": 1000000, "per_call_ceiling": 128000,
                                        "method": "fixed envelopes; preserve historical preceding spend and control reservations",
                                        "summary": b_summary, "calls": b_rows, "saved_r6": fixed})
    print(json.dumps({"A": summaries, "B": b_summary}, indent=2))


if __name__ == "__main__":
    main()
