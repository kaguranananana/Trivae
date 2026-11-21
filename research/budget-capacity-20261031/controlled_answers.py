"""Production Runtime/Finalizer with a fixed historical tool prefix and live synthesis.

Prefix model turns are scripted (zero inference), not Agent search decisions.
The last turn uses the configured official DeepSeek model, original product Prompt,
and production Host projections. This isolates evidence use from search randomness.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pickle
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter

from agents import Model
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.usage import Usage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research/agent-quality-20261029"))
from model_request_meter import install_meter  # noqa: E402

from trivae.bootstrap.application import create_application  # noqa: E402
from trivae.capabilities import contracts  # noqa: E402
from trivae.capabilities.registry import CapabilityRegistry  # noqa: E402
from trivae.config.dotenv import load_environment_file  # noqa: E402
from trivae.config.settings import load_settings  # noqa: E402
from trivae.conversation.serialization import serialize_answer_artifact  # noqa: E402
from trivae.evaluation.contracts import EvaluationCaseBundle  # noqa: E402
from trivae.evaluation.workspace import EvaluationWorkspace  # noqa: E402
from trivae.query.evidence import (  # noqa: E402
    _projected_source_ids,
    build_tool_result_record,
    finalize_answer_gracefully,
)
from trivae.query.runtime.contracts import AgentRunRequest, ModelContextMessage  # noqa: E402
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter  # noqa: E402

STUDY = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
BUNDLE = ROOT / "data/evaluation/eval-v1-20261028/cases"
FROZEN = ROOT / "data/evaluation/frozen-20261028-validated/freeze.json"


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)


class PrefixThenLive(Model):
    def __init__(self, live, steps):
        self.live = live
        self.prefix = ScriptedModel(steps)
        self.remaining = len(steps)

    async def get_response(self, *args, **kwargs):
        if self.remaining:
            self.remaining -= 1
            return await self.prefix.get_response(*args, **kwargs)
        return await self.live.get_response(*args, **kwargs)

    async def stream_response(self, *args, **kwargs):
        target = self.live
        if self.remaining:
            self.remaining -= 1
            target = self.prefix
        async for event in target.stream_response(*args, **kwargs):
            yield event


class FixedTool:
    def __init__(self, name, entries, cursor):
        self.name, self.entries, self.cursor = name, entries, cursor

    def invoke(self, request, scope):
        entry = self.entries[self.cursor[0]]
        assert entry["tool_name"] == self.name
        # Canonical requests were resolved under this exact frozen scope. Handles
        # in old scripted model arguments may differ after retention; the fixed
        # replay deliberately returns the saved canonical evidence, not a lookup
        # against changed run-local handles.
        self.cursor[0] += 1
        return entry["envelope"]


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    with args.envelopes.open("rb") as stream:
        semantic = pickle.load(stream)
    maps = {i["run_id"]: i["source"] for i in json.loads((STUDY / "source-map-b.json").read_text())["selected"]}
    study = json.loads((STUDY / "study-data.json").read_text())
    typed = {"lexical_search": contracts.SearchMessagesInput, "semantic_search": contracts.SemanticSearchInput,
             "get_recent_messages": contracts.GetRecentMessagesInput, "get_message_context": contracts.GetMessageContextInput,
             "find_members": contracts.FindMembersInput, "get_schema": contracts.GetSchemaInput,
             "execute_sql": contracts.ExecuteSQLInput}
    plans = []
    with EvaluationWorkspace.create(FROZEN) as workspace:
        with create_application(workspace.database_path, semantic_index_path=workspace.semantic_index_path) as app:
            for cid in args.cases:
                case = EvaluationCaseBundle.from_json(BUNDLE / f"{cid}.json")
                run = study["cases"][cid]["runs"]["B"][0]
                source = run["trace"]["trace_path"] if run["source"] == "new-agent-run" else maps[run["run_id"]]["trace_record"]
                trace = json.loads((ROOT / source).read_text())
                events = trace["timeline"]
                batches = [[o for o in e["payload"].get("observable_output", []) if o.get("type") == "function_call"]
                           for e in events if e["operation"] == "model.output"]
                batches = [b for b in batches if b]
                starts = {int(e["operation_id"].rsplit("/", 1)[1]): e["payload"] for e in events
                          if e["operation"] == "tool.call.started"}
                sem = iter([s for s in semantic if s["label"] == f"B0-{cid}"])
                entries, handle_map, ordinal = [], {}, 0
                for batch in batches:
                    for obs in batch:
                        ordinal += 1
                        start = starts.get(ordinal)
                        if start is None:
                            # Original budget control stopped this declared call before
                            # Capability execution. Recover its exact canonical request
                            # from an already known source handle, and record that fact.
                            assert obs["name"] == "get_message_context", obs
                            request = json.loads(obs["arguments"])
                            source_id = request.pop("source_id")
                            request["message_id"] = handle_map[source_id]
                            start = {"tool_name": obs["name"], "request": request,
                                     "original_capability_executed": False}
                        assert obs["name"] == start["tool_name"]
                        if start["tool_name"] == "semantic_search":
                            saved = next(sem)
                            assert saved["request"]["query"] == start["request"]["query"]
                            env = saved["envelopes"][args.capacity]
                            original_env = saved["envelopes"][100]
                        else:
                            env = app.invoke_tool(start["tool_name"], typed[start["tool_name"]](**start["request"]), case.data_access_scope)
                            original_env = env
                        assert env.status != "error", env.error
                        record = build_tool_result_record(run_id="fixed", tool_call_id=f"fixed/tool-call/{ordinal}",
                                                          tool_result_id=f"fixed/tool-call/{ordinal}/result",
                                                          tool_name=start["tool_name"], envelope=original_env,
                                                          scope=case.data_access_scope)
                        handle_map.update({f"m{record.model_scope_id}-{i+1}": item.message.internal_message_id
                                           for i, item in enumerate(record.message_items)})
                        # Canonical requests keep the fixed context lookup stable even
                        # when increased semantic capacity changes run-local handles.
                        obs["arguments"] = json.dumps(start["request"], ensure_ascii=False)
                        entries.append({**start, "envelope": env})
                first = next(e["payload"]["model_visible_context"] for e in events
                             if e["operation"] == "model.turn" and e["phase"] == "started")
                history = [i for i in first if i.get("role") in ("user", "assistant") and i.get("content") != case.query]
                plans.append({"case": case, "source_trace": source, "batches": batches, "entries": entries, "history": history})
            with (args.output / "plans.pickle").open("xb") as stream:
                pickle.dump(plans, stream)
            write(args.output / "preparation.json", {"freeze": str(FROZEN), "workspace": workspace.record_storage(),
                                                    "capacity": args.capacity, "cases": args.cases,
                                                    "source_traces": [p["source_trace"] for p in plans]})
        workspace.mark_results_persisted()


async def run(args):
    import httpx
    import httpx2

    import trivae.query.runtime.openai_tools as tool_module

    args.output.mkdir(parents=True, exist_ok=False)
    with args.plan.open("rb") as stream:
        plans = pickle.load(stream)
    load_environment_file(None)
    base = load_settings(model_id="deepseek-flash", role="agent")
    assert base.provider == "deepseek" and base.base_url.rstrip("/") == "https://api.deepseek.com"
    install_meter("agent", f"budget-C-{args.pool}", args.output)
    # Save exact outbound inference JSON locally, never headers or credentials.
    # Measure the same complete input against Provider Usage after the response.
    ordinal = [0]
    def wrap(send):
        async def capture(client, request):
            if request.method == "POST" and request.url.path.endswith("/chat/completions"):
                body = json.loads(request.content)
                # Scripted prefix turns generated no reasoning. DeepSeek requires
                # the field on assistant tool turns even in this no-tools final
                # request. Explicit empty fields describe that fixture truthfully;
                # never invent reasoning or alter real Provider turns.
                for message in body["messages"]:
                    if message.get("role") == "assistant" and message.get("tool_calls"):
                        assert "reasoning_content" not in message
                        message["reasoning_content"] = ""
                content = json.dumps(body, ensure_ascii=False).encode()
                headers = dict(request.headers)
                headers["content-length"] = str(len(content))
                request = type(request)(request.method, request.url, headers=headers,
                                        content=content, extensions=request.extensions)
                ordinal[0] += 1
                assert len(request.content) + body.get("max_tokens", 16384) + 10000 < 1000000, "input/output exceeds verified context"
                write(args.output / f"request-{ordinal[0]:03}.json", body)
            response = await send(client, request)
            if response.status_code >= 400:
                await response.aread()
                write(args.output / f"http-error-{ordinal[0]:03}.json", {"status": response.status_code,
                                                                     "body": response.text})
            return response
        return capture
    for lib in (httpx, httpx2):
        lib.AsyncClient._send_single_request = wrap(lib.AsyncClient._send_single_request)
    original_append = tool_module._append_runtime_tool_result
    current_dir = [None]
    def append(context, name, call_id, env, reservation):
        payload = original_append(context, name, call_id, env, reservation)
        record = context.tool_results[-1]
        handles = _projected_source_ids(payload["data"])
        write(current_dir[0] / f"tool-{len(context.tool_results):02}.json", {
            "payload": payload, "handle_map": {f"m{record.model_scope_id}-{i+1}": item.message.internal_message_id
                                               for i, item in enumerate(record.message_items)},
            "visible_ids": [item.message.internal_message_id for i, item in enumerate(record.message_items)
                            if f"m{record.model_scope_id}-{i+1}" in handles],
        })
        return payload
    tool_module._append_runtime_tool_result = append
    for plan in plans:
        case, batches = plan["case"], plan["batches"]
        out = args.output / case.case_id
        out.mkdir()
        current_dir[0] = out
        registry, cursor = CapabilityRegistry(), [0]
        names = tuple(dict.fromkeys(e["tool_name"] for e in plan["entries"]))
        for name in names:
            registry.register(FixedTool(name, plan["entries"], cursor))
        settings = replace(base, model_context_window_tokens=1000000, run_tool_evidence_budget=args.pool,
                           per_call_tool_result_cap=128000, max_tool_rounds=len(batches), max_turns=len(batches)+1)
        runtime = OpenAIAgentsRuntimeAdapter(registry, settings=settings)
        live_model = (ScriptedModel([ModelStep(output=[assistant_message('{"claims":[{"text":"offline protocol check","finding":"format check","criterion":"synthetic fixture","sufficiency":"partial","sources":["m1-1"],"limitations":[]}],"limitations":[]}')], usage=Usage(requests=0))])
                      if args.dry_run else runtime._model)
        runtime._model = PrefixThenLive(live_model, [ModelStep(
            output=[function_call(o["name"], o["arguments"], call_id=o["call_id"]) for o in batch],
            usage=Usage(requests=0), response_id=f"fixed-prefix-{i}",
        ) for i, batch in enumerate(batches)])
        write(out / "configuration.json", {"settings": settings.to_safe_dict(), "source_trace": plan["source_trace"],
                                            "fixed_prefix_rounds": len(batches), "live_search_decisions": False})
        request = AgentRunRequest(query=case.query, scope=case.data_access_scope, available_capabilities=names,
                                  model_context=tuple(ModelContextMessage(**i) for i in plan["history"]))
        first_ordinal = ordinal[0]
        started = perf_counter()
        events = []
        result = None
        try:
            async for event in runtime.stream(request):
                if event.type not in ("thinking_delta", "content_delta"):
                    events.append(asdict(event))
                if event.result is not None:
                    result = event.result
            assert result is not None
            final = finalize_answer_gracefully(result.final_answer or "", run_id=result.run_id,
                                               tool_results=result.tool_results, scope=case.data_access_scope)
            write(out / "result.json", {"termination": result.termination, "usage": result.usage,
                                        "runtime_error": asdict(result.error) if result.error else None,
                                        "latency_seconds": perf_counter()-started, "raw_answer": result.final_answer,
                                        "inference_http_requests": ordinal[0]-first_ordinal,
                                        "finalization_diagnostics": final.diagnostics.to_dict(),
                                        "finalization_error": asdict(final.error) if final.error else None,
                                        "artifact": json.loads(serialize_answer_artifact(final.artifact)) if final.artifact else None})
            write(out / "events.json", events)
            print(f"{args.pool} {case.case_id} {result.termination} {result.usage}", flush=True)
            if result.error is not None and result.error.diagnostic_type == "BadRequestError":
                raise RuntimeError("Provider rejected the experimental protocol; stop before the next case")
        finally:
            await runtime.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--envelopes", type=Path, required=True)
    prep.add_argument("--capacity", type=int, choices=(100, 200, 500), required=True)
    prep.add_argument("--cases", nargs="+", required=True)
    prep.add_argument("--output", type=Path, required=True)
    live = sub.add_parser("run")
    live.add_argument("--plan", type=Path, required=True)
    live.add_argument("--pool", type=int, choices=(32000, 64000, 128000), required=True)
    live.add_argument("--output", type=Path, required=True)
    live.add_argument("--dry-run", action="store_true", help="Replay prefix and synthetic final; zero inference")
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args)
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
