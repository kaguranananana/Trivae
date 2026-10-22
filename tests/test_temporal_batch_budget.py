"""真实SQLite及SDK回归：同轮多个时间窗不能由先执行者独占数据预算。"""

from __future__ import annotations

import asyncio
import json

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_ingestion import make_message, write_export
from tests.test_tool_result_budget import _dynamic_settings
from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.capabilities.tools import RecentMessagesTool
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import finalize_answer
from trivae.query.runtime.contracts import AgentRunRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.structured import StructuredRetrieval


def test_parallel_temporal_windows_each_receive_evidence_within_original_pool(tmp_path):
    """原真实形态：20条探路→四段各65条；每段仍须在共享16k中送达正文。"""
    base = 1_786_700_000_000
    path = tmp_path / "temporal-batch.sqlite3"
    export = write_export(tmp_path, "时间窗(900).json", [
        make_message(str(index), index, base + index * 1000,
                     "讨论数据库事务和服务部署的实际经验。" * 3 + f"消息{index}")
        for index in range(300)
    ], chat_name="时间窗", peer_uid="900", version="1")
    store = SQLiteCanonicalStore(path)
    SharedImporter(store).import_paths([export])
    repository = SQLiteCanonicalReadRepository(path)
    registry = CapabilityRegistry()
    registry.register(RecentMessagesTool(RecentMessagesCapability(StructuredRetrieval(repository))))
    first = {"start_timestamp": base, "end_timestamp": base + 300_000, "limit": 20}
    windows = [{"start_timestamp": base + index * 75_000,
                "end_timestamp": base + (index + 1) * 75_000, "limit": 65} for index in range(4)]
    final = json.dumps({"claims": [{"text": "所查窗口存在讨论消息。", "finding": "存在消息",
        "criterion": "返回了原始正文", "sufficiency": "partial", "sources": ["m1-1"], "limitations": []}],
        "limitations": ["固定输出只检验预算、来源和协议，不证明主题覆盖完整。"]}, ensure_ascii=False)
    model = ScriptedModel([
        ModelStep(output=[function_call("get_recent_messages", first, call_id="call-first")]),
        ModelStep(output=[function_call("get_recent_messages", args, call_id=f"call-window-{index}")
                          for index, args in enumerate(windows)]),
        ModelStep(output=[assistant_message(final)]),
    ])
    runtime = OpenAIAgentsRuntimeAdapter(registry, model=model, settings=_dynamic_settings())
    scope = ExecutionScope(max_results=5000)
    try:
        result = asyncio.run(runtime.run(AgentRunRequest("分段检查整个时间窗", scope,
            available_capabilities=("get_recent_messages",))))
        assert result.termination == "completed"
        assert len(result.tool_calls) == 5
        assert [call.error_code for call in result.tool_calls] == [None] * 5
        assert result.tool_calls[0].model_result_projected_messages == 20
        assert all(call.model_result_projected_messages > 0 for call in result.tool_calls[1:])
        # 原始300条计数由四个不重叠子窗完全分解，正文抽样仍保持partial语义。
        assert sum(record.query_scope_snapshot["total_hits"] for record in result.tool_results[1:]) == 300
        assert sum(call.model_result_estimated_tokens for call in result.tool_calls) <= 16_000
        finalize_answer(result.final_answer, run_id=result.run_id, tool_results=result.tool_results, scope=scope)
    finally:
        repository.close()
        store.close()
