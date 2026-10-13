"""使用 OpenAI-compatible 模型完成 blind retrieval relevance 初筛。"""

from __future__ import annotations

import json
from collections.abc import Sequence

from openai import AsyncOpenAI, OpenAIError

from trivae.config.model_capabilities import resolve_reasoning_effort
from trivae.config.settings import ModelSettings

from .contracts import EvaluationContractError, _mapping, utc_now
from .retrieval_evaluation import (
    RETRIEVAL_RUBRIC_VERSION,
    BlindAnnotationPacket,
    BlindCandidate,
    RelevanceAnnotation,
    RelevanceAnnotationSet,
)

_ANNOTATION_SYSTEM_PROMPT = """你是 Trivae retrieval relevance 的盲标员。
你只能根据自然语言 query、候选消息和给定的 bounded surrounding context 判断相关性。
你看不到也不得猜测候选来自 lexical 还是 semantic、其排名、分数或 variant 身份。

标签定义：
- relevant：候选或上下文直接回答、支持或提供 query 所需的具体信息。
- partially_relevant：主题相关且有帮助，但信息间接、不完整或只覆盖问题的一部分。
- not_relevant：没有为 query 提供有用信息；仅共享宽泛词汇也算不相关。
- uncertain：上下文不足、指代不清、反讽/转述等导致无法可靠判断。

confidence 是 0 到 1 的单条判断自信度，不是人工一致率。notes 只写简短可审计理由，
不要输出长推理，不要声称这是 human ground truth。必须对输入中的每个 blind_id 恰好输出一次。
仅返回 JSON object：
{"labels":[{"blind_id":"...","label":"relevant|partially_relevant|not_relevant|uncertain","confidence":0.0,"notes":"..."}]}
"""


class LLMRetrievalAnnotator:
    """顺序执行 bounded blind batches；Provider failure 不触发静默重试或改标签。"""

    def __init__(self, settings: ModelSettings) -> None:
        if not isinstance(settings, ModelSettings):
            raise EvaluationContractError("LLMRetrievalAnnotator requires ModelSettings")
        # 此独立工具使用 Chat Completions，不能把订阅 OAuth 当成传统 API key 发送。
        if settings.provider == "chatgpt-plan":
            raise EvaluationContractError(
                "LLMRetrievalAnnotator does not support chatgpt-plan; "
                "use an explicit DeepSeek or OpenCode Go API key configuration for annotation"
            )
        self._settings = settings

    async def annotate(
        self,
        packet: BlindAnnotationPacket,
        *,
        batch_size: int = 12,
    ) -> RelevanceAnnotationSet:
        """按 query 分组盲标全部候选，并严格验证完整、一一对应的 JSON 输出。"""

        if not isinstance(packet, BlindAnnotationPacket):
            raise EvaluationContractError("annotate requires a BlindAnnotationPacket")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise EvaluationContractError("annotation batch_size must be positive")

        grouped: dict[str, list[BlindCandidate]] = {}
        query_order: list[str] = []
        for candidate in packet.candidates:
            if candidate.query_id not in grouped:
                grouped[candidate.query_id] = []
                query_order.append(candidate.query_id)
            grouped[candidate.query_id].append(candidate)

        annotations: list[RelevanceAnnotation] = []
        # OpenCode Go 需要稳定 session 标识和自有 User-Agent 才能接受 Go API 请求。
        default_headers = (
            {"x-opencode-session": "trivae-retrieval-annotation", "User-Agent": "trivae/0.1.0"}
            if self._settings.provider == "opencode-go"
            else None
        )
        async with AsyncOpenAI(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
            default_headers=default_headers,
        ) as client:
            for query_id in query_order:
                candidates = grouped[query_id]
                for offset in range(0, len(candidates), batch_size):
                    batch = tuple(candidates[offset : offset + batch_size])
                    annotations.extend(await self._annotate_batch(client, batch))

        expected_ids = {item.blind_id for item in packet.candidates}
        actual_ids = {item.blind_id for item in annotations}
        if expected_ids != actual_ids or len(annotations) != len(expected_ids):
            raise EvaluationContractError("LLM annotation did not cover every blind candidate exactly once")
        return RelevanceAnnotationSet(
            packet_id=packet.packet_id,
            snapshot_id=packet.snapshot_id,
            rubric_version=packet.rubric_version,
            annotator_type="llm_assisted",
            annotator_identity=(
                f"{self._settings.provider}:{self._settings.model_name}:"
                f"{RETRIEVAL_RUBRIC_VERSION}"
            ),
            created_at=utc_now(),
            annotations=tuple(annotations),
        )

    async def _annotate_batch(
        self,
        client: AsyncOpenAI,
        candidates: Sequence[BlindCandidate],
    ) -> tuple[RelevanceAnnotation, ...]:
        """发送不含 sealed metadata 的单批输入，并拒绝缺项、重复项或未知 ID。"""

        if not candidates:
            return ()
        query = candidates[0].query
        if any(item.query != query for item in candidates):
            raise EvaluationContractError("one annotation batch must contain one query")
        payload = {
            "query": query,
            "candidates": [
                {
                    "blind_id": item.blind_id,
                    "candidate": dict(item.candidate),
                    "context": [dict(context) for context in item.context],
                }
                for item in candidates
            ],
        }
        try:
            response = await client.chat.completions.create(
                model=self._settings.model_name,
                messages=[
                    {"role": "system", "content": _ANNOTATION_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                # 批量标签 JSON 属于评测输出，不能被 Router/Planner 的短预算截断。
                max_tokens=self._settings.max_output_tokens,
                # 盲标与 Judge/Runtime 使用同一已验证 reasoning contract。
                reasoning_effort=resolve_reasoning_effort(
                    provider=self._settings.provider,
                    model_name=self._settings.model_name,
                ),
            )
        except OpenAIError as exc:
            # 对外只保留异常类型；provider 原文可能含 request 或 endpoint 细节。
            raise EvaluationContractError(
                f"LLM annotation provider failed: {type(exc).__name__}"
            ) from exc
        if not response.choices:
            raise EvaluationContractError("LLM annotation response has no choices")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise EvaluationContractError("LLM annotation response has no JSON content")
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as exc:
            raise EvaluationContractError("LLM annotation response is not valid JSON") from exc
        body = _mapping(decoded, "llm_annotation_response")
        labels = body.get("labels")
        if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
            raise EvaluationContractError("LLM annotation response labels must be an array")

        expected_ids = {item.blind_id for item in candidates}
        output: list[RelevanceAnnotation] = []
        seen: set[str] = set()
        for raw in labels:
            item = _mapping(raw, "llm_annotation_label")
            blind_id = item.get("blind_id")
            if not isinstance(blind_id, str) or blind_id not in expected_ids:
                raise EvaluationContractError("LLM annotation returned an unknown blind_id")
            if blind_id in seen:
                raise EvaluationContractError("LLM annotation returned a duplicate blind_id")
            seen.add(blind_id)
            notes = item.get("notes", "")
            if not isinstance(notes, str):
                raise EvaluationContractError("LLM annotation notes must be a string")
            output.append(
                RelevanceAnnotation(
                    blind_id=blind_id,
                    label=item.get("label"),
                    confidence=item.get("confidence"),
                    notes=notes[:500],
                    verification_status="llm_assisted_provisional",
                )
            )
        if seen != expected_ids:
            raise EvaluationContractError("LLM annotation batch omitted one or more blind IDs")
        output.sort(key=lambda item: next(
            index for index, candidate in enumerate(candidates) if candidate.blind_id == item.blind_id
        ))
        return tuple(output)
