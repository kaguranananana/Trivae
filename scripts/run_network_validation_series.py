"""验证层持续尝试：每次独立账本和失败工件，共享冻结条件，不改产品重试策略。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import traceback
from pathlib import Path

from scripts.run_runtime_budget_followup import read_json, write_json
from scripts.run_temporal_coverage_probe import run

# 仅继续本轮已经实测的传输失败；格式、引用、源码漂移和其他错误交回主任务诊断。
NETWORK_ERRORS = {"ConnectError", "ReadTimeout", "RemoteProtocolError"}


async def validate(templates: list[Path], root: Path) -> None:
    """顺序验证各题，避免多个进程同时刷新同一OAuth会话。"""
    root.mkdir(parents=True, exist_ok=False)
    progress = {
        "status": "running",
        "pid": os.getpid(),
        "templates": [str(path) for path in templates],
        "trials": [],
        "inference_requests": 0,
    }
    write_json(root / "progress.json", progress, exclusive=True)
    for template in templates:
        case_root = root / template.name
        case_root.mkdir()
        trial_number = 0
        while True:
            trial_number += 1
            trial = case_root / f"trial-{trial_number:04d}"
            (trial / "snapshot").mkdir(parents=True)
            # 复用已冻结且已重建的快照，只克隆文件，不更换材料或重新调参。
            for name in ("trivae.sqlite3", "trivae.semantic.sqlite3"):
                subprocess.run(
                    ["cp", "-c", str(template / "snapshot" / name), str(trial / "snapshot" / name)], check=True
                )
            write_json(trial / "protocol.json", read_json(template / "protocol.json"), exclusive=True)
            # 每次尝试有独立上限；总账只累加，任何失败都不从历史中扣除。
            write_json(
                trial / "http-ledger.json",
                {"maximum": 8, "maximum_per_case": 8, "used": 0, "attempts": [], "blocked": [], "attempted_cases": []},
                exclusive=True,
            )
            network_failure = False
            exception_type = None
            try:
                await run(trial)
            except Exception as exc:
                exception_type = type(exc).__name__
                network_failure = getattr(exc, "code", None) == "AUTH_NETWORK"
                # 保留异常链，不能只留下失败类别而丢失源码漂移或认证失败的定位信息。
                (trial / "exception.txt").write_text(traceback.format_exc())
            result = read_json(trial / "temporal/result.json")
            attempts = read_json(trial / "http-ledger.json")["used"]
            # 终态错误仍要结合真实传输类型判断，不能把任意Provider错误当作网络错误重跑。
            network_failure = network_failure or any(
                item.get("exception_type") in NETWORK_ERRORS for item in result.get("transport", [])
            )
            row = {
                "case": template.name,
                "trial": trial_number,
                "path": str(trial),
                "status": result["status"],
                "inference_requests": attempts,
                "network_failure": network_failure,
                "exception_type": exception_type,
            }
            progress["trials"].append(row)
            progress["inference_requests"] += attempts
            write_json(root / "progress.json", progress)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if result["status"] == "completed":
                break
            if not network_failure:
                # 主任务继续定位实现或契约根因，不通过反复采样掩盖真实失败。
                progress["status"] = "needs_diagnosis"
                write_json(root / "progress.json", progress)
                raise RuntimeError(f"validation requires diagnosis: {trial}")
            # 用户明确要求网络失败继续尝试；间隔只用于验证进程，不进入在线产品。
            await asyncio.sleep(10)
    progress["status"] = "completed"
    write_json(root / "progress.json", progress)
    print(json.dumps({"status": "completed", "inference_requests": progress["inference_requests"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(validate(args.template, args.output))
