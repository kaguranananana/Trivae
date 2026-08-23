"""Trivae CLI：只做参数解析、Application 调用和结果投影。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Sequence, TextIO, cast

from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.capabilities.contracts import CapabilityContractError, ExecutionScope
from trivae.config.settings import SettingsError
from trivae.conversation.contracts import ConversationError
from trivae.data.model import ChatSession, IngestionError
from trivae.evaluation import (
    ControlledVariant,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationSuite,
)
from trivae.evaluation.review import M6_FAILURE_REGRESSION_MAP
from trivae.evaluation.store import EvaluationStoreError
from trivae.interfaces.cli_renderer import CliEventRenderer
from trivae.observability.sqlite import ImportDiagnosticsError, TraceStoreError
from trivae.query.contracts import QueryContractError, QueryRequest, QueryResult
from trivae.retrieval.structured import RetrievalError


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI parser，不在 import 时初始化数据库或外部服务。"""

    parser = argparse.ArgumentParser(prog="trivae", description="Trivae high-noise chat intelligence system")
    subparsers = parser.add_subparsers(dest="command")
    import_parser = subparsers.add_parser("import", help="Import QQ chat exports into the Canonical Store")
    import_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory containing QQChatExporter JSON files",
    )
    import_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    import_subparsers = import_parser.add_subparsers(dest="import_command")
    import_diagnostics_parser = import_subparsers.add_parser(
        "diagnostics",
        help="Read existing ImportBatch and ImportError diagnostics",
    )
    import_diagnostics_parser.add_argument("--batch-id", help="Filter one import batch")
    import_diagnostics_parser.add_argument("--source-file", help="Filter one source file")
    import_diagnostics_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite database path",
    )
    chat_parser = subparsers.add_parser("chat", help="Interactively query the Canonical chat store")
    chat_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    chat_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed route, plan, tool, retrieval, usage, and normalized event metadata",
    )
    trace_parser = subparsers.add_parser("trace", help="Read a persisted Trace projection")
    trace_subparsers = trace_parser.add_subparsers(dest="trace_command", required=True)
    trace_show_parser = trace_subparsers.add_parser("show", help="Show one Trace projection")
    trace_show_parser.add_argument("trace_id", help="Trace identity returned by QueryResult")
    trace_show_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite database path",
    )
    trace_export_parser = trace_subparsers.add_parser(
        "export",
        help="Export one Trace as a human-readable text log",
    )
    trace_export_parser.add_argument("trace_id", help="Trace identity returned by QueryResult")
    trace_export_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite database path",
    )
    trace_export_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional text log output path",
    )
    trace_export_parser.add_argument(
        "--view",
        choices=("transcript", "raw"),
        default="transcript",
        help="Text projection view; raw keeps normalized events instead of the human transcript",
    )
    trace_export_parser.add_argument(
        "--context",
        choices=("delta", "full"),
        default="delta",
        help="Model context detail for transcript view; full keeps every captured input per turn",
    )
    evaluation_parser = subparsers.add_parser("eval", help="Run local Evaluation against the production Query path")
    evaluation_subparsers = evaluation_parser.add_subparsers(dest="evaluation_command", required=True)
    eval_cases_parser = evaluation_subparsers.add_parser("cases", help="Validate versioned Evaluation Cases")
    eval_cases_subparsers = eval_cases_parser.add_subparsers(dest="cases_command", required=True)
    eval_cases_validate_parser = eval_cases_subparsers.add_parser("validate", help="Validate one Case or directory")
    eval_cases_validate_parser.add_argument("path", type=Path, help="Case JSON file or directory")
    eval_run_parser = evaluation_subparsers.add_parser("run", help="Execute a versioned Suite")
    eval_run_parser.add_argument("--suite", type=Path, required=True, help="Evaluation Suite JSON")
    eval_run_parser.add_argument("--variant", type=Path, required=True, help="Controlled Variant JSON")
    eval_run_parser.add_argument(
        "--cases-dir",
        type=Path,
        default=Path("evaluation/cases"),
        help="Directory containing versioned Case JSON files",
    )
    eval_run_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    eval_run_parser.add_argument(
        "--evaluation-database",
        type=Path,
        default=None,
        help="Independent SQLite Evaluation Store path",
    )
    eval_run_parser.add_argument("--repeat", type=int, default=1, help="Number of repetitions per Case")
    eval_show_parser = evaluation_subparsers.add_parser("show", help="Show one persisted Evaluation Run")
    eval_show_parser.add_argument("run_id", help="Evaluation Run identity")
    eval_show_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    eval_show_parser.add_argument(
        "--evaluation-database",
        type=Path,
        default=None,
        help="Independent SQLite Evaluation Store path",
    )
    eval_compare_parser = evaluation_subparsers.add_parser("compare", help="Build a blind paired comparison")
    eval_compare_parser.add_argument("--case", type=Path, required=True, help="Evaluation Case JSON")
    eval_compare_parser.add_argument("--baseline", required=True, help="Baseline Run identity")
    eval_compare_parser.add_argument("--candidate", required=True, help="Candidate Run identity")
    eval_compare_parser.add_argument("--baseline-variant", type=Path, required=True, help="Baseline Variant JSON")
    eval_compare_parser.add_argument("--candidate-variant", type=Path, required=True, help="Candidate Variant JSON")
    eval_compare_parser.add_argument("--seed", default=None, help="Blind randomization seed")
    eval_compare_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    eval_compare_parser.add_argument(
        "--evaluation-database",
        type=Path,
        default=None,
        help="Independent SQLite Evaluation Store path",
    )
    evaluation_subparsers.add_parser("regression", help="Show M6 failure regression coverage")
    diagnostics_parser = subparsers.add_parser(
        "import-diagnostics",
        help="Read existing ImportBatch and ImportError diagnostics",
    )
    diagnostics_parser.add_argument("--batch-id", help="Filter one import batch")
    diagnostics_parser.add_argument("--source-file", help="Filter one source file")
    diagnostics_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite database path",
    )
    return parser


def _load_variant(path: Path) -> ControlledVariant:
    """从 version-controlled JSON 读取 Variant；CLI 不在这里推断配置。"""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationContractError(f"variant JSON cannot be read: {path}") from exc
    return ControlledVariant.from_dict(payload)


def _case_paths(path: Path) -> tuple[Path, ...]:
    """解析单文件或 Case 目录，保持目录顺序确定。"""

    if path.is_file():
        return (path,)
    if path.is_dir():
        paths = tuple(sorted(path.glob("*.json")))
        if not paths:
            raise EvaluationContractError(f"Case directory contains no JSON files: {path}")
        return paths
    raise EvaluationContractError(f"Case path does not exist: {path}")


def _load_cases(path: Path) -> dict[str, EvaluationCaseBundle]:
    """加载 Case，并同时建立 identity 与 case_id 索引供 Suite reference 解析。"""

    cases: dict[str, EvaluationCaseBundle] = {}
    for case_path in _case_paths(path):
        case = EvaluationCaseBundle.from_json(case_path)
        cases[case.identity] = case
        cases[case.case_id] = case
    return cases


def _run_evaluation_command(args: argparse.Namespace) -> int:
    """Evaluation CLI 只调用 Application facade，不直接触碰 Runtime/Tool。"""

    try:
        if args.evaluation_command == "cases":
            if args.cases_command != "validate":
                raise EvaluationContractError("unsupported eval cases command")
            cases = _load_cases(args.path)
            identities = sorted({case.identity for case in cases.values()})
            print(json.dumps({"status": "valid", "cases": identities}, ensure_ascii=False, indent=2))
            return 0

        if args.evaluation_command == "regression":
            print(json.dumps(dict(M6_FAILURE_REGRESSION_MAP), ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.evaluation_command == "run":
            suite = EvaluationSuite.from_json(args.suite)
            variant = _load_variant(args.variant)
            cases = _load_cases(args.cases_dir)
            with create_application(
                args.database,
                evaluation_database_path=args.evaluation_database,
            ) as application:
                runs = asyncio.run(application.evaluate_suite(suite, cases, variant, repetitions=args.repeat))
            print(
                json.dumps(
                    {"suite": suite.identity, "variant": variant.to_dict(), "runs": [run.to_dict() for run in runs]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.evaluation_command == "show":
            with create_application(
                args.database,
                evaluation_database_path=args.evaluation_database,
            ) as application:
                run = application.read_evaluation_run(args.run_id)
            print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
            return 0

        if args.evaluation_command == "compare":
            case = EvaluationCaseBundle.from_json(args.case)
            baseline_variant = _load_variant(args.baseline_variant)
            candidate_variant = _load_variant(args.candidate_variant)
            with create_application(
                args.database,
                evaluation_database_path=args.evaluation_database,
            ) as application:
                comparison = application.compare_evaluation_runs(
                    case,
                    baseline_variant,
                    candidate_variant,
                    (args.baseline,),
                    (args.candidate,),
                    randomization_seed=args.seed,
                )
            print(json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2))
            return 0
    except (EvaluationContractError, EvaluationStoreError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    raise EvaluationContractError("unsupported eval command")


def _select_chat(
    sessions: tuple[ChatSession, ...],
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> tuple[ExecutionScope, str] | None:
    """读取一次可信群聊选择，并把选择编译成固定的 ExecutionScope。"""

    while True:
        try:
            # 选择发生在进入 Query 前，模型不会参与 scope 的派生。
            raw_choice = input_fn("Select chat > ").strip()
        except (EOFError, KeyboardInterrupt):
            # 选择阶段的 EOF/Ctrl+C 与聊天阶段一样属于正常退出。
            output_fn("Bye.")
            return None

        # 0 是 contract 约定的 unrestricted 选择，不创造特殊 session id。
        if raw_choice == "0":
            return ExecutionScope(allowed_session_ids=None), "All chats"

        # 只接受整数序号，错误输入留在 picker 内让用户重新选择。
        try:
            selected_number = int(raw_choice)
        except ValueError:
            output_fn("Invalid selection.")
            continue

        # 序号从 1 开始，映射到已排序的真实 ChatSession 列表。
        if 1 <= selected_number <= len(sessions):
            selected_session = sessions[selected_number - 1]
            # session id 是 trusted application state，不从用户自然语言或模型输出推导。
            scope = ExecutionScope(allowed_session_ids=(selected_session.session_id,))
            return scope, selected_session.name

        # 越界选择不改变 scope，也不离开交互模式。
        output_fn("Invalid selection.")


class _CallbackTextStream:
    """把 write/flush 文本流适配到旧的逐行 output_fn，专供可注入 CLI 测试使用。"""

    def __init__(self, output_fn: Callable[[str], None]) -> None:
        """保存逐行回调和仍未遇到换行的流式片段。"""

        self._output_fn = output_fn
        self._buffer = ""

    def write(self, content: str) -> int:
        """按换行边界交付完整行，连续 token 在测试投影中仍保持同一文本段。"""

        self._buffer += content
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", maxsplit=1)
            self._output_fn(line)
        return len(content)

    def flush(self) -> None:
        """回调没有独立缓冲设备；开放行由 Renderer 在段完成时显式关闭。"""


def _query_failure_message(result: QueryResult) -> str:
    """从 QueryResult 的正式错误投影生成可读失败信息，不读取 runtime_answer。"""

    # Finalization failure 是正式答案边界上的第一优先错误来源。
    if result.finalization_error is not None:
        return result.finalization_error.message
    # Runtime terminal error 已是 secret-safe projection，可直接展示给人工用户。
    if result.runtime_result.error is not None:
        return result.runtime_result.error.message
    # 没有更细错误时只展示稳定 termination，不猜测底层原因。
    return f"query did not complete: {result.termination}"


def _print_query_result(
    result: QueryResult,
    *,
    output_fn: Callable[[str], None],
    log_path: Path | None = None,
    log_error: str | None = None,
    answer_already_rendered: bool = False,
    failure_already_rendered: bool = False,
) -> None:
    """补齐未被 stream 投影的结果，并始终展示 Trace 与文本日志位置。"""

    # `is_successful` 与 `final_answer` 同时成立，才允许展示正式回答。
    if result.is_successful and result.final_answer is not None and not answer_already_rendered:
        output_fn("Trivae >")
        output_fn(result.final_answer)
    elif not result.is_successful and not failure_already_rendered:
        # 失败时明确暴露状态，绝不把 Runtime 原始文本当成用户答案。
        output_fn("Trivae >")
        output_fn(f"Error: {_query_failure_message(result)}")

    # 每一轮 Query 都沿用 Application 产生的 Trace identity，详细查看交给 trace CLI。
    if result.trace_id is not None:
        output_fn(f"[trace: {result.trace_id}]")
    if log_path is not None:
        # Application 返回绝对路径，终端通常可以直接点击定位本地文件。
        output_fn(f"[log: {log_path}]")
    elif log_error is not None:
        # 导出失败必须可见，但不能把已经得到的正式答案改写成失败。
        output_fn(f"[trace log unavailable: {log_error}]")


async def _run_interactive_chat(
    application: TrivaeApplication,
    *,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
    verbose: bool = False,
) -> int:
    """运行一段固定 session scope、可复用 Conversation 的交互式 Query loop。"""

    # 只在函数调用时解析默认 I/O，便于测试注入 scripted input 而不触碰 provider。
    read_input = input if input_fn is None else input_fn
    write_output = print if output_fn is None else output_fn
    # 真实终端直接接收 token write；注入 output_fn 时用逐行 adapter 保持既有测试接口。
    terminal_stream = sys.stdout if output_fn is None else cast(TextIO, _CallbackTextStream(write_output))

    # Session metadata 通过 Application facade 读取，CLI 不直接读 SQLite。
    sessions = application.list_sessions()
    if not sessions:
        write_output("No chats found in the Canonical Store.")
        return 1

    # 先展示稳定排序后的真实群聊，再提供 unrestricted 入口。
    write_output("Trivae interactive chat")
    write_output("")
    write_output("Available chats:")
    for index, session in enumerate(sessions, start=1):
        write_output(f"{index}. {session.name}")
    write_output("0. All chats")

    # picker 返回的 scope 在本次 CLI 生命周期内保持不变。
    selected = _select_chat(sessions, input_fn=read_input, output_fn=write_output)
    if selected is None:
        return 0
    scope, selected_name = selected
    write_output(f"Selected: {selected_name}")
    write_output("/new   Start a new conversation")
    write_output("/exit  Exit")

    # conversation_id 与 scope 是两个独立状态；/new 只会重置前者。
    conversation_id: str | None = None
    while True:
        try:
            raw_query = read_input("You > ")
        except (EOFError, KeyboardInterrupt):
            write_output("Bye.")
            return 0

        # 空白输入不构造 QueryRequest，继续等待下一条真实问题。
        query = raw_query.strip()
        if not query:
            continue

        # 两个退出命令共享同一正常结束行为，不触发 Query。
        if query in {"/exit", "/quit"}:
            write_output("Bye.")
            return 0

        # /new 只清空 Conversation identity，绝不改写已经选择的 trusted scope。
        if query == "/new":
            conversation_id = None
            write_output("Started a new conversation.")
            continue

        # 普通文本统一编译为正式 QueryRequest，并进入 Application Query path。
        request = QueryRequest(
            query=query,
            scope=scope,
            conversation_id=conversation_id,
            trace_profile="debug" if verbose else "normal",
        )
        renderer = CliEventRenderer(terminal_stream, verbose=verbose)
        try:
            # Application 仍执行唯一 Query 主链路；CLI 只订阅同源实时事件。
            result = await application.query(request, on_event=renderer.handle)
        finally:
            # 成功、分类错误、task cancellation 和 Ctrl+C 都必须恢复到完整终端行。
            renderer.finish()
        # QueryResult 是 Conversation identity 的正式返回边界，后续轮次复用它。
        conversation_id = result.conversation_id
        log_path: Path | None = None
        log_error: str | None = None
        if result.trace_id is not None:
            try:
                # 使用 Application facade 从 canonical Trace 生成完整日志，不在 CLI 读取 SQLite。
                log_path = application.export_trace_log(result.trace_id)
            except TraceStoreError as exc:
                # 文本日志是诊断 projection；失败时继续显示答案并保留明确原因。
                log_error = str(exc)
        _print_query_result(
            result,
            output_fn=write_output,
            log_path=log_path,
            log_error=log_error,
            answer_already_rendered=renderer.answer_rendered,
            failure_already_rendered=renderer.failure_rendered,
        )


def _run_chat_command(args: argparse.Namespace) -> int:
    """创建正式 Application 并运行 chat；已分类错误可读，未知错误继续暴露。"""

    try:
        # Application 统一拥有 Store、Provider、Conversation 和 Trace lifecycle。
        with create_application(args.database) as application:
            return asyncio.run(_run_interactive_chat(application, verbose=args.verbose))
    except (EOFError, KeyboardInterrupt):
        # Ctrl+D/Ctrl+C 即使发生在 Query 等待期间，也只做短退出提示。
        print("Bye.")
        return 0
    except (
        CapabilityContractError,
        ConversationError,
        QueryContractError,
        RetrievalError,
        SettingsError,
        TraceStoreError,
    ) as exc:
        # 这些错误已有稳定业务语义；只展示消息，不把它们伪装成成功答案。
        print(f"Error: {exc}")
        trace_id = getattr(exc, "trace_id", None)
        if isinstance(trace_id, str) and trace_id:
            print(f"[trace: {trace_id}]")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """执行 CLI；已分类 ingestion error 转成非零状态，未知异常继续暴露。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "chat":
        return _run_chat_command(args)
    if args.command == "eval":
        return _run_evaluation_command(args)
    if args.command == "trace":
        try:
            with create_application(args.database) as application:
                if args.trace_command == "show":
                    trace_projection = application.read_trace(args.trace_id)
                elif args.trace_command == "export":
                    log_path = application.export_trace_log(
                        args.trace_id,
                        output_path=args.output,
                        view=args.view,
                        context_mode=args.context,
                    )
                else:
                    raise TraceStoreError(f"unsupported trace command: {args.trace_command}")
        except TraceStoreError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        if args.trace_command == "show":
            print(json.dumps(asdict(trace_projection), ensure_ascii=False, indent=2))
        else:
            print(log_path)
        return 0

    if args.command == "import" and getattr(args, "import_command", None) == "diagnostics":
        try:
            with create_application(args.database) as application:
                import_projection = application.read_import_diagnostics(
                    source_file=args.source_file,
                    batch_id=args.batch_id,
                )
        except ImportDiagnosticsError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(asdict(import_projection), ensure_ascii=False, indent=2))
        return 0

    if args.command == "import-diagnostics":
        try:
            with create_application(args.database) as application:
                import_projection = application.read_import_diagnostics(
                    source_file=args.source_file,
                    batch_id=args.batch_id,
                )
        except ImportDiagnosticsError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(asdict(import_projection), ensure_ascii=False, indent=2))
        return 0

    if args.command != "import":
        parser.print_help()
        return 0

    try:
        # Application 负责 lifecycle，CLI 不直接创建 Parser/Store，也不复制导入语义。
        with create_application(args.database) as application:
            summary = application.import_directory(args.raw_dir)
    except IngestionError as exc:
        # 已分类错误需要给调用方可读信息；未知异常不在这里被吞掉。
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 1 if summary.has_errors else 0
