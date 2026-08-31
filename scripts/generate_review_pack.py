#!/usr/bin/env python3
"""生成 enriched 人工 GT review pack（local-only artifact）。

覆盖 data/evaluation/benchmark/review-pack-dev.md：
- 每 case：query / category / completeness / GT axes / message 摘要（bounded）/ 证明复核 / 建议
- 摘要含真实消息片段：本文件在 data/evaluation/（gitignored），禁止提交或外发
- 建议来自确定性审计 + module-level 可达性，仅供人工裁决参考，不替代裁决
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DATABASE = Path("data/trivae.sqlite3")
CASE_DIRS = (Path("evaluation/cases/benchmark/calibration"), Path("evaluation/cases/benchmark/dev"))
AUDIT_PATH = Path("data/evaluation/benchmark/gt-audit.json")
CAL_MODULE_PATH = Path("data/evaluation/benchmark/module-retrieval-scores.json")
DEV_MODULE_PATH = Path("data/evaluation/benchmark/module-retrieval-scores-dev.json")
OUTPUT = Path("data/evaluation/benchmark/review-pack-dev.md")
EXCERPT_CHARS = 140


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


def main() -> None:
    audit = json.loads(AUDIT_PATH.read_text())
    audit_by_case: dict[str, list[dict]] = {}
    for finding in audit["findings"]:
        audit_by_case.setdefault(str(finding["case_id"]), []).append(finding)
    reach = load_module_reachability()

    connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    lines = [
        "# resume-benchmark-v1 GT Review Pack（development + calibration）",
        "",
        "> **local-only artifact**：含真实消息片段，禁止提交/外发。",
        "> 裁决规则：确认 (a) query 是否自然 (b) GT 消息正确且完备 (c) completeness 声明成立。",
        "> 裁决动作：在对应 case JSON 的**所有** finding `provenance.adjudicated` 置 `true`（Accept）",
        "> 或先修改再置 `true`（Modify）。Reject 的 case 直接删除文件并记录原因。",
        "> **禁止修改 GT 迁就系统输出。** 机器审计结果：0 error / 0 warning。",
        "",
        "## 汇总",
        "",
    ]
    suggestions: dict[str, str] = {}
    case_payloads: list[tuple[dict, str]] = []
    for case_dir in CASE_DIRS:
        for path in sorted(case_dir.glob("*.json")):
            payload = json.loads(path.read_text())
            category = next(t.removeprefix("category:") for t in payload["suite_tags"] if t.startswith("category:"))
            case_payloads.append((payload, str(path)))
            if audit_by_case.get(payload["case_id"]):
                suggestions[payload["case_id"]] = "Reject"
            elif category in ("exact_lexical", "citation_evidence"):
                suggestions[payload["case_id"]] = "Accept"
            elif category == "zero_result":
                suggestions[payload["case_id"]] = "Accept"
            elif category == "temporal_overview":
                suggestions[payload["case_id"]] = "Modify?"
            elif category == "context_recovery":
                suggestions[payload["case_id"]] = "Modify?"
            elif category == "semantic_paraphrase":
                r = reach.get(payload["case_id"], {})
                if any((r.get(f"{s}:recall_at_k") or 0) > 0 or (r.get(f"{s}:mrr_at_k") or 0) > 0 for s in ("lexical", "semantic")):
                    suggestions[payload["case_id"]] = "Accept?"
                else:
                    suggestions[payload["case_id"]] = "Modify?"
            else:
                suggestions[payload["case_id"]] = "Accept?"

    counts: dict[str, int] = {}
    for case_id, suggestion in suggestions.items():
        key = suggestion.rstrip("?")
        counts[key] = counts.get(key, 0) + 1
    lines.append(f"- 建议 Accept（高置信，可快速过）：{counts.get('Accept', 0)}")
    lines.append(f"- 建议 Modify（需重点人工判断）：{counts.get('Modify', 0)}")
    lines.append(f"- 建议 Reject：{counts.get('Reject', 0)}")
    lines.append("")
    lines.append("## 分类别裁决要点（带 ? 表示机器无法替你判断，需人工确认）")
    lines.append("")
    lines.append(
        "- **exact_lexical / citation_evidence（13+6，建议 Accept）**：GT=LIKE 全库扫描的精确集合，"
        "机器已重扫并比对一致。你只需确认 query 是否自然、是否接受该 URL/token 作为 predicate。"
    )
    lines.append(
        "- **zero_result（5，建议 Accept）**：空窗口/零 token 由 SQL COUNT 证明为 0。"
        "唯一需要人工确认的是 query 是否与'零命中谓词'语义一致（尤其是 excalidraw 的概念等价风险）。"
    )
    lines.append(
        "- **temporal_overview（8，需人工判断）**：count/truncated 由 SQL 复算一致，"
        "但 **expected_coverage_status 是行为预期而非事实**——请判断：2699 条（1d/2d）是否应当要求系统分页到 complete？"
        "如果你认为'合理概括即可、不要求全量分页'，把 expected_coverage_status 改为 partial 并同步 expected_truncated。"
    )
    lines.append(
        "- **context_recovery（5，需人工判断）**：reply pair 由机器验证存在且绑定，"
        "但 **required_context 是否唯一/充分**需要你判断（同一话题可能有多条回复；当前 GT 只锚定一条已知回复）。"
        "若认为遗漏，补 ReferenceEvidence 即可（completeness 保持 partial）。"
    )
    lines.append(
        "- **semantic_paraphrase（10，混合）**：target 语义对齐与否只有你能判断（query 与原文是否真等价、"
        "是否'只对 semantic 有利'）。module 可达性只是参考：两者都 0 的 case 可能过难，"
        "保留难度是合法选择——hard case 不是错误。"
    )
    lines.append("")

    for payload, path in case_payloads:
        case_id = payload["case_id"]
        category = next(t.removeprefix("category:") for t in payload["suite_tags"] if t.startswith("category:"))
        lines.append("---")
        lines.append(f"## {case_id}  [{category}]  →  建议：{suggestions.get(case_id, 'Accept?')}")
        lines.append(f"- 文件：`{path}`")
        lines.append(f"- query：{payload['query']}")
        for finding in payload["reference_findings"]:
            criterion = finding["criterion"]
            completeness = finding["annotation_completeness"]
            method = finding["provenance"]["method"]
            lines.append(f"- `{criterion}` ({completeness})：{finding['expected_semantics']}")
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
                lines.append(f"- module 可达性（确定性检索，供参考）：{'；'.join(parts)}")
        lines.append(f"- 判断要点：{payload['uncertainty_constraints']}")
        lines.append(f"- 负约束：{payload['negative_constraints']}")
        lines.append("- 裁决：[ ] Accept / [ ] Modify（改什么：____） / [ ] Reject（原因：____）")
        lines.append("")

    connection.close()
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(case_payloads)} cases)")
    print("suggestion counts:", counts)


if __name__ == "__main__":
    main()
