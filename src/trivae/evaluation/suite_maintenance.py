"""Create reviewable candidate suites on a new local data snapshot."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .contracts import (
    CaseReference,
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationSuite,
    utc_now,
)


def rebase_suite(*, suite: EvaluationSuite, cases: Mapping[str, EvaluationCaseBundle], freeze_path: Path,
                 output_dir: Path) -> dict[str, object]:
    """Copy questions into new candidate identities; never carry old GT across snapshots as verified."""
    try:
        data = json.loads(freeze_path.read_text(encoding="utf-8"))
        snapshot = DatasetSnapshot.from_dict(data["snapshot"])
        if data.get("role") != "master":
            raise EvaluationContractError("suite candidates must refer to a frozen master")
        selected = [cases[ref.identity] for ref in suite.case_references]
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, EvaluationContractError):
            raise
        raise EvaluationContractError("suite, case or freeze manifest cannot be read") from exc
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise EvaluationContractError("candidate output directory already exists") from exc
    case_dir = output_dir / "cases"
    case_dir.mkdir()
    created: list[EvaluationCaseBundle] = []
    for old in selected:
        payload = old.to_dict()
        payload["case_id"] = "candidate-" + old.case_id
        payload["version"] = 1
        payload["dataset_snapshot"] = snapshot.to_dict()
        payload["reference_findings"] = []
        payload["diagnostic_expectations"] = None
        payload["suite_tags"] = [tag for tag in old.suite_tags if not tag.startswith("benchmark:")] + ["review:pending"]
        payload["provenance"] = {"source": old.identity, "method": "derived question; new snapshot, GT pending review",
                                 "created_at": utc_now(), "notes": "Historical reference evidence was not transferred."}
        candidate = EvaluationCaseBundle.from_dict(payload)
        candidate.to_json(case_dir / (candidate.case_id + ".json"))
        created.append(candidate)
    candidate_suite = EvaluationSuite(suite_id="candidate-" + suite.suite_id, version=1, kind=suite.kind,
                                      case_references=tuple(CaseReference(c.case_id, c.version) for c in created),
                                      description="Unreviewed candidates derived from " + suite.identity,
                                      created_at=utc_now())
    (output_dir / "suite.json").write_text(json.dumps(candidate_suite.to_dict(), ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    return {"suite": candidate_suite.identity, "cases": len(created), "review_status": "pending",
            "freeze_id": data["freeze_id"]}
