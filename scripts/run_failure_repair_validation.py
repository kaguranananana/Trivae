"""冻结一份语料和索引，逐题验收当前修复；不重试、不重算索引、不调用 Judge。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from scripts.run_runtime_budget_followup import RequestLedger, write_json
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.conversation import SQLiteConversationStore
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.query.runtime.prompt import SYSTEM_PROMPT

CASES = {
    "written": "dev-para-written-test", "nanobot": "dev-cite-nanobot",
    "matt": "dev-context-mattpocock-1", "archify": "dev-context-archify", "owner": "dev-para-intern-owner",
}
UNITS = ("written-1", "nanobot-1", "matt-1", "archify-1", "owner-1", "empty-1", "written-2")


def prepare(root: Path) -> None:
    """同时持有两个源库的只读快照，确认 revision 一致后各备份一次。"""

    snapshot = root / "snapshot"
    snapshot.mkdir(parents=True, exist_ok=False)
    with (
        closing(sqlite3.connect("file:data/trivae.sqlite3?mode=ro", uri=True)) as canonical,
        closing(sqlite3.connect("file:data/trivae.semantic.sqlite3?mode=ro", uri=True)) as semantic,
    ):
        # 读事务固定同一观察版本，后台增量导入不会使这次备份在中途换语料。
        canonical.execute("BEGIN")
        revision = int(canonical.execute(
            "SELECT value FROM trivae_derived_meta WHERE key='canonical_revision'"
        ).fetchone()[0])
        message_count = canonical.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        semantic.execute("BEGIN")
        state = semantic.execute(
            "SELECT status, canonical_revision, indexed_message_count FROM semantic_index_state WHERE state_id=1"
        ).fetchone()
        if state != ("completed", revision, message_count):
            raise RuntimeError(f"cannot freeze mismatched indexes: canonical={revision}/{message_count}, semantic={state}")
        for source, name in ((canonical, "trivae.sqlite3"), (semantic, "trivae.semantic.sqlite3")):
            # 使用 SQLite 备份协议，不复制正在写入的数据库文件，不创建每题语料副本。
            with closing(sqlite3.connect(snapshot / name)) as destination:
                source.backup(destination, pages=512)
    queries = {}
    for label, case_id in CASES.items():
        value = json.loads((Path("evaluation/cases/benchmark/dev") / f"{case_id}.json").read_text())
        queries[label] = {"case_id": case_id, "query": value["query"]}
    queries["empty"] = {"case_id": "diagnostic:incomplete-empty", "query": "搜索完整关键词“量子香蕉数据库”，能找到原文吗？"}
    settings = load_settings()
    if (settings.provider, settings.model_name, settings.chatgpt_reasoning_effort) != (
        "chatgpt-plan", "gpt-6.1-sol", "medium",
    ):
        raise RuntimeError("validation requires the existing Plan / gpt-6.1-sol / medium configuration")
    protocol = {
        "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "canonical_revision": revision, "message_count": message_count, "model": settings.to_safe_dict(),
        "system_prompt": SYSTEM_PROMPT, "scope": {"allowed_session_ids": None, "max_results": 5000},
        "forced_route": "standard_execution", "units": UNITS, "queries": queries,
        "judge": False, "automatic_retries": False,
    }
    write_json(root / "protocol.json", protocol, exclusive=True)
    write_json(root / "http-ledger.json", {
        "used": 0, "maximum": 48, "maximum_per_case": 8, "attempts": [], "blocked": [],
    }, exclusive=True)
    print(json.dumps({"prepared": True, "revision": revision, "messages": message_count}), flush=True)


async def run_unit(root: Path, unit: str) -> None:
    """只运行指定独立样本，先记发送账本，再保存完整成功或失败。"""

    protocol = json.loads((root / "protocol.json").read_text())
    if unit not in protocol["units"]:
        raise ValueError(f"unit was not registered: {unit}")
    output = root / unit
    output.mkdir(exist_ok=False)
    settings = load_settings()
    if settings.to_safe_dict() != protocol["model"] or SYSTEM_PROMPT != protocol["system_prompt"]:
        raise RuntimeError("frozen model configuration or prompt changed")
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if current != protocol["code_version"]:
        raise RuntimeError("execution commit changed after preparation")
    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    snapshot = root / "snapshot"
    application = create_application(
        snapshot / "trivae.sqlite3", agent_runtime=runtime,
        semantic_index_path=snapshot / "trivae.semantic.sqlite3",
        conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"),
        trace_store=SQLiteTraceStore(output / "trace.sqlite3"),
        evaluation_database_path=output / "evaluation.sqlite3", feedback_database_path=output / "feedback.sqlite3",
    )
    runtime.capability_registry = application.capability_registry
    # 复用已验证的发送前持久化计数；全系列共享次数，每个独立样本最多 8 次真实 HTTP。
    runtime._model._client.event_hooks["request"].append(RequestLedger(root / "http-ledger.json", unit).before_request)
    observer = runtime._model._observer
    observations = []

    def observe(value):
        observations.append(dict(value))
        write_json(output / "transport.json", observations)
        observer(value)

    runtime._model._observer = observe
    query = protocol["queries"][unit.rsplit("-", 1)[0]]["query"]
    try:
        # readiness 在任何推理请求前核对；失败保持明确错误，不自动重建索引。
        state = application.semantic_index_status()
        if state.status != "completed" or application.read_repository.canonical_revision() != protocol["canonical_revision"]:
            raise RuntimeError("frozen canonical or semantic index is not ready")
        result = await application.query(QueryRequest(
            query, ExecutionScope(max_results=5000), trace_profile="debug",
            execution_override=ExecutionOverride(forced_route="standard_execution"),
        ))
        write_json(output / "result.json", asdict(result), exclusive=True)
        if result.answer_artifact is not None:
            (output / "answer.md").write_text(result.answer_artifact.answer_text + "\n")
        print(json.dumps({"unit": unit, "successful": result.is_successful, "trace_id": result.trace_id,
                          "termination": result.termination, "finalization": result.finalization_status,
                          "tool_rounds": result.runtime_result.tool_rounds}, ensure_ascii=False), flush=True)
        if not result.is_successful:
            raise RuntimeError(f"query did not deliver a valid answer: {unit}")
    except Exception as exc:
        # 原始失败独立保留，下一次运行不能覆盖目录，也不把失败替换成成功样本。
        write_json(output / "failure.json", {"type": type(exc).__name__, "message": str(exc)}, exclusive=True)
        raise
    finally:
        await application.aclose()


def main() -> None:
    """准备与执行分开，执行时不修改源码、Prompt、预算和冻结输入。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "run"))
    parser.add_argument("--root", type=Path, default=Path("data/evaluation/failure-repair-20261023/live"))
    parser.add_argument("--units", nargs="+", choices=UNITS, default=UNITS)
    args = parser.parse_args()
    load_environment_file(None)
    if args.phase == "prepare":
        prepare(args.root)
    else:
        async def run():
            for unit in args.units:
                await run_unit(args.root, unit)
        asyncio.run(run())


if __name__ == "__main__":
    main()
