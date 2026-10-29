"""Create local, consistent SQLite data/index copies for repeatable evaluations."""
from __future__ import annotations

import ctypes
import errno
import json
import os
import sqlite3
import sys
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


def _clone_file(source: Path, destination: Path) -> None:
    """Create a verified filesystem copy-on-write clone, without a full-copy fallback."""

    if sys.platform != "darwin":
        raise EvaluationContractError("evaluation data clones require macOS APFS clonefile support")
    if source.is_symlink():
        raise EvaluationContractError("clone source must be a regular database file")
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise EvaluationContractError("clone destination already exists")
    if not source.is_file() or source.is_symlink():
        raise EvaluationContractError("clone source must be a regular database file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_dev != destination.parent.stat().st_dev:
        raise EvaluationContractError("APFS clone source and destination must be on the same volume")

    try:
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        clonefile = library.clonefile
    except (OSError, AttributeError) as exc:
        raise EvaluationContractError("macOS clonefile API is unavailable; refusing a full database copy") from exc
    clonefile.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
    clonefile.restype = ctypes.c_int
    result = clonefile(os.fsencode(source), os.fsencode(destination), 0)
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, "APFS clonefile failed; no full-copy fallback was attempted", str(destination))

    cloned = destination.stat()
    original = source.stat()
    if cloned.st_dev != original.st_dev or (cloned.st_dev, cloned.st_ino) == (original.st_dev, original.st_ino):
        destination.unlink(missing_ok=True)
        raise EvaluationContractError("clonefile did not create a separate file on the source volume")


def _validated_master(manifest_path: Path) -> tuple[dict[str, Any], Path, Path | None]:
    """Validate the frozen master and return its database paths before making any copy."""

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise EvaluationContractError("unsupported frozen snapshot manifest version")
        if data.get("role") != "master":
            raise EvaluationContractError("working copies cannot be used as frozen masters")
        if not isinstance(data.get("freeze_id"), str) or not data["freeze_id"].strip():
            raise EvaluationContractError("frozen snapshot manifest has no freeze identity")
        canonical_name = data["canonical_file"]
        semantic_name = data["semantic_file"]
        if not isinstance(canonical_name, str) or Path(canonical_name).name != canonical_name:
            raise EvaluationContractError("frozen snapshot manifest has an invalid canonical filename")
        if semantic_name is not None and (
            not isinstance(semantic_name, str) or Path(semantic_name).name != semantic_name
        ):
            raise EvaluationContractError("frozen snapshot manifest has an invalid semantic filename")
        canonical = manifest_path.parent / canonical_name
        semantic = manifest_path.parent / semantic_name if semantic_name else None
        for database in (canonical, semantic):
            if database is not None:
                wal_path = database.with_name(database.name + "-wal")
                if wal_path.exists() and wal_path.stat().st_size:
                    raise EvaluationContractError("frozen master has a nonempty SQLite WAL; create a closed freeze")
        if _metadata(canonical, semantic) != data["index_state"]:
            raise EvaluationContractError("frozen master index state has changed")
        actual = DatasetSnapshot.from_database(canonical)
        expected = DatasetSnapshot.from_dict(data["snapshot"])
        if (actual.snapshot_id != expected.snapshot_id
                or actual.deterministic_fingerprint != expected.deterministic_fingerprint):
            raise EvaluationContractError("frozen master snapshot metadata has changed")
        return data, canonical, semantic
    except EvaluationContractError:
        raise
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        raise EvaluationContractError("cannot validate frozen master; inspect its manifest and databases") from exc


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
    """Make an isolated APFS working copy of a validated frozen master."""

    created_output = False
    try:
        data, canonical, semantic = _validated_master(manifest_path)
        canonical_name = canonical.name
        semantic_name = None if semantic is None else semantic.name
        output_dir.mkdir(parents=True, exist_ok=False)
        created_output = True
        _clone_file(canonical, output_dir / canonical_name)
        if semantic is not None and semantic_name is not None:
            _clone_file(semantic, output_dir / semantic_name)
        if _metadata(output_dir / canonical_name,
                     output_dir / semantic_name if semantic_name else None) != data["index_state"]:
            raise EvaluationContractError("working clone index state differs from frozen master")
        cloned_snapshot = DatasetSnapshot.from_database(output_dir / canonical_name)
        if (cloned_snapshot.snapshot_id != data["snapshot"]["snapshot_id"]
                or cloned_snapshot.deterministic_fingerprint != data["snapshot"]["deterministic_fingerprint"]):
            raise EvaluationContractError("working clone snapshot differs from frozen master")
        # Revalidate the master after cloning to detect an unexpected concurrent replacement or mutation.
        master_after, _, _ = _validated_master(manifest_path)
        if (master_after["freeze_id"] != data["freeze_id"]
                or master_after["snapshot"] != data["snapshot"]
                or master_after["index_state"] != data["index_state"]):
            raise EvaluationContractError("frozen master identity changed while cloning")
        data["role"] = "working_copy"
        data["storage"] = {"mode": "apfs_clonefile", "source_freeze_manifest": str(manifest_path.resolve())}
        (output_dir / "freeze.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"freeze_id": data["freeze_id"], "canonical_file": canonical_name,
                "semantic_file": semantic_name, "clone_method": "apfs_clonefile"}
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        if created_output:
            import shutil

            try:
                shutil.rmtree(output_dir)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                raise EvaluationContractError("clone failed and partial output could not be cleaned") from cleanup_error
        raise EvaluationContractError("cannot clone frozen data; inspect the local manifest and databases") from exc
    except BaseException:
        if created_output:
            import shutil

            try:
                shutil.rmtree(output_dir)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                raise EvaluationContractError("interrupted clone and partial output could not be cleaned") from cleanup_error
        raise
