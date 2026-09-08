#!/usr/bin/env python3
"""生成 Gate 3 冻结后的 resume-benchmark-v1 holdout 候选。

本脚本只负责构造候选和人工 review 材料，不登记、不运行 holdout。
候选必须先由用户逐条审核并标记为 adjudicated，之后才允许执行 seal-holdout。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / "data" / "trivae.sqlite3"
SNAPSHOT_PATH = ROOT / "data" / "evaluation" / "benchmark" / "snapshot.json"
FREEZE_PATH = ROOT / "data" / "evaluation" / "benchmark" / "gate3-final-freeze.json"
HOLDOUT_ROOT = ROOT / "data" / "evaluation" / "benchmark" / "holdout"
CASES_DIR = HOLDOUT_ROOT / "cases"
SUITE_PATH = HOLDOUT_ROOT / "resume-benchmark-holdout-v1.json"
QUERYSET_PATH = HOLDOUT_ROOT / "resume-benchmark-holdout-retrieval-queries.json"
REVIEW_PATH = HOLDOUT_ROOT / "review.md"
PACKET_PATH = HOLDOUT_ROOT / "candidate-packet.json"

SCOPE = {"allowed_session_ids": None, "start_timestamp": None, "end_timestamp": None, "max_results": 100}
SCOPE_IDENTITY = json.dumps(SCOPE, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
REVIEW_POLICY = {
    "rubric_version": "m7-v1",
    "reviewer_types": ["human"],
    "blind_pairwise": True,
    "human_adjudication_on_disagreement": True,
}
DAY = 24 * 60 * 60 * 1000
CREATED_AT = "2026-09-08T00:00:00+00:00"


def provenance(case_id: str, snapshot_id: str, method: str) -> dict[str, object]:
    """为候选 finding 写入固定 Snapshot/Scope 的 provisional provenance。"""

    return {
        "source": f"deterministic-construction:{case_id}",
        "created_at": CREATED_AT,
        "method": method,
        "snapshot_id": snapshot_id,
        "scope_identity": SCOPE_IDENTITY,
        "adjudicated": False,
        "limitations": ["provisional; awaiting human review"],
    }


def evidence(message_id: str, why: str, snapshot_id: str, relation: str = "supports") -> dict[str, object]:
    """构造不携带正文的 canonical message evidence locator。"""

    return {
        "evidence_id": f"ev:{message_id}",
        "relation": relation,
        "source_type": "message",
        "locator": {"internal_message_id": message_id},
        "why_relevant": why,
        "provenance": provenance("shared", snapshot_id, "deterministic candidate construction / manual pick"),
    }


def case_payload(
    case_id: str,
    query: str,
    category: str,
    snapshot: dict[str, object],
    findings: list[dict[str, object]],
    constraints: dict[str, list[str]],
    method: str,
) -> dict[str, object]:
    """生成与 Development Case 相同的 canonical payload，保持 split 只由 tag 区分。"""

    return {
        "schema_version": 1,
        "case_id": case_id,
        "version": 1,
        "suite_tags": [f"category:{category}", "benchmark:holdout"],
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
            "source": f"holdout-construction:{case_id}",
            "method": method,
            "created_at": CREATED_AT,
            "notes": "provisional pending human review",
        },
    }


def zero_finding(case_id: str, snapshot_id: str, expected: str, method: str) -> dict[str, object]:
    """声明 zero-result 轴，避免由缺少 relevant finding 隐式推断。"""

    return {
        "finding_id": "zero",
        "criterion": "gt.expected_zero_result",
        "expected_semantics": expected,
        "reference_evidence": [],
        "annotation_completeness": "exhaustive",
        "provenance": provenance(case_id, snapshot_id, method),
        "known_limitations": [],
        "critical": expected == "true",
    }


def relevant_finding(
    case_id: str,
    snapshot_id: str,
    message_ids: list[str],
    semantics: str,
    completeness: str,
    method: str,
) -> dict[str, object]:
    """构造相关消息 finding；正文仍只通过 message ID 引用。"""

    return {
        "finding_id": "relevant",
        "criterion": "gt.relevant",
        "expected_semantics": semantics,
        "reference_evidence": [
            evidence(message_id, "候选目标消息", snapshot_id) for message_id in message_ids
        ],
        "annotation_completeness": completeness,
        "provenance": provenance(case_id, snapshot_id, method),
        "known_limitations": [] if completeness == "exhaustive" else ["target 集合未证明 corpus-exhaustive。"],
        "critical": False,
    }


def context_finding(
    case_id: str,
    snapshot_id: str,
    message_ids: list[str],
    semantics: str,
) -> dict[str, object]:
    """构造需要被 evidence 恢复的上下文 finding。"""

    return {
        "finding_id": "context",
        "criterion": "gt.required_context",
        "expected_semantics": semantics,
        "reference_evidence": [
            evidence(message_id, "脱离该消息无法解释 direct target", snapshot_id, relation="context")
            for message_id in message_ids
        ],
        "annotation_completeness": "exhaustive",
        "provenance": provenance(case_id, snapshot_id, "single known reply pair"),
        "known_limitations": [],
        "critical": True,
    }


def fact_finding(case_id: str, snapshot_id: str, alias: str) -> dict[str, object]:
    """声明只在 answer_text 中评分的 extractive fact alias。"""

    return {
        "finding_id": "fact",
        "criterion": "gt.expected_fact",
        "expected_semantics": json.dumps([alias.lower()], ensure_ascii=False),
        "reference_evidence": [],
        "annotation_completeness": "exhaustive",
        "provenance": provenance(case_id, snapshot_id, "extractive fact from target messages"),
        "known_limitations": [],
        "critical": True,
    }


def query_entry(case_id: str, query: str, lexical_query: str, category: str, context: int = 2) -> dict[str, object]:
    """把 Case 投影为现有 module-level retrieval workflow 使用的 query entry。"""

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


def message_text(connection: sqlite3.Connection, message_id: str) -> sqlite3.Row:
    """读取人工 review 所需的 bounded source metadata；找不到消息时立即失败。"""

    row = connection.execute(
        "SELECT internal_message_id, timestamp, sender_name, content_text "
        "FROM messages WHERE internal_message_id = ? AND recalled = 0",
        (message_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"holdout candidate message is missing or recalled: {message_id}")
    return row


def load_used_evidence_ids() -> set[str]:
    """收集 calibration/development 已用 evidence，执行 split 的消息级隔离检查。"""

    used: set[str] = set()
    for root in (ROOT / "evaluation" / "cases" / "benchmark" / "dev", ROOT / "evaluation" / "cases" / "benchmark" / "calibration"):
        for path in root.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for finding in payload.get("reference_findings", []):
                for item in finding.get("reference_evidence", []):
                    message_id = item.get("locator", {}).get("internal_message_id")
                    if isinstance(message_id, str):
                        used.add(message_id)
    return used


def build_cases(connection: sqlite3.Connection, snapshot: dict[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, list[dict[str, object]]]]:
    """按六类各三条构造 18 条 holdout 候选，并返回 review packet 的正文节选。"""

    snapshot_id = str(snapshot["snapshot_id"])
    cases: list[dict[str, object]] = []
    queries: list[dict[str, object]] = []
    excerpts: dict[str, list[dict[str, object]]] = {}

    def add_case(payload: dict[str, object], lexical_query: str, context: int = 2) -> None:
        """统一追加 Case、retrieval query 和 bounded review source。"""

        cases.append(payload)
        queries.append(
            query_entry(
                str(payload["case_id"]),
                str(payload["query"]),
                lexical_query,
                next(tag.removeprefix("category:") for tag in payload["suite_tags"] if tag.startswith("category:")),
                context=context,
            )
        )
        source_ids: list[str] = []
        for finding in payload["reference_findings"]:
            for item in finding["reference_evidence"]:
                message_id = item["locator"]["internal_message_id"]
                if message_id not in source_ids:
                    source_ids.append(message_id)
        excerpts[str(payload["case_id"])] = []
        for message_id in source_ids:
            row = message_text(connection, message_id)
            text = str(row["content_text"])
            bounded = text[:1600]
            excerpts[str(payload["case_id"])].append(
                {
                    "message_id": message_id,
                    "timestamp": int(row["timestamp"]),
                    "sender_name": row["sender_name"],
                    "text": bounded,
                    "truncated": len(text) > len(bounded),
                }
            )

    # exact_lexical：LIKE 全库可枚举的 repo occurrence set，三个 repo 均来自未使用消息。
    lexical_specs = [
        ("holdout-lexical-agent-learning-hub", "datawhalechina/Agent-Learning-Hub", "群里有人分享过 datawhalechina/Agent-Learning-Hub 吗？"),
        ("holdout-lexical-sea-mult-agent", "yu-xin-c/Sea-mult-agent", "群里出现过 yu-xin-c/Sea-mult-agent 这个仓库吗？"),
        ("holdout-lexical-sea-breakthewaves", "Sea-Go/Sea-BreakTheWaves", "有人分享过 Sea-Go/Sea-BreakTheWaves 这个仓库吗？"),
    ]
    for case_id, keyword, query in lexical_specs:
        rows = connection.execute(
            "SELECT internal_message_id FROM messages WHERE content_text LIKE ? AND recalled = 0 ORDER BY timestamp",
            (f"%{keyword}%",),
        ).fetchall()
        ids = [str(row["internal_message_id"]) for row in rows]
        if not 2 <= len(ids) <= 8:
            raise SystemExit(f"{case_id}: unexpected LIKE hit count {len(ids)}")
        add_case(
            case_payload(
                case_id,
                query,
                "exact_lexical",
                snapshot,
                [
                    relevant_finding(
                        case_id,
                        snapshot_id,
                        ids,
                        f"包含 {keyword} 的消息（LIKE 全库扫描枚举，共 {len(ids)} 条）",
                        "exhaustive",
                        f"deterministic LIKE scan; hit_count={len(ids)}",
                    ),
                    zero_finding(case_id, snapshot_id, "false", "predicate scan proves non-empty"),
                    fact_finding(case_id, snapshot_id, keyword),
                ],
                {
                    "uncertainty": ["不要求罗列每条消息的发送者与时间。"],
                    "negative": ["不得引用 Scope 外消息。"],
                    "critical": ["答案应给出仓库名称或 URL，并引用命中消息。"],
                },
                f"deterministic LIKE scan ({len(ids)} hits); provisional",
            ),
            keyword,
        )

    # citation_evidence：目标消息包含可直接引用的仓库信息，事实只允许从 source message 提取。
    citation_specs = [
        ("holdout-cite-pony-code", "xiawiie/pony-code", "pony-code 这个项目是怎么被群里推荐的？请引用原文依据。"),
        ("holdout-cite-bridge", "Utopia-V/chatgpt-pro-bridge", "chatgpt-pro-bridge 是用来做什么的？请引用原文依据。"),
        ("holdout-cite-deepwiki", "AsyncFuncAI/deepwiki-open", "deepwiki-open 这个仓库在群里是否被分享过？请引用原始链接。"),
    ]
    for case_id, keyword, query in citation_specs:
        rows = connection.execute(
            "SELECT internal_message_id FROM messages WHERE content_text LIKE ? AND recalled = 0 ORDER BY timestamp",
            (f"%{keyword}%",),
        ).fetchall()
        ids = [str(row["internal_message_id"]) for row in rows]
        if not 2 <= len(ids) <= 8:
            raise SystemExit(f"{case_id}: unexpected LIKE hit count {len(ids)}")
        add_case(
            case_payload(
                case_id,
                query,
                "citation_evidence",
                snapshot,
                [
                    relevant_finding(
                        case_id,
                        snapshot_id,
                        ids,
                        f"包含 {keyword} 的消息（LIKE 全库扫描枚举，共 {len(ids)} 条）",
                        "exhaustive",
                        f"deterministic LIKE scan; hit_count={len(ids)}",
                    ),
                    zero_finding(case_id, snapshot_id, "false", "predicate scan proves non-empty"),
                    fact_finding(case_id, snapshot_id, keyword),
                ],
                {
                    "uncertainty": ["只对消息中明确出现的项目名、URL 或描述评分。"],
                    "negative": ["不得用未被引用支持的外部项目资料补全答案。"],
                    "critical": ["每个项目事实必须绑定至少一个可解析 source handle。"],
                },
                f"deterministic LIKE scan ({len(ids)} hits); provisional",
            ),
            keyword,
        )

    # semantic_paraphrase：每条只标一个人工目标，声明为 partial，不声称语义全库穷举。
    paraphrase_specs = [
        ("holdout-para-model-planning", "qq:750807478:7674084484709452834", "有人纠结过选哪个模型来帮自己做规划吗？", "大模型 规划"),
        ("holdout-para-mac-agent", "qq:831907794:7673738740124008581", "有没有人提到 Agent 跑自动化会让 Mac 发热？", "自动化 温度"),
        ("holdout-para-client-name", "qq:831907794:7673702070476093323", "实习经历里能不能写甲方公司的名字？", "实习 甲方"),
    ]
    for case_id, target_id, query, lexical_query in paraphrase_specs:
        message_text(connection, target_id)
        add_case(
            case_payload(
                case_id,
                query,
                "semantic_paraphrase",
                snapshot,
                [
                    relevant_finding(
                        case_id,
                        snapshot_id,
                        [target_id],
                        "人工确认的语义 paraphrase target 消息",
                        "partial",
                        "manual target pick; corpus semantic enumeration not attempted",
                    ),
                    zero_finding(case_id, snapshot_id, "false", "target exists"),
                ],
                {
                    "uncertainty": ["query 与原消息措辞不同，只评估该人工 target 是否被召回。"],
                    "negative": ["不得把主题相关的其他消息直接当成该 target。"],
                    "critical": ["答案应引用该 target 消息。"],
                },
                "manual target pick; provisional",
            ),
            lexical_query,
        )

    # context_recovery：direct target 与 parent/reply 成对出现，避免只命中单条而失去指代关系。
    context_specs = [
        (
            "holdout-context-galgame-skill",
            "GalgameCharacterSkills 有没有使用反馈？",
            "qq:750807478:7627841031521224732",
            "qq:750807478:7627805818104781259",
            "使用反馈",
            "reply 表达使用反馈；parent 提供被测试的 skill 仓库和测试范围",
        ),
        (
            "holdout-context-ios-proxy",
            "群里有人推荐过哪些 iOS 科学上网工具？",
            "qq:750807478:7674455424302619170",
            "qq:750807478:7674455424302619143",
            "iOS 工具",
            "reply 给出工具名；parent 是被回答的 iOS 工具请求",
        ),
        (
            "holdout-context-agent-stall",
            "为什么有人醒来发现交给 Agent 的十个任务都没干？",
            "qq:677019167:7674451112113215278",
            "qq:677019167:7673703779383615080",
            "Agent 任务",
            "reply 指出 permission request 阻塞；parent 是十个任务未执行的原始抱怨",
        ),
    ]
    for case_id, query, direct_id, context_id, lexical_query, semantics in context_specs:
        message_text(connection, direct_id)
        message_text(connection, context_id)
        add_case(
            case_payload(
                case_id,
                query,
                "context_recovery",
                snapshot,
                [
                    relevant_finding(
                        case_id,
                        snapshot_id,
                        [direct_id],
                        "reply pair 中直接回答 query 的消息",
                        "partial",
                        "manual reply-pair target pick",
                    ),
                    context_finding(case_id, snapshot_id, [context_id], semantics),
                    zero_finding(case_id, snapshot_id, "false", "target exists"),
                ],
                {
                    "uncertainty": ["direct target 与 required_context 必须一起核对。"],
                    "negative": ["不得只引用 reply 而丢失 parent 的指代对象。"],
                    "critical": ["最终 evidence 应同时覆盖 direct 与 required_context。"],
                },
                "manual reply-pair pick; provisional",
            ),
            lexical_query,
            context=4,
        )

    # temporal_overview：窗口大小使用未在 Development 出现的 12h/36h/72h，覆盖 complete 与 partial。
    latest = int(connection.execute("SELECT MAX(timestamp) FROM messages").fetchone()[0])
    temporal_specs = [
        ("holdout-temporal-12h", "最近12小时群里主要聊了什么？", 12, "complete", "false"),
        ("holdout-temporal-36h", "过去36小时大家都在讨论哪些主题？", 36, "complete", "false"),
        ("holdout-temporal-72h", "最近72小时群里的讨论主题有哪些？", 72, "partial", "true"),
    ]
    for case_id, query, hours, coverage, truncated in temporal_specs:
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM messages WHERE timestamp > ? AND timestamp <= ?",
                (latest - hours * 60 * 60 * 1000, latest + 1),
            ).fetchone()[0]
        )
        if (coverage == "complete" and count > 5000) or (coverage == "partial" and count <= 5000):
            raise SystemExit(f"{case_id}: window count {count} contradicts expected coverage {coverage}")
        add_case(
            case_payload(
                case_id,
                query,
                "temporal_overview",
                snapshot,
                [
                    {
                        "finding_id": "coverage",
                        "criterion": "gt.expected_coverage_status",
                        "expected_semantics": coverage,
                        "reference_evidence": [],
                        "annotation_completeness": "exhaustive",
                        "provenance": provenance(case_id, snapshot_id, f"SQL COUNT over trailing {hours}h = {count}"),
                        "known_limitations": [],
                        "critical": True,
                    },
                    {
                        "finding_id": "truncated",
                        "criterion": "gt.expected_truncated",
                        "expected_semantics": truncated,
                        "reference_evidence": [],
                        "annotation_completeness": "exhaustive",
                        "provenance": provenance(case_id, snapshot_id, f"window count {count} vs trusted capacity"),
                        "known_limitations": [],
                        "critical": False,
                    },
                    zero_finding(case_id, snapshot_id, "false", f"window count {count} > 0"),
                ],
                {
                    "uncertainty": [f"窗口实测 {count} 条消息；coverage/truncated 预期由容量决定。"],
                    "negative": ["不得把 partial 覆盖说成 complete。"],
                    "critical": ["coverage 声明必须与 Artifact retrieval_coverage 一致。"],
                },
                f"deterministic trailing-window COUNT ({count}); provisional",
            ),
            "最近讨论",
        )

    # zero_result：使用三个全库 LIKE=0 的精确 token，避免把开放概念类问题冒充零结果证明。
    zero_specs = [
        ("holdout-zero-tldraw", "tldraw", "群里有没有明确提到过 tldraw？"),
        ("holdout-zero-roamresearch", "roamresearch", "群里有没有明确提到过 roamresearch？"),
        ("holdout-zero-flowise", "flowise", "群里有没有明确提到过 flowise？"),
    ]
    for case_id, token, query in zero_specs:
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM messages WHERE content_text LIKE ? AND recalled = 0",
                (f"%{token}%",),
            ).fetchone()[0]
        )
        if count != 0:
            raise SystemExit(f"{case_id}: zero token scan found {count} messages")
        add_case(
            case_payload(
                case_id,
                query,
                "zero_result",
                snapshot,
                [
                    zero_finding(case_id, snapshot_id, "true", f"deterministic LIKE scan for token {token!r} = 0"),
                ],
                {
                    "uncertainty": ["仅对精确 token 的全库零命中负责。"],
                    "negative": ["不得根据相近概念编造群内讨论。"],
                    "critical": ["应输出经过 positive proof 的 no_result。"],
                },
                f"deterministic zero-token LIKE scan ({token!r}); provisional",
            ),
            token,
        )

    return cases, queries, excerpts


def write_review_pack(
    cases: list[dict[str, object]],
    excerpts: dict[str, list[dict[str, object]]],
    freeze: dict[str, object],
) -> None:
    """写入含 bounded source excerpt 的本地人工 review 材料。"""

    lines = [
        "# resume-benchmark-v1 Holdout Candidate Review",
        "",
        f"冻结基线：`{freeze['execution_commit']}`；本 packet 只用于冻结后的候选人工审核，不是正式 holdout 结果。",
        "候选共 18 条，六类各 3 条。请逐条确认 query 自然性、GT 目标是否正确/完备、coverage 预期是否成立；确认后再由脚本把对应 Case 标记为 adjudicated。",
        "禁止根据系统答案修改 GT；只有 GT 与 Snapshot 矛盾、重复或数据损坏才允许替换，并需记录原因。",
        "",
    ]
    packet_items: list[dict[str, object]] = []
    for payload in cases:
        case_id = str(payload["case_id"])
        category = next(tag.removeprefix("category:") for tag in payload["suite_tags"] if tag.startswith("category:"))
        item = {
            "case_id": case_id,
            "category": category,
            "query": payload["query"],
            "reference_findings": payload["reference_findings"],
            "excerpts": excerpts[case_id],
            "status": "pending",
        }
        packet_items.append(item)
        lines.append(f"## {case_id} [{category}]")
        lines.append(f"- query：{payload['query']}")
        for finding in payload["reference_findings"]:
            ids = [item["locator"]["internal_message_id"] for item in finding["reference_evidence"]]
            lines.append(
                f"- {finding['criterion']} / {finding['annotation_completeness']}：{finding['expected_semantics']}"
            )
            if ids:
                lines.append(f"  - ids：{ids}")
        lines.append("- 来源节选：")
        for excerpt in excerpts[case_id]:
            lines.append(
                f"  - `{excerpt['message_id']}` timestamp={excerpt['timestamp']} sender={excerpt['sender_name']} truncated={excerpt['truncated']}"
            )
            lines.append("    > " + str(excerpt["text"]).replace("\n", "\n    > "))
        lines.append("- 核验状态：`pending`；结论：；理由：")
        lines.append("")

    REVIEW_PATH.write_text("\n".join(lines), encoding="utf-8")
    PACKET_PATH.write_text(
        json.dumps(
            {
                "status": "pending_human_review",
                "benchmark": freeze["benchmark"],
                "frozen_execution_commit": freeze["execution_commit"],
                "freeze_path": str(FREEZE_PATH.resolve()),
                "count": len(packet_items),
                "category_counts": {
                    category: sum(1 for item in packet_items if item["category"] == category)
                    for category in sorted({str(item["category"]) for item in packet_items})
                },
                "items": packet_items,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """执行候选构造、隔离校验和本地 artifact 写入。"""

    if not FREEZE_PATH.is_file():
        raise SystemExit(f"final freeze does not exist: {FREEZE_PATH}")
    if HOLDOUT_ROOT.exists() and any(HOLDOUT_ROOT.iterdir()):
        raise SystemExit(f"holdout output is not empty; refusing to overwrite: {HOLDOUT_ROOT}")

    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("benchmark") != "resume-benchmark-v1":
        raise SystemExit("final freeze benchmark is not resume-benchmark-v1")
    if not isinstance(freeze.get("execution_commit"), str) or not freeze["execution_commit"]:
        raise SystemExit("final freeze has no execution_commit")

    connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        cases, queries, excerpts = build_cases(connection, snapshot)
        used_ids = load_used_evidence_ids()
        candidate_ids = {
            item["locator"]["internal_message_id"]
            for payload in cases
            for finding in payload["reference_findings"]
            for item in finding["reference_evidence"]
        }
        overlap = sorted(candidate_ids & used_ids)
        if overlap:
            raise SystemExit(f"holdout candidate reuses existing GT evidence: {overlap}")
        if len(candidate_ids) != sum(
            len(finding["reference_evidence"])
            for payload in cases
            for finding in payload["reference_findings"]
        ):
            raise SystemExit("holdout candidates reuse GT evidence across cases")
    finally:
        connection.close()

    if len(cases) != 18:
        raise SystemExit(f"expected 18 holdout candidates, got {len(cases)}")
    categories = [tag for payload in cases for tag in payload["suite_tags"] if tag.startswith("category:")]
    if any(categories.count(category) != 3 for category in set(categories)):
        raise SystemExit(f"holdout category distribution is not 3 each: {categories}")

    CASES_DIR.mkdir(parents=True, exist_ok=False)
    for payload in cases:
        path = CASES_DIR / f"{payload['case_id']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    SUITE_PATH.write_text(
        json.dumps(
            {
                "suite_id": "resume-benchmark-holdout",
                "version": 1,
                "kind": "core",
                "description": "resume-benchmark-v1 holdout candidates generated after Gate 3 final freeze; pending human adjudication.",
                "created_at": CREATED_AT,
                "cases": [{"case_id": payload["case_id"], "version": payload["version"]} for payload in cases],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    QUERYSET_PATH.write_text(
        json.dumps(
            {
                "schema_version": "retrieval-annotation-v1",
                "query_set_id": "resume-benchmark-holdout",
                "version": 1,
                "snapshot_id": snapshot["snapshot_id"],
                "description": "holdout candidate module-level retrieval inputs; pending human adjudication",
                "queries": queries,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_review_pack(cases, excerpts, freeze)
    print(f"wrote {len(cases)} holdout candidates to {HOLDOUT_ROOT}")
    print(f"wrote review packet to {REVIEW_PATH}")


if __name__ == "__main__":
    main()
