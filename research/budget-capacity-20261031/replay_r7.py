"""Recreate R7's saved first batch and audit the next-batch admission boundary.

The failed second batch's arguments were not persisted (the hook raised first).
Consequently 3/4/7-call boundary probes are declared probes, not the lost batch.
No Prompt candidate or model request is used.
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput
from trivae.evaluation.workspace import EvaluationWorkspace
from trivae.query.runtime.budget import ToolResultBudgetConfig, ToolResultBudgetExhausted
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import (
    _append_runtime_tool_result,
    minimum_budget_stop_tokens,
    reserve_budget_stop_results,
)

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "data/evaluation/agent-quality-codex-20261030"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    trace = json.loads((OLD / "joint-08/traces/trace-001.json").read_text())
    starts = [e for e in trace["timeline"] if e["operation"] == "tool.call.started"]
    completed = [e["payload"] for e in trace["timeline"] if e["operation"] == "runtime.tool.completed"]
    observed = next(e["payload"]["observable_output"] for e in trace["timeline"] if e["operation"] == "model.output")
    scope = ExecutionScope(max_results=100)
    # Application writes only to a fresh APFS clone. Persist recreated envelopes
    # and workspace identity before declaring the workspace safe to remove.
    with EvaluationWorkspace.create(ROOT / "data/evaluation/frozen-20261028-validated/freeze.json") as workspace:
        with create_application(workspace.database_path, semantic_index_path=workspace.semantic_index_path) as app:
            envelopes = [app.invoke_tool("lexical_search", SearchMessagesInput(**e["payload"]["request"]), scope)
                         for e in starts]
            with (args.output_dir / "envelopes.pickle").open("xb") as stream:
                pickle.dump(envelopes, stream)
            (args.output_dir / "workspace.json").write_text(json.dumps({"database": str(workspace.database_path),
                                                                      "freeze": str(workspace.freeze_manifest_path)}))
        workspace.mark_results_persisted()
    run_id = completed[0]["run_id"]
    prefix = completed[0]["tool_call_id"].rsplit("/tool-call/", 1)[0]
    rows = []
    for pool in (32000, 64000, 128000):
        config = ToolResultBudgetConfig(context_window_tokens=1000000, run_tool_evidence_budget_override=pool)
        context = RuntimeContext(scope=scope, capability_registry=None, available_capabilities=("lexical_search",),
                                 run_id=run_id, tool_identity_prefix=prefix, tool_result_budget_policy=config.new_policy())
        reserve_budget_stop_results(context, [(o["name"], o["call_id"]) for o in observed])
        outputs = []
        for obs, env in zip(observed, envelopes, strict=True):
            call_id = context.resolve_tool_call_id(obs["call_id"])
            minimum = minimum_budget_stop_tokens(context, obs["name"], call_id)
            reservation = context.tool_result_budget_policy.begin_call(minimum_budget=minimum)
            payload = _append_runtime_tool_result(context, obs["name"], call_id, env, reservation)
            outputs.append(payload)
        remaining = context.tool_result_budget_policy.remaining_run_tool_evidence_budget
        # Keep this exact original spend separate from recomputed current-schema
        # projections, so metadata changes cannot masquerade as a budget fix.
        probes = []
        for count in (3, 4, 7):
            probe = RuntimeContext(scope=scope, capability_registry=None, available_capabilities=("lexical_search",),
                                   run_id=run_id, tool_identity_prefix=prefix, tool_result_budget_policy=config.new_policy())
            policy = probe.tool_result_budget_policy
            prior = policy.begin_call()
            policy.complete_call(prior, projected_tool_result_tokens=31409, truncated=True,
                                 omitted_context_messages=0, omitted_hit_messages=0)
            minimum = sum(minimum_budget_stop_tokens(probe, "lexical_search", f"{prefix}/tool-call/{i+3}")
                          for i in range(count))
            try:
                reserve_budget_stop_results(probe, [("lexical_search", f"boundary-{i}") for i in range(count)])
                outcome = "admitted"
            except ToolResultBudgetExhausted as exc:
                outcome = str(exc)
            probes.append({"declared_probe_calls": count, "minimum_control_tokens": minimum, "outcome": outcome})
        rows.append({"pool": pool, "reconstructed_first_batch": [o["model_projection"] for o in outputs],
                     "reconstructed_remaining": remaining, "historical_spend": 31409,
                     "historical_remaining_if_same_spend": pool - 31409, "boundary_probes": probes})
        with (args.output_dir / f"payloads-{pool}.json").open("x") as stream:
            json.dump(outputs, stream, ensure_ascii=False, indent=2)
    result = {"source_trace": trace["trace_id"], "context_window": 1000000, "per_call_ceiling": 128000,
              "missing_observation": "failed second batch tool names and arguments were not persisted",
              "rows": rows}
    with (args.output_dir / "summary.json").open("x") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
