"""Trivae CLI：只做参数解析、Application 调用和结果投影。"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from trivae.bootstrap.application import create_application
from trivae.data.model import IngestionError
from trivae.evaluation import (
    ControlledVariant,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationSuite,
)
from trivae.evaluation.review import M6_FAILURE_REGRESSION_MAP
from trivae.evaluation.store import EvaluationStoreError
from trivae.observability.sqlite import ImportDiagnosticsError, TraceStoreError


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
            print(json.dumps({"suite": suite.identity, "variant": variant.to_dict(), "runs": [run.to_dict() for run in runs]}, ensure_ascii=False, indent=2))
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


def main(argv: Sequence[str] | None = None) -> int:
    """执行 CLI；已分类 ingestion error 转成非零状态，未知异常继续暴露。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "eval":
        return _run_evaluation_command(args)
    if args.command == "trace":
        try:
            with create_application(args.database) as application:
                trace_projection = application.read_trace(args.trace_id)
        except TraceStoreError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(asdict(trace_projection), ensure_ascii=False, indent=2))
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
