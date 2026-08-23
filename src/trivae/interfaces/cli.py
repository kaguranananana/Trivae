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
from trivae.capabilities.contracts import CapabilityContractError, ExecutionScope, SemanticSearchInput
from trivae.config.settings import SettingsError, load_settings
from trivae.conversation.contracts import ConversationError
from trivae.data.model import ChatSession, IngestionError
from trivae.evaluation import (
    BlindAnnotationPacket,
    ControlledVariant,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationSuite,
    LLMRetrievalAnnotator,
    RelevanceAnnotationSet,
    RetrievalQuerySet,
    SealedRetrievalPacket,
    build_retrieval_audit_queue,
    build_retrieval_metrics,
)
from trivae.evaluation.review import M6_FAILURE_REGRESSION_MAP
from trivae.evaluation.store import EvaluationStoreError
from trivae.interfaces.cli_renderer import CliEventRenderer
from trivae.observability.sqlite import ImportDiagnosticsError, TraceStoreError
from trivae.query.contracts import QueryContractError, QueryRequest, QueryResult
from trivae.retrieval.semantic.contracts import SemanticError, SemanticRetrievalResult
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
    eval_snapshot_parser = evaluation_subparsers.add_parser(
        "snapshot",
        help="Materialize a secret-free Canonical Dataset Snapshot manifest",
    )
    eval_snapshot_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    eval_snapshot_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path; stdout is used when omitted",
    )
    retrieval_packet_parser = evaluation_subparsers.add_parser(
        "retrieval-packet",
        help="Generate local-only blind and sealed lexical/semantic annotation packets",
    )
    retrieval_packet_parser.add_argument("--queries", type=Path, required=True)
    retrieval_packet_parser.add_argument("--lexical-variant", type=Path, required=True)
    retrieval_packet_parser.add_argument("--semantic-variant", type=Path, required=True)
    retrieval_packet_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    retrieval_packet_parser.add_argument(
        "--semantic-index",
        type=Path,
        default=None,
        help="Optional independent semantic SQLite path",
    )
    retrieval_packet_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/evaluation/semantic-vs-lexical-provisional-v1"),
        help="Gitignored local artifact directory",
    )
    retrieval_annotate_parser = evaluation_subparsers.add_parser(
        "retrieval-annotate",
        help="Create LLM-assisted provisional blind labels and a human audit queue",
    )
    retrieval_annotate_parser.add_argument("--packet", type=Path, required=True)
    retrieval_annotate_parser.add_argument("--sealed", type=Path, required=True)
    retrieval_annotate_parser.add_argument("--batch-size", type=int, default=12)
    retrieval_annotate_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/evaluation/semantic-vs-lexical-provisional-v1"),
        help="Gitignored local artifact directory",
    )
    retrieval_metrics_parser = evaluation_subparsers.add_parser(
        "retrieval-metrics",
        help="Compute lexical/semantic metrics from sealed metadata and relevance labels",
    )
    retrieval_metrics_parser.add_argument("--sealed", type=Path, required=True)
    retrieval_metrics_parser.add_argument("--annotations", type=Path, required=True)
    retrieval_metrics_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional metrics JSON path; stdout is used when omitted",
    )
    semantic_parser = subparsers.add_parser(
        "semantic",
        help="Inspect, rebuild, and smoke-test the local semantic derived index",
    )
    semantic_subparsers = semantic_parser.add_subparsers(dest="semantic_command", required=True)
    semantic_status_parser = semantic_subparsers.add_parser(
        "status",
        help="Show semantic provider/index identity and readiness",
    )
    semantic_rebuild_parser = semantic_subparsers.add_parser(
        "rebuild",
        help="Explicitly rebuild the semantic derived index",
    )
    semantic_smoke_parser = semantic_subparsers.add_parser(
        "smoke",
        help="Run one bounded semantic retrieval smoke against the local index",
    )
    for semantic_command_parser in (
        semantic_status_parser,
        semantic_rebuild_parser,
        semantic_smoke_parser,
    ):
        semantic_command_parser.add_argument(
            "--database",
            type=Path,
            default=Path("data/trivae.sqlite3"),
            help="SQLite Canonical Store path",
        )
        semantic_command_parser.add_argument(
            "--semantic-index",
            type=Path,
            default=None,
            help="Optional independent semantic SQLite path",
        )
    semantic_smoke_parser.add_argument("--query", required=True, help="Semantic retrieval query")
    semantic_smoke_parser.add_argument(
        "--session-id",
        action="append",
        default=None,
        help="Optional trusted session ID; repeat to restrict the smoke scope",
    )
    semantic_smoke_parser.add_argument("--start-timestamp", type=int, default=None)
    semantic_smoke_parser.add_argument("--end-timestamp", type=int, default=None)
    semantic_smoke_parser.add_argument("--limit", type=int, default=5)
    semantic_smoke_parser.add_argument("--context-before", type=int, default=2)
    semantic_smoke_parser.add_argument("--context-after", type=int, default=2)
    semantic_smoke_parser.add_argument("--dense-top-k", type=int, default=40)
    semantic_smoke_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the derived index before the smoke; otherwise an existing ready index is required",
    )
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


def _write_json_projection(payload: object, output_path: Path | None) -> None:
    """把 bounded JSON projection 输出到 stdout 或用户明确指定的文件。"""

    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output_path is None:
        print(serialized)
        return
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
    except OSError as exc:
        raise EvaluationContractError(f"JSON output cannot be written: {output_path}") from exc
    print(output_path.resolve())


def _run_retrieval_packet_command(args: argparse.Namespace) -> int:
    """通过 Application facade 生成 local-only blind/sealed packet。"""

    query_set = RetrievalQuerySet.from_json(args.queries)
    lexical_variant = _load_variant(args.lexical_variant)
    semantic_variant = _load_variant(args.semantic_variant)
    with create_application(
        args.database,
        semantic_index_path=args.semantic_index,
    ) as application:
        blind, sealed = application.generate_retrieval_annotation_packet(
            query_set,
            lexical_variant,
            semantic_variant,
        )
    output_dir: Path = args.output_dir
    _write_json_projection(blind.to_dict(), output_dir / "blind-packet.json")
    _write_json_projection(sealed.to_dict(), output_dir / "sealed-metadata.json")
    _write_json_projection(
        {
            "schema_version": "retrieval-annotation-v1",
            "packet_id": blind.packet_id,
            "snapshot_id": blind.snapshot_id,
            "query_count": len(query_set.queries),
            "candidate_count": len(blind.candidates),
            "blind_packet": "blind-packet.json",
            "sealed_metadata": "sealed-metadata.json",
            "privacy": "local_only_gitignored_contains_private_chat_content",
        },
        output_dir / "packet-summary.json",
    )
    return 0


def _run_retrieval_annotation_command(args: argparse.Namespace) -> int:
    """执行 blind LLM 初筛；输出始终是 provisional，并同时生成 audit queue。"""

    packet = BlindAnnotationPacket.from_json(args.packet)
    sealed = SealedRetrievalPacket.from_json(args.sealed)
    if packet.packet_id != sealed.packet_id:
        raise EvaluationContractError("blind packet does not match sealed metadata")
    annotator = LLMRetrievalAnnotator(load_settings())
    annotations = asyncio.run(annotator.annotate(packet, batch_size=args.batch_size))
    audit_queue = build_retrieval_audit_queue(sealed, annotations)
    output_dir: Path = args.output_dir
    _write_json_projection(annotations.to_dict(), output_dir / "annotations.json")
    _write_json_projection(audit_queue, output_dir / "audit-queue.json")
    return 0


def _run_retrieval_metrics_command(args: argparse.Namespace) -> int:
    """读取 sealed provenance 与标签，生成不含聊天正文的 paired metrics。"""

    sealed = SealedRetrievalPacket.from_json(args.sealed)
    annotations = RelevanceAnnotationSet.from_json(args.annotations)
    report = build_retrieval_metrics(sealed, annotations)
    _write_json_projection(report, args.output)
    return 0


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

        if args.evaluation_command == "snapshot":
            with create_application(args.database) as application:
                snapshot = application.materialize_evaluation_snapshot()
            _write_json_projection(snapshot.to_dict(), args.output)
            return 0

        if args.evaluation_command == "retrieval-packet":
            return _run_retrieval_packet_command(args)

        if args.evaluation_command == "retrieval-annotate":
            return _run_retrieval_annotation_command(args)

        if args.evaluation_command == "retrieval-metrics":
            return _run_retrieval_metrics_command(args)

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
    except (EvaluationContractError, EvaluationStoreError, SettingsError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    raise EvaluationContractError("unsupported eval command")


def _semantic_smoke_projection(
    application: TrivaeApplication,
    args: argparse.Namespace,
) -> dict[str, object]:
    """执行一个不输出聊天正文的 semantic retrieval smoke projection。"""

    if isinstance(args.limit, bool) or not isinstance(args.limit, int) or args.limit <= 0:
        raise CapabilityContractError("semantic smoke limit must be positive")
    # Smoke 的 trusted scope 由显式 CLI 参数编译，不能由模型或检索结果反推。
    session_ids = None if args.session_id is None else tuple(args.session_id)
    scope = ExecutionScope(
        allowed_session_ids=session_ids,
        start_timestamp=args.start_timestamp,
        end_timestamp=args.end_timestamp,
        max_results=args.limit,
    )
    envelope = application.invoke_tool(
        "semantic_search",
        SemanticSearchInput(
            query=args.query,
            session_ids=session_ids,
            start_timestamp=args.start_timestamp,
            end_timestamp=args.end_timestamp,
            limit=args.limit,
            context_before=args.context_before,
            context_after=args.context_after,
            dense_top_k=args.dense_top_k,
        ),
        scope,
    )
    projection: dict[str, object] = {
        "tool_status": envelope.status,
        "error": None if envelope.error is None else {
            "code": envelope.error.code,
            "message": envelope.error.message,
        },
        "meta": dict(envelope.meta),
    }
    if isinstance(envelope.data, SemanticRetrievalResult):
        result = envelope.data
        projection["retrieval"] = {
            "strategy": result.strategy,
            "query": result.query.to_dict(),
            "hit_count": len(result.hits),
            "hits": [
                {
                    "chunk_id": hit.chunk_id,
                    "parent_id": hit.parent_id,
                    "session_id": hit.session_id,
                    "start_message_id": hit.start_message_id,
                    "end_message_id": hit.end_message_id,
                    "score": hit.score,
                    "score_type": hit.score_type,
                    "dense_rank": hit.dense_rank,
                }
                for hit in result.hits
            ],
            "expanded_message_count": len(result.expanded_messages),
            "total_hits": result.total_hits,
            "returned_messages": result.returned_messages,
            "coverage": {"status": result.coverage.status, "basis": result.coverage.basis},
            "partial": result.partial,
            "truncated": result.truncated,
            "metadata": {
                "ordering": result.metadata.ordering,
                "latency_ms": result.metadata.latency_ms,
                "details": dict(result.metadata.details),
            },
        }
    elif envelope.data is not None:
        raise RuntimeError("semantic smoke received an unexpected tool result type")
    return projection


def _run_semantic_command(args: argparse.Namespace) -> int:
    """semantic CLI 只通过 Application facade 操作独立 derived index。"""

    try:
        with create_application(
            args.database,
            semantic_index_path=args.semantic_index,
        ) as application:
            rebuild: dict[str, object] | None = None
            integrity: dict[str, object] | None = None
            if args.semantic_command == "rebuild":
                rebuild = application.rebuild_semantic_index().to_dict()
                integrity = application.validate_semantic_index().to_dict()
            elif args.semantic_command == "smoke" and args.rebuild:
                rebuild = application.rebuild_semantic_index().to_dict()
                integrity = application.validate_semantic_index().to_dict()

            status = application.semantic_index_status()
            if args.semantic_command == "status":
                _write_json_projection(status.to_dict(), None)
                return 0
            if args.semantic_command == "rebuild":
                _write_json_projection(
                    {"rebuild": rebuild, "integrity": integrity, "status": status.to_dict()},
                    None,
                )
                return 0 if integrity is not None and integrity["status"] == "valid" else 1
            if args.semantic_command == "smoke":
                smoke = _semantic_smoke_projection(application, args)
                _write_json_projection(
                    {
                        "status": smoke["tool_status"],
                        "index": status.to_dict(),
                        "integrity": integrity,
                        "rebuild": rebuild,
                        "smoke": smoke,
                    },
                    None,
                )
                return 0 if smoke["tool_status"] in ("ok", "partial") else 1
    except (CapabilityContractError, SemanticError, RetrievalError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": getattr(exc, "error_code", type(exc).__name__),
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    raise RuntimeError(f"unsupported semantic command: {args.semantic_command}")


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
    if args.command == "semantic":
        return _run_semantic_command(args)
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
