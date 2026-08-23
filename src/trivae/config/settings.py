"""从环境变量读取模型配置，并保持密钥不进入可观测结果。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_SUPPORTED_PROVIDER = "deepseek"
_DEFAULT_MAX_TURNS = 8
_DEFAULT_MAX_TOOL_ROUNDS = 3
_DEFAULT_MAX_OUTPUT_TOKENS = 16384
_DEFAULT_COMPLETION_MAX_TOKENS = 2048


class SettingsError(ValueError):
    """模型运行所需配置缺失、非法或不受支持。"""


@dataclass(frozen=True)
class DeepSeekSettings:
    """DeepSeek OpenAI-compatible Chat Completions 的非敏感配置投影。"""

    api_key: str
    base_url: str
    provider: str
    model_name: str
    max_turns: int
    max_tool_rounds: int = _DEFAULT_MAX_TOOL_ROUNDS
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS
    completion_max_tokens: int = _DEFAULT_COMPLETION_MAX_TOKENS

    def __repr__(self) -> str:
        """调试时只显示密钥存在性，绝不显示密钥正文。"""

        return (
            "DeepSeekSettings("
            "api_key='[REDACTED]', "
            f"base_url={self.base_url!r}, provider={self.provider!r}, "
            f"model_name={self.model_name!r}, max_turns={self.max_turns!r}, "
            f"max_tool_rounds={self.max_tool_rounds!r}, "
            f"max_output_tokens={self.max_output_tokens!r}, "
            f"completion_max_tokens={self.completion_max_tokens!r})"
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
        }


def load_settings(environ: Mapping[str, str] | None = None) -> DeepSeekSettings:
    """在调用时读取并校验配置，不在模块导入时创建客户端。"""

    values = os.environ if environ is None else environ
    api_key = values.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SettingsError("DEEPSEEK_API_KEY is required when the DeepSeek provider is invoked")

    provider = values.get("TRIVAE_MODEL_PROVIDER", _SUPPORTED_PROVIDER).strip().lower()
    if provider != _SUPPORTED_PROVIDER:
        raise SettingsError(f"unsupported model provider: {provider or '<empty>'}")

    model_name = values.get("TRIVAE_MODEL_NAME", "").strip()
    if not model_name:
        raise SettingsError("TRIVAE_MODEL_NAME is required when the model is invoked")

    base_url = values.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).strip()
    if not base_url:
        raise SettingsError("DEEPSEEK_BASE_URL must not be empty")

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

    return DeepSeekSettings(
        api_key=api_key,
        base_url=base_url,
        provider=provider,
        model_name=model_name,
        max_turns=max_turns,
        max_tool_rounds=max_tool_rounds,
        max_output_tokens=max_output_tokens,
        completion_max_tokens=completion_max_tokens,
    )


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
