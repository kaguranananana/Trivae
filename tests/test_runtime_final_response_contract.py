"""实际SQL和空窗结果进入SDK后，下一次模型输入应取得与Finalizer一致的格式资格。"""

from __future__ import annotations

import asyncio

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_ingestion import make_message, write_export
from tests.test_tool_result_budget import _dynamic_settings
from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.execute_sql import ExecuteSQLCapability
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.capabilities.tools import ExecuteSQLTool, RecentMessagesTool
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import AnswerFinalizationError, finalize_answer, has_verified_zero_result_evidence
from trivae.query.runtime.contracts import AgentRunRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.structured import StructuredRetrieval


def run_history(tmp_path, sql, *, read_empty=True):
    """重现日期统计与完整空窗共存，所有工具均走真实SQLite及SDK投影。"""
    database = tmp_path / "messages.sqlite3"
    export = write_export(tmp_path, "messages(930).json", [make_message("m1", 1, 1_786_700_000_000, "已有消息")],
                          chat_name="格式契约测试", peer_uid=None, version="5.5.64")
    store = SQLiteCanonicalStore(database)
    SharedImporter(store).import_paths([export])
    store.close()
    repository = SQLiteCanonicalReadRepository(database)
    registry = CapabilityRegistry()
    registry.register(ExecuteSQLTool(ExecuteSQLCapability(repository)))
    registry.register(RecentMessagesTool(RecentMessagesCapability(StructuredRetrieval(repository))))
    steps = []
    if sql is not None:
        steps.append(ModelStep(output=[function_call("execute_sql", {"sql": sql}, call_id="sql")]))
    if read_empty:
        steps.append(ModelStep(output=[function_call("get_recent_messages", {
            "start_timestamp": 1_000_000, "end_timestamp": 1_000_500, "limit": 10,
        }, call_id="recent")]))
    final = '{"kind":"no_result","summary":"目标时间窗内没有消息。","limitations":[]}'
    steps.append(ModelStep(output=[assistant_message(final)]))
    model = ScriptedModel(steps)
    runtime = OpenAIAgentsRuntimeAdapter(registry, model=model, settings=_dynamic_settings())
    request = AgentRunRequest("检查目标时间窗是否为空", ExecutionScope(),
                              available_capabilities=("execute_sql", "get_recent_messages"))
    try:
        result = asyncio.run(runtime.run(request))
    finally:
        repository.close()
    return result, model, request


@pytest.mark.parametrize(("sql", "read_empty", "allowed"), [
    (None, True, True),
    ("SELECT COUNT(*) AS n FROM messages WHERE timestamp < 1000", True, True),
    ("SELECT date(timestamp / 1000, 'unixepoch') AS day, COUNT(*) AS n FROM messages GROUP BY day", True, False),
    ("SELECT COUNT(*) AS n FROM messages WHERE timestamp < 1000", False, False),
])
def test_next_model_input_receives_actual_finalizer_eligibility(tmp_path, sql, read_empty, allowed):
    """辅助数值聚合可并存，日期行和单独COUNT不能冒充合法no_result。"""
    result, model, request = run_history(tmp_path, sql, read_empty=read_empty)
    assert result.termination == "completed"
    assert all(call.error_code is None for call in result.tool_calls)
    assert has_verified_zero_result_evidence(result.tool_results) is allowed
    expected = "allowed" if allowed else "unavailable"
    assert f"Host-verified no_result eligibility: {expected}." in model.calls[-1].system_instructions
    if allowed:
        assert finalize_answer(result.final_answer, run_id=result.run_id,
                               tool_results=result.tool_results, scope=request.scope).answer_text
    else:
        # 新提示不能削弱Finalizer：模型即使仍选错格式，也必须保留原始显式失败。
        with pytest.raises(AnswerFinalizationError, match="verified complete-and-empty"):
            finalize_answer(result.final_answer, run_id=result.run_id,
                            tool_results=result.tool_results, scope=request.scope)
