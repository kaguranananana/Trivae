"""Replay Z Code's saved ANN pools through production range recovery, without embeddings.

The master databases are opened read-only. This isolates message selection from ANN,
query generation and answer generation. Outputs contain private source IDs and belong
in the ignored data/evaluation directory, not in the public research directory.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import types
from collections import Counter
from dataclasses import fields
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from trivae.capabilities.contracts import ExecutionScope, ToolEnvelope
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.semantic.contracts import SemanticIndexCandidate, SemanticIndexIdentity, SemanticQuery
from trivae.retrieval.semantic.retrieval import SemanticRetrieval

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = Path(__file__).resolve().parent
STUDY = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
FROZEN = ROOT / "data/evaluation/frozen-20261028-validated"


def baseline_class(ref: str):
    source = subprocess.run(
        ["git", "show", f"{ref}:src/trivae/retrieval/semantic/retrieval.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    module = types.ModuleType("trivae.retrieval.semantic._research_baseline")
    import sys

    sys.modules[module.__name__] = module
    exec(compile(source, f"{ref}:retrieval.py", "exec"), module.__dict__)
    return module.SemanticRetrieval


class SavedPool:
    def __init__(self, state, candidates):
        self.persisted_state = state
        self.candidates = candidates

    def state(self):
        return self.persisted_state

    def dense_search(self, identity, vector, limit, **scope):
        assert identity == self.persisted_state.identity
        assert limit >= len(self.candidates)
        return self.candidates


class NoEmbedding:
    def __init__(self, identity):
        self.identity = identity

    def embed_query(self, text):
        # SavedPool does not consume this sentinel: no new ANN or embedding work.
        return ()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="003642b3")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-projection", action="store_true", help="Compare old/new Host on the same ranked envelope")
    args = parser.parse_args()
    old_class = baseline_class(args.baseline_ref)
    calls = json.loads((RESEARCH / "rounds/outputs/replay-calls.json").read_text())
    study = json.loads((STUDY / "study-data.json").read_text())
    checklist = json.loads((STUDY / "fact-checklist.json").read_text())
    maps = {}
    for arm in ("a", "b"):
        for item in json.loads((STUDY / f"source-map-{arm}.json").read_text())["selected"]:
            maps[item["run_id"]] = item["source"]
    requests = {}
    runtime_calls = {}
    for cid, case in study["cases"].items():
        for arm, runs in case["runs"].items():
            for idx, run in enumerate(runs):
                trace = (run["trace"]["trace_path"] if run["source"] == "new-agent-run"
                         else maps[run["run_id"]]["trace_record"])
                events = json.loads((ROOT / trace).read_text())["timeline"]
                requests[f"{arm}{idx}-{cid}"] = [
                    e["payload"]["request"] for e in events
                    if e["operation"] == "tool.call.started" and e["payload"]["tool_name"] == "semantic_search"
                ]
                completed = {e["payload"]["tool_call_id"]: e["payload"] for e in events
                             if e["operation"] == "runtime.tool.completed"}
                runtime_calls[f"{arm}{idx}-{cid}"] = [
                    completed[e["operation_id"]] for e in events
                    if e["operation"] == "tool.call.started" and e["payload"]["tool_name"] == "semantic_search"
                ]
    repo = SQLiteCanonicalReadRepository(FROZEN / "trivae.sqlite3")
    # The snapshot is immutable; both arms intentionally recover identical ranges.
    repo.read_message_range = lru_cache(maxsize=None)(repo.read_message_range)
    sem = sqlite3.connect(f"file:{FROZEN}/trivae.semantic.sqlite3?mode=ro", uri=True)
    sem.row_factory = sqlite3.Row
    row = dict(sem.execute("SELECT * FROM semantic_index_state WHERE state_id=1").fetchone())
    identity = SemanticIndexIdentity.from_dict(json.loads(row.pop("identity_json")))
    state = SimpleNamespace(**row, identity=identity)
    provider = NoEmbedding(identity.embedding)
    evidence_by_case = {}
    corrections = []
    for case in checklist["cases"]:
        targets = set()
        for criterion in case["criteria"]:
            for mid in criterion["evidence"]:
                if repo.read_message_by_id(mid) is not None:
                    targets.add(mid)
                else:
                    # Explicitly record the known GT group-prefix error; no fuzzy ID matches.
                    source_id = mid.split(":")[2].split("#")[0]
                    found = repo._connection.execute(
                        "SELECT internal_message_id FROM messages WHERE source_message_id=?", (source_id,),
                    ).fetchall()
                    assert len(found) == 1, (mid, found)
                    corrected = found[0][0] + ("#" + mid.split("#", 1)[1] if "#" in mid else "")
                    assert repo.read_message_by_id(corrected) is not None, corrected
                    targets.add(corrected)
                    corrections.append({"original": mid, "resolved": corrected})
        evidence_by_case[case["case_id"]] = targets
    stats = Counter()
    output = []
    positions = Counter()
    host_stats = Counter()
    host_rows = []
    if args.host_projection:
        from probe_host_budget import baseline_module

        import trivae.query.evidence as new_host

        old_host = baseline_module()
    for call in calls:
        if call["tool"] != "semantic":
            continue
        label = call["label"]
        request = requests[label][positions[label]]
        runtime = runtime_calls[label][positions[label]]
        positions[label] += 1
        candidates = []
        for saved in call["pool_rows"]:
            chunk = dict(sem.execute("SELECT * FROM semantic_chunks WHERE chunk_id=?", (saved["chunk_id"],)).fetchone())
            chunk.update(distance=saved["distance"], dense_rank=saved["dense_rank"])
            candidates.append(SemanticIndexCandidate(**{f.name: chunk[f.name] for f in fields(SemanticIndexCandidate)}))
        store = SavedPool(state, tuple(candidates))
        query_fields = {f.name for f in fields(SemanticQuery)}
        qargs = {k: v for k, v in request.items() if k in query_fields and k != "time_range"}
        qargs.update(start_timestamp=call["resolved_start"], end_timestamp=call["resolved_end"])
        query = SemanticQuery(**qargs)
        old = old_class(repo, store, provider, database_identity=identity.database_identity).search(query)
        new = SemanticRetrieval(repo, store, provider, database_identity=identity.database_identity).search(query)
        old_ids = {m.internal_message_id for m in old.expanded_messages}
        new_ids = {m.internal_message_id for m in new.expanded_messages}
        assert old_ids == set(call["expanded_ids"]), label
        assert [h.chunk_id for h in old.hits] == call["accepted_chunk_ids"], label
        assert old.hits == new.hits, "Candidate must not change selected chunks"
        assert len(new_ids) <= 100
        gt = evidence_by_case[call["case"]]
        if args.host_projection:
            envelope = ToolEnvelope(
                status="partial" if new.partial else "ok", data=new,
                meta={"truncated": new.truncated, "total_hits": new.total_hits,
                      "returned_messages": new.returned_messages}, error=None,
            )
            visible_by_arm = {}
            metrics_by_arm = {}
            projection_errors = {}
            budget = runtime["tool_result_budget"]["effective_per_call_tool_result_budget"]
            for arm_name, module in [("old", old_host), ("new", new_host)]:
                record = module.build_tool_result_record(
                    run_id=runtime["run_id"], tool_call_id=runtime["tool_call_id"],
                    tool_result_id=f"{runtime['tool_call_id']}/result", tool_name="semantic_search",
                    envelope=envelope, scope=ExecutionScope(max_results=100),
                )
                try:
                    payload = module.project_tool_result_for_model(envelope, record, token_budget=budget)
                except module.ToolResultProjectionError as exc:
                    # Some recorded calls had only enough budget for a control error.
                    # Keep this outcome explicit; never treat it as an empty retrieval.
                    projection_errors[arm_name] = str(exc)
                    visible_by_arm[arm_name] = set()
                    continue
                handles = module._projected_source_ids(payload["data"])
                visible_by_arm[arm_name] = {
                    item.message.internal_message_id for i, item in enumerate(record.message_items)
                    if f"m{record.model_scope_id}-{i + 1}" in handles
                }
                metrics_by_arm[arm_name] = payload["model_projection"]
            before, after = visible_by_arm["old"], visible_by_arm["new"]
            host_stats["calls"] += 1
            host_stats["comparable_calls"] += not projection_errors
            host_stats["old_projection_errors"] += "old" in projection_errors
            host_stats["new_projection_errors"] += "new" in projection_errors
            host_stats["changed_calls"] += before != after
            host_stats["old_gt_occurrences"] += len(gt & before)
            host_stats["new_gt_occurrences"] += len(gt & after)
            host_stats["gained_gt_occurrences"] += len((gt & after) - before)
            host_stats["lost_gt_occurrences"] += len((gt & before) - after)
            host_rows.append({"label": label, "budget": budget, "old_ids": sorted(before), "new_ids": sorted(after),
                              "gained_gt": sorted((gt & after) - before), "lost_gt": sorted((gt & before) - after),
                              "metrics": metrics_by_arm, "projection_errors": projection_errors})
        cores = []
        for hit in old.hits:
            candidate = next(c for c in candidates if c.chunk_id == hit.chunk_id)
            core = repo.read_message_range(hit.session_id, hit.start_message_id, hit.end_message_id, candidate.message_count)
            ids = {m.internal_message_id for m in core}
            cores.append({"dense_rank": hit.dense_rank, "chunk_id": hit.chunk_id,
                          "size": len(ids), "old_kept": len(ids & old_ids), "new_kept": len(ids & new_ids),
                          "gt_in_core": sorted(gt & ids)})
        stats["calls"] += 1
        stats["changed_calls"] += old_ids != new_ids
        stats["old_zero_message_chunks"] += sum(c["old_kept"] == 0 for c in cores)
        stats["new_zero_message_chunks"] += sum(c["new_kept"] == 0 for c in cores)
        stats["old_top_rank_zero"] += min(cores, key=lambda c: c["dense_rank"])["old_kept"] == 0
        stats["new_top_rank_zero"] += min(cores, key=lambda c: c["dense_rank"])["new_kept"] == 0
        stats["old_gt_occurrences"] += len(gt & old_ids)
        stats["new_gt_occurrences"] += len(gt & new_ids)
        stats["gained_gt_occurrences"] += len((gt & new_ids) - old_ids)
        stats["lost_gt_occurrences"] += len((gt & old_ids) - new_ids)
        output.append({"label": label, "query": call["query"], "cores": cores,
                       "old_ids": sorted(old_ids), "new_ids": sorted(new_ids),
                       "gt_old": sorted(gt & old_ids), "gt_new": sorted(gt & new_ids),
                       "gained_gt": sorted((gt & new_ids) - old_ids), "lost_gt": sorted((gt & old_ids) - new_ids),
                       "literal_old": list(old.metadata.details["literal_message_ids"]),
                       "literal_new": list(new.metadata.details["literal_message_ids"])})
        print(f"{stats['calls']}/51 {label} gt={len(gt & old_ids)}->{len(gt & new_ids)}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump({"baseline_ref": args.baseline_ref, "stats": dict(stats), "gt_corrections": corrections,
                   "calls": output, "host_stats": dict(host_stats), "host_calls": host_rows}, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(stats), indent=2))
    if args.host_projection:
        print("Host comparison:", json.dumps(dict(host_stats), indent=2))


if __name__ == "__main__":
    main()
