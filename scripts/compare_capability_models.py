"""Check whether two recorded capability experiments differ only by model/provider."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trivae.evaluation.experiment_manifest import compare_model_experiments


def review_conditions(directory: Path, runs: list[dict[str, object]]) -> dict[str, object]:
    """Require one review of every completed run and a single actual judge configuration."""
    expected = {run["run_id"] for run in runs if run.get("terminal_status") == "completed"}
    if not expected:
        raise ValueError("no completed runs are available for judge comparison")
    found: set[str] = set()
    configurations = []
    for review_path in sorted(directory.glob("*/review.json")):
        review = json.loads(review_path.read_text(encoding="utf-8"))
        run_id = review["run_id"]
        if run_id not in expected or run_id in found or review["reviewer_type"] != "model_assisted":
            raise ValueError("review records do not match completed runs uniquely")
        config = json.loads((review_path.parent / "configuration.json").read_text(encoding="utf-8"))
        response = json.loads((review_path.parent / "response.json").read_text(encoding="utf-8"))
        if config["rubric_version"] != review["rubric_version"]:
            raise ValueError("review rubric differs from recorded judge configuration")
        configurations.append({**config, "actual_model": response["model"]})
        found.add(run_id)
    if found != expected:
        raise ValueError("completed runs do not all have a recorded judge review")
    if any(config != configurations[0] for config in configurations[1:]):
        raise ValueError("judge conditions differ within an experiment")
    return configurations[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline-reviews", type=Path)
    parser.add_argument("--candidate-reviews", type=Path)
    args = parser.parse_args()
    result = compare_model_experiments(args.baseline, args.candidate)
    if (args.baseline_reviews is None) != (args.candidate_reviews is None):
        parser.error("provide both review directories or neither")
    if args.baseline_reviews is None:
        result["review_conditions"] = "not_checked"
    else:
        try:
            baseline = review_conditions(args.baseline_reviews, result["baseline_runs"])
            candidate = review_conditions(args.candidate_reviews, result["candidate_runs"])
            result["review_conditions"] = "matched" if baseline == candidate else "different"
            if baseline != candidate:
                result["reasons"].append("judge conditions differ")
                result["comparable"] = False
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result["review_conditions"] = "incomplete"
            result["reasons"].append(str(exc))
            result["comparable"] = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["comparable"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
