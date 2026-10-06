"""Prompt 开发筛选：复用生产 Runtime 和 EvaluationRun，不判定自然语言等价。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from agents.exceptions import ModelBehaviorError

from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter, _project_usage_mapping
from trivae.query.runtime.prompt import SYSTEM_PROMPT


class FirstToolProbeStop(ModelBehaviorError):
    """实验在首轮工具执行前终止；该终态不是完整答案成功。"""


class ScreeningRuntime(OpenAIAgentsRuntimeAdapter):
    """只为显式实验覆写已有 builder，正式 Runtime 不增加实验模式分支。"""

    def __init__(self, *args: Any, prompt: str = SYSTEM_PROMPT, first_tool: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.screening_prompt = prompt
        self.first_tool = first_tool
        self.probe_calls: list[dict[str, object]] = []
        self.probe_usage: dict[str, int | float] | None = None

    def _build_agent(self, request: Any, context: Any, state: Any) -> Any:
        # 保留生产工具、模型、预算和动态 instructions 的唯一构造入口。
        agent = super()._build_agent(request, context, state)
        original_instructions = agent.instructions

        def instructions(wrapper: Any, current_agent: Any) -> str:
            # 仅替换 Base 原文，动态 budget/Plan/finalizing 后缀逐字保留。
            original = original_instructions(wrapper, current_agent)
            if not original.startswith(SYSTEM_PROMPT):
                raise EvaluationContractError("production instructions no longer start with SYSTEM_PROMPT")
            return self.screening_prompt + original[len(SYSTEM_PROMPT):]

        agent.instructions = instructions
        if self.first_tool:
            # 每次正式构造新run时清空观测，不能继承上一case的usage。
            self.probe_usage = None
            # SDK 已完成模型轮次和 usage hook，替换工具 callable 可在任何 Host 查询之前停止。
            for tool in agent.tools:
                tool.on_invoke_tool = self._probe_invoker(tool.name)
        return agent

    def _probe_invoker(self, name: str) -> Any:
        async def stop_before_tool(context: Any, arguments: str) -> None:
            # ToolContext.usage在SDK完成本模型轮后已更新，不依赖失败流是否排空Trace hook队列。
            self.probe_usage = _project_usage_mapping(context.usage) or None
            # 保存完整参数；同一模型轮次并行选择的工具也只记录，全部不执行。
            self.probe_calls.append({"name": name, "arguments": json.loads(arguments)})
            raise FirstToolProbeStop("first-tool probe stopped before capability execution")
        return stop_before_tool


@dataclass
class ProviderCallBudget:
    """在 HTTP request hook 计数并拒绝超过显式预算的请求。"""

    maximum: int
    requests: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.maximum, bool) or not isinstance(self.maximum, int) or self.maximum < 0:
            raise EvaluationContractError("maximum provider calls must be a non-negative integer")

    async def before_request(self, request: Any) -> None:
        # 计数包含真实 transport attempts；超额请求在发送前显式失败，绝不自动扩大预算。
        if len(self.requests) >= self.maximum:
            raise EvaluationContractError("maximum provider calls exhausted before sending request")
        body = json.loads(request.content)
        # 不保存鉴权头或隐藏 reasoning；完整可见请求用于检查首轮非策略字段一致性。
        body = {key: value for key, value in body.items() if key not in {"reasoning", "reasoning_content"}}
        self.requests.append(body)


def select_policy_cases(
    cases: Sequence[EvaluationCaseBundle], policy: str | None,
) -> tuple[EvaluationCaseBundle, ...]:
    """复用 versioned case 的 suite_tags，不新增第二份 case truth。"""

    selected = tuple(case for case in cases if policy is None or policy in case.suite_tags)
    if not selected:
        raise EvaluationContractError(f"no cases selected for policy {policy!r}")
    if len({case.identity for case in selected}) != len(selected):
        raise EvaluationContractError("duplicate cases would spend provider calls twice")
    return selected


def screening_conditions(
    case: EvaluationCaseBundle, *, provider: str, model: str,
    settings: Mapping[str, object], tool_budget: int, tools: Sequence[str],
) -> dict[str, object]:
    """冻结所有实际执行条件；Prompt/commit 在 artifact 中另存，不混入相等比较。"""

    return json.loads(json.dumps({
        "case": case.identity, "query": case.query, "locale": case.locale,
        "snapshot": case.dataset_snapshot.to_dict(),
        "scope": case.to_dict()["data_access_scope"], "route": "standard_execution",
        "provider": provider, "model": model, "settings": dict(settings),
        "tool_budget": tool_budget, "tools": list(tools),
    }))


def verify_frozen_baseline(
    artifact: Mapping[str, Any], conditions: Mapping[str, object], baseline_prompt: str,
) -> None:
    """只复用生产 baseline；失败候选、probe 和运行条件漂移在付费前拒绝。"""

    if artifact.get("kind") != "frozen_baseline":
        raise EvaluationContractError("candidate-only requires a frozen baseline, not a candidate or probe")
    if artifact.get("prompt") != baseline_prompt:
        raise EvaluationContractError("frozen prompt does not match the production baseline")
    if not artifact.get("commit") or not artifact.get("run") or not artifact.get("trace"):
        raise EvaluationContractError("frozen baseline requires commit, evaluation run and trace")
    frozen_conditions = artifact.get("conditions")
    # 冻结记录必须保留实际条件对象，缺失时显式指出契约错误。
    if not isinstance(frozen_conditions, Mapping):
        raise EvaluationContractError("frozen execution conditions must be an object")
    if frozen_conditions != dict(conditions):
        # 相等门禁保持不变；只列变化字段，不把整份请求或配置值塞进异常。
        changed = sorted(
            key for key in set(frozen_conditions) | set(conditions)
            if key not in frozen_conditions or key not in conditions or frozen_conditions[key] != conditions[key]
        )
        raise EvaluationContractError(
            f"frozen execution conditions drifted ({', '.join(changed)}); refusing provider call"
        )


def read_artifact(path: Path) -> dict[str, Any]:
    """读取本地完整 artifact，格式错误显式冒泡。"""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvaluationContractError("screening artifact must be a JSON object")
    return value


def write_artifact(path: Path, artifact: Mapping[str, object]) -> None:
    """失败和候选不覆盖；同样的 repeat 必须使用新的输出目录。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(dict(artifact), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def candidate_repeat_count(verdict: str, additional: int, reason: str | None) -> int:
    """明确退步立即淘汰；只有单 case 的人工 borderline/randomness 判断允许追加。"""

    if additional < 0:
        raise EvaluationContractError("additional candidate repeats must be non-negative")
    if verdict == "regression":
        return 0
    if additional and (verdict != "borderline" or reason not in {"provider_randomness", "borderline"}):
        raise EvaluationContractError("extra repeats require an explicit borderline review and reason")
    return additional
