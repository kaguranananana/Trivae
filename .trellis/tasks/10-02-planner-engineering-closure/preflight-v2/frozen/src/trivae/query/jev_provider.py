"""OpenRouter Decisions API adapter for the Router's bounded Jev Choice."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from trivae.config.settings import RouterJevSettings
from trivae.query.contracts import QueryContext
from trivae.query.router import (
    RouterDecisionProviderError,
    RouterProviderResult,
    router_context_projection,
)

_DECISION_PATH = "/alpha/decisions"
_CHOICE_QUESTION = "route"
_ROUTE_CRITERIA = {
    "standard_execution": (
        "A direct lookup, count, ranking, aggregation, or summary; multiple data operations "
        "alone do not justify a separate Planner."
    ),
    "planned_execution": (
        "A dependent multi-stage investigation where earlier evidence changes later steps, "
        "temporal evolution reasoning, evidence-dependent investigation, or explicit recovery."
    ),
}


class JevRouteDecisionProvider:
    """把 OpenRouter 的 Decisions 响应隔离为 Trivae 自有的 route projection。"""

    def __init__(self, settings: RouterJevSettings, *, client: Any | None = None) -> None:
        """保存独立配置并允许测试注入最小 `.post()` transport。"""

        self._settings = settings
        self._client = client
        # 生产环境创建的 client 由本适配器关闭；注入的 client 仍归调用方管理。
        self._owns_client = client is None
        self._closed = False

    async def decide(self, context: QueryContext) -> RouterProviderResult:
        """发送相同 Router context projection，并只返回已校验的 bounded Choice。"""

        # 缺少 Router 专属 key 只在实际调用时显式失败，不影响应用或主模型启动。
        if not self._settings.api_key:
            raise RouterDecisionProviderError("JEV_ROUTER_API_KEY_MISSING")
        # 关闭后的 client 不会被静默重建，生命周期错误保留为 provider unavailable。
        if self._closed:
            raise RouterDecisionProviderError("JEV_ROUTER_PROVIDER_UNAVAILABLE")
        # state 只由 Router 已允许的 query/locale/history/data snapshot 组成。
        request_body = {
            "model": self._settings.model,
            "state": router_context_projection(context),
            "questions": {
                _CHOICE_QUESTION: {
                    "type": "choice",
                    "instructions": (
                        "Choose whether this query should enter the separate Planner before the "
                        "shared Agent Runtime. Judge dependent planning value, not wording, time "
                        "span, message count, or Tool count."
                    ),
                    "criteria": _ROUTE_CRITERIA,
                }
            },
        }
        # 调用已安装的 OpenAI SDK transport；不新建 HTTP stack 或依赖 SDK 私有类型。
        try:
            response = await self._get_client().post(
                _DECISION_PATH,
                cast_to=dict[str, object],
                body=request_body,
            )
        except APITimeoutError as exc:
            raise RouterDecisionProviderError("JEV_ROUTER_TIMEOUT") from exc
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise RouterDecisionProviderError("JEV_ROUTER_AUTH_ERROR") from exc
        except RateLimitError as exc:
            raise RouterDecisionProviderError("JEV_ROUTER_RATE_LIMITED") from exc
        except NotFoundError as exc:
            raise RouterDecisionProviderError("JEV_ROUTER_MODEL_UNAVAILABLE") from exc
        except APIConnectionError as exc:
            raise RouterDecisionProviderError("JEV_ROUTER_NETWORK_ERROR") from exc
        except APIResponseValidationError as exc:
            raise RouterDecisionProviderError(
                "JEV_ROUTER_INVALID_RESPONSE",
                diagnostic_type=type(exc).__name__,
            ) from exc
        except APIStatusError as exc:
            # OpenRouter 的上游/服务状态只投影为稳定码，不保存可能含原始响应的 body。
            code = (
                "JEV_ROUTER_PROVIDER_UNAVAILABLE"
                if exc.status_code in {402, 500, 502, 503, 524, 529}
                else "JEV_ROUTER_PROVIDER_ERROR"
            )
            raise RouterDecisionProviderError(code) from exc
        except Exception as exc:
            # 未分类 SDK/transport 故障也有稳定归属；异常正文不进入 Trace 或 artifact。
            raise RouterDecisionProviderError(
                "JEV_ROUTER_PROVIDER_ERROR",
                diagnostic_type=type(exc).__name__,
            ) from exc
        # 网络调用成功不代表 contract 成功；结构验证在 adapter boundary 完成。
        return self._parse_response(response)

    def _get_client(self) -> Any:
        """按配置 endpoint 懒建一个 OpenAI SDK async client。"""

        if self._client is not None:
            return self._client
        # endpoint 已由 Settings 校验；这里拆出 API root，SDK 负责 JSON 与 Bearer transport。
        endpoint = urlsplit(self._settings.endpoint)
        root_path = endpoint.path.removesuffix(_DECISION_PATH).rstrip("/")
        base_url = f"{endpoint.scheme}://{endpoint.netloc}{root_path}"
        self._client = AsyncOpenAI(
            api_key=self._settings.api_key,
            base_url=base_url,
            timeout=10.0,
            max_retries=0,
        )
        return self._client

    def _parse_response(self, payload: object) -> RouterProviderResult:
        """验证 Decisions Choice，并只保留 route、概率、confidence 与实际 usage。"""

        # 顶层、answers 和指定 answer 都必须是对象，避免对异常 SDK 值做隐式猜测。
        if not isinstance(payload, Mapping):
            raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
        answers = payload.get("answers")
        answer = answers.get(_CHOICE_QUESTION) if isinstance(answers, Mapping) else None
        if not isinstance(answer, Mapping) or answer.get("type") != "choice":
            raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
        # API 返回的 Choice 名称与 Trivae 的两路标签必须完全一致。
        route = answer.get("choice")
        if route not in _ROUTE_CRITERIA:
            raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
        # confidence 是 Jev 返回的分布集中度，不用 winning probability 替代。
        confidence = _probability(answer.get("confidence"))
        probabilities_value = answer.get("probabilities")
        if not isinstance(probabilities_value, Mapping) or set(probabilities_value) != set(_ROUTE_CRITERIA):
            raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
        # 两个 option probability 必须有界且构成一组分布；仅保存这两个已知标签。
        probabilities = {
            label: _probability(probabilities_value[label])
            for label in _ROUTE_CRITERIA
        }
        if not math.isclose(math.fsum(probabilities.values()), 1.0, abs_tol=0.02):
            raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
        # usage/cost 是 OpenRouter 实际返回时才记录；不在适配器中估算或补造。
        usage = _project_usage(payload.get("usage"))
        resolved_model = payload.get("model")
        if resolved_model is None:
            resolved_model = self._settings.model
        elif (
            not isinstance(resolved_model, str)
            or not resolved_model.startswith(self._settings.model)
            or len(resolved_model) > 256
        ):
            raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
        return RouterProviderResult(
            route=route,
            confidence=confidence,
            probabilities=probabilities,
            usage=usage,
            provider="openrouter",
            model=resolved_model.strip(),
        )

    async def aclose(self) -> None:
        """释放 SDK transport；注入的测试 transport 由测试管理。"""

        if self._closed:
            return
        self._closed = True
        if self._owns_client and isinstance(self._client, AsyncOpenAI):
            await self._client.close()
            self._client = None


def _probability(value: object) -> float:
    """只接受有限的 [0, 1] 数值，拒绝 bool 和非数值 provider 字段。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
    return number


def _project_usage(value: object) -> dict[str, int | float] | None:
    """复制实际 token/cost 字段，不保留 provider 的任意 metadata。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
    projected: dict[str, int | float] = {}
    # 只复制 OpenRouter Decisions schema 中的输入/输出 token 和真实 cost。
    for field_name in ("input_tokens", "output_tokens"):
        if field_name not in value:
            continue
        count = value[field_name]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
        projected[field_name] = count
    if "cost" in value:
        cost = value["cost"]
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or float(cost) < 0
        ):
            raise RouterDecisionProviderError("JEV_ROUTER_INVALID_RESPONSE")
        projected["cost"] = float(cost)
    return projected or None
