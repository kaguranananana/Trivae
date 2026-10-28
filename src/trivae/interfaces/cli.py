"""Trivae CLI：只做参数解析、Application 调用和结果投影。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO, cast

from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.capabilities.contracts import CapabilityContractError, ExecutionScope, SemanticSearchInput
from trivae.config.dotenv import DotenvError, load_environment_file
from trivae.config.settings import SettingsError, load_router_jev_settings, load_settings
from trivae.conversation.contracts import ConversationError, ConversationSummary
from trivae.data.model import ChatSession, IngestionError
from trivae.evaluation import (
    BlindAnnotationPacket,
    ControlledVariant,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationRun,
    EvaluationSuite,
    LLMRetrievalAnnotator,
    RelevanceAnnotationSet,
    RetrievalQuerySet,
    SealedRetrievalPacket,
    build_retrieval_audit_queue,
    build_retrieval_metrics,
)
from trivae.evaluation.benchmark.closure import BenchmarkFinalFreezeRecord, HoldoutRegistrationRecord
from trivae.evaluation.benchmark.environment import capture_environment
from trivae.evaluation.benchmark.orchestrator import (
    BenchmarkOrchestrator,
    run_benchmark_async,
)
from trivae.evaluation.contracts import select_suite_references
from trivae.evaluation.review import M6_FAILURE_REGRESSION_MAP
from trivae.evaluation.store import EvaluationStoreError
from trivae.feedback.contracts import FeedbackError, FeedbackRecord
from trivae.interfaces.cli_renderer import CliEventRenderer
from trivae.observability.sqlite import ImportDiagnosticsError, TraceStoreError
from trivae.query.contracts import QueryContractError, QueryRequest, QueryResult
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerSourceSummary,
    MessageSource,
    SourceHandleReference,
    SourceInspectionError,
    StructuredSource,
    answer_source_summaries,
    extract_urls,
    source_reference_key,
)
from trivae.retrieval.semantic.contracts import (
    SemanticError,
    SemanticIndexStatusReport,
    SemanticRetrievalResult,
)
from trivae.retrieval.structured import ForwardProvenance, RetrievalError


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI parser，不在 import 时初始化数据库或外部服务。"""

    parser = argparse.ArgumentParser(prog="trivae", description="Trivae high-noise chat intelligence system")
    subparsers = parser.add_subparsers(dest="command")
    # 认证入口只配置命令，不在解析阶段读取凭证、创建数据库或打开浏览器。
    from trivae.interfaces.auth_cli import configure_auth_parser

    configure_auth_parser(subparsers)
    # 无人值守导入入口保持独立适配，避免影响交互式 Query 或原 import 命令。
    from trivae.interfaces.import_once_cli import configure_import_once_parser

    configure_import_once_parser(subparsers)
    # 日报复用现有模型配置，但拥有独立的数据选择和邮件交付入口。
    from trivae.interfaces.digest_cli import configure_digest_parser

    configure_digest_parser(subparsers)
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
        help="Show detailed route, plan, tool, retrieval, usage, and normalized event metadata (plain mode only)",
    )
    chat_parser.add_argument(
        "--plain",
        action="store_true",
        help="Use the streaming stdout renderer instead of the interactive Textual TUI",
    )
    chat_parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional dotenv path; defaults to .env in the current directory when present",
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
    evaluation_parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional dotenv path; defaults to .env in the current directory when present",
    )
    evaluation_subparsers = evaluation_parser.add_subparsers(dest="evaluation_command", required=True)
    eval_cases_parser = evaluation_subparsers.add_parser("cases", help="Validate versioned Evaluation Cases")
    eval_cases_subparsers = eval_cases_parser.add_subparsers(dest="cases_command", required=True)
    eval_cases_validate_parser = eval_cases_subparsers.add_parser("validate", help="Validate one Case or directory")
    eval_cases_validate_parser.add_argument("path", type=Path, help="Case JSON file or directory")
    eval_cases_version_parser = eval_cases_subparsers.add_parser("new-version", help="Create a new Case version")
    eval_cases_version_parser.add_argument("--source", type=Path, required=True)
    eval_cases_version_parser.add_argument("--output", type=Path, required=True)
    eval_cases_version_parser.add_argument("--snapshot", type=Path, help="Freeze manifest for a new unreviewed data version")
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
    eval_run_parser.add_argument("--case-list", type=Path,
                                 help="JSON array of exact Case identities to run within the Suite")
    eval_run_parser.add_argument("--record-dir", type=Path, help="Create a formal experiment record")
    eval_run_parser.add_argument("--freeze-manifest", type=Path, help="Manifest in the working data clone")
    eval_run_parser.add_argument("--judge-version", default="none", help="Judge identity or none")
    eval_freeze = evaluation_subparsers.add_parser("freeze-data", help="Freeze private canonical and index databases")
    eval_freeze.add_argument("--database", type=Path, required=True)
    eval_freeze.add_argument("--semantic-index", type=Path, default=None)
    eval_freeze.add_argument("--output-dir", type=Path, required=True)
    eval_clone = evaluation_subparsers.add_parser("clone-data", help="Create a working copy of a frozen master")
    eval_clone.add_argument("--manifest", type=Path, required=True)
    eval_clone.add_argument("--output-dir", type=Path, required=True)
    eval_candidates = evaluation_subparsers.add_parser("suite-candidates", help="Prepare unreviewed Cases on new data")
    eval_candidates.add_argument("--suite", type=Path, required=True)
    eval_candidates.add_argument("--cases-dir", type=Path, required=True)
    eval_candidates.add_argument("--freeze-manifest", type=Path, required=True)
    eval_candidates.add_argument("--output-dir", type=Path, required=True)
    eval_exp_compare = evaluation_subparsers.add_parser("compare-experiments", help="Check experiment comparability")
    eval_exp_compare.add_argument("--baseline", type=Path, required=True)
    eval_exp_compare.add_argument("--candidate", type=Path, required=True)
    eval_report = evaluation_subparsers.add_parser("report", help="Report run, review and judge failures separately")
    eval_report.add_argument("--evaluation-database", type=Path, required=True)
    eval_report.add_argument("--suite-id")
    eval_report.add_argument("--judgments", type=Path)
    eval_report.add_argument("--output", type=Path, help="Create-only local JSON output")
    eval_review = evaluation_subparsers.add_parser("review", help="Save a structured human or model-assisted Review")
    eval_review.add_argument("--evaluation-database", type=Path, required=True)
    eval_review.add_argument("--review", type=Path, required=True)
    eval_sync = evaluation_subparsers.add_parser("langsmith-sync", help="Upload saved runs as a LangSmith experiment")
    eval_sync.add_argument("--suite", type=Path, required=True)
    eval_sync.add_argument("--cases-dir", type=Path, required=True)
    eval_sync.add_argument("--evaluation-database", type=Path, required=True)
    eval_sync.add_argument("--run-id", action="append", help="Select one persisted Run; repeat for a suite")
    eval_sync.add_argument("--variant-id", help="Select this variant from benchmark --records")
    eval_sync.add_argument("--variant-file", type=Path, help="Declared historical Variant configuration")
    eval_sync.add_argument("--experiment", required=True)
    eval_sync.add_argument("--trace-database", type=Path)
    eval_sync.add_argument("--records", type=Path, help="Existing benchmark raw-records.json")
    eval_sync.add_argument("--judgments", type=Path, help="Existing benchmark judge results")
    eval_sync.add_argument("--failures", type=Path, help="Existing benchmark failure details")
    eval_sync.add_argument("--manifest", type=Path, help="Formal experiment.json with runtime conditions")
    eval_sync.add_argument("--history-report", type=Path, help="Original benchmark report with environment and Variant")
    eval_sync.add_argument("--history-note", help="Historical stage and comparison limitations")
    eval_sync.add_argument("--require-complete", action="store_true", help="Require matching Case, Result and complete Trace")
    eval_sync.add_argument("--import-time", action="store_true",
                           help="Use import time on LangSmith; keep original run times and duration in outputs")
    eval_sync.add_argument("--content", type=Path, help="Optional explicitly prepared case/run text")
    eval_sync.add_argument("--metadata-only", action="store_true", help="Do not export original questions/answers")
    eval_sync.add_argument("--ledger", type=Path, default=Path("data/evaluation/langsmith-external.sqlite3"))
    eval_map = evaluation_subparsers.add_parser("langsmith-map", help="Look up LangSmith IDs for a local Run")
    eval_map.add_argument("--run-id", required=True)
    eval_map.add_argument("--ledger", type=Path, default=Path("data/evaluation/langsmith-external.sqlite3"))
    eval_resolve = evaluation_subparsers.add_parser("langsmith-resolve", help="Resolve remote Run IDs after ingestion")
    eval_resolve.add_argument("--experiment", required=True)
    eval_resolve.add_argument("--ledger", type=Path, default=Path("data/evaluation/langsmith-external.sqlite3"))
    eval_review_sync = evaluation_subparsers.add_parser("langsmith-review-sync", help="Upload a later local Review")
    eval_review_sync.add_argument("--evaluation-database", type=Path, required=True)
    eval_review_sync.add_argument("--review-id", required=True)
    eval_review_sync.add_argument("--experiment", required=True)
    eval_review_sync.add_argument("--ledger", type=Path, default=Path("data/evaluation/langsmith-external.sqlite3"))
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
    eval_router_jev_parser = evaluation_subparsers.add_parser(
        "router-jev",
        help="Run a paired ambiguous-Router evaluation against the existing LLM and OpenRouter Jev",
    )
    eval_router_jev_parser.add_argument(
        "--cases",
        type=Path,
        default=Path("evaluation/router-jev/cases-v1.json"),
        help="Versioned Router case manifest",
    )
    eval_router_jev_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Create-only path for the secret-free diagnostic report",
    )
    eval_router_jev_parser.add_argument("--repeat", type=int, default=1, help="Paired repetitions per case")
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
    )
    benchmark_parser = evaluation_subparsers.add_parser(
        "benchmark",
        help="resume-benchmark orchestration: environment gate, end-to-end runs, scoring and report",
    )
    benchmark_subparsers = benchmark_parser.add_subparsers(dest="benchmark_command", required=True)
    benchmark_gate_parser = benchmark_subparsers.add_parser(
        "gate", help="Verify the pinned environment manifest against the live environment"
    )
    benchmark_gate_parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    benchmark_gate_parser.add_argument("--manifest", type=Path, required=True)
    benchmark_capture_parser = benchmark_subparsers.add_parser(
        "capture-environment", help="Capture and persist a BenchmarkEnvironmentManifest"
    )
    benchmark_capture_parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    benchmark_capture_parser.add_argument("--benchmark", required=True, help="Benchmark name, e.g. resume-benchmark-v1")
    benchmark_capture_parser.add_argument("--output", type=Path, required=True)
    benchmark_run_parser = benchmark_subparsers.add_parser(
        "run", help="Run a benchmark suite across variants and write scoring outputs"
    )
    benchmark_run_parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    benchmark_run_parser.add_argument("--evaluation-database", type=Path, default=None)
    benchmark_run_parser.add_argument("--manifest", type=Path, required=True)
    benchmark_run_parser.add_argument("--suite", type=Path, required=True)
    benchmark_run_parser.add_argument("--cases-dir", type=Path, action="append", required=True)
    benchmark_run_parser.add_argument("--variant", type=Path, action="append", required=True)
    benchmark_run_parser.add_argument("--output-dir", type=Path, required=True)
    benchmark_run_parser.add_argument("--repeat", type=int, default=1)
    benchmark_run_parser.add_argument(
        "--paired-by-case",
        action="store_true",
        help="Interleave variants for each Case to limit time-window drift in paired experiments",
    )
    benchmark_run_parser.add_argument(
        "--paired-order",
        choices=("fixed", "counterbalanced"),
        default="fixed",
        help="Use an opt-in deterministic AB/BA order for paired-by-case runs",
    )
    benchmark_retrieval_score_parser = benchmark_subparsers.add_parser(
        "retrieval-score", help="Deterministic module-level lexical/semantic scoring against benchmark GT"
    )
    benchmark_retrieval_score_parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    benchmark_retrieval_score_parser.add_argument("--manifest", type=Path, required=True)
    benchmark_retrieval_score_parser.add_argument("--queries", type=Path, required=True)
    benchmark_retrieval_score_parser.add_argument("--cases-dir", type=Path, required=True)
    benchmark_retrieval_score_parser.add_argument("--lexical-variant", type=Path, required=True)
    benchmark_retrieval_score_parser.add_argument("--semantic-variant", type=Path, required=True)
    benchmark_retrieval_score_parser.add_argument("--output", type=Path, required=True)
    benchmark_judge_parser = benchmark_subparsers.add_parser(
        "judge", help="Tier 2 atomic-claim/citation judgment over persisted benchmark runs"
    )
    benchmark_judge_parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    benchmark_judge_parser.add_argument("--evaluation-database", type=Path, default=None)
    benchmark_judge_parser.add_argument("--records", type=Path, required=True, help="raw-records.json from a benchmark run")
    benchmark_judge_parser.add_argument("--cases-dir", type=Path, required=True)
    benchmark_judge_parser.add_argument("--output", type=Path, required=True)
    benchmark_freeze_parser = benchmark_subparsers.add_parser(
        "freeze-final", help="Capture the Gate 3 Development identity after final review"
    )
    benchmark_freeze_parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    benchmark_freeze_parser.add_argument("--manifest", type=Path, required=True)
    benchmark_freeze_parser.add_argument("--suite", type=Path, required=True)
    benchmark_freeze_parser.add_argument("--cases-dir", type=Path, required=True)
    benchmark_freeze_parser.add_argument("--variant", type=Path, action="append", required=True)
    benchmark_freeze_parser.add_argument(
        "--development-dir",
        type=Path,
        required=True,
        help="Completed final Development output directory to bind into the Gate 3 review",
    )
    benchmark_freeze_parser.add_argument("--output", type=Path, required=True)
    benchmark_freeze_parser.add_argument("--gate2-freeze", type=Path, default=None)
    benchmark_holdout_parser = benchmark_subparsers.add_parser(
        "seal-holdout", help="Register manually adjudicated holdout cases after Gate 3"
    )
    benchmark_holdout_parser.add_argument("--freeze", type=Path, required=True)
    benchmark_holdout_parser.add_argument("--suite", type=Path, required=True)
    benchmark_holdout_parser.add_argument("--cases-dir", type=Path, required=True)
    benchmark_holdout_parser.add_argument("--output", type=Path, required=True)
    benchmark_holdout_run_parser = benchmark_subparsers.add_parser(
        "run-holdout", help="Run the sealed holdout once through the production query path"
    )
    benchmark_holdout_run_parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    benchmark_holdout_run_parser.add_argument("--evaluation-database", type=Path, default=None)
    benchmark_holdout_run_parser.add_argument("--manifest", type=Path, required=True)
    benchmark_holdout_run_parser.add_argument("--freeze", type=Path, required=True)
    benchmark_holdout_run_parser.add_argument("--registration", type=Path, required=True)
    benchmark_holdout_run_parser.add_argument("--suite", type=Path, required=True)
    benchmark_holdout_run_parser.add_argument("--cases-dir", type=Path, required=True)
    benchmark_holdout_run_parser.add_argument("--variant", type=Path, action="append", required=True)
    benchmark_holdout_run_parser.add_argument("--output-dir", type=Path, required=True)
    benchmark_holdout_run_parser.add_argument("--repeat", type=int, default=1)
    benchmark_merge_parser = benchmark_subparsers.add_parser(
        "merge-report", help="Merge sealed Development and holdout reports when identities match"
    )
    benchmark_merge_parser.add_argument("--development-dir", type=Path, required=True)
    benchmark_merge_parser.add_argument("--holdout-dir", type=Path, required=True)
    benchmark_merge_parser.add_argument("--freeze", type=Path, required=True)
    benchmark_merge_parser.add_argument("--output-dir", type=Path, required=True)
    benchmark_audit_parser = benchmark_subparsers.add_parser(
        "audit", help="Deterministic GT consistency audit over version-controlled benchmark cases"
    )
    benchmark_audit_parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    benchmark_audit_parser.add_argument("--cases-dir", type=Path, action="append", required=True)
    benchmark_audit_parser.add_argument("--output", type=Path, default=None)
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
    semantic_rebuild_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an unfinished index with exactly matching source and index identity",
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
    web_parser = subparsers.add_parser(
        "web",
        help="Start the local ChatLab-style Web UI (primary interaction surface)",
    )
    web_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    web_parser.add_argument("--host", default="127.0.0.1", help="Bind host; non-localhost disables local OS integrations")
    web_parser.add_argument("--port", type=int, default=8710, help="Bind port")
    web_parser.add_argument("--no-open", action="store_true", help="Do not auto-open the browser")
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


def _run_router_jev_evaluation(args: argparse.Namespace) -> int:
    """配对运行 Router provider 并只写入不含 query/secret 的诊断 projection。"""

    from trivae.evaluation.router_jev import (
        RouterEvaluationError,
        load_router_evaluation_cases,
        run_paired_router_evaluation,
        write_router_evaluation_report,
    )
    from trivae.query.jev_provider import JevRouteDecisionProvider
    from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

    jev_settings = load_router_jev_settings()
    if not jev_settings.enabled:
        raise EvaluationContractError("Router Jev evaluation requires TRIVIAE_ROUTER_JEV_ENABLED=true")
    if not jev_settings.api_key:
        raise EvaluationContractError("Router Jev evaluation requires OPENROUTER_API_KEY in the environment")
    if args.repeat <= 0:
        raise EvaluationContractError("Router Jev evaluation --repeat must be positive")

    try:
        suite_id, cases = load_router_evaluation_cases(args.cases)
        primary_settings = load_settings()
        baseline = OpenAIAgentsRuntimeAdapter(settings=primary_settings)
        jev_provider = JevRouteDecisionProvider(jev_settings)

        async def run() -> dict[str, object]:
            """在同一异步边界内运行两种 provider，并明确释放各自的 transport。"""

            try:
                return await run_paired_router_evaluation(
                    suite_id=suite_id,
                    cases=cases,
                    llm_completion=baseline.complete_text_with_observation,
                    jev_provider=jev_provider,
                    llm_identity={
                        "provider": primary_settings.provider,
                        "model": primary_settings.model_name,
                    },
                    jev_model=jev_settings.model,
                    repetitions=args.repeat,
                )
            finally:
                await jev_provider.aclose()
                await baseline.aclose()

        report = asyncio.run(run())
        # 记录本次 Router 专属配置，始终排除 OPENROUTER_API_KEY。
        report["configured_router_jev"] = {
            "enabled": jev_settings.enabled,
            "model": jev_settings.model,
            "endpoint": jev_settings.endpoint,
            "mode": jev_settings.mode,
        }
        write_router_evaluation_report(report, args.output)
    except RouterEvaluationError as exc:
        raise EvaluationContractError(str(exc)) from exc
    summary = {
        "status": report["status"],
        "suite_id": suite_id,
        "case_count": len(cases),
        "repetitions": args.repeat,
        "output": str(args.output),
        "promotion_recommendation": report["promotion_recommendation"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run_retrieval_metrics_command(args: argparse.Namespace) -> int:
    """读取 sealed provenance 与标签，生成不含聊天正文的 paired metrics。"""

    sealed = SealedRetrievalPacket.from_json(args.sealed)
    annotations = RelevanceAnnotationSet.from_json(args.annotations)
    report = build_retrieval_metrics(sealed, annotations)
    _write_json_projection(report, args.output)
    return 0


async def _run_benchmark_with_application(args: argparse.Namespace) -> dict[str, object]:
    """在同一个 async context 内运行 benchmark 并关闭 Application。"""

    # create-only 检查必须早于 Application 初始化，防止新实验污染已有评测库或覆盖旧报告。
    if args.output_dir.exists():
        raise EvaluationContractError(f"benchmark output directory already exists: {args.output_dir}")
    if args.evaluation_database is not None and args.evaluation_database.exists():
        raise EvaluationContractError(f"evaluation database already exists: {args.evaluation_database}")
    # Provider 配置必须在创建 Application 前校验，避免缺配置时逐 Case 重复写失败记录。
    load_settings()
    suite = EvaluationSuite.from_json(args.suite)
    variant_paths = tuple(args.variant)
    # Application 的异步 client 在同一 loop 中完成请求与关闭，避免跨 loop 释放连接。
    async with create_application(
        args.database,
        evaluation_database_path=args.evaluation_database,
    ) as application:
        return await run_benchmark_async(
            application=application,
            database_path=args.database,
            manifest_path=args.manifest,
            suite=suite,
            cases_dir=args.cases_dir,
            variant_paths=variant_paths,
            output_dir=args.output_dir,
            repetitions=args.repeat,
            paired_by_case=args.paired_by_case,
            paired_order=args.paired_order,
        )


async def _run_holdout_with_application(args: argparse.Namespace) -> dict[str, object]:
    """在 Gate 3 identity 复核后执行一次性 holdout，并持久化 claim 状态。"""

    from trivae.evaluation.benchmark.closure import (
        assert_finalized_run_inputs,
        begin_holdout_run,
        complete_holdout_run,
        fail_holdout_run,
    )

    # Holdout 是一次性运行；先校验 Provider，不能先创建 claim 再发现本地配置缺失。
    load_settings()
    if isinstance(args.repeat, bool) or not isinstance(args.repeat, int) or args.repeat <= 0:
        raise EvaluationContractError("holdout repetitions must be a positive integer")
    suite = EvaluationSuite.from_json(args.suite)
    cases = _load_cases(args.cases_dir)
    variants = tuple(_load_variant(path) for path in args.variant)
    freeze = _load_final_freeze(args.freeze)
    registration = _load_holdout_registration(args.registration)
    async with create_application(
        args.database,
        evaluation_database_path=args.evaluation_database,
    ) as application:
        orchestrator = BenchmarkOrchestrator(application=application, database_path=args.database)
        manifest = orchestrator.load_manifest(args.manifest)
        gate = orchestrator.preflight_gate(manifest)
        if not gate.passed:
            return {"status": "gate_failed", "gate": gate.to_dict()}
        # 所有 identity 检查都发生在 claim 和 provider 请求前，失败时不会留下“已开始”的假象。
        assert_finalized_run_inputs(
            freeze=freeze,
            manifest=manifest,
            suite=suite,
            cases=cases,
            variants=variants,
            split="holdout",
            registration=registration,
            freeze_path=args.freeze,
        )
        claim_path, _claim = begin_holdout_run(
            freeze=freeze,
            freeze_path=args.freeze,
            registration_path=args.registration,
            output_dir=args.output_dir,
        )
        try:
            outcome = await run_benchmark_async(
                application=application,
                database_path=args.database,
                manifest_path=args.manifest,
                suite=suite,
                cases_dir=args.cases_dir,
                variant_paths=tuple(args.variant),
                output_dir=args.output_dir,
                repetitions=args.repeat,
                holdout_sealed=True,
            )
            if outcome.get("status") != "completed":
                raise EvaluationContractError(
                    f"holdout benchmark did not complete: {outcome.get('status')}"
                )
            completed_claim = complete_holdout_run(claim_path, args.output_dir / "report.json")
        except Exception as exc:  # noqa: BLE001 - claim 必须保留真实失败原因
            fail_holdout_run(claim_path, exc)
            raise
    outcome["holdout_run_claim"] = completed_claim.to_dict()
    return outcome


def _load_final_freeze(path: Path) -> BenchmarkFinalFreezeRecord:
    """读取 final freeze；schema 或 identity 损坏由 contract 显式拒绝。"""

    return BenchmarkFinalFreezeRecord.from_json(path)


def _load_holdout_registration(path: Path) -> HoldoutRegistrationRecord:
    """读取 holdout registration；损坏或 schema 漂移由 contract 显式拒绝。"""

    return HoldoutRegistrationRecord.from_json(path)


def _run_benchmark_command(args: argparse.Namespace) -> int:
    """Benchmark 编排 CLI：gate、冻结、封存、运行、评分和报告合并。"""

    try:
        if args.benchmark_command == "gate":
            with create_application(args.database) as application:
                orchestrator = BenchmarkOrchestrator(application=application, database_path=args.database)
                manifest = orchestrator.load_manifest(args.manifest)
                gate = orchestrator.preflight_gate(manifest)
            print(json.dumps({"status": "passed" if gate.passed else "failed", "gate": gate.to_dict()}, ensure_ascii=False, indent=2))
            return 0 if gate.passed else 1

        if args.benchmark_command == "capture-environment":
            with create_application(args.database) as application:
                snapshot = application.materialize_evaluation_snapshot()
                status = application.semantic_index_status()
                persisted = status.persisted_identity
                if persisted is None:
                    raise EvaluationContractError("semantic index is missing; cannot capture environment")
                manifest = capture_environment(
                    benchmark=args.benchmark,
                    database_path=args.database,
                    snapshot=snapshot,
                    semantic_index_identity=persisted.serialized,
                )
            manifest.to_json(args.output)
            print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
            return 0

        if args.benchmark_command == "freeze-final":
            from trivae.evaluation.benchmark.closure import assert_development_acceptance, capture_final_freeze

            if args.output.exists():
                raise EvaluationContractError(f"final freeze already exists: {args.output}")
            if args.gate2_freeze is not None and not args.gate2_freeze.is_file():
                raise EvaluationContractError(f"Gate 2 freeze does not exist: {args.gate2_freeze}")
            suite = EvaluationSuite.from_json(args.suite)
            cases = _load_cases(args.cases_dir)
            variants = tuple(_load_variant(path) for path in args.variant)
            with create_application(args.database) as application:
                orchestrator = BenchmarkOrchestrator(application=application, database_path=args.database)
                manifest = orchestrator.load_manifest(args.manifest)
                gate = orchestrator.preflight_gate(manifest)
                if not gate.passed:
                    print(json.dumps({"status": "gate_failed", "gate": gate.to_dict()}, ensure_ascii=False, indent=2))
                    return 1
                development_acceptance = assert_development_acceptance(
                    output_dir=args.development_dir,
                    manifest=manifest,
                    suite=suite,
                    variants=variants,
                )
                freeze = capture_final_freeze(
                    manifest=manifest,
                    suite=suite,
                    dev_cases=cases,
                    variants=variants,
                    gate2_freeze_path=args.gate2_freeze,
                )
            freeze.to_json(args.output)
            print(
                json.dumps(
                    {
                        "status": "completed",
                        "development_acceptance": development_acceptance,
                        "freeze": freeze.to_dict(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.benchmark_command == "seal-holdout":
            from trivae.evaluation.benchmark.closure import register_holdout

            if args.output.exists():
                raise EvaluationContractError(f"holdout registration already exists: {args.output}")
            freeze = _load_final_freeze(args.freeze)
            suite = EvaluationSuite.from_json(args.suite)
            cases = _load_cases(args.cases_dir)
            registration = register_holdout(
                freeze=freeze,
                freeze_path=args.freeze,
                suite=suite,
                holdout_cases=cases,
            )
            registration.to_json(args.output)
            print(
                json.dumps(
                    {"status": "completed", "registration": registration.to_dict()},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.benchmark_command == "run-holdout":
            outcome = asyncio.run(_run_holdout_with_application(args))
            summary = {
                "status": outcome["status"],
                "gate": outcome.get("gate"),
                "report_path": str(args.output_dir / "report.json"),
                "markdown_path": str(args.output_dir / "report.md"),
                "failures_path": str(args.output_dir / "failures" / "failures.json"),
                "holdout_run_claim": outcome.get("holdout_run_claim"),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if outcome["status"] == "completed" else 1

        if args.benchmark_command == "merge-report":
            from trivae.evaluation.benchmark.closure import merge_reports, read_holdout_run_claim

            freeze = _load_final_freeze(args.freeze)
            claim = read_holdout_run_claim(args.freeze)
            if claim.status != "completed":
                raise EvaluationContractError(
                    f"holdout run claim is not completed: {claim.status}"
                )
            if claim.benchmark != freeze.benchmark:
                raise EvaluationContractError("holdout run claim benchmark differs from final freeze")
            if claim.output_dir != str(args.holdout_dir.resolve()):
                raise EvaluationContractError("holdout run claim output_dir differs from --holdout-dir")
            expected_report = str((args.holdout_dir / "report.json").resolve())
            if claim.report_path != expected_report:
                raise EvaluationContractError("holdout run claim report_path differs from holdout report")
            report = merge_reports(
                development_dir=args.development_dir,
                holdout_dir=args.holdout_dir,
                output_dir=args.output_dir,
                freeze=freeze,
            )
            metadata = report.get("metadata")
            full_available = metadata.get("full_available") if isinstance(metadata, Mapping) else None
            print(
                json.dumps(
                    {
                        "status": "completed",
                        "full_available": full_available,
                        "report_path": str(args.output_dir / "report.json"),
                        "markdown_path": str(args.output_dir / "report.md"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.benchmark_command == "retrieval-score":
            from trivae.evaluation.benchmark.orchestrator import run_module_retrieval_scoring

            with create_application(args.database) as application:
                outcome = run_module_retrieval_scoring(
                    application=application,
                    database_path=args.database,
                    manifest_path=args.manifest,
                    query_set_path=args.queries,
                    cases_dir=args.cases_dir,
                    lexical_variant_path=args.lexical_variant,
                    semantic_variant_path=args.semantic_variant,
                    output_path=args.output,
                )
            print(json.dumps({"status": outcome["status"]}, ensure_ascii=False, indent=2))
            return 0 if outcome["status"] == "completed" else 1

        if args.benchmark_command == "judge":
            from trivae.evaluation.benchmark.orchestrator import judge_records

            records = json.loads(Path(args.records).read_text(encoding="utf-8"))
            settings = load_settings()
            with create_application(
                args.database,
                evaluation_database_path=args.evaluation_database,
            ) as application:
                outcome = judge_records(
                    application=application,
                    records=records,
                    cases_dir=args.cases_dir,
                    settings=settings,
                    output_path=args.output,
                )
            print(json.dumps(outcome, ensure_ascii=False, indent=2))
            return 0 if outcome["status"] == "completed" else 1

        if args.benchmark_command == "audit":
            from trivae.evaluation.benchmark.audit import CaseAudit

            audit = CaseAudit(database_path=args.database, case_dirs=tuple(args.cases_dir))
            try:
                result = audit.audit()
            finally:
                audit.close()
            if args.output is not None:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["passed"] else 1

        if args.benchmark_command == "run":
            outcome = asyncio.run(_run_benchmark_with_application(args))
            summary = {
                "status": outcome["status"],
                "gate": outcome.get("gate"),
                "report_path": str(args.output_dir / "report.json"),
                "markdown_path": str(args.output_dir / "report.md"),
                "failures_path": str(args.output_dir / "failures" / "failures.json"),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if outcome["status"] == "completed" else 1
    except (EvaluationContractError, EvaluationStoreError, SettingsError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    raise EvaluationContractError("unsupported benchmark command")


def _run_evaluation_command(args: argparse.Namespace) -> int:
    """Evaluation CLI 只调用 Application facade，不直接触碰 Runtime/Tool。"""

    try:
        # eval 的真实 provider run 同样需要凭据；dotenv 注入只发生在显式 CLI 边界。
        load_environment_file(getattr(args, "env_file", None))
        if args.evaluation_command == "cases":
            if args.cases_command == "new-version":
                case = EvaluationCaseBundle.from_json(args.source)
                payload = case.to_dict()
                payload["version"] = case.version + 1
                payload["provenance"] = {
                    "source": case.identity,
                    "method": "new Case version pending review",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "notes": "Copied reference evidence retains its original provenance; review changes before promotion.",
                }
                if args.snapshot is not None:
                    try:
                        freeze = json.loads(args.snapshot.read_text(encoding="utf-8"))
                        payload["dataset_snapshot"] = freeze["snapshot"]
                    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                        raise EvaluationContractError("freeze manifest cannot be read") from exc
                    payload["reference_findings"] = []
                    payload["provenance"] = {
                        "source": case.identity,
                        "method": "new data snapshot; reference evidence removed pending review",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "notes": "Candidate only; inspect and annotate evidence before claiming verified ground truth.",
                    }
                target = EvaluationCaseBundle.from_dict(payload)
                try:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    with args.output.open("x", encoding="utf-8") as stream:
                        json.dump(target.to_dict(), stream, ensure_ascii=False, indent=2, sort_keys=True)
                        stream.write("\n")
                except OSError as exc:
                    raise EvaluationContractError("new Case output cannot be created") from exc
                print(json.dumps({"case": target.identity, "status": "needs_review"}, ensure_ascii=False))
                return 0
            cases = _load_cases(args.path)
            identities = sorted({case.identity for case in cases.values()})
            print(json.dumps({"status": "valid", "cases": identities}, ensure_ascii=False, indent=2))
            return 0

        if args.evaluation_command == "freeze-data":
            from trivae.evaluation.frozen_data import freeze_data
            frozen = freeze_data(args.database, args.semantic_index, args.output_dir)
            print(json.dumps({"status": "frozen", "freeze_id": frozen["freeze_id"]}))
            return 0

        if args.evaluation_command == "clone-data":
            from trivae.evaluation.frozen_data import clone_frozen
            print(json.dumps(clone_frozen(args.manifest, args.output_dir), ensure_ascii=False))
            return 0

        if args.evaluation_command == "suite-candidates":
            from trivae.evaluation.suite_maintenance import rebase_suite
            result = rebase_suite(suite=EvaluationSuite.from_json(args.suite), cases=_load_cases(args.cases_dir),
                                  freeze_path=args.freeze_manifest, output_dir=args.output_dir)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.evaluation_command == "compare-experiments":
            from trivae.evaluation.experiment_manifest import compare_experiments
            experiment_comparison = compare_experiments(args.baseline, args.candidate)
            print(json.dumps(experiment_comparison, ensure_ascii=False, indent=2))
            return 0 if experiment_comparison["comparable"] else 1

        if args.evaluation_command == "report":
            from trivae.evaluation.reporting import run_report
            report = run_report(args.evaluation_database, suite_id=args.suite_id, judgments=args.judgments)
            if args.output is None:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                try:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    with args.output.open("x", encoding="utf-8") as stream:
                        json.dump(report, stream, ensure_ascii=False, indent=2)
                        stream.write("\n")
                except OSError as exc:
                    raise EvaluationContractError("report output cannot be created") from exc
                print(json.dumps({"status": "created", "counts": report["counts"]}, ensure_ascii=False))
            return 0

        if args.evaluation_command == "langsmith-map":
            from trivae.evaluation.langsmith_sync import lookup_mapping
            print(json.dumps(lookup_mapping(args.ledger, args.run_id), ensure_ascii=False, indent=2))
            return 0

        if args.evaluation_command == "langsmith-resolve":
            from trivae.evaluation.langsmith_sync import resolve_remote
            result = resolve_remote(ledger_path=args.ledger, experiment=args.experiment)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "resolved" else 1

        if args.evaluation_command == "langsmith-review-sync":
            from trivae.evaluation.langsmith_sync import sync_review
            result = sync_review(evaluation_db=args.evaluation_database, ledger_path=args.ledger,
                                 experiment=args.experiment, review_id=args.review_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.evaluation_command == "review":
            from trivae.evaluation.contracts import EvaluationReview
            from trivae.evaluation.store import SQLiteEvaluationStore
            if not args.evaluation_database.is_file():
                raise EvaluationContractError("evaluation database does not exist")
            try:
                review = EvaluationReview.from_dict(json.loads(args.review.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                raise EvaluationContractError("review JSON cannot be read") from exc
            store = SQLiteEvaluationStore(args.evaluation_database)
            try:
                store.get_run(review.run_id)
                try:
                    store.get_review(review.review_id)
                except EvaluationStoreError as exc:
                    if not str(exc).startswith("evaluation review not found:"):
                        raise
                else:
                    raise EvaluationContractError("review ID already exists; create a new review")
                store.save_review(review)
            finally:
                store.close()
            print(json.dumps({"status": "saved", "review_id": review.review_id}))
            return 0

        if args.evaluation_command == "langsmith-sync":
            from trivae.evaluation.langsmith_sync import export_experiment
            suite = EvaluationSuite.from_json(args.suite)
            run_ids = args.run_id
            if args.variant_id is not None:
                if run_ids or args.records is None:
                    raise EvaluationContractError("--variant-id requires --records and cannot be combined with --run-id")
                try:
                    raw = json.loads(args.records.read_text(encoding="utf-8"))
                    case_ids = {ref.case_id for ref in suite.case_references}
                    run_ids = [record["run_id"] for record in raw if record.get("variant_id") == args.variant_id
                               and record.get("case_id") in case_ids]
                except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                    raise EvaluationContractError("benchmark records cannot be selected") from exc
            if not run_ids and args.manifest is not None:
                try:
                    record = json.loads(args.manifest.read_text(encoding="utf-8"))
                    run_ids = [item["run_id"] for item in record["runs"]]
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    raise EvaluationContractError("experiment manifest runs cannot be selected") from exc
            if not run_ids:
                raise EvaluationContractError("select --run-id, --variant-id with --records, or --manifest")
            result = export_experiment(
                evaluation_db=args.evaluation_database, suite=suite,
                cases=_load_cases(args.cases_dir), include_content=not args.metadata_only and args.content is None,
                run_ids=run_ids, experiment=args.experiment, ledger_path=args.ledger,
                trace_db=args.trace_database, content_path=args.content,
                records_path=args.records, judgments_path=args.judgments, failures_path=args.failures,
                manifest_path=args.manifest,
                variant_path=args.variant_file, import_time=args.import_time,
                history_report_path=args.history_report, history_note=args.history_note,
                require_complete=args.require_complete,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.evaluation_command == "regression":
            print(json.dumps(dict(M6_FAILURE_REGRESSION_MAP), ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.evaluation_command == "router-jev":
            return _run_router_jev_evaluation(args)

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

        if args.evaluation_command == "benchmark":
            return _run_benchmark_command(args)

        if args.evaluation_command == "run":
            suite = EvaluationSuite.from_json(args.suite)
            variant = _load_variant(args.variant)
            cases = _load_cases(args.cases_dir)
            selected_cases = None
            if args.case_list is not None:
                try:
                    selection = json.loads(args.case_list.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise EvaluationContractError("selected Case list cannot be read") from exc
                selected_cases = [ref.identity for ref in select_suite_references(suite, selection)]
            if (args.record_dir is None) != (args.freeze_manifest is None):
                raise EvaluationContractError("--record-dir and --freeze-manifest must be supplied together")
            manifest = None
            if args.record_dir is not None:
                from trivae.evaluation.experiment_manifest import prepare_experiment
                if args.evaluation_database is None or args.evaluation_database.exists():
                    raise EvaluationContractError("formal evaluation requires a new independent --evaluation-database")
                manifest = prepare_experiment(
                    suite=suite, cases=cases, variant=variant, database=args.database,
                    freeze_path=args.freeze_manifest, output_dir=args.record_dir,
                    repetitions=args.repeat, judge_version=args.judge_version, selected_cases=selected_cases,
                )

            async def evaluate_suite() -> tuple[EvaluationRun, ...]:
                """在同一 event loop 内运行 Evaluation 并关闭主模型与 Jev client。"""

                async with create_application(
                    args.database,
                    evaluation_database_path=args.evaluation_database,
                ) as application:
                    if selected_cases is not None:
                        return await application.evaluate_suite(
                            suite, cases, variant, repetitions=args.repeat, selected_cases=selected_cases,
                        )
                    return await application.evaluate_suite(
                        suite,
                        cases,
                        variant,
                        repetitions=args.repeat,
                    )

            try:
                runs = asyncio.run(evaluate_suite())
            except Exception as exc:
                if manifest is not None:
                    from trivae.evaluation.experiment_manifest import finish_experiment
                    from trivae.evaluation.store import SQLiteEvaluationStore
                    saved: tuple[EvaluationRun, ...] = ()
                    if args.evaluation_database.is_file():
                        store = SQLiteEvaluationStore(args.evaluation_database)
                        try:
                            saved = store.list_runs()
                        finally:
                            store.close()
                    finish_experiment(args.record_dir, manifest, saved, error_type=type(exc).__name__)
                raise
            if manifest is not None:
                from trivae.evaluation.experiment_manifest import finish_experiment
                finish_experiment(args.record_dir, manifest, runs)
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


def _semantic_status_projection(
    status: SemanticIndexStatusReport,
    args: argparse.Namespace,
) -> dict[str, object]:
    """给 status 增加可复制的下一步命令，同时保留原始可运维字段。"""

    projection = status.to_dict()
    state = projection.get("status")
    common = ["--database", str(args.database)]
    if args.semantic_index is not None:
        common.extend(("--semantic-index", str(args.semantic_index)))
    if state == "completed":
        next_action = "run a bounded semantic smoke or an explicit semantic-enabled query"
        command = shlex.join(["trivae", "semantic", "smoke", *common, "--query", "<query>"])
    elif state == "building":
        next_action = "wait for the active rebuild and poll status"
        command = shlex.join(["trivae", "semantic", "status", *common])
    else:
        # missing/stale/failed/partial 都需要用户显式重建；CLI 不会自动切换到 lexical。
        next_action = "explicitly rebuild the semantic derived index"
        command = shlex.join(["trivae", "semantic", "rebuild", *common])
    projection["operational_guidance"] = {
        "next_action": next_action,
        "next_command": command,
    }
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
                # 续建必须由用户显式选择；默认 rebuild 仍然清空并重建派生索引。
                rebuild = application.rebuild_semantic_index(resume=args.resume).to_dict()
                integrity = application.validate_semantic_index().to_dict()
            elif args.semantic_command == "smoke" and args.rebuild:
                rebuild = application.rebuild_semantic_index().to_dict()
                integrity = application.validate_semantic_index().to_dict()

            status = application.semantic_index_status()
            status_projection = _semantic_status_projection(status, args)
            if args.semantic_command == "status":
                _write_json_projection(status_projection, None)
                return 0
            if args.semantic_command == "rebuild":
                _write_json_projection(
                    {"rebuild": rebuild, "integrity": integrity, "status": status_projection},
                    None,
                )
                return 0 if integrity is not None and integrity["status"] == "valid" else 1
            if args.semantic_command == "smoke":
                smoke = _semantic_smoke_projection(application, args)
                _write_json_projection(
                    {
                        "status": smoke["tool_status"],
                        "index": status_projection,
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


def _print_chat_list(
    sessions: tuple[ChatSession, ...],
    *,
    output_fn: Callable[[str], None],
) -> None:
    """输出稳定排序的群聊清单，序号只在当前 CLI 生命周期内有效。"""

    output_fn("Available chats:")
    for index, session in enumerate(sessions, start=1):
        output_fn(f"{index}. {session.name}")
    output_fn("0. All chats")


def _print_chat_commands(*, output_fn: Callable[[str], None]) -> None:
    """输出交互模式支持的命令，供启动提示和 /help 复用。"""

    # 命令清单只描述当前 CLI 已实现的动作，避免帮助文本与分支逻辑漂移。
    output_fn("/help  Show available commands")
    output_fn("/new   Start a new conversation")
    output_fn("/scope  Show current scope")
    output_fn("/chats  Switch chat scope")
    output_fn("/status Show local readiness")
    output_fn("/history  List saved conversations")
    output_fn("/resume n  Resume a saved conversation")
    output_fn("/good [note]  Mark the last answer helpful")
    output_fn("/bad [note]  Mark the last answer unhelpful")
    output_fn("/feedback  Show feedback for the last answer")
    output_fn("/source n  Inspect a cited source")
    output_fn("/exit  Exit")


def _scope_label(scope: ExecutionScope, selected_name: str) -> str:
    """将 trusted scope 投影为不泄漏内部 locator 的人类标签。"""

    return selected_name if scope.allowed_session_ids is not None else "All chats"


def _print_scope(
    scope: ExecutionScope,
    selected_name: str,
    conversation_id: str | None,
    *,
    output_fn: Callable[[str], None],
) -> None:
    """展示当前 scope/conversation 边界，避免用户猜测历史是否会复用。"""

    output_fn(f"Scope: {_scope_label(scope, selected_name)}")
    output_fn(f"Time range: {_scope_time_label(scope)}")
    output_fn(f"Result limit: {scope.max_results}")
    output_fn(f"Conversation: {'active' if conversation_id else 'new'}")


def _scope_time_label(scope: ExecutionScope) -> str:
    """输出半开时间区间的稳定描述。"""

    start = "beginning" if scope.start_timestamp is None else str(scope.start_timestamp)
    end = "end" if scope.end_timestamp is None else str(scope.end_timestamp)
    return f"[{start}, {end})"


def _print_readiness(
    readiness: object,
    *,
    output_fn: Callable[[str], None],
) -> None:
    """用少量稳定字段展示本地 readiness，不把 safe dict 当作普通终端输出。"""

    database_status = getattr(readiness, "database_status", "unavailable")
    session_count = getattr(readiness, "session_count", None)
    message_count = getattr(readiness, "message_count", None)
    output_fn(
        f"Ready: database={database_status}, sessions={session_count}, messages={message_count}"
    )
    provider = getattr(readiness, "provider", None)
    if provider is not None:
        provider_status = getattr(provider, "status", "unknown")
        provider_name = getattr(provider, "provider", None)
        model_name = getattr(provider, "model", None)
        detail = ", ".join(value for value in (provider_name, model_name) if isinstance(value, str))
        output_fn(f"Provider: {provider_status}{f' ({detail})' if detail else ''}")
    semantic = getattr(readiness, "semantic", None)
    if semantic is not None:
        identity = getattr(semantic, "configured_identity", None)
        embedding = getattr(identity, "embedding", None)
        semantic_parts = [
            value
            for value in (
                getattr(embedding, "provider", None),
                getattr(embedding, "model", None),
            )
            if isinstance(value, str)
        ]
        dimension = getattr(embedding, "dimension", None)
        if isinstance(dimension, int):
            semantic_parts.append(f"dim={dimension}")
        chunker_version = getattr(identity, "chunker_version", None)
        if isinstance(chunker_version, str):
            semantic_parts.append(f"chunker={chunker_version}")
        semantic_detail = ", ".join(semantic_parts)
        suffix = f" ({semantic_detail})" if semantic_detail else ""
        output_fn(f"Semantic index: {semantic.status}{suffix}")
    else:
        error = getattr(readiness, "semantic_message", None)
        output_fn(f"Semantic index: unavailable{f' ({error})' if error else ''}")


def _print_history(
    summaries: tuple[ConversationSummary, ...],
    *,
    sessions: tuple[ChatSession, ...],
    output_fn: Callable[[str], None],
) -> None:
    """以序号展示 bounded history、更新时间和 scope，只有完整 scope 才允许恢复。"""

    if not summaries:
        output_fn("No saved conversations.")
        return
    output_fn("Conversation history:")
    for index, summary in enumerate(summaries, start=1):
        resumable = "resumable" if summary.scope is not None else "scope unavailable"
        scope_name = (
            _scope_name_from_sessions(summary.scope, sessions)
            if summary.scope is not None
            else "scope unavailable"
        )
        # 只展示 Store 提供的更新时间和首问标题，不为历史列表额外调用 Provider。
        output_fn(
            f"{index}. {summary.title} · {summary.updated_at} · {scope_name} · "
            f"{summary.message_count} messages · {resumable}"
        )


def _scope_name_from_sessions(scope: ExecutionScope, sessions: tuple[ChatSession, ...]) -> str:
    """仅在 session metadata 精确匹配时显示名称，否则使用不带猜测的通用标签。"""

    if scope.allowed_session_ids is None:
        return "All chats"
    if len(scope.allowed_session_ids) == 1:
        selected_id = scope.allowed_session_ids[0]
        for session in sessions:
            if session.session_id == selected_id:
                return session.name
    return "Saved scope"


def _feedback_target(result: QueryResult | None) -> tuple[str, str, str] | None:
    """从最后一轮成功 Query 提取 feedback 所需的完整关联 identity。"""

    if result is None or not result.is_successful:
        return None
    if result.conversation_id is None or result.trace_id is None or result.runtime_result.run_id is None:
        return None
    return result.conversation_id, result.trace_id, result.runtime_result.run_id


def _print_feedback(record: FeedbackRecord | None, *, output_fn: Callable[[str], None]) -> None:
    """展示反馈状态，不输出内部 feedback id。"""

    if record is None:
        output_fn("No feedback saved for the last answer.")
        return
    output_fn(f"Feedback: {record.rating}")
    if record.note:
        output_fn(f"Note: {record.note}")
    output_fn(f"Updated: {record.updated_at}")


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
    source_summaries: tuple[AnswerSourceSummary, ...] = (),
    verbose: bool = False,
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

    artifact = getattr(result, "answer_artifact", None)
    if result.is_successful and isinstance(artifact, AnswerArtifact):
        # Evidence 与 Sources 必须从同一个 validated Artifact 投影，不能重新查询或相信模型正文。
        _print_evidence_block(artifact, source_summaries, output_fn=output_fn)
    if result.is_successful and source_summaries:
        _print_source_block(source_summaries, output_fn=output_fn, verbose=verbose)
    if result.is_successful and isinstance(artifact, AnswerArtifact):
        limitations = _answer_limitations(artifact)
        if artifact.resolved_time_range:
            # 最终时间事实由 Host 投影，直接显示 UTC 区间，避免正文中的人工换算成为唯一依据。
            start = artifact.resolved_time_range.get("resolved_start_utc") or "-"
            end = artifact.resolved_time_range.get("resolved_end_utc") or "-"
            output_fn(f"Effective time range: [{start}, {end})")
        if limitations:
            output_fn(f"Note: answer limitations — {'; '.join(limitations)}")
        if result.is_degraded:
            # degraded 仍是可交付答案，但必须把 citation/字段丢弃事实明确告诉用户。
            output_fn("Note: answer validation was degraded; inspect the trace diagnostics.")

    # 每一轮 Query 都沿用 Application 产生的 Trace identity，详细查看交给 trace CLI。
    if result.trace_id is not None:
        output_fn(f"[trace: {result.trace_id}]")
    if log_path is not None:
        # Application 返回绝对路径，终端通常可以直接点击定位本地文件。
        output_fn(f"[log: {log_path}]")
    elif log_error is not None:
        # 导出失败必须可见，但不能把已经得到的正式答案改写成失败。
        output_fn(f"[trace log unavailable: {log_error}]")


def _print_source_block(
    source_summaries: tuple[AnswerSourceSummary, ...],
    *,
    output_fn: Callable[[str], None],
    verbose: bool,
) -> None:
    """展示 finalized Artifact 的来源摘要，不把 raw event 或正文转储到终端。"""

    output_fn("Sources:")
    for summary in source_summaries:
        reference = summary.reference
        if isinstance(reference, MessageSource):
            snapshot = reference.snapshot
            if snapshot is None:
                # 缺失 trusted snapshot 是 contract 问题，不能拿 locator 猜展示信息。
                output_fn(f"{summary.index}. message source metadata unavailable")
                continue
            author = snapshot.author_display or "unknown author"
            time_label = "forwarded at " if snapshot.forward is not None else ""
            rendered = (
                f"{summary.index}. message · {snapshot.session_display} · "
                f"{author} · {time_label}{_format_timestamp(snapshot.timestamp_ms, snapshot.timezone)} · "
                f"{_bounded_cli_text(snapshot.excerpt, 240)}"
            )
            if verbose:
                rendered += f" · {reference.internal_message_id}"
            output_fn(rendered)
            if snapshot.forward is not None:
                _print_forward_details(
                    snapshot.forward,
                    source_message_id=snapshot.source_message_id,
                    sender_platform_id=snapshot.sender_platform_id,
                    sender_uin=snapshot.sender_uin,
                    output_fn=output_fn,
                )
            for path in snapshot.unexpanded_forward_paths:
                output_fn(f"   Missing forward content: {path} · exported messages=[]; preview is incomplete")
            for url in snapshot.urls:
                output_fn(f"   URL: {url}")
            continue
        if isinstance(reference, StructuredSource):
            rendered = f"{summary.index}. {reference.locator_kind} source"
            if reference.query_scope_snapshot:
                rendered += " · scoped result"
            if verbose:
                rendered += f" · {reference.locator}"
            output_fn(rendered)
            output_fn(f"   Value: {_bounded_cli_value(reference.value_snapshot, 800)}")
            if reference.source_id:
                output_fn(f"   Source ID: {reference.source_id}")
            for url in extract_urls(reference.value_snapshot):
                output_fn(f"   URL: {url}")


def _print_evidence_block(
    artifact: AnswerArtifact,
    source_summaries: tuple[AnswerSourceSummary, ...],
    *,
    output_fn: Callable[[str], None],
) -> None:
    """把 validated claim→evidence→source 关系直接投影到答案层。"""

    if not artifact.evidence_items:
        return
    output_fn("Evidence:")
    source_indexes = {
        source_reference_key(summary.reference): summary.index for summary in source_summaries
    }
    block_by_id = {block.block_id: block for block in artifact.content_blocks}
    evidence_by_id = {item.evidence_id: item for item in artifact.evidence_items}
    for binding in artifact.citation_bindings:
        block = block_by_id.get(binding.content_block_id)
        if block is None:
            continue
        output_fn(f"Claim {block.block_id} → {', '.join(binding.evidence_ids)}")
        for evidence_id in binding.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            output_fn(f"  Finding: {_bounded_cli_text(evidence.finding, 320)}")
            output_fn(f"  Criterion: {_bounded_cli_text(evidence.criterion, 320)}")
            output_fn(f"  Sufficiency: {evidence.sufficiency}")
            indexes = [
                str(source_indexes[source_reference_key(source.reference)])
                for source in evidence.sources
                if source_reference_key(source.reference) in source_indexes
            ]
            output_fn(f"  Sources: {', '.join(indexes) if indexes else 'none'}")
            if evidence.limitations:
                output_fn(f"  Limitations: {'; '.join(evidence.limitations)}")

    # 没有 binding 的 Evidence 仍然是 Artifact 事实，明确显示而不是静默丢弃。
    bound_ids = {
        evidence_id
        for binding in artifact.citation_bindings
        for evidence_id in binding.evidence_ids
    }
    for evidence in artifact.evidence_items:
        if evidence.evidence_id in bound_ids:
            continue
        output_fn(f"Evidence {evidence.evidence_id} (unbound)")
        output_fn(f"  Finding: {_bounded_cli_text(evidence.finding, 320)}")
        output_fn(f"  Criterion: {_bounded_cli_text(evidence.criterion, 320)}")
        output_fn(f"  Sufficiency: {evidence.sufficiency}")


def _answer_limitations(artifact: AnswerArtifact) -> tuple[str, ...]:
    """将 Artifact 的 partial/limitation 事实投影为简短用户提示。"""

    labels = {
        "tool_result_partial": "a tool returned partial results",
        "retrieval_partial": "retrieval was partial",
        "retrieval_truncated": "retrieval was truncated",
        "unexpanded_forward_content": "some forwarded nodes have no exported messages; previews do not establish their content",
    }
    rendered: list[str] = []
    for limitation in artifact.limitations:
        label = labels.get(limitation, limitation)
        if label not in rendered:
            rendered.append(_bounded_cli_text(label, 240))
    if any(item.sufficiency != "sufficient" for item in artifact.evidence_items):
        rendered.append("some cited evidence is not complete")
    return tuple(rendered[:6])


def _format_timestamp(timestamp_ms: int, timezone_name: str) -> str:
    """按 finalized snapshot 的 timezone 标记输出稳定的人工可读时间。"""

    rendered = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    return f"{rendered} ({timezone_name})"


def _print_forward_details(
    forward: ForwardProvenance,
    *,
    source_message_id: str | None,
    sender_platform_id: str | None,
    sender_uin: str | None,
    output_fn: Callable[[str], None],
) -> None:
    """来源摘要和 drill-down 共同展示 canonical 的父子链与原始时间。"""

    original_time = (
        "unknown"
        if forward.original_timestamp is None
        else _format_timestamp(forward.original_timestamp, "UTC")
    )
    output_fn(f"   Original sent at: {original_time}")
    output_fn(
        f"   Forward: root={forward.root_message_id} · root source ID={forward.root_source_message_id or 'unknown'} · "
        f"parent={forward.parent_message_id} · {forward.path}"
    )
    output_fn(
        f"   Original message: ID={source_message_id or 'unknown'} · "
        f"sender={sender_platform_id or 'unknown'} · UIN={sender_uin or 'unknown'}"
    )
    if forward.source_file is not None:
        # 只显示文件名，record index 与 JSON 路径可定位到导出文件内的原始记录。
        record = f"messages[{forward.source_record_index}]" if forward.source_record_index is not None else "record unknown"
        output_fn(f"   Export: {Path(forward.source_file).name} · {record}.{forward.path}")


def _print_source_detail(
    summary: AnswerSourceSummary,
    *,
    application: TrivaeApplication,
    scope: ExecutionScope,
    output_fn: Callable[[str], None],
    verbose: bool,
) -> None:
    """执行来源 drill-down；Message Source 必须重新读取 bounded canonical context。"""

    reference = summary.reference
    if isinstance(reference, StructuredSource):
        output_fn(f"Source {summary.index}: {reference.locator_kind} result")
        output_fn(f"Value: {_bounded_cli_value(reference.value_snapshot, 800)}")
        if reference.execution_limitations:
            output_fn(f"Limitations: {', '.join(reference.execution_limitations)}")
        if verbose:
            output_fn(f"Locator: {reference.locator}")
        return
    if isinstance(reference, SourceHandleReference):
        # transient handle 不应越过 finalizer；若出现则显式显示 unavailable，不猜测来源。
        output_fn(f"Source {summary.index} unavailable: source handle was not finalized")
        return

    try:
        messages = application.inspect_message_source(reference, scope)
    except SourceInspectionError as exc:
        output_fn(f"Source {summary.index} unavailable: {exc}")
        return

    output_fn(f"Source {summary.index}: message context")
    for message in messages:
        marker = ">" if message.internal_message_id == reference.internal_message_id else " "
        author = message.sender_name or message.sender_user_id or "unknown author"
        excerpt = _bounded_cli_text(message.normalized_content, 480)
        time_label = "forwarded at " if message.forward is not None else ""
        output_fn(
            f"{marker} {message.session_display} · {author} · "
            f"{time_label}{_format_timestamp(message.timestamp, 'UTC')} · {excerpt}"
        )
        if message.forward is not None:
            _print_forward_details(
                message.forward,
                source_message_id=message.source_message_id,
                sender_platform_id=message.sender_platform_id,
                sender_uin=message.sender_uin,
                output_fn=output_fn,
            )
        for path in message.unexpanded_forward_paths:
            output_fn(f"   Missing forward content: {path} · exported messages=[]; preview is incomplete")
        if verbose and marker == ">":
            output_fn(f"  message_id: {message.internal_message_id}")


def _bounded_cli_text(value: object, max_chars: int) -> str:
    """给来源查看提供单行、有限长度的正文投影。"""

    rendered = str(value).replace("\n", "\\n")
    return rendered if len(rendered) <= max_chars else f"{rendered[:max_chars - 1]}…"


def _bounded_cli_value(value: object, max_chars: int) -> str:
    """把 structured source 显示为 key=value，而不是 JSON 转储。"""

    if isinstance(value, Mapping):
        rendered = ", ".join(
            f"{key}={_bounded_cli_value(item, max(80, max_chars // 4))}"
            for key, item in list(value.items())[:12]
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rendered = ", ".join(
            _bounded_cli_value(item, max(80, max_chars // 4))
            for item in list(value)[:12]
        )
    else:
        rendered = str(value)
    return _bounded_cli_text(rendered, max_chars)


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

    readiness_reader = getattr(application, "readiness", None)
    if callable(readiness_reader):
        _print_readiness(readiness_reader(), output_fn=write_output)

    # Session metadata 通过 Application facade 读取，CLI 不直接读 SQLite。
    sessions = application.list_sessions()
    if not sessions:
        write_output("No chats found in the Canonical Store.")
        return 1

    # 先展示稳定排序后的真实群聊，再提供 unrestricted 入口。
    write_output("Trivae interactive chat")
    write_output("")
    _print_chat_list(sessions, output_fn=write_output)

    # picker 返回的 scope 在本次 CLI 生命周期内保持不变。
    selected = _select_chat(sessions, input_fn=read_input, output_fn=write_output)
    if selected is None:
        return 0
    scope, selected_name = selected
    write_output(f"Selected: {selected_name}")
    _print_chat_commands(output_fn=write_output)

    # conversation_id 与 scope 是两个独立状态；/new 还会清空上一轮来源索引。
    conversation_id: str | None = None
    last_sources: tuple[AnswerSourceSummary, ...] = ()
    last_result: QueryResult | None = None
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

        if query == "/help":
            # 帮助只读当前交互状态，不创建 Query 或改变 scope/conversation。
            _print_chat_commands(output_fn=write_output)
            continue

        # /new 只清空 Conversation identity，绝不改写已经选择的 trusted scope。
        if query == "/new":
            conversation_id = None
            last_sources = ()
            last_result = None
            write_output("Started a new conversation.")
            continue

        if query == "/scope":
            _print_scope(scope, selected_name, conversation_id, output_fn=write_output)
            continue

        if query == "/status":
            readiness_reader = getattr(application, "readiness", None)
            if not callable(readiness_reader):
                write_output("Status is unavailable from this application.")
                continue
            _print_readiness(readiness_reader(), output_fn=write_output)
            _print_scope(scope, selected_name, conversation_id, output_fn=write_output)
            continue

        if query == "/chats":
            _print_chat_list(sessions, output_fn=write_output)
            selected = _select_chat(sessions, input_fn=read_input, output_fn=write_output)
            if selected is None:
                return 0
            scope, selected_name = selected
            conversation_id = None
            last_sources = ()
            last_result = None
            write_output(f"Switched to: {selected_name}")
            write_output("Started a new conversation.")
            continue

        if query == "/history":
            try:
                summaries = application.list_conversations()
            except ConversationError as exc:
                write_output(f"History unavailable: {exc}")
                continue
            _print_history(summaries, sessions=sessions, output_fn=write_output)
            continue

        if query.startswith("/resume"):
            parts = query.split()
            if len(parts) != 2 or not parts[1].isdigit():
                write_output("Usage: /resume n")
                continue
            try:
                summaries = application.list_conversations()
            except ConversationError as exc:
                write_output(f"History unavailable: {exc}")
                continue
            resume_index = int(parts[1])
            if resume_index < 1 or resume_index > len(summaries):
                write_output("Conversation number is not available.")
                continue
            summary = summaries[resume_index - 1]
            try:
                resumed = application.resume_conversation(summary.conversation_id)
            except ConversationError as exc:
                write_output(f"Conversation cannot be resumed: {exc}")
                continue
            if resumed.scope is None:
                # Application contract 已检查；这里保留显式边界，防止未来 Store 破坏类型。
                write_output("Conversation cannot be resumed: scope metadata is unavailable.")
                continue
            scope = resumed.scope
            selected_name = _scope_name_from_sessions(scope, sessions)
            conversation_id = resumed.conversation_id
            last_sources = ()
            last_result = None
            write_output(f"Resumed: {summary.title}")
            _print_scope(scope, selected_name, conversation_id, output_fn=write_output)
            continue

        if query == "/feedback":
            target = _feedback_target(last_result)
            if target is None:
                write_output("Feedback is available after a completed answer.")
                continue
            try:
                _print_feedback(
                    application.read_feedback(target[0], target[1]),
                    output_fn=write_output,
                )
            except FeedbackError as exc:
                write_output(f"Feedback unavailable: {exc}")
            continue

        if query == "/good" or query.startswith("/good ") or query == "/bad" or query.startswith("/bad "):
            command, _, note = query.partition(" ")
            target = _feedback_target(last_result)
            if target is None:
                write_output("Feedback is available after a completed answer.")
                continue
            try:
                application.save_feedback(
                    conversation_id=target[0],
                    trace_id=target[1],
                    run_id=target[2],
                    scope=scope,
                    rating="good" if command == "/good" else "bad",
                    note=note or None,
                )
            except FeedbackError as exc:
                write_output(f"Feedback was not saved: {exc}")
                continue
            write_output("Feedback saved.")
            continue

        if query.startswith("/source"):
            parts = query.split()
            if len(parts) != 2 or not parts[1].isdigit():
                write_output("Usage: /source n")
                continue
            source_index = int(parts[1])
            selected_source = next(
                (summary for summary in last_sources if summary.index == source_index),
                None,
            )
            if selected_source is None:
                write_output("Source number is not available from the last answer.")
                continue
            _print_source_detail(
                selected_source,
                application=application,
                scope=scope,
                output_fn=write_output,
                verbose=verbose,
            )
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
        except (
            CapabilityContractError,
            ConversationError,
            QueryContractError,
            RetrievalError,
            SettingsError,
            TraceStoreError,
        ) as exc:
            renderer.finish()
            write_output(f"Error: {exc}")
            trace_id = getattr(exc, "trace_id", None)
            if isinstance(trace_id, str) and trace_id:
                write_output(f"[trace: {trace_id}]")
            last_result = None
            continue
        except Exception as exc:
            # 未知异常写入日志，同时给终端一个可行动的类型诊断，不输出长 traceback。
            renderer.finish()
            logging.getLogger(__name__).exception("TRIVAE_INTERACTIVE_QUERY_FAILED")
            write_output(f"Error: unexpected query failure ({type(exc).__name__}); inspect the trace log.")
            trace_id = getattr(exc, "trace_id", None)
            if isinstance(trace_id, str) and trace_id:
                write_output(f"[trace: {trace_id}]")
            last_result = None
            continue
        finally:
            # 成功、分类错误、task cancellation 和 Ctrl+C 都必须恢复到完整终端行。
            renderer.finish()
        # QueryResult 是 Conversation identity 的正式返回边界，后续轮次复用它。
        conversation_id = result.conversation_id
        artifact = getattr(result, "answer_artifact", None)
        if result.is_successful and isinstance(artifact, AnswerArtifact):
            last_sources = answer_source_summaries(artifact)
            last_result = result
        else:
            last_sources = ()
            last_result = None
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
            source_summaries=last_sources,
            verbose=verbose,
        )


async def _run_tui_chat(application: TrivaeApplication, *, verbose: bool) -> int:
    """以 Textual TUI 运行交互 chat；Runtime 仍由 Application 唯一执行。"""

    # macOS 中文 IME 需要终端传递完整的组字序列；Kitty 全键盘协议会打断该序列。
    # Textual 在首次 import 时读取此开关，因此必须在下方局部 import 之前固定协议选择。
    os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = "1"
    # 局部 import 保持 plain 路径不加载 Textual。
    from trivae.interfaces.tui.app import TrivaeChatApp

    sessions = application.list_sessions()
    if not sessions:
        print("No chats found in the Canonical Store.")
        return 1
    readiness_lines: list[str] = []
    readiness_reader = getattr(application, "readiness", None)
    if callable(readiness_reader):
        _print_readiness(readiness_reader(), output_fn=readiness_lines.append)
    readiness_summary = " · ".join(readiness_lines) if readiness_lines else "Readiness unavailable"
    tui_app = TrivaeChatApp(
        application,
        sessions=sessions,
        readiness_summary=readiness_summary,
        verbose=verbose,
    )
    # 标准全屏（alternate screen）模式：渲染路径最成熟；退出后终端恢复原样。
    await tui_app.run_async()
    return 0


def _run_chat_command(args: argparse.Namespace) -> int:
    """创建正式 Application 并运行 chat；已分类错误可读，未知错误继续暴露。"""

    try:
        # CLI 入口负责注入工作目录配置，库层 load_settings 不隐式读取凭据文件。
        load_environment_file(args.env_file)
        # Application 统一拥有 Store、Provider、Conversation 和 Trace lifecycle。
        with create_application(args.database) as application:
            use_plain = args.plain or not sys.stdout.isatty()

            async def run_chat() -> int:
                """在 CLI 查询使用的 event loop 内退出 TUI/关闭 Async Provider。"""

                try:
                    if use_plain:
                        return await _run_interactive_chat(application, verbose=args.verbose)
                    return await _run_tui_chat(application, verbose=args.verbose)
                finally:
                    await application.aclose()

            return asyncio.run(run_chat())
    except (EOFError, KeyboardInterrupt):
        # Ctrl+D/Ctrl+C 即使发生在 Query 等待期间，也只做短退出提示。
        print("Bye.")
        return 0
    except (
        DotenvError,
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
    except Exception as exc:
        # 未知启动错误保留 logger traceback，终端只显示稳定诊断类型。
        logging.getLogger(__name__).exception("TRIVAE_CHAT_FAILED")
        print(f"Error: unexpected failure ({type(exc).__name__}); inspect diagnostics.")
        trace_id = getattr(exc, "trace_id", None)
        if isinstance(trace_id, str) and trace_id:
            print(f"[trace: {trace_id}]")
        return 1


def _run_web_command(args: argparse.Namespace) -> int:
    """启动 Local Web UI；执行链路仍然完全复用 Application。"""

    # 延迟导入保持其他 CLI 子命令不加载 FastAPI。
    from trivae.interfaces.web.server import WebServerSettings, run_web_server

    try:
        return run_web_server(
            WebServerSettings(
                database_path=args.database,
                host=args.host,
                port=args.port,
                open_browser=not args.no_open,
            )
        )
    except KeyboardInterrupt:
        print("Web server stopped.")
        return 0
    except (
        DotenvError,
        CapabilityContractError,
        ConversationError,
        QueryContractError,
        RetrievalError,
        SettingsError,
        TraceStoreError,
    ) as exc:
        print(f"Error: {exc}")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """执行 CLI；已分类 ingestion error 转成非零状态，未知异常继续暴露。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "digest":
        from trivae.interfaces.digest_cli import run_digest_command

        return run_digest_command(args)
    if args.command == "import-once":
        # 轻量 Composition Root 仍使用 SharedImporter，不初始化 Evaluation 或模型。
        from trivae.interfaces.import_once_cli import run_import_once_command

        return run_import_once_command(args)
    if args.command == "auth":
        # OAuth 生命周期由独立认证模块拥有，CLI 不接触或打印 Token。
        from trivae.interfaces.auth_cli import run_auth_command

        return run_auth_command(args)
    if args.command == "chat":
        return _run_chat_command(args)
    if args.command == "web":
        return _run_web_command(args)
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
