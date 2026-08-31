#!/usr/bin/env python3
"""生成 GT review pack（local-only artifact）。

覆盖 data/evaluation/benchmark/review-pack-dev.md：
- 每 case：query / category / completeness / GT axes / message 摘要（bounded）/ 证明复核 / 裁决结果
- 摘要含真实消息片段：本文件在 data/evaluation/（gitignored），禁止提交或外发
- 2026-08-31 人工裁决完成后：裁决结果读取 case provenance notes；
  module 可达性保留为参考（不构成 GT 依据）
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DATABASE = Path("data/trivae.sqlite3")
CASE_DIRS = (Path("evaluation/cases/benchmark/calibration"), Path("evaluation/cases/benchmark/dev"))
AUDIT_PATH = Path("data/evaluation/benchmark/gt-audit.json")
CAL_MODULE_PATH = Path("data/evaluation/benchmark/module-retrieval-scores.json")
DEV_MODULE_PATH = Path("data/evaluation/benchmark/module-retrieval-scores-dev.json")
OUTPUT = Path("data/evaluation/benchmark/review-pack-dev.md")
EXCERPT_CHARS = 140
ADJUDICATION_NOTE = re.compile(r"human adjudication (\S+): (Accept|Modify)(?: \((.*)\))?")


def load_module_reachability() -> dict[str, dict[str, object]]:
    reach: dict[str, dict[str, object]] = {}
    for path in (CAL_MODULE_PATH, DEV_MODULE_PATH):
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for query in data["queries"]:
            per_strategy: dict[str, object] = {}
            for metric in query["metrics"]:
                if metric["availability"] != "available" or metric["value"] is None:
                    continue
                strategy, _, rest = metric["name"].partition(":")
                if rest in ("recall_at_k", "mrr_at_k") and metric["k"] == 10:
                    per_strategy[f"{strategy}:{rest}"] = metric["value"]
            reach[query["case_id"]] = per_strategy
    return reach


def parse_decision(notes: str | None) -> tuple[str, str, str | None]:
    """从 case provenance notes 解析裁决（date, decision, detail）。"""
    if notes:
        match = ADJUDICATION_NOTE.search(notes)
        if match:
            return match.group(1), match.group(2), match.group(3)
    return "-", "NOT ADJUDICATED", None


def main() -> None:
    audit = json.loads(AUDIT_PATH.read_text())
    audit_errors = sum(1 for f in audit["findings"] if f["severity"] == "error")
    audit_warnings = sum(1 for f in audit["findings"] if f["severity"] == "warning")
    reach = load_module_reachability()

    connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    lines = [
        "# resume-benchmark-v1 GT Review Pack（development + calibration）",
        "",
        "> **local-only artifact**：含真实消息片段，禁止提交/外发。",
        "> 2026-08-31 人工 GT 裁决已完成；本文件为裁决后存档（GT 终态 + 裁决记录）。",
        f"> 机器审计：{audit['case_count']} cases / {audit.get('adjudicated_case_count', '?')} adjudicated / "
        f"{audit_errors} error / {audit_warnings} warning / passed={audit['passed']}。",
        "> **禁止修改 GT 迁就系统输出。** 正式 dev rerun 须待 Gate 2 freeze 后进行。",
        "",
        "## 裁决汇总",
        "",
    ]
    case_payloads: list[tuple[dict, str]] = []
    decision_counts: dict[str, int] = {}
    for case_dir in CASE_DIRS:
        for path in sorted(case_dir.glob("*.json")):
            payload = json.loads(path.read_text())
            case_payloads.append((payload, str(path)))
    for payload, _ in case_payloads:
        _, decision, _ = parse_decision(payload.get("provenance", {}).get("notes"))
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
    lines.append(f"- Accept：{decision_counts.get('Accept', 0)}")
    lines.append(f"- Modify：{decision_counts.get('Modify', 0)}")
    lines.append("- Reject：0（无删除 case）")
    lines.append(f"- 未裁决：{decision_counts.get('NOT ADJUDICATED', 0)}")
    lines.append("")

    for payload, path in case_payloads:
        case_id = payload["case_id"]
        category = next(t.removeprefix("category:") for t in payload["suite_tags"] if t.startswith("category:"))
        decision_date, decision, decision_detail = parse_decision(payload.get("provenance", {}).get("notes"))
        lines.append("---")
        lines.append(f"## {case_id}  [{category}]  →  裁决：{decision}（{decision_date}，case v{payload['version']}）")
        if decision_detail:
            lines.append(f"- 修改内容：{decision_detail}")
        lines.append(f"- 文件：`{path}`")
        lines.append(f"- query：{payload['query']}")
        for finding in payload["reference_findings"]:
            completeness = finding["annotation_completeness"]
            method = finding["provenance"]["method"]
            lines.append(f"- `{finding['criterion']}` ({completeness})：{finding['expected_semantics']}")
            lines.append(f"  - 验证：{method}")
            for ev in finding["reference_evidence"]:
                message_id = ev["locator"]["internal_message_id"]
                row = connection.execute(
                    "SELECT sender_name, timestamp, content_text FROM messages WHERE internal_message_id = ?",
                    (message_id,),
                ).fetchone()
                if row is None:
                    lines.append(f"  - `{message_id}`：**DB 中不存在！**")
                    continue
                content = (row["content_text"] or "").replace("\n", " ⏎ ")
                excerpt = content[:EXCERPT_CHARS] + ("…" if len(content) > EXCERPT_CHARS else "")
                lines.append(f"  - `{message_id}` · {row['sender_name']}：{excerpt}")
        module_info = reach.get(case_id, {})
        if module_info:
            parts = [f"{key.split(':')[0]} MRR@10={value:.2f}" for key, value in sorted(module_info.items()) if key.endswith("mrr_at_k")]
            if parts:
                lines.append(f"- module 可达性（裁决前参考，非 GT 依据）：{'；'.join(parts)}")
        lines.append(f"- 判断要点：{payload['uncertainty_constraints']}")
        lines.append(f"- 负约束：{payload['negative_constraints']}")
        lines.append("")

    connection.close()
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(case_payloads)} cases)")
    print("decision counts:", decision_counts)


if __name__ == "__main__":
    main()
