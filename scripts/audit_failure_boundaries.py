"""零模型请求核验遗留检索边界、空结果契约与真实 SDK 的 SQL 调度。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from time import perf_counter

from agents.tool_context import ToolContext

from tests.test_forward_retrieval import make_forward_message
from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.capabilities import ExecutionScope
from trivae.capabilities.contracts import SearchMessagesInput
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.capabilities.tools import LexicalSearchTool
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import (
    build_tool_result_record,
    finalize_answer_gracefully,
    has_verified_zero_result_evidence,
)
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import ExecuteSQLSDKToolAdapter
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import LexicalQuery, RetrievalResult, ScopeFilters

WRITTEN_TARGET = "qq:831907794:7671498185377818633"


def audit_retrieval(database: Path) -> dict[str, object]:
    """只读当前语料并复用正式检索和 Finalizer，不重建索引或重跑模型。"""

    repository = SQLiteCanonicalReadRepository(database)
    try:
        queries = []
        for keyword in ("构造", "笔试 测试", "github.com 荐"):
            # 查询原始命中顺序，避免把普通邻居混入目标的词法排名。
            query = LexicalQuery(keyword=keyword, limit=5000, context_before=0, context_after=0)
            ids = [hit.message.internal_message_id for hit in repository.read_lexical_hits(query)]
            queries.append({
                "keyword": keyword,
                "total_hits": repository.count_lexical_hits(query),
                "known_target_rank": ids.index(WRITTEN_TARGET) + 1 if WRITTEN_TARGET in ids else None,
            })
        # 子串计数只用于诊断；正式检索仍走 FTS，没有加入 LIKE 或其他查询分支。
        with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
            literal_count = connection.execute(
                "SELECT COUNT(*) FROM messages "
                "WHERE instr(lower(content_text), 'github.com') > 0 AND instr(content_text, '荐') > 0"
            ).fetchone()[0]
            message_count = connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        scope = ExecutionScope(max_results=5000)
        tool = LexicalSearchTool(SearchMessagesCapability(LexicalRetrieval(repository)))
        # 使用已有历史失败中的不存在词，保留当前真实 coverage 与转发缺口。
        envelope = tool.invoke(SearchMessagesInput(
            keyword="量子香蕉数据库", limit=20, context_before=0, context_after=0,
        ), scope)
        # 此探针必须取得真实检索结果；索引或读取失败时保留原错误并直接终止。
        assert isinstance(envelope.data, RetrievalResult), envelope.error
        record = build_tool_result_record(
            run_id="failure-audit", tool_call_id="failure-audit/tool-call/1",
            tool_result_id="failure-audit/tool-call/1/result", tool_name="lexical_search",
            envelope=envelope, scope=scope,
        )
        text = "当前可恢复文本未命中；部分转发正文缺失，不能判断全范围是否存在。"
        candidates = {
            "no_result": {"kind": "no_result", "summary": text, "limitations": []},
            "empty_source_claim": {"claims": [{
                "text": text, "finding": "当前可恢复文本未命中", "criterion": "仅陈述当前检索观察",
                "sufficiency": "insufficient", "sources": [], "limitations": [],
            }], "limitations": []},
        }
        finalizations = {}
        for name, candidate in candidates.items():
            # 两个候选共用完全相同的工具历史，仅改变既有最终输出形态。
            result = finalize_answer_gracefully(
                json.dumps(candidate, ensure_ascii=False), run_id="failure-audit",
                tool_results=(record,), scope=scope,
            )
            finalizations[name] = {
                "status": result.diagnostics.status,
                "error_code": result.diagnostics.error_code,
                "answer_preserved": result.diagnostics.user_answer_preserved,
                "validated_citations": result.diagnostics.validated_citation_count,
            }
        data = envelope.data
        return {
            "canonical_messages": message_count,
            "known_target_exists": repository.read_message_by_id(WRITTEN_TARGET) is not None,
            "queries": queries,
            "canonical_literal_github_and_single_han": literal_count,
            "empty_result": {
                "status": envelope.status, "total_hits": data.total_hits,
                "coverage": data.coverage.to_dict(),
                "forward_gaps": data.metadata.details["unexpanded_forward_nodes"],
                "no_result_eligible": has_verified_zero_result_evidence((record,)),
                "finalizations": finalizations,
            },
        }
    finally:
        repository.close()


async def measure_sql_loop(application: TrivaeApplication, sql: str) -> dict[str, object]:
    """在真实 SDK 工具入口同时安排定时回调，直接测量事件循环是否被占用。"""

    registry = application.capability_registry
    runtime = RuntimeContext(
        scope=ExecutionScope(), capability_registry=registry,
        available_capabilities=("execute_sql",), run_id="sql-loop-audit",
    )
    runtime.allocate_tool_call_id("sql-loop")
    arguments = json.dumps({"sql": sql, "max_rows": 1})
    wrapper = ToolContext(
        context=runtime, tool_name="execute_sql", tool_call_id="sql-loop", tool_arguments=arguments,
    )
    tool = ExecuteSQLSDKToolAdapter(registry).as_sdk_tool()
    loop = asyncio.get_running_loop()
    heartbeat = loop.create_future()
    started = perf_counter()
    # 回调不执行 SQL 或模型调用；其延迟直接反映同一事件循环的可调度性。
    loop.call_later(0.02, lambda: heartbeat.set_result(perf_counter() - started))
    result = await tool.on_invoke_tool(wrapper, arguments)
    elapsed = perf_counter() - started
    # 等待同一次测量的回调，不能在 SQL 返回后重新安排计时而隐藏阻塞。
    pulse = await heartbeat
    return {
        "sql_seconds": elapsed, "scheduled_callback_seconds": 0.02,
        "actual_callback_seconds": pulse, "callback_delay_seconds": pulse - 0.02,
        "tool_status": result["status"],
        "error_code": result["error"]["code"] if result.get("error") else None,
    }


def audit_sql_loop() -> dict[str, object]:
    """临时小库上对照快查询与历史慢查询形态，不占用在线数据库。"""

    with tempfile.TemporaryDirectory(prefix="trivae-sql-loop-audit-") as temporary:
        root = Path(temporary)
        raw = root / "raw"
        raw.mkdir()
        write_export(raw, "loop(100).json", [
            make_message(f"m{i}", i, 1_700_000_000_000 + i, "事件循环响应检查") for i in range(1000)
        ], chat_name="loop", peer_uid=None, version="5.5.64")
        with create_application(root / "messages.sqlite3") as application:
            application.import_directory(raw)
            # 两组共用同一工具与数据；控制组排除 SDK 建模和结果投影自身需要数秒的解释。
            control = asyncio.run(measure_sql_loop(application, "SELECT COUNT(*) AS n FROM messages"))
            slow = asyncio.run(measure_sql_loop(
                application, "SELECT COUNT(*) AS n FROM messages a CROSS JOIN messages b "
                "CROSS JOIN messages c CROSS JOIN messages d",
            ))
            return {"control": control, "slow": slow}


def audit_forward_enrichment() -> dict[str, object]:
    """复现先导入空转发、后补齐正文的真实数据形态，并用相反顺序排除索引故障。"""

    missing = make_forward_message("outer", 10_000, [])
    complete = make_forward_message("outer", 10_000, [make_message(
        "inner", None, 100, "新补齐的远程连接正文",
    )])
    observations = {}
    with tempfile.TemporaryDirectory(prefix="trivae-forward-enrichment-audit-") as temporary:
        for name, messages in (("missing_then_full", (missing, complete)),
                               ("full_then_missing", (complete, missing))):
            directory = Path(temporary) / name
            directory.mkdir()
            path = directory / "messages.sqlite3"
            store = SQLiteCanonicalStore(path)
            try:
                importer = SharedImporter(store)
                for ordinal, message in enumerate(messages):
                    # 每个输入文件单独导入，明确控制顺序；根消息身份和预览始终相同。
                    source = write_export(directory, f"input-{ordinal}(100).json", [message],
                                          chat_name="测试群", peer_uid="100", version="0.1.0")
                    imported = importer.import_paths([source]).batches[0]
                index = SQLiteLexicalIndex(path)
                try:
                    # 主动重建派生索引，避免把 Canonical 丢失误判成索引尚未刷新。
                    index.rebuild()
                finally:
                    index.close()
                repository = SQLiteCanonicalReadRepository(path)
                try:
                    hits = repository.count_lexical_hits(LexicalQuery(keyword="远程连接", limit=50))
                    gaps = len(repository.forward_content_gaps(ScopeFilters()))
                finally:
                    repository.close()
                variant = store.connection.execute(
                    "SELECT variant_kind, raw_payload_json FROM message_variants"
                ).fetchone()
                observations[name] = {
                    "second_import_duplicates": imported.duplicate_count,
                    "second_import_conflicts": imported.conflict_count,
                    "content_hits_after_rebuild": hits, "remaining_gaps": gaps,
                    "variant_kind": variant[0], "variant_has_raw": variant[1] is not None,
                }
            finally:
                store.close()
    return observations


def main() -> None:
    """先保存完整观察，再按显式选项让事件循环响应断言失败以供后续修复验收。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-responsive-sql", action="store_true")
    parser.add_argument("--require-forward-enrichment", action="store_true")
    args = parser.parse_args()
    report = {
        "model_requests": 0, "retrieval": audit_retrieval(args.database),
        "sql_loop": audit_sql_loop(), "forward_enrichment": audit_forward_enrichment(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    if args.require_responsive_sql:
        # 该独立审计命令应在当前缺陷下变红，修复后同一工具链的定时回调应及时执行。
        assert report["sql_loop"]["slow"]["callback_delay_seconds"] < 0.2, "SQL blocked the event loop"
    if args.require_forward_enrichment:
        # 新导出的真实内部正文应可恢复；这个断言不以导入成功或索引 ready 冒充内容可见。
        assert report["forward_enrichment"]["missing_then_full"]["content_hits_after_rebuild"] == 1, (
            "newly available forwarded body was discarded as an equal duplicate"
        )


if __name__ == "__main__":
    main()
