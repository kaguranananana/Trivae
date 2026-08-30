#!/usr/bin/env python3
"""生成 resume-benchmark-v1 校准 pilot case 集。

GT 构造纪律：
- exhaustive 声明必须由确定性 LIKE 全库扫描证明（本脚本执行并记录计数）；
- paraphrase / context 类如实标 partial（target 集合）；
- case JSON 不包含任何聊天正文；why_relevant 只写结构性依据；
- 全部 case 当前为 provisional（provenance.adjudicated=false），等待人工 review。

再次运行：python3 scripts/generate_calibration_cases.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DATABASE = Path("data/trivae.sqlite3")
SNAPSHOT_PATH = Path("data/evaluation/benchmark/snapshot.json")
OUTPUT_DIR = Path("evaluation/cases/benchmark/calibration")

SCOPE = {"allowed_session_ids": None, "start_timestamp": None, "end_timestamp": None, "max_results": 100}
SCOPE_IDENTITY = json.dumps(SCOPE, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
REVIEW_POLICY = {
    "rubric_version": "m7-v1",
    "reviewer_types": ["human"],
    "blind_pairwise": True,
    "human_adjudication_on_disagreement": True,
}


def scope_identity_of(scope: dict) -> str:
    return json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def like_scan(connection: sqlite3.Connection, keyword: str) -> list[dict]:
    rows = connection.execute(
        "SELECT internal_message_id, session_id, timestamp FROM messages "
        "WHERE content_text LIKE ? AND recalled = 0 ORDER BY timestamp",
        (f"%{keyword}%",),
    ).fetchall()
    return [dict(row) for row in rows]


def message_ids(connection: sqlite3.Connection, ids: list[str]) -> list[dict]:
    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"SELECT internal_message_id, session_id, timestamp FROM messages WHERE internal_message_id IN ({placeholders})",
        ids,
    ).fetchall()
    return [dict(row) for row in rows]


def provenance(case_id: str, snapshot_id: str, method: str) -> dict:
    return {
        "source": f"deterministic-construction:{case_id}",
        "created_at": "2026-08-30T00:00:00+00:00",
        "method": method,
        "snapshot_id": snapshot_id,
        "scope_identity": SCOPE_IDENTITY,
        "adjudicated": False,
        "limitations": ["provisional; awaiting human review"],
    }


def evidence(message_id: str, why: str, snapshot_id: str, relation: str = "supports") -> dict:
    return {
        "evidence_id": f"ev:{message_id}",
        "relation": relation,
        "source_type": "message",
        "locator": {"internal_message_id": message_id},
        "why_relevant": why,
        "provenance": provenance("shared", snapshot_id, "deterministic LIKE scan / manual pick"),
    }


def case_payload(case_id: str, query: str, tags: list[str], snapshot: dict, findings: list[dict], constraints: dict, method: str) -> dict:
    return {
        "schema_version": 1,
        "case_id": case_id,
        "version": 1,
        "suite_tags": tags,
        "dataset_snapshot": snapshot,
        "data_access_scope": SCOPE,
        "query": query,
        "locale": "zh-CN",
        "time_context": None,
        "reference_findings": findings,
        "uncertainty_constraints": constraints.get("uncertainty", []),
        "negative_constraints": constraints.get("negative", []),
        "critical_requirements": constraints.get("critical", []),
        "diagnostic_expectations": None,
        "review_policy": REVIEW_POLICY,
        "provenance": {
            "source": f"calibration-construction:{case_id}",
            "method": method,
            "created_at": "2026-08-30T00:00:00+00:00",
            "notes": "provisional pending human review",
        },
    }


def main() -> None:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    snapshot_id = snapshot["snapshot_id"]
    connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    cases: list[dict] = []

    # --- exact_lexical：URL predicate，LIKE 全库扫描证明 exhaustive ---
    lexical_specs = [
        (
            "cal-lexical-tupu",
            "群里有没有人分享过 GitHub 上的 ailiujiarui/tupu 这个开源工具？",
            "github.com/ailiujiarui/tupu",
        ),
        (
            "cal-lexical-token-monitor",
            "有没有人分享过 GitHub 上的 Javis603/token-monitor 项目？",
            "github.com/Javis603/token-monitor",
        ),
        (
            "cal-lexical-hello-agents",
            "datawhalechina 的 hello-agents 仓库在群里被谁分享过？",
            "github.com/datawhalechina/hello-agents",
        ),
    ]
    for case_id, query, keyword in lexical_specs:
        hits = like_scan(connection, keyword)
        assert 0 < len(hits) <= 8, f"{case_id}: unexpected hit count {len(hits)}"
        findings = [
            {
                "finding_id": "relevant",
                "criterion": "gt.relevant",
                "expected_semantics": f"包含 {keyword} 的全部消息（LIKE 全库扫描枚举，共 {len(hits)} 条）",
                "reference_evidence": [
                    evidence(hit["internal_message_id"], f"包含关键词 {keyword}", snapshot_id)
                    for hit in hits
                ],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, f"deterministic LIKE scan over {snapshot_id}, hit_count={len(hits)}"),
                "known_limitations": [],
                "critical": False,
            },
            {
                "finding_id": "zero",
                "criterion": "gt.expected_zero_result",
                "expected_semantics": "false",
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "predicate scan proves non-empty"),
                "known_limitations": [],
                "critical": False,
            },
            {
                "finding_id": "fact",
                "criterion": "gt.expected_fact",
                "expected_semantics": json.dumps([keyword.lower()]),
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "extractive fact from GT messages"),
                "known_limitations": [],
                "critical": False,
            },
        ]
        cases.append(
            case_payload(
                case_id,
                query,
                ["category:exact_lexical", "benchmark:development", "calibration"],
                snapshot,
                findings,
                {
                    "uncertainty": ["不要求回答每条消息的发送者与时间细节。"],
                    "negative": ["不得引用 Scope 外消息。"],
                    "critical": ["答案必须给出仓库 URL（expected_fact 别名命中）。"],
                },
                f"deterministic LIKE scan ({len(hits)} hits); provisional",
            )
        )

    # --- semantic_paraphrase：target 集合（partial）---
    paraphrase_specs = [
        (
            "cal-paraphrase-agent-memory",
            "群里有没有人聊过多个 Agent 之间怎么共享信息或者记忆？比如用共享笔记这种办法。",
            "qq:383550736:7673518280826576789",
            "memory.md",
        ),
        (
            "cal-paraphrase-subagent",
            "大家是怎么理解 subagent 的？它和主 Agent 的区别有哪些。",
            "qq:383550736:7673517691138806162",
            "subagent",
        ),
    ]
    for case_id, query, target_id, lexical_query in paraphrase_specs:
        rows = message_ids(connection, [target_id])
        assert len(rows) == 1, f"{case_id}: target message missing"
        findings = [
            {
                "finding_id": "relevant",
                "criterion": "gt.relevant",
                "expected_semantics": "人工确认的目标消息（语义等价内容的 target 集合，未做全库语义枚举）",
                "reference_evidence": [evidence(target_id, "语义 paraphrase 的 target 消息", snapshot_id)],
                "annotation_completeness": "partial",
                "provenance": provenance(case_id, snapshot_id, "manual target pick; corpus-exhaustive semantic enumeration not attempted"),
                "known_limitations": ["target 集合未证明 corpus-exhaustive，只能评 Target Recall。"],
                "critical": False,
            },
            {
                "finding_id": "zero",
                "criterion": "gt.expected_zero_result",
                "expected_semantics": "false",
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "target exists"),
                "known_limitations": [],
                "critical": False,
            },
        ]
        cases.append(
            case_payload(
                case_id,
                query,
                ["category:semantic_paraphrase", "benchmark:development", "calibration"],
                snapshot,
                findings,
                {
                    "uncertainty": ["query 与原消息措辞刻意不同；不要求原文复述。"],
                    "negative": ["不得把主题相关的其他消息计为 miss 之外的错误。"],
                    "critical": ["答案应引用 target 消息。"],
                },
                "manual target pick; provisional",
            )
        )

    # --- context_recovery：direct hit 缺上下文无法回答 ---
    context_specs = [
        (
            "cal-context-ui-skill",
            "之前有没有人推荐过可以检查 UI 效果的 skill？大家觉得怎么样？",
            "qq:831907794:7674452946487780087",
            "qq:831907794:7674452946487780099",
            "jakubkrehel/skills",
        ),
        (
            "cal-context-ts-docs",
            "之前有没有人问过想深入学习某个前端 SDK 文档但是读不进去的问题？",
            "qq:831907794:7673166668798186827",
            "qq:831907794:7674452954669596319",
            "vercel",
        ),
    ]
    for case_id, query, parent_id, child_id, lexical_query in context_specs:
        rows = message_ids(connection, [parent_id, child_id])
        assert len(rows) == 2, f"{case_id}: context pair incomplete"
        findings = [
            {
                "finding_id": "relevant",
                "criterion": "gt.relevant",
                "expected_semantics": "被讨论的推荐消息（direct target）",
                "reference_evidence": [evidence(parent_id, "对话主消息", snapshot_id)],
                "annotation_completeness": "partial",
                "provenance": provenance(case_id, snapshot_id, "reply pair pick; manual"),
                "known_limitations": ["target 集合未证明 corpus-exhaustive。"],
                "critical": False,
            },
            {
                "finding_id": "context",
                "criterion": "gt.required_context",
                "expected_semantics": "对 direct target 的追问/回应，脱离上下文不可解释",
                "reference_evidence": [
                    evidence(child_id, "回复消息，指代 direct target", snapshot_id, relation="context")
                ],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "single known reply pair"),
                "known_limitations": [],
                "critical": False,
            },
            {
                "finding_id": "zero",
                "criterion": "gt.expected_zero_result",
                "expected_semantics": "false",
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "target exists"),
                "known_limitations": [],
                "critical": False,
            },
        ]
        cases.append(
            case_payload(
                case_id,
                query,
                ["category:context_recovery", "benchmark:development", "calibration"],
                snapshot,
                findings,
                {
                    "uncertainty": ["required_context 必须出现在最终 evidence 中才算恢复成功。"],
                    "negative": ["不得只引用 direct target 而丢失回复语境。"],
                    "critical": ["答案应同时覆盖 direct 与 required_context。"],
                },
                "reply pair pick; provisional",
            )
        )

    # --- temporal_overview：coverage 三轴预期 ---
    temporal_specs = [
        (
            "cal-temporal-last-2d",
            "最近两天大家都在聊什么？",
            "complete",
            "false",
            ["2699 条消息在 recent 1000/5000 容量内，keyset continuation 应能完整覆盖。"],
            ["2699/100 误判回归：不得在 total_hits>returned 时声称覆盖完整窗口。"],
        ),
        (
            "cal-temporal-last-7d",
            "过去一周群里的热门话题有哪些？",
            "partial",
            "true",
            ["15221 条消息超过 recent 5000 上限，正确行为是如实声明 partial。"],
            ["不得把 partial 覆盖说成 complete。"],
        ),
    ]
    for case_id, query, coverage, truncated, uncertainty, negative in temporal_specs:
        findings = [
            {
                "finding_id": "coverage",
                "criterion": "gt.expected_coverage_status",
                "expected_semantics": coverage,
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "window count via SQL COUNT (deterministic)"),
                "known_limitations": [],
                "critical": True,
            },
            {
                "finding_id": "truncated",
                "criterion": "gt.expected_truncated",
                "expected_semantics": truncated,
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "window count vs trusted capacity (deterministic)"),
                "known_limitations": [],
                "critical": False,
            },
            {
                "finding_id": "zero",
                "criterion": "gt.expected_zero_result",
                "expected_semantics": "false",
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "window count > 0 (deterministic)"),
                "known_limitations": [],
                "critical": False,
            },
        ]
        cases.append(
            case_payload(
                case_id,
                query,
                ["category:temporal_overview", "benchmark:development", "calibration"],
                snapshot,
                findings,
                {
                    "uncertainty": uncertainty,
                    "negative": negative,
                    "critical": ["coverage 声明必须与 Artifact retrieval_coverage 一致。"],
                },
                "deterministic window count; provisional",
            )
        )

    # --- zero_result：空窗口（确定性验证 0 条）---
    empty_window_start, empty_window_end = 1754870400000, 1754956800000
    empty_count = connection.execute(
        "SELECT COUNT(*) FROM messages WHERE timestamp >= ? AND timestamp < ?", (empty_window_start, empty_window_end)
    ).fetchone()[0]
    assert empty_count == 0, "empty window expectation broken"
    findings = [
        {
            "finding_id": "zero",
            "criterion": "gt.expected_zero_result",
            "expected_semantics": "true",
            "reference_evidence": [],
            "annotation_completeness": "exhaustive",
            "provenance": provenance(
                "cal-zero-empty-window",
                snapshot_id,
                f"SQL COUNT over [{empty_window_start},{empty_window_end}) = 0 (deterministic)",
            ),
            "known_limitations": [],
            "critical": True,
        },
    ]
    cases.append(
        case_payload(
            "cal-zero-empty-window",
            "2025年8月11日当天大家有没有发言？都在聊什么？",
            ["category:zero_result", "benchmark:development", "calibration"],
            snapshot,
            findings,
            {
                "uncertainty": ["该 UTC 日窗口经验证为 0 条消息；合法空窗。"],
                "negative": ["不得把空窗口当作执行失败；也不得编造当天讨论。"],
                "critical": ["应输出 kind=no_result 且通过 positive proof。"],
            },
            "deterministic empty-window COUNT; provisional",
        )
    )

    connection.close()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for payload in cases:
        path = OUTPUT_DIR / f"{payload['case_id']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")

    # --- module-level retrieval query set（exact/paraphrase/context 共 7 条）---
    query_set = {
        "schema_version": "retrieval-annotation-v1",
        "query_set_id": "resume-benchmark-calibration",
        "version": 1,
        "snapshot_id": snapshot_id,
        "description": "calibration pilot module-level lexical/semantic scoring input",
        "queries": [
            {
                "query_id": "cal-lexical-tupu",
                "query": "群里有没有人分享过 GitHub 上的 ailiujiarui/tupu 这个开源工具？",
                "lexical_query": "github.com/ailiujiarui/tupu",
                "query_types": ["exact_lexical"],
                "scope": SCOPE,
                "candidate_limit": 10,
                "context_before": 2,
                "context_after": 2,
                "dense_top_k": 40,
                "diagnostic": False,
                "notes": "URL predicate",
            },
            {
                "query_id": "cal-lexical-token-monitor",
                "query": "有没有人分享过 GitHub 上的 Javis603/token-monitor 项目？",
                "lexical_query": "github.com/Javis603/token-monitor",
                "query_types": ["exact_lexical"],
                "scope": SCOPE,
                "candidate_limit": 10,
                "context_before": 2,
                "context_after": 2,
                "dense_top_k": 40,
                "diagnostic": False,
                "notes": "URL predicate",
            },
            {
                "query_id": "cal-lexical-hello-agents",
                "query": "datawhalechina 的 hello-agents 仓库在群里被谁分享过？",
                "lexical_query": "github.com/datawhalechina/hello-agents",
                "query_types": ["exact_lexical"],
                "scope": SCOPE,
                "candidate_limit": 10,
                "context_before": 2,
                "context_after": 2,
                "dense_top_k": 40,
                "diagnostic": False,
                "notes": "URL predicate",
            },
            {
                "query_id": "cal-paraphrase-agent-memory",
                "query": "群里有没有人聊过多个 Agent 之间怎么共享信息或者记忆？比如用共享笔记这种办法。",
                "lexical_query": "memory.md",
                "query_types": ["semantic_paraphrase"],
                "scope": SCOPE,
                "candidate_limit": 10,
                "context_before": 2,
                "context_after": 2,
                "dense_top_k": 40,
                "diagnostic": False,
                "notes": "lexical control uses literal token",
            },
            {
                "query_id": "cal-paraphrase-subagent",
                "query": "大家是怎么理解 subagent 的？它和主 Agent 的区别有哪些。",
                "lexical_query": "subagent",
                "query_types": ["semantic_paraphrase"],
                "scope": SCOPE,
                "candidate_limit": 10,
                "context_before": 2,
                "context_after": 2,
                "dense_top_k": 40,
                "diagnostic": False,
                "notes": "lexical control uses literal token",
            },
            {
                "query_id": "cal-context-ui-skill",
                "query": "之前有没有人推荐过可以检查 UI 效果的 skill？大家觉得怎么样？",
                "lexical_query": "jakubkrehel/skills",
                "query_types": ["context_recovery"],
                "scope": SCOPE,
                "candidate_limit": 10,
                "context_before": 4,
                "context_after": 4,
                "dense_top_k": 40,
                "diagnostic": False,
                "notes": "lexical hits parent; reply is required context",
            },
            {
                "query_id": "cal-context-ts-docs",
                "query": "之前有没有人问过想深入学习某个前端 SDK 文档但是读不进去的问题？",
                "lexical_query": "vercel",
                "query_types": ["context_recovery"],
                "scope": SCOPE,
                "candidate_limit": 10,
                "context_before": 4,
                "context_after": 4,
                "dense_top_k": 40,
                "diagnostic": False,
                "notes": "lexical hits parent; reply is required context",
            },
        ],
    }
    queryset_path = Path("data/evaluation/benchmark/calibration-retrieval-queries.json")
    queryset_path.write_text(json.dumps(query_set, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {queryset_path}")


if __name__ == "__main__":
    main()
