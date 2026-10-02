"""已验证的模型能力和 context window 解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ContextWindowSource = Literal[
    "explicit_config",
    "verified_model_registry",
    "fallback",
    "not_used",
]
ReasoningEffort = Literal["low", "high", "max"]


class ModelCapabilityError(ValueError):
    """模型能力注册或 context 解析输入违反契约。"""


@dataclass(frozen=True)
class VerifiedModelMetadata:
    """一条已经通过外部验证、可以参与预算计算的模型能力事实。"""

    provider: str
    model_name: str
    context_window_tokens: int
    reasoning_effort: ReasoningEffort | None = None

    def __post_init__(self) -> None:
        """只接受有意义的 provider/model 和正整数 context，拒绝伪精确值。"""

        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ModelCapabilityError("provider must be a non-empty string")
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ModelCapabilityError("model_name must be a non-empty string")
        if (
            isinstance(self.context_window_tokens, bool)
            or not isinstance(self.context_window_tokens, int)
            or self.context_window_tokens <= 0
        ):
            raise ModelCapabilityError("context_window_tokens must be a positive integer")
        if self.reasoning_effort not in {None, "low", "high", "max"}:
            raise ModelCapabilityError("reasoning_effort must be low, high, max, or None")
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "model_name", self.model_name.strip())


class ModelCapabilityRegistry:
    """按 provider/model 精确查找 verified metadata，不在 Runtime 分散模型特判。"""

    def __init__(self, metadata: tuple[VerifiedModelMetadata, ...] = ()) -> None:
        """建立不可变查找表，并在注册阶段拒绝重复 identity。"""

        if not isinstance(metadata, tuple):
            raise ModelCapabilityError("metadata must be a tuple")
        index: dict[tuple[str, str], VerifiedModelMetadata] = {}
        for item in metadata:
            if not isinstance(item, VerifiedModelMetadata):
                raise ModelCapabilityError("metadata must contain VerifiedModelMetadata values")
            key = self._key(item.provider, item.model_name)
            if key in index:
                raise ModelCapabilityError("verified model metadata identity must be unique")
            index[key] = item
        self._metadata = index

    @staticmethod
    def _key(provider: str, model_name: str) -> tuple[str, str]:
        """只做 identity 的大小写归一化，不从名称推导任何未注册能力。"""

        return provider.strip().casefold(), model_name.strip().casefold()

    def resolve(self, provider: str, model_name: str) -> VerifiedModelMetadata | None:
        """返回精确匹配的 verified metadata；未知组合明确返回 None。"""

        if not isinstance(provider, str) or not isinstance(model_name, str):
            raise ModelCapabilityError("provider and model_name must be strings")
        return self._metadata.get(self._key(provider, model_name))


@dataclass(frozen=True)
class ContextWindowResolution:
    """把 context 数值和事实来源绑定，供预算和 Trace 共同消费。"""

    context_window_tokens: int | None
    source: ContextWindowSource

    def __post_init__(self) -> None:
        """确保 source 与 context 是否存在相互一致，避免 Trace 产生矛盾事实。"""

        if self.source not in {
            "explicit_config",
            "verified_model_registry",
            "fallback",
            "not_used",
        }:
            raise ModelCapabilityError(f"unsupported context window source: {self.source!r}")
        if self.context_window_tokens is not None and (
            isinstance(self.context_window_tokens, bool)
            or not isinstance(self.context_window_tokens, int)
            or self.context_window_tokens <= 0
        ):
            raise ModelCapabilityError("context_window_tokens must be a positive integer when present")
        if self.source in {"explicit_config", "verified_model_registry"} and self.context_window_tokens is None:
            raise ModelCapabilityError(f"{self.source} requires context_window_tokens")
        if self.source in {"fallback", "not_used"} and self.context_window_tokens is not None:
            raise ModelCapabilityError(f"{self.source} cannot carry a context window")


DEFAULT_MODEL_CAPABILITY_REGISTRY = ModelCapabilityRegistry(
    (
        # 官方 DeepSeek 文档确认当前 deepseek-flash 支持 1M context；low 是本项目为
        # 保留最终 JSON 输出预算而显式选择的请求档位，不把 provider 默认 high 带入 Runtime。
        VerifiedModelMetadata(
            provider="deepseek",
            model_name="deepseek-flash",
            context_window_tokens=1_000_000,
            reasoning_effort="low",
        ),
        # 这是历史 OpenCode Go / DeepSeek V4 Flash 运行身份，不能与官方 identity 合并。
        VerifiedModelMetadata(
            provider="opencode-go",
            model_name="deepseek-v4-flash",
            context_window_tokens=1_000_000,
            reasoning_effort="low",
        ),
    )
)


def resolve_context_window(
    *,
    explicit_context_window_tokens: int | None,
    provider: str,
    model_name: str,
    registry: ModelCapabilityRegistry = DEFAULT_MODEL_CAPABILITY_REGISTRY,
) -> ContextWindowResolution:
    """按 explicit → verified registry → fallback 的固定优先级解析 context。"""

    if explicit_context_window_tokens is not None:
        if (
            isinstance(explicit_context_window_tokens, bool)
            or not isinstance(explicit_context_window_tokens, int)
            or explicit_context_window_tokens <= 0
        ):
            raise ModelCapabilityError("explicit context window must be a positive integer")
        return ContextWindowResolution(explicit_context_window_tokens, "explicit_config")
    metadata = registry.resolve(provider, model_name)
    if metadata is not None:
        return ContextWindowResolution(metadata.context_window_tokens, "verified_model_registry")
    return ContextWindowResolution(None, "fallback")


def resolve_reasoning_effort(
    *,
    provider: str,
    model_name: str,
    registry: ModelCapabilityRegistry = DEFAULT_MODEL_CAPABILITY_REGISTRY,
) -> ReasoningEffort | None:
    """只为已精确登记的 provider/model 返回 reasoning 档位，未知组合不猜测。"""

    metadata = registry.resolve(provider, model_name)
    return None if metadata is None else metadata.reasoning_effort
