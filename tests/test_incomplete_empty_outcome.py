"""有缺失转发但当前可恢复文本无命中时，应能正式表达取证不足。"""

from __future__ import annotations

import asyncio
import json
from contextlib import closing
from dataclasses import replace

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_forward_retrieval import make_forward_message
from tests.test_ingestion import make_message, write_export
from tests.test_tool_result_budget import _dynamic_settings
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, SearchMessagesInput
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.capabilities.tools import LexicalSearchTool
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.evidence import build_tool_result_record, finalize_answer_gracefully
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.lexical import LexicalRetrieval


def test_partial_empty_retrieval_has_a_valid_insufficient_evidence_outcome(tmp_path):
    """同一真实工具历史保留 partial，新增正式结果不能依赖空来源的 graceful 降级。"""
    source = write_export(tmp_path, "partial(100).json", [make_forward_message("outer", 10_000, []),
                          make_message("normal", 1, 11_000, "已知的正常讨论")],
                          chat_name="测试群", peer_uid="100", version="0.1.0")
    database = tmp_path / "messages.sqlite3"
    scope = ExecutionScope(max_results=50)
    with SQLiteCanonicalStore(database) as store, closing(SQLiteCanonicalReadRepository(database)) as reader:
        SharedImporter(store).import_paths([source])
        with closing(SQLiteLexicalIndex(database)) as index:
            index.rebuild()
        envelope = LexicalSearchTool(SearchMessagesCapability(LexicalRetrieval(reader))).invoke(
            SearchMessagesInput(keyword="量子香蕉数据库", limit=50, context_before=0, context_after=0), scope,
        )
        assert envelope.data.total_hits == 0 and envelope.data.coverage.status == "partial"
        record = build_tool_result_record(run_id="partial-empty", tool_call_id="partial-empty/tool-call/1",
                                          tool_result_id="partial-empty/tool-call/1/result", tool_name="lexical_search",
                                          envelope=envelope, scope=scope)
        output = json.dumps({"kind": "insufficient_evidence", "summary": "可恢复文本中未命中；转发正文缺失，无法确定完整范围。",
                             "limitations": []}, ensure_ascii=False)
        result = finalize_answer_gracefully(output, run_id=record.run_id, tool_results=(record,), scope=scope)
        assert result.diagnostics.status == "valid"
        assert result.artifact.content_blocks[0].block_id == "insufficient-evidence"
        assert "coverage:partial" in result.artifact.limitations
        assert "unexpanded_forward_content" in result.artifact.limitations
        assert result.artifact.evidence_items == ()
        # 完整无结果的原资格不放宽；同样的 partial 工具历史仍不能声称全范围无结果。
        wrong = json.dumps({"kind": "no_result", "summary": "范围内没有任何消息", "limitations": []})
        rejected = finalize_answer_gracefully(wrong, run_id=record.run_id, tool_results=(record,), scope=scope)
        assert rejected.diagnostics.status == "failed"
        positive = LexicalSearchTool(SearchMessagesCapability(LexicalRetrieval(reader))).invoke(
            SearchMessagesInput(keyword="正常", limit=50), scope,
        )
        positive_record = build_tool_result_record(run_id=record.run_id, tool_call_id="partial-empty/tool-call/2",
                                                  tool_result_id="partial-empty/tool-call/2/result",
                                                  tool_name="lexical_search", envelope=positive, scope=scope)
        error_record = replace(record, status="error", limitations=("tool_error:EXECUTION_ERROR",))
        # 有真实候选、只有工具失败或根本未检索时，均不能用取证不足形态替代正式错误/引用。
        for history in ((positive_record,), (error_record,), ()):
            assert finalize_answer_gracefully(output, run_id=record.run_id, tool_results=history,
                                              scope=scope).diagnostics.status == "failed"


def test_sdk_incomplete_empty_outcome_is_saved_without_degradation(tmp_path):
    """完整 Application→SDK→Finalizer→会话链路保留正式取证不足与 Host 格式资格。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    write_export(raw, "partial(100).json", [make_forward_message("outer", 10_000, [])],
                 chat_name="测试群", peer_uid="100", version="0.1.0")
    final = json.dumps({"kind": "insufficient_evidence", "summary": "可恢复文本未命中，但转发缺失，不能判断全范围。",
                        "limitations": []}, ensure_ascii=False)
    model = ScriptedModel([
        ModelStep(output=[function_call("lexical_search", {"keyword": "量子香蕉数据库", "limit": 50,
                                                           "context_before": 0, "context_after": 0}, call_id="search")]),
        ModelStep(output=[assistant_message(final)]),
    ])
    runtime = OpenAIAgentsRuntimeAdapter(model=model, settings=_dynamic_settings())
    with create_application(tmp_path / "messages.sqlite3", agent_runtime=runtime) as application:
        runtime.capability_registry = application.capability_registry
        application.import_directory(raw)
        with closing(SQLiteLexicalIndex(tmp_path / "messages.sqlite3")) as index:
            index.rebuild()
        result = asyncio.run(application.query(QueryRequest("查找这个不存在词", ExecutionScope(),
                                  execution_override=ExecutionOverride(forced_route="standard_execution"))))
        assert result.is_successful and result.finalization_status == "valid"
        assert "Host-verified insufficient_evidence eligibility: allowed." in model.calls[-1].system_instructions
        saved = application.read_conversation(result.conversation_id).messages[-1].answer_artifact
        assert saved == result.answer_artifact
        assert saved.content_blocks[0].block_id == "insufficient-evidence"
