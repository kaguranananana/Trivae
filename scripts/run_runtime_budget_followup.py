"""运行既有 Development Case 的 Medium 可靠性验证；请求上限从持久化账本读取。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

import httpx

from trivae.bootstrap.application import create_application
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_router_jev_settings, load_settings
from trivae.conversation import SQLiteConversationStore
from trivae.evaluation.contracts import DatasetSnapshot, EvaluationCaseBundle, utc_now
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.query.runtime.prompt import SYSTEM_PROMPT

ROOT = Path("data/evaluation/runtime-budget-followup-20261022")
PARENT_LEDGER = Path("data/evaluation/runtime-budget-20261022/http-ledger.json")
TOOLS = ("lexical_search", "semantic_search", "get_recent_messages", "get_message_context",
         "find_members", "get_schema", "execute_sql")
CASES = {
    "matt": (Path("data/evaluation/gpt-high-ablation-20261018/resume-cases/dev-context-mattpocock-1.json"),
             Path("data/evaluation/gpt-high-ablation-20261018/resume-snapshot/trivae.sqlite3")),
    "miner": (Path("data/evaluation/tool-round-budget-20261021/cases/budget-dev-lexical-resume-miner.json"),
              Path("data/evaluation/tool-round-budget-20261021/trivae.sqlite3")),
    "written": (Path("data/evaluation/tool-round-budget-20261021/cases/budget-dev-para-written-test.json"),
                Path("data/evaluation/tool-round-budget-20261021/trivae.sqlite3")),
    "archify": (Path("data/evaluation/tool-round-budget-20261021/cases/budget-dev-context-archify.json"),
                Path("data/evaluation/tool-round-budget-20261021/trivae.sqlite3")),
}
INITIAL_CASES = ("matt", "miner", "written")


def protocol_path(label: str) -> Path:
    """修复后新 Case 使用独立冻结清单，保留前三条原始实验条件。"""
    return ROOT / ("protocol-after-limit-fix.json" if label == "archify" else "protocol.json")


def read_json(path: Path) -> Any:
    """读取本地实验事实；格式错误直接暴露。"""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object, *, exclusive: bool = False) -> None:
    """关键状态写入并同步落盘，禁止发送后才补记请求次数。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


class RequestBudgetExceeded(RuntimeError):
    """实验门禁拒绝未发送请求，不能归因为产品 Tool Result 预算故障。"""


class RequestLedger:
    """单进程顺序实验共享账本；预算调整保留历史计数，旧轮次账本只读。"""

    def __init__(self, path: Path, case: str) -> None:
        self.path = path
        self.case = case

    async def before_request(self, request: httpx.Request) -> None:
        """在真实推理 client 边界检查身份、预扣次数并持久化；不记录认证头。"""
        if str(request.url) != "https://api.openai.com/v1/responses" or request.method != "POST":
            raise RuntimeError("experiment inference endpoint changed")
        body = json.loads(request.content)
        if body["model"] != "gpt-6.1-sol" or body["reasoning"]["effort"] != "medium":
            raise RuntimeError("experiment provider/model/effort changed")
        ledger = read_json(self.path)
        used_for_case = sum(item["case"] == self.case for item in ledger["attempts"])
        if ledger["used"] >= ledger["maximum"] or used_for_case >= ledger["maximum_per_case"]:
            # 超额请求不发送、不计入已发送 HTTP，但保留独立实验失败事实。
            ledger["blocked"].append({"case": self.case, "at": utc_now(), "reason": "EXPERIMENT_HTTP_LIMIT"})
            write_json(self.path, ledger)
            raise RequestBudgetExceeded("EXPERIMENT_HTTP_LIMIT: request blocked before send")
        # 此段无 await；同进程顺序请求不能在读取与预扣之间互相超卖。
        ledger["used"] += 1
        ledger["attempts"].append({
            "number": ledger["used"], "case": self.case, "before_send": utc_now(),
            "actual_http_projection": {key: body[key] for key in ("model", "reasoning", "store", "stream")},
            "tools_present": bool(body.get("tools")),
        })
        write_json(self.path, ledger)


def configured_runtime() -> OpenAIAgentsRuntimeAdapter:
    """只使用本机已配置的 Plan Medium，不注入 API key 或独立 Router shadow。"""
    load_environment_file(None)
    settings = load_settings()
    if (settings.provider, settings.model_name, settings.chatgpt_reasoning_effort) != (
        "chatgpt-plan", "gpt-6.1-sol", "medium",
    ):
        raise RuntimeError("follow-up requires the authorized ChatGPT Plan Medium configuration")
    if settings.max_tool_rounds != 3 or settings.max_turns != 8 or load_router_jev_settings().enabled:
        raise RuntimeError("production budgets or independent Jev configuration changed")
    return OpenAIAgentsRuntimeAdapter(settings=settings)


def open_application(label: str, runtime: OpenAIAgentsRuntimeAdapter) -> Any:
    """复用原 Case 对应快照；所有新会话、Evaluation 与 Trace 写到独立 ignored 目录。"""
    _, database = CASES[label]
    output = ROOT / label
    output.mkdir(parents=True, exist_ok=True)
    application = create_application(
        database, agent_runtime=runtime,
        semantic_index_path=database.with_name("trivae.semantic.sqlite3"),
        trace_store=SQLiteTraceStore(output / "trace.sqlite3"),
        conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"),
        evaluation_database_path=output / "evaluation.sqlite3", feedback_database_path=output / "feedback.sqlite3",
    )
    runtime.capability_registry = application.capability_registry
    return application


def inspect_case(label: str, application: Any) -> tuple[EvaluationCaseBundle, DatasetSnapshot, dict[str, object]]:
    """核对原 Snapshot 和现有语义索引；禁止重绑 GT、忽略 stale 或自动重建。"""
    file, database = CASES[label]
    case = EvaluationCaseBundle.from_json(file)
    snapshot = DatasetSnapshot.from_database(database)
    if snapshot.snapshot_id != case.dataset_snapshot.snapshot_id:
        raise RuntimeError(f"{label}: original Case snapshot no longer matches")
    semantic = application.semantic_index_status().to_dict()
    if semantic["status"] != "completed" or semantic["indexed_message_count"] != snapshot.message_count:
        raise RuntimeError(f"{label}: semantic index is not ready; do not rebuild it in this experiment")
    return case, snapshot, semantic


async def prepare(*, after_fix: bool = False) -> None:
    """真实请求前冻结全部条件；旧四请求记录既不清零，也不写回。"""
    if read_json(PARENT_LEDGER)["used"] != 4:
        raise RuntimeError("parent experiment ledger changed")
    labels = ("archify",) if after_fix else INITIAL_CASES
    # 后续阶段共享已预扣的账本，只读取授权后上限，绝不重置已有请求。
    limits = read_json(ROOT / "http-ledger.json") if after_fix else {"maximum": 12, "maximum_per_case": 4}
    protocol: dict[str, Any] = {
        "created_at": utc_now(), "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "additional_http_maximum": limits["maximum"], "maximum_per_case": limits["maximum_per_case"], "parent_http_used": 4,
        "automatic_retries": False, "judge": False, "forced_route": "standard_execution",
        "tools": TOOLS, "system_prompt": SYSTEM_PROMPT, "order": list(labels), "cases": {},
    }
    for label in labels:
        runtime = configured_runtime()
        application = open_application(label, runtime)
        try:
            case, snapshot, semantic = inspect_case(label, application)
            protocol["cases"][label] = {
                "case_id": case.case_id, "case_version": case.version, "snapshot": snapshot.to_dict(),
                "semantic_index": semantic, "runtime": runtime.safe_configuration(),
                "query": case.query, "scope": case.to_dict()["data_access_scope"],
                "reference_findings": case.to_dict()["reference_findings"],
            }
            print(json.dumps({"preflight": label, "snapshot_matches": True, "messages": snapshot.message_count,
                              "semantic_status": semantic["status"]}), flush=True)
        finally:
            await application.aclose()
    write_json(protocol_path(labels[0]), protocol, exclusive=True)
    if not after_fix:
        # 仅首轮预检允许创建账本；exclusive 禁止覆盖旧计数。
        write_json(ROOT / "http-ledger.json", {"maximum": 12, "maximum_per_case": 4, "used": 0,
                                               "attempts": [], "blocked": [], "attempted_cases": []}, exclusive=True)


async def run_case(label: str) -> None:
    """每个预先登记的 Case 最多运行一次；失败工件先保存，禁止为好结果补跑。"""
    protocol = read_json(protocol_path(label))
    runtime = configured_runtime()
    application = open_application(label, runtime)
    output = ROOT / label
    record: dict[str, Any] = {"case": label, "transport": [], "events": []}
    started = perf_counter()
    try:
        case, snapshot, semantic = inspect_case(label, application)
        frozen = protocol["cases"][label]
        if (snapshot.snapshot_id != frozen["snapshot"]["snapshot_id"] or semantic != frozen["semantic_index"]
                or runtime.safe_configuration() != frozen["runtime"] or SYSTEM_PROMPT != protocol["system_prompt"]):
            raise RuntimeError("frozen experiment conditions changed")
        ledger = read_json(ROOT / "http-ledger.json")
        if label in ledger["attempted_cases"]:
            raise RuntimeError("Case already attempted; do not repeat")
        # 使用生产模型目录验证，预检网络失败不占推理次数；不跳过或缓存替代认证检查。
        await runtime._model._validate_model()
        ledger["attempted_cases"].append(label)
        write_json(ROOT / "http-ledger.json", ledger)
        before = ledger["used"]
        runtime._model._client.event_hooks["request"].append(RequestLedger(ROOT / "http-ledger.json", label).before_request)
        original_observer = runtime._model._observer

        def transport_observer(observation: Mapping[str, object]) -> None:
            # 无论后续 JSON/Finalizer 是否失败，都先保存生产安全投影和已知 Usage。
            record["transport"].append(dict(observation))
            write_json(output / "result.json", record)
            original_observer(observation)

        runtime._model._observer = transport_observer
        captured: dict[str, Any] = {}

        async def query(request: QueryRequest) -> Any:
            def event_observer(event: Any) -> None:
                # 不持久化 delta/推理正文；最终答案和允许保存的工具投影由原 Trace 契约负责。
                record["events"].append({"type": event.type, "sequence": event.sequence, "tool_name": event.tool_name})
            result = await application.query(request, on_event=event_observer)
            captured["result"] = result
            return result

        runner = EvaluationRunner(query_executor=query, trace_reader=application.read_trace,
                                  store=application.evaluation_store, snapshot_resolver=lambda: snapshot)
        variant = ControlledVariant(
            variant_id="runtime-budget-followup-20261022:medium", code_version=protocol["code_version"],
            provider="chatgpt-plan", model="gpt-6.1-sol", available_tools=TOOLS,
            model_parameters={"reasoning_effort": "medium"}, prompt_identity="production-system-prompt",
            budget={"max_tool_rounds": 3, "max_turns": 8}, runtime_configuration={"trace_profile": "debug"},
            execution_override=ExecutionOverride(forced_route="standard_execution"),
        )
        evaluation = (await runner.run_case(case, variant, suite_id="runtime-budget-followup-development"))[0]
        result = captured["result"]
        record.update(status=result.execution_status, evaluation=evaluation.to_dict(), result=asdict(result))
        if result.trace_id is not None:
            application.export_trace_log(result.trace_id, output_path=output / "trace.log", context_mode="full")
        record["http_requests"] = read_json(ROOT / "http-ledger.json")["used"] - before
        print(json.dumps({"case": label, "status": result.execution_status, "http_requests": record["http_requests"],
                          "tool_rounds": result.runtime_result.tool_rounds,
                          "runtime_error": result.runtime_result.error.code if result.runtime_result.error else None}), flush=True)
    except Exception as exc:
        record.update(status="exception", error_type=type(exc).__name__)
        write_json(output / "result.json", record)
        raise
    finally:
        record["wall_seconds"] = perf_counter() - started
        write_json(output / "result.json", record)
        await application.aclose()


def main() -> None:
    """预检和每条 Case 分开执行，便于在失败后先定位原因，而非自动补跑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "prepare-postfix", *CASES))
    action = parser.parse_args().action
    asyncio.run(prepare(after_fix=action == "prepare-postfix") if action.startswith("prepare") else run_case(action))


if __name__ == "__main__":
    main()
