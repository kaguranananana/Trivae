"""Temporary, isolated APFS workspaces for repeatable evaluation runs."""
from __future__ import annotations

import errno
import fcntl
import json
import os
import shutil
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from .contracts import EvaluationContractError, utc_now
from .frozen_data import _validated_master, clone_frozen

WORKSPACE_ROOT_NAME = ".trivae-eval-workspaces"
WORKSPACE_MARKER = "workspace.json"
WORKSPACE_SCHEMA = "trivae-evaluation-workspace-v1"
DEFAULT_RETENTION = timedelta(days=7)


def _read_marker(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EvaluationContractError("workspace marker is missing or is not a regular file")
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationContractError("workspace marker cannot be read") from exc
    if not isinstance(marker, dict) or marker.get("schema") != WORKSPACE_SCHEMA:
        raise EvaluationContractError("workspace marker has an unsupported schema")
    if marker.get("workspace_id") != path.parent.name:
        raise EvaluationContractError("workspace marker does not match its directory")
    return marker


def _write_marker(directory: Path, marker: dict[str, Any]) -> None:
    temporary = directory / (WORKSPACE_MARKER + ".tmp")
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, directory / WORKSPACE_MARKER)


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise EvaluationContractError(f"workspace {field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EvaluationContractError(f"workspace {field} must be a timestamp") from exc
    if parsed.utcoffset() is None:
        raise EvaluationContractError(f"workspace {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _workspace_root(manifest_path: Path) -> Path:
    return manifest_path.resolve().parent / WORKSPACE_ROOT_NAME


def _safe_workspace_directory(root: Path, directory: Path) -> None:
    if root.is_symlink() or not root.is_dir() or directory.is_symlink() or not directory.is_dir():
        raise EvaluationContractError("workspace cleanup target is not a managed directory")
    if directory.resolve().parent != root.resolve():
        raise EvaluationContractError("workspace cleanup target escaped its managed root")


def _remove_managed_workspace(root: Path, directory: Path) -> None:
    _safe_workspace_directory(root, directory)
    marker = _read_marker(directory / WORKSPACE_MARKER)
    if marker.get("workspace_id") != directory.name:
        raise EvaluationContractError("workspace cleanup identity mismatch")
    shutil.rmtree(directory)
    try:
        root.rmdir()
    except FileNotFoundError:
        pass
    except OSError as exc:
        if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
            raise


def cleanup_stale_workspaces(
    freeze_manifest_path: Path,
    *,
    max_age: timedelta = DEFAULT_RETENTION,
    now: datetime | None = None,
) -> dict[str, list[str]]:
    """Remove only expired workspaces below the validated freeze's private workspace root."""

    if max_age < timedelta(0):
        raise ValueError("max_age must not be negative")
    _validated_master(freeze_manifest_path)
    root = _workspace_root(freeze_manifest_path)
    report: dict[str, list[str]] = {"removed": [], "active": [], "retained": [], "errors": []}
    if not root.exists():
        return report
    if root.is_symlink() or not root.is_dir():
        raise EvaluationContractError("managed workspace root is not a regular directory")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for directory in sorted(root.iterdir()):
        try:
            _safe_workspace_directory(root, directory)
            marker = _read_marker(directory / WORKSPACE_MARKER)
            lease_path = directory / ".lease"
            lease_flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            lease_fd = os.open(lease_path, lease_flags)
            try:
                if not stat.S_ISREG(os.fstat(lease_fd).st_mode):
                    raise EvaluationContractError("workspace lease is not a regular file")
                try:
                    fcntl.flock(lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    report["active"].append(directory.name)
                    continue
                created = _parse_time(marker.get("created_at"), "created_at")
                expiry_value = marker.get("retain_until")
                expires = _parse_time(expiry_value, "retain_until") if expiry_value is not None else created + max_age
                if current < expires:
                    report["retained"].append(directory.name)
                    continue
                _remove_managed_workspace(root, directory)
                report["removed"].append(directory.name)
            finally:
                os.close(lease_fd)
        except (OSError, EvaluationContractError, ValueError) as exc:
            report["errors"].append(f"{directory.name}: {type(exc).__name__}: {exc}")
    return report


class EvaluationWorkspace:
    """One validated isolated data clone with a lease and explicit persistence boundary."""

    def __init__(
        self,
        *,
        freeze_manifest_path: Path,
        directory: Path,
        root: Path,
        lease_file: Any,
        marker: dict[str, Any],
        cleanup_report: dict[str, list[str]],
        retention: timedelta,
        keep_debug_copy: bool,
    ) -> None:
        self.freeze_manifest_path = freeze_manifest_path.resolve()
        self.directory = directory
        self.root = root
        self.data_directory = directory / "data"
        self.freeze_path = self.data_directory / "freeze.json"
        self.marker = marker
        self.cleanup_report = cleanup_report
        self.retention = retention
        self.keep_debug_copy = keep_debug_copy
        self._lease_file = lease_file
        self._entered = False
        self._results_persisted = False
        self._closed = False

    @classmethod
    def create(
        cls,
        freeze_manifest_path: Path,
        *,
        keep_debug_copy: bool = False,
        retention: timedelta = DEFAULT_RETENTION,
    ) -> EvaluationWorkspace:
        """Validate a frozen master, clear expired work, then create two APFS database clones."""

        manifest_path = freeze_manifest_path.resolve(strict=True)
        data, _, _ = _validated_master(manifest_path)
        cleanup_report = cleanup_stale_workspaces(manifest_path, max_age=retention)
        root = _workspace_root(manifest_path)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise EvaluationContractError("managed workspace root is not a regular directory")
        directory = Path(tempfile.mkdtemp(prefix="run-", dir=root))
        lease_path = directory / ".lease"
        lease_file = lease_path.open("x+b")
        try:
            fcntl.flock(lease_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            created_at = utc_now()
            marker: dict[str, Any] = {
                "schema": WORKSPACE_SCHEMA,
                "workspace_id": directory.name,
                "status": "active",
                "created_at": created_at,
                "updated_at": created_at,
                "pid": os.getpid(),
                "freeze_id": data["freeze_id"],
                "snapshot_id": data["snapshot"]["snapshot_id"],
                "source_freeze_manifest": str(manifest_path),
                "storage_mode": "apfs_clonefile",
                "clone_method_verified": True,
                "results_persisted": False,
            }
            _write_marker(directory, marker)
            clone_frozen(manifest_path, directory / "data")
            # Revalidate the input and both copies immediately before exposing the workspace to a runner.
            _validated_master(manifest_path)
            return cls(
                freeze_manifest_path=manifest_path,
                directory=directory,
                root=root,
                lease_file=lease_file,
                marker=marker,
                cleanup_report=cleanup_report,
                retention=retention,
                keep_debug_copy=keep_debug_copy,
            )
        except BaseException:
            lease_file.close()
            if directory.exists() and not directory.is_symlink() and directory.resolve().parent == root.resolve():
                try:
                    shutil.rmtree(directory)
                except FileNotFoundError:
                    pass
            raise

    @property
    def database_path(self) -> Path:
        return self.data_directory / str(self.marker.get("canonical_file", ""))

    @property
    def semantic_index_path(self) -> Path | None:
        name = self.marker.get("semantic_file")
        return None if not isinstance(name, str) else self.data_directory / name

    def __enter__(self) -> EvaluationWorkspace:
        if self._entered or self._closed:
            raise RuntimeError("evaluation workspace cannot be entered more than once")
        manifest = json.loads(self.freeze_path.read_text(encoding="utf-8"))
        self.marker["canonical_file"] = manifest["canonical_file"]
        self.marker["semantic_file"] = manifest["semantic_file"]
        self._entered = True
        return self

    def mark_results_persisted(self) -> None:
        """Declare that Evaluation DB, Run projections, Trace projections and final manifest are durable."""

        if not self._entered or self._closed:
            raise RuntimeError("evaluation workspace is not active")
        self._results_persisted = True
        self.marker["results_persisted"] = True
        self.marker["status"] = "results_persisted"
        self.marker["updated_at"] = utc_now()
        _write_marker(self.directory, self.marker)

    def record_storage(self) -> dict[str, object]:
        return {
            "mode": "temporary_apfs_clonefile",
            "clone_method_verified": True,
            "source_freeze_manifest": str(self.freeze_manifest_path),
            "workspace_id": self.directory.name,
            "recovered_workspaces": self.cleanup_report,
        }

    def _release(self) -> None:
        if not self._closed:
            self._closed = True
            self._lease_file.close()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        retain = self.keep_debug_copy
        interrupted = exc_type is not None and (
            issubclass(exc_type, KeyboardInterrupt) or exc_type.__name__ == "CancelledError"
        )
        if interrupted:
            assert exc_type is not None
            retain = True
            self.marker["status"] = "interrupted_persisted" if self._results_persisted else "recovery_needed"
            self.marker["error_type"] = exc_type.__name__
        elif exc_type is not None and not self._results_persisted:
            retain = True
            self.marker["status"] = "recovery_needed"
            self.marker["error_type"] = getattr(exc_type, "__name__", str(exc_type))
        elif exc_type is not None:
            self.marker["status"] = "failed_persisted"
            self.marker["error_type"] = getattr(exc_type, "__name__", str(exc_type))
        elif not self._results_persisted:
            retain = True
            self.marker["status"] = "recovery_needed"
            self.marker["error_type"] = "ResultsNotPersisted"

        if retain:
            now = datetime.now(timezone.utc)
            self.marker["updated_at"] = now.isoformat(timespec="milliseconds")
            self.marker["retain_until"] = (now + self.retention).isoformat(timespec="milliseconds")
            _write_marker(self.directory, self.marker)
            self._release()
            if exc_type is None and not self._results_persisted:
                raise RuntimeError("evaluation workspace results were not persisted; recovery copy was retained")
            return False

        _write_marker(self.directory, self.marker)
        try:
            # Keep the lease held through removal so a concurrent reaper cannot claim the same path.
            _remove_managed_workspace(self.root, self.directory)
        except Exception as cleanup_error:
            self._release()
            if exc_value is not None:
                raise RuntimeError("evaluation workspace cleanup failed; recovery data remains on disk") from exc_value
            raise cleanup_error
        self._release()
        return False
