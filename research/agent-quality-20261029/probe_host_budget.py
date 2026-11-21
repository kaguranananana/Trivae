"""Freeze one real semantic envelope, then compare Host clipping at the recorded budget.

First run uses EvaluationWorkspace and local embeddings; subsequent runs reuse the
trusted local envelope pickle. No Agent/Judge requests are made.
"""
from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path

import trivae.query.evidence as candidate
from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope, SemanticSearchInput
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation.workspace import EvaluationWorkspace

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/evaluation/agent-quality-codex-20261030"
TRACE_ID = "trace-5ad00d5575be431b9c5d12f61e8fdb84"
TARGETS = {"qq:1098836554:7684554100525131775", "qq:1040412855:7700052583306734879"}


def baseline_module():
    source = subprocess.run(["git", "show", "e5f53ac4:src/trivae/query/evidence.py"], cwd=ROOT,
                            check=True, capture_output=True, text=True).stdout
    module = types.ModuleType("trivae.query._research_baseline_evidence")
    sys.modules[module.__name__] = module
    exec(compile(source, "e5f53ac4:evidence.py", "exec"), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    trace = next(json.loads(p.read_text()) for p in (OUT / "candidate-08-complete/traces").glob("*.json")
                 if json.loads(p.read_text())["trace_id"] == TRACE_ID)
    request = next(e["payload"]["request"] for e in trace["timeline"]
                   if e["operation"] == "tool.call.started" and e["payload"]["tool_name"] == "semantic_search")
    runtime = next(e["payload"] for e in trace["timeline"]
                   if e["operation"] == "runtime.tool.completed" and e["payload"]["tool_name"] == "semantic_search")
    cache = OUT / "host-budget-envelope.pickle"
    scope = ExecutionScope(max_results=100)
    if cache.exists():
        with cache.open("rb") as stream:
            envelope = pickle.load(stream)
    else:
        with EvaluationWorkspace.create(ROOT / "data/evaluation/frozen-20261028-validated/freeze.json") as workspace:
            with create_application(workspace.database_path) as app:
                envelope = app.invoke_tool("semantic_search", SemanticSearchInput(**request), scope)
                assert envelope.data is not None, envelope.error
                with cache.open("xb") as stream:
                    pickle.dump(envelope, stream)
                (OUT / "host-budget-envelope.json").write_text(json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2))
            workspace.mark_results_persisted()
    budget = runtime["tool_result_budget"]["effective_per_call_tool_result_budget"]
    rows = []
    # Reconstruct only the selected primary order from frozen canonical ranges.
    # Content, selected IDs, hits, metadata and the recorded budget stay identical.
    repo = SQLiteCanonicalReadRepository(ROOT / "data/evaluation/frozen-20261028-validated/trivae.sqlite3")
    primary_ids = set(envelope.data.primary_message_ids)
    priority = dict.fromkeys(envelope.data.metadata.details["literal_message_ids"])
    for hit in envelope.data.hits:
        for message in repo.read_message_range(hit.session_id, hit.start_message_id, hit.end_message_id, 1000):
            if message.internal_message_id in primary_ids:
                priority[message.internal_message_id] = None
    assert set(priority) == primary_ids
    ranked_envelope = replace(envelope, data=replace(envelope.data, primary_message_ids=tuple(priority)))
    for name, module in [("baseline", baseline_module()), ("candidate", candidate)]:
        selected_envelope = envelope if name == "baseline" else ranked_envelope
        record = module.build_tool_result_record(
            run_id=runtime["run_id"], tool_call_id=runtime["tool_call_id"],
            tool_result_id=f"{runtime['tool_call_id']}/result", tool_name="semantic_search", envelope=selected_envelope, scope=scope,
        )
        projected = module.project_tool_result_for_model(selected_envelope, record, token_budget=budget)
        visible = module._projected_source_ids(projected["data"])
        ids = {item.message.internal_message_id for i, item in enumerate(record.message_items)
               if f"m{record.model_scope_id}-{i + 1}" in visible}
        rows.append({"arm": name, "projected_ids": sorted(ids), "gt_visible": sorted(ids & TARGETS),
                     "projection": projected, "metrics": projected["model_projection"]})
    body_ids = {m.internal_message_id for m in envelope.data.expanded_messages}
    result = {"source_trace": TRACE_ID, "request": request, "token_budget": budget,
              "gt_in_capability": sorted(body_ids & TARGETS),
              "recorded_projection": {k: runtime.get(k) for k in ["projected_messages", "omitted_hit_messages"]},
              "rows": rows}
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"gt_in_capability": result["gt_in_capability"], "budget": budget,
                      "rows": [{"arm": r["arm"], "gt_visible": r["gt_visible"], "metrics": r["metrics"]} for r in rows]}, indent=2))


if __name__ == "__main__":
    main()
