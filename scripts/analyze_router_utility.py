#!/usr/bin/env python3
"""离线合并 forced treatment、Jev route 与人工 utility 裁决。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trivae.evaluation.router_utility import (
    analyze_router_utility,
    load_treatment_pairs,
    write_create_only,
)


def main() -> None:
    """分析只读取本地 artifact，不调用 Provider。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--evaluation-db", type=Path, required=True)
    parser.add_argument("--standard-variant-id", required=True)
    parser.add_argument("--planned-variant-id", required=True)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--adjudications", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pairs = load_treatment_pairs(
        args.raw,
        args.evaluation_db,
        standard_variant_id=args.standard_variant_id,
        planned_variant_id=args.planned_variant_id,
    )
    routes = json.loads(args.routes.read_text(encoding="utf-8"))
    adjudications = json.loads(args.adjudications.read_text(encoding="utf-8"))
    report = analyze_router_utility(pairs, routes, adjudications)
    write_create_only(report, args.output)


if __name__ == "__main__":
    main()
