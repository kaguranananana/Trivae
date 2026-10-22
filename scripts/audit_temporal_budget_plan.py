"""零模型隔离首轮读取大小：同一5段后续取证和原16k池，不改任何产品检索契约。"""

import argparse
import ast
import asyncio
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from scripts.analyze_reply_context_live import model_messages
from scripts.run_quality_repair_iteration import application_for
from scripts.run_runtime_budget_followup import configured_runtime, write_json
from trivae.capabilities import ExecutionScope
from trivae.query.contracts import ExecutionOverride, QueryRequest


async def audit(source: Path, output: Path):
    output.mkdir(exist_ok=False)
    old = json.loads((source / "temporal/result.json").read_text())
    window = old["result"]["runtime_result"]["tool_results"][0]["query_scope_snapshot"]["resolved_time_range"]
    start, end = window["resolved_start_timestamp"], window["resolved_end_timestamp"]
    boundaries = [start + (end - start) * i // 5 for i in range(6)]
    followups = [{"start_timestamp": a, "end_timestamp": b, "limit": 15} for a, b in zip(boundaries, boundaries[1:])]
    write_json(
        output / "protocol.json",
        {
            "model_requests": 0,
            "original_window": window,
            "followups": followups,
            "candidate_first_limit": 20,
            "baseline_first_limit": 5000,
            "shared_budget": 16000,
            "source_code": Path(__file__).read_text(),
        },
        exclusive=True,
    )
    rows = []
    for arm, limit in [("baseline", 5000), ("candidate", 20)]:
        root = output / arm
        (root / "snapshot").mkdir(parents=True)
        for name in ["trivae.sqlite3", "trivae.semantic.sqlite3"]:
            subprocess.run(["cp", "-c", str(source / "snapshot" / name), str(root / "snapshot" / name)], check=True)
        runtime = configured_runtime()
        calls = [
            {
                "time_range": {"kind": "relative", "amount": 14, "unit": "day", "anchor": "archive_latest"},
                "limit": limit,
            },
            *followups,
        ]
        outputs = [
            function_call(
                "get_recent_messages",
                args,
                call_id=f"call_temporal_{n}",
                item_id=f"fc_temporal_{n}",
                namespace="trivae",
            )
            for n, args in enumerate(calls)
        ]
        final_output = [
            assistant_message(
                json.dumps(
                    {
                        "claims": [
                            {
                                "text": "所查看的窗口确有聊天记录，但检查范围有限。",
                                "finding": "存在消息",
                                "criterion": "返回了原始消息",
                                "sufficiency": "partial",
                                "sources": ["m1-1"],
                                "limitations": ["非完整主题总结"],
                            }
                        ],
                        "limitations": ["固定答案仅验证工具协议，不评判总结质量"],
                    },
                    ensure_ascii=False,
                )
            )
        ]
        # 尊重Runtime已移除工具的状态；不能强迫baseline发出真实模型未被允许的后续工具调用。
        runtime._model = ScriptedModel(
            [
                ModelStep(output=outputs[:1]),
                ModelStep.respond(lambda call: ModelStep(output=outputs[1:] if call.tools else final_output)),
                ModelStep(output=final_output),
            ]
        )
        app = application_for(root, "temporal", runtime)
        try:
            result = await app.query(
                QueryRequest(
                    query="最近两周大家主要在聊什么方向的内容？",
                    scope=ExecutionScope(max_results=5000),
                    execution_override=ExecutionOverride(forced_route="standard_execution"),
                )
            )
            write_json(root / "temporal/result.json", asdict(result), exclusive=True)
            # 在Model边界读取实际完整输出；Trace为控制体积会截断深层字段，不能用它统计可见正文。
            projections = {}
            for call in runtime._model.calls:
                for item in call.input:
                    if isinstance(item, dict) and item.get("type") == "function_call_output":
                        projections[item["call_id"]] = ast.literal_eval(item["output"])
            visible = [m for p in projections.values() for m in model_messages(p.get("data"))]
            row = {
                "arm": arm,
                "status": result.execution_status,
                "finalization": result.finalization_status,
                "runtime_error": None if result.runtime_result.error is None else result.runtime_result.error.code,
                "tokens": [c.model_result_estimated_tokens for c in result.runtime_result.tool_calls],
                "errors": [c.error_code for c in result.runtime_result.tool_calls],
                "prepared_messages": len(visible),
                "utc_dates": sorted(set(m["timestamp_utc"][:10] for m in visible)),
                "subwindow_host_messages": [len(r.message_items) for r in result.runtime_result.tool_results[1:]],
                "subwindow_totals": [
                    r.query_scope_snapshot.get("total_hits") for r in result.runtime_result.tool_results[1:]
                ],
            }
            assert result.is_successful
            rows.append(row)
            print(row, flush=True)
        finally:
            await app.aclose()
    assert all(error is None for error in rows[1]["errors"])
    assert (
        sum(rows[1]["subwindow_totals"])
        == old["result"]["runtime_result"]["tool_results"][0]["query_scope_snapshot"]["total_hits"]
    )
    write_json(output / "comparison.json", {"model_requests": 0, "results": rows}, exclusive=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="含snapshot/及temporal/result.json的已冻结当前基线")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(audit(args.source, args.output))
