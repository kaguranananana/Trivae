#!/usr/bin/env python3
"""应用 2026-08-31 人工 GT 裁决（resume-benchmark-v1，47 case）。

裁决输入：人工逐条审核 data/evaluation/benchmark/review-pack-dev.md 后的最终意见。
结果：Accept 26 / Modify 21 / Reject 0（calibration 6+4，development 20+17）。

应用规则（与裁决指令一致）：
- Accept：GT 语义不变，全部 finding/evidence provenance.adjudicated=true。
- Modify：先按下述人工意见修改（query / completeness / 角色 / 证明措辞），
  修改后 case version 1→2（run identity 含 case version，旧 provisional run 保持 v1 身份），
  再置 adjudicated=true。
- 不修改 GT 迁就系统输出；不导入数据；不生成 holdout。

时区 contract 依据（src 代码事实）：canonical timestamp 为无时区 epoch 毫秒；
全系统唯一正式日历解释是 UTC（capabilities.format_timestamp_utc、CLI/TUI 显示
Host-owned UTC 窗口、prompt 要求模型照抄 UTC 文本）；不存在本地时区解释，
也不存在裸日期解析器。因此带日期的 zero-result query 显式声明 UTC 日窗口。

本脚本幂等：重复运行时已完成裁决的 case 跳过（按 provenance.notes 判断）。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASE_ROOT = ROOT / "evaluation" / "cases" / "benchmark"
DATABASE = ROOT / "data" / "trivae.sqlite3"
ADJUDICATION_DATE = "2026-08-31"

ACCEPT_CALIBRATION = (
    "cal-lexical-token-monitor",
    "cal-lexical-tupu",
    "cal-paraphrase-agent-memory",
    "cal-paraphrase-subagent",
    "cal-temporal-last-2d",
    "cal-temporal-last-7d",
)
ACCEPT_DEV = (
    "dev-cite-archify",
    "dev-cite-comment-render",
    "dev-cite-lofisu",
    "dev-cite-nanobot",
    "dev-cite-volcengine",
    "dev-context-archify",
    "dev-context-mattpocock-2",
    "dev-lexical-deepseek-harness",
    "dev-lexical-forge",
    "dev-para-intern-hard-part",
    "dev-para-intern-owner",
    "dev-para-job-anxiety",
    "dev-para-resume-advice",
    "dev-para-ts-learning",
    "dev-para-webnovel",
    "dev-para-written-test",
    "dev-temporal-2d",
    "dev-temporal-3d",
    "dev-temporal-7d",
    "dev-temporal-14d",
)

# query 重写（人工裁决指定文本）
QUERY_REWRITES: dict[str, str] = {
    "cal-context-ui-skill": "之前有没有人推荐过可以检查 UI 效果的 skill？除了推荐者本人，还有没有其他人评价过它？",
    "cal-lexical-hello-agents": "群里有没有人分享过 datawhalechina/hello-agents 这个仓库？",
    "cal-zero-empty-window": "按 UTC 时间算，2025年8月11日当天大家有没有发言？都在聊什么？",
    "dev-context-mattpocock-1": "有人推荐过 mattpocock 的 skills 仓库吗？怎么使用，群里有没有人反馈它好用？",
    "dev-lexical-chatlog-alpha": "teest114514/chatlog_alpha 这个聊天记录相关的仓库在群里被分享过吗？",
    "dev-lexical-siclaw": "群里有没有人给 scitix/siclaw 这个项目求过 star？",
    "dev-lexical-zenith": "zenith-image-generator 这个图片生成项目在群里被分享或讨论过吗？",
    "dev-para-ai-interest": "有没有人坦白过自己其实对 Agent/AI 提不起兴趣，每天只是为了工作而工作？",
    "dev-temporal-1d": "最近24小时大家都聊了些什么？",
    "dev-temporal-30d": "最近30天群里的主要话题有哪些？",
    "dev-zero-empty-1": "按 UTC 时间算，2025-08-11 这天大家有没有发言？都在聊什么？",
    "dev-zero-empty-2": "按 UTC 时间算，2025-08-23 这天大家有没有发言？都在聊什么？",
    "dev-zero-empty-3": "按 UTC 时间算，2025-08-26 这天大家有没有发言？都在聊什么？",
    "dev-zero-excalidraw": "群里有没有人明确提到过 excalidraw？",
}

# gt.relevant exhaustive → partial/target（query 为语义类；LIKE 只证明该 repo URL 出现集合完整）
TARGET_SCOPE_CASES: dict[str, tuple[str, int]] = {
    "dev-cite-meimei": ("87789771/meimei-nestjs-admin", 3),
    "dev-lexical-agentic-zh": ("WenyuChiou/awesome-agentic-ai-zh", 4),
    "dev-lexical-mcp-switch": ("asashiki/mcp-switch", 2),
    "dev-lexical-nanobot-wiki": ("yu-xin-c/nanobot-llm-wiki", 4),
    "dev-lexical-resume-miner": ("auberginewly/resume-project-miner", 4),
    "dev-lexical-vibe-game": ("asashiki/vibe-game", 3),
}

# 角色互换：reply 直接回答 query（relevant），parent 恢复指代对象（required_context）
ROLE_SWAP_CASE = "cal-context-ts-docs"
ROLE_SWAP_REPLY = "qq:831907794:7674452954669596319"   # 3qwerty：读 SDK 文档抓不到重点、想深入学
ROLE_SWAP_PARENT = "qq:831907794:7673166668798186827"  # 奶龙大学校长：vercel ai sdk 推荐

MODIFY_NOTES: dict[str, str] = {
    "cal-context-ts-docs": "Modify: swap gt.relevant/gt.required_context roles (reply directly answers query; parent restores the Vercel AI SDK referent)",
    "cal-context-ui-skill": "Modify: query rewritten so a second member's reply is required evidence (direct target alone already answered the old query)",
    "cal-lexical-hello-agents": "Modify: query rewritten to drop the sender-extraction dimension (exact lexical case keeps single responsibility)",
    "cal-zero-empty-window": "Modify: query declares explicit UTC day window (production renders UTC only; bare date + UTC proof ambiguity removed)",
    "dev-cite-meimei": "Modify: gt.relevant exhaustive->partial (LIKE proves the target repo occurrence set, not semantic-class corpus enumeration)",
    "dev-context-mattpocock-1": "Modify: query rewritten so the reply's usability feedback is required evidence",
    "dev-lexical-agentic-zh": "Modify: gt.relevant exhaustive->partial (semantic-class query; LIKE proves target repo occurrence set only)",
    "dev-lexical-chatlog-alpha": "Modify: query rewritten to drop the sender-extraction dimension",
    "dev-lexical-mcp-switch": "Modify: gt.relevant exhaustive->partial (semantic-class query; LIKE proves target repo occurrence set only)",
    "dev-lexical-nanobot-wiki": "Modify: gt.relevant exhaustive->partial (semantic-class query; LIKE proves target repo occurrence set only)",
    "dev-lexical-resume-miner": "Modify: gt.relevant exhaustive->partial (semantic-class query; LIKE proves target repo occurrence set only)",
    "dev-lexical-siclaw": "Modify: query rewritten to drop the sender-extraction dimension",
    "dev-lexical-vibe-game": "Modify: gt.relevant exhaustive->partial (semantic-class query; LIKE proves target repo occurrence set only)",
    "dev-lexical-zenith": "Modify: query rewritten to 'shared or discussed' (URL occurrence set != sharer set)",
    "dev-para-ai-interest": "Modify: query rewritten to avoid introducing an economic-motive fact absent from the target message",
    "dev-temporal-1d": "Modify: query '昨天'->'最近24小时' (proof window is trailing 24h; boundary now explicit)",
    "dev-temporal-30d": "Modify: query '过去一个月'->'最近30天' (proof window is fixed 30d; boundary now explicit)",
    "dev-zero-empty-1": "Modify: query declares explicit UTC day window (production renders UTC only)",
    "dev-zero-empty-2": "Modify: query declares explicit UTC day window (production renders UTC only)",
    "dev-zero-empty-3": "Modify: query declares explicit UTC day window (production renders UTC only)",
    "dev-zero-excalidraw": "Modify: query narrowed to explicit excalidraw mention (token-level zero proof; no open-ended conceptual-class claim)",
}


def case_path(case_id: str) -> Path:
    split = "calibration" if case_id.startswith("cal-") else "dev"
    return CASE_ROOT / split / f"{case_id}.json"


def load_case(case_id: str) -> dict:
    return json.loads(case_path(case_id).read_text(encoding="utf-8"))


def write_case(payload: dict) -> None:
    path = case_path(payload["case_id"])
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def mark_provenance_adjudicated(provenance: dict) -> None:
    provenance["adjudicated"] = True
    # "provisional; awaiting human review" limitation 已由人工裁决解决。
    provenance["limitations"] = []


def apply_accept(case_id: str) -> None:
    payload = load_case(case_id)
    if payload["provenance"].get("notes", "").startswith("human adjudication"):
        return
    for finding in payload["reference_findings"]:
        if finding["criterion"].startswith("gt."):
            mark_provenance_adjudicated(finding["provenance"])
            for evidence in finding["reference_evidence"]:
                mark_provenance_adjudicated(evidence["provenance"])
    payload["provenance"]["method"] = f"{payload['provenance']['method'].removesuffix('; provisional')}; human adjudicated {ADJUDICATION_DATE}"
    payload["provenance"]["notes"] = f"human adjudication {ADJUDICATION_DATE}: Accept (GT unchanged)"
    write_case(payload)


def apply_target_scope(payload: dict, repo: str, hits: int) -> None:
    for finding in payload["reference_findings"]:
        if finding["criterion"] != "gt.relevant":
            continue
        finding["annotation_completeness"] = "partial"
        finding["expected_semantics"] = (
            f"包含 {repo} 的消息（target 集合=该 repo 全部出现，LIKE 全库扫描枚举共 {hits} 条；"
            "query 为语义类，不声称 corpus 穷举）"
        )
        finding["known_limitations"] = [
            "target 集合=该 repo URL 全部出现（LIKE 证明）；query 为语义类，只能评 Target Recall。"
        ]
        finding["provenance"]["method"] = (
            f"deterministic LIKE scan; hit_count={hits} (target repo occurrence set; corpus semantic enumeration not claimed)"
        )


def apply_role_swap(payload: dict) -> None:
    findings = {f["criterion"]: f for f in payload["reference_findings"]}
    relevant = findings["gt.relevant"]
    context = findings["gt.required_context"]
    parent_evidence = relevant["reference_evidence"][0]
    reply_evidence = context["reference_evidence"][0]
    if parent_evidence["locator"]["internal_message_id"] != ROLE_SWAP_PARENT:
        raise SystemExit(f"role swap precondition failed: relevant is not {ROLE_SWAP_PARENT}")
    if reply_evidence["locator"]["internal_message_id"] != ROLE_SWAP_REPLY:
        raise SystemExit(f"role swap precondition failed: required_context is not {ROLE_SWAP_REPLY}")

    reply_evidence["relation"] = "supports"
    reply_evidence["why_relevant"] = "直接回答 query：读 SDK 文档抓不到重点、想深入学的提问"
    parent_evidence["relation"] = "context"
    parent_evidence["why_relevant"] = "reply pair 的 parent：恢复'这个'指代的 Vercel AI SDK 上文"

    relevant["reference_evidence"] = [reply_evidence]
    relevant["expected_semantics"] = "直接回答 query 的提问消息（读前端 SDK 文档抓不到重点、想深入学）"
    relevant["provenance"]["method"] = "reply pair pick; reply directly answers query (roles swapped per human adjudication)"
    relevant["annotation_completeness"] = "partial"  # 保持 partial

    context["reference_evidence"] = [parent_evidence]
    context["expected_semantics"] = "direct target 回复指向的上文（Vercel AI SDK 推荐），脱离上下文不可解释"
    context["provenance"]["method"] = "single known reply pair (parent of direct target)"
    context["annotation_completeness"] = "exhaustive"  # reply pair 的唯一 parent，确定性事实


def verify_database_facts() -> None:
    """对裁决涉及的全部确定性声明做一次落库前复核。"""
    connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro", uri=True)

    def like_hits(token: str) -> int:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM messages WHERE content_text LIKE ? ESCAPE '\\' AND recalled = 0",
                (f"%{token}%",),
            ).fetchone()[0]
        )

    for case_id, (repo, expected) in TARGET_SCOPE_CASES.items():
        actual = like_hits(repo)
        if actual != expected:
            raise SystemExit(f"{case_id}: {repo} occurrence set drift: {actual} != {expected}")

    if like_hits("excalidraw") != 0:
        raise SystemExit("excalidraw token is no longer zero-hit")

    row = connection.execute(
        "SELECT reply_to_source_message_id FROM messages WHERE internal_message_id = ?",
        (ROLE_SWAP_REPLY,),
    ).fetchone()
    if row is None or row[0] is None:
        raise SystemExit("role swap reply message missing or has no parent linkage")
    parent = connection.execute(
        "SELECT internal_message_id FROM messages WHERE session_id = "
        "(SELECT session_id FROM messages WHERE internal_message_id = ?) AND source_message_id = ?",
        (ROLE_SWAP_REPLY, row[0]),
    ).fetchone()
    if parent is None or parent[0] != ROLE_SWAP_PARENT:
        raise SystemExit(f"role swap parent linkage mismatch: {parent[0] if parent else None}")

    connection.close()


def apply_modify(case_id: str) -> None:
    payload = load_case(case_id)
    if payload["provenance"].get("notes", "").startswith("human adjudication"):
        return
    if case_id in QUERY_REWRITES:
        payload["query"] = QUERY_REWRITES[case_id]
    if case_id in TARGET_SCOPE_CASES:
        repo, hits = TARGET_SCOPE_CASES[case_id]
        apply_target_scope(payload, repo, hits)
    if case_id == ROLE_SWAP_CASE:
        apply_role_swap(payload)
    if case_id == "dev-zero-excalidraw":
        for finding in payload["reference_findings"]:
            if finding["criterion"] == "gt.expected_zero_result":
                finding["provenance"]["method"] = "LIKE scan for token 'excalidraw' = 0 (deterministic)"
                finding["known_limitations"] = [
                    "query 已按人工裁决收窄为显式提及 excalidraw；不再声称'同类画图工具'概念级零命中。"
                ]
    for finding in payload["reference_findings"]:
        if finding["criterion"].startswith("gt."):
            mark_provenance_adjudicated(finding["provenance"])
            for evidence in finding["reference_evidence"]:
                mark_provenance_adjudicated(evidence["provenance"])
    payload["version"] = 2
    payload["provenance"]["method"] = f"{payload['provenance']['method'].removesuffix('; provisional')}; human adjudicated {ADJUDICATION_DATE}"
    payload["provenance"]["notes"] = f"human adjudication {ADJUDICATION_DATE}: {MODIFY_NOTES[case_id]}"
    write_case(payload)


def main() -> int:
    verify_database_facts()

    accepted = 0
    for case_id in (*ACCEPT_CALIBRATION, *ACCEPT_DEV):
        before = load_case(case_id)
        apply_accept(case_id)
        after = load_case(case_id)
        if after["provenance"].get("notes", "").startswith("human adjudication"):
            accepted += 1
            assert after["version"] == before["version"], f"{case_id}: accept must not bump version"

    modified = 0
    for case_id in MODIFY_NOTES:
        apply_modify(case_id)
        after = load_case(case_id)
        assert after["version"] == 2, f"{case_id}: modify must bump version to 2"
        assert all(
            f["provenance"]["adjudicated"] for f in after["reference_findings"] if f["criterion"].startswith("gt.")
        ), f"{case_id}: gt findings must be adjudicated"
        assert all(
            ev["provenance"]["adjudicated"]
            for f in after["reference_findings"]
            for ev in f["reference_evidence"]
        ), f"{case_id}: evidence must be adjudicated"
        modified += 1

    total = accepted + modified
    expected_total = len(ACCEPT_CALIBRATION) + len(ACCEPT_DEV) + len(MODIFY_NOTES)
    if total != expected_total or expected_total != 47:
        raise SystemExit(f"adjudication count mismatch: accept={accepted} modify={modified} total={total}")
    print(f"applied human adjudication: Accept={accepted} Modify={modified} Reject=0 total={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
