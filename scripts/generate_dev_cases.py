#!/usr/bin/env python3
"""生成 resume-benchmark-v1 development case 池（约 37 case，六类覆盖）。

构造纪律与校准集一致：
- exhaustive 声明必须由确定性 LIKE 全库扫描证明；
- paraphrase / context / temporal 归因类如实声明完备度；
- case JSON 不含聊天正文；why_relevant 只写结构性依据；
- 全部 case 为 provisional（adjudicated=false），等待人工 review；
- 同步生成 review pack（Markdown）供逐条裁决，以及 module-level retrieval query set。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DATABASE = Path("data/trivae.sqlite3")
SNAPSHOT_PATH = Path("data/evaluation/benchmark/snapshot.json")
OUTPUT_DIR = Path("evaluation/cases/benchmark/dev")
QUERYSET_PATH = Path("data/evaluation/benchmark/dev-retrieval-queries.json")
REVIEW_PACK_PATH = Path("data/evaluation/benchmark/review-pack-dev.md")

SCOPE = {"allowed_session_ids": None, "start_timestamp": None, "end_timestamp": None, "max_results": 100}
SCOPE_IDENTITY = json.dumps(SCOPE, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
REVIEW_POLICY = {
    "rubric_version": "m7-v1",
    "reviewer_types": ["human"],
    "blind_pairwise": True,
    "human_adjudication_on_disagreement": True,
}
DAY = 24 * 60 * 60 * 1000


def like_scan(connection: sqlite3.Connection, keyword: str) -> list[dict]:
    rows = connection.execute(
        "SELECT internal_message_id, timestamp FROM messages WHERE content_text LIKE ? AND recalled = 0 ORDER BY timestamp",
        (f"%{keyword}%",),
    ).fetchall()
    return [dict(row) for row in rows]


def message_ids(connection: sqlite3.Connection, ids: list[str]) -> list[dict]:
    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"SELECT internal_message_id, timestamp FROM messages WHERE internal_message_id IN ({placeholders})", ids
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
            "source": f"dev-construction:{case_id}",
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
    retrieval_queries: list[dict] = []

    def zero_false_finding(case_id: str, method: str) -> dict:
        return {
            "finding_id": "zero",
            "criterion": "gt.expected_zero_result",
            "expected_semantics": "false",
            "reference_evidence": [],
            "annotation_completeness": "exhaustive",
            "provenance": provenance(case_id, snapshot_id, method),
            "known_limitations": [],
            "critical": False,
        }

    def relevant_finding(case_id: str, hits: list[dict], keyword: str, completeness: str, method: str) -> dict:
        return {
            "finding_id": "relevant",
            "criterion": "gt.relevant",
            "expected_semantics": f"包含 {keyword} 的消息（LIKE 全库扫描枚举，共 {len(hits)} 条）",
            "reference_evidence": [evidence(hit["internal_message_id"], f"包含关键词 {keyword}", snapshot_id) for hit in hits],
            "annotation_completeness": completeness,
            "provenance": provenance(case_id, snapshot_id, f"{method}; hit_count={len(hits)}"),
            "known_limitations": [] if completeness == "exhaustive" else ["target 集合未证明 corpus-exhaustive。"],
            "critical": False,
        }

    # --- exact_lexical（10，exhaustive）---
    lexical_specs = [
        ("dev-lexical-nanobot-wiki", "yu-xin-c/nanobot-llm-wiki", "有没有人给 nanobot 做过知识库插件？分享过仓库吗？"),
        ("dev-lexical-resume-miner", "auberginewly/resume-project-miner", "有没有人分享过能把项目经历整理到简历上的工具？"),
        ("dev-lexical-agentic-zh", "WenyuChiou/awesome-agentic-ai-zh", "群里有没有人分享过中文的 Agentic AI 资源合集仓库？"),
        ("dev-lexical-zenith", "WuMingDao/zenith-image-generator", "zenith-image-generator 这个图片生成项目谁分享过？"),
        ("dev-lexical-vibe-game", "asashiki/vibe-game", "想了解 AI 做游戏，群里有人推荐过相关仓库吗？"),
        ("dev-lexical-siclaw", "scitix/siclaw", "scitix 的 siclaw 项目是谁在群里求 star 的？"),
        ("dev-lexical-deepseek-harness", "deepseek-ai/deepseek-harness", "deepseek 官方的 harness 仓库在群里被分享过吗？"),
        ("dev-lexical-forge", "AnHuoZhe/forge", "有没有人分享过一个把需求拆成任务并生成文档的 agent 项目 forge？"),
        ("dev-lexical-mcp-switch", "asashiki/mcp-switch", "有没有人分享过统一管理 MCP 的工具？"),
        ("dev-lexical-chatlog-alpha", "teest114514/chatlog_alpha", "chatlog_alpha 这个聊天记录相关的仓库谁分享过？"),
    ]
    for case_id, keyword, query in lexical_specs:
        hits = like_scan(connection, keyword)
        assert 2 <= len(hits) <= 8, f"{case_id}: unexpected hit count {len(hits)}"
        findings = [
            relevant_finding(case_id, hits, keyword, "exhaustive", "deterministic LIKE scan"),
            zero_false_finding(case_id, "predicate scan proves non-empty"),
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
                ["category:exact_lexical", "benchmark:development"],
                snapshot,
                findings,
                {
                    "uncertainty": ["不要求罗列每条消息的发送者与时间。"],
                    "negative": ["不得引用 Scope 外消息。"],
                    "critical": ["答案必须给出仓库 URL（expected_fact 别名命中）。"],
                },
                f"deterministic LIKE scan ({len(hits)} hits); provisional",
            )
        )
        retrieval_queries.append(_query_entry(case_id, query, keyword, "exact_lexical"))

    # --- citation_evidence（6，exhaustive + expected_fact）---
    citation_specs = [
        ("dev-cite-nanobot", "nanobot-llm-wiki", "nanobot 的 llm-wiki 知识库插件是给谁/什么项目做的？群里怎么介绍的？"),
        ("dev-cite-archify", "tt-a1i/archify", "archify 项目最近发展怎么样？star 数有被提到过吗？"),
        ("dev-cite-volcengine", "volcengine/volcengine-python-sdk", "volcengine 的 python sdk 相关 issue 有没有人在群里发过？"),
        ("dev-cite-meimei", "87789771/meimei-nestjs-admin", "有没有人分享过 Java/NestJS 方向的管理后台模板或学习资源？"),
        ("dev-cite-lofisu", "LofiSu/LofiSu", "LofiSu 这个仓库里的 offer.md 被谁分享过？聊了什么？"),
        ("dev-cite-comment-render", "ifeichuan/CommentMarkdownRender", "CommentMarkdownRender 这个项目是谁分享的？用途是什么？"),
    ]
    for case_id, keyword, query in citation_specs:
        hits = like_scan(connection, keyword)
        assert 2 <= len(hits) <= 8, f"{case_id}: unexpected hit count {len(hits)}"
        findings = [
            relevant_finding(case_id, hits, keyword, "exhaustive", "deterministic LIKE scan"),
            zero_false_finding(case_id, "predicate scan proves non-empty"),
            {
                "finding_id": "fact",
                "criterion": "gt.expected_fact",
                "expected_semantics": json.dumps([keyword.lower()]),
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "extractive fact; citation required"),
                "known_limitations": [],
                "critical": True,
            },
        ]
        cases.append(
            case_payload(
                case_id,
                query,
                ["category:citation_evidence", "benchmark:development"],
                snapshot,
                findings,
                {
                    "uncertainty": ["期望答案明确引用来源消息。"],
                    "negative": ["不得无 citation 输出事实 claim。"],
                    "critical": ["每个事实 claim 至少一个可解析 source handle。"],
                },
                f"deterministic LIKE scan ({len(hits)} hits); provisional",
            )
        )
        retrieval_queries.append(_query_entry(case_id, query, keyword, "citation_evidence"))

    # --- semantic_paraphrase（8，partial target）---
    paraphrase_specs = [
        ("dev-para-job-anxiety", "qq:383550736:7673532419201245493", "快到招聘季了心里很慌、准备方向很散，群里有人有同样的状态吗？", "投递"),
        ("dev-para-resume-advice", "qq:750807478:7672997189707493185", "简历上没有亮眼数据怎么办？有人给过建议吗？", "简历"),
        ("dev-para-ts-learning", "qq:831907794:7672993271365395321", "有没有人分享过跟着视频项目入门全栈的学习路子？", "全栈"),
        ("dev-para-intern-hard-part", "qq:750807478:7672077881178122777", "有人聊过实习里最难的部分是什么吗？", "实习"),
        ("dev-para-ai-interest", "qq:831907794:7674452964454943926", "有没有人坦白过自己对 AI 这个方向其实提不起兴趣、只是为了谋生？", "实习"),
        ("dev-para-written-test", "qq:831907794:7671498185377818633", "有人遇到过笔试需要自己构造测试数据的情况吗？", "笔试"),
        ("dev-para-webnovel", "qq:677019167:7673445910938235654", "有没有人聊过写网文赚钱为什么不划算？", "短篇"),
        ("dev-para-intern-owner", "qq:1040412855:7673849331665371920", "群里怎么看待让实习生一个人从头负责一个内部项目？", "owner"),
    ]
    for case_id, target_id, query, lexical_query in paraphrase_specs:
        rows = message_ids(connection, [target_id])
        assert len(rows) == 1, f"{case_id}: target message missing"
        findings = [
            {
                "finding_id": "relevant",
                "criterion": "gt.relevant",
                "expected_semantics": "人工确认的目标消息（语义等价 target，未做全库语义枚举）",
                "reference_evidence": [evidence(target_id, "语义 paraphrase 的 target 消息", snapshot_id)],
                "annotation_completeness": "partial",
                "provenance": provenance(case_id, snapshot_id, "manual target pick"),
                "known_limitations": ["target 集合未证明 corpus-exhaustive，只能评 Target Recall。"],
                "critical": False,
            },
            zero_false_finding(case_id, "target exists"),
        ]
        cases.append(
            case_payload(
                case_id,
                query,
                ["category:semantic_paraphrase", "benchmark:development"],
                snapshot,
                findings,
                {
                    "uncertainty": ["query 与原消息措辞刻意不同。"],
                    "negative": ["不得把主题相关的其他消息算作错误。"],
                    "critical": ["答案应引用 target 消息。"],
                },
                "manual target pick; provisional",
            )
        )
        retrieval_queries.append(_query_entry(case_id, query, lexical_query, "semantic_paraphrase"))

    # --- context_recovery（3，reply 对）---
    context_specs = [
        (
            "dev-context-mattpocock-1",
            "有没有人推荐过可以直接下载来用的 skill 仓库？怎么使用？",
            "qq:677019167:7664449865363143940",
            "qq:677019167:7664449865363143925",
            "mattpocock/skills",
        ),
        (
            "dev-context-mattpocock-2",
            "mattpocock 的 skills 仓库用起来怎么样？有反馈吗？",
            "qq:677019167:7666849111367864709",
            "qq:677019167:7666849111367864725",
            "mattpocock/skills",
        ),
        (
            "dev-context-archify",
            "archify 这个工具有人用过吗？反馈如何？",
            "qq:1039179741:7665652181386089161",
            "qq:1039179741:7665654465962176057",
            "tt-a1i/archify",
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
                "reference_evidence": [evidence(child_id, "回复消息，指代 direct target", snapshot_id, relation="context")],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, "single known reply pair"),
                "known_limitations": [],
                "critical": False,
            },
            zero_false_finding(case_id, "target exists"),
        ]
        cases.append(
            case_payload(
                case_id,
                query,
                ["category:context_recovery", "benchmark:development"],
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
        retrieval_queries.append(_query_entry(case_id, query, lexical_query, "context_recovery", context=4))

    # --- temporal_overview（6，coverage 三轴）---
    latest = connection.execute("SELECT MAX(timestamp) FROM messages").fetchone()[0]
    temporal_specs = [
        ("dev-temporal-1d", "昨天大家都聊了些什么？", 1, "complete", "false"),
        ("dev-temporal-2d", "最近两天大家都在聊什么？", 2, "complete", "false"),
        ("dev-temporal-3d", "最近三天群里的热门话题有哪些？", 3, "partial", "true"),
        ("dev-temporal-7d", "过去一周有哪些值得关注的讨论？", 7, "partial", "true"),
        ("dev-temporal-14d", "最近两周大家主要在聊什么方向的内容？", 14, "partial", "true"),
        ("dev-temporal-30d", "过去一个月群里的主要话题有哪些？", 30, "partial", "true"),
    ]
    for case_id, query, days, coverage, truncated in temporal_specs:
        count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE timestamp > ? AND timestamp <= ?",
            (latest - days * DAY, latest + 1),
        ).fetchone()[0]
        if coverage == "complete":
            assert count <= 5000, f"{case_id}: window {count} exceeds trusted capacity"
        else:
            assert count > 5000, f"{case_id}: window {count} within capacity; partial expectation invalid"
        findings = [
            {
                "finding_id": "coverage",
                "criterion": "gt.expected_coverage_status",
                "expected_semantics": coverage,
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, f"SQL COUNT over last {days}d = {count} (deterministic)"),
                "known_limitations": [],
                "critical": True,
            },
            {
                "finding_id": "truncated",
                "criterion": "gt.expected_truncated",
                "expected_semantics": truncated,
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, f"window count {count} vs trusted capacity (deterministic)"),
                "known_limitations": [],
                "critical": False,
            },
            zero_false_finding(case_id, f"window count {count} > 0 (deterministic)"),
        ]
        cases.append(
            case_payload(
                case_id,
                query,
                ["category:temporal_overview", "benchmark:development"],
                snapshot,
                findings,
                {
                    "uncertainty": [f"窗口实测 {count} 条消息；coverage/truncated 预期由容量决定。"],
                    "negative": ["不得把 partial 覆盖说成 complete。"],
                    "critical": ["coverage 声明必须与 Artifact retrieval_coverage 一致。"],
                },
                f"deterministic window count ({count}); provisional",
            )
        )

    # --- zero_result（4，空窗口 ×3 + 稀有 token ×1）---
    import datetime

    for index, day_str in enumerate(("2025-08-11", "2025-08-23", "2025-08-26")):
        case_id = f"dev-zero-empty-{index + 1}"
        start = int(datetime.datetime.fromisoformat(day_str).replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
        end = start + DAY
        count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE timestamp >= ? AND timestamp < ?", (start, end)
        ).fetchone()[0]
        assert count == 0, f"{case_id}: window not empty ({count})"
        findings = [
            {
                "finding_id": "zero",
                "criterion": "gt.expected_zero_result",
                "expected_semantics": "true",
                "reference_evidence": [],
                "annotation_completeness": "exhaustive",
                "provenance": provenance(case_id, snapshot_id, f"SQL COUNT over {day_str} UTC = 0 (deterministic)"),
                "known_limitations": [],
                "critical": True,
            },
        ]
        cases.append(
            case_payload(
                case_id,
                f"{day_str}这天大家有没有发言？都在聊什么？",
                ["category:zero_result", "benchmark:development"],
                snapshot,
                findings,
                {
                    "uncertainty": [f"{day_str} UTC 窗口经验证为 0 条消息；合法空窗。"],
                    "negative": ["不得把空窗口当执行失败；也不得编造当天讨论。"],
                    "critical": ["应输出 kind=no_result 且通过 positive proof。"],
                },
                "deterministic empty-window COUNT; provisional",
            )
        )

    keyword = "excalidraw"
    count = connection.execute(
        "SELECT COUNT(*) FROM messages WHERE content_text LIKE ? AND recalled=0", (f"%{keyword}%",)
    ).fetchone()[0]
    assert count == 0, "excalidraw expectation broken"
    cases.append(
        case_payload(
            "dev-zero-excalidraw",
            "群里有没有人分享或讨论过 excalidraw 这类画图工具？",
            ["category:zero_result", "benchmark:development"],
            snapshot,
            [
                {
                    "finding_id": "zero",
                    "criterion": "gt.expected_zero_result",
                    "expected_semantics": "true",
                    "reference_evidence": [],
                    "annotation_completeness": "exhaustive",
                    "provenance": provenance("dev-zero-excalidraw", snapshot_id, "LIKE scan for token = 0 (deterministic)"),
                    "known_limitations": ["概念等价但不同措辞的资源分享理论上存在；以 token 级零命中为准。"],
                    "critical": True,
                },
            ],
            {
                "uncertainty": ["关键 token 全库 0 命中。"],
                "negative": ["不得编造不存在的讨论。"],
                "critical": ["应输出 kind=no_result 且通过 positive proof。"],
            },
            "deterministic zero-token LIKE scan; provisional",
        )
    )

    connection.close()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for payload in cases:
        path = OUTPUT_DIR / f"{payload['case_id']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} dev cases to {OUTPUT_DIR}")

    QUERYSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    query_set = {
        "schema_version": "retrieval-annotation-v1",
        "query_set_id": "resume-benchmark-dev",
        "version": 1,
        "snapshot_id": snapshot_id,
        "description": "dev pool module-level lexical/semantic scoring input",
        "queries": retrieval_queries,
    }
    QUERYSET_PATH.write_text(json.dumps(query_set, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {QUERYSET_PATH} ({len(retrieval_queries)} queries)")

    _write_review_pack(cases, REVIEW_PACK_PATH)
    print(f"wrote {REVIEW_PACK_PATH}")


def _query_entry(case_id: str, query: str, lexical_query: str, category: str, context: int = 2) -> dict:
    return {
        "query_id": case_id,
        "query": query,
        "lexical_query": lexical_query,
        "query_types": [category],
        "scope": SCOPE,
        "candidate_limit": 10,
        "context_before": context,
        "context_after": context,
        "dense_top_k": 40,
        "diagnostic": False,
        "notes": category,
    }


def _write_review_pack(cases: list[dict], path: Path) -> None:
    """生成人工 review pack：每个 case 的 query/GT/验证方式 + 裁决槽。"""

    lines = [
        "# resume-benchmark-v1 Development GT Review Pack",
        "",
        "裁决规则：对每个 case 确认 (a) query 是否自然、(b) GT 消息是否正确/完备、(c) completeness 声明是否成立。",
        "确认后在 case JSON 的所有 finding provenance 中置 adjudicated=true。**禁止修改 GT 迁就系统输出。**",
        "",
    ]
    for payload in cases:
        tags = payload["suite_tags"]
        category = next(tag.removeprefix("category:") for tag in tags if tag.startswith("category:"))
        lines.append(f"## {payload['case_id']} [{category}]")
        lines.append(f"- query: {payload['query']}")
        for finding in payload["reference_findings"]:
            criterion = finding["criterion"]
            completeness = finding["annotation_completeness"]
            method = finding["provenance"]["method"]
            ids = [e["locator"]["internal_message_id"] for e in finding["reference_evidence"]]
            lines.append(f"- {criterion} ({completeness}): {finding['expected_semantics'][:80]}")
            if ids:
                lines.append(f"  - ids: {ids}")
            lines.append(f"  - verification: {method}")
        lines.append(f"- expected: {payload['uncertainty_constraints']}")
        lines.append(f"- negative: {payload['negative_constraints']}")
        lines.append("- adjudicated: [ ] yes / [ ] no — 理由：")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
