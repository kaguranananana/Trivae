"""resume-benchmark-v1 Gate 3 收尾契约。

本模块只负责评测生命周期的边界事实：最终冻结、冻结后 holdout 登记、一次性
正式运行声明和 dev/holdout 报告合并。它复用已有的 Case、Suite、Variant、GT
解析器和 ``build_report``，不创建新的 Query 或检索执行路径。

这里的 identity 使用已有的 canonical JSON 文本和 git commit。模块不会为了
防止重复运行再引入内容摘要算法；一次性运行由冻结文件旁的固定 claim 文件
承担。
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from trivae.evaluation.contracts import (
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationSuite,
    _json_safe,
    utc_now,
)
from trivae.evaluation.variant import ControlledVariant

from .environment import BenchmarkEnvironmentManifest
from .freeze import _assert_adjudicated
from .gt import build_case_ground_truth
from .report import build_report, write_report_outputs

FINAL_FREEZE_SCHEMA_VERSION = "benchmark-final-freeze-v1"
HOLDOUT_REGISTRATION_SCHEMA_VERSION = "benchmark-holdout-registration-v1"
HOLDOUT_RUN_CLAIM_SCHEMA_VERSION = "benchmark-holdout-run-claim-v1"

RunClaimStatus = Literal["started", "completed", "failed"]


def _read_json(path: Path, field_name: str) -> object:
    """读取本地 artifact，并把文件损坏显式转换成 Evaluation contract error。"""

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationContractError(f"{field_name} cannot be read: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationContractError(f"{field_name} is not valid JSON: {path}") from exc


def _required_text(value: object, field_name: str) -> str:
    """读取生命周期记录中的必填文本，不把缺失字段悄悄转成字符串。"""

    if not isinstance(value, str) or not value.strip():
        raise EvaluationContractError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str | None:
    """读取可选诊断文本；错误信息为空时仍保持缺失语义。"""

    if value is None:
        return None
    return _required_text(value, field_name)


def _canonical_json(value: object, field_name: str) -> str:
    """用稳定 JSON 文本比较完整配置，避免依赖新的 hash identity。"""

    _json_safe(value, field_name)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _environment_dict(
    environment: BenchmarkEnvironmentManifest | Mapping[str, object],
) -> dict[str, object]:
    """复制 Environment manifest 的完整 JSON projection。"""

    if isinstance(environment, BenchmarkEnvironmentManifest):
        value = environment.to_dict()
    elif isinstance(environment, Mapping):
        value = dict(environment)
    else:
        raise EvaluationContractError("benchmark environment must be a manifest or object")
    _json_safe(value, "benchmark environment")
    for field_name in ("benchmark", "canonical_snapshot_id", "lexical_index", "semantic_index", "git_commit"):
        if field_name not in value:
            raise EvaluationContractError(f"benchmark environment requires {field_name}")
    _required_text(value.get("benchmark"), "benchmark environment benchmark")
    _required_text(value.get("canonical_snapshot_id"), "benchmark environment canonical_snapshot_id")
    _required_text(value.get("semantic_index"), "benchmark environment semantic_index")
    _required_text(value.get("git_commit"), "benchmark environment git_commit")
    if not isinstance(value.get("lexical_index"), Mapping):
        raise EvaluationContractError("benchmark environment lexical_index must be an object")
    return value


def environment_identity(environment: Mapping[str, object]) -> dict[str, object]:
    """返回报告合并所需的 Environment identity 字段。"""

    value = _environment_dict(environment)
    lexical_index = value["lexical_index"]
    if not isinstance(lexical_index, Mapping):
        # _environment_dict 已验证此字段；这里保持类型收窄，避免把 object 当作配置映射。
        raise EvaluationContractError("benchmark environment lexical_index must be an object")
    return {
        "benchmark": value["benchmark"],
        "canonical_snapshot_id": value["canonical_snapshot_id"],
        "lexical_index": dict(lexical_index),
        "semantic_index": value["semantic_index"],
        "git_commit": value["git_commit"],
    }


def _ordered_cases(
    suite: EvaluationSuite,
    cases: Mapping[str, EvaluationCaseBundle],
) -> tuple[EvaluationCaseBundle, ...]:
    """严格按 Suite 顺序解析 Case，保证冻结与运行顺序一致。"""

    ordered: list[EvaluationCaseBundle] = []
    for reference in suite.case_references:
        case = cases.get(reference.identity) or cases.get(reference.case_id)
        if case is None or case.identity != reference.identity:
            raise EvaluationContractError(f"suite case cannot be resolved for closure: {reference.identity}")
        ordered.append(case)
    return tuple(ordered)


def _case_configurations(
    suite: EvaluationSuite,
    cases: Mapping[str, EvaluationCaseBundle],
) -> tuple[tuple[str, ...], dict[str, Mapping[str, object]]]:
    """生成完整 Case 配置的 identity 映射；不只保存 query 或 finding 摘要。"""

    ordered = _ordered_cases(suite, cases)
    identities = tuple(case.identity for case in ordered)
    configurations: dict[str, Mapping[str, object]] = {
        case.identity: case.to_dict() for case in ordered
    }
    return identities, configurations


def _variant_configurations(variants: Sequence[ControlledVariant]) -> dict[str, str]:
    """读取每个 Variant 的完整 canonical configuration text。"""

    configurations: dict[str, str] = {}
    for variant in variants:
        if not isinstance(variant, ControlledVariant):
            raise EvaluationContractError("closure variants must contain ControlledVariant values")
        if variant.variant_id in configurations:
            raise EvaluationContractError(f"duplicate variant_id in closure: {variant.variant_id}")
        configurations[variant.variant_id] = variant.fingerprint
    if not configurations:
        raise EvaluationContractError("closure requires at least one controlled variant")
    return dict(sorted(configurations.items()))


def _require_five_variants(benchmark: str, variant_configurations: Mapping[str, str]) -> None:
    """resume-benchmark-v1 的最终身份必须包含 A/B/C/C2/D 五个 Variant。"""

    if benchmark == "resume-benchmark-v1" and len(variant_configurations) != 5:
        raise EvaluationContractError("resume-benchmark-v1 final freeze requires five controlled variants")


def _validate_case_snapshot(
    case: EvaluationCaseBundle,
    *,
    expected_split: str,
    expected_snapshot_id: str,
) -> None:
    """校验 Case 的实际 GT、Snapshot 和 split；调用已有 adjudication contract。"""

    _assert_adjudicated(case)
    truth = build_case_ground_truth(case)
    if truth.benchmark_split != expected_split:
        raise EvaluationContractError(
            f"case {case.identity} benchmark split is {truth.benchmark_split!r}, expected {expected_split!r}"
        )
    if case.dataset_snapshot.snapshot_id != expected_snapshot_id:
        raise EvaluationContractError(f"case {case.identity} Snapshot does not match final environment")


def _check(checks: list[dict[str, object]], name: str, expected: object, actual: object) -> None:
    """记录可读的 closure identity 检查，不把 mismatch 静默修正。"""

    checks.append({"name": name, "passed": expected == actual, "expected": expected, "actual": actual})


@dataclass(frozen=True)
class ClosureVerificationResult:
    """冻结或 holdout 登记的逐项检查结果。"""

    passed: bool
    checks: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "checks": [dict(item) for item in self.checks]}


@dataclass(frozen=True)
class BenchmarkFinalFreezeRecord:
    """Gate 3 的最终冻结记录；只描述 dev 与运行环境，不创建 holdout。"""

    benchmark: str
    frozen_at: str
    execution_commit: str
    development_suite_identity: str
    ordered_dev_case_identities: tuple[str, ...]
    development_case_configurations: Mapping[str, Mapping[str, object]]
    variant_configurations: Mapping[str, str]
    environment: Mapping[str, object]
    gate2_freeze_path: str | None = None
    schema_version: str = FINAL_FREEZE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """校验冻结记录所有 identity 字段，防止不完整 artifact 被当成 Gate 通过。"""

        for field_name in (
            "benchmark",
            "frozen_at",
            "execution_commit",
            "development_suite_identity",
        ):
            _required_text(getattr(self, field_name), f"final freeze {field_name}")
        if self.schema_version != FINAL_FREEZE_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported benchmark final freeze schema_version")
        if not isinstance(self.ordered_dev_case_identities, tuple) or not self.ordered_dev_case_identities:
            raise EvaluationContractError("final freeze requires ordered development Case identities")
        if len(set(self.ordered_dev_case_identities)) != len(self.ordered_dev_case_identities):
            raise EvaluationContractError("final freeze development Case identities must be unique")
        if not isinstance(self.development_case_configurations, Mapping):
            raise EvaluationContractError("final freeze Case configurations must be an object")
        if set(self.development_case_configurations) != set(self.ordered_dev_case_identities):
            raise EvaluationContractError("final freeze Case configurations do not match ordered identities")
        if not isinstance(self.variant_configurations, Mapping) or not self.variant_configurations:
            raise EvaluationContractError("final freeze requires variant configurations")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.variant_configurations.items()):
            raise EvaluationContractError("final freeze variant configurations must be string mappings")
        environment = _environment_dict(self.environment)
        if environment["benchmark"] != self.benchmark:
            raise EvaluationContractError("final freeze benchmark does not match environment")
        if environment["git_commit"] != self.execution_commit:
            raise EvaluationContractError("final freeze execution_commit does not match environment git_commit")
        _require_five_variants(self.benchmark, self.variant_configurations)
        for identity, configuration in self.development_case_configurations.items():
            _canonical_json(configuration, f"final freeze case configuration {identity}")
        if self.gate2_freeze_path is not None:
            _required_text(self.gate2_freeze_path, "final freeze gate2_freeze_path")

    def to_dict(self) -> dict[str, object]:
        """输出可审阅的完整配置；variant text 保持 canonical 顺序。"""

        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "frozen_at": self.frozen_at,
            "execution_commit": self.execution_commit,
            "development_suite_identity": self.development_suite_identity,
            "ordered_dev_case_identities": list(self.ordered_dev_case_identities),
            "development_case_configurations": {
                key: dict(value) for key, value in sorted(self.development_case_configurations.items())
            },
            "variant_configurations": dict(sorted(self.variant_configurations.items())),
            "environment": dict(self.environment),
            "gate2_freeze_path": self.gate2_freeze_path,
        }

    @classmethod
    def from_dict(cls, value: object) -> BenchmarkFinalFreezeRecord:
        """从 JSON 恢复并重新执行 final freeze contract。"""

        if not isinstance(value, Mapping):
            raise EvaluationContractError("benchmark final freeze must be an object")
        raw_ids = value.get("ordered_dev_case_identities", ())
        if not isinstance(raw_ids, (list, tuple)) or not all(isinstance(item, str) for item in raw_ids):
            raise EvaluationContractError("final freeze ordered_dev_case_identities must be an array of strings")
        raw_cases = value.get("development_case_configurations", {})
        if not isinstance(raw_cases, Mapping) or not all(isinstance(item, Mapping) for item in raw_cases.values()):
            raise EvaluationContractError("final freeze development_case_configurations must be an object")
        raw_variants = value.get("variant_configurations", {})
        if not isinstance(raw_variants, Mapping):
            raise EvaluationContractError("final freeze variant_configurations must be an object")
        return cls(
            schema_version=_required_text(value.get("schema_version"), "final freeze schema_version"),
            benchmark=_required_text(value.get("benchmark"), "final freeze benchmark"),
            frozen_at=_required_text(value.get("frozen_at"), "final freeze frozen_at"),
            execution_commit=_required_text(value.get("execution_commit"), "final freeze execution_commit"),
            development_suite_identity=_required_text(
                value.get("development_suite_identity"), "final freeze development_suite_identity"
            ),
            ordered_dev_case_identities=tuple(raw_ids),
            development_case_configurations={str(key): dict(item) for key, item in raw_cases.items()},
            variant_configurations={str(key): value for key, value in raw_variants.items()},
            environment=value.get("environment", {}),
            gate2_freeze_path=value.get("gate2_freeze_path"),
        )

    def to_json(self, path: Path) -> None:
        """写入 Gate 3 final freeze artifact。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> BenchmarkFinalFreezeRecord:
        """读取 Gate 3 final freeze artifact。"""

        return cls.from_dict(_read_json(path, "benchmark final freeze"))


def capture_final_freeze(
    *,
    manifest: BenchmarkEnvironmentManifest,
    suite: EvaluationSuite,
    dev_cases: Mapping[str, EvaluationCaseBundle],
    variants: Sequence[ControlledVariant],
    frozen_at: str | None = None,
    gate2_freeze_path: Path | None = None,
) -> BenchmarkFinalFreezeRecord:
    """从最终 Development artifact 捕获 Gate 3 identity，不读取或创建 holdout。"""

    environment = _environment_dict(manifest)
    benchmark = manifest.benchmark
    identities, configurations = _case_configurations(suite, dev_cases)
    for case in _ordered_cases(suite, dev_cases):
        _validate_case_snapshot(
            case,
            expected_split="development",
            expected_snapshot_id=manifest.canonical_snapshot_id,
        )
    variant_map = _variant_configurations(variants)
    _require_five_variants(benchmark, variant_map)
    return BenchmarkFinalFreezeRecord(
        benchmark=benchmark,
        frozen_at=frozen_at or utc_now(),
        execution_commit=manifest.git_commit,
        development_suite_identity=suite.identity,
        ordered_dev_case_identities=identities,
        development_case_configurations=configurations,
        variant_configurations=variant_map,
        environment=environment,
        gate2_freeze_path=None if gate2_freeze_path is None else str(gate2_freeze_path.resolve()),
    )


capture_final_freeze_record = capture_final_freeze


def verify_final_freeze(
    record: BenchmarkFinalFreezeRecord,
    *,
    manifest: BenchmarkEnvironmentManifest,
    suite: EvaluationSuite,
    dev_cases: Mapping[str, EvaluationCaseBundle],
    variants: Sequence[ControlledVariant],
) -> ClosureVerificationResult:
    """逐项复核当前 dev artifact 是否仍与 Gate 3 freeze 完全一致。"""

    checks: list[dict[str, object]] = []
    current_environment = _environment_dict(manifest)
    _check(checks, "benchmark", record.benchmark, manifest.benchmark)
    _check(checks, "environment_identity", environment_identity(record.environment), environment_identity(current_environment))
    _check(checks, "development_suite_identity", record.development_suite_identity, suite.identity)
    current_ids, current_configurations = _case_configurations(suite, dev_cases)
    _check(checks, "ordered_dev_case_identities", record.ordered_dev_case_identities, current_ids)
    _check(
        checks,
        "development_case_configurations",
        _canonical_json(record.development_case_configurations, "record development cases"),
        _canonical_json(current_configurations, "current development cases"),
    )
    current_variants = _variant_configurations(variants)
    _check(checks, "variant_configurations", dict(record.variant_configurations), current_variants)
    return ClosureVerificationResult(
        passed=all(item["passed"] is True for item in checks),
        checks=tuple(checks),
    )


verify_final_freeze_record = verify_final_freeze


def _freeze_identity(record: BenchmarkFinalFreezeRecord, freeze_path: Path) -> dict[str, object]:
    """生成 holdout registration 绑定的完整冻结 identity。"""

    return {
        "benchmark": record.benchmark,
        "frozen_at": record.frozen_at,
        "execution_commit": record.execution_commit,
        "development_suite_identity": record.development_suite_identity,
        "ordered_dev_case_identities": list(record.ordered_dev_case_identities),
        "variant_configurations": dict(sorted(record.variant_configurations.items())),
        "environment": dict(record.environment),
        "freeze_path": str(freeze_path.resolve()),
    }


@dataclass(frozen=True)
class HoldoutRegistrationRecord:
    """冻结后一次登记的 holdout identity 与完整 Case 配置。"""

    benchmark: str
    registered_at: str
    freeze_path: str
    freeze_identity: Mapping[str, object]
    holdout_suite_identity: str
    ordered_holdout_case_identities: tuple[str, ...]
    case_configurations: Mapping[str, Mapping[str, object]]
    adjudication: Mapping[str, Mapping[str, object]]
    schema_version: str = HOLDOUT_REGISTRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """校验登记数据本身；Case 的语义校验在 register/verify 阶段完成。"""

        for name in ("benchmark", "registered_at", "freeze_path", "holdout_suite_identity"):
            _required_text(getattr(self, name), f"holdout registration {name}")
        if self.schema_version != HOLDOUT_REGISTRATION_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported holdout registration schema_version")
        if not isinstance(self.ordered_holdout_case_identities, tuple) or not self.ordered_holdout_case_identities:
            raise EvaluationContractError("holdout registration requires Case identities")
        if len(set(self.ordered_holdout_case_identities)) != len(self.ordered_holdout_case_identities):
            raise EvaluationContractError("holdout registration Case identities must be unique")
        if set(self.case_configurations) != set(self.ordered_holdout_case_identities):
            raise EvaluationContractError("holdout registration Case configurations do not match identities")
        if set(self.adjudication) != set(self.ordered_holdout_case_identities):
            raise EvaluationContractError("holdout registration adjudication does not match identities")
        _json_safe(self.freeze_identity, "holdout registration freeze_identity")
        for identity, configuration in self.case_configurations.items():
            _canonical_json(configuration, f"holdout registration case configuration {identity}")
        for identity, status in self.adjudication.items():
            if status.get("adjudicated") is not True:
                raise EvaluationContractError(f"holdout Case {identity} is not marked adjudicated")

    def to_dict(self) -> dict[str, object]:
        """输出 holdout 完整配置和人工裁决状态，供漂移检查与人工审阅。"""

        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "registered_at": self.registered_at,
            "freeze_path": self.freeze_path,
            "freeze_identity": dict(self.freeze_identity),
            "holdout_suite_identity": self.holdout_suite_identity,
            "ordered_holdout_case_identities": list(self.ordered_holdout_case_identities),
            "case_configurations": {key: dict(value) for key, value in sorted(self.case_configurations.items())},
            "adjudication": {key: dict(value) for key, value in sorted(self.adjudication.items())},
        }

    @classmethod
    def from_dict(cls, value: object) -> HoldoutRegistrationRecord:
        """从 JSON 恢复并执行登记记录结构校验。"""

        if not isinstance(value, Mapping):
            raise EvaluationContractError("holdout registration must be an object")
        raw_ids = value.get("ordered_holdout_case_identities", ())
        if not isinstance(raw_ids, (list, tuple)) or not all(isinstance(item, str) for item in raw_ids):
            raise EvaluationContractError("holdout registration identities must be an array of strings")
        raw_cases = value.get("case_configurations", {})
        raw_adjudication = value.get("adjudication", {})
        if not isinstance(raw_cases, Mapping) or not all(isinstance(item, Mapping) for item in raw_cases.values()):
            raise EvaluationContractError("holdout registration case_configurations must be an object")
        if not isinstance(raw_adjudication, Mapping) or not all(
            isinstance(item, Mapping) for item in raw_adjudication.values()
        ):
            raise EvaluationContractError("holdout registration adjudication must be an object")
        return cls(
            schema_version=_required_text(value.get("schema_version"), "holdout registration schema_version"),
            benchmark=_required_text(value.get("benchmark"), "holdout registration benchmark"),
            registered_at=_required_text(value.get("registered_at"), "holdout registration registered_at"),
            freeze_path=_required_text(value.get("freeze_path"), "holdout registration freeze_path"),
            freeze_identity=value.get("freeze_identity", {}),
            holdout_suite_identity=_required_text(
                value.get("holdout_suite_identity"), "holdout registration holdout_suite_identity"
            ),
            ordered_holdout_case_identities=tuple(raw_ids),
            case_configurations={str(key): dict(item) for key, item in raw_cases.items()},
            adjudication={str(key): dict(item) for key, item in raw_adjudication.items()},
        )

    def to_json(self, path: Path) -> None:
        """写入 local-only holdout registration。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> HoldoutRegistrationRecord:
        """读取 local-only holdout registration。"""

        return cls.from_dict(_read_json(path, "holdout registration"))


def register_holdout(
    *,
    freeze: BenchmarkFinalFreezeRecord,
    freeze_path: Path,
    suite: EvaluationSuite,
    holdout_cases: Mapping[str, EvaluationCaseBundle],
    registered_at: str | None = None,
) -> HoldoutRegistrationRecord:
    """在 Gate 3 freeze 之后登记 holdout，并保存每个 Case 的完整配置。"""

    freeze_file = freeze_path.resolve()
    environment = _environment_dict(freeze.environment)
    ordered = _ordered_cases(suite, holdout_cases)
    dev_ids = set(freeze.ordered_dev_case_identities)
    dev_case_ids = {
        str(configuration.get("case_id"))
        for configuration in freeze.development_case_configurations.values()
        if isinstance(configuration.get("case_id"), str)
    }
    identities: list[str] = []
    configurations: dict[str, Mapping[str, object]] = {}
    adjudication: dict[str, Mapping[str, object]] = {}
    for case in ordered:
        _validate_case_snapshot(
            case,
            expected_split="holdout",
            expected_snapshot_id=str(environment["canonical_snapshot_id"]),
        )
        if case.identity in dev_ids or case.case_id in dev_case_ids:
            raise EvaluationContractError(f"holdout Case overlaps Development: {case.identity}")
        if case.identity in configurations:
            raise EvaluationContractError(f"duplicate holdout Case identity: {case.identity}")
        identities.append(case.identity)
        configurations[case.identity] = case.to_dict()
        adjudication[case.identity] = {
            "adjudicated": True,
            "finding_count": sum(1 for finding in case.reference_findings if finding.criterion.startswith("gt.")),
        }
    if not identities:
        raise EvaluationContractError("holdout registration requires at least one Case")
    return HoldoutRegistrationRecord(
        benchmark=freeze.benchmark,
        registered_at=registered_at or utc_now(),
        freeze_path=str(freeze_file),
        freeze_identity=_freeze_identity(freeze, freeze_file),
        holdout_suite_identity=suite.identity,
        ordered_holdout_case_identities=tuple(identities),
        case_configurations=configurations,
        adjudication=adjudication,
    )


register_holdout_cases = register_holdout


def verify_holdout_registration(
    registration: HoldoutRegistrationRecord,
    *,
    freeze: BenchmarkFinalFreezeRecord,
    freeze_path: Path,
    suite: EvaluationSuite,
    holdout_cases: Mapping[str, EvaluationCaseBundle],
) -> ClosureVerificationResult:
    """校验登记后的 holdout 是否仍为同一冻结、Suite、Case 配置和人工 GT。"""

    checks: list[dict[str, object]] = []
    current_freeze_identity = _freeze_identity(freeze, freeze_path)
    _check(checks, "benchmark", registration.benchmark, freeze.benchmark)
    _check(checks, "freeze_path", registration.freeze_path, str(freeze_path.resolve()))
    _check(
        checks,
        "freeze_identity",
        _canonical_json(registration.freeze_identity, "registered freeze identity"),
        _canonical_json(current_freeze_identity, "current freeze identity"),
    )
    _check(checks, "holdout_suite_identity", registration.holdout_suite_identity, suite.identity)
    current_ids, current_configurations = _case_configurations(suite, holdout_cases)
    _check(checks, "ordered_holdout_case_identities", registration.ordered_holdout_case_identities, current_ids)
    _check(
        checks,
        "case_configurations",
        _canonical_json(registration.case_configurations, "registered holdout cases"),
        _canonical_json(current_configurations, "current holdout cases"),
    )
    current_adjudication: dict[str, Mapping[str, object]] = {}
    expected_snapshot = str(freeze.environment["canonical_snapshot_id"])
    for case in _ordered_cases(suite, holdout_cases):
        _validate_case_snapshot(case, expected_split="holdout", expected_snapshot_id=expected_snapshot)
        current_adjudication[case.identity] = {
            "adjudicated": True,
            "finding_count": sum(1 for finding in case.reference_findings if finding.criterion.startswith("gt.")),
        }
    _check(
        checks,
        "adjudication",
        _canonical_json(registration.adjudication, "registered adjudication"),
        _canonical_json(current_adjudication, "current adjudication"),
    )
    return ClosureVerificationResult(
        passed=all(item["passed"] is True for item in checks),
        checks=tuple(checks),
    )


verify_holdout_registration_record = verify_holdout_registration


def assert_holdout_registration(
    registration: HoldoutRegistrationRecord,
    *,
    freeze: BenchmarkFinalFreezeRecord,
    freeze_path: Path,
    suite: EvaluationSuite,
    holdout_cases: Mapping[str, EvaluationCaseBundle],
) -> None:
    """把 registration mismatch 转成显式 contract error，供 provider 前调用。"""

    result = verify_holdout_registration(
        registration,
        freeze=freeze,
        freeze_path=freeze_path,
        suite=suite,
        holdout_cases=holdout_cases,
    )
    if not result.passed:
        mismatches = [str(item["name"]) for item in result.checks if item.get("passed") is not True]
        raise EvaluationContractError(f"holdout registration drift: {', '.join(mismatches)}")


def assert_finalized_run_inputs(
    *,
    freeze: BenchmarkFinalFreezeRecord,
    manifest: BenchmarkEnvironmentManifest,
    suite: EvaluationSuite,
    cases: Mapping[str, EvaluationCaseBundle],
    variants: Sequence[ControlledVariant],
    split: str,
    registration: HoldoutRegistrationRecord | None = None,
    freeze_path: Path | None = None,
) -> None:
    """在第一次 provider 请求前拒绝 Environment、Case、Variant 或 split 漂移。"""

    if split == "holdout":
        if registration is None or freeze_path is None:
            raise EvaluationContractError("holdout run requires final freeze and holdout registration")
        # Holdout 复核既要确认登记文件没有漂移，也要确认当前 live 环境和 Variant
        # 仍是冻结时的身份；否则不能在 provider 请求前声称这是同一轮测量。
        if environment_identity(freeze.environment) != environment_identity(manifest.to_dict()):
            raise EvaluationContractError("holdout run environment differs from final freeze")
        current_variants = _variant_configurations(variants)
        if dict(freeze.variant_configurations) != current_variants:
            raise EvaluationContractError("holdout run variants differ from final freeze")
        assert_holdout_registration(
            registration,
            freeze=freeze,
            freeze_path=freeze_path,
            suite=suite,
            holdout_cases=cases,
        )
        return
    if split != "development":
        raise EvaluationContractError(f"unsupported finalized benchmark split: {split}")
    result = verify_final_freeze(
        freeze,
        manifest=manifest,
        suite=suite,
        dev_cases=cases,
        variants=variants,
    )
    if not result.passed:
        mismatches = [str(item["name"]) for item in result.checks if item.get("passed") is not True]
        raise EvaluationContractError(f"final freeze drift: {', '.join(mismatches)}")


@dataclass(frozen=True)
class HoldoutRunClaim:
    """冻结旁的不可重用正式 holdout 运行声明。"""

    benchmark: str
    freeze_path: str
    registration_path: str
    output_dir: str
    status: RunClaimStatus
    started_at: str
    finished_at: str | None = None
    report_path: str | None = None
    error_type: str | None = None
    error: str | None = None
    schema_version: str = HOLDOUT_RUN_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """校验 claim 状态机允许的字段组合。"""

        for name in ("benchmark", "freeze_path", "registration_path", "output_dir", "started_at"):
            _required_text(getattr(self, name), f"holdout run claim {name}")
        if self.schema_version != HOLDOUT_RUN_CLAIM_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported holdout run claim schema_version")
        if self.status not in ("started", "completed", "failed"):
            raise EvaluationContractError("holdout run claim status is invalid")
        for name in ("finished_at", "report_path", "error_type", "error"):
            _optional_text(getattr(self, name), f"holdout run claim {name}")
        if self.status == "started" and any(
            getattr(self, name) is not None for name in ("finished_at", "report_path", "error_type", "error")
        ):
            raise EvaluationContractError("started holdout run claim cannot contain completion fields")
        if self.status in ("completed", "failed") and self.finished_at is None:
            raise EvaluationContractError(f"{self.status} holdout run claim requires finished_at")
        if self.status == "completed":
            if self.report_path is None:
                raise EvaluationContractError("completed holdout run claim requires report_path")
            if self.error_type is not None or self.error is not None:
                raise EvaluationContractError("completed holdout run claim cannot contain failure fields")
        if self.status == "failed":
            if self.error_type is None:
                raise EvaluationContractError("failed holdout run claim requires error_type")
            if self.report_path is not None:
                raise EvaluationContractError("failed holdout run claim cannot contain report_path")

    def to_dict(self) -> dict[str, object]:
        """输出 claim 状态，保留 started/failed 事实供人工复查。"""

        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "freeze_path": self.freeze_path,
            "registration_path": self.registration_path,
            "output_dir": self.output_dir,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_path": self.report_path,
            "error_type": self.error_type,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: object) -> HoldoutRunClaim:
        """读取 claim 并执行状态契约。"""

        if not isinstance(value, Mapping):
            raise EvaluationContractError("holdout run claim must be an object")
        status = value.get("status")
        if status not in ("started", "completed", "failed"):
            raise EvaluationContractError("holdout run claim status is invalid")
        return cls(
            schema_version=_required_text(value.get("schema_version"), "holdout run claim schema_version"),
            benchmark=_required_text(value.get("benchmark"), "holdout run claim benchmark"),
            freeze_path=_required_text(value.get("freeze_path"), "holdout run claim freeze_path"),
            registration_path=_required_text(value.get("registration_path"), "holdout run claim registration_path"),
            output_dir=_required_text(value.get("output_dir"), "holdout run claim output_dir"),
            status=status,
            started_at=_required_text(value.get("started_at"), "holdout run claim started_at"),
            finished_at=value.get("finished_at"),
            report_path=value.get("report_path"),
            error_type=value.get("error_type"),
            error=value.get("error"),
        )

    def to_json(self, path: Path) -> None:
        """写入 claim；仅供内部状态迁移使用。"""

        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> HoldoutRunClaim:
        """读取现有 claim；损坏时拒绝继续执行。"""

        return cls.from_dict(_read_json(path, "holdout run claim"))


def holdout_run_claim_path(freeze_path: Path) -> Path:
    """返回由 freeze identity 唯一决定的 claim 路径，忽略 output-dir。"""

    resolved = freeze_path.resolve()
    return resolved.with_name(f"{resolved.stem}-holdout-run.json")


def read_holdout_run_claim(freeze_path: Path) -> HoldoutRunClaim:
    """读取冻结旁已有 claim；不存在也显式报错。"""

    path = holdout_run_claim_path(freeze_path)
    if not path.exists():
        raise EvaluationContractError(f"holdout run claim does not exist: {path}")
    return HoldoutRunClaim.from_json(path)


def begin_holdout_run(
    *,
    freeze: BenchmarkFinalFreezeRecord,
    freeze_path: Path,
    registration_path: Path,
    output_dir: Path,
) -> tuple[Path, HoldoutRunClaim]:
    """在任何 provider 请求前原子地登记第一次 holdout run。"""

    # 已有结果即使没有 claim 也不能被新一轮静默覆盖；先检查结果文件再创建 claim。
    for artifact_name in (
        "report.json",
        "report.md",
        "raw-records.json",
        str(Path("failures") / "failures.json"),
    ):
        if (output_dir / artifact_name).exists():
            raise EvaluationContractError(f"holdout output already contains {artifact_name}: {output_dir}")
    claim_path = holdout_run_claim_path(freeze_path)
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim = HoldoutRunClaim(
        benchmark=freeze.benchmark,
        freeze_path=str(freeze_path.resolve()),
        registration_path=str(registration_path.resolve()),
        output_dir=str(output_dir.resolve()),
        status="started",
        started_at=utc_now(),
    )
    try:
        # exclusive create 保证换 output-dir 或并发调用都不能覆盖第一次声明。
        with claim_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(claim.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    except FileExistsError as exc:
        existing = HoldoutRunClaim.from_json(claim_path)
        raise EvaluationContractError(
            f"holdout run already claimed: {claim_path} (status={existing.status})"
        ) from exc
    return claim_path, claim


def _update_run_claim(
    claim_path: Path,
    *,
    status: RunClaimStatus,
    report_path: Path | None = None,
    error: BaseException | None = None,
) -> HoldoutRunClaim:
    """完成 started claim 的唯一状态迁移；中断不会调用本函数。"""

    current = HoldoutRunClaim.from_json(claim_path)
    if current.status != "started":
        raise EvaluationContractError(f"holdout run claim is already terminal: {current.status}")
    if status == "completed":
        if report_path is None or not report_path.is_file():
            raise EvaluationContractError("completed holdout run requires an existing report.json")
        if report_path.resolve().parent != Path(current.output_dir):
            raise EvaluationContractError("completed holdout report is outside claimed output_dir")
    error_text = None
    if error is not None:
        # 某些异常的 str 为空；保留异常类型作为非空诊断，而不是让 failed 状态丢失。
        error_text = str(error).strip() or f"{type(error).__name__} (empty error message)"
    updated = replace(
        current,
        status=status,
        finished_at=utc_now(),
        report_path=None if report_path is None else str(report_path.resolve()),
        error_type=None if error is None else type(error).__name__,
        error=error_text,
    )
    updated.to_json(claim_path)
    return updated


def complete_holdout_run(claim_path: Path, report_path: Path) -> HoldoutRunClaim:
    """在 report/raw records 全部写成功后封存 completed claim。"""

    return _update_run_claim(claim_path, status="completed", report_path=report_path)


def fail_holdout_run(claim_path: Path, error: BaseException) -> HoldoutRunClaim:
    """保存普通异常的 failed 事实；KeyboardInterrupt/CancelledError 由调用方保留 started。"""

    return _update_run_claim(claim_path, status="failed", error=error)


def _load_report_artifacts(output_dir: Path, expected_split: str) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    """读取一个 split 的 report/raw/failures 三件产物。"""

    report_value = _read_json(output_dir / "report.json", f"{expected_split} report")
    raw_value = _read_json(output_dir / "raw-records.json", f"{expected_split} raw records")
    failure_value = _read_json(output_dir / "failures" / "failures.json", f"{expected_split} failures")
    if not isinstance(report_value, Mapping):
        raise EvaluationContractError(f"{expected_split} report must be an object")
    if expected_split == "holdout" and report_value.get("holdout_sealed") is not True:
        # Holdout 只有在 run-holdout 完整写出后才可进入合并；历史 dev 报告不能冒充封存结果。
        raise EvaluationContractError("holdout report is not sealed")
    if not isinstance(raw_value, list) or not all(isinstance(item, Mapping) for item in raw_value):
        raise EvaluationContractError(f"{expected_split} raw records must be an array of objects")
    if not isinstance(failure_value, list) or not all(isinstance(item, Mapping) for item in failure_value):
        raise EvaluationContractError(f"{expected_split} failures must be an array of objects")
    raw_records = [dict(item) for item in raw_value]
    for record in raw_records:
        split = record.get("split")
        if split != expected_split:
            raise EvaluationContractError(
                f"{expected_split} raw record has unexpected split: {split!r}"
            )
    return dict(report_value), raw_records, [dict(item) for item in failure_value]


def _report_variant_configurations(report: Mapping[str, object], split: str) -> tuple[dict[str, str], list[Mapping[str, object]]]:
    """读取 report 中每个 Variant 的完整 canonical configuration text。"""

    raw_variants = report.get("variants")
    if not isinstance(raw_variants, Sequence) or isinstance(raw_variants, str):
        raise EvaluationContractError(f"{split} report variants must be an array")
    variants: list[Mapping[str, object]] = []
    configurations: dict[str, str] = {}
    for raw in raw_variants:
        if not isinstance(raw, Mapping):
            raise EvaluationContractError(f"{split} report variant must be an object")
        variant_id = raw.get("variant_id")
        fingerprint = raw.get("variant_fingerprint")
        if not isinstance(variant_id, str) or not variant_id:
            raise EvaluationContractError(f"{split} report variant_id is invalid")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise EvaluationContractError(
                f"{split} report variant {variant_id} lacks full variant_fingerprint"
            )
        if variant_id in configurations:
            raise EvaluationContractError(f"{split} report contains duplicate variant {variant_id}")
        configurations[variant_id] = fingerprint
        variants.append(raw)
    if not configurations:
        raise EvaluationContractError(f"{split} report requires variants")
    return dict(sorted(configurations.items())), variants


def _report_environment(report: Mapping[str, object], split: str) -> Mapping[str, object]:
    """读取 report 的 Environment identity，并拒绝缺少版本字段的报告。"""

    value = report.get("environment")
    if not isinstance(value, Mapping):
        raise EvaluationContractError(f"{split} report environment must be an object")
    return _environment_dict(value)


def _report_provenance(
    *,
    output_dir: Path,
    report: Mapping[str, object],
    raw_records: Sequence[Mapping[str, object]],
    failures: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """保留每个 split 的来源路径和记录数，方便人工确认 full 的构成。"""

    return {
        "output_dir": str(output_dir.resolve()),
        "report": str((output_dir / "report.json").resolve()),
        "raw_records": str((output_dir / "raw-records.json").resolve()),
        "failures": str((output_dir / "failures" / "failures.json").resolve()),
        "report_schema_version": report.get("schema_version"),
        "raw_record_count": len(raw_records),
        "failure_count": len(failures),
    }


def _merge_case_stats(records_by_split: Mapping[str, Sequence[Mapping[str, object]]]) -> dict[str, object]:
    """从原始 run records 重新计算 split/category/variant 计数。"""

    all_records = [record for records in records_by_split.values() for record in records]
    category_counts = Counter(str(record["category"]) for record in all_records if isinstance(record.get("category"), str))
    split_case_ids: dict[str, set[str]] = {}
    variant_counts: Counter[str] = Counter()
    for record in all_records:
        split = record.get("split")
        case_id = record.get("case_id")
        variant_id = record.get("variant_id")
        if isinstance(split, str) and isinstance(case_id, str):
            split_case_ids.setdefault(split, set()).add(case_id)
        if isinstance(variant_id, str):
            variant_counts[variant_id] += 1
    return {
        "suite": "merged",
        "suite_cases": len({case_id for ids in split_case_ids.values() for case_id in ids}),
        "by_category": dict(sorted(category_counts.items())),
        "by_split": {split: len(ids) for split, ids in sorted(split_case_ids.items())},
        "by_variant_runs": dict(sorted(variant_counts.items())),
    }


def merge_reports(
    *,
    development_dir: Path,
    holdout_dir: Path,
    output_dir: Path | None = None,
    freeze: BenchmarkFinalFreezeRecord | None = None,
) -> dict[str, object]:
    """合并 dev/holdout 原始指标；版本不一致时保留 split 并标记 full unavailable。

    ``freeze`` 由正式 CLI 传入时，两个 split 还必须分别匹配 Gate 3 identity；不传
    ``freeze`` 则保留原始报告之间的 identity mismatch 诊断能力，便于离线复核历史产物。
    """

    dev_report, dev_records, dev_failures = _load_report_artifacts(development_dir, "development")
    holdout_report, holdout_records, holdout_failures = _load_report_artifacts(holdout_dir, "holdout")
    dev_environment = _report_environment(dev_report, "development")
    holdout_environment = _report_environment(holdout_report, "holdout")
    dev_variants, dev_variant_entries = _report_variant_configurations(dev_report, "development")
    holdout_variants, holdout_variant_entries = _report_variant_configurations(holdout_report, "holdout")
    if freeze is not None:
        # 最终合并必须引用 freeze 绑定的同一环境和 Variant 配置，不能只比较两个报告彼此相等。
        expected_environment = environment_identity(freeze.environment)
        for split, environment, variants in (
            ("development", dev_environment, dev_variants),
            ("holdout", holdout_environment, holdout_variants),
        ):
            if environment_identity(environment) != expected_environment:
                raise EvaluationContractError(f"{split} report differs from final freeze environment")
            if variants != dict(freeze.variant_configurations):
                raise EvaluationContractError(f"{split} report differs from final freeze variants")
    benchmark = dev_report.get("benchmark")
    if not isinstance(benchmark, str) or not benchmark:
        raise EvaluationContractError("development report benchmark is invalid")
    if holdout_report.get("benchmark") != benchmark:
        mismatches: dict[str, object] = {"benchmark": {"development": benchmark, "holdout": holdout_report.get("benchmark")}}
    else:
        mismatches = {}
    if environment_identity(dev_environment) != environment_identity(holdout_environment):
        mismatches["environment"] = {
            "development": environment_identity(dev_environment),
            "holdout": environment_identity(holdout_environment),
        }
    if dev_variants != holdout_variants:
        mismatches["variant_configurations"] = {
            "development": dev_variants,
            "holdout": holdout_variants,
        }
    all_variant_ids = set(dev_variants) | set(holdout_variants)
    for split, records, known_ids in (
        ("development", dev_records, set(dev_variants)),
        ("holdout", holdout_records, set(holdout_variants)),
    ):
        for record in records:
            if record.get("variant_id") not in known_ids:
                raise EvaluationContractError(f"{split} raw record references unknown Variant")

    records_by_split: dict[str, Sequence[Mapping[str, object]]] = {
        "development": dev_records,
        "holdout": holdout_records,
    }
    failures = [*dev_failures, *holdout_failures]
    metadata: dict[str, object] = {
        "stage": "merged",
        "full_available": not mismatches,
        "full_unavailable_reasons": sorted(mismatches) if mismatches else [],
        "development_provenance": _report_provenance(
            output_dir=development_dir,
            report=dev_report,
            raw_records=dev_records,
            failures=dev_failures,
        ),
        "holdout_provenance": _report_provenance(
            output_dir=holdout_dir,
            report=holdout_report,
            raw_records=holdout_records,
            failures=holdout_failures,
        ),
    }
    if not mismatches:
        merged_records = [*dev_records, *holdout_records]
        records_by_split["full"] = merged_records
    raw_module_retrieval = dev_report.get("module_retrieval")
    module_retrieval = raw_module_retrieval if isinstance(raw_module_retrieval, Mapping) else None
    report = build_report(
        benchmark=benchmark,
        environment=dev_environment,
        variants=dev_variant_entries,
        case_stats=_merge_case_stats(records_by_split),
        end_to_end_records=records_by_split,
        module_retrieval=module_retrieval,
        failures=failures,
        holdout_sealed=True,
        report_metadata=metadata,
    )
    # report 顶层再保留 provenance，Markdown 和 JSON 都能直接看到两个输入 split。
    report["provenance"] = {
        "development": metadata["development_provenance"],
        "holdout": metadata["holdout_provenance"],
    }
    if mismatches:
        report_splits = report.get("splits")
        if not isinstance(report_splits, dict):
            raise EvaluationContractError("merged report splits must be an object")
        report_splits["full"] = {
            "status": "unavailable",
            "reason": "identity_mismatch",
            "mismatches": mismatches,
        }
    report["variant_identity"] = {
        "development": dev_variants,
        "holdout": holdout_variants,
        "matching": not bool(mismatches),
        "variant_ids": sorted(all_variant_ids),
    }
    if output_dir is not None:
        # Final report 是可审阅事实；已有核心 artifact 时拒绝静默覆盖，避免重复合并改变证据。
        if output_dir.exists() and not output_dir.is_dir():
            raise EvaluationContractError(f"merged output path is not a directory: {output_dir}")
        for artifact_path in (
            output_dir / "report.json",
            output_dir / "report.md",
            output_dir / "raw-records.json",
            output_dir / "failures" / "failures.json",
        ):
            if artifact_path.exists():
                raise EvaluationContractError(
                    f"merged output already contains {artifact_path.name}: {output_dir}"
                )
        output_dir.mkdir(parents=True, exist_ok=True)
        write_report_outputs(
            report,
            json_path=output_dir / "report.json",
            markdown_path=output_dir / "report.md",
        )
        (output_dir / "raw-records.json").write_text(
            json.dumps([*dev_records, *holdout_records], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "failures").mkdir(parents=True, exist_ok=True)
        (output_dir / "failures" / "failures.json").write_text(
            json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report


merge_benchmark_reports = merge_reports


__all__ = [
    "BenchmarkFinalFreezeRecord",
    "ClosureVerificationResult",
    "FINAL_FREEZE_SCHEMA_VERSION",
    "HOLDOUT_REGISTRATION_SCHEMA_VERSION",
    "HOLDOUT_RUN_CLAIM_SCHEMA_VERSION",
    "HoldoutRegistrationRecord",
    "HoldoutRunClaim",
    "assert_finalized_run_inputs",
    "assert_holdout_registration",
    "begin_holdout_run",
    "capture_final_freeze",
    "capture_final_freeze_record",
    "complete_holdout_run",
    "environment_identity",
    "fail_holdout_run",
    "holdout_run_claim_path",
    "merge_benchmark_reports",
    "merge_reports",
    "read_holdout_run_claim",
    "register_holdout",
    "register_holdout_cases",
    "verify_final_freeze",
    "verify_final_freeze_record",
    "verify_holdout_registration",
    "verify_holdout_registration_record",
]
