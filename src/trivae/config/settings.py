"""从环境变量读取 OpenAI-compatible 模型配置，并保持密钥不进入可观测结果。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, cast
from urllib.parse import urlsplit

from trivae.config.limits import (
    DEFAULT_PER_CALL_TOOL_RESULT_CAP,
    DEFAULT_PER_CALL_TOOL_RESULT_PERCENT,
    DEFAULT_RUN_TOOL_EVIDENCE_CAP,
    DEFAULT_RUN_TOOL_EVIDENCE_PERCENT,
    ToolResultBudgetMode,
)

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEFAULT_PROVIDER = "deepseek"
_SUPPORTED_PROVIDERS = frozenset({"deepseek", "opencode-go"})
_DEFAULT_MAX_TURNS = 8
_DEFAULT_MAX_TOOL_ROUNDS = 3
_DEFAULT_MAX_OUTPUT_TOKENS = 16384
_DEFAULT_COMPLETION_MAX_TOKENS = 2048
_DEFAULT_ROUTER_JEV_ENABLED = True
_DEFAULT_ROUTER_JEV_MODEL = "typesafe/jev-1.13"
_DEFAULT_ROUTER_JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
_DEFAULT_ROUTER_JEV_MODE = "shadow"


class SettingsError(ValueError):
    """模型运行所需配置缺失、非法或不受支持。"""


@dataclass(frozen=True)
class ModelSettings:
    """OpenAI-compatible Chat Completions 的配置和分离式运行预算。"""

    api_key: str
    base_url: str
    provider: str
    model_name: str
    max_turns: int
    max_tool_rounds: int = _DEFAULT_MAX_TOOL_ROUNDS
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS
    completion_max_tokens: int = _DEFAULT_COMPLETION_MAX_TOKENS
    tool_result_budget_mode: ToolResultBudgetMode = "dynamic"
    model_context_window_tokens: int | None = None
    per_call_tool_result_percent: int = DEFAULT_PER_CALL_TOOL_RESULT_PERCENT
    per_call_tool_result_cap: int = DEFAULT_PER_CALL_TOOL_RESULT_CAP
    run_tool_evidence_percent: int = DEFAULT_RUN_TOOL_EVIDENCE_PERCENT
    run_tool_evidence_cap: int = DEFAULT_RUN_TOOL_EVIDENCE_CAP
    run_tool_evidence_budget: int | None = None

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
            f"per_call_tool_result_percent={self.per_call_tool_result_percent!r}, "
            f"per_call_tool_result_cap={self.per_call_tool_result_cap!r}, "
            f"run_tool_evidence_percent={self.run_tool_evidence_percent!r}, "
            f"run_tool_evidence_cap={self.run_tool_evidence_cap!r}, "
            f"run_tool_evidence_budget={self.run_tool_evidence_budget!r})"
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
            "per_call_tool_result_percent": self.per_call_tool_result_percent,
            "per_call_tool_result_cap": self.per_call_tool_result_cap,
            "run_tool_evidence_percent": self.run_tool_evidence_percent,
            "run_tool_evidence_cap": self.run_tool_evidence_cap,
            "run_tool_evidence_budget": self.run_tool_evidence_budget,
        }


@dataclass(frozen=True)
class RouterJevSettings:
    """Router 专用 Jev 配置；与 Planner/Runtime 的 ModelSettings 完全分离。"""

    api_key: str
    enabled: bool
    model: str
    endpoint: str
    mode: str

    def __repr__(self) -> str:
        """调试配置时只显示 key 是否存在，不显示 key 正文。"""

        return (
            "RouterJevSettings("
            f"api_key={'[REDACTED]' if self.api_key else '[MISSING]'!r}, "
            f"enabled={self.enabled!r}, model={self.model!r}, "
            f"endpoint={self.endpoint!r}, mode={self.mode!r})"
        )

    def to_safe_dict(self) -> dict[str, object]:
        """返回可进入配置诊断的值，不包含密钥正文。"""

        return {
            "api_key_configured": bool(self.api_key),
            "enabled": self.enabled,
            "model": self.model,
            "endpoint": self.endpoint,
            "mode": self.mode,
        }


DeepSeekSettings = ModelSettings


def load_router_jev_settings(environ: Mapping[str, str] | None = None) -> RouterJevSettings:
    """只读取 Router Jev 专用环境变量，不修改或继承主模型 Provider 配置。"""

    # 让调用方可以用独立 mapping 测试配置，同时生产默认只读取进程环境。
    values = os.environ if environ is None else environ
    # 仅把空白去掉后放入配置对象；密钥缺失不阻止应用启动。
    api_key = values.get("OPENROUTER_API_KEY", "").strip()
    # enabled 使用显式布尔词，避免拼错时静默启动或关闭实验。
    enabled_raw = values.get("TRIVIAE_ROUTER_JEV_ENABLED", str(_DEFAULT_ROUTER_JEV_ENABLED)).strip().lower()
    if enabled_raw not in {"true", "false"}:
        raise SettingsError("TRIVIAE_ROUTER_JEV_ENABLED must be true or false")
    # model 与 endpoint 保持在 Router 专用配置中，不能借用 TRIVIAE_MODEL_NAME/BASE_URL。
    model = values.get("TRIVIAE_ROUTER_JEV_MODEL", _DEFAULT_ROUTER_JEV_MODEL).strip()
    endpoint = values.get("TRIVIAE_ROUTER_JEV_ENDPOINT", _DEFAULT_ROUTER_JEV_ENDPOINT).strip()
    # mode 只允许当前支持的 A/B/shadow 选项，避免出现未定义的路由语义。
    mode = values.get("TRIVIAE_ROUTER_JEV_MODE", _DEFAULT_ROUTER_JEV_MODE).strip().lower()
    if mode not in {"existing_llm", "jev", "shadow"}:
        raise SettingsError("TRIVIAE_ROUTER_JEV_MODE must be existing_llm, jev, or shadow")
    # 空模型和非 Decisions HTTPS endpoint 在任何 Provider 请求前显式报配置错误。
    if not model:
        raise SettingsError("TRIVIAE_ROUTER_JEV_MODEL must not be empty")
    parsed_endpoint = urlsplit(endpoint)
    if (
        parsed_endpoint.scheme != "https"
        or not parsed_endpoint.netloc
        or not parsed_endpoint.path.endswith("/alpha/decisions")
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise SettingsError("TRIVIAE_ROUTER_JEV_ENDPOINT must be an HTTPS OpenRouter Decisions endpoint")
    # 返回专属设置；OPENROUTER_API_KEY 不会覆盖 ModelSettings 的 API key。
    return RouterJevSettings(
        api_key=api_key,
        enabled=enabled_raw == "true",
        model=model,
        endpoint=endpoint,
        mode=mode,
    )


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
    max_output_tokens = _positive_integer(values, "TRIVAE_MAX_OUTPUT_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS)
    completion_max_tokens = _positive_integer(
        values,
        "TRIVAE_COMPLETION_MAX_TOKENS",
        _DEFAULT_COMPLETION_MAX_TOKENS,
    )
    tool_result_budget_mode = _budget_mode(values)
    model_context_window_tokens = _optional_positive_integer(values, "TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS")
    per_call_tool_result_percent = _bounded_percentage(
        values,
        "TRIVAE_PER_CALL_TOOL_RESULT_PERCENT",
        DEFAULT_PER_CALL_TOOL_RESULT_PERCENT,
    )
    per_call_tool_result_cap = _positive_integer(
        values,
        "TRIVAE_PER_CALL_TOOL_RESULT_CAP",
        DEFAULT_PER_CALL_TOOL_RESULT_CAP,
    )
    run_tool_evidence_percent = _bounded_percentage(
        values,
        "TRIVAE_RUN_TOOL_EVIDENCE_PERCENT",
        DEFAULT_RUN_TOOL_EVIDENCE_PERCENT,
    )
    run_tool_evidence_cap = _positive_integer(
        values,
        "TRIVAE_RUN_TOOL_EVIDENCE_CAP",
        DEFAULT_RUN_TOOL_EVIDENCE_CAP,
    )
    run_tool_evidence_budget = _optional_positive_integer(values, "TRIVAE_RUN_TOOL_EVIDENCE_BUDGET")

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
        per_call_tool_result_percent=per_call_tool_result_percent,
        per_call_tool_result_cap=per_call_tool_result_cap,
        run_tool_evidence_percent=run_tool_evidence_percent,
        run_tool_evidence_cap=run_tool_evidence_cap,
        run_tool_evidence_budget=run_tool_evidence_budget,
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
    """读取可选的正整数；缺失表示没有显式覆盖。"""

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

    raw = values.get("TRIVAE_TOOL_RESULT_BUDGET_MODE", "dynamic").strip().lower()
    if raw not in {"fixed", "dynamic"}:
        raise SettingsError("TRIVAE_TOOL_RESULT_BUDGET_MODE must be fixed or dynamic")
    return cast(ToolResultBudgetMode, raw)


def _bounded_percentage(values: Mapping[str, str], name: str, default: int) -> int:
    """读取一套 dynamic 预算百分比，确保每个参数的错误名称可定位。"""

    raw = values.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer from 1 to 100") from exc
    if value < 1 or value > 100 or raw != str(value):
        raise SettingsError(f"{name} must be an integer from 1 to 100")
    return value
