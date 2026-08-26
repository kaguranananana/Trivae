"""Runtime 内一次 Agent run 共享的 Tool Result 投影预算。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from trivae.config.limits import (
    DEFAULT_MAX_TOOL_RESULT_PERCENT,
    DEFAULT_MAX_TOOL_RESULT_TOKENS,
    DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
    ToolResultBudgetMode,
)

ContextWindowSource = Literal["explicit_config", "fallback", "not_used"]
BudgetResolution = Literal["configured", "fallback_fixed"]


class ToolResultBudgetError(ValueError):
    """Tool Result 预算配置、预留或结算违反契约。"""


class ToolResultBudgetExhausted(ToolResultBudgetError):
    """一次动态 run 的共享 Tool Result pool 已经没有可分配预算。"""


@dataclass(frozen=True)
class ToolResultBudgetConfig:
    """从 settings 复制出的不可变预算配置，不读取模型名称猜测 context window。"""

    mode: ToolResultBudgetMode = "fixed"
    context_window_tokens: int | None = None
    max_tool_result_percent: int = DEFAULT_MAX_TOOL_RESULT_PERCENT
    max_tool_result_tokens: int = DEFAULT_MAX_TOOL_RESULT_TOKENS
    fallback_budget: int = DEFAULT_TOOL_RESULT_TOKEN_BUDGET

    def __post_init__(self) -> None:
        """在 Runtime 创建前校验配置，避免非法预算进入 provider loop。"""

        if self.mode not in {"fixed", "dynamic"}:
            raise ToolResultBudgetError(f"unsupported tool result budget mode: {self.mode!r}")
        if self.context_window_tokens is not None:
            _require_positive_integer(self.context_window_tokens, "context_window_tokens")
        if (
            isinstance(self.max_tool_result_percent, bool)
            or not isinstance(self.max_tool_result_percent, int)
            or not 1 <= self.max_tool_result_percent <= 100
        ):
            raise ToolResultBudgetError("max_tool_result_percent must be an integer from 1 to 100")
        _require_positive_integer(self.max_tool_result_tokens, "max_tool_result_tokens")
        _require_positive_integer(self.fallback_budget, "fallback_budget")
        if self.mode == "dynamic" and self.context_window_tokens is not None:
            run_budget = self.run_tool_evidence_budget
            if run_budget is None or run_budget <= 0:
                raise ToolResultBudgetError(
                    "dynamic context window produces no positive Tool Result budget"
                )

    @property
    def context_window_source(self) -> ContextWindowSource:
        """返回 context window 的事实来源，而不是根据 model string 推断。"""

        if self.mode == "fixed":
            return "not_used"
        return "explicit_config" if self.context_window_tokens is not None else "fallback"

    @property
    def budget_resolution(self) -> BudgetResolution:
        """区分显式 dynamic 计算和契约要求的固定 fallback。"""

        return "configured" if self.context_window_tokens is not None or self.mode == "fixed" else "fallback_fixed"

    @property
    def run_tool_evidence_budget(self) -> int | None:
        """计算一次 run 的共享 pool；fixed 模式保留旧的逐调用语义。"""

        if self.mode == "fixed":
            return None
        if self.context_window_tokens is None:
            # 未知 context 不做伪精确计算，使用已验证的固定预算作为安全 run pool。
            return self.fallback_budget
        calculated = (self.context_window_tokens * self.max_tool_result_percent) // 100
        return min(calculated, self.max_tool_result_tokens)

    @property
    def per_call_ceiling(self) -> int:
        """返回单次 Tool projection 可申请的上限。"""

        if self.mode == "fixed" or self.context_window_tokens is None:
            return self.fallback_budget
        return self.max_tool_result_tokens

    def new_policy(self) -> ToolResultBudgetPolicy:
        """为每次 Runtime run 创建隔离的 mutable accounting state。"""

        return ToolResultBudgetPolicy(self)


@dataclass(frozen=True)
class ToolResultBudgetCall:
    """一次已预留的 Tool Result budget，供投影完成后结算。"""

    reservation_id: int
    remaining_before: int | None
    effective_budget: int


@dataclass(frozen=True)
class ToolResultBudgetSnapshot:
    """一次 Tool Result projection 的完整预算归因，直接进入 Runtime/Trace。"""

    budget_mode: ToolResultBudgetMode
    context_window_tokens: int | None
    context_window_source: ContextWindowSource
    max_tool_result_percent: int
    absolute_tool_result_cap: int
    run_tool_evidence_budget: int | None
    per_call_ceiling: int
    remaining_tool_evidence_budget_before_call: int | None
    effective_tool_result_budget: int
    projected_estimated_tokens: int
    remaining_tool_evidence_budget_after_call: int | None
    truncated: bool
    omitted_context_messages: int
    omitted_hit_messages: int
    budget_resolution: BudgetResolution

    def to_dict(self) -> dict[str, object]:
        """生成 Trace/Evaluation 可安全保存的普通值。"""

        return {
            "budget_mode": self.budget_mode,
            "context_window_tokens": self.context_window_tokens,
            "context_window_source": self.context_window_source,
            "max_tool_result_percent": self.max_tool_result_percent,
            "absolute_tool_result_cap": self.absolute_tool_result_cap,
            "run_tool_evidence_budget": self.run_tool_evidence_budget,
            "per_call_ceiling": self.per_call_ceiling,
            "remaining_tool_evidence_budget_before_call": self.remaining_tool_evidence_budget_before_call,
            "effective_tool_result_budget": self.effective_tool_result_budget,
            "projected_estimated_tokens": self.projected_estimated_tokens,
            "remaining_tool_evidence_budget_after_call": self.remaining_tool_evidence_budget_after_call,
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
    def remaining_tool_evidence_budget(self) -> int | None:
        """返回尚未被完成 projection 消耗的共享余额。"""

        return self._remaining

    def begin_call(self) -> ToolResultBudgetCall:
        """先预留 effective budget，再允许 Tool 执行，避免并发调用各自重置预算。"""

        self._next_reservation_id += 1
        reservation_id = self._next_reservation_id
        remaining_before = self._remaining
        if self._remaining is None:
            effective_budget = self.config.per_call_ceiling
        else:
            if self._remaining <= 0:
                raise ToolResultBudgetExhausted(
                    "dynamic Tool Result run budget is exhausted before the next tool call"
                )
            effective_budget = min(self.config.per_call_ceiling, self._remaining)
            self._remaining -= effective_budget
        reservation = ToolResultBudgetCall(
            reservation_id=reservation_id,
            remaining_before=remaining_before,
            effective_budget=effective_budget,
        )
        self._reservations[reservation_id] = reservation
        return reservation

    def complete_call(
        self,
        reservation: ToolResultBudgetCall,
        *,
        projected_estimated_tokens: int,
        truncated: bool,
        omitted_context_messages: int,
        omitted_hit_messages: int,
    ) -> ToolResultBudgetSnapshot:
        """按实际 projection estimate 结算，并生成不可变的 Trace 快照。"""

        stored = self._reservations.pop(reservation.reservation_id, None)
        if stored != reservation:
            raise ToolResultBudgetError("Tool Result budget reservation is unknown or already completed")
        _require_non_negative_integer(projected_estimated_tokens, "projected_estimated_tokens")
        _require_non_negative_integer(omitted_context_messages, "omitted_context_messages")
        _require_non_negative_integer(omitted_hit_messages, "omitted_hit_messages")
        if not isinstance(truncated, bool):
            raise ToolResultBudgetError("truncated must be a boolean")
        if projected_estimated_tokens > reservation.effective_budget:
            raise ToolResultBudgetError(
                "projected Tool Result exceeds its effective budget"
            )

        remaining_after = self._remaining
        if self._remaining is not None:
            # 预留时先扣除 ceiling；这里退回未使用部分，最终只按 actual estimate 扣减。
            self._remaining += reservation.effective_budget - projected_estimated_tokens
            remaining_after = self._remaining
        return ToolResultBudgetSnapshot(
            budget_mode=self.config.mode,
            context_window_tokens=self.config.context_window_tokens,
            context_window_source=self.config.context_window_source,
            max_tool_result_percent=self.config.max_tool_result_percent,
            absolute_tool_result_cap=self.config.max_tool_result_tokens,
            run_tool_evidence_budget=self.config.run_tool_evidence_budget,
            per_call_ceiling=self.config.per_call_ceiling,
            remaining_tool_evidence_budget_before_call=reservation.remaining_before,
            effective_tool_result_budget=reservation.effective_budget,
            projected_estimated_tokens=projected_estimated_tokens,
            remaining_tool_evidence_budget_after_call=remaining_after,
            truncated=truncated,
            omitted_context_messages=omitted_context_messages,
            omitted_hit_messages=omitted_hit_messages,
            budget_resolution=self.config.budget_resolution,
        )


def _require_positive_integer(value: object, field_name: str) -> None:
    """校验正整数配置，拒绝 bool 这种 Python 整数子类。"""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ToolResultBudgetError(f"{field_name} must be a positive integer")


def _require_non_negative_integer(value: object, field_name: str) -> None:
    """校验 projection 产生的非负计数。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ToolResultBudgetError(f"{field_name} must be a non-negative integer")
