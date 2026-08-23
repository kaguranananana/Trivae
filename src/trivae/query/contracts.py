"""Query application layer 的输入、诊断和结果契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping

from trivae.capabilities.contracts import ExecutionScope
from trivae.query.evidence import AnswerArtifact, FinalizationErrorInfo
from trivae.query.runtime.contracts import AgentRunRequest, ModelContextMessage, RuntimeResult

if TYPE_CHECKING:
    from trivae.query.planner import Plan
    from trivae.query.router import RouteDecision


class QueryContractError(ValueError):
    """Query 请求违反应用层公开契约。"""


@dataclass(frozen=True)
class QueryContext:
    """Router/Planner 共用的无 provider 上下文投影。"""

    query: str
    locale: str
    prior_context: tuple[ModelContextMessage, ...]
    data_snapshot: Mapping[str, object]
    available_capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        """只校验应用层需要的普通值，不把 trusted scope 带入模型上下文。"""

        if not isinstance(self.query, str) or not self.query.strip():
            raise QueryContractError("query must be a non-empty string")
        if not isinstance(self.locale, str) or not self.locale.strip():
            raise QueryContractError("locale must be a non-empty string")
        if not isinstance(self.prior_context, tuple):
            raise QueryContractError("prior_context must be a tuple")
        if any(not isinstance(message, ModelContextMessage) for message in self.prior_context):
            raise QueryContractError("prior_context must contain ModelContextMessage values")
        if not isinstance(self.data_snapshot, Mapping):
            raise QueryContractError("data_snapshot must be a mapping")
        if not isinstance(self.available_capabilities, tuple):
            raise QueryContractError("available_capabilities must be a tuple")
        if any(not isinstance(name, str) or not name for name in self.available_capabilities):
            raise QueryContractError("available_capabilities must contain non-empty names")
        if len(set(self.available_capabilities)) != len(self.available_capabilities):
            raise QueryContractError("available_capabilities must not contain duplicates")
        object.__setattr__(self, "query", self.query.strip())
        object.__setattr__(self, "locale", self.locale.strip())


@dataclass(frozen=True)
class QueryRequest:
    """用户查询入口；scope 是可信本地对象，不会自动序列化到 prompt。"""

    query: str
    scope: ExecutionScope
    request_id: str | None = None
    locale: str = "zh-CN"
    prior_context: tuple[ModelContextMessage, ...] = ()
    data_snapshot: Mapping[str, object] = field(default_factory=dict)
    available_capabilities: tuple[str, ...] = ("search_messages",)
    conversation_id: str | None = None

    def __post_init__(self) -> None:
        """在应用入口校验并规范化查询字段，减少下游分支。"""

        if not isinstance(self.query, str) or not self.query.strip():
            raise QueryContractError("query must be a non-empty string")
        if not isinstance(self.scope, ExecutionScope):
            raise QueryContractError("scope must be an ExecutionScope")
        if self.request_id is not None:
            if not isinstance(self.request_id, str) or not self.request_id.strip():
                raise QueryContractError("request_id must be a non-empty string when provided")
            object.__setattr__(self, "request_id", self.request_id.strip())
        if self.conversation_id is not None:
            if not isinstance(self.conversation_id, str) or not self.conversation_id.strip():
                raise QueryContractError("conversation_id must be a non-empty string when provided")
            object.__setattr__(self, "conversation_id", self.conversation_id.strip())
        object.__setattr__(self, "query", self.query.strip())
        QueryContext(
            query=self.query,
            locale=self.locale,
            prior_context=self.prior_context,
            data_snapshot=self.data_snapshot,
            available_capabilities=self.available_capabilities,
        )

    def to_context(self) -> QueryContext:
        """生成 Router/Planner 输入；显式丢弃 scope，保持模型边界清晰。"""

        return QueryContext(
            query=self.query,
            locale=self.locale,
            prior_context=self.prior_context,
            data_snapshot=self.data_snapshot,
            available_capabilities=self.available_capabilities,
        )

    def to_runtime_request(self, plan_guidance: str | None = None) -> AgentRunRequest:
        """将应用请求编译为同一 Runtime 的输入，不改变 trusted scope identity。"""

        return AgentRunRequest(
            query=self.query,
            scope=self.scope,
            available_capabilities=self.available_capabilities,
            model_context=self.prior_context,
            plan_guidance=plan_guidance,
            request_id=self.request_id,
        )


@dataclass(frozen=True)
class QueryDiagnostic:
    """Router/Planner/Runtime 的安全降级记录。"""

    stage: str
    code: str
    message: str
    degraded: bool = True


@dataclass(frozen=True)
class QueryResult:
    """Query Orchestrator 的稳定结果，保留 route/plan/runtime 三段证据。"""

    runtime_result: RuntimeResult
    route_decision: "RouteDecision"
    plan: "Plan | None" = None
    diagnostics: tuple[QueryDiagnostic, ...] = ()
    # 只有 finalizer 成功后该字段才非空，形成 M5 的 validated commit boundary。
    answer_artifact: AnswerArtifact | None = None
    finalization_error: FinalizationErrorInfo | None = None
    conversation_id: str | None = None

    @property
    def final_answer(self) -> str | None:
        """只返回已经通过 finalization 的回答文本。"""

        return None if self.answer_artifact is None else self.answer_artifact.answer_text

    @property
    def runtime_answer(self) -> str | None:
        """保留低层 Runtime 原始文本投影，供诊断使用而不冒充 validated answer。"""

        return self.runtime_result.final_answer

    @property
    def is_successful(self) -> bool:
        """只有 Runtime completed 且 Answer Artifact 已验证才算 Query 成功。"""

        return (
            self.runtime_result.termination == "completed"
            and self.answer_artifact is not None
            and self.finalization_error is None
        )

    @property
    def termination(self) -> str:
        """返回 runtime termination，避免调用者依赖具体 adapter。"""

        return self.runtime_result.termination
