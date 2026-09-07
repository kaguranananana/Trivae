"""resume-benchmark Measurement Substrate。

本包复用现有 Evaluation contract（Case/Snapshot/Variant/Runner/Store），只新增
GT 解析、environment lock、指标引擎与报告层，不构建第二套 Agent 或检索实现。
"""

from .closure import (
    BenchmarkFinalFreezeRecord,
    ClosureVerificationResult,
    HoldoutRegistrationRecord,
    HoldoutRunClaim,
    assert_finalized_run_inputs,
    assert_holdout_registration,
    begin_holdout_run,
    capture_final_freeze,
    complete_holdout_run,
    environment_identity,
    fail_holdout_run,
    holdout_run_claim_path,
    merge_reports,
    read_holdout_run_claim,
    register_holdout,
    verify_final_freeze,
    verify_holdout_registration,
)
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
    "BenchmarkFinalFreezeRecord",
    "ClosureVerificationResult",
    "HoldoutRegistrationRecord",
    "HoldoutRunClaim",
    "assert_finalized_run_inputs",
    "assert_holdout_registration",
    "begin_holdout_run",
    "capture_final_freeze",
    "complete_holdout_run",
    "environment_identity",
    "fail_holdout_run",
    "holdout_run_claim_path",
    "merge_reports",
    "read_holdout_run_claim",
    "register_holdout",
    "verify_final_freeze",
    "verify_holdout_registration",
    "BenchmarkFreezeRecord",
    "FreezeVerificationResult",
    "capture_freeze_record",
    "verify_freeze_record",
    "CaseGroundTruth",
    "build_case_ground_truth",
]
