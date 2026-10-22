"""当前Plan与默认可信容量的14天总结探针：冻结快照、单次执行、完整记账。"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from dataclasses import asdict
from pathlib import Path

from scripts.run_quality_repair_iteration import SOURCE, application_for
from scripts.run_runtime_budget_followup import RequestLedger, configured_runtime, read_json, write_json
from trivae.capabilities import ExecutionScope
from trivae.config.limits import DEFAULT_TRUSTED_RESULT_LIMIT
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation.contracts import DatasetSnapshot
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.prompt import SYSTEM_PROMPT

QUERY = "最近两周大家主要在聊什么方向的内容？"


async def prepare(root: Path, *, query: str = QUERY, snapshot_template: Path | None = None) -> None:
    """新建独立探针；不改旧14天题的max_results=100或人工标注。"""
    root.mkdir(parents=True, exist_ok=False)
    (root / "snapshot").mkdir()
    # 同一语料重复重建曾耗尽磁盘；只有显式指定已冻结模板时才复用其写时复制快照。
    source = SOURCE if snapshot_template is None else snapshot_template / "snapshot"
    for name in ("trivae.sqlite3", "trivae.semantic.sqlite3"):
        subprocess.run(["cp", "-c", str(source / name), str(root / "snapshot" / name)], check=True)
    if snapshot_template is None:
        index = SQLiteLexicalIndex(root / "snapshot/trivae.sqlite3")
        try:
            build = asdict(index.rebuild())
        finally:
            index.close()
    else:
        frozen = read_json(snapshot_template / "protocol.json")
        observed = DatasetSnapshot.from_database(root / "snapshot/trivae.sqlite3").to_dict()
        # 观察时间不属于语料身份；其他快照字段必须仍与模板一致。
        observed["created_at"] = frozen["snapshot"]["created_at"]
        if observed != frozen["snapshot"]:
            raise RuntimeError("reused temporal snapshot differs from its frozen template")
        repository = SQLiteCanonicalReadRepository(root / "snapshot/trivae.sqlite3")
        try:
            # 复用现有策略/版本/计数校验；旧索引直接报错，不能静默重建或降级。
            repository._ensure_lexical_ready()
        finally:
            repository.close()
        build = {"reused_from": str(snapshot_template), "source_build": frozen["lexical_build"]}
    runtime = configured_runtime()
    application = application_for(root, "temporal", runtime)
    try:
        semantic = application.semantic_index_status().to_dict()
        assert semantic["status"] == "completed", "semantic index is not ready"
        protocol = {
            "query": query,
            "scope": asdict(ExecutionScope(max_results=DEFAULT_TRUSTED_RESULT_LIMIT)),
            "snapshot": DatasetSnapshot.from_database(root / "snapshot/trivae.sqlite3").to_dict(),
            "semantic": semantic,
            "lexical_build": build,
            "runtime": runtime.safe_configuration(),
            "system_prompt": SYSTEM_PROMPT,
            "script": Path(__file__).read_text(),
            "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "automatic_retries": False,
            "judge": False,
            "old_gt_modified": False,
        }
        write_json(root / "protocol.json", protocol, exclusive=True)
        write_json(
            root / "http-ledger.json",
            {"maximum": 8, "maximum_per_case": 8, "used": 0, "attempts": [], "blocked": [], "attempted_cases": []},
            exclusive=True,
        )
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
        if (
            snapshot != protocol["snapshot"]
            or runtime.safe_configuration() != protocol["runtime"]
            or SYSTEM_PROMPT != protocol["system_prompt"]
            or Path(__file__).read_text() != protocol["script"]
            or revision != protocol["code_version"]
            or changes
        ):
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
        result = await application.query(
            QueryRequest(
                query=protocol["query"],
                scope=ExecutionScope(**protocol["scope"]),
                execution_override=ExecutionOverride(forced_route="standard_execution"),
            )
        )
        record.update(
            status=result.execution_status, result=asdict(result), http_requests=read_json(ledger_path)["used"]
        )
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
    parser.add_argument("--query", default=QUERY, help="prepare时冻结待验证的原始问题")
    parser.add_argument("--snapshot-template", type=Path, help="prepare时显式克隆已登记的有效快照，避免重复重建")
    args = parser.parse_args()
    asyncio.run(prepare(args.root, query=args.query, snapshot_template=args.snapshot_template)
                if args.action == "prepare" else run(args.root))
