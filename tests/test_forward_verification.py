"""真实核验脚本必须检查正文 Citation，而不是只检查证据候选存在。"""

from dataclasses import replace

from scripts.verify_forward_retrieval import cited_message_sources, visible_matching_sources
from tests.test_forward_evidence import _child, _envelope, _record
from trivae.capabilities.contracts import ExecutionScope
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    MessageSource,
    project_tool_result_for_model,
)


def test_unbound_child_evidence_is_not_counted_as_a_citation() -> None:
    """即使候选集合含命中子消息，正文只引用普通消息时也不能通过子消息核验。"""

    child = MessageSource("run", "call", "result", "child-item", "qq:100", "qq:100:root#forward:0.0")
    ordinary = replace(child, result_item_id="ordinary-item", internal_message_id="qq:100:ordinary")
    child_evidence = EvidenceItem(
        "child-evidence", "内部消息候选", "存在匹配正文", "sufficient", (EvidenceSource("supports", child),),
    )
    ordinary_evidence = EvidenceItem(
        "ordinary-evidence", "普通消息来源", "存在普通正文", "sufficient", (EvidenceSource("supports", ordinary),),
    )
    artifact = AnswerArtifact(
        content_blocks=(AnswerContentBlock("answer", "只依据普通消息生成的结论。"),),
        citation_bindings=(CitationBinding("answer", ("ordinary-evidence",)),),
        evidence_items=(child_evidence, ordinary_evidence),
    )
    assert cited_message_sources(artifact) == (("answer", "ordinary-evidence", ordinary),)

    # 只有正文实际绑定该证据后，子消息来源才成为可计入验收的 Citation。
    bound = replace(artifact, citation_bindings=(CitationBinding("answer", ("child-evidence",)),))
    assert cited_message_sources(bound) == (("answer", "child-evidence", child),)


def test_visible_keyword_in_another_source_does_not_prove_target_body_is_visible() -> None:
    """来源在场但正文词被裁掉时，其他来源含同词也不能掩盖核验失败。"""

    child = _child()
    other = replace(child, internal_message_id="qq:100:another", normalized_content="远程连接的另一处讨论")
    envelope = _envelope((child, other), semantic=True)
    record = _record(envelope, ExecutionScope(allowed_session_ids=(child.session_id,)))
    projected = project_tool_result_for_model(envelope, record)
    first = projected["data"]["expanded_messages"][0]
    first["content"] = "前文被截断了…"
    assert visible_matching_sources(projected, record, {child.internal_message_id}, "远程连接") == ()
    first["content"] = child.normalized_content
    assert visible_matching_sources(projected, record, {child.internal_message_id}, "远程连接") == (first["source_id"],)
