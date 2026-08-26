"""在同一代码版本上运行四个历史 prompt 的 fixed/dynamic operational A/B。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.config.dotenv import load_environment_file
from trivae.query.contracts import QueryRequest

CASES = {
    "github_skills_resources": "最近的这一个月之内，有没有讨论过一些有价值的 GitHub 仓库、Skills、有价值的一些资源之类的东西",
    "agent_learning_materials": "最近一个月群里推荐过哪些 Agent 学习资料？",
    "taste_skill": "群里对 taste-skill 的评价是什么？有没有人实际用过？",
    "deepseek_projects": "最近两周讨论过哪些 DeepSeek 相关项目？",
}


def _set_budget_environment(mode: str) -> None:
    """只切换预算实验变量，保持 provider/model 与其他运行配置不变。"""

    os.environ["TRIVAE_TOOL_RESULT_BUDGET_MODE"] = mode
    if mode == "dynamic":
        os.environ["TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS"] = "128000"
        os.environ["TRIVAE_MAX_TOOL_RESULT_PERCENT"] = "50"
        os.environ["TRIVAE_MAX_TOOL_RESULT_TOKENS"] = "128000"
    else:
        os.environ.pop("TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS", None)
        os.environ.pop("TRIVAE_MAX_TOOL_RESULT_PERCENT", None)
        os.environ.pop("TRIVAE_MAX_TOOL_RESULT_TOKENS", None)


async def _run_one(
    application: TrivaeApplication,
    case_name: str,
    prompt: str,
    mode: str,
    repetition: int,
) -> dict[str, object]:
    """运行单个 A/B cell，并只返回可比较的执行事实。"""

    result = await application.query(
        QueryRequest(
            prompt,
            ExecutionScope(),
            request_id=f"dynamic-budget-{case_name}-{mode}-{repetition}",
            trace_profile="debug",
        )
    )
    trace = application.read_trace(result.trace_id) if result.trace_id is not None else None
    calls = result.runtime_result.tool_calls
    snapshots = [call.tool_result_budget.to_dict() for call in calls if call.tool_result_budget is not None]
    return {
        "case": case_name,
        "mode": mode,
        "repetition": repetition,
        "trace_id": result.trace_id,
        "provider": result.runtime_result.provider,
        "model": result.runtime_result.model,
        "termination": result.runtime_result.termination,
        "is_successful": result.is_successful,
        "tool_calls": len(calls),
        "tool_rounds": result.runtime_result.tool_rounds,
        "projection_estimated_tokens": sum(
            call.model_result_estimated_tokens or 0 for call in calls
        ),
        "projection_truncated_count": sum(
            1 for call in calls if call.model_result_truncated is True
        ),
        "omitted_context_messages": sum(
            call.model_result_omitted_context_messages or 0 for call in calls
        ),
        "omitted_hit_messages": sum(call.model_result_omitted_hit_messages or 0 for call in calls),
        "latency_ms": None if trace is None else trace.metrics.total_duration_ms,
        "budget_snapshots": snapshots,
        "usage": None
        if result.runtime_result.usage is None
        else dict(result.runtime_result.usage),
    }


async def _run_all() -> None:
    """按固定顺序完成全部 4×2×3 cells，便于结果配对并复用同一 mode 的本地 provider。"""

    for mode in ("fixed", "dynamic"):
        _set_budget_environment(mode)
        application = create_application(Path("data/trivae.sqlite3"))
        try:
            for case_name, prompt in CASES.items():
                for repetition in range(1, 4):
                    try:
                        result = await _run_one(application, case_name, prompt, mode, repetition)
                    except Exception as exc:
                        # 失败仍显式输出类型并继续其他 cell；不会把失败转换成成功或伪造 result。
                        result = {
                            "case": case_name,
                            "mode": mode,
                            "repetition": repetition,
                            "status": "error",
                            "exception_type": type(exc).__name__,
                        }
                    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        finally:
            # 当前函数运行在 event loop 内，必须使用异步 lifecycle，避免 harness 错误混入 A/B。
            await application.aclose()


def main() -> None:
    """加载本地 dotenv 后执行真实 provider A/B；不打印任何 secret value。"""

    load_environment_file(Path(".env"))
    asyncio.run(_run_all())


if __name__ == "__main__":
    main()
