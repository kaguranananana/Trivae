#!/usr/bin/env python3
"""对 Planner Utility CaseBundle 执行 Rule gate + Jev-only route observation。"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from pathlib import Path

from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_router_jev_settings
from trivae.evaluation.benchmark.orchestrator import load_cases_dir
from trivae.evaluation.contracts import EvaluationSuite
from trivae.evaluation.router_utility import run_jev_route_observations, write_create_only
from trivae.query.jev_provider import JevRouteDecisionProvider


def main() -> None:
    """先完成输入与输出 preflight，再创建计费 Provider。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--cases-dir", type=Path, action="append", required=True)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"route observation output already exists: {args.output}")
    suite = EvaluationSuite.from_json(args.suite)
    cases = load_cases_dir(tuple(args.cases_dir))
    if args.case_id:
        selected = set(args.case_id)
        references = tuple(ref for ref in suite.case_references if ref.case_id in selected)
        if len(references) != len(selected):
            raise ValueError("selected case IDs must all belong to the Suite")
        suite = replace(suite, case_references=references)
    for reference in suite.case_references:
        if cases[reference.case_id].identity != reference.identity:
            raise ValueError(f"Suite Case identity mismatch: {reference.identity}")
    load_environment_file(args.env_file)
    settings = load_router_jev_settings()
    if not settings.enabled or not settings.api_key:
        raise ValueError("Jev must be enabled with an OpenRouter API key")
    provider = JevRouteDecisionProvider(settings)

    async def run() -> dict[str, object]:
        """一次 Provider 生命周期覆盖所选 Case，退出时关闭连接。"""

        try:
            return await run_jev_route_observations(suite, cases, provider, repetitions=args.repeat)
        finally:
            await provider.aclose()

    report = asyncio.run(run())
    write_create_only(report, args.output)


if __name__ == "__main__":
    main()
