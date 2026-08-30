"""Controlled Variant 身份与 Baseline/Candidate diff。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Mapping

from trivae.query.contracts import ExecutionOverride

from .contracts import EvaluationContractError, _json_safe, _mapping, _text, _texts

VariantRole = Literal["last_stable", "minimal_control", "forced_standard", "forced_planned", "candidate"]

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret",
    "password",
    "private_key",
    "credential",
    "credentials",
}
_NORMALIZED_SENSITIVE_KEYS = {key.replace("_", "") for key in _SENSITIVE_KEYS}
_SENSITIVE_KEY_FRAGMENTS = (
    "apikey",
    "authorization",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "secret",
    "password",
    "privatekey",
    "credential",
)


def _normalize(value: object, path: str = "config") -> object:
    """递归排序 JSON 配置并拒绝 secret，保证 fingerprint 只含可公开实验身份。"""

    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise EvaluationContractError(f"{path} contains an invalid configuration key")
            normalized_key = key.lower().replace("_", "").replace("-", "")
            if key.lower() in _SENSITIVE_KEYS or normalized_key in _NORMALIZED_SENSITIVE_KEYS or any(
                fragment in normalized_key for fragment in _SENSITIVE_KEY_FRAGMENTS
            ):
                raise EvaluationContractError(f"{path}.{key} must not contain secrets")
            normalized[key] = _normalize(nested, f"{path}.{key}")
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (tuple, list)):
        return [_normalize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    _json_safe(value, path)
    return value


@dataclass(frozen=True)
class ControlledVariant:
    """所有会影响结果的受控配置；不接受漂移的 main/current defaults 身份。"""

    variant_id: str
    code_version: str
    provider: str
    model: str
    role: VariantRole = "candidate"
    model_parameters: Mapping[str, object] = field(default_factory=dict)
    prompt_identity: str = "prompt-unknown"
    router_configuration: Mapping[str, object] = field(default_factory=dict)
    planner_configuration: Mapping[str, object] = field(default_factory=dict)
    runtime_configuration: Mapping[str, object] = field(default_factory=dict)
    available_tools: tuple[str, ...] = ("search_messages",)
    retrieval_configuration: Mapping[str, object] = field(default_factory=dict)
    index_identity: str = "index-unknown"
    context_expansion_configuration: Mapping[str, object] = field(default_factory=dict)
    evidence_citation_version: str = "evidence-citation-unknown"
    budget: Mapping[str, object] = field(default_factory=dict)
    execution_override: ExecutionOverride = field(default_factory=ExecutionOverride)
    extra_configuration: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("variant_id", "code_version", "provider", "model", "prompt_identity", "index_identity", "evidence_citation_version"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.role not in ("last_stable", "minimal_control", "forced_standard", "forced_planned", "candidate"):
            raise EvaluationContractError("variant role is invalid")
        for field_name in (
            "model_parameters",
            "router_configuration",
            "planner_configuration",
            "runtime_configuration",
            "retrieval_configuration",
            "context_expansion_configuration",
            "budget",
            "extra_configuration",
        ):
            normalized = _normalize(_mapping(getattr(self, field_name), field_name), field_name)
            object.__setattr__(self, field_name, normalized)
        object.__setattr__(self, "available_tools", _texts(self.available_tools, "available_tools"))
        if not isinstance(self.execution_override, ExecutionOverride):
            raise EvaluationContractError("variant execution_override is invalid")

    def configuration_dict(self) -> dict[str, object]:
        """返回 fingerprint/diff 使用的 canonical configuration。"""

        return {
            "code_version": self.code_version,
            "provider": self.provider,
            "model": self.model,
            "role": self.role,
            "model_parameters": self.model_parameters,
            "prompt_identity": self.prompt_identity,
            "router_configuration": self.router_configuration,
            "planner_configuration": self.planner_configuration,
            "runtime_configuration": self.runtime_configuration,
            "available_tools": self.available_tools,
            "retrieval_configuration": self.retrieval_configuration,
            "index_identity": self.index_identity,
            "context_expansion_configuration": self.context_expansion_configuration,
            "evidence_citation_version": self.evidence_citation_version,
            "budget": self.budget,
            "execution_override": self.execution_override.to_dict(),
            "extra_configuration": self.extra_configuration,
        }

    @property
    def fingerprint(self) -> str:
        """以 canonical normalized config 作为稳定文本身份，不使用密码学哈希。"""

        normalized = _normalize(self.configuration_dict())
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def identity(self) -> str:
        """Variant ID 与 fingerprint 同时用于结果追溯。"""

        return f"{self.variant_id}:{self.fingerprint}"

    def to_dict(self) -> dict[str, object]:
        return {
            "variant_id": self.variant_id,
            "role": self.role,
            "code_version": self.code_version,
            "provider": self.provider,
            "model": self.model,
            "model_parameters": dict(self.model_parameters),
            "prompt_identity": self.prompt_identity,
            "router_configuration": dict(self.router_configuration),
            "planner_configuration": dict(self.planner_configuration),
            "runtime_configuration": dict(self.runtime_configuration),
            "available_tools": list(self.available_tools),
            "retrieval_configuration": dict(self.retrieval_configuration),
            "index_identity": self.index_identity,
            "context_expansion_configuration": dict(self.context_expansion_configuration),
            "evidence_citation_version": self.evidence_citation_version,
            "budget": dict(self.budget),
            "execution_override": self.execution_override.to_dict(),
            "extra_configuration": dict(self.extra_configuration),
            "variant_fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> ControlledVariant:
        payload = _mapping(value, "controlled_variant")
        override_payload = payload.get("execution_override", {})
        if not isinstance(override_payload, Mapping):
            raise EvaluationContractError("controlled_variant.execution_override must be an object")
        return cls(
            variant_id=payload.get("variant_id"),
            role=payload.get("role", "candidate"),
            code_version=payload.get("code_version"),
            provider=payload.get("provider"),
            model=payload.get("model"),
            model_parameters=payload.get("model_parameters", {}),
            prompt_identity=payload.get("prompt_identity", "prompt-unknown"),
            router_configuration=payload.get("router_configuration", {}),
            planner_configuration=payload.get("planner_configuration", {}),
            runtime_configuration=payload.get("runtime_configuration", {}),
            available_tools=tuple(payload.get("available_tools", ("search_messages",))),
            retrieval_configuration=payload.get("retrieval_configuration", {}),
            index_identity=payload.get("index_identity", "index-unknown"),
            context_expansion_configuration=payload.get("context_expansion_configuration", {}),
            evidence_citation_version=payload.get("evidence_citation_version", "evidence-citation-unknown"),
            budget=payload.get("budget", {}),
            execution_override=ExecutionOverride(
                forced_route=override_payload.get("forced_route"),
                context_window_limit=override_payload.get("context_window_limit"),
            ),
            extra_configuration=payload.get("extra_configuration", {}),
        )


def _diff_values(baseline: object, candidate: object, path: str, output: dict[str, object]) -> None:
    """递归记录配置差异，不用单个关键词猜测 root cause。"""

    if isinstance(baseline, Mapping) and isinstance(candidate, Mapping):
        keys = sorted(set(baseline) | set(candidate))
        for key in keys:
            next_path = f"{path}.{key}" if path else str(key)
            if key not in baseline:
                output[next_path] = {"baseline": None, "candidate": candidate[key]}
            elif key not in candidate:
                output[next_path] = {"baseline": baseline[key], "candidate": None}
            else:
                _diff_values(baseline[key], candidate[key], next_path, output)
        return
    if baseline != candidate:
        output[path] = {"baseline": baseline, "candidate": candidate}


def variant_diff(baseline: ControlledVariant, candidate: ControlledVariant) -> dict[str, object]:
    """生成可追溯的 Baseline/Candidate 显式 diff。"""

    if not isinstance(baseline, ControlledVariant) or not isinstance(candidate, ControlledVariant):
        raise EvaluationContractError("variant_diff requires ControlledVariant values")
    if baseline.fingerprint == candidate.fingerprint:
        raise EvaluationContractError("baseline and candidate configurations are identical")
    output: dict[str, object] = {}
    _diff_values(baseline.configuration_dict(), candidate.configuration_dict(), "", output)
    return output
