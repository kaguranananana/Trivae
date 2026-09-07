"""Benchmark Gate 3 收尾契约：冻结、holdout 封存、一次性 claim 和报告合并。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from trivae.capabilities.contracts import ExecutionScope
from trivae.evaluation import ControlledVariant
from trivae.evaluation.benchmark.closure import (
    BenchmarkFinalFreezeRecord,
    begin_holdout_run,
    capture_final_freeze,
    complete_holdout_run,
    fail_holdout_run,
    merge_reports,
    read_holdout_run_claim,
    register_holdout,
    verify_final_freeze,
)
from trivae.evaluation.benchmark.environment import BenchmarkEnvironmentManifest
from trivae.evaluation.benchmark.report import build_report, write_report_outputs
from trivae.evaluation.contracts import (
    CaseProvenance,
    CaseReference,
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationSuite,
    ReferenceEvidence,
    ReferenceFinding,
    ReferenceProvenance,
    scope_identity,
)

_SNAPSHOT = DatasetSnapshot(
    snapshot_id="snapshot:closure-test",
    canonical_database_identity="sqlite-canonical:closure-test",
    schema_version="canonical-m1-v1",
    source_identity="source:closure-test",
    message_count=2,
    relevant_time_range=(100, 200),
    deterministic_fingerprint="manifest:closure-test",
    created_at="2026-09-07T00:00:00+00:00",
    manifest={"message_count": 2, "lexical_index": {"present": True, "message_count": 2}},
)
_SCOPE = ExecutionScope(allowed_session_ids=("session:closure",), max_results=10)


def _provenance(*, adjudicated: bool = True) -> ReferenceProvenance:
    """构造与 Case Snapshot/Scope 一致的可审阅 finding provenance。"""

    return ReferenceProvenance(
        source="closure-test",
        created_at="2026-09-07T00:00:00+00:00",
        method="deterministic test fixture",
        snapshot_id=_SNAPSHOT.snapshot_id,
        scope_identity=scope_identity(_SCOPE),
        adjudicated=adjudicated,
    )


def _case(case_id: str, split: str) -> EvaluationCaseBundle:
    """构造一个带真实人工裁决标记的最小 development/holdout Case。"""

    provenance = _provenance()
    evidence = ReferenceEvidence(
        evidence_id=f"evidence:{case_id}",
        relation="supports",
        source_type="message",
        locator={"internal_message_id": "m1"},
        why_relevant="closure fixture",
        provenance=provenance,
    )
    finding = ReferenceFinding(
        finding_id="relevant",
        criterion="gt.relevant",
        expected_semantics="answer",
        reference_evidence=(evidence,),
        annotation_completeness="exhaustive",
        provenance=provenance,
    )
    return EvaluationCaseBundle(
        case_id=case_id,
        version=1,
        suite_tags=("category:exact_lexical", f"benchmark:{split}"),
        dataset_snapshot=_SNAPSHOT,
        data_access_scope=_SCOPE,
        query="closure query",
        reference_findings=(finding,),
        provenance=CaseProvenance(
            source="closure-test",
            method="fixture",
            created_at="2026-09-07T00:00:00+00:00",
            notes="human adjudication: Accept",
        ),
    )


def _suite(case: EvaluationCaseBundle, suite_id: str) -> EvaluationSuite:
    return EvaluationSuite(
        suite_id=suite_id,
        version=1,
        kind="core",
        case_references=(CaseReference(case.case_id, case.version),),
        description="closure fixture suite",
        created_at="2026-09-07T00:00:00+00:00",
    )


def _variant() -> ControlledVariant:
    return ControlledVariant(
        variant_id="closure-variant",
        code_version="commit:closure",
        provider="test",
        model="closure-model",
    )


def _manifest(*, git_commit: str = "commit:closure") -> BenchmarkEnvironmentManifest:
    return BenchmarkEnvironmentManifest(
        benchmark="resume-benchmark-closure-test",
        canonical_snapshot_id=_SNAPSHOT.snapshot_id,
        lexical_index={"present": True, "message_count": 2},
        semantic_index="semantic-index:closure",
        git_commit=git_commit,
        created_at="2026-09-07T00:00:00+00:00",
    )


def _freeze(tmp_path: Path) -> tuple[BenchmarkFinalFreezeRecord, Path, EvaluationSuite, EvaluationCaseBundle, ControlledVariant]:
    dev_case = _case("dev-closure", "development")
    dev_suite = _suite(dev_case, "closure-development")
    variant = _variant()
    freeze_path = tmp_path / "benchmark-final-freeze.json"
    freeze = capture_final_freeze(
        manifest=_manifest(),
        suite=dev_suite,
        dev_cases={dev_case.case_id: dev_case},
        variants=(variant,),
        frozen_at="2026-09-07T00:00:00+00:00",
    )
    freeze.to_json(freeze_path)
    return freeze, freeze_path, dev_suite, dev_case, variant


def _write_report_dir(
    output_dir: Path,
    *,
    split: str,
    environment: BenchmarkEnvironmentManifest,
    variant: ControlledVariant,
    holdout_sealed: bool,
) -> None:
    """写入 merge_reports 需要的三个最小报告 artifact。"""

    report = build_report(
        benchmark=environment.benchmark,
        environment=environment.to_dict(),
        variants=(variant.to_dict(),),
        case_stats={},
        end_to_end_records={split: ()},
        module_retrieval=None,
        failures=(),
        holdout_sealed=holdout_sealed,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_report_outputs(report, json_path=output_dir / "report.json", markdown_path=output_dir / "report.md")
    (output_dir / "raw-records.json").write_text("[]\n", encoding="utf-8")
    (output_dir / "failures").mkdir(parents=True, exist_ok=True)
    (output_dir / "failures" / "failures.json").write_text("[]\n", encoding="utf-8")


def test_final_freeze_roundtrip_and_git_drift_is_visible(tmp_path: Path) -> None:
    """冻结可恢复，manifest 的 commit 漂移必须进入失败检查。"""

    freeze, freeze_path, suite, case, variant = _freeze(tmp_path)
    restored = BenchmarkFinalFreezeRecord.from_json(freeze_path)
    passed = verify_final_freeze(
        restored,
        manifest=_manifest(),
        suite=suite,
        dev_cases={case.case_id: case},
        variants=(variant,),
    )
    assert passed.passed is True

    drift = verify_final_freeze(
        restored,
        manifest=_manifest(git_commit="commit:drift"),
        suite=suite,
        dev_cases={case.case_id: case},
        variants=(variant,),
    )
    assert drift.passed is False
    assert any(item["name"] == "environment_identity" for item in drift.checks if item["passed"] is False)


def test_holdout_registration_and_claim_cannot_be_reused(tmp_path: Path) -> None:
    """Holdout 登记绑定 freeze，claim 创建后换输出目录也不能再次运行。"""

    freeze, freeze_path, _dev_suite, _dev_case, variant = _freeze(tmp_path)
    holdout_case = _case("holdout-closure", "holdout")
    holdout_suite = _suite(holdout_case, "closure-holdout")
    registration_path = tmp_path / "holdout-registration.json"
    registration = register_holdout(
        freeze=freeze,
        freeze_path=freeze_path,
        suite=holdout_suite,
        holdout_cases={holdout_case.case_id: holdout_case},
    )
    registration.to_json(registration_path)

    output_dir = tmp_path / "holdout-run"
    claim_path, claim = begin_holdout_run(
        freeze=freeze,
        freeze_path=freeze_path,
        registration_path=registration_path,
        output_dir=output_dir,
    )
    assert claim.status == "started"
    with pytest.raises(EvaluationContractError, match="already claimed"):
        begin_holdout_run(
            freeze=freeze,
            freeze_path=freeze_path,
            registration_path=registration_path,
            output_dir=tmp_path / "another-output",
        )

    report_path = output_dir / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("{}\n", encoding="utf-8")
    completed = complete_holdout_run(claim_path, report_path)
    assert completed.status == "completed"
    assert read_holdout_run_claim(freeze_path).report_path == str(report_path.resolve())


def test_holdout_claim_preserves_partial_outputs_and_empty_error_reason(tmp_path: Path) -> None:
    """半套输出不能覆盖，空异常也要留下可读的 failed 诊断。"""

    freeze, freeze_path, _suite, _case, _variant = _freeze(tmp_path)
    output_dir = tmp_path / "holdout-run"
    failures_path = output_dir / "failures" / "failures.json"
    failures_path.parent.mkdir(parents=True)
    failures_path.write_text("original\n", encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="failures/failures.json"):
        begin_holdout_run(
            freeze=freeze,
            freeze_path=freeze_path,
            registration_path=tmp_path / "registration.json",
            output_dir=output_dir,
        )

    failures_path.unlink()
    claim_path, _claim = begin_holdout_run(
        freeze=freeze,
        freeze_path=freeze_path,
        registration_path=tmp_path / "registration.json",
        output_dir=output_dir,
    )
    failed = fail_holdout_run(claim_path, RuntimeError())
    assert failed.status == "failed"
    assert failed.error == "RuntimeError (empty error message)"


def test_completed_holdout_claim_requires_report_in_claimed_directory(tmp_path: Path) -> None:
    """completed claim 必须绑定真实存在且位于首次 output-dir 的 report。"""

    freeze, freeze_path, _suite, _case, _variant = _freeze(tmp_path)
    output_dir = tmp_path / "holdout-run"
    claim_path, _claim = begin_holdout_run(
        freeze=freeze,
        freeze_path=freeze_path,
        registration_path=tmp_path / "registration.json",
        output_dir=output_dir,
    )
    with pytest.raises(EvaluationContractError, match="existing report.json"):
        complete_holdout_run(claim_path, output_dir / "report.json")
    report_path = tmp_path / "other" / "report.json"
    report_path.parent.mkdir()
    report_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="outside claimed output_dir"):
        complete_holdout_run(claim_path, report_path)


def test_merge_reports_keeps_split_when_identity_mismatches(tmp_path: Path) -> None:
    """同身份可以得到 full；版本不一致时保留 split 并明确标记 full unavailable。"""

    freeze, _freeze_path, _suite, _case, variant = _freeze(tmp_path)
    development_dir = tmp_path / "development"
    holdout_dir = tmp_path / "holdout"
    _write_report_dir(
        development_dir,
        split="development",
        environment=_manifest(),
        variant=variant,
        holdout_sealed=False,
    )
    _write_report_dir(
        holdout_dir,
        split="holdout",
        environment=_manifest(),
        variant=variant,
        holdout_sealed=True,
    )
    merged = merge_reports(
        development_dir=development_dir,
        holdout_dir=holdout_dir,
        freeze=freeze,
    )
    assert merged["metadata"]["full_available"] is True  # type: ignore[index]

    drifted_holdout = replace(_manifest(), git_commit="commit:other")
    _write_report_dir(
        holdout_dir,
        split="holdout",
        environment=drifted_holdout,
        variant=variant,
        holdout_sealed=True,
    )
    unavailable = merge_reports(development_dir=development_dir, holdout_dir=holdout_dir)
    assert unavailable["metadata"]["full_available"] is False  # type: ignore[index]
    assert unavailable["splits"]["full"]["status"] == "unavailable"  # type: ignore[index]


def test_unsealed_holdout_report_cannot_be_merged(tmp_path: Path) -> None:
    """没有 holdout_sealed 标记的历史/半成品报告不能进入最终合并。"""

    _freeze_record, _freeze_path, _suite, _case, variant = _freeze(tmp_path)
    _write_report_dir(
        tmp_path / "development",
        split="development",
        environment=_manifest(),
        variant=variant,
        holdout_sealed=False,
    )
    _write_report_dir(
        tmp_path / "holdout",
        split="holdout",
        environment=_manifest(),
        variant=variant,
        holdout_sealed=False,
    )
    with pytest.raises(EvaluationContractError, match="not sealed"):
        merge_reports(
            development_dir=tmp_path / "development",
            holdout_dir=tmp_path / "holdout",
        )


def test_merge_output_does_not_overwrite_existing_report(tmp_path: Path) -> None:
    """最终报告目录已有核心 artifact 时必须保留原件并拒绝覆盖。"""

    freeze, _freeze_path, _suite, _case, variant = _freeze(tmp_path)
    development_dir = tmp_path / "development"
    holdout_dir = tmp_path / "holdout"
    _write_report_dir(
        development_dir,
        split="development",
        environment=_manifest(),
        variant=variant,
        holdout_sealed=False,
    )
    _write_report_dir(
        holdout_dir,
        split="holdout",
        environment=_manifest(),
        variant=variant,
        holdout_sealed=True,
    )
    output_dir = tmp_path / "final-report"
    output_dir.mkdir()
    (output_dir / "report.json").write_text("original\n", encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="already contains report.json"):
        merge_reports(
            development_dir=development_dir,
            holdout_dir=holdout_dir,
            output_dir=output_dir,
            freeze=freeze,
        )
    assert (output_dir / "report.json").read_text(encoding="utf-8") == "original\n"
