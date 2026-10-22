"""离线核对真实回复调查的工具选择、送达、引用与用量；不调用模型。"""

from __future__ import annotations

import json
from typing import Any

from scripts.run_reply_context_live import CASES, ROOT, SOURCE
from scripts.run_runtime_budget_followup import read_json, write_json
from trivae.observability.sqlite import SQLiteTraceStore


def model_messages(value: object) -> list[dict[str, Any]]:
    """只采集模型确实看见的消息正文，不能用完整 Host 候选冒充送达。"""
    found = []
    if isinstance(value, dict):
        if isinstance(value.get("source_id"), str) and "content" in value:
            found.append(value)
        for nested in value.values():
            found.extend(model_messages(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(model_messages(nested))
    return found


def analyze_case(label: str) -> dict[str, object]:
    """用同一运行的 canonical record、真实 SDK 投影和最终 Evidence 逐层核对。"""
    output = ROOT / label
    record = read_json(output / "result.json")
    result = record["result"]
    runtime = result["runtime_result"]
    targets = read_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.targets.json")
    target_ids = {message["internal_message_id"] for message in targets}
    canonical_ids: set[str] = set()
    handle_ids = {}
    for tool in runtime["tool_results"]:
        ordinal = tool["tool_call_id"].rsplit("/", 1)[-1]
        for index, item in enumerate(tool["message_items"]):
            identity = item["message"]["internal_message_id"]
            canonical_ids.add(identity)
            handle_ids[f"m{ordinal}-{index + 1}"] = identity
    store = SQLiteTraceStore(output / "trace.sqlite3")
    try:
        trace = store.read_trace(result["trace_id"])
    finally:
        store.close()
    # 多轮模型输入会重复携带旧工具输出；按 SDK call_id 去重，而不是重复累计 Token。
    projections = {}
    requests = []
    for event in trace.events:
        if event.operation == "tool.call.started":
            requests.append(dict(event.payload))
        for item in event.payload.get("model_visible_context", []):
            if item.get("type") == "function_call_output":
                projections[item["call_id"]] = item["output_projection"]
    visible_ids: set[str] = set()
    tools = []
    for call_id, payload in projections.items():
        messages = model_messages(payload.get("data"))
        handles = {message["source_id"] for message in messages}
        visible_ids.update(handle_ids[handle] for handle in handles)
        details = (payload.get("data") or {}).get("metadata", {}).get("details", {})
        tools.append({"provider_call_id": call_id, "status": payload["status"],
            "error_code": (payload.get("error") or {}).get("code"), "projection": payload["model_projection"],
            "include_replies": details.get("include_replies"), "returned_replies": details.get("returned_replies"),
            "has_more_replies": details.get("has_more_replies"),
            "visible_reply_relations": sum("reply_to_source_message_id" in message for message in messages)})
    artifact = result["answer_artifact"]
    evidence_ids = {source["reference"]["internal_message_id"]
        for evidence in (artifact or {}).get("evidence_items", []) for source in evidence["sources"]
        if "internal_message_id" in source["reference"]}
    # 缺失 Usage 保留未知，不把无字段的响应当作零消耗。
    usages = [observation.get("usage") for observation in record["transport"]]
    known_usage = {name: sum(usage[name] for usage in usages if usage is not None and name in usage)
        for name in ("input_tokens", "output_tokens", "total_tokens")}
    return {"case": label, "status": record["status"], "http_requests": record["http_requests"],
        "tool_rounds": runtime["tool_rounds"], "target_count": len(target_ids),
        "canonical_target_coverage": len(target_ids & canonical_ids),
        "model_target_coverage": len(target_ids & visible_ids),
        "evidence_target_coverage": len(target_ids & evidence_ids),
        "finalization_status": result["finalization_status"],
        "citation_bindings": len((artifact or {}).get("citation_bindings", [])),
        "checks": [{"name": check["name"], "status": check["status"]}
            for check in record["evaluation"]["deterministic_checks"]],
        "tool_requests": requests, "tool_projections": tools,
        "provider_completed": sum(observation["terminal_event"] == "response.completed" for observation in record["transport"]),
        "known_usage": known_usage, "responses_without_usage": sum(usage is None for usage in usages),
        "responses_missing_usage_fields": {name: sum(usage is None or name not in usage for usage in usages)
            for name in known_usage},
        "finalizing_reasons": [dict(event.payload) for event in trace.events if event.operation == "runtime.finalizing"],
        "wall_seconds": record["wall_seconds"]}


def main() -> None:
    """分析已完成的三条实验，并保留完整私有诊断结果。"""
    cases = [analyze_case(label) for label in CASES]
    ledger = read_json(ROOT / "http-ledger.json")
    summary = {"cases": cases, "http_used": ledger["used"], "http_maximum": ledger["maximum"],
        "blocked": len(ledger["blocked"]), "quality_ab": False}
    write_json(ROOT / "analysis.json", summary, exclusive=True)
    for case in cases:
        print(json.dumps({name: case[name] for name in ("case", "status", "http_requests", "tool_rounds",
            "canonical_target_coverage", "model_target_coverage", "evidence_target_coverage", "target_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
