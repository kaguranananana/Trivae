"""Benchmark 编排：pre-run gate → suite×variant 执行 → GT 评分 → failure artifact → 报告。

编排器只消费现有 Application facade（``evaluate_suite`` / ``generate_retrieval_annotation_packet``
/ ``materialize_evaluation_snapshot`` / ``semantic_index_status``），不创建 Runtime/Tool 实例。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

from trivae.bootstrap.application import TrivaeApplication
from trivae.config.settings import ModelSettings
from trivae.evaluation.contracts import (
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationRun,
    EvaluationSuite,
)
from trivae.evaluation.variant import ControlledVariant

from .environment import BenchmarkEnvironmentManifest, EnvironmentGateResult, verify_environment
from .failures import BenchmarkFailure, evaluate_case_failure
from .gt import CaseGroundTruth, build_ground_truth_index
from .metrics import evaluate_end_to_end_case
from .report import build_report, write_report_outputs
from .retrieval import assert_benchmark_variants, score_sealed_packet


@dataclass(frozen=True)
class BenchmarkRunOutcome:
    """一次 benchmark 编排的完整产出引用。"""

    runs: tuple[EvaluationRun, ...]
    end_to_end_records: tuple[dict[str, object], ...]
    failures: tuple[BenchmarkFailure, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_count": len(self.runs),
            "end_to_end_record_count": len(self.end_to_end_records),
            "failure_count": len(self.failures),
            "failures": [item.to_dict() for item in self.failures],
        }


class BenchmarkOrchestrator:
    """拥有 Application facade 引用的 benchmark 编排器。"""

    def __init__(self, *, application: TrivaeApplication, database_path: Path) -> None:
        if not isinstance(application, TrivaeApplication):
            raise EvaluationContractError("BenchmarkOrchestrator requires a TrivaeApplication")
        self._application = application
        self._database_path = database_path

    def load_manifest(self, manifest_path: Path) -> BenchmarkEnvironmentManifest:
        manifest = BenchmarkEnvironmentManifest.from_json(manifest_path)
        self._verify_manifest_identity(manifest)
        return manifest

    def _semantic_identity(self) -> str:
        report = self._application.semantic_index_status()
        persisted = report.persisted_identity
        if persisted is None:
            raise EvaluationContractError("semantic index is missing; benchmark cannot start")
        return persisted.serialized

    def _verify_manifest_identity(self, manifest: BenchmarkEnvironmentManifest) -> None:
        expected_database = self._application.store.database_path
        if expected_database.resolve() != self._database_path.resolve():
            raise EvaluationContractError("orchestrator database path differs from application store")

    def preflight_gate(self, manifest: BenchmarkEnvironmentManifest) -> EnvironmentGateResult:
        """三查：canonical snapshot / lexical count / semantic identity。"""

        snapshot = self._application.materialize_evaluation_snapshot()
        return verify_environment(
            manifest,
            database_path=self._database_path,
            snapshot=snapshot,
            semantic_index_identity=self._semantic_identity(),
        )

    def build_gt_index(self, cases: dict[str, EvaluationCaseBundle]) -> dict[str, CaseGroundTruth]:
        return build_ground_truth_index(cases)

    async def run_variant_suite(
        self,
        *,
        suite: EvaluationSuite,
        cases: dict[str, EvaluationCaseBundle],
        variant: ControlledVariant,
        repetitions: int,
    ) -> tuple[EvaluationRun, ...]:
        """逐 case 执行一个 variant × suite。

        Runner 会把单 case 异常先落盘再向上抛；benchmark 编排层捕获后继续下一个
        case（provider crash 不得杀死整个 variant），异常细节记入 stderr/日志，
        已落盘的 exception run 会作为 provider_failure 进入报告。
        """

        all_runs: list[EvaluationRun] = []
        for reference in suite.case_references:
            case = cases.get(reference.case_id)
            if case is None or case.identity != reference.identity:
                raise EvaluationContractError(f"suite case cannot be resolved: {reference.identity}")
            try:
                all_runs.extend(
                    await self._application.evaluate_case(case, variant, repetitions=repetitions)
                )
            except Exception as exc:  # noqa: BLE001 - 单 case 异常必须隔离，不终止 suite
                print(
                    json.dumps(
                        {
                            "status": "case_exception",
                            "case_id": case.case_id,
                            "variant_id": variant.variant_id,
                            "exception": type(exc).__name__,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                saved: list[EvaluationRun] = []
                store = self._application.evaluation_store
                list_runs = getattr(store, "list_runs", None)
                if callable(list_runs):
                    saved = [
                        run
                        for run in list_runs(case_id=case.case_id)
                        if run.variant_id == variant.variant_id
                    ]
                if saved:
                    all_runs.append(max(saved, key=lambda run: run.completed_at))
        return tuple(all_runs)

    def score_variant_runs(
        self,
        *,
        runs: tuple[EvaluationRun, ...],
        gt_index: dict[str, CaseGroundTruth],
        variant_id: str,
    ) -> tuple[list[dict[str, object]], tuple[BenchmarkFailure, ...]]:
        """对单 variant 的 runs 做 Tier 1 评分 + acceptance failure 判定。"""

        records: list[dict[str, object]] = []
        failures: list[BenchmarkFailure] = []
        for run in runs:
            gt = gt_index.get(run.case_id)
            if gt is None:
                raise EvaluationContractError(f"run {run.run_id} references unknown benchmark case {run.case_id}")
            outcome = evaluate_end_to_end_case(
                gt,
                run.query_result,
                operational_measurements=run.operational_measurements,
            )
            records.append(
                {
                    "case_id": run.case_id,
                    "variant_id": variant_id,
                    "category": gt.category,
                    "split": gt.benchmark_split or "development",
                    "run_id": run.run_id,
                    "run_status": outcome["run_status"],
                    "flags": outcome["flags"],
                    "metrics": outcome["metrics"],
                    # 把同一 EvaluationRun 的 operational facts 带入 report，
                    # 让 latency/tool/token 聚合与质量指标共享完全相同的分母。
                    "operational_measurements": dict(run.operational_measurements),
                    "trace_id": run.trace_id,
                }
            )
            failure = evaluate_case_failure(
                gt,
                variant_id=variant_id,
                run_id=run.run_id,
                run_query_result=run.query_result,
                trace_id=run.trace_id,
            )
            if failure is not None:
                failures.append(failure)
        return records, tuple(failures)

    def write_benchmark_outputs(
        self,
        *,
        output_dir: Path,
        report: dict[str, object],
        failures: tuple[BenchmarkFailure, ...],
        raw_records: tuple[dict[str, object], ...],
    ) -> None:
        """落盘 report.json / report.md / failures.json / raw-records.json（全部 local-only）。"""

        output_dir.mkdir(parents=True, exist_ok=True)
        failures_dir = output_dir / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        write_report_outputs(
            report,
            json_path=output_dir / "report.json",
            markdown_path=output_dir / "report.md",
        )
        (failures_dir / "failures.json").write_text(
            json.dumps([item.to_dict() for item in failures], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "raw-records.json").write_text(
            json.dumps(list(raw_records), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _load_variant(path: Path) -> ControlledVariant:
    """读取 version-controlled Controlled Variant JSON。"""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationContractError(f"variant JSON cannot be read: {path}") from exc
    return ControlledVariant.from_dict(payload)


def load_cases_dir(cases_dir: Path | Sequence[Path]) -> dict[str, EvaluationCaseBundle]:
    """读取一个或多个 Case 目录；跨目录重复 case_id 仍由 contract 拒绝。"""

    directories = (cases_dir,) if isinstance(cases_dir, Path) else tuple(cases_dir)
    if not directories:
        raise EvaluationContractError("benchmark requires at least one cases dir")
    cases: dict[str, EvaluationCaseBundle] = {}
    for directory in directories:
        if not directory.is_dir():
            raise EvaluationContractError(f"benchmark cases dir is not a directory: {directory}")
        for path in sorted(directory.glob("*.json")):
            case = EvaluationCaseBundle.from_json(path)
            if case.case_id in cases:
                raise EvaluationContractError(f"duplicate benchmark case_id: {case.case_id}")
            cases[case.case_id] = case
    if not cases:
        raise EvaluationContractError("benchmark cases dirs contain no cases")
    return cases


def _execution_units(
    suite: EvaluationSuite,
    variants: Sequence[ControlledVariant],
    *,
    paired_by_case: bool,
    paired_order: str = "fixed",
) -> tuple[tuple[EvaluationSuite, ControlledVariant], ...]:
    """生成执行顺序；配对模式保持原 Suite identity 并交替执行同 Case 的两路。"""

    if paired_order not in ("fixed", "counterbalanced"):
        raise EvaluationContractError("paired_order must be fixed or counterbalanced")
    if paired_order == "counterbalanced" and (not paired_by_case or len(variants) != 2):
        raise EvaluationContractError("counterbalanced order requires paired-by-case and exactly two variants")
    if not paired_by_case:
        return tuple((suite, variant) for variant in variants)
    # 每个单 Case Suite 仍保留原 suite_id/version，Evaluation run 身份不会漂移。
    return tuple(
        (replace(suite, case_references=(reference,)), variant)
        for index, reference in enumerate(suite.case_references)
        for variant in (tuple(reversed(variants)) if paired_order == "counterbalanced" and index % 2 else variants)
    )


async def run_benchmark_async(
    *,
    application: TrivaeApplication,
    database_path: Path,
    manifest_path: Path,
    suite: EvaluationSuite,
    cases_dir: Path | Sequence[Path],
    variant_paths: tuple[Path, ...],
    output_dir: Path,
    repetitions: int = 1,
    holdout_sealed: bool = False,
    paired_by_case: bool = False,
    paired_order: str = "fixed",
) -> dict[str, object]:
    """异步 benchmark 主入口：运行、评分和落盘共享调用方的 event loop。"""

    orchestrator = BenchmarkOrchestrator(application=application, database_path=database_path)
    manifest = orchestrator.load_manifest(manifest_path)
    gate = orchestrator.preflight_gate(manifest)
    if not gate.passed:
        return {"status": "gate_failed", "gate": gate.to_dict()}

    cases = load_cases_dir(cases_dir)
    suite_case_ids = {reference.case_id for reference in suite.case_references}
    missing = suite_case_ids - set(cases)
    if missing:
        raise EvaluationContractError(f"suite references cases missing from cases dir: {sorted(missing)!r}")
    gt_index = orchestrator.build_gt_index(cases)

    variants = [_load_variant(path) for path in variant_paths]
    if len({variant.variant_id for variant in variants}) != len(variants):
        raise EvaluationContractError("duplicate variant_id in benchmark variant list")

    units = _execution_units(suite, variants, paired_by_case=paired_by_case, paired_order=paired_order)
    # 顺序策略与实际 unit 序列在付费调用前 create-only 落盘；Case/Suite identity 不变。
    order_manifest: dict[str, object] = {
        "schema_version": 1,
        "experiment_identity": f"{suite.identity}:repeat={repetitions}:paired={paired_by_case}:order={paired_order}:variants={','.join(variant.variant_id for variant in variants)}",
        "suite_identity": suite.identity,
        "repetitions": repetitions,
        "paired_by_case": paired_by_case,
        "paired_order": paired_order,
        "variant_ids": [variant.variant_id for variant in variants],
        "units": [
            {"case_ids": [reference.case_id for reference in selected_suite.case_references], "variant_id": variant.variant_id}
            for selected_suite, variant in units
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "execution-order.json").open("x", encoding="utf-8") as stream:
        json.dump(order_manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    all_records: list[dict[str, object]] = []
    all_failures: list[BenchmarkFailure] = []
    for selected_suite, variant in units:
        # 所有 Variant 共用同一个 loop，避免 provider client 跨 loop 保存连接状态。
        runs = await orchestrator.run_variant_suite(
            suite=selected_suite,
            cases=cases,
            variant=variant,
            repetitions=repetitions,
        )
        records, failures = orchestrator.score_variant_runs(runs=runs, gt_index=gt_index, variant_id=variant.variant_id)
        all_records.extend(records)
        all_failures.extend(failures)

    end_to_end: dict[str, list[dict[str, object]]] = {}
    for record in all_records:
        end_to_end.setdefault(str(record["split"]), []).append(record)

    case_stats = {
        "suite": suite.identity,
        "suite_cases": len(suite_case_ids),
        "by_category": _count_by(all_records, "category"),
        "by_split": _count_by_case(all_records, "split", "case_id"),
        "by_variant_runs": _count_by(all_records, "variant_id"),
    }
    report = build_report(
        benchmark=manifest.benchmark,
        environment=manifest.to_dict(),
        variants=[variant.to_dict() for variant in variants],
        case_stats=case_stats,
        end_to_end_records=end_to_end,
        module_retrieval=None,
        failures=[item.to_dict() for item in all_failures],
        holdout_sealed=holdout_sealed,
    )
    report["experiment_order"] = order_manifest
    orchestrator.write_benchmark_outputs(
        output_dir=output_dir,
        report=report,
        failures=tuple(all_failures),
        raw_records=tuple(all_records),
    )
    return {"status": "completed", "report": report}


def run_benchmark(
    *,
    application: TrivaeApplication,
    database_path: Path,
    manifest_path: Path,
    suite: EvaluationSuite,
    cases_dir: Path | Sequence[Path],
    variant_paths: tuple[Path, ...],
    output_dir: Path,
    repetitions: int = 1,
) -> dict[str, object]:
    """同步包装 benchmark 主入口；CLI 需要使用 async 入口管理 Application lifecycle。"""

    return asyncio.run(
        run_benchmark_async(
            application=application,
            database_path=database_path,
            manifest_path=manifest_path,
            suite=suite,
            cases_dir=cases_dir,
            variant_paths=variant_paths,
            output_dir=output_dir,
            repetitions=repetitions,
        )
    )


def run_module_retrieval_scoring(
    *,
    application: TrivaeApplication,
    database_path: Path,
    manifest_path: Path,
    query_set_path: Path,
    cases_dir: Path,
    lexical_variant_path: Path,
    semantic_variant_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """module-level 双策略确定性评分：现有 Workflow 执行 → GT 直接评分。"""

    orchestrator = BenchmarkOrchestrator(application=application, database_path=database_path)
    manifest = orchestrator.load_manifest(manifest_path)
    gate = orchestrator.preflight_gate(manifest)
    if not gate.passed:
        return {"status": "gate_failed", "gate": gate.to_dict()}
    from trivae.evaluation.retrieval_evaluation import RetrievalQuerySet

    query_set = RetrievalQuerySet.from_json(query_set_path)
    cases = load_cases_dir(cases_dir)
    gt_index = build_ground_truth_index(cases)
    lexical_variant = _load_variant(lexical_variant_path)
    semantic_variant = _load_variant(semantic_variant_path)
    assert_benchmark_variants(lexical_variant, semantic_variant)
    sealed = application.generate_retrieval_annotation_packet(query_set, lexical_variant, semantic_variant)[1]
    scores = score_sealed_packet(sealed, gt_index)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(scores, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "scores": scores}


def judge_records(
    *,
    application: TrivaeApplication,
    records: Sequence[Mapping[str, object]],
    cases_dir: Path,
    settings: ModelSettings,
    output_path: Path,
) -> dict[str, object]:
    """Tier 2 judge：对已落盘的 benchmark runs 做 atomic claim / citation 判定。

    evidence 摘要通过现有 get_message_context Tool facade 读取（bounded）；
    判定产物只写本地（data/evaluation/benchmark/），不含聊天正文。
    """

    import asyncio

    from trivae.capabilities.contracts import GetMessageContextInput
    from trivae.evaluation.benchmark.judge import LLMClaimJudge, canonical_message_excerpt

    cases = load_cases_dir(cases_dir)
    judge = LLMClaimJudge(settings)
    # 幂等续跑：已有判定结果的 run 跳过（provider 瞬时故障后可安全重试批次）。
    existing: dict[str, dict[str, object]] = {}
    if output_path.exists():
        # 已有文件是人工可审阅的结果，解析失败必须保留原件并显式退出。
        try:
            saved = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvaluationContractError(f"cannot read existing judge results: {exc}") from exc
        if not isinstance(saved, list):
            raise EvaluationContractError("existing judge results must be an array")
        for item in saved:
            if not isinstance(item, dict) or not isinstance(item.get("run_id"), str):
                raise EvaluationContractError("existing judge result requires run_id")
            # 显式续跑只跳过成功项，失败项仍允许下一次人工发起的批次重新判定。
            if item.get("status") not in ("judge_failed", "skipped_no_content_blocks"):
                existing[item["run_id"]] = item
    judgments: list[dict[str, object]] = list(existing.values())
    for record in records:
        run_id = record.get("run_id")
        case_id = record.get("case_id")
        variant_id = record.get("variant_id")
        if not (isinstance(run_id, str) and isinstance(case_id, str) and isinstance(variant_id, str)):
            raise EvaluationContractError("benchmark record identity fields are invalid")
        case = cases.get(case_id)
        if case is None:
            raise EvaluationContractError(f"judge record references unknown case {case_id}")
        run = application.read_evaluation_run(run_id)
        if run_id in existing:
            continue
        query_result = run.query_result or {}
        content_blocks = query_result.get("content_blocks") or []
        citation_bindings = query_result.get("citation_bindings") or []
        if not isinstance(content_blocks, Sequence) or isinstance(content_blocks, str):
            content_blocks = []
        if not isinstance(citation_bindings, Sequence) or isinstance(citation_bindings, str):
            citation_bindings = []
        if not content_blocks:
            # 旧 projection 或 no_result 形态：无 block 可判，显式跳过。
            judgments.append(
                {
                    "run_id": run_id,
                    "case_id": case_id,
                    "variant_id": variant_id,
                    "status": "skipped_no_content_blocks",
                }
            )
            continue
        evidence_sources = query_result.get("evidence_sources") or {}
        message_ids: list[str] = []
        for source in evidence_sources.get("sources", ()) if isinstance(evidence_sources, Mapping) else ():
            if isinstance(source, Mapping):
                for message_id in source.get("message_ids", ()):
                    if isinstance(message_id, str) and message_id not in message_ids:
                        message_ids.append(message_id)
        excerpts: dict[str, str] = {}
        try:
            for message_id in message_ids[:20]:
                # 使用原 Case scope 读取证据，不能用空正文掩盖读取失败。
                envelope = application.invoke_tool(
                    "get_message_context",
                    GetMessageContextInput(message_id=message_id, context_before=0, context_after=0),
                    case.data_access_scope,
                )
                if envelope.error is not None:
                    raise EvaluationContractError(
                        f"judge evidence {message_id}: {envelope.error.code}: {envelope.error.message}"
                    )
                if envelope.data is None:
                    raise EvaluationContractError(f"judge evidence {message_id}: tool returned no data")
                messages = getattr(envelope.data, "messages", ())
                if not messages:
                    raise EvaluationContractError(f"judge evidence {message_id}: source message unavailable")
                # 日期关系属于 grounded claim 检查；正文 alone 不足以验证“同一天”。
                excerpts[message_id] = canonical_message_excerpt(
                    timestamp_ms=messages[0].timestamp, content=messages[0].normalized_content,
                )
            judgment = asyncio.run(
                judge.judge(
                    run_id=run_id,
                    case_id=case_id,
                    variant_id=variant_id,
                    content_blocks=content_blocks,
                    citation_bindings=citation_bindings,
                    evidence_excerpts=excerpts,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 单条判定失败显式记录，批次继续
            judgments.append(
                {
                    "run_id": run_id,
                    "case_id": case_id,
                    "variant_id": variant_id,
                    "status": "judge_failed",
                    "exception": type(exc).__name__,
                    "error": str(exc),
                }
            )
            print(
                json.dumps(
                    {
                        "status": "judge_failed",
                        "run_id": run_id,
                        "exception": type(exc).__name__,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            continue
        judgments.append(judgment.to_dict())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _collect_rate(name: str) -> list[float]:
        values: list[float] = []
        for item in judgments:
            if not isinstance(item, dict):
                continue
            value = item.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        return values

    grounded = _collect_rate("grounded_claim_rate")
    citation = _collect_rate("citation_correctness")
    judged_count = sum(1 for item in judgments if isinstance(item, dict) and "grounded_claim_rate" in item)
    skipped_count = sum(
        1 for item in judgments if isinstance(item, dict) and item.get("status") == "skipped_no_content_blocks"
    )
    # 批次完成与判定成功分开：存在失败时 CLI 必须可观察到非成功状态。
    failed_count = sum(item.get("status") == "judge_failed" for item in judgments)
    return {
        "status": "partial" if failed_count else "completed",
        "failed": failed_count,
        "judged": judged_count,
        "skipped": skipped_count,
        "grounded_claim_rate_macro": sum(grounded) / len(grounded) if grounded else None,
        "citation_correctness_macro": sum(citation) / len(citation) if citation else None,
        "output": str(output_path),
    }


def _count_by(records: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(key)
        if isinstance(value, str):
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _count_by_case(records: list[dict[str, object]], key: str, case_key: str) -> dict[str, int]:
    counts: dict[str, set[str]] = {}
    for record in records:
        split = record.get(key)
        case_id = record.get(case_key)
        if isinstance(split, str) and isinstance(case_id, str):
            counts.setdefault(split, set()).add(case_id)
    return {name: len(case_ids) for name, case_ids in sorted(counts.items())}
