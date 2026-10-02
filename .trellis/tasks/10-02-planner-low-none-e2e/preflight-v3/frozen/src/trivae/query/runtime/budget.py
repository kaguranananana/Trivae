"""Runtime 内一次 Agent run 共享的 Tool Result 投影预算。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from trivae.config.limits import (
    DEFAULT_PER_CALL_TOOL_RESULT_CAP,
    DEFAULT_PER_CALL_TOOL_RESULT_PERCENT,
    DEFAULT_RUN_TOOL_EVIDENCE_CAP,
    DEFAULT_RUN_TOOL_EVIDENCE_PERCENT,
    DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
    ToolResultBudgetMode,
)
from trivae.config.model_capabilities import ContextWindowSource

BudgetResolution = Literal["fixed_compatibility", "dynamic_configured", "dynamic_fallback"]


class ToolResultBudgetError(ValueError):
    """Tool Result 预算配置、预留或结算违反契约。"""


class ToolResultBudgetExhausted(ToolResultBudgetError):
    """一次动态 run 的共享 Tool Evidence pool 已经没有可分配预算。"""


@dataclass(frozen=True)
class ToolResultBudgetConfig:
    """从 settings 复制出的不可变预算配置，明确区分单次 ceiling 与累计 pool。"""

    # 默认 dynamic；fixed 只作为显式回归/调试开关，不由未知 context 隐式触发。
    mode: ToolResultBudgetMode = "dynamic"
    context_window_tokens: int | None = None
    context_window_source: ContextWindowSource | None = None
    per_call_tool_result_percent: int = DEFAULT_PER_CALL_TOOL_RESULT_PERCENT
    per_call_tool_result_cap: int = DEFAULT_PER_CALL_TOOL_RESULT_CAP
    run_tool_evidence_percent: int = DEFAULT_RUN_TOOL_EVIDENCE_PERCENT
    run_tool_evidence_cap: int = DEFAULT_RUN_TOOL_EVIDENCE_CAP
    # 该值只用于显式实验/校准；run_tool_evidence_budget property 是 Runtime 唯一消费入口。
    run_tool_evidence_budget_override: int | None = None
    fallback_per_call_budget: int = DEFAULT_TOOL_RESULT_TOKEN_BUDGET
    fallback_run_tool_evidence_budget: int = DEFAULT_TOOL_RESULT_TOKEN_BUDGET

    def __post_init__(self) -> None:
        """在 Runtime 创建前校验两套预算及 context source 的一致性。"""

        if self.mode not in {"fixed", "dynamic"}:
            raise ToolResultBudgetError(f"unsupported tool result budget mode: {self.mode!r}")
        if self.context_window_tokens is not None:
            _require_positive_integer(self.context_window_tokens, "context_window_tokens")
        _require_percentage(self.per_call_tool_result_percent, "per_call_tool_result_percent")
        _require_positive_integer(self.per_call_tool_result_cap, "per_call_tool_result_cap")
        _require_percentage(self.run_tool_evidence_percent, "run_tool_evidence_percent")
        _require_positive_integer(self.run_tool_evidence_cap, "run_tool_evidence_cap")
        if self.run_tool_evidence_budget_override is not None:
            _require_positive_integer(
                self.run_tool_evidence_budget_override,
                "run_tool_evidence_budget_override",
            )
        _require_positive_integer(self.fallback_per_call_budget, "fallback_per_call_budget")
        _require_positive_integer(
            self.fallback_run_tool_evidence_budget,
            "fallback_run_tool_evidence_budget",
        )

        source = self.context_window_source
        if source is None:
            source = (
                "not_used"
                if self.mode == "fixed"
                else "explicit_config"
                if self.context_window_tokens is not None
                else "fallback"
            )
            object.__setattr__(self, "context_window_source", source)
        if source not in {"explicit_config", "verified_model_registry", "fallback", "not_used"}:
            raise ToolResultBudgetError(f"unsupported context window source: {source!r}")
        if self.mode == "fixed":
            if source != "not_used" or self.context_window_tokens is not None:
                raise ToolResultBudgetError("fixed budget must not consume a context window")
            if self.run_tool_evidence_budget_override is not None:
                raise ToolResultBudgetError("fixed budget must not configure a run evidence pool")
        else:
            if source in {"explicit_config", "verified_model_registry"} and self.context_window_tokens is None:
                raise ToolResultBudgetError(f"{source} requires context_window_tokens")
            if source in {"fallback", "not_used"} and self.context_window_tokens is not None:
                raise ToolResultBudgetError(f"{source} cannot carry context_window_tokens")
            if self.context_window_tokens is None and self.run_tool_evidence_budget_override is not None:
                # 未知模型必须保留 16k shared pool，不能用显式 pool 绕过能力验证。
                raise ToolResultBudgetError(
                    "run_tool_evidence_budget requires a resolved context window"
                )
            resolved_run_budget = self.run_tool_evidence_budget
            if resolved_run_budget is None or resolved_run_budget <= 0:
                raise ToolResultBudgetError("dynamic context window produces no positive run evidence budget")
            if self.per_call_ceiling <= 0:
                raise ToolResultBudgetError("dynamic context window produces no positive per-call budget")

    @property
    def budget_resolution(self) -> BudgetResolution:
        """区分 fixed 基线、已知 context 计算和未知 context 安全 fallback。"""

        if self.mode == "fixed":
            return "fixed_compatibility"
        return "dynamic_configured" if self.context_window_tokens is not None else "dynamic_fallback"

    @property
    def run_tool_evidence_budget(self) -> int | None:
        """计算一次 Run 的共享 pool；显式实验值优先于通用公式。"""

        if self.mode == "fixed":
            return None
        if self.context_window_tokens is None:
            # 未知 context 不做伪精确计算，per-call/run 都使用 16k 安全边界。
            return self.fallback_run_tool_evidence_budget
        if self.run_tool_evidence_budget_override is not None:
            return self.run_tool_evidence_budget_override
        calculated = (self.context_window_tokens * self.run_tool_evidence_percent) // 100
        return min(calculated, self.run_tool_evidence_cap)

    @property
    def per_call_ceiling(self) -> int:
        """返回单次 Tool projection 可申请的 ceiling，不代表 Run 剩余余额。"""

        if self.mode == "fixed" or self.context_window_tokens is None:
            return self.fallback_per_call_budget
        calculated = (self.context_window_tokens * self.per_call_tool_result_percent) // 100
        return min(calculated, self.per_call_tool_result_cap)

    def new_policy(self) -> ToolResultBudgetPolicy:
        """为每次 Runtime run 创建隔离的 mutable accounting state。"""

        return ToolResultBudgetPolicy(self)


@dataclass(frozen=True)
class ToolResultBudgetCall:
    """一次已预留的 per-call budget，供 projection 完成后按实际 token 结算。"""

    reservation_id: int
    remaining_run_tool_evidence_budget_before: int | None
    effective_per_call_budget: int


@dataclass(frozen=True)
class ToolResultBudgetSnapshot:
    """一次 Tool Result projection 的完整 per-call/run-level 预算归因。"""

    budget_mode: ToolResultBudgetMode
    context_window_tokens: int | None
    context_window_source: ContextWindowSource
    per_call_tool_result_percent: int
    per_call_tool_result_cap: int
    run_tool_evidence_percent: int
    run_tool_evidence_cap: int
    run_tool_evidence_budget: int | None
    per_call_tool_result_ceiling: int
    remaining_run_tool_evidence_budget_before_call: int | None
    effective_per_call_tool_result_budget: int
    projected_tool_result_tokens: int
    remaining_run_tool_evidence_budget_after_call: int | None
    truncated: bool
    omitted_context_messages: int
    omitted_hit_messages: int
    budget_resolution: BudgetResolution

    def to_dict(self) -> dict[str, object]:
        """生成 Trace/Evaluation 可安全保存的普通值，避免含义不清的旧字段。"""

        return {
            "budget_mode": self.budget_mode,
            "context_window_tokens": self.context_window_tokens,
            "context_window_source": self.context_window_source,
            "per_call_tool_result_percent": self.per_call_tool_result_percent,
            "per_call_tool_result_cap": self.per_call_tool_result_cap,
            "run_tool_evidence_percent": self.run_tool_evidence_percent,
            "run_tool_evidence_cap": self.run_tool_evidence_cap,
            "run_tool_evidence_budget": self.run_tool_evidence_budget,
            "per_call_tool_result_ceiling": self.per_call_tool_result_ceiling,
            "remaining_run_tool_evidence_budget_before_call": self.remaining_run_tool_evidence_budget_before_call,
            "effective_per_call_tool_result_budget": self.effective_per_call_tool_result_budget,
            "projected_tool_result_tokens": self.projected_tool_result_tokens,
            "remaining_run_tool_evidence_budget_after_call": self.remaining_run_tool_evidence_budget_after_call,
            "truncated": self.truncated,
            "omitted_context_messages": self.omitted_context_messages,
            "omitted_hit_messages": self.omitted_hit_messages,
            "budget_resolution": self.budget_resolution,
        }


@dataclass
class ToolResultBudgetPolicy:
    """单次 run 的 Tool Result 预算账本；policy 不跨 run 复用。"""

    config: ToolResultBudgetConfig
    _remaining: int | None = field(init=False)
    _next_reservation_id: int = field(default=0, init=False)
    _reservations: dict[int, ToolResultBudgetCall] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """初始化共享 pool，保证每个 RuntimeContext 都从独立余额开始。"""

        self._remaining = self.config.run_tool_evidence_budget

    @property
    def remaining_run_tool_evidence_budget(self) -> int | None:
        """返回尚未被完成 projection 消耗的共享余额。"""

        return self._remaining

    def begin_call(self) -> ToolResultBudgetCall:
        """先预留本次 ceiling，再允许 Tool 执行，避免调用间超卖共享 pool。"""

        self._next_reservation_id += 1
        reservation_id = self._next_reservation_id
        remaining_before = self._remaining
        if self._remaining is None:
            effective_budget = self.config.per_call_ceiling
        else:
            if self._remaining <= 0:
                raise ToolResultBudgetExhausted(
                    "dynamic Tool Result run evidence budget is exhausted before the next tool call"
                )
            effective_budget = min(self.config.per_call_ceiling, self._remaining)
            self._remaining -= effective_budget
        reservation = ToolResultBudgetCall(
            reservation_id=reservation_id,
            remaining_run_tool_evidence_budget_before=remaining_before,
            effective_per_call_budget=effective_budget,
        )
        self._reservations[reservation_id] = reservation
        return reservation

    def complete_call(
        self,
        reservation: ToolResultBudgetCall,
        *,
        projected_tool_result_tokens: int,
        truncated: bool,
        omitted_context_messages: int,
        omitted_hit_messages: int,
    ) -> ToolResultBudgetSnapshot:
        """按实际 projection estimate 结算，并生成不可变的 Trace 快照。"""

        # 先读取而不是立即删除 reservation，保证非法结算不会丢失预留状态。
        stored = self._reservations.get(reservation.reservation_id)
        if stored != reservation:
            raise ToolResultBudgetError("Tool Result budget reservation is unknown or already completed")
        _require_non_negative_integer(projected_tool_result_tokens, "projected_tool_result_tokens")
        _require_non_negative_integer(omitted_context_messages, "omitted_context_messages")
        _require_non_negative_integer(omitted_hit_messages, "omitted_hit_messages")
        if not isinstance(truncated, bool):
            raise ToolResultBudgetError("truncated must be a boolean")
        if projected_tool_result_tokens > reservation.effective_per_call_budget:
            raise ToolResultBudgetError("projected Tool Result exceeds its effective per-call budget")

        # 所有输入校验通过后才消费 reservation，失败路径不会造成 shared pool 泄漏。
        self._reservations.pop(reservation.reservation_id)
        remaining_after = self._remaining
        if self._remaining is not None:
            # 预留时先扣除 ceiling；这里退回未使用部分，最终只按实际 estimate 扣减。
            self._remaining += reservation.effective_per_call_budget - projected_tool_result_tokens
            remaining_after = self._remaining
        return ToolResultBudgetSnapshot(
            budget_mode=self.config.mode,
            context_window_tokens=self.config.context_window_tokens,
            context_window_source=self.config.context_window_source or "fallback",
            per_call_tool_result_percent=self.config.per_call_tool_result_percent,
            per_call_tool_result_cap=self.config.per_call_tool_result_cap,
            run_tool_evidence_percent=self.config.run_tool_evidence_percent,
            run_tool_evidence_cap=self.config.run_tool_evidence_cap,
            run_tool_evidence_budget=self.config.run_tool_evidence_budget,
            per_call_tool_result_ceiling=self.config.per_call_ceiling,
            remaining_run_tool_evidence_budget_before_call=(
                reservation.remaining_run_tool_evidence_budget_before
            ),
            effective_per_call_tool_result_budget=reservation.effective_per_call_budget,
            projected_tool_result_tokens=projected_tool_result_tokens,
            remaining_run_tool_evidence_budget_after_call=remaining_after,
            truncated=truncated,
            omitted_context_messages=omitted_context_messages,
            omitted_hit_messages=omitted_hit_messages,
            budget_resolution=self.config.budget_resolution,
        )


def _require_percentage(value: object, field_name: str) -> None:
    """校验百分比，拒绝 bool 这种 Python 整数子类。"""

    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise ToolResultBudgetError(f"{field_name} must be an integer from 1 to 100")


def _require_positive_integer(value: object, field_name: str) -> None:
    """校验正整数配置，拒绝 bool 这种 Python 整数子类。"""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ToolResultBudgetError(f"{field_name} must be a positive integer")


def _require_non_negative_integer(value: object, field_name: str) -> None:
    """校验 projection 产生的非负计数。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ToolResultBudgetError(f"{field_name} must be a non-negative integer")
