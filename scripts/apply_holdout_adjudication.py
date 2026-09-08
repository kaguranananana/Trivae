#!/usr/bin/env python3
"""将 holdout/review.md 中已完成的人工裁决写入本地 Holdout Case。

脚本只接受逐条 ``confirmed`` 且结论为 ``同意 adjudicate`` 的 review，
不会根据系统运行结果修改 GT 目标、完备度或 expected 语义。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLDOUT_ROOT = ROOT / "data" / "evaluation" / "benchmark" / "holdout"
CASES_DIR = HOLDOUT_ROOT / "cases"
REVIEW_PATH = HOLDOUT_ROOT / "review.md"
PACKET_PATH = HOLDOUT_ROOT / "candidate-packet.json"
ADJUDICATION_DATE = "2026-09-08"


def review_decisions() -> dict[str, str]:
    """解析 review 的逐条状态，并拒绝缺失、重复或非确认结论。"""

    text = REVIEW_PATH.read_text(encoding="utf-8")
    headings = re.findall(r"^## (holdout-[^\s]+) \[", text, flags=re.MULTILINE)
    statuses = re.findall(
        r"^- 核验状态：`([^`]+)`；结论：([^；]*)；理由：",
        text,
        flags=re.MULTILINE,
    )
    if len(headings) != 18 or len(statuses) != 18:
        raise SystemExit(f"review must contain 18 case headings and 18 status lines, got {len(headings)} / {len(statuses)}")
    if len(set(headings)) != len(headings):
        raise SystemExit("review contains duplicate holdout case headings")
    decisions: dict[str, str] = {}
    for case_id, (status, conclusion) in zip(headings, statuses, strict=True):
        if status != "confirmed" or conclusion.strip() != "同意 adjudicate":
            raise SystemExit(f"{case_id}: review status is not confirmed/adjudicate: {status!r} / {conclusion!r}")
        decisions[case_id] = status
    return decisions


def mark_provenance_adjudicated(provenance: dict[str, object]) -> None:
    """把已人工核验的 provenance 标记为可进入 holdout registration。"""

    provenance["adjudicated"] = True
    provenance["limitations"] = []


def apply_case(case_path: Path) -> None:
    """对单个 Case 的所有 benchmark GT finding/evidence 写入人工裁决事实。"""

    payload = json.loads(case_path.read_text(encoding="utf-8"))
    case_id = str(payload["case_id"])
    findings = [finding for finding in payload["reference_findings"] if finding["criterion"].startswith("gt.")]
    if not findings:
        raise SystemExit(f"{case_id}: no benchmark GT finding")
    already_adjudicated = all(
        finding["provenance"].get("adjudicated") is True
        and all(item["provenance"].get("adjudicated") is True for item in finding["reference_evidence"])
        for finding in findings
    )
    partially_adjudicated = any(
        finding["provenance"].get("adjudicated") is True
        or any(item["provenance"].get("adjudicated") is True for item in finding["reference_evidence"])
        for finding in findings
    )
    if partially_adjudicated and not already_adjudicated:
        raise SystemExit(f"{case_id}: partial adjudication state is invalid")
    if already_adjudicated:
        return

    for finding in findings:
        mark_provenance_adjudicated(finding["provenance"])
        for item in finding["reference_evidence"]:
            mark_provenance_adjudicated(item["provenance"])
    method = str(payload["provenance"]["method"]).removesuffix("; provisional")
    payload["provenance"]["method"] = f"{method}; human adjudicated {ADJUDICATION_DATE}"
    payload["provenance"]["notes"] = (
        f"human adjudication {ADJUDICATION_DATE}: Accept (GT unchanged; confirmed in holdout/review.md)"
    )
    case_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def update_packet(decisions: dict[str, str]) -> None:
    """同步更新 candidate packet 的 lifecycle 状态，不改 packet 中的 GT 内容。"""

    payload = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list) or {item.get("case_id") for item in items} != set(decisions):
        raise SystemExit("candidate packet case identities do not match review decisions")
    payload["status"] = "human_adjudicated"
    for item in items:
        item["status"] = decisions[item["case_id"]]
    PACKET_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """完成 review 一致性检查、18 条 Case 裁决写入和 packet 状态同步。"""

    decisions = review_decisions()
    case_paths = {path.stem: path for path in CASES_DIR.glob("*.json")}
    if set(case_paths) != set(decisions):
        raise SystemExit("review case identities do not match holdout case files")
    for case_id in decisions:
        apply_case(case_paths[case_id])
    update_packet(decisions)
    print(f"adjudicated {len(decisions)} holdout cases")


if __name__ == "__main__":
    main()
