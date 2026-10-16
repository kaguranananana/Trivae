"""真实核验脚本必须检查正文 Citation，而不是只检查证据候选存在。"""

from dataclasses import replace

from scripts.verify_forward_retrieval import cited_message_sources
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    MessageSource,
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
