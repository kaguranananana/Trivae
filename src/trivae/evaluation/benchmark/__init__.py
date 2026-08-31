"""resume-benchmark Measurement Substrate。

本包复用现有 Evaluation contract（Case/Snapshot/Variant/Runner/Store），只新增
GT 解析、environment lock、指标引擎与报告层，不构建第二套 Agent 或检索实现。
"""

from .environment import BenchmarkEnvironmentManifest, EnvironmentGateResult
from .freeze import (
    BenchmarkFreezeRecord,
    FreezeVerificationResult,
    capture_freeze_record,
    verify_freeze_record,
)
from .gt import CaseGroundTruth, build_case_ground_truth

__all__ = [
    "BenchmarkEnvironmentManifest",
    "EnvironmentGateResult",
    "BenchmarkFreezeRecord",
    "FreezeVerificationResult",
    "capture_freeze_record",
    "verify_freeze_record",
    "CaseGroundTruth",
    "build_case_ground_truth",
]
