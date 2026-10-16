#!/usr/bin/env python3
"""核验真实合并转发的 lexical、semantic、生产 Agent 和来源回读；输出只存本地新目录。"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput, SemanticSearchInput
from trivae.config.dotenv import load_environment_file
from trivae.conversation.sqlite import SQLiteConversationStore
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import QueryRequest
from trivae.query.evidence import AnswerArtifact, MessageSource
from trivae.retrieval.semantic.contracts import SemanticRetrievalResult
from trivae.retrieval.structured import RetrievalResult


def _save(path: Path, value: object) -> None:
    """保存可复查的真实结果；聊天内容不进入版本控制。"""

    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def cited_message_sources(artifact: AnswerArtifact) -> tuple[tuple[str, str, MessageSource], ...]:
    """只核验正文实际绑定的来源，证据面板中未引用的候选不能冒充 Citation。"""

    evidence_by_id = {item.evidence_id: item for item in artifact.evidence_items}
    references: list[tuple[str, str, MessageSource]] = []
    for binding in artifact.citation_bindings:
        # 正文 block → evidence → source 必须形成完整绑定链。
        for evidence_id in binding.evidence_ids:
            for source in evidence_by_id[evidence_id].sources:
                if isinstance(source.reference, MessageSource):
                    references.append((binding.content_block_id, evidence_id, source.reference))
    return tuple(references)


async def verify(args: argparse.Namespace) -> None:
    """复用 Application 主链路，不复制检索或证据生成逻辑。"""

    # 每次运行独立目录，避免覆盖历史实验或已有验证记录。
    args.output.mkdir(parents=True, exist_ok=False)
    # 查询范围固定为实际群；时间语义由生产工具执行。
    scope = ExecutionScope(allowed_session_ids=(args.session_id,), max_results=100)
    # 会话、Trace 和辅助数据库单独保存，不触碰冻结的 Evaluation 数据库。
    conversations = SQLiteConversationStore(args.output / "conversations.sqlite3")
    traces = SQLiteTraceStore(args.output / "traces.sqlite3")
    async with create_application(
        args.database,
        semantic_index_path=args.semantic_index,
        conversation_store=conversations,
        trace_store=traces,
        evaluation_database_path=args.output / "runtime.evaluation.sqlite3",
        feedback_database_path=args.output / "feedback.sqlite3",
    ) as application:
        # readiness 保留索引版本和过期状态，不能把缺失语义索引报告成成功。
        _save(args.output / "readiness.json", application.readiness().to_dict())
        reports: list[dict[str, object]] = []
        for index, keyword in enumerate(args.keyword, start=1):
            started = perf_counter()
            lexical = application.invoke_tool(
                "lexical_search",
                SearchMessagesInput(keyword=keyword, limit=100, context_before=0, context_after=0),
                scope,
            )
            # Tool error 先落盘；失败直接暴露，不改用其他策略伪造命中。
            _save(args.output / f"{index}-lexical.json", asdict(lexical))
            if lexical.status == "error":
                raise RuntimeError(f"lexical retrieval failed for {keyword}: {lexical.error}")
            # 明确读取对应工具的领域结果，避免把另一种 Tool Envelope 当成 lexical 结果。
            lexical_result = lexical.data
            if not isinstance(lexical_result, RetrievalResult):
                raise TypeError("lexical_search did not return RetrievalResult")
            lexical_children = [
                hit.message for hit in lexical_result.hits
                if hit.message.forward is not None and keyword in hit.message.normalized_content
            ]
            if not lexical_children:
                raise RuntimeError(f"no actual forwarded child found for {keyword}")
            # 使用真实配置的 embedding 模型，禁止以测试向量替代真实语义验证。
            semantic = application.invoke_tool(
                "semantic_search",
                SemanticSearchInput(query=keyword, limit=20, context_before=0, context_after=0),
                scope,
            )
            _save(args.output / f"{index}-semantic.json", asdict(semantic))
            if semantic.status == "error":
                raise RuntimeError(f"semantic retrieval failed for {keyword}: {semantic.error}")
            # 语义命中必须来自真实恢复的消息集合，不能只检查向量分数或 chunk ID。
            semantic_result = semantic.data
            if not isinstance(semantic_result, SemanticRetrievalResult):
                raise TypeError("semantic_search did not return SemanticRetrievalResult")
            expected_ids = {message.internal_message_id for message in lexical_children}
            semantic_ids = {message.internal_message_id for message in semantic_result.expanded_messages}
            matched_ids = sorted(expected_ids & semantic_ids)
            if not matched_ids:
                raise RuntimeError(f"semantic candidates did not recover the actual forwarded child for {keyword}")
            report: dict[str, object] = {
                "keyword": keyword,
                "lexical_total_hits": lexical_result.total_hits,
                "lexical_children": [asdict(message) for message in lexical_children],
                "semantic_matching_child_ids": matched_ids,
                "retrieval_elapsed_ms": (perf_counter() - started) * 1000,
            }
            if args.run_agent:
                # 真实 Agent 自行执行工具与答案生成，Host 只检查实际引用及回读结果。
                query = (
                    f"请查找本群合并转发聊天里关于“{keyword}”的具体讨论。"
                    "请用 lexical_search 和 semantic_search 核实，引用具体内部消息，"
                    "说明内部发送者、原始发送时间、转发到本群的时间及外层来源。"
                )
                if args.agent_query_mode == "natural":
                    # 普通用户问法不指定工具和转发位置，验证 Agent 能自行发现内部讨论。
                    query = f"群里有人讨论过“{keyword}”吗？请说明当时谁说了什么，补充相关上下文并引用原始消息。"
                result = await application.query(QueryRequest(query=query, scope=scope, trace_profile="debug"))
                _save(args.output / f"{index}-agent.json", asdict(result))
                if result.trace_id is not None:
                    application.export_trace_log(result.trace_id, output_path=args.output / f"{index}-agent.log")
                if not result.is_successful or result.answer_artifact is None:
                    raise RuntimeError(f"production Agent failed for {keyword}; trace={result.trace_id}")
                called = {
                    call.name for call in result.runtime_result.tool_calls
                    if call.status in {"ok", "partial"}
                }
                if args.agent_query_mode == "both" and not {"lexical_search", "semantic_search"}.issubset(called):
                    raise RuntimeError(f"production Agent did not execute both retrieval tools: {sorted(called)}")
                if not {"lexical_search", "semantic_search"} & called:
                    raise RuntimeError("production Agent did not execute a successful retrieval tool")
                cited: list[dict[str, object]] = []
                for block_id, evidence_id, reference in cited_message_sources(result.answer_artifact):
                    if reference.internal_message_id not in expected_ids:
                        continue
                    # 来源查看重新读 Canonical JSON，不能只依据答案内的 display snapshot。
                    context = application.inspect_message_source(reference, scope, before=1, after=1)
                    recovered = next(
                        (message for message in context if message.internal_message_id == reference.internal_message_id),
                        None,
                    )
                    if recovered is None:
                        raise RuntimeError("cited child was not recovered from canonical source")
                    # 实际快照必须保留相同父子位置、原始时间与转发时间。
                    if (
                        reference.snapshot is None
                        or reference.snapshot.forward != recovered.forward
                        or reference.snapshot.timestamp_ms != recovered.timestamp
                        or reference.snapshot.source_message_id != recovered.source_message_id
                    ):
                        raise RuntimeError("cited snapshot does not match the recovered child provenance")
                    cited.append({
                        "content_block_id": block_id, "evidence_id": evidence_id,
                        "source": asdict(reference), "context": [asdict(message) for message in context],
                    })
                if not cited:
                    raise RuntimeError(f"Agent did not cite the actual matching child for {keyword}")
                report.update({"trace_id": result.trace_id, "cited_children": cited, "called_tools": sorted(called)})
            reports.append(report)
            # 每个已完成 case 都立即保存；后续失败仍保留之前的核验事实。
            _save(args.output / "report.json", reports)
            print(json.dumps({"keyword": keyword, "status": "verified", "semantic_matches": len(matched_ids)}, ensure_ascii=False), flush=True)


def main() -> None:
    """只执行用户显式指定的数据范围；Agent 网络请求由开关启用。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    parser.add_argument("--semantic-index", type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--keyword", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-agent", action="store_true")
    parser.add_argument("--agent-query-mode", choices=("both", "natural"), default="both")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    load_environment_file(args.env_file)
    asyncio.run(verify(args))


if __name__ == "__main__":
    main()
