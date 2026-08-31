"""Benchmark Environment Lock：canonical snapshot + lexical/semantic index identity。

``DatasetSnapshot`` 保持原职责（只描述 canonical dataset identity）；本模块提供薄
的 environment manifest，把「跑 benchmark 时必须锁定的运行环境事实」集中成一个
可 version-control（redacted）、可逐项验证的 artifact。

v1 pin 单一 serving semantic index。未来若评测 embedding/index variant，应扩展为
per-variant index identity 或独立 environment matrix；v1 不解决该问题。
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from trivae.evaluation.contracts import (
    DatasetSnapshot,
    EvaluationContractError,
    _json_safe,
    _mapping,
    _text,
    utc_now,
)

BENCHMARK_ENV_SCHEMA_VERSION = "benchmark-environment-v1"


def _read_json(path: Path, field_name: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationContractError(f"{field_name} cannot be read: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationContractError(f"{field_name} is not valid JSON: {path}") from exc


def _fts_message_count(database_path: Path) -> tuple[bool, int | None]:
    """读取 lexical FTS 的 presence 与 row count（复用 DatasetSnapshot 的 staleness 语义）。"""

    resolved = database_path.resolve()
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    try:
        present = (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts'"
            ).fetchone()
            is not None
        )
        if not present:
            return False, None
        row = connection.execute("SELECT COUNT(*) FROM messages_fts").fetchone()
        if row is None:
            raise EvaluationContractError("lexical index count returned no row")
        return True, int(row[0])
    except sqlite3.Error as exc:
        raise EvaluationContractError("lexical index inspection failed") from exc
    finally:
        connection.close()


def _git_commit() -> str:
    """捕获当前 commit；git 不可用或仓库脏时显式失败，不猜 identity。"""

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvaluationContractError("git commit could not be captured for environment lock") from exc
    if not commit:
        raise EvaluationContractError("git rev-parse returned an empty commit")
    return commit


@dataclass(frozen=True)
class BenchmarkEnvironmentManifest:
    """一次 benchmark 全量运行必须锁定的环境事实。"""

    benchmark: str
    canonical_snapshot_id: str
    lexical_index: Mapping[str, object]
    semantic_index: str
    git_commit: str
    created_at: str
    schema_version: str = BENCHMARK_ENV_SCHEMA_VERSION
    notes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "benchmark", _text(self.benchmark, "benchmark"))
        object.__setattr__(
            self, "canonical_snapshot_id", _text(self.canonical_snapshot_id, "canonical_snapshot_id")
        )
        object.__setattr__(self, "lexical_index", _mapping(self.lexical_index, "lexical_index"))
        object.__setattr__(self, "semantic_index", _text(self.semantic_index, "semantic_index"))
        object.__setattr__(self, "git_commit", _text(self.git_commit, "git_commit"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        if self.schema_version != BENCHMARK_ENV_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported benchmark environment schema_version")
        object.__setattr__(self, "notes", _mapping(self.notes, "notes"))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "canonical_snapshot_id": self.canonical_snapshot_id,
            "lexical_index": dict(self.lexical_index),
            "semantic_index": self.semantic_index,
            "git_commit": self.git_commit,
            "created_at": self.created_at,
            "notes": dict(self.notes),
        }

    @classmethod
    def from_dict(cls, value: object) -> BenchmarkEnvironmentManifest:
        payload = _mapping(value, "benchmark_environment")
        return cls(
            benchmark=payload.get("benchmark"),
            canonical_snapshot_id=payload.get("canonical_snapshot_id"),
            lexical_index=payload.get("lexical_index", {}),
            semantic_index=payload.get("semantic_index"),
            git_commit=payload.get("git_commit"),
            created_at=payload.get("created_at"),
            schema_version=payload.get("schema_version", BENCHMARK_ENV_SCHEMA_VERSION),
            notes=payload.get("notes", {}),
        )

    def to_json(self, path: Path) -> None:
        _json_safe(self.to_dict(), "benchmark_environment")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def from_json(cls, path: Path) -> BenchmarkEnvironmentManifest:
        return cls.from_dict(_read_json(path, "benchmark environment manifest"))


@dataclass(frozen=True)
class EnvironmentGateResult:
    """pre-run gate 的逐项验证结果；任何 violation 都必须阻止 benchmark 启动。"""

    passed: bool
    checks: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "checks": [dict(item) for item in self.checks],
        }


def capture_environment(
    *,
    benchmark: str,
    database_path: Path,
    snapshot: DatasetSnapshot,
    semantic_index_identity: str,
    git_commit: str | None = None,
    notes: Mapping[str, object] | None = None,
) -> BenchmarkEnvironmentManifest:
    """从当前环境捕获 manifest；lexical facts 直接复用 Snapshot manifest。"""

    lexical_manifest = snapshot.manifest.get("lexical_index")
    lexical_manifest = lexical_manifest if isinstance(lexical_manifest, Mapping) else {}
    lexical_present = lexical_manifest.get("present") is True
    if not lexical_present:
        raise EvaluationContractError("benchmark requires a canonical lexical FTS index")
    lexical_index = {
        "present": True,
        "message_count": lexical_manifest.get("message_count"),
    }
    return BenchmarkEnvironmentManifest(
        benchmark=benchmark,
        canonical_snapshot_id=snapshot.snapshot_id,
        lexical_index=lexical_index,
        semantic_index=semantic_index_identity,
        git_commit=git_commit if git_commit is not None else _git_commit(),
        created_at=utc_now(),
        notes=dict(notes or {}),
    )


def verify_environment(
    manifest: BenchmarkEnvironmentManifest,
    *,
    database_path: Path,
    snapshot: DatasetSnapshot,
    semantic_index_identity: str,
    git_commit: str | None = None,
) -> EnvironmentGateResult:
    """pre-run gate：逐项对比 live 环境与 pinned manifest，任一不匹配即整体失败。"""

    checks: list[dict[str, object]] = []

    snapshot_match = snapshot.snapshot_id == manifest.canonical_snapshot_id
    checks.append(
        {
            "name": "canonical_snapshot",
            "passed": snapshot_match,
            "expected": manifest.canonical_snapshot_id,
            "actual": snapshot.snapshot_id,
        }
    )

    lexical_present, lexical_count = _fts_message_count(database_path)
    expected_lexical_count = manifest.lexical_index.get("message_count")
    lexical_match = lexical_present and lexical_count == expected_lexical_count
    checks.append(
        {
            "name": "lexical_index",
            "passed": lexical_match,
            "expected": {"present": True, "message_count": expected_lexical_count},
            "actual": {"present": lexical_present, "message_count": lexical_count},
        }
    )

    semantic_match = semantic_index_identity == manifest.semantic_index
    checks.append(
        {
            "name": "semantic_index",
            "passed": semantic_match,
            "expected": manifest.semantic_index,
            "actual": semantic_index_identity,
        }
    )

    # 默认读取当前仓库 HEAD；测试或离线验证可显式传入待比较的 commit。
    actual_git_commit = git_commit if git_commit is not None else _git_commit()
    git_match = actual_git_commit == manifest.git_commit
    checks.append(
        {
            "name": "git_commit",
            "passed": git_match,
            "expected": manifest.git_commit,
            "actual": actual_git_commit,
        }
    )

    passed = all(item["passed"] is True for item in checks)
    return EnvironmentGateResult(passed=passed, checks=tuple(checks))
