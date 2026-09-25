"""将主实验与 targeted repeat 分开核验，输出每个 Case 的三次质量方向。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from analyze_planner_utility import _metrics, _paired_quality


def _rows(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _payloads(path: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    with sqlite3.connect(path) as connection:
        runs = {run_id: json.loads(payload) for run_id, payload in connection.execute("SELECT run_id,payload_json FROM evaluation_runs")}
        results = {run_id for (run_id,) in connection.execute("SELECT run_id FROM evaluation_results")}
    return runs, results


def analyze(main_records: Path, main_db: Path, repeat_records: Path, repeat_db: Path, canonical_db: Path) -> dict[str, Any]:
    """按真实 repetition identity 配对，绝不把 targeted 24 runs 混进主 74 分母。"""

    main = _rows(main_records)
    repeats = _rows(repeat_records)
    if len(main) != 74 or len(repeats) != 24:
        raise ValueError("expected 74 main and 24 targeted repeat records")
    main_payloads, main_results = _payloads(main_db)
    repeat_payloads, repeat_results = _payloads(repeat_db)
    if {row["run_id"] for row in main} != set(main_payloads) or set(main_payloads) != main_results:
        raise ValueError("main raw/Evaluation identity mismatch")
    if {row["run_id"] for row in repeats} != set(repeat_payloads) or set(repeat_payloads) != repeat_results:
        raise ValueError("repeat raw/Evaluation identity mismatch")
    trace_ids = [row["trace_id"] for row in repeats]
    with sqlite3.connect(canonical_db) as connection:
        trace_count = connection.execute(
            f"SELECT COUNT(*) FROM traces WHERE trace_id IN ({','.join('?' for _ in trace_ids)})", trace_ids
        ).fetchone()[0]
    if len(set(trace_ids)) != 24 or trace_count != 24:
        raise ValueError("repeat Trace identities do not align")

    by_main: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in main:
        arm = "standard" if "-standard-" in row["variant_id"] else "planned"
        by_main[row["case_id"]][arm] = row
    by_repeat: dict[str, dict[int, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    for row in repeats:
        payload = repeat_payloads[row["run_id"]]
        repetition = payload["query_request"]["data_snapshot"]["repetition"]
        arm = "standard" if "-standard-" in row["variant_id"] else "planned"
        if arm in by_repeat[row["case_id"]][repetition]:
            raise ValueError("duplicate targeted case/repetition/arm")
        by_repeat[row["case_id"]][repetition][arm] = row

    cases: list[dict[str, Any]] = []
    for case_id, repeat_groups in sorted(by_repeat.items()):
        if set(repeat_groups) != {0, 1} or any(set(group) != {"standard", "planned"} for group in repeat_groups.values()):
            raise ValueError(f"incomplete targeted repetitions: {case_id}")
        main_group = by_main[case_id]
        main_direction, _ = _paired_quality(
            main_group["standard"], main_group["planned"],
            main_payloads[main_group["standard"]["run_id"]], main_payloads[main_group["planned"]["run_id"]],
        )
        observations = [{"source": "main", "direction": main_direction,
                         "standard_metrics": _metrics(main_group["standard"]), "planned_metrics": _metrics(main_group["planned"])}]
        for index in (0, 1):
            group = repeat_groups[index]
            standard, planned = group["standard"], group["planned"]
            direction, _ = _paired_quality(
                standard, planned, repeat_payloads[standard["run_id"]], repeat_payloads[planned["run_id"]]
            )
            observations.append({
                "source": f"targeted_repeat_{index + 1}", "direction": direction,
                "standard_status": standard["run_status"], "planned_status": planned["run_status"],
                "standard_metrics": _metrics(standard), "planned_metrics": _metrics(planned),
                "standard_planner": standard["operational_measurements"]["planner"]["status"],
                "planned_planner": planned["operational_measurements"]["planner"]["status"],
                "standard_tools": standard["operational_measurements"]["agent_tool_behavior"]["tool_sequence"],
                "planned_tools": planned["operational_measurements"]["agent_tool_behavior"]["tool_sequence"],
            })
        cases.append({"case_id": case_id, "observations": observations,
                      "same_direction_all_three": len({item["direction"] for item in observations}) == 1})
    return {
        "integrity": {"main_raw": 74, "repeat_raw": 24, "repeat_evaluation_runs": len(repeat_payloads),
                      "repeat_evaluation_results": len(repeat_results), "repeat_traces": trace_count},
        "cases": cases,
        "stable_direction_cases": sum(case["same_direction_all_three"] for case in cases),
        "direction_sequences": dict(Counter("/".join(item["direction"] for item in case["observations"]) for case in cases)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-records", type=Path, required=True)
    parser.add_argument("--main-db", type=Path, required=True)
    parser.add_argument("--repeat-records", type=Path, required=True)
    parser.add_argument("--repeat-db", type=Path, required=True)
    parser.add_argument("--canonical-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"repeat analysis output already exists: {args.output}")
    result = analyze(args.main_records, args.main_db, args.repeat_records, args.repeat_db, args.canonical_db)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"integrity": result["integrity"], "stable_direction_cases": result["stable_direction_cases"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
