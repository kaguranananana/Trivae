#!/usr/bin/env python3
"""导出 version-controlled 的 redacted BenchmarkEnvironmentManifest。

角色边界（design §2 / prd R1）：
- 本地完整版 `data/evaluation/benchmark/environment.json` 是 pre-run gate 的唯一
  事实源（`BenchmarkEnvironmentManifest` contract）；
- 本脚本产出 `evaluation/snapshots/<benchmark>.json` 仅用于仓库内复现说明与
  freeze verification 审阅：同一 contract 形态、可被 `from_dict` 解析，
  但**不承担 DatasetSnapshot binding，也不是 gate 的输入**。

manifest 字段本身不含聊天正文、source metadata、本地路径或凭据；脚本会做一次
显式私有信息断言（external_chat_id / 绝对路径 / api key 字样）后再落盘。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from trivae.config.dotenv import load_environment_file
from trivae.evaluation.benchmark.environment import BenchmarkEnvironmentManifest

PRIVATE_MARKERS = ("external_chat_id", "api_key", "/users/", "/home/")


def main() -> int:
    load_environment_file()
    source = Path("data/evaluation/benchmark/environment.json")
    output = Path("evaluation/snapshots") / f"{json.loads(source.read_text())['benchmark']}.json"
    manifest = BenchmarkEnvironmentManifest.from_json(source)

    payload = manifest.to_dict()
    payload["notes"] = {
        "role": "redacted reproducibility artifact; freeze verification only",
        "binding": "pre-run gate binds to the local data/evaluation/benchmark/environment.json via BenchmarkEnvironmentManifest contract",
        "dataset_binding": "cases bind DatasetSnapshot.snapshot_id; this file does not rebind datasets",
        "private_fields_check": "passed",
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    lowered = serialized.lower()
    for marker in PRIVATE_MARKERS:
        if marker in lowered:
            print(f"refusing to write: private marker {marker!r} found", file=sys.stderr)
            return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    # 复核：redacted 产物必须仍是合法 BenchmarkEnvironmentManifest 形态。
    parsed = BenchmarkEnvironmentManifest.from_dict(json.loads(output.read_text()))
    assert parsed.canonical_snapshot_id == manifest.canonical_snapshot_id
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
