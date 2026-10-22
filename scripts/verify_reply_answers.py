"""离线核验真实答案已引用目标回复，并用生产 CLI 组件展示来源编号。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.run_reply_context_live import CASES, SOURCE
from scripts.run_runtime_budget_followup import read_json, write_json
from trivae.conversation import deserialize_answer_artifact
from trivae.interfaces.cli import _print_evidence_block, _print_source_block
from trivae.query.evidence import MessageSource, answer_source_summaries


def verify(root: Path, label: str) -> dict[str, object]:
    """从同次运行的持久化 Artifact 恢复，禁止重跑模型或另写答案。"""
    output = root / label
    result = read_json(output / "result.json")["result"]
    targets = read_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.targets.json")
    reply_id = targets[1]["internal_message_id"]
    with closing(sqlite3.connect(f"{(output / 'conversation.sqlite3').resolve().as_uri()}?mode=ro", uri=True)) as conn:
        # 用真实 Trace 身份定位已提交的 assistant 消息，不能拿未最终化的 Runtime 文本冒充。
        row = conn.execute("SELECT answer_artifact_json FROM conversation_messages WHERE role = 'assistant' AND trace_id = ?",
            (result["trace_id"],)).fetchone()
    assert row is not None, "completed reply has no persisted artifact"
    artifact = deserialize_answer_artifact(row[0])
    summaries = answer_source_summaries(artifact)
    summary = next(item for item in summaries
        if isinstance(item.reference, MessageSource) and item.reference.internal_message_id == reply_id)
    evidence_ids = {item.evidence_id for item in artifact.evidence_items for source in item.sources
        if isinstance(source.reference, MessageSource) and source.reference.internal_message_id == reply_id}
    bound_blocks = {binding.content_block_id for binding in artifact.citation_bindings
        if evidence_ids.intersection(binding.evidence_ids)}
    claims = [block.text for block in artifact.content_blocks if block.block_id in bound_blocks]
    assert claims, "target reply is not bound to any final answer claim"
    # 只调用生产 Evidence/Sources 渲染组件；完整正文来自已存 Artifact，不在此合成结论。
    lines = ["Trivae >", artifact.answer_text]
    _print_evidence_block(artifact, summaries, output_fn=lines.append)
    _print_source_block(summaries, output_fn=lines.append, verbose=False)
    lines.extend((f"Note: {'; '.join(artifact.limitations)}", f"[trace: {result['trace_id']}]"))
    assert any(line.startswith(f"{summary.index}. message ·") for line in lines), "reply source number missing"
    with (output / "terminal.txt").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return {"case": label, "reply_cited": True, "reply_source_index": summary.index,
        "source_count": len(summaries), "citation_bindings": len(artifact.citation_bindings),
        "bound_claims": claims, "terminal_source_number_verified": True, "model_requests": 0}


def main() -> None:
    """保存明确的送达后使用证据，三条成功不能外推为全库质量提升。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    root = parser.parse_args().root
    results = [verify(root, label) for label in CASES]
    write_json(root / "answer-verification.json", {"cases": results, "model_requests": 0}, exclusive=True)
    for result in results:
        print(json.dumps({key: value for key, value in result.items() if key != "bound_claims"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
