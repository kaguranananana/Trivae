"""从环境变量读取 OpenAI-compatible 模型配置，并保持密钥不进入可观测结果。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, cast

from trivae.config.limits import (
    DEFAULT_MAX_TOOL_RESULT_PERCENT,
    DEFAULT_MAX_TOOL_RESULT_TOKENS,
    ToolResultBudgetMode,
)

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEFAULT_PROVIDER = "deepseek"
_SUPPORTED_PROVIDERS = frozenset({"deepseek", "opencode-go"})
_DEFAULT_MAX_TURNS = 8
_DEFAULT_MAX_TOOL_ROUNDS = 3
_DEFAULT_MAX_OUTPUT_TOKENS = 16384
_DEFAULT_COMPLETION_MAX_TOKENS = 2048


class SettingsError(ValueError):
    """模型运行所需配置缺失、非法或不受支持。"""


@dataclass(frozen=True)
class ModelSettings:
    """OpenAI-compatible Chat Completions 的配置和运行预算。"""

    api_key: str
    base_url: str
    provider: str
    model_name: str
    max_turns: int
    max_tool_rounds: int = _DEFAULT_MAX_TOOL_ROUNDS
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS
    completion_max_tokens: int = _DEFAULT_COMPLETION_MAX_TOKENS
    tool_result_budget_mode: ToolResultBudgetMode = "fixed"
    model_context_window_tokens: int | None = None
    max_tool_result_percent: int = DEFAULT_MAX_TOOL_RESULT_PERCENT
    max_tool_result_tokens: int = DEFAULT_MAX_TOOL_RESULT_TOKENS

    def __repr__(self) -> str:
        """调试时只显示密钥存在性，绝不显示密钥正文。"""

        return (
            "ModelSettings("
            "api_key='[REDACTED]', "
            f"base_url={self.base_url!r}, provider={self.provider!r}, "
            f"model_name={self.model_name!r}, max_turns={self.max_turns!r}, "
            f"max_tool_rounds={self.max_tool_rounds!r}, "
            f"max_output_tokens={self.max_output_tokens!r}, "
            f"completion_max_tokens={self.completion_max_tokens!r}, "
            f"tool_result_budget_mode={self.tool_result_budget_mode!r}, "
            f"model_context_window_tokens={self.model_context_window_tokens!r}, "
            f"max_tool_result_percent={self.max_tool_result_percent!r}, "
            f"max_tool_result_tokens={self.max_tool_result_tokens!r})"
        )

    def to_safe_dict(self) -> dict[str, object]:
        """返回可用于日志或测试快照的非敏感配置。"""

        return {
            "api_key_configured": bool(self.api_key),
            "base_url": self.base_url,
            "provider": self.provider,
            "model_name": self.model_name,
            "max_turns": self.max_turns,
            "max_tool_rounds": self.max_tool_rounds,
            "max_output_tokens": self.max_output_tokens,
            "completion_max_tokens": self.completion_max_tokens,
            "tool_result_budget_mode": self.tool_result_budget_mode,
            "model_context_window_tokens": self.model_context_window_tokens,
            "max_tool_result_percent": self.max_tool_result_percent,
            "max_tool_result_tokens": self.max_tool_result_tokens,
        }


DeepSeekSettings = ModelSettings


def load_settings(environ: Mapping[str, str] | None = None) -> ModelSettings:
    """在调用时读取并校验配置，不在模块导入时创建客户端。"""

    values = os.environ if environ is None else environ

    # 没有显式 provider 时保留旧版 DeepSeek 默认，避免旧 smoke/evaluation 无法启动。
    provider = values.get("TRIVAE_MODEL_PROVIDER", _DEFAULT_PROVIDER).strip().lower()
    if provider not in _SUPPORTED_PROVIDERS:
        raise SettingsError(f"unsupported model provider: {provider or '<empty>'}")

    # 新 key 是唯一通用入口；只有 DeepSeek 才允许按字段读取 legacy key。
    api_key = _provider_value(
        values,
        provider,
        "TRIVAE_MODEL_API_KEY",
        "DEEPSEEK_API_KEY",
        label="API key",
    )

    model_name = values.get("TRIVAE_MODEL_NAME", "").strip()
    if not model_name:
        raise SettingsError("TRIVAE_MODEL_NAME is required when the model is invoked")

    # 新 generic 配置必须明确 URL；仅 legacy-only DeepSeek 保留历史默认 URL。
    legacy_only_deepseek = provider == "deepseek" and "TRIVAE_MODEL_API_KEY" not in values
    base_url = _provider_value(
        values,
        provider,
        "TRIVAE_MODEL_BASE_URL",
        "DEEPSEEK_BASE_URL",
        label="base URL",
        default=DEFAULT_DEEPSEEK_BASE_URL if legacy_only_deepseek else None,
    )

    max_turns = _positive_integer(values, "TRIVAE_MAX_TURNS", _DEFAULT_MAX_TURNS)
    max_tool_rounds = _positive_integer(values, "TRIVAE_MAX_TOOL_ROUNDS", _DEFAULT_MAX_TOOL_ROUNDS)
    max_output_tokens = _positive_integer(
        values,
        "TRIVAE_MAX_OUTPUT_TOKENS",
        _DEFAULT_MAX_OUTPUT_TOKENS,
    )
    completion_max_tokens = _positive_integer(
        values,
        "TRIVAE_COMPLETION_MAX_TOKENS",
        _DEFAULT_COMPLETION_MAX_TOKENS,
    )
    tool_result_budget_mode = _budget_mode(values)
    model_context_window_tokens = _optional_positive_integer(
        values,
        "TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS",
    )
    max_tool_result_percent = _bounded_percentage(values)
    max_tool_result_tokens = _positive_integer(
        values,
        "TRIVAE_MAX_TOOL_RESULT_TOKENS",
        DEFAULT_MAX_TOOL_RESULT_TOKENS,
    )

    return ModelSettings(
        api_key=api_key,
        base_url=base_url,
        provider=provider,
        model_name=model_name,
        max_turns=max_turns,
        max_tool_rounds=max_tool_rounds,
        max_output_tokens=max_output_tokens,
        completion_max_tokens=completion_max_tokens,
        tool_result_budget_mode=tool_result_budget_mode,
        model_context_window_tokens=model_context_window_tokens,
        max_tool_result_percent=max_tool_result_percent,
        max_tool_result_tokens=max_tool_result_tokens,
    )


def _provider_value(
    values: Mapping[str, str],
    provider: str,
    new_name: str,
    legacy_name: str,
    *,
    label: str,
    default: str | None = None,
) -> str:
    """按 new-first 规则读取一个 Provider 字段，并显式拒绝空值。"""

    # 变量存在但为空时也必须走新变量的校验，不能悄悄借用旧变量掩盖配置冲突。
    if new_name in values:
        value = values[new_name].strip()
        if not value:
            raise SettingsError(f"{new_name} must not be empty")
        return value

    # legacy 变量只对 DeepSeek 生效，OpenCode Go 不会误用旧凭据或旧端点。
    if provider == "deepseek" and legacy_name in values:
        value = values[legacy_name].strip()
        if not value:
            raise SettingsError(f"{legacy_name} must not be empty")
        return value

    # 只有明确保留的旧 DeepSeek 默认值可以在这里生效。
    if default is not None:
        return default
    raise SettingsError(f"{new_name} is required when the {label} is used")


def _positive_integer(values: Mapping[str, str], name: str, default: int) -> int:
    """读取一个有界执行预算；格式错误必须在 provider 调用前暴露。"""

    # 读取原始文本而不是静默转换，避免例如 `2.0` 被当成合法预算。
    raw = values.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a positive integer") from exc
    # 保留正数和规范十进制表示，避免不同文本产生相同但不可追踪的配置。
    if value <= 0 or raw != str(value):
        raise SettingsError(f"{name} must be a positive integer")
    return value


def _optional_positive_integer(values: Mapping[str, str], name: str) -> int | None:
    """读取可选的显式 context window；缺失表示 context 未经验证。"""

    if name not in values:
        return None
    raw = values[name].strip()
    if not raw:
        raise SettingsError(f"{name} must not be empty when provided")
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a positive integer") from exc
    if value <= 0 or raw != str(value):
        raise SettingsError(f"{name} must be a positive integer")
    return value


def _budget_mode(values: Mapping[str, str]) -> ToolResultBudgetMode:
    """读取严格的 fixed/dynamic 模式，不接受未知模式的静默降级。"""

    raw = values.get("TRIVAE_TOOL_RESULT_BUDGET_MODE", "fixed").strip().lower()
    if raw not in {"fixed", "dynamic"}:
        raise SettingsError("TRIVAE_TOOL_RESULT_BUDGET_MODE must be fixed or dynamic")
    return cast(ToolResultBudgetMode, raw)


def _bounded_percentage(values: Mapping[str, str]) -> int:
    """读取 dynamic pool 百分比，确保公式输入在可解释范围内。"""

    raw = values.get(
        "TRIVAE_MAX_TOOL_RESULT_PERCENT",
        str(DEFAULT_MAX_TOOL_RESULT_PERCENT),
    ).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError("TRIVAE_MAX_TOOL_RESULT_PERCENT must be an integer from 1 to 100") from exc
    if value < 1 or value > 100 or raw != str(value):
        raise SettingsError("TRIVAE_MAX_TOOL_RESULT_PERCENT must be an integer from 1 to 100")
    return value
