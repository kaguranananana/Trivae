#!/usr/bin/env python3
"""授权后核验真实 ChatGPT 模型的生产 Query、工具、来源和多轮会话。"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.query.contracts import QueryRequest
from trivae.query.streaming import QueryStreamEvent


async def verify(database: Path, output: Path, topic: str, session_id: str | None) -> None:
    """四个真实查询顺序运行，失败保留证据并停止后续请求。"""

    # 配置预检必须早于任何推理，避免误用现有付费 Provider。
    settings = load_settings()
    if settings.provider != "chatgpt-plan":
        raise ValueError("verification requires TRIVAE_MODEL_PROVIDER=chatgpt-plan")
    # 新建输出目录，保留历史验证而不覆盖 DeepSeek Baseline。
    output.mkdir(parents=True, exist_ok=False)
    # 目录校验由生产 Responses Model 执行，并与同一 Auth Manager 的账号绑定。
    # 验证脚本不创建额外认证客户端或重复查询目录，避免另建一条非生产预检链路。
    scope = ExecutionScope(allowed_session_ids=None if session_id is None else (session_id,))
    queries = (
        ("fact", f"请找出群里提到 {topic} 的一条具体消息，说明谁说了什么并引用原消息。"),
        ("analysis", f"调查 {topic} 的群聊讨论，先检索关键消息，再对比不同人的看法，形成有来源的证据链。"),
        ("followup", "接着上一轮，对其中一个有明确来源的观点补充原始上下文，说明能确认和不能确认的内容。"),
        ("structured", f"统计群里包含 {topic} 的消息数量，给出统计口径及来源引用，并说明数据限制。"),
    )
    conversation_id: str | None = None
    async with create_application(database) as application:
        for case_name, query in queries:
            events: list[dict[str, object]] = []

            def capture(event: QueryStreamEvent) -> None:
                """只保存规范化事件元数据，隐藏推理和凭证不会进入文件。"""

                events.append({"type": event.type, "sequence": event.sequence, "tool_name": event.tool_name})

            # fact/analysis 是独立查询；followup 必须复用分析轮的持久化会话。
            request = QueryRequest(
                query=query, scope=scope,
                conversation_id=conversation_id if case_name == "followup" else None,
                trace_profile="debug",
            )
            result = await application.query(request, on_event=capture)
            if result.trace_id is None:
                raise RuntimeError("production query did not return a Trace ID")
            trace = application.read_trace(result.trace_id)
            log_path = application.export_trace_log(result.trace_id, output_path=output / f"{case_name}.log")
            report = {
                "case": case_name, "query": query, "configuration": settings.to_safe_dict(),
                "successful": result.is_successful, "termination": result.termination,
                "conversation_id": result.conversation_id, "trace_id": result.trace_id,
                "events": events, "trace": asdict(trace), "trace_log": str(log_path),
                "runtime": asdict(result.runtime_result),
                "answer": None if result.answer_artifact is None else asdict(result.answer_artifact),
                "finalization_status": result.finalization_status,
            }
            # 失败也先留完整事实；绝不重试、修改证据契约或伪造成功。
            (output / f"{case_name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if not result.is_successful or result.answer_artifact is None:
                raise RuntimeError(f"{case_name}: query failed; inspect {result.trace_id}")
            if not result.runtime_result.tool_calls or not result.answer_artifact.citation_bindings:
                raise RuntimeError(f"{case_name}: missing actual tool execution or validated citations")
            event_types = {event["type"] for event in events}
            if not {"query.completed", "answer.completed", "tool.completed"}.issubset(event_types):
                raise RuntimeError(f"{case_name}: expected stream/tool completion events were not received")
            # 传输终态来自实际 Responses 流，不能只依据 HTTP 200 或 Runtime 自述。
            observations = [item.payload.get("provider_observation") for item in trace.timeline]
            attempts = [
                attempt for observation in observations if isinstance(observation, dict)
                for attempt in observation.get("transport_attempts", []) if isinstance(attempt, dict)
            ]
            if not attempts or not all(attempt.get("stream_completed") is True for attempt in attempts):
                raise RuntimeError(f"{case_name}: Responses stream completion is unverified")
            conversation_id = result.conversation_id
            print(json.dumps({"case": case_name, "status": "verified", "trace_id": result.trace_id}, ensure_ascii=False))


def main() -> None:
    """只读取显式本地配置；OAuth 登录由独立 auth 命令完成。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--topic", default="Trellis")
    parser.add_argument("--session-id")
    args = parser.parse_args()
    load_environment_file(args.env_file)
    asyncio.run(verify(args.database, args.output, args.topic, args.session_id))


if __name__ == "__main__":
    main()
