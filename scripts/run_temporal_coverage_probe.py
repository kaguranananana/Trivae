"""当前Plan与默认可信容量的14天总结探针：冻结快照、单次执行、完整记账。"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from scripts.run_quality_repair_iteration import SOURCE, application_for
from scripts.run_runtime_budget_followup import RequestLedger, configured_runtime, read_json, write_json
from trivae.capabilities import ExecutionScope
from trivae.config.limits import DEFAULT_TRUSTED_RESULT_LIMIT
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.evaluation.contracts import DatasetSnapshot
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime import openai_adapter
from trivae.query.runtime.openai_tools import GetRecentMessagesSDKToolAdapter
from trivae.query.runtime.prompt import SYSTEM_PROMPT

QUERY = "最近两周大家主要在聊什么方向的内容？"


@contextmanager
def stratified_plan():
    """仅实验替换取证建议，沿用现有工具/分页/Scope/预算，不新增生产fallback。"""
    old = "Read\nthe real recent window FIRST for time-determined questions (prefer `limit` at or near the schema maximum),\nthen identify, cluster, and summarize noteworthy topics from the returned messages."
    new = ("Read the real window FIRST for time-determined questions. For summaries over long windows, "
           "begin with limit=20 to resolve the exact time range and total count while preserving "
           "evidence budget. When that page is partial, spend the next round on a few disjoint "
           "subwindows spread across the whole resolved range, using modest per-window limits; "
           "do not repeatedly page only the same recent tail. Use the returned absolute start/end "
           "timestamps, keep every subwindow within them, and leave budget for relevant context. "
           "Summarize only supported themes, explicitly describing sampled rather than complete coverage.")
    assert SYSTEM_PROMPT.count(old) == 1, "temporal planning prompt changed"
    prompt = SYSTEM_PROMPT.replace(old, new)
    original = GetRecentMessagesSDKToolAdapter.as_sdk_tool

    def as_sdk_tool(adapter, **kwargs):
        tool = original(adapter, **kwargs)
        old_hint = ("Prefer limit at or near the schema maximum for broad recent-activity questions "
                    "so a two-day overview is not needlessly partial.")
        assert tool.description.count(old_hint) == 1, "temporal tool hint changed"
        tool.description = tool.description.replace(old_hint,
            "For long-window summaries, start with limit=20 to resolve the window and count, "
            "then inspect a few disjoint subwindows across it with modest limits before synthesis. "
            "Keep budget for those calls and distinguish sampling from complete coverage.")
        return tool

    with patch.object(openai_adapter, "SYSTEM_PROMPT", prompt), patch.object(
            GetRecentMessagesSDKToolAdapter, "as_sdk_tool", as_sdk_tool):
        yield


async def prepare(root: Path, *, candidate: bool = False) -> None:
    """新建独立探针；不改旧14天题的max_results=100或人工标注。"""
    root.mkdir(parents=True, exist_ok=False)
    (root / "snapshot").mkdir()
    for name in ("trivae.sqlite3", "trivae.semantic.sqlite3"):
        subprocess.run(["cp", "-c", str(SOURCE / name), str(root / "snapshot" / name)], check=True)
    index = SQLiteLexicalIndex(root / "snapshot/trivae.sqlite3")
    try:
        build = asdict(index.rebuild())
    finally:
        index.close()
    runtime = configured_runtime()
    application = application_for(root, "temporal", runtime)
    try:
        semantic = application.semantic_index_status().to_dict()
        assert semantic["status"] == "completed", "semantic index is not ready"
        protocol = {"stratified_plan": candidate, "query": QUERY, "scope": asdict(ExecutionScope(max_results=DEFAULT_TRUSTED_RESULT_LIMIT)),
            "snapshot": DatasetSnapshot.from_database(root / "snapshot/trivae.sqlite3").to_dict(),
            "semantic": semantic, "lexical_build": build, "runtime": runtime.safe_configuration(),
            "system_prompt": SYSTEM_PROMPT, "script": Path(__file__).read_text(),
            "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "automatic_retries": False, "judge": False, "old_gt_modified": False}
        write_json(root / "protocol.json", protocol, exclusive=True)
        write_json(root / "http-ledger.json", {"maximum": 8, "maximum_per_case": 8,
            "used": 0, "attempts": [], "blocked": [], "attempted_cases": []}, exclusive=True)
    finally:
        await application.aclose()
    print({"prepared": "temporal", "scope_max_results": DEFAULT_TRUSTED_RESULT_LIMIT}, flush=True)


async def run(root: Path) -> None:
    """仅观察当前自主策略；覆盖不足与事实错误分开判定。"""
    protocol = read_json(root / "protocol.json")
    ledger_path = root / "http-ledger.json"
    ledger = read_json(ledger_path)
    if ledger["attempted_cases"]:
        raise RuntimeError("probe already attempted")
    runtime = configured_runtime()
    application = application_for(root, "temporal", runtime)
    record = {"transport": []}
    try:
        snapshot = DatasetSnapshot.from_database(root / "snapshot/trivae.sqlite3").to_dict()
        snapshot["created_at"] = protocol["snapshot"]["created_at"]
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        changes = subprocess.check_output(["git", "diff", "--name-only", "--", "src"], text=True).strip()
        if (snapshot != protocol["snapshot"] or runtime.safe_configuration() != protocol["runtime"]
                or SYSTEM_PROMPT != protocol["system_prompt"] or Path(__file__).read_text() != protocol["script"]
                or revision != protocol["code_version"] or changes):
            raise RuntimeError("frozen temporal probe conditions changed")
        await runtime._model._validate_model()
        ledger["attempted_cases"].append("temporal")
        write_json(ledger_path, ledger)
        runtime._model._client.event_hooks["request"].append(RequestLedger(ledger_path, "temporal").before_request)
        observer = runtime._model._observer

        def observe(value):
            record["transport"].append(dict(value))
            write_json(root / "temporal/result.json", record)
            observer(value)

        runtime._model._observer = observe
        with stratified_plan() if protocol["stratified_plan"] else nullcontext():
            result = await application.query(QueryRequest(query=QUERY,
                scope=ExecutionScope(**protocol["scope"]),
                execution_override=ExecutionOverride(forced_route="standard_execution")))
        record.update(status=result.execution_status, result=asdict(result), http_requests=read_json(ledger_path)["used"])
        print({"status": result.execution_status, "http_requests": record["http_requests"]}, flush=True)
    except Exception as exc:
        record.update(status="exception", error_type=type(exc).__name__)
        raise
    finally:
        write_json(root / "temporal/result.json", record)
        await application.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stratified-plan", action="store_true", help="仅prepare登记实验取证指导，不修改生产Prompt")
    args = parser.parse_args()
    asyncio.run(prepare(args.root, candidate=args.stratified_plan) if args.action == "prepare" else run(args.root))
