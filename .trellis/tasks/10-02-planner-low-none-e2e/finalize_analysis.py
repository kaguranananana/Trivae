"""全部盲审完成后，把未修改的判断和明确标注的人工解释合并到自动指标。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def finalize(directory: Path) -> None:
    """只读原始判断与揭盲映射；不重新评价或覆盖盲审判断。"""
    blind = directory / "blind"
    # 字节相等确认原始判断没有在揭盲后被反向修改。
    if (blind / "judgments.json").read_bytes() != (blind / "judgments.frozen.json").read_bytes():
        raise ValueError("blind judgments changed after reveal")
    judgments = json.loads((blind / "judgments.json").read_text())
    reveal = json.loads((blind / "reveal.json").read_text())
    # 必须全部 8 组完成，且与 reveal 一一对应，才能进入解释阶段。
    ids = {r["case_id"] for r in judgments["judgments"]}
    if len(ids) != 8 or ids != {r["case_id"] for r in reveal["pairs"]}:
        raise ValueError("blind pair set is incomplete")
    analysis = json.loads((directory / "analysis.json").read_text())
    analysis["blind_review"] = {"source": reveal["reviewer_source"], "results": [
        {k: r[k] for k in ("case_id", "judgment", "mapping", "preferred_treatment", "reason")}
        for r in reveal["pairs"]]}
    # interpretation 是揭盲后人工核验原始 ToolResult 的结论，不冒充自动事实评分。
    analysis.update(json.loads((directory / "interpretation.json").read_text()))
    (directory / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    finalize(args.directory)
