"""Router/Planner 共用的 provider-neutral text completion boundary。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompletionObservation:
    """Provider completion 的安全观测投影，不携带 SDK response 对象。"""

    # provider/model 是普通 identity，便于 Trace 按运行配置聚合。
    provider: str | None = None
    model: str | None = None
    # request 只保存显式非敏感参数，例如 max_tokens 和 JSON mode。
    request: dict[str, object] = field(default_factory=dict)
    # latency 在 Provider boundary 内测量，和 Planner 的 wait_for 总耗时分开。
    latency_ms: float | None = None
    # finish_reason 用于区分正常结束和 Provider length 截断。
    finish_reason: str | None = None
    # usage 只保留普通数字，不让 SDK Usage 类型越过 adapter boundary。
    usage: dict[str, int | float] | None = None
    # response_content 是模型公开文本，不是 SDK raw repr；Trace profile 决定是否落盘正文。
    response_content: str | None = None


@dataclass(frozen=True)
class CompletionResult:
    """Completion 文本与可选 Provider 观测的显式返回值。"""

    # None 表示 Provider 返回了空/不可观察 content，不能伪装成普通空字符串。
    content: str | None
    # 注入式 fake 可以只返回 content；真实 adapter 返回完整安全观测。
    observation: CompletionObservation | None = None


CompletionCallbackResult = str | CompletionResult
CompletionCallback = Callable[[str], CompletionCallbackResult | Awaitable[CompletionCallbackResult]]


async def invoke_completion(callback: CompletionCallback, prompt: str) -> CompletionResult:
    """调用 completion 并保留 provider-neutral observation，供 Planner 做阶段归因。"""

    # 先调用回调，兼容同步 fake 与真实 async Provider adapter。
    value: Any = callback(prompt)
    # 只等待真正的 awaitable，不把同步返回值误当成 coroutine。
    if inspect.isawaitable(value):
        value = await value
    # 真实 adapter 可以显式表达空 content 和 finish_reason。
    if isinstance(value, CompletionResult):
        return value
    # 旧的测试/注入 callback 只有文本时，补一个无 Provider metadata 的结果。
    if isinstance(value, str):
        return CompletionResult(value)
    # 未知返回类型必须显式失败，不能用 repr 猜测 Provider 输出。
    raise ValueError("completion callback must return text or CompletionResult")


async def complete_text(callback: CompletionCallback, prompt: str) -> str:
    """调用注入的 completion，并只接受纯文本结果。"""

    # 通过统一 helper 调用，保留真实 adapter 的观测但对旧调用者只返回文本。
    result = await invoke_completion(callback, prompt)
    # 空 content 仍是错误；需要阶段分类的 Planner 会直接使用 invoke_completion。
    if not isinstance(result.content, str) or not result.content.strip():
        raise ValueError("completion callback must return non-empty text")
    return result.content.strip()
