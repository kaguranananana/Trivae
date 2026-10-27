"""Record reproducibility conditions around the existing EvaluationRunner."""
from __future__ import annotations

import json
import platform
import sqlite3
from collections import Counter
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Any

from trivae.config.settings import load_router_jev_settings, load_settings

from .benchmark.environment import _git_commit
from .contracts import (
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationRun,
    EvaluationSuite,
    utc_now,
)
from .frozen_data import _metadata
from .variant import ControlledVariant


def prepare_experiment(*, suite: EvaluationSuite, cases: Mapping[str, EvaluationCaseBundle], variant: ControlledVariant,
                       database: Path, freeze_path: Path, output_dir: Path, repetitions: int,
                       judge_version: str) -> dict[str, Any]:
    try:
        frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
        if frozen.get("role") != "working_copy":
            raise EvaluationContractError("formal evaluation requires a working copy, not the frozen master")
        if freeze_path.parent.resolve() != database.parent.resolve() or frozen["canonical_file"] != database.name:
            raise EvaluationContractError("run must use the working clone containing the freeze manifest")
        semantic_name = frozen["semantic_file"]
        semantic = database.parent / semantic_name if semantic_name else None
        if semantic is None and "semantic_search" in variant.available_tools:
            raise EvaluationContractError("semantic-search experiments require a frozen semantic index")
        if _metadata(database, semantic) != frozen["index_state"]:
            raise EvaluationContractError("working data/index revisions differ from frozen master")
        if semantic is not None and "semantic_search" in variant.available_tools:
            try:
                declared_index = json.loads(variant.index_identity)
            except ValueError as exc:
                raise EvaluationContractError("semantic variant must declare its index identity") from exc
            if declared_index != frozen["index_state"].get("semantic_index"):
                raise EvaluationContractError("declared semantic index differs from the frozen index")
        snapshot = DatasetSnapshot.from_database(database)
        if snapshot.deterministic_fingerprint != frozen["snapshot"]["deterministic_fingerprint"]:
            raise EvaluationContractError("working data manifest differs from frozen master")
        selected = [cases[ref.identity] for ref in suite.case_references]
        for case in selected:
            if (case.dataset_snapshot.snapshot_id != snapshot.snapshot_id or
                    case.dataset_snapshot.deterministic_fingerprint != snapshot.deterministic_fingerprint):
                raise EvaluationContractError("case snapshot differs from frozen data; create a new case version")
        settings = load_settings()
        if (settings.provider, settings.model_name) != (variant.provider, variant.model):
            raise EvaluationContractError("declared variant provider/model differs from actual runtime settings")
        commit = _git_commit()
        if variant.code_version not in (commit, commit[:len(variant.code_version)]):
            raise EvaluationContractError("declared variant code_version differs from checked-out commit")
        if repetitions <= 0 or not judge_version.strip():
            raise EvaluationContractError("repetitions and judge version must be specified")
        try:
            output_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise EvaluationContractError("experiment output directory already exists") from exc
        manifest: dict[str, Any] = {
            "schema_version": 1, "status": "running", "created_at": utc_now(), "suite": suite.to_dict(),
            "cases": [case.to_dict() for case in selected], "freeze_id": frozen["freeze_id"],
            "snapshot": frozen["snapshot"], "index_state": frozen["index_state"], "git_commit": commit,
            "variant": variant.to_dict(), "runtime_settings": settings.to_safe_dict(),
            "router_settings": load_router_jev_settings().to_safe_dict(), "judge_version": judge_version,
            "python": platform.python_version(), "openai_agents_version": metadata.version("openai-agents"),
            "repetitions": repetitions, "runs": [],
        }
        write_manifest(output_dir, manifest)
        return manifest
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        if isinstance(exc, EvaluationContractError):
            raise
        raise EvaluationContractError("cannot prepare experiment manifest; inspect data and case versions") from exc

def write_manifest(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    (output_dir / "experiment.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def finish_experiment(output_dir: Path, manifest: dict[str, Any], runs: tuple[EvaluationRun, ...], *,
                      error_type: str | None = None) -> None:
    manifest["status"] = "failed" if error_type else "completed"
    manifest["completed_at"] = utc_now()
    manifest["error_type"] = error_type
    manifest["runs"] = [{"run_id": r.run_id, "case": f"{r.case_id}@v{r.case_version}", "trace_id": r.trace_id,
                         "terminal_status": r.terminal_status,
                         "failed_checks": [c.name for c in r.deterministic_checks if c.status == "failed"]}
                        for r in runs]
    write_manifest(output_dir, manifest)


def compare_experiments(baseline_path: Path, candidate_path: Path) -> dict[str, Any]:
    try:
        a = json.loads(baseline_path.read_text(encoding="utf-8"))
        b = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvaluationContractError("experiment manifest cannot be read") from exc
    reasons = []
    for key in ("suite", "cases", "freeze_id", "snapshot", "index_state", "judge_version", "repetitions"):
        if a.get(key) != b.get(key):
            reasons.append(key + " differs")
    if a.get("status") != "completed" or b.get("status") != "completed":
        reasons.append("one or both experiments did not complete")
    expected = len(a.get("cases", [])) * a.get("repetitions", 0)
    if len(a.get("runs", [])) != expected or len(b.get("runs", [])) != expected:
        reasons.append("run count is incomplete")
    identities = [f"{case['case_id']}@v{case['version']}" for case in a.get("cases", [])]
    expected_cases = Counter({identity: a.get("repetitions", 0) for identity in identities})
    for label, item in (("baseline", a), ("candidate", b)):
        if Counter(run.get("case") for run in item.get("runs", [])) != expected_cases:
            reasons.append(label + " case repetitions differ from suite")
    baseline_ids = {run.get("run_id") for run in a.get("runs", [])}
    candidate_ids = {run.get("run_id") for run in b.get("runs", [])}
    if baseline_ids & candidate_ids:
        reasons.append("baseline and candidate share run IDs")
    changed = [key for key in ("git_commit", "variant", "runtime_settings", "router_settings", "python",
                                "openai_agents_version") if a.get(key) != b.get(key)]
    return {"comparable": not reasons, "reasons": reasons, "changed_conditions": changed,
            "baseline_runs": a.get("runs", []), "candidate_runs": b.get("runs", [])}
