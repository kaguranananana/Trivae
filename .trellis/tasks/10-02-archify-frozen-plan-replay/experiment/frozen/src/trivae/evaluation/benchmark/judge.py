"""Benchmark Tier 2 Judge：atomic claim 切分 + citation 蕴含判定。

硬规则（design §6 / prd R4）：
- claim 单位 = atomic factual claim（Judge 先把 content block 切分为原子事实声明）。
  未做 atomic 切分的实现不得称 Grounded Claim Rate。
- 全部判定为 ``llm_assisted_provisional``；只有被人工逐条确认的 item 才置
  ``adjudicated=true``；抽查产出 judge-human agreement，不整组升级。
- citation 存在 ≠ citation 正确；verdict 词表显式，provider failure 直接上抛。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from openai import AsyncOpenAI, OpenAIError

from trivae.config.model_capabilities import resolve_reasoning_effort
from trivae.config.settings import ModelSettings
from trivae.evaluation.contracts import EvaluationContractError, _mapping, utc_now

JUDGE_RUBRIC_VERSION = "benchmark-judge-v1"
VERIFICATION_STATUS = "llm_assisted_provisional"

CITATION_VERDICTS = ("supported", "partially_supported", "unsupported", "insufficient_evidence")

_MAX_EVIDENCE_EXCERPTS = 20
_MAX_EXCERPT_CHARS = 400
_MAX_CLAIM_TEXT_CHARS = 500
_CLAIM_SYSTEM_PROMPT = """你是 Trivae benchmark 的 Tier 2 judge。输入是一个最终回答的
content blocks、每个 block 的 citation 绑定（指向的 evidence 摘要），以及 evidence 摘要文本。

任务（两部分，必须完整输出）：
1. atomic claims：把每个 block 切分为原子事实声明（每条只表达一个可独立核查的事实）。
   is_factual=false 表示该声明是过渡语/观点/程序性说明，不需要聊天记录证据支持。
   对每条 factual claim 判断当前 block 引用的 evidence 是否支持它（supported=true/false）。
   block 没有 citation 时，其 factual claims 一律 supported=false。
2. citation verdicts：对每个 citation 绑定（block → evidence ids），判断该 evidence 组合
   是否实际支持该 block 的陈述。verdict 取值：
   supported | partially_supported | unsupported | insufficient_evidence

规则：只能基于给出的 evidence 摘要判断，不得使用外部知识；evidence 摘要不含所需信息时
verdict 用 insufficient_evidence。对每个 content block 至少输出一条 atomic claim；
对输入的每个 citation 绑定恰好输出一条 verdict。
仅返回 JSON object：
{"claims":[{"block_id":"...","text":"...","is_factual":true,"supported":true}],
 "citations":[{"content_block_id":"...","evidence_ids":["..."],"verdict":"supported"}]}
"""


@dataclass(frozen=True)
class ClaimJudgment:
    """一条 atomic factual claim 的判定；adjudicated 只能由人工置位。"""

    block_id: str
    text: str
    is_factual: bool
    supported: bool | None
    verification_status: str = VERIFICATION_STATUS
    adjudicated: bool = False


@dataclass(frozen=True)
class CitationJudgment:
    """一个 citation 绑定（block → evidence ids）的蕴含判定。"""

    content_block_id: str
    evidence_ids: tuple[str, ...]
    verdict: str
    verification_status: str = VERIFICATION_STATUS
    adjudicated: bool = False


@dataclass(frozen=True)
class AnswerJudgment:
    """一次 run 的完整 Tier 2 判定 artifact。"""

    run_id: str
    case_id: str
    variant_id: str
    claims: tuple[ClaimJudgment, ...]
    citations: tuple[CitationJudgment, ...]
    judge_identity: str
    created_at: str
    verification_status: str = VERIFICATION_STATUS
    notes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("run_id", "case_id", "variant_id", "judge_identity", "created_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise EvaluationContractError(f"answer judgment {name} must be a non-empty string")
        if self.verification_status != VERIFICATION_STATUS:
            raise EvaluationContractError("LLM judgment cannot claim a status other than llm_assisted_provisional")

    @property
    def grounded_claim_rate(self) -> float | None:
        factual = [claim for claim in self.claims if claim.is_factual]
        if not factual:
            return None
        supported = sum(1 for claim in factual if claim.supported is True)
        return supported / len(factual)

    @property
    def citation_correctness(self) -> float | None:
        if not self.citations:
            return None
        supported = sum(1 for citation in self.citations if citation.verdict == "supported")
        return supported / len(self.citations)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "variant_id": self.variant_id,
            "claims": [
                {
                    "block_id": claim.block_id,
                    "text": claim.text,
                    "is_factual": claim.is_factual,
                    "supported": claim.supported,
                    "verification_status": claim.verification_status,
                    "adjudicated": claim.adjudicated,
                }
                for claim in self.claims
            ],
            "citations": [
                {
                    "content_block_id": citation.content_block_id,
                    "evidence_ids": list(citation.evidence_ids),
                    "verdict": citation.verdict,
                    "verification_status": citation.verification_status,
                    "adjudicated": citation.adjudicated,
                }
                for citation in self.citations
            ],
            "judge_identity": self.judge_identity,
            "created_at": self.created_at,
            "verification_status": self.verification_status,
            "grounded_claim_rate": self.grounded_claim_rate,
            "citation_correctness": self.citation_correctness,
            "notes": dict(self.notes),
        }


class LLMClaimJudge:
    """OpenAI-compatible 单次调用完成 claim 切分与 citation 蕴含判定。"""

    def __init__(self, settings: ModelSettings) -> None:
        if not isinstance(settings, ModelSettings):
            raise EvaluationContractError("LLMClaimJudge requires ModelSettings")
        self._settings = settings

    @property
    def identity(self) -> str:
        return f"{self._settings.provider}:{self._settings.model_name}:{JUDGE_RUBRIC_VERSION}"

    async def judge(
        self,
        *,
        run_id: str,
        case_id: str,
        variant_id: str,
        content_blocks: Sequence[Mapping[str, object]],
        citation_bindings: Sequence[Mapping[str, object]],
        evidence_excerpts: Mapping[str, str],
    ) -> AnswerJudgment:
        """对单次 run 的 bounded 投影执行 judge；输入不完整时显式拒绝。"""

        if not content_blocks:
            raise EvaluationContractError("judge requires content blocks")
        block_ids = [str(block.get("block_id")) for block in content_blocks]
        if any(not block_id or block_id == "None" for block_id in block_ids):
            raise EvaluationContractError("judge input block ids are invalid")
        bounded_excerpts = {
            message_id: excerpt[:_MAX_EXCERPT_CHARS]
            for message_id, excerpt in list(evidence_excerpts.items())[:_MAX_EVIDENCE_EXCERPTS]
        }
        payload = {
            "content_blocks": [dict(block) for block in content_blocks],
            "citation_bindings": [dict(binding) for binding in citation_bindings],
            "evidence_excerpts": dict(bounded_excerpts),
        }
        response_text = await self._complete(payload, session_id=run_id)
        claims, citations = _parse_judge_output(response_text, block_ids, citation_bindings)
        return AnswerJudgment(
            run_id=run_id,
            case_id=case_id,
            variant_id=variant_id,
            claims=claims,
            citations=citations,
            judge_identity=self.identity,
            created_at=utc_now(),
        )

    async def _complete(self, payload: Mapping[str, object], *, session_id: str) -> str:
        # OpenCode Go 按稳定会话标识路由；同一 Run 的 Judge 请求始终使用同一身份。
        headers = (
            {"x-opencode-session": session_id, "User-Agent": "trivae/0.1.0"}
            if self._settings.provider == "opencode-go"
            else None
        )
        # Judge 与 Runtime 共用精确 provider/model registry，不凭字符串猜测档位。
        reasoning_effort = resolve_reasoning_effort(
            provider=self._settings.provider,
            model_name=self._settings.model_name,
        )
        async with AsyncOpenAI(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
            default_headers=headers,
        ) as client:
            try:
                response = await client.chat.completions.create(
                    model=self._settings.model_name,
                    messages=[
                        {"role": "system", "content": _CLAIM_SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                    # Judge 产出完整 JSON，不受 Router/Planner 的短 completion budget 截断。
                    max_tokens=self._settings.max_output_tokens,
                    reasoning_effort=reasoning_effort,
                )
            except OpenAIError as exc:
                raise EvaluationContractError(f"benchmark judge provider failed: {type(exc).__name__}: {exc}") from exc
        if not response.choices:
            raise EvaluationContractError("benchmark judge response has no choices")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            # 空正文仍是失败；记录公开终止原因，区分预算截断与正常停止的空输出。
            raise EvaluationContractError(
                f"benchmark judge response has no JSON content; finish_reason={response.choices[0].finish_reason}"
            )
        return content


def _parse_judge_output(
    output: str,
    block_ids: Sequence[str],
    citation_bindings: Sequence[Mapping[str, object]],
) -> tuple[tuple[ClaimJudgment, ...], tuple[CitationJudgment, ...]]:
    """严格验证 judge JSON：claim 覆盖所有 block；verdict 覆盖所有 citation 绑定。"""

    try:
        decoded = json.loads(output)
    except json.JSONDecodeError as exc:
        raise EvaluationContractError("benchmark judge output is not valid JSON") from exc
    body = _mapping(decoded, "benchmark_judge_output")
    raw_claims = body.get("claims")
    raw_citations = body.get("citations")
    if not isinstance(raw_claims, Sequence) or isinstance(raw_claims, str):
        raise EvaluationContractError("benchmark judge claims must be an array")
    if not isinstance(raw_citations, Sequence) or isinstance(raw_citations, str):
        raise EvaluationContractError("benchmark judge citations must be an array")

    block_id_set = set(block_ids)
    claims: list[ClaimJudgment] = []
    covered_blocks: set[str] = set()
    for raw in raw_claims:
        item = _mapping(raw, "benchmark_judge_claim")
        block_id = item.get("block_id")
        text = item.get("text")
        if block_id not in block_id_set:
            raise EvaluationContractError(f"judge claim references unknown block {block_id!r}")
        covered_blocks.add(str(block_id))
        if not isinstance(text, str) or not text.strip():
            raise EvaluationContractError("judge claim text must be a non-empty string")
        supported = item.get("supported")
        if supported is not None and not isinstance(supported, bool):
            raise EvaluationContractError("judge claim supported must be boolean or null")
        claims.append(
            ClaimJudgment(
                block_id=str(block_id),
                text=text.strip()[:_MAX_CLAIM_TEXT_CHARS],
                is_factual=item.get("is_factual") is True,
                supported=supported,
            )
        )
    missing_blocks = block_id_set - covered_blocks
    if missing_blocks:
        raise EvaluationContractError(f"judge did not cover content blocks: {sorted(missing_blocks)!r}")

    expected_bindings: set[tuple[str, tuple[str, ...]]] = set()
    for binding in citation_bindings:
        evidence_raw = binding.get("evidence_ids") or ()
        if not isinstance(evidence_raw, Sequence) or isinstance(evidence_raw, str):
            raise EvaluationContractError("citation binding evidence_ids must be an array")
        expected_bindings.add(
            (
                str(binding.get("content_block_id")),
                tuple(str(e) for e in evidence_raw),
            )
        )
    seen_bindings: set[tuple[str, tuple[str, ...]]] = set()
    citations: list[CitationJudgment] = []
    for raw in raw_citations:
        item = _mapping(raw, "benchmark_judge_citation")
        content_block_id = str(item.get("content_block_id"))
        evidence_ids = tuple(str(e) for e in (item.get("evidence_ids") or ()))
        verdict = item.get("verdict")
        if verdict not in CITATION_VERDICTS:
            raise EvaluationContractError(f"judge citation verdict invalid: {verdict!r}")
        key = (content_block_id, evidence_ids)
        if key not in expected_bindings or key in seen_bindings:
            raise EvaluationContractError("judge citation output does not match input bindings exactly once")
        seen_bindings.add(key)
        citations.append(
            CitationJudgment(
                content_block_id=content_block_id,
                evidence_ids=evidence_ids,
                verdict=str(verdict),
            )
        )
    if seen_bindings != expected_bindings:
        raise EvaluationContractError("judge citation output missing one or more input bindings")
    return tuple(claims), tuple(citations)
