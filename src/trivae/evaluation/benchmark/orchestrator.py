"""Benchmark 编排：pre-run gate → suite×variant 执行 → GT 评分 → failure artifact → 报告。

编排器只消费现有 Application facade（``evaluate_suite`` / ``generate_retrieval_annotation_packet``
/ ``materialize_evaluation_snapshot`` / ``semantic_index_status``），不创建 Runtime/Tool 实例。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from trivae.bootstrap.application import TrivaeApplication
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
        """通过现有 Application.evaluate_suite 执行一个 variant × suite。"""

        return await self._application.evaluate_suite(suite, cases, variant, repetitions=repetitions)

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


def load_cases_dir(cases_dir: Path) -> dict[str, EvaluationCaseBundle]:
    """读取 benchmark case 目录；非法 JSON / 重复 case_id 由 contract 拒绝。"""

    if not cases_dir.is_dir():
        raise EvaluationContractError(f"benchmark cases dir is not a directory: {cases_dir}")
    cases: dict[str, EvaluationCaseBundle] = {}
    for path in sorted(cases_dir.glob("*.json")):
        case = EvaluationCaseBundle.from_json(path)
        if case.case_id in cases:
            raise EvaluationContractError(f"duplicate benchmark case_id: {case.case_id}")
        cases[case.case_id] = case
    if not cases:
        raise EvaluationContractError(f"benchmark cases dir contains no cases: {cases_dir}")
    return cases


def run_benchmark(
    *,
    application: TrivaeApplication,
    database_path: Path,
    manifest_path: Path,
    suite: EvaluationSuite,
    cases_dir: Path,
    variant_paths: tuple[Path, ...],
    output_dir: Path,
    repetitions: int = 1,
) -> dict[str, object]:
    """同步入口：gate → 逐 variant 执行 → 评分 → failure → 报告落盘。"""

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

    all_records: list[dict[str, object]] = []
    all_failures: list[BenchmarkFailure] = []
    for variant in variants:
        runs = asyncio.run(
            orchestrator.run_variant_suite(
                suite=suite,
                cases=cases,
                variant=variant,
                repetitions=repetitions,
            )
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
        holdout_sealed=False,
    )
    orchestrator.write_benchmark_outputs(
        output_dir=output_dir,
        report=report,
        failures=tuple(all_failures),
        raw_records=tuple(all_records),
    )
    return {"status": "completed", "report": report}


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
