"""Create local, consistent SQLite data/index copies for repeatable evaluations."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .contracts import DatasetSnapshot, EvaluationContractError, utc_now


def _backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise EvaluationContractError("snapshot source database does not exist")
    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _metadata(canonical: Path, semantic: Path | None) -> dict[str, Any]:
    connection = sqlite3.connect(canonical.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        values = dict(connection.execute("SELECT key, value FROM trivae_derived_meta WHERE key IN "
                                         "('canonical_revision','lexical_canonical_revision')"))
    except sqlite3.Error as exc:
        raise EvaluationContractError("snapshot lacks canonical/lexical revision metadata") from exc
    finally:
        connection.close()
    if not values.get("canonical_revision") or values.get("canonical_revision") != values.get("lexical_canonical_revision"):
        raise EvaluationContractError("canonical and lexical revisions are missing or differ")
    result: dict[str, Any] = {"canonical_revision": int(values["canonical_revision"]),
                              "lexical_revision": int(values["lexical_canonical_revision"])}
    if semantic is not None:
        connection = sqlite3.connect(semantic.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = connection.execute("SELECT status, canonical_revision, identity_json FROM semantic_index_state "
                                     "WHERE state_id=1").fetchone()
        except sqlite3.Error as exc:
            raise EvaluationContractError("semantic snapshot state is unavailable") from exc
        finally:
            connection.close()
        if row is None or row[0] != "completed" or int(row[1]) != result["canonical_revision"]:
            raise EvaluationContractError("semantic index is not completed at the canonical revision")
        identity = json.loads(row[2])
        if identity.get("database_identity") != canonical.name:
            raise EvaluationContractError("semantic index database identity does not match canonical filename")
        result["semantic_index"] = identity
    return result


def freeze_data(canonical: Path, semantic: Path | None, output_dir: Path) -> dict[str, Any]:
    """Capture consistent content, lexical tables and optional semantic vectors using SQLite backup."""
    if semantic is not None and semantic.resolve() == canonical.resolve():
        raise EvaluationContractError("semantic database must be separate")
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise EvaluationContractError("snapshot output directory already exists") from exc
    frozen_canonical = output_dir / canonical.name
    frozen_semantic = output_dir / semantic.name if semantic else None
    _backup(canonical, frozen_canonical)
    if semantic is not None and frozen_semantic is not None:
        _backup(semantic, frozen_semantic)
    metadata = _metadata(frozen_canonical, frozen_semantic)
    snapshot = DatasetSnapshot.from_database(frozen_canonical)
    manifest = {"schema_version": 1, "freeze_id": "freeze-" + uuid.uuid4().hex,
                "created_at": utc_now(), "canonical_file": canonical.name,
                "semantic_file": semantic.name if semantic else None,
                "snapshot": snapshot.to_dict(), "index_state": metadata,
                "role": "master"}
    (output_dir / "freeze.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def clone_frozen(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    """Make a working copy; application stores conversations and traces in the canonical file."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        canonical_name = data["canonical_file"]
        semantic_name = data["semantic_file"]
        if not isinstance(canonical_name, str) or Path(canonical_name).name != canonical_name:
            raise ValueError("invalid canonical filename")
        if semantic_name is not None and (not isinstance(semantic_name, str) or Path(semantic_name).name != semantic_name):
            raise ValueError("invalid semantic filename")
        canonical = manifest_path.parent / canonical_name
        semantic = manifest_path.parent / semantic_name if semantic_name else None
        if _metadata(canonical, semantic) != data["index_state"]:
            raise EvaluationContractError("frozen master index state has changed")
        if DatasetSnapshot.from_database(canonical).deterministic_fingerprint != data["snapshot"]["deterministic_fingerprint"]:
            raise EvaluationContractError("frozen master snapshot metadata has changed")
        if data.get("role") != "master":
            raise EvaluationContractError("working copies cannot be used as frozen masters")
        output_dir.mkdir(parents=True, exist_ok=False)
        _backup(canonical, output_dir / canonical_name)
        if semantic is not None and semantic_name is not None:
            _backup(semantic, output_dir / semantic_name)
        data["role"] = "working_copy"
        (output_dir / "freeze.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"freeze_id": data["freeze_id"], "canonical_file": canonical_name, "semantic_file": semantic_name}
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        raise EvaluationContractError("cannot clone frozen data; inspect the local manifest and databases") from exc
