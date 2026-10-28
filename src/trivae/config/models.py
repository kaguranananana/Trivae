"""Small, secret-free model registry shared by normal queries and Eval."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml  # type: ignore[import-untyped]

DEFAULT_MODELS_PATH = Path(__file__).resolve().parents[3] / "config" / "models.yaml"
MODEL_PROVIDERS = frozenset({"deepseek", "opencode-go", "chatgpt-plan"})
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_MODEL_KEYS = {"provider", "model", "base_url", "auth", "parameters"}
_PARAMETER_KEYS = {"reasoning_effort", "max_output_tokens", "completion_max_tokens", "model_context_window_tokens"}


class ModelConfigurationError(ValueError):
    """The model registry is missing, malformed, or names unsupported capabilities."""


@dataclass(frozen=True)
class ModelProfile:
    """Resolved non-secret model identity and authentication reference."""

    profile_id: str
    provider: str
    model: str
    base_url: str
    auth_type: str
    auth_env: str | None
    reasoning_effort: str | None
    max_output_tokens: int | None
    completion_max_tokens: int | None
    model_context_window_tokens: int | None

    def to_safe_dict(self) -> dict[str, object]:
        """Return the selected profile without credentials or private auth state."""

        auth: dict[str, str] = {"type": self.auth_type}
        if self.auth_env is not None:
            auth["env"] = self.auth_env
        result: dict[str, object] = {
            "id": self.profile_id,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "auth": auth,
        }
        parameters = {
            key: value
            for key, value in {
                "reasoning_effort": self.reasoning_effort,
                "max_output_tokens": self.max_output_tokens,
                "completion_max_tokens": self.completion_max_tokens,
                "model_context_window_tokens": self.model_context_window_tokens,
            }.items()
            if value is not None
        }
        if parameters:
            result["parameters"] = parameters
        return result


@dataclass(frozen=True)
class ModelCatalog:
    """Validated model profiles and their small set of role defaults."""

    profiles: Mapping[str, ModelProfile]
    query_default: str
    agent_default: str
    judge_default: str

    def select(self, role: str, profile_id: str | None = None) -> ModelProfile:
        """Resolve an explicit profile or the configured default for a known role."""

        if profile_id is None:
            if role == "query":
                profile_id = self.query_default
            elif role == "agent":
                profile_id = self.agent_default
            elif role == "judge":
                profile_id = self.judge_default
            else:
                raise ModelConfigurationError("model role must be query, agent, or judge")
        try:
            return self.profiles[profile_id]
        except KeyError as exc:
            raise ModelConfigurationError(f"unknown model profile: {profile_id}") from exc


def load_model_catalog(path: Path = DEFAULT_MODELS_PATH) -> ModelCatalog:
    """Load and validate the deliberately small YAML profile format."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ModelConfigurationError(f"cannot read model configuration: {path}") from exc
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ModelConfigurationError(f"cannot parse model configuration: {path}") from exc
    if not isinstance(raw, Mapping) or set(raw) - {"models", "defaults", "evaluation"}:
        raise ModelConfigurationError("model configuration must contain only models, defaults, and evaluation")

    raw_models = raw.get("models")
    if not isinstance(raw_models, Mapping) or not raw_models:
        raise ModelConfigurationError("model configuration must define at least one model")
    profiles = {str(profile_id): _parse_profile(str(profile_id), value) for profile_id, value in raw_models.items()}

    defaults = raw.get("defaults", {})
    evaluation = raw.get("evaluation", {})
    if not isinstance(defaults, Mapping) or set(defaults) - {"query"}:
        raise ModelConfigurationError("defaults may define only query")
    if not isinstance(evaluation, Mapping) or set(evaluation) - {"agent", "judge"}:
        raise ModelConfigurationError("evaluation may define only agent and judge")
    query = _profile_reference(defaults.get("query"), "defaults.query", profiles)
    agent = _profile_reference(evaluation.get("agent"), "evaluation.agent", profiles)
    judge = _profile_reference(evaluation.get("judge"), "evaluation.judge", profiles)
    return ModelCatalog(profiles=profiles, query_default=query, agent_default=agent, judge_default=judge)


def _parse_profile(profile_id: str, raw: Any) -> ModelProfile:
    if not profile_id or not isinstance(raw, Mapping) or set(raw) - _MODEL_KEYS:
        raise ModelConfigurationError(f"invalid model profile: {profile_id or '<empty>'}")
    provider = _required_string(raw, "provider", profile_id).lower()
    model = _required_string(raw, "model", profile_id)
    if provider not in MODEL_PROVIDERS:
        raise ModelConfigurationError(f"unsupported provider in model profile: {profile_id}")

    auth = raw.get("auth")
    if not isinstance(auth, Mapping) or set(auth) - {"type", "env"}:
        raise ModelConfigurationError(f"invalid authentication reference in model profile: {profile_id}")
    auth_type = auth.get("type")
    if provider == "chatgpt-plan":
        if auth_type != "chatgpt_oauth" or "env" in auth:
            raise ModelConfigurationError(f"chatgpt-plan requires chatgpt_oauth authentication: {profile_id}")
        configured_url = raw.get("base_url")
        if configured_url is not None and configured_url != "https://api.openai.com/v1":
            raise ModelConfigurationError(f"chatgpt-plan must use the official Responses endpoint: {profile_id}")
        base_url = "https://api.openai.com/v1"
        auth_env = None
    else:
        auth_env = auth.get("env")
        if auth_type != "api_key" or not isinstance(auth_env, str) or _ENV_NAME.fullmatch(auth_env) is None:
            raise ModelConfigurationError(f"API-key provider requires auth.env: {profile_id}")
        base_url = _required_string(raw, "base_url", profile_id)
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ModelConfigurationError(f"invalid base_url in model profile: {profile_id}")

    parameters = raw.get("parameters", {})
    if not isinstance(parameters, Mapping) or set(parameters) - _PARAMETER_KEYS:
        raise ModelConfigurationError(f"unsupported model parameters in profile: {profile_id}")
    effort = parameters.get("reasoning_effort")
    if effort is not None:
        from trivae.config.model_capabilities import CHATGPT_REASONING_EFFORTS

        if not isinstance(effort, str) or effort not in CHATGPT_REASONING_EFFORTS.get((provider, model), frozenset()):
            raise ModelConfigurationError(f"unsupported reasoning_effort in model profile: {profile_id}")
    max_output_tokens = _positive_optional(parameters, "max_output_tokens", profile_id)
    completion_max_tokens = _positive_optional(parameters, "completion_max_tokens", profile_id)
    model_context_window_tokens = _positive_optional(parameters, "model_context_window_tokens", profile_id)

    return ModelProfile(
        profile_id=profile_id,
        provider=provider,
        model=model,
        base_url=base_url,
        auth_type=auth_type,
        auth_env=auth_env,
        reasoning_effort=effort,
        max_output_tokens=max_output_tokens,
        completion_max_tokens=completion_max_tokens,
        model_context_window_tokens=model_context_window_tokens,
    )


def _required_string(raw: Mapping[str, Any], name: str, profile_id: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ModelConfigurationError(f"model profile {profile_id} requires {name}")
    return value.strip()


def _positive_optional(raw: Mapping[str, Any], name: str, profile_id: str) -> int | None:
    value = raw.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ModelConfigurationError(f"{name} in model profile {profile_id} must be a positive integer")
    return value


def _profile_reference(value: Any, field: str, profiles: Mapping[str, ModelProfile]) -> str:
    if not isinstance(value, str) or value not in profiles:
        raise ModelConfigurationError(f"{field} must name a configured model profile")
    return value
