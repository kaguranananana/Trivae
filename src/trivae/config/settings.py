"""从环境变量读取模型配置，并保持密钥不进入可观测结果。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_SUPPORTED_PROVIDER = "deepseek"
_DEFAULT_MAX_TURNS = 8
_DEFAULT_MAX_TOOL_ROUNDS = 3


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

    def __repr__(self) -> str:
        """调试时只显示密钥存在性，绝不显示密钥正文。"""

        return (
            "DeepSeekSettings("
            "api_key='[REDACTED]', "
            f"base_url={self.base_url!r}, provider={self.provider!r}, "
            f"model_name={self.model_name!r}, max_turns={self.max_turns!r}, "
            f"max_tool_rounds={self.max_tool_rounds!r})"
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

    max_turns_text = values.get("TRIVAE_MAX_TURNS", str(_DEFAULT_MAX_TURNS)).strip()
    try:
        max_turns = int(max_turns_text)
    except ValueError as exc:
        raise SettingsError("TRIVAE_MAX_TURNS must be a positive integer") from exc
    if max_turns <= 0 or max_turns_text != str(max_turns):
        raise SettingsError("TRIVAE_MAX_TURNS must be a positive integer")

    max_tool_rounds_text = values.get("TRIVAE_MAX_TOOL_ROUNDS", str(_DEFAULT_MAX_TOOL_ROUNDS)).strip()
    try:
        max_tool_rounds = int(max_tool_rounds_text)
    except ValueError as exc:
        raise SettingsError("TRIVAE_MAX_TOOL_ROUNDS must be a positive integer") from exc
    if max_tool_rounds <= 0 or max_tool_rounds_text != str(max_tool_rounds):
        raise SettingsError("TRIVAE_MAX_TOOL_ROUNDS must be a positive integer")

    return DeepSeekSettings(
        api_key=api_key,
        base_url=base_url,
        provider=provider,
        model_name=model_name,
        max_turns=max_turns,
        max_tool_rounds=max_tool_rounds,
    )
