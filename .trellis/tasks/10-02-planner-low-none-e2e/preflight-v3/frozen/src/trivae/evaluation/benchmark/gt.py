"""Benchmark Ground Truth 解析：ReferenceFinding criterion 约定 → 结构化 GT 视图。

Case 的 canonical truth 仍完全由 ``EvaluationCaseBundle.reference_findings`` 承载；
本模块是唯一的 criterion 约定解析点，负责把 finding/evidence 转成指标引擎可直读的
结构，并强制 GT 内部一致性（单向蕴含、criterion 唯一性、locator 形态）。

criterion 约定（design §3）：
- ``gt.relevant``：相关消息；每条一个 ``ReferenceEvidence(relation="supports",
  source_type="message", locator={"internal_message_id": ...})``。finding 的
  ``annotation_completeness`` 声明枚举完备度（exhaustive 才允许 corpus scope 指标）。
- ``gt.required_context``：expansion 应恢复的上下文消息，``relation="context"``。
- ``gt.expected_coverage_status``：``expected_semantics`` ∈ 生产 CoverageStatus 词表。
- ``gt.expected_truncated``：``expected_semantics`` = ``true|false``。
- ``gt.expected_zero_result``：``expected_semantics`` = ``true|false``；
  单向蕴含：true ⇒ 不得存在 gt.relevant；false 时通常应存在 gt.relevant。
- ``gt.expected_fact``：``expected_semantics`` = JSON 数组（规范化 alias 列表）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from trivae.evaluation.contracts import (
    EvaluationCaseBundle,
    EvaluationContractError,
    ReferenceFinding,
)

RELEVANT_CRITERION = "gt.relevant"
REQUIRED_CONTEXT_CRITERION = "gt.required_context"
EXPECTED_COVERAGE_CRITERION = "gt.expected_coverage_status"
EXPECTED_TRUNCATED_CRITERION = "gt.expected_truncated"
EXPECTED_ZERO_RESULT_CRITERION = "gt.expected_zero_result"
EXPECTED_FACT_CRITERION = "gt.expected_fact"

GT_CRITERIA = (
    RELEVANT_CRITERION,
    REQUIRED_CONTEXT_CRITERION,
    EXPECTED_COVERAGE_CRITERION,
    EXPECTED_TRUNCATED_CRITERION,
    EXPECTED_ZERO_RESULT_CRITERION,
    EXPECTED_FACT_CRITERION,
)

COVERAGE_STATUS_VOCABULARY = ("complete", "partial", "none", "unknown", "not_applicable")


def _parse_bool_semantics(finding: ReferenceFinding) -> bool:
    """解析 true/false 词表的 expected_semantics，拒绝其他文本。"""

    normalized = finding.expected_semantics.strip().lower()
    if normalized not in ("true", "false"):
        raise EvaluationContractError(
            f"finding {finding.finding_id} expected_semantics must be true or false"
        )
    return normalized == "true"


def _parse_locator_message_id(finding: ReferenceFinding, evidence_index: int) -> str:
    """从 ReferenceEvidence locator 解析 canonical message ID，拒绝其他形态。"""

    evidence = finding.reference_evidence[evidence_index]
    if evidence.relation not in ("supports", "context"):
        raise EvaluationContractError(
            f"finding {finding.finding_id} evidence {evidence_index} relation must be supports or context"
        )
    if evidence.source_type != "message":
        raise EvaluationContractError(
            f"finding {finding.finding_id} evidence {evidence_index} must reference a message"
        )
    internal_message_id = evidence.locator.get("internal_message_id")
    if not isinstance(internal_message_id, str) or not internal_message_id.strip():
        raise EvaluationContractError(
            f"finding {finding.finding_id} evidence {evidence_index} locator requires internal_message_id"
        )
    return internal_message_id.strip()


@dataclass(frozen=True)
class CaseGroundTruth:
    """一个 Case 的结构化 GT 视图；指标引擎只消费本结构，不重复解析 finding。"""

    case_id: str
    relevant_message_ids: tuple[str, ...]
    required_context_message_ids: tuple[str, ...]
    expected_coverage_status: str | None
    expected_truncated: bool | None
    expected_zero_result: bool | None
    expected_facts: tuple[tuple[str, ...], ...]
    completeness: str
    category: str | None
    benchmark_split: str | None

    @property
    def evidence_target_ids(self) -> tuple[str, ...]:
        """Evidence Recall / Context Recovery 的目标集合（relevant ∪ required_context）。"""

        return tuple(dict.fromkeys((*self.relevant_message_ids, *self.required_context_message_ids)))

    @property
    def has_relevant(self) -> bool:
        return bool(self.relevant_message_ids)

    @property
    def recall_scope(self) -> str:
        """GT 完备度决定的指标 scope：exhaustive→corpus；其余→target。"""

        return "corpus" if self.completeness == "exhaustive" else "target"


def _normalized_aliases(finding: ReferenceFinding) -> tuple[str, ...]:
    """解析 expected_fact 的 JSON alias 数组，并做规范化（去空白、小写、去重）。"""

    try:
        decoded = json.loads(finding.expected_semantics)
    except json.JSONDecodeError as exc:
        raise EvaluationContractError(
            f"finding {finding.finding_id} expected_semantics must be a JSON alias array"
        ) from exc
    if not isinstance(decoded, list) or not decoded:
        raise EvaluationContractError(
            f"finding {finding.finding_id} expected_semantics must be a non-empty JSON array"
        )
    aliases: list[str] = []
    for item in decoded:
        if not isinstance(item, str) or not item.strip():
            raise EvaluationContractError(
                f"finding {finding.finding_id} alias must be a non-empty string"
            )
        normalized = item.strip().lower()
        if normalized not in aliases:
            aliases.append(normalized)
    return tuple(aliases)


def _expect_single(finding_id: str, findings: list[ReferenceFinding]) -> ReferenceFinding:
    if len(findings) != 1:
        raise EvaluationContractError(
            f"criterion for {finding_id} must appear exactly once, found {len(findings)}"
        )
    return findings[0]


def _category_from_tags(tags: tuple[str, ...]) -> str | None:
    for tag in tags:
        if tag.startswith("category:"):
            return tag.removeprefix("category:")
    return None


def _split_from_tags(tags: tuple[str, ...]) -> str | None:
    for tag in tags:
        if tag.startswith("benchmark:"):
            return tag.removeprefix("benchmark:")
    return None


def build_case_ground_truth(case: EvaluationCaseBundle) -> CaseGroundTruth:
    """解析并校验一个 Case 的 benchmark GT；违反一致性立即拒绝。"""

    by_criterion: dict[str, list[ReferenceFinding]] = {}
    for finding in case.reference_findings:
        if not finding.criterion.startswith("gt."):
            # 非 gt. 前缀的 finding 属于 review rubric / diagnostic expectation，不进入 benchmark GT。
            continue
        by_criterion.setdefault(finding.criterion, []).append(finding)

    for criterion in by_criterion:
        if criterion not in GT_CRITERIA:
            raise EvaluationContractError(f"unknown benchmark gt criterion: {criterion}")

    relevant_findings = by_criterion.get(RELEVANT_CRITERION, [])
    relevant_finding = _expect_single(RELEVANT_CRITERION, relevant_findings) if relevant_findings else None
    relevant_ids = tuple(
        dict.fromkeys(
            _parse_locator_message_id(relevant_finding, index)
            for index in range(len(relevant_finding.reference_evidence))
        )
        if relevant_finding is not None
        else ()
    )

    context_findings = by_criterion.get(REQUIRED_CONTEXT_CRITERION, [])
    context_finding = _expect_single(REQUIRED_CONTEXT_CRITERION, context_findings) if context_findings else None
    context_ids = tuple(
        dict.fromkeys(
            _parse_locator_message_id(context_finding, index)
            for index in range(len(context_finding.reference_evidence))
        )
        if context_finding is not None
        else ()
    )

    overlap = set(relevant_ids) & set(context_ids)
    if overlap:
        raise EvaluationContractError(
            f"case {case.case_id} gt.relevant and gt.required_context overlap: {sorted(overlap)!r}"
        )

    expected_zero_result: bool | None = None
    zero_findings = by_criterion.get(EXPECTED_ZERO_RESULT_CRITERION, [])
    if zero_findings:
        expected_zero_result = _parse_bool_semantics(_expect_single(EXPECTED_ZERO_RESULT_CRITERION, zero_findings))
    if expected_zero_result is True and relevant_ids:
        raise EvaluationContractError(
            f"case {case.case_id} expected_zero_result=true conflicts with gt.relevant messages"
        )

    expected_coverage_status: str | None = None
    coverage_findings = by_criterion.get(EXPECTED_COVERAGE_CRITERION, [])
    if coverage_findings:
        coverage_finding = _expect_single(EXPECTED_COVERAGE_CRITERION, coverage_findings)
        normalized = coverage_finding.expected_semantics.strip()
        if normalized not in COVERAGE_STATUS_VOCABULARY:
            raise EvaluationContractError(
                f"case {case.case_id} expected_coverage_status must be one of {COVERAGE_STATUS_VOCABULARY}"
            )
        expected_coverage_status = normalized

    expected_truncated: bool | None = None
    truncated_findings = by_criterion.get(EXPECTED_TRUNCATED_CRITERION, [])
    if truncated_findings:
        expected_truncated = _parse_bool_semantics(
            _expect_single(EXPECTED_TRUNCATED_CRITERION, truncated_findings)
        )

    # expected_fact 允许多个 finding：每个 finding 是一个独立事实（一组 alias）。
    expected_facts = tuple(
        _normalized_aliases(finding)
        for finding in by_criterion.get(EXPECTED_FACT_CRITERION, [])
    )

    completeness = "exhaustive"
    if relevant_finding is None:
        completeness = "unknown"
    elif relevant_finding.annotation_completeness != "exhaustive":
        completeness = relevant_finding.annotation_completeness

    zero_expected_declared = expected_zero_result is not None
    if (
        completeness == "exhaustive"
        and not relevant_ids
        and not zero_expected_declared
    ):
        # 没有 relevant 也没有 zero-result 声明的 case 无法参与任何召回/零结果指标。
        raise EvaluationContractError(
            f"case {case.case_id} must declare gt.relevant evidence or gt.expected_zero_result"
        )

    return CaseGroundTruth(
        case_id=case.case_id,
        relevant_message_ids=relevant_ids,
        required_context_message_ids=context_ids,
        expected_coverage_status=expected_coverage_status,
        expected_truncated=expected_truncated,
        expected_zero_result=expected_zero_result,
        expected_facts=expected_facts,
        completeness=completeness,
        category=_category_from_tags(case.suite_tags),
        benchmark_split=_split_from_tags(case.suite_tags),
    )


def build_ground_truth_index(cases: Mapping[str, EvaluationCaseBundle]) -> dict[str, CaseGroundTruth]:
    """按 case identity 解析 GT 索引；重复 case_id 立即拒绝。"""

    index: dict[str, CaseGroundTruth] = {}
    for case in cases.values():
        truth = build_case_ground_truth(case)
        if truth.case_id in index:
            raise EvaluationContractError(f"duplicate benchmark case_id: {truth.case_id}")
        index[truth.case_id] = truth
    return index
