"""Router/Planner 共用的 provider-neutral text completion boundary。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

CompletionCallback = Callable[[str], str | Awaitable[str]]


async def complete_text(callback: CompletionCallback, prompt: str) -> str:
    """调用注入的 completion，并只接受纯文本结果。"""

    value: Any = callback(prompt)
    if inspect.isawaitable(value):
        value = await value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("completion callback must return non-empty text")
    return value.strip()
