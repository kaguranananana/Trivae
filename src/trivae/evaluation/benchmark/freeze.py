"""Gate 2 Freeze：锁定 development benchmark 的内容身份与变更边界。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from trivae.evaluation.contracts import (
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationSuite,
    _json_safe,
    scope_identity,
)
from trivae.evaluation.variant import ControlledVariant

from .environment import BenchmarkEnvironmentManifest
from .gt import CaseGroundTruth, build_case_ground_truth

FREEZE_SCHEMA_VERSION = "benchmark-freeze-v1"
INVALID_CASE_REPLACEMENT_REASONS = (
    "GT/Snapshot contradiction",
    "duplicate",
    "corruption",
)
FROZEN_CASE_FIELDS = (
    "query",
    "ground_truth",
    "relevant_message_ids",
    "required_context_message_ids",
    "expected_facts",
    "expected_coverage_status",
    "expected_truncated",
    "expected_zero_result",
    "category",
    "scope_identity",
    "difficulty",
)


def _read_json(path: Path, field_name: str) -> object:
    """读取冻结记录 JSON，并把文件错误转成 Evaluation contract error。"""

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationContractError(f"{field_name} cannot be read: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationContractError(f"{field_name} is not valid JSON: {path}") from exc


def _required_text(payload: Mapping[str, object], field_name: str) -> str:
    """读取 freeze JSON 的必填文本字段，让类型检查与运行时校验保持一致。"""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationContractError(f"freeze {field_name} must be a non-empty string")
    return value


def _case_difficulty(case: EvaluationCaseBundle) -> str | None:
    """读取 Case 已声明的 difficulty；当前 v1 数据未声明时保留 null，不猜测难度。"""

    for tag in case.suite_tags:
        if tag.startswith("difficulty:"):
            return tag.removeprefix("difficulty:") or None
    expectations = case.diagnostic_expectations
    if isinstance(expectations, Mapping):
        value = expectations.get("difficulty")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _truth_snapshot(truth: CaseGroundTruth) -> dict[str, object]:
    """把 GT 解析结果转为冻结用普通 JSON 值，避免重复保存 finding 正文。"""

    return {
        "case_id": truth.case_id,
        "relevant_message_ids": list(truth.relevant_message_ids),
        "required_context_message_ids": list(truth.required_context_message_ids),
        "expected_coverage_status": truth.expected_coverage_status,
        "expected_truncated": truth.expected_truncated,
        "expected_zero_result": truth.expected_zero_result,
        "expected_facts": [list(aliases) for aliases in truth.expected_facts],
        "completeness": truth.completeness,
        "recall_scope": truth.recall_scope,
        "category": truth.category,
        "benchmark_split": truth.benchmark_split,
    }


def _case_snapshot(case: EvaluationCaseBundle, truth: CaseGroundTruth) -> dict[str, object]:
    """生成 Gate 2 需要逐项比较的 Case 身份快照。"""

    return {
        "case_identity": case.identity,
        "case_id": case.case_id,
        "case_version": case.version,
        "query": case.query,
        "ground_truth": _truth_snapshot(truth),
        "relevant_message_ids": list(truth.relevant_message_ids),
        "required_context_message_ids": list(truth.required_context_message_ids),
        "expected_facts": [list(aliases) for aliases in truth.expected_facts],
        "expected_coverage_status": truth.expected_coverage_status,
        "expected_truncated": truth.expected_truncated,
        "expected_zero_result": truth.expected_zero_result,
        "category": truth.category,
        "scope_identity": scope_identity(case.data_access_scope),
        "difficulty": _case_difficulty(case),
        "dataset_snapshot_id": case.dataset_snapshot.snapshot_id,
        "suite_tags": list(case.suite_tags),
    }


def _adjudication_label(case: EvaluationCaseBundle) -> str:
    """从人工裁决记录的显式 notes 读取 Accept/Modify/Reject，不从内容推断裁决。"""

    notes = (case.provenance.notes or "").casefold()
    if "modify:" in notes:
        return "modify"
    if "reject:" in notes or "reject (" in notes:
        return "reject"
    if "accept" in notes:
        return "accept"
    raise EvaluationContractError(f"case {case.identity} has no explicit adjudication outcome")


def _assert_adjudicated(case: EvaluationCaseBundle) -> None:
    """Gate 2 要求每个 GT finding/evidence 都已完成真实人工裁决。"""

    findings = [finding for finding in case.reference_findings if finding.criterion.startswith("gt.")]
    if not findings or not all(
        finding.provenance.adjudicated
        and all(evidence.provenance.adjudicated for evidence in finding.reference_evidence)
        for finding in findings
    ):
        raise EvaluationContractError(f"case {case.identity} is not fully adjudicated")


def _ordered_case_snapshots(
    *,
    suite: EvaluationSuite,
    cases: Mapping[str, EvaluationCaseBundle],
) -> tuple[tuple[str, ...], tuple[Mapping[str, object], ...]]:
    """按 Suite 顺序生成 dev identity 与内容快照，防止文件名排序改变实验顺序。"""

    identities: list[str] = []
    snapshots: list[Mapping[str, object]] = []
    for reference in suite.case_references:
        case = cases.get(reference.case_id)
        if case is None or case.identity != reference.identity:
            raise EvaluationContractError(f"suite case cannot be resolved for freeze: {reference.identity}")
        truth = build_case_ground_truth(case)
        _assert_adjudicated(case)
        identities.append(case.identity)
        snapshots.append(_case_snapshot(case, truth))
    return tuple(identities), tuple(snapshots)


def _case_labels(cases: Sequence[EvaluationCaseBundle]) -> dict[str, int]:
    """统计 calibration + development 的人工裁决结果，作为冻结前置事实。"""

    counts = {"accept": 0, "modify": 0, "reject": 0}
    for case in cases:
        _assert_adjudicated(case)
        label = _adjudication_label(case)
        counts[label] += 1
    counts["case_count"] = len(cases)
    return counts


def _environment_identity(environment: BenchmarkEnvironmentManifest) -> dict[str, object]:
    """只复制 environment lock 的普通值，供冻结记录持久化。"""

    return {
        "benchmark": environment.benchmark,
        "canonical_snapshot_id": environment.canonical_snapshot_id,
        "lexical_index": dict(environment.lexical_index),
        "semantic_index": environment.semantic_index,
        "git_commit": environment.git_commit,
    }


@dataclass(frozen=True)
class BenchmarkFreezeRecord:
    """Gate 2 的 immutable benchmark identity；holdout 故意不在此记录中生成。"""

    benchmark: str
    split: str
    frozen_at: str
    execution_commit: str
    suite_identity: str
    ordered_dev_case_identities: tuple[str, ...]
    calibration_case_identities: tuple[str, ...]
    case_snapshots: tuple[Mapping[str, object], ...]
    variant_fingerprints: Mapping[str, str]
    environment: Mapping[str, object]
    gt_adjudication: Mapping[str, int]
    invalid_case_replacement_reasons: tuple[str, ...] = INVALID_CASE_REPLACEMENT_REASONS
    calibration_excluded: bool = True
    holdout_absent: bool = True
    identity_method: str = (
        "ordered versioned Case identities plus canonical variant configuration text; "
        "cryptographic digests are not used by this repository"
    )
    schema_version: str = FREEZE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """校验冻结记录自身，防止不完整的 identity artifact 被当成 Gate 通过。"""

        for field_name in ("benchmark", "split", "frozen_at", "execution_commit", "suite_identity", "identity_method"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise EvaluationContractError(f"freeze {field_name} must be a non-empty string")
        if self.schema_version != FREEZE_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported benchmark freeze schema_version")
        if self.split != "development":
            raise EvaluationContractError("benchmark freeze split must be development")
        if not isinstance(self.ordered_dev_case_identities, tuple) or not self.ordered_dev_case_identities:
            raise EvaluationContractError("freeze must contain ordered development Case identities")
        if len(set(self.ordered_dev_case_identities)) != len(self.ordered_dev_case_identities):
            raise EvaluationContractError("freeze development Case identities must be unique")
        if tuple(item.get("case_identity") for item in self.case_snapshots) != self.ordered_dev_case_identities:
            raise EvaluationContractError("freeze Case snapshots must follow ordered development identities")
        if len(self.calibration_case_identities) != len(set(self.calibration_case_identities)):
            raise EvaluationContractError("freeze calibration Case identities must be unique")
        if not isinstance(self.variant_fingerprints, Mapping) or not self.variant_fingerprints:
            raise EvaluationContractError("freeze must contain variant fingerprints")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.variant_fingerprints.items()):
            raise EvaluationContractError("freeze variant fingerprints must be string mappings")
        _json_safe(self.environment, "freeze.environment")
        _json_safe(self.gt_adjudication, "freeze.gt_adjudication")
        if self.invalid_case_replacement_reasons != INVALID_CASE_REPLACEMENT_REASONS:
            raise EvaluationContractError("freeze invalid case replacement reasons must keep fixed order")
        if self.calibration_excluded is not True or self.holdout_absent is not True:
            raise EvaluationContractError("freeze must exclude calibration and assert holdout absence")
        for index, snapshot in enumerate(self.case_snapshots):
            _json_safe(snapshot, f"freeze.case_snapshots[{index}]")

    def to_dict(self) -> dict[str, object]:
        """输出稳定 JSON projection；variant map 按 variant_id 排序。"""

        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "split": self.split,
            "frozen_at": self.frozen_at,
            "execution_commit": self.execution_commit,
            "suite_identity": self.suite_identity,
            "ordered_dev_case_identities": list(self.ordered_dev_case_identities),
            "calibration_case_identities": list(self.calibration_case_identities),
            "case_snapshots": [dict(item) for item in self.case_snapshots],
            "variant_fingerprints": dict(sorted(self.variant_fingerprints.items())),
            "environment": dict(self.environment),
            "gt_adjudication": dict(self.gt_adjudication),
            "invalid_case_replacement_reasons": list(self.invalid_case_replacement_reasons),
            "calibration_excluded": self.calibration_excluded,
            "holdout_absent": self.holdout_absent,
            "identity_method": self.identity_method,
        }

    @classmethod
    def from_dict(cls, value: object) -> BenchmarkFreezeRecord:
        """从 JSON object 恢复并执行完整冻结记录校验。"""

        if not isinstance(value, Mapping):
            raise EvaluationContractError("benchmark freeze must be an object")
        raw_cases = value.get("case_snapshots", ())
        raw_dev = value.get("ordered_dev_case_identities", ())
        raw_calibration = value.get("calibration_case_identities", ())
        reasons = value.get("invalid_case_replacement_reasons", ())
        if not isinstance(raw_cases, (list, tuple)) or not all(isinstance(item, Mapping) for item in raw_cases):
            raise EvaluationContractError("freeze case_snapshots must be an array of objects")
        if not isinstance(raw_dev, (list, tuple)) or not all(isinstance(item, str) for item in raw_dev):
            raise EvaluationContractError("freeze ordered_dev_case_identities must be an array of strings")
        if not isinstance(raw_calibration, (list, tuple)) or not all(isinstance(item, str) for item in raw_calibration):
            raise EvaluationContractError("freeze calibration_case_identities must be an array of strings")
        if not isinstance(reasons, (list, tuple)) or not all(isinstance(item, str) for item in reasons):
            raise EvaluationContractError("freeze invalid case replacement reasons must be an array of strings")
        raw_gt = value.get("gt_adjudication", {})
        if not isinstance(raw_gt, Mapping):
            raise EvaluationContractError("freeze gt_adjudication must be an object")
        raw_variants = value.get("variant_fingerprints", {})
        if not isinstance(raw_variants, Mapping):
            raise EvaluationContractError("freeze variant_fingerprints must be an object")
        return cls(
            schema_version=_required_text(value, "schema_version"),
            benchmark=_required_text(value, "benchmark"),
            split=_required_text(value, "split"),
            frozen_at=_required_text(value, "frozen_at"),
            execution_commit=_required_text(value, "execution_commit"),
            suite_identity=_required_text(value, "suite_identity"),
            ordered_dev_case_identities=tuple(raw_dev),
            calibration_case_identities=tuple(raw_calibration),
            case_snapshots=tuple(raw_cases),
            variant_fingerprints=dict(raw_variants),
            environment=value.get("environment", {}),
            gt_adjudication=dict(raw_gt),
            invalid_case_replacement_reasons=tuple(reasons),
            calibration_excluded=value.get("calibration_excluded", False),
            holdout_absent=value.get("holdout_absent", False),
            identity_method=_required_text(value, "identity_method"),
        )

    def to_json(self, path: Path) -> None:
        """写入 version-controlled freeze record。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def from_json(cls, path: Path) -> BenchmarkFreezeRecord:
        """读取 version-controlled freeze record。"""

        return cls.from_dict(_read_json(path, "benchmark freeze record"))


@dataclass(frozen=True)
class FreezeVerificationResult:
    """冻结校验的逐项结果，便于 gate 日志与报告复查。"""

    passed: bool
    checks: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "checks": [dict(item) for item in self.checks]}


def capture_freeze_record(
    *,
    benchmark: str,
    execution_commit: str,
    frozen_at: str,
    suite: EvaluationSuite,
    dev_cases: Mapping[str, EvaluationCaseBundle],
    calibration_cases: Mapping[str, EvaluationCaseBundle],
    variants: Sequence[ControlledVariant],
    environment: BenchmarkEnvironmentManifest,
    holdout_dir: Path = Path("data/evaluation/benchmark/holdout"),
) -> BenchmarkFreezeRecord:
    """在 Gate 2 前置条件满足时捕获冻结记录，不创建 holdout。"""

    if environment.benchmark != benchmark:
        raise EvaluationContractError("freeze benchmark does not match environment benchmark")
    if holdout_dir.exists() and any(holdout_dir.iterdir()):
        raise EvaluationContractError("holdout must be absent when creating Gate 2 freeze")
    ordered_ids, snapshots = _ordered_case_snapshots(suite=suite, cases=dev_cases)
    calibration_ids = tuple(sorted(case.identity for case in calibration_cases.values()))
    all_cases = list(dev_cases.values()) + list(calibration_cases.values())
    if len({case.identity for case in all_cases}) != len(all_cases):
        raise EvaluationContractError("calibration and development Case identities must be disjoint")
    labels = _case_labels(all_cases)
    variant_map: dict[str, str] = {}
    for variant in variants:
        if variant.variant_id in variant_map:
            raise EvaluationContractError(f"duplicate variant_id in freeze: {variant.variant_id}")
        variant_map[variant.variant_id] = variant.fingerprint
    if len(variant_map) != 5:
        raise EvaluationContractError("resume-benchmark-v1 Gate 2 freeze requires five controlled variants")
    return BenchmarkFreezeRecord(
        benchmark=benchmark,
        split="development",
        frozen_at=frozen_at,
        execution_commit=execution_commit,
        suite_identity=suite.identity,
        ordered_dev_case_identities=ordered_ids,
        calibration_case_identities=calibration_ids,
        case_snapshots=snapshots,
        variant_fingerprints=variant_map,
        environment=_environment_identity(environment),
        gt_adjudication=labels,
    )


def _check(
    checks: list[dict[str, object]],
    name: str,
    expected: object,
    actual: object,
) -> None:
    """追加一个结构化冻结检查，不把 mismatch 变成静默修正。"""

    checks.append({"name": name, "passed": expected == actual, "expected": expected, "actual": actual})


def verify_freeze_record(
    record: BenchmarkFreezeRecord,
    *,
    suite: EvaluationSuite,
    dev_cases: Mapping[str, EvaluationCaseBundle],
    calibration_cases: Mapping[str, EvaluationCaseBundle],
    variants: Sequence[ControlledVariant],
    environment: BenchmarkEnvironmentManifest,
    holdout_dir: Path = Path("data/evaluation/benchmark/holdout"),
) -> FreezeVerificationResult:
    """复核冻结内容；允许当前 Git commit 改变，但不允许 Case/GT/Variant/Index 漂移。"""

    checks: list[dict[str, object]] = []
    _check(checks, "benchmark", record.benchmark, environment.benchmark)
    _check(checks, "suite_identity", record.suite_identity, suite.identity)
    current_ids, current_snapshots = _ordered_case_snapshots(suite=suite, cases=dev_cases)
    _check(checks, "ordered_dev_case_identities", record.ordered_dev_case_identities, current_ids)
    _check(checks, "case_snapshots", record.case_snapshots, current_snapshots)
    current_calibration_ids = tuple(sorted(case.identity for case in calibration_cases.values()))
    _check(checks, "calibration_case_identities", record.calibration_case_identities, current_calibration_ids)
    current_variant_map = {variant.variant_id: variant.fingerprint for variant in variants}
    _check(
        checks,
        "variant_fingerprints",
        dict(sorted(record.variant_fingerprints.items())),
        dict(sorted(current_variant_map.items())),
    )
    current_labels = _case_labels(list(dev_cases.values()) + list(calibration_cases.values()))
    _check(checks, "gt_adjudication", dict(record.gt_adjudication), current_labels)
    _check(checks, "canonical_snapshot_id", record.environment.get("canonical_snapshot_id"), environment.canonical_snapshot_id)
    _check(checks, "lexical_index", record.environment.get("lexical_index"), dict(environment.lexical_index))
    _check(checks, "semantic_index", record.environment.get("semantic_index"), environment.semantic_index)
    holdout_absent = not holdout_dir.exists() or not any(holdout_dir.iterdir())
    _check(checks, "holdout_absent", True, holdout_absent)
    _check(
        checks,
        "invalid_case_replacement_reasons",
        INVALID_CASE_REPLACEMENT_REASONS,
        record.invalid_case_replacement_reasons,
    )
    return FreezeVerificationResult(
        passed=all(item["passed"] is True for item in checks),
        checks=tuple(checks),
    )
