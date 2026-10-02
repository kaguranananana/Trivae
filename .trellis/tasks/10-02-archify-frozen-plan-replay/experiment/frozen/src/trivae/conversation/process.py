"""一轮回答的 bounded 过程摘要收集（UI-neutral）。

该收集器只消费 ``QueryStreamEvent`` 中真实发生的事实，把 router/plan/thinking/tool/
retrieval/usage/error 压缩成普通值 mapping，供 Conversation 持久化与各 interface 回放。
它不生成任何不存在的过程步骤，也不把 provider 之外的内容伪装成 reasoning。
"""

from __future__ import annotations

from typing import Literal, Mapping

from trivae.query.streaming import QueryStreamEvent

# conversation 内保存的 thinking 文本按段有界；完整事实仍在 provider stream/Trace 边界内，
# 截断以显式 flag 暴露，回放 UI 必须展示"已截断"。
MAX_THINKING_SEGMENT_CHARS = 1_500
MAX_TOOL_ARGUMENT_JSON_CHARS = 1_200
MAX_PLAN_STEPS = 20
MAX_PROCESS_STEPS = 64


class TurnProcessCollector:
    """按 sequence 顺序收集一轮 Query 的过程事实，输出 bounded JSON-ready mapping。"""

    def __init__(self) -> None:
        self._router: dict[str, object] | None = None
        self._plan: dict[str, object] | None = None
        self._steps: list[dict[str, object]] = []
        self._tools_by_call_id: dict[str, dict[str, object]] = {}
        self._usage: dict[str, object] | None = None
        self._error: dict[str, object] | None = None
        self._status: Literal["completed", "failed", "aborted"] | None = None
        # thinking 段在 started 与 completed 之间积累文本；visibility 由 delta 提供。
        self._thinking_index: int | None = None

    def handle(self, event: QueryStreamEvent) -> None:
        """消费一个 live event；未知类型不产生伪造步骤。"""

        if event.type == "route.completed":
            metadata = event.metadata
            self._router = {
                "route": event.route,
                "reason": metadata.get("reason"),
                "confidence": metadata.get("confidence"),
                "source": metadata.get("source"),
                "degradation_code": metadata.get("degradation_code"),
                "duration_ms": event.duration_ms,
            }
            return
        if event.type == "plan.completed" and event.plan is not None:
            plan = event.plan
            steps = plan.get("steps")
            self._plan = {
                "title": plan.get("title"),
                "intent": plan.get("intent"),
                "step_count": plan.get("step_count"),
                "success_criteria": plan.get("success_criteria"),
                "steps": [
                    {
                        "goal": step.get("goal"),
                        "suggested_tools": step.get("suggested_tools"),
                        "evidence_needed": step.get("evidence_needed"),
                    }
                    for step in (steps if isinstance(steps, list) else [])[:MAX_PLAN_STEPS]
                ],
                "duration_ms": event.duration_ms,
            }
            return
        if event.type == "plan.failed":
            self._plan = {
                "failed": True,
                "error_code": event.error_code,
                "error_message": event.error_message,
                "duration_ms": event.duration_ms,
            }
            return
        if event.type == "thinking.started":
            if len(self._steps) >= MAX_PROCESS_STEPS:
                return
            self._thinking_index = len(self._steps)
            self._steps.append({"kind": "thinking", "text": ""})
            return
        if event.type == "thinking.delta":
            if self._thinking_index is not None:
                thinking_step = self._steps[self._thinking_index]
                raw_text = thinking_step.get("text")
                previous = raw_text if isinstance(raw_text, str) else ""
                if len(previous) < MAX_THINKING_SEGMENT_CHARS:
                    appended = previous + str(event.content or "")[: MAX_THINKING_SEGMENT_CHARS - len(previous)]
                    thinking_step["text"] = appended
                    if len(appended) >= MAX_THINKING_SEGMENT_CHARS:
                        thinking_step["text_truncated"] = True
                else:
                    thinking_step["text_truncated"] = True
                visibility = event.thinking_visibility
                if visibility is not None and "visibility" not in thinking_step:
                    thinking_step["visibility"] = visibility
            return
        if event.type in {"thinking.completed", "answer.delta"}:
            # thinking.completed 只关闭段；answer.delta 已由 answer_text 覆盖，不重复保存。
            if event.type == "thinking.completed":
                self._thinking_index = None
            return
        if event.type == "tool.started":
            if len(self._steps) >= MAX_PROCESS_STEPS or event.tool_call_id is None:
                return
            step: dict[str, object] = {
                "kind": "tool",
                "tool_call_id": event.tool_call_id,
                "tool_name": event.tool_name,
                "arguments": _bounded_arguments(event.arguments),
            }
            self._steps.append(step)
            self._tools_by_call_id[event.tool_call_id] = step
            return
        if event.type in {"tool.completed", "tool.failed"} and event.tool_call_id is not None:
            existing = self._tools_by_call_id.get(event.tool_call_id)
            if existing is None:
                return
            existing["status"] = "failed" if event.type == "tool.failed" else "completed"
            existing["error_code"] = event.error_code
            existing["duration_ms"] = event.duration_ms
            projection = event.result_projection
            if isinstance(projection, Mapping):
                result = projection.get("result")
                if isinstance(result, Mapping):
                    existing["total_items"] = result.get("total_items")
                    existing["item_kind"] = result.get("item_kind")
                    existing["limitations"] = result.get("limitations")
            summary = event.result_summary
            if isinstance(summary, Mapping) and "status" in summary:
                existing["result_status"] = summary.get("status")
            return
        if event.type == "retrieval.completed" and event.tool_call_id is not None:
            existing = self._tools_by_call_id.get(event.tool_call_id)
            if existing is not None:
                existing["retrieval"] = dict(event.result_summary) if event.result_summary else {}
            return
        if event.type == "usage.updated" and event.usage:
            self._usage = dict(event.usage)
            return
        if event.type in {"query.completed", "query.failed", "query.aborted"}:
            self._status = (
                "completed" if event.type == "query.completed" else "aborted" if event.type == "query.aborted" else "failed"
            )
            if event.type != "query.completed":
                self._error = {
                    "code": event.error_code,
                    "message": event.error_message,
                }
            return

    def to_projection(self) -> dict[str, object]:
        """输出可直接进入 Conversation Store 的 bounded 普通值 mapping。"""

        return {
            "schema_version": 1,
            "router": self._router,
            "plan": self._plan,
            "steps": self._steps,
            "usage": self._usage,
            "error": self._error,
            "status": self._status,
        }


def _bounded_arguments(arguments: Mapping[str, object] | None) -> object:
    """arguments 保持结构化；只防止单个字符串字段无界增长。"""

    if arguments is None:
        return None
    bounded: dict[str, object] = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > MAX_TOOL_ARGUMENT_JSON_CHARS:
            bounded[str(key)] = value[: MAX_TOOL_ARGUMENT_JSON_CHARS - 1] + "…"
        else:
            bounded[str(key)] = value
    return bounded
