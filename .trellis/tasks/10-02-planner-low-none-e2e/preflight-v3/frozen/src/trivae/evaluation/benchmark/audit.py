"""Benchmark GT 机器审计：人工裁决前后的确定性一致性检查。

审计是裁决的前置，不替代裁决；所有检查都是确定性的，结果按 case 汇总。
检查项（prd §3/§5）：
- case_id 唯一、全部绑定同一 canonical snapshot
- GT 引用的 message id 存在于 canonical DB
- zero_result 单向蕴含（复用 gt.py 校验）+ 空窗口/零 token 的 canonical 空证明复核；
  带日历日期的 zero-result query 必须显式声明 UTC（生产系统唯一正式日历语义是 UTC，
  裸日期 + UTC proof 属于 query/proof 边界歧义，2026-08-31 人工裁决禁止）
- relevant 集合的确定性证明复核（expected_fact alias 作 predicate 重新 LIKE 扫描，
  集合必须与 GT 一致；exhaustive = corpus 谓词完备，partial = target repo 出现集合完备，
  两者都要求 declared 集合 == alias 全库出现集合，不得声称语义类 corpus 穷举）
- temporal 窗口计数与 archive_latest 一致（复核 provenance 中记录的 count）
- expected_fact alias 非空且规范化后唯一
- category 与 GT 形态一致（exact_lexical/citation_evidence 允许 exhaustive 或 partial/target；
  "target URL exhaustive" 不等价于 "query semantic corpus exhaustive"，故 partial 合法）
- 裁决完整性：gt finding/evidence provenance.adjudicated 未全置 true → warning
  （裁决前审计允许 provisional；最终 gate 目标是 0 warning）
- version-controlled case 文件无正文泄露（字符串值不得命中任何消息内容）
- holdout 目录不存在（构造时序隔离）
"""

from __future__ import annotations

import datetime
import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Mapping

from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError
from trivae.evaluation.retrieval_evaluation import RETRIEVAL_PACKET_SCHEMA_VERSION  # noqa: F401  # 保留 schema 对齐引用

from .gt import CaseGroundTruth, build_case_ground_truth

_ESCAPE_TABLE = str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"})

# query 中的日历日期（中文年月日 / ISO）；zero-result 空窗口证明按 UTC 日复核。
_DATE_PATTERNS = (
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
)
# zero-token 证明的 method 约定：LIKE scan for token '<token>' = 0
_TOKEN_ZERO_PATTERN = re.compile(r"LIKE scan for token '([^']+)' = 0")
_UTC_DAY_MS = 24 * 60 * 60 * 1000


def _extract_query_date(query: str) -> tuple[int, int, int] | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(query)
        if match:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return None


def _escape_like(value: str) -> str:
    return value.translate(_ESCAPE_TABLE)


def _iter_strings(value: object) -> Iterator[str]:

    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


class CaseAudit:
    """对一组 version-controlled case 目录执行确定性审计。"""

    def __init__(
        self,
        *,
        database_path: Path,
        case_dirs: tuple[Path, ...],
        holdout_dir: Path = Path("data/evaluation/benchmark/holdout"),
    ) -> None:
        self._database_path = database_path
        self._case_dirs = case_dirs
        self._holdout_dir = holdout_dir
        self._connection = sqlite3.connect(f"file:{database_path.resolve()}?mode=ro", uri=True)
        self._connection.row_factory = sqlite3.Row
        # 正文泄露检查的 haystack：一次性载入全部消息内容（本地评测环境可承受），
        # 避免对每条候选字符串做一次全表 LIKE 扫描。
        rows = self._connection.execute("SELECT content_text FROM messages WHERE recalled = 0")
        self._content_corpus = "\x00".join(
            row[0] for row in rows if isinstance(row[0], str) and row[0]
        )

    def close(self) -> None:
        self._connection.close()

    def _message_exists(self, message_id: str) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM messages WHERE internal_message_id = ?", (message_id,)
            ).fetchone()
            is not None
        )

    def _like_message_ids(self, keyword: str) -> set[str]:
        rows = self._connection.execute(
            "SELECT internal_message_id FROM messages WHERE content_text LIKE ? ESCAPE '\\' AND recalled = 0",
            (f"%{_escape_like(keyword)}%",),
        ).fetchall()
        return {row["internal_message_id"] for row in rows}

    def _content_leak(self, text: str) -> bool:
        if len(text) < 20:
            return False
        return text in self._content_corpus

    def _window_count(self, start: int, end: int) -> int:
        return int(
            self._connection.execute(
                "SELECT COUNT(*) FROM messages WHERE timestamp >= ? AND timestamp < ?", (start, end)
            ).fetchone()[0]
        )

    def _archive_latest(self) -> int:
        return int(self._connection.execute("SELECT MAX(timestamp) FROM messages").fetchone()[0])

    def audit(self) -> dict[str, object]:
        findings: list[dict[str, object]] = []
        cases: dict[str, EvaluationCaseBundle] = {}
        snapshot_ids: set[str] = set()

        for case_dir in self._case_dirs:
            for path in sorted(case_dir.glob("*.json")):
                case = EvaluationCaseBundle.from_json(path)
                if case.case_id in cases:
                    findings.append(_finding("error", case.case_id, "duplicate_case_id"))
                cases[case.case_id] = case
                snapshot_ids.add(case.dataset_snapshot.snapshot_id)
        if len(snapshot_ids) > 1:
            findings.append(_finding("error", "*", f"mixed_snapshot_binding: {sorted(snapshot_ids)!r}"))

        archive_latest = self._archive_latest()
        category_counts: dict[str, int] = {}
        adjudicated_cases = 0
        for case_id in sorted(cases):
            case = cases[case_id]
            category = next(
                (tag.removeprefix("category:") for tag in case.suite_tags if tag.startswith("category:")),
                None,
            )
            if category is not None:
                category_counts[category] = category_counts.get(category, 0) + 1
            try:
                truth: CaseGroundTruth = build_case_ground_truth(case)
            except EvaluationContractError as exc:
                findings.append(_finding("error", case_id, f"gt_contract: {exc}"))
                continue

            # 裁决完整性：gt finding 与其 evidence 的 provenance.adjudicated 必须全部置 true
            # （裁决前 provisional 属正常，最终 gate 目标 0 warning）。
            gt_findings = [f for f in case.reference_findings if f.criterion.startswith("gt.")]
            if all(
                f.provenance.adjudicated and all(e.provenance.adjudicated for e in f.reference_evidence)
                for f in gt_findings
            ):
                adjudicated_cases += 1
            else:
                findings.append(_finding("warning", case_id, "case_not_adjudicated"))

            # message id 存在性
            for message_id in truth.evidence_target_ids:
                if not self._message_exists(message_id):
                    findings.append(_finding("error", case_id, f"missing_message: {message_id}"))

            # category ↔ GT 形态一致性
            findings.extend(self._category_shape(case_id, category, truth))

            # 出现集合证明复核：expected_fact alias 作 predicate 重新扫描。
            # exhaustive（corpus 谓词）与 partial（target repo 出现集合）都要求
            # declared relevant 集合 == alias 全库出现集合；partial 只是额外声明
            # "query 语义类不穷举 corpus"，不豁免 target 集合的确定性证明。
            if truth.has_relevant and truth.expected_facts:
                alias = truth.expected_facts[0][0]
                scanned = self._like_message_ids(alias)
                declared = set(truth.relevant_message_ids)
                if scanned != declared:
                    missing = sorted(declared - scanned)
                    extra = sorted(scanned - declared)
                    findings.append(
                        _finding(
                            "error",
                            case_id,
                            f"occurrence_set_mismatch: missing={missing} extra={extra}",
                        )
                    )

            # zero_result 空证明复核：query 中的 UTC 日期窗口必须为 0
            if truth.expected_zero_result is True:
                date_parts = _extract_query_date(case.query)
                token_zero = date_parts is None
                if date_parts is not None:
                    year, month, day = date_parts
                    try:
                        day_date = datetime.date(year, month, day)
                    except ValueError:
                        findings.append(_finding("error", case_id, f"zero_result_invalid_date: {year}-{month}-{day}"))
                    else:
                        start = int(
                            datetime.datetime.fromisoformat(day_date.isoformat())
                            .replace(tzinfo=datetime.timezone.utc)
                            .timestamp()
                            * 1000
                        )
                        if self._window_count(start, start + _UTC_DAY_MS) != 0:
                            findings.append(_finding("error", case_id, "zero_result_window_not_empty"))
                        # 生产系统唯一正式日历语义是 UTC；裸日期与 UTC proof 的组合
                        # 存在边界歧义，人工裁决（2026-08-31）要求 query 显式声明 UTC。
                        if "UTC" not in case.query.upper():
                            findings.append(_finding("warning", case_id, "zero_result_bare_date_without_utc"))
                elif truth.has_relevant:
                    findings.append(_finding("error", case_id, "zero_result_true_with_relevant"))
                if token_zero and not truth.has_relevant:
                    # token 级零命中 case：expected_fact 不应存在（无 extractive fact 可答）。
                    if truth.expected_facts:
                        findings.append(_finding("warning", case_id, "zero_result_case_declares_expected_fact"))
                    findings.extend(self._token_zero_check(case_id, case))

            # temporal 窗口计数复核：provenance method 内记录的 count 与当前 DB 重算一致
            if category == "temporal_overview":
                findings.extend(self._temporal_count_check(case_id, case, archive_latest))

            # 正文泄露检查（version-controlled artifact）。
            # expected_fact alias 是刻意提取的消息子串，属合法 GT 引用，不视为泄露。
            alias_exemptions = {alias for aliases in truth.expected_facts for alias in aliases}
            leak_candidates = [
                text
                for text in _iter_strings(json.loads(json.dumps(case.to_dict(), ensure_ascii=False)))
                if len(text) >= 20
                and text.casefold() not in alias_exemptions
                and not text.startswith(("snapshot-v1:", "sqlite-canonical", "deterministic", "manual", "reply pair", "window count", "SQL COUNT", "LIKE scan", "deterministic-construction", "dev-construction", "calibration-construction", "provisional"))
            ]
            for text in leak_candidates:
                if self._content_leak(text):
                    findings.append(_finding("error", case_id, f"content_leak: {text[:60]!r}"))

        if self._holdout_dir.exists() and any(self._holdout_dir.iterdir()):
            findings.append(_finding("error", "*", "holdout_dir_exists_before_freeze"))

        return {
            "schema_version": "benchmark-gt-audit-v1",
            "case_count": len(cases),
            "adjudicated_case_count": adjudicated_cases,
            "category_counts": dict(sorted(category_counts.items())),
            "snapshot_ids": sorted(snapshot_ids),
            "archive_latest": archive_latest,
            "findings": findings,
            "passed": not any(item["severity"] == "error" for item in findings),
        }

    def _token_zero_check(self, case_id: str, case: EvaluationCaseBundle) -> list[dict[str, object]]:
        """token 级零命中证明复核：method 声明 'LIKE scan for token X = 0' 时重新扫描。"""
        findings: list[dict[str, object]] = []
        zero = next((f for f in case.reference_findings if f.criterion == "gt.expected_zero_result"), None)
        if zero is None:
            return findings
        match = _TOKEN_ZERO_PATTERN.search(zero.provenance.method)
        if match is None:
            return findings
        token = match.group(1)
        if self._like_message_ids(token):
            findings.append(_finding("error", case_id, f"zero_result_token_hit_present: {token}"))
        return findings

    def _category_shape(self, case_id: str, category: str | None, gt: CaseGroundTruth) -> list[dict[str, object]]:
        findings: list[dict[str, object]] = []
        if category == "zero_result" and gt.expected_zero_result is not True:
            findings.append(_finding("error", case_id, "category_shape: zero_result without expected_zero_result=true"))
        if category == "temporal_overview" and gt.expected_coverage_status is None:
            findings.append(_finding("error", case_id, "category_shape: temporal without expected_coverage_status"))
        if category in ("exact_lexical", "citation_evidence"):
            # exhaustive = query 等价于可枚举 predicate；partial = 语义类 query +
            # target repo 出现集合（"target URL exhaustive" ≠ "query corpus exhaustive"，
            # 2026-08-31 人工裁决确立两者都合法，unknown 仍拒绝）。
            if gt.completeness not in ("exhaustive", "partial"):
                findings.append(
                    _finding("error", case_id, "category_shape: predicate case must declare exhaustive or partial/target")
                )
            if not gt.expected_facts:
                findings.append(_finding("error", case_id, "category_shape: predicate case without expected_fact"))
        if category == "semantic_paraphrase" and gt.completeness == "exhaustive":
            findings.append(_finding("error", case_id, "category_shape: paraphrase must not claim exhaustive"))
        if category == "context_recovery" and not gt.required_context_message_ids:
            findings.append(_finding("error", case_id, "category_shape: context_recovery without required_context"))
        return findings

    def _temporal_count_check(self, case_id: str, case: EvaluationCaseBundle, archive_latest: int) -> list[dict[str, object]]:
        findings: list[dict[str, object]] = []
        zero = next((f for f in case.reference_findings if f.criterion == "gt.expected_zero_result"), None)
        if zero is None or zero.expected_semantics != "false":
            return findings
        days_match = re.search(r"last (\d+)d", " ".join(f.provenance.method for f in case.reference_findings))
        count_match = re.search(r"= (\d+)", " ".join(f.provenance.method for f in case.reference_findings))
        if not days_match or not count_match:
            return findings
        days = int(days_match.group(1))
        recorded = int(count_match.group(1))
        current = self._window_count(archive_latest - days * 24 * 60 * 60 * 1000, archive_latest + 1)
        if current != recorded:
            findings.append(
                _finding("error", case_id, f"temporal_count_drift: recorded={recorded} current={current}")
            )
        return findings


def _finding(severity: str, case_id: str, detail: str) -> dict[str, object]:
    return {"severity": severity, "case_id": case_id, "detail": detail}
