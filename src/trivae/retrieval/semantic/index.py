"""独立 sqlite-vec derived index 的 schema、状态和 dense candidate 读取。"""

from __future__ import annotations

import importlib
import json
import math
import sqlite3
import struct
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from trivae.retrieval.semantic.contracts import (
    SemanticChunk,
    SemanticChunkRange,
    SemanticIndexCandidate,
    SemanticIndexIdentity,
    SemanticIndexIntegrityReport,
    SemanticIndexStale,
    SemanticIndexState,
    SemanticIndexStatus,
    SemanticIndexStorageError,
    SemanticIndexUnavailable,
)


class SQLiteSemanticIndex:
    """把 semantic vectors 放在 canonical store 之外，并用 state 表作为可用性事实来源。"""

    def __init__(self, database_path: Path) -> None:
        self._incremental_active = False
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(self.database_path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._load_sqlite_vec()
            self._create_schema()
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            raise

    def _load_sqlite_vec(self) -> None:
        """显式加载 sqlite-vec；缺失时失败，不退回 Python 全表扫描。"""

        try:
            module = importlib.import_module("sqlite_vec")
            loader = getattr(module, "load", None)
            if not callable(loader):
                raise RuntimeError("sqlite_vec.load is unavailable")
            self._connection.enable_load_extension(True)
            loader(self._connection)
        except Exception as exc:
            raise SemanticIndexStorageError(
                f"sqlite-vec is required for semantic index: {type(exc).__name__}"
            ) from exc
        finally:
            try:
                self._connection.enable_load_extension(False)
            except sqlite3.Error:
                pass

    def _create_schema(self) -> None:
        """创建只包含 metadata/vector derived rows 的 schema。"""

        try:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS semantic_index_state (
                    state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
                    identity_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('building', 'completed', 'partial', 'failed')),
                    canonical_message_count INTEGER NOT NULL,
                    indexed_message_count INTEGER NOT NULL,
                    canonical_revision INTEGER NOT NULL DEFAULT 0,
                    forwarded_message_count INTEGER NOT NULL DEFAULT 0,
                    indexed_forwarded_message_count INTEGER NOT NULL DEFAULT 0,
                    embedding_input_format INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL,
                    last_error TEXT,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS semantic_chunks (
                    vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id TEXT NOT NULL UNIQUE,
                    parent_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    parent_start_message_id TEXT NOT NULL,
                    parent_end_message_id TEXT NOT NULL,
                    start_message_id TEXT NOT NULL,
                    end_message_id TEXT NOT NULL,
                    start_timestamp INTEGER NOT NULL,
                    end_timestamp INTEGER NOT NULL,
                    message_count INTEGER NOT NULL,
                    effective_chars INTEGER NOT NULL,
                    embedding_input TEXT
                );
                CREATE INDEX IF NOT EXISTS semantic_chunks_session_time
                    ON semantic_chunks(session_id, start_timestamp, end_timestamp);
                """
            )
            # 既有派生文件只迁移 metadata 列；旧 identity 仍由查询主链路明确判为 stale。
            columns = {str(row["name"]) for row in self._connection.execute("PRAGMA table_info(semantic_index_state)")}
            for name in ("canonical_revision", "forwarded_message_count", "indexed_forwarded_message_count"):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE semantic_index_state ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
                    )
            # 旧行没有输入凭据，保持 NULL；仅显式重建可以声明新格式完成。
            if "embedding_input_format" not in columns:
                self._connection.execute(
                    "ALTER TABLE semantic_index_state ADD COLUMN embedding_input_format INTEGER NOT NULL DEFAULT 0"
                )
            chunk_columns = {
                str(row["name"]) for row in self._connection.execute("PRAGMA table_info(semantic_chunks)")
            }
            if "embedding_input" not in chunk_columns:
                self._connection.execute("ALTER TABLE semantic_chunks ADD COLUMN embedding_input TEXT")
            self._connection.commit()
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(f"failed to create semantic index schema: {type(exc).__name__}: {exc}") from exc

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        """全量批次独立提交；增量的所有写操作由外层发布事务统一提交。"""

        if self._incremental_active:
            # connection 上下文会提交已有事务，因此增量期间只能复用当前事务。
            yield
        else:
            with self._connection:
                yield

    def supports_incremental(self) -> bool:
        """仅完整的新格式快照可作增量基线，打开旧文件不会伪造输入凭据。"""

        state = self.state()
        if (
            state is None
            or state.status != "completed"
            or state.indexed_message_count != state.canonical_message_count
            or state.indexed_forwarded_message_count != state.forwarded_message_count
        ):
            return False
        return self.has_replay_inputs()

    def has_replay_inputs(self) -> bool:
        """空旧索引与失败旧构建同样必须先迁移，不能伪造输入比较事实。"""

        row = self._connection.execute(
            "SELECT embedding_input_format FROM semantic_index_state WHERE state_id = 1"
        ).fetchone()
        # 独立格式标记区分“新版空索引”和“没有任何旧行可检查的旧版空索引”。
        return bool(
            row is not None
            and row[0] == 1
            and self._connection.execute(
                "SELECT 1 FROM semantic_chunks WHERE embedding_input IS NULL LIMIT 1"
            ).fetchone() is None
        )

    @contextmanager
    def incremental_transaction(
        self,
        identity: SemanticIndexIdentity,
        canonical_message_count: int,
        *,
        base_revision: int,
        canonical_revision: int,
        forwarded_message_count: int,
    ) -> Iterator[None]:
        """持有写锁后校验旧快照，原子发布新快照；异常与强停均回滚。"""

        if self._incremental_active:
            raise SemanticIndexStorageError("semantic incremental transaction is already active")
        entered = False
        try:
            # 写锁必须先于基线读取，第二个 builder 等待后不能提交已经过期的计划。
            self._connection.execute("BEGIN IMMEDIATE")
            state = self.state()
            if state is None or not self.supports_incremental():
                raise SemanticIndexUnavailable("semantic index requires a full rebuild before incremental updates")
            if state.identity.serialized != identity.serialized or state.canonical_revision != base_revision:
                raise SemanticIndexStale("semantic incremental base identity or revision changed")
            metadata, vectors, missing, orphan = self._vector_row_counts(identity.embedding.dimension)
            if metadata != state.chunk_count or metadata != vectors or missing or orphan:
                raise SemanticIndexStorageError(
                    "semantic incremental metadata/vector mismatch: "
                    f"state={state.chunk_count}, metadata={metadata}, vectors={vectors}, "
                    f"missing={missing}, orphan={orphan}"
                )
            # 临时表属于本次事务；旧输入与 float32 blob 留在 SQLite，避免 Python 持有整段向量。
            self._connection.execute(
                "CREATE TEMP TABLE semantic_incremental_reuse (embedding_input TEXT PRIMARY KEY, embedding BLOB NOT NULL)"
            )
            self._connection.execute(
                """
                UPDATE semantic_index_state
                SET status = 'building', canonical_message_count = ?, canonical_revision = ?,
                    forwarded_message_count = ?, last_error = NULL, updated_at = ?
                WHERE state_id = 1
                """,
                (canonical_message_count, canonical_revision, forwarded_message_count, _now_ms()),
            )
            self._incremental_active = True
            entered = True
            yield
            # 调用方须明确完成 coverage，再允许事务发布，避免遗漏 finish 时半成品被提交。
            completed = self.state()
            if (
                completed is None
                or completed.status != "completed"
                or completed.indexed_message_count != canonical_message_count
                or completed.indexed_forwarded_message_count != forwarded_message_count
            ):
                raise SemanticIndexStorageError("semantic incremental transaction did not complete its source coverage")
            self._connection.execute("DROP TABLE semantic_incremental_reuse")
            self._connection.commit()
        except BaseException as exc:
            # KeyboardInterrupt/SystemExit 同样回滚 vec0 和 metadata，旧版 revision 仍是可追踪事实。
            self._connection.rollback()
            self._incremental_active = False
            if entered:
                with self._connection:
                    # 只记录错误，不把未提交的新 revision 标成 completed 或破坏旧 coverage。
                    self._connection.execute(
                        "UPDATE semantic_index_state SET last_error = ?, updated_at = ? WHERE state_id = 1",
                        (f"{type(exc).__name__}: {exc}".rstrip(": "), _now_ms()),
                    )
            if isinstance(exc, sqlite3.Error):
                raise SemanticIndexStorageError(
                    f"semantic incremental transaction failed: {type(exc).__name__}: {exc}"
                ) from exc
            raise
        finally:
            self._incremental_active = False

    def prepare_incremental_ranges(
        self, ranges: Sequence[tuple[str, int | None, int | None]],
    ) -> int:
        """先保存受影响旧块的精确输入与向量，再删除对应 metadata/vector。"""

        if not self._incremental_active:
            raise SemanticIndexStorageError("semantic incremental ranges require an active transaction")
        state = self.state()
        assert state is not None
        table = self._vector_table(state.identity.embedding.dimension)
        removed = 0
        try:
            for session_id, start_timestamp, end_timestamp in ranges:
                clauses = ["session_id = ?"]
                parameters: list[object] = [session_id]
                if start_timestamp is not None:
                    # 范围是 inclusive，任何与安全时间段相交的旧块都须重切。
                    clauses.append("end_timestamp >= ?")
                    parameters.append(start_timestamp)
                if end_timestamp is not None:
                    clauses.append("start_timestamp <= ?")
                    parameters.append(end_timestamp)
                predicate = " AND ".join(clauses)
                ids = f"SELECT vector_id FROM semantic_chunks WHERE {predicate}"
                count = int(self._connection.execute(
                    f"SELECT COUNT(*) FROM semantic_chunks WHERE {predicate}", parameters,
                ).fetchone()[0])
                if count == 0:
                    # 新 session 或新版空基线没有旧向量表，也没有可删除的派生行。
                    continue
                self._connection.execute(
                    f"""
                    INSERT OR IGNORE INTO semantic_incremental_reuse(embedding_input, embedding)
                    SELECT c.embedding_input, v.embedding FROM semantic_chunks AS c
                    JOIN {table} AS v ON c.vector_id = v.vector_id
                    WHERE c.vector_id IN ({ids})
                    """,
                    parameters,
                )
                self._connection.execute(f"DELETE FROM {table} WHERE vector_id IN ({ids})", parameters)
                self._connection.execute(f"DELETE FROM semantic_chunks WHERE {predicate}", parameters)
                removed += count
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(
                f"failed to prepare semantic incremental ranges: {type(exc).__name__}: {exc}"
            ) from exc
        return removed

    def reusable_vectors(self, chunks: Sequence[SemanticChunk]) -> dict[str, tuple[float, ...]]:
        """按输入全文等值查询本次旧向量池；chunk ID 不参与向量正确性判定。"""

        if not self._incremental_active:
            raise SemanticIndexStorageError("semantic vector reuse requires an active transaction")
        state = self.state()
        assert state is not None
        reusable: dict[str, tuple[float, ...]] = {}
        try:
            for chunk in chunks:
                row = self._connection.execute(
                    "SELECT embedding FROM semantic_incremental_reuse WHERE embedding_input = ?",
                    (chunk.embedding_input,),
                ).fetchone()
                if row is not None:
                    reusable[chunk.chunk_id] = self._unpack_vector(row[0], state.identity.embedding.dimension)
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(
                f"semantic vector reuse query failed: {type(exc).__name__}: {exc}"
            ) from exc
        return reusable

    def start_rebuild(
        self,
        identity: SemanticIndexIdentity,
        canonical_message_count: int,
        *,
        canonical_revision: int = 0,
        forwarded_message_count: int = 0,
    ) -> None:
        """原子清空旧 vectors，写入新 identity，并进入 building。"""

        if canonical_message_count < 0:
            raise ValueError("canonical_message_count must be non-negative")
        try:
            with self._write_transaction():
                self._drop_vector_tables()
                self._connection.execute("DELETE FROM semantic_chunks")
                self._connection.execute(
                    """
                    INSERT INTO semantic_index_state(
                        state_id, identity_json, status, canonical_message_count,
                        indexed_message_count, chunk_count, last_error, updated_at,
                        canonical_revision, forwarded_message_count, indexed_forwarded_message_count,
                        embedding_input_format
                    ) VALUES (1, ?, 'building', ?, 0, 0, NULL, ?, ?, ?, 0, 1)
                    ON CONFLICT(state_id) DO UPDATE SET
                        identity_json = excluded.identity_json,
                        status = excluded.status,
                        canonical_message_count = excluded.canonical_message_count,
                        indexed_message_count = excluded.indexed_message_count,
                        chunk_count = excluded.chunk_count,
                        last_error = excluded.last_error,
                        updated_at = excluded.updated_at,
                        canonical_revision = excluded.canonical_revision,
                        forwarded_message_count = excluded.forwarded_message_count,
                        indexed_forwarded_message_count = excluded.indexed_forwarded_message_count,
                        embedding_input_format = excluded.embedding_input_format
                    """,
                    (identity.serialized, canonical_message_count, _now_ms(), canonical_revision, forwarded_message_count),
                )
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(f"failed to start semantic rebuild: {type(exc).__name__}: {exc}") from exc

    def insert_chunks(self, chunks: Sequence[tuple[SemanticChunk, Sequence[float]]]) -> None:
        """在同一事务写入 chunk metadata 与对应 vec0 row。"""

        if not chunks:
            return
        state = self.state()
        if state is None or state.status != "building":
            raise SemanticIndexStorageError("semantic chunks can only be inserted during a rebuild")
        dimension = state.identity.embedding.dimension
        table = self._vector_table(dimension)
        try:
            with self._write_transaction():
                self._create_vector_table(dimension)
                for chunk, vector_values in chunks:
                    vector = self._validate_vector(vector_values, dimension)
                    row = self._connection.execute(
                        """
                        INSERT INTO semantic_chunks(
                            chunk_id, parent_id, session_id, parent_start_message_id,
                            parent_end_message_id, start_message_id, end_message_id,
                            start_timestamp, end_timestamp, message_count, effective_chars, embedding_input
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk.chunk_id,
                            chunk.parent_id,
                            chunk.session_id,
                            chunk.parent_start_message_id,
                            chunk.parent_end_message_id,
                            chunk.start_message_id,
                            chunk.end_message_id,
                            chunk.start_timestamp,
                            chunk.end_timestamp,
                            chunk.message_count,
                            chunk.effective_chars,
                            chunk.embedding_input,
                        ),
                    )
                    if row.lastrowid is None:
                        raise SemanticIndexStorageError("semantic chunk insert returned no vector id")
                    vector_id = int(row.lastrowid)
                    self._connection.execute(
                        f"INSERT INTO {table}(vector_id, embedding) VALUES (?, ?)",
                        (vector_id, self._pack_vector(vector)),
                    )
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(f"failed to insert semantic chunks: {type(exc).__name__}") from exc

    def begin_resume(
        self,
        identity: SemanticIndexIdentity,
        canonical_message_count: int,
        *,
        canonical_revision: int = 0,
        forwarded_message_count: int = 0,
    ) -> int:
        """只续建相同源快照的未完成索引，任何校验失败都保留原 rows/state。"""

        state = self.state()
        if state is None:
            raise SemanticIndexUnavailable("semantic index is missing; cannot resume it")
        if state.identity.serialized != identity.serialized:
            raise SemanticIndexStale("semantic index identity changed; cannot resume it")
        if (
            state.canonical_message_count != canonical_message_count
            or state.canonical_revision != canonical_revision
            or state.forwarded_message_count != forwarded_message_count
        ):
            raise SemanticIndexStale("semantic index source snapshot changed; cannot resume it")
        if state.status == "completed":
            raise SemanticIndexUnavailable("semantic index is completed; there is no unfinished build to resume")
        try:
            # 同批 metadata 与 vector 必须完整配对；不把真实损坏当作可复用缓存。
            metadata_count, vector_count, missing, orphan = self._vector_row_counts(identity.embedding.dimension)
            if metadata_count != vector_count or missing or orphan:
                raise SemanticIndexStorageError(
                    "semantic resume metadata/vector mismatch: "
                    f"metadata={metadata_count}, vectors={vector_count}, missing={missing}, orphan={orphan}"
                )
            # insert 与 progress 分属两个事务，强停允许 state 水位落后已经原子提交的 rows。
            if metadata_count < state.chunk_count:
                raise SemanticIndexStorageError(
                    "semantic resume chunk count is below saved progress: "
                    f"state={state.chunk_count}, metadata={metadata_count}"
                )
            with self._write_transaction():
                # 进度由确定性重放恢复；此处只校正 chunk 事实并显式开启新一次执行。
                self._connection.execute(
                    """
                    UPDATE semantic_index_state
                    SET status = 'building', chunk_count = ?, last_error = NULL, updated_at = ?
                    WHERE state_id = 1
                    """,
                    (metadata_count, _now_ms()),
                )
            return metadata_count
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(
                f"failed to begin semantic resume: {type(exc).__name__}: {exc}"
            ) from exc

    def reusable_chunk_ids(self, chunks: Sequence[SemanticChunk]) -> frozenset[str]:
        """有界检查重放 chunk 的全部持久 metadata，返回可以直接复用的 ID。"""

        if not chunks:
            return frozenset()
        state = self.state()
        if state is None or state.status != "building":
            raise SemanticIndexStorageError("semantic chunks can only be reused during a resumed build")
        placeholders = ", ".join("?" for _ in chunks)
        fields = (
            "chunk_id", "parent_id", "session_id", "parent_start_message_id", "parent_end_message_id",
            "start_message_id", "end_message_id", "start_timestamp", "end_timestamp", "message_count", "effective_chars",
            "embedding_input",
        )
        try:
            rows = self._connection.execute(
                f"SELECT vector_id, {', '.join(fields)} FROM semantic_chunks WHERE chunk_id IN ({placeholders})",
                tuple(chunk.chunk_id for chunk in chunks),
            ).fetchall()
            # 首批尚未产生 vec 表时没有旧块，因此可以直接计算本批。
            if not rows:
                return frozenset()
            table = self._vector_table(state.identity.embedding.dimension)
            vector_ids = {
                int(row[0])
                for row in self._connection.execute(
                    f"SELECT vector_id FROM {table} WHERE vector_id IN ({', '.join('?' for _ in rows)})",
                    tuple(int(row["vector_id"]) for row in rows),
                )
            }
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(
                f"semantic resume chunk lookup failed: {type(exc).__name__}: {exc}"
            ) from exc

        replayed = {chunk.chunk_id: chunk for chunk in chunks}
        for row in rows:
            chunk = replayed[str(row["chunk_id"])]
            # 重放同时比较精确输入，避免同边界但正文改变的旧向量被复用。
            for field in fields:
                if row[field] != getattr(chunk, field):
                    raise SemanticIndexStorageError(
                        f"semantic resume chunk metadata mismatch: {chunk.chunk_id}, field={field}"
                    )
            if int(row["vector_id"]) not in vector_ids:
                raise SemanticIndexStorageError(f"semantic resume chunk is missing its vector: {chunk.chunk_id}")
        return frozenset(str(row["chunk_id"]) for row in rows)

    def update_progress(self, indexed_message_count: int, *, indexed_forwarded_message_count: int = 0) -> None:
        """更新 canonical processed watermark，不把 chunk 数冒充 coverage。"""

        if indexed_message_count < 0:
            raise ValueError("indexed_message_count must be non-negative")
        try:
            with self._write_transaction():
                cursor = self._connection.execute(
                    """
                    UPDATE semantic_index_state
                    SET indexed_message_count = ?, indexed_forwarded_message_count = ?, chunk_count = (
                        SELECT COUNT(*) FROM semantic_chunks
                    ), updated_at = ?
                    WHERE state_id = 1 AND status = 'building'
                    """,
                    (indexed_message_count, indexed_forwarded_message_count, _now_ms()),
                )
                if cursor.rowcount != 1:
                    raise SemanticIndexStorageError("semantic rebuild state is not writable")
        except sqlite3.Error as exc:
            if isinstance(exc, SemanticIndexStorageError):
                raise
            raise SemanticIndexStorageError(f"failed to update semantic progress: {type(exc).__name__}: {exc}") from exc

    def finish(self, status: SemanticIndexStatus, error: str | None = None) -> None:
        """写入显式终态；failed 也保留错误信息，不伪装成 completed。"""

        if status == "building":
            raise ValueError("finish status must be a terminal status")
        try:
            with self._write_transaction():
                cursor = self._connection.execute(
                    """
                    UPDATE semantic_index_state
                    SET status = ?, chunk_count = (SELECT COUNT(*) FROM semantic_chunks),
                        last_error = ?, updated_at = ?
                    WHERE state_id = 1
                    """,
                    (status, error, _now_ms()),
                )
                if cursor.rowcount != 1:
                    raise SemanticIndexStorageError("semantic rebuild state does not exist")
        except sqlite3.Error as exc:
            if isinstance(exc, SemanticIndexStorageError):
                raise
            raise SemanticIndexStorageError(f"failed to finish semantic rebuild: {type(exc).__name__}") from exc

    def state(self) -> SemanticIndexState | None:
        """读取可追踪 state；损坏 metadata 直接暴露为 storage error。"""

        row = self._connection.execute(
            """
            SELECT identity_json, status, canonical_message_count, indexed_message_count,
                   chunk_count, last_error, updated_at, canonical_revision,
                   forwarded_message_count, indexed_forwarded_message_count
            FROM semantic_index_state
            WHERE state_id = 1
            """
        ).fetchone()
        if row is None:
            return None
        try:
            identity_value = json.loads(str(row["identity_json"]))
            identity = SemanticIndexIdentity.from_dict(identity_value)
            status = str(row["status"])
            if status not in ("building", "completed", "partial", "failed"):
                raise ValueError(f"unknown semantic index status {status}")
            return SemanticIndexState(
                identity=identity,
                status=status,  # type: ignore[arg-type]
                canonical_message_count=int(row["canonical_message_count"]),
                indexed_message_count=int(row["indexed_message_count"]),
                chunk_count=int(row["chunk_count"]),
                last_error=None if row["last_error"] is None else str(row["last_error"]),
                updated_at=int(row["updated_at"]),
                canonical_revision=int(row["canonical_revision"]),
                forwarded_message_count=int(row["forwarded_message_count"]),
                indexed_forwarded_message_count=int(row["indexed_forwarded_message_count"]),
            )
        except Exception as exc:
            if isinstance(exc, SemanticIndexStorageError):
                raise
            raise SemanticIndexStorageError(f"semantic index state metadata is invalid: {type(exc).__name__}: {exc}") from exc

    def size_bytes(self) -> int:
        """返回 derived database 主文件大小，供 rebuild report 记录。"""

        try:
            return self.database_path.stat().st_size
        except OSError as exc:
            raise SemanticIndexStorageError("semantic index file size cannot be read") from exc

    def integrity_report(
        self,
        identity: SemanticIndexIdentity,
        *,
        sample_size: int = 16,
    ) -> SemanticIndexIntegrityReport:
        """验证 metadata/vector 对应关系，并抽样检查持久化向量范数。"""

        if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size <= 0:
            raise ValueError("semantic integrity sample_size must be positive")
        state = self._queryable_state(identity)
        dimension = identity.embedding.dimension
        table = self._vector_table(dimension)
        try:
            metadata_count, vector_count, missing_vector_count, orphan_vector_count = self._vector_row_counts(dimension)
            parent_count = int(
                self._connection.execute(
                    "SELECT COUNT(DISTINCT parent_id) FROM semantic_chunks"
                ).fetchone()[0]
            )
            vector_rows = self._connection.execute(
                f"SELECT embedding FROM {table} ORDER BY vector_id ASC LIMIT ?",
                (sample_size,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(
                f"semantic index integrity query failed: {type(exc).__name__}"
            ) from exc

        # sqlite-vec 返回 float32 blob；只抽样计算，不把原始向量放进 report。
        max_norm_deviation = 0.0
        for row in vector_rows:
            vector = self._unpack_vector(row["embedding"], dimension)
            norm = math.sqrt(sum(value * value for value in vector))
            max_norm_deviation = max(max_norm_deviation, abs(norm - 1.0))
        normalized_invalid = identity.embedding.normalized and max_norm_deviation > 1e-4
        invalid = any(
            (
                state.chunk_count != metadata_count,
                metadata_count != vector_count,
                missing_vector_count != 0,
                orphan_vector_count != 0,
                normalized_invalid,
            )
        )
        return SemanticIndexIntegrityReport(
            status="invalid" if invalid else "valid",
            identity=identity,
            dimension=dimension,
            parent_count=parent_count,
            metadata_chunk_count=metadata_count,
            vector_count=vector_count,
            missing_vector_count=missing_vector_count,
            orphan_vector_count=orphan_vector_count,
            sampled_vector_count=len(vector_rows),
            max_sample_norm_deviation=max_norm_deviation,
        )

    def sample_ranges(
        self,
        identity: SemanticIndexIdentity,
        *,
        sample_size: int = 16,
    ) -> tuple[SemanticChunkRange, ...]:
        """从索引首尾抽取 bounded range，用于跨库 canonical recovery 校验。"""

        if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size <= 0:
            raise ValueError("semantic range sample_size must be positive")
        self._queryable_state(identity)
        first_count = (sample_size + 1) // 2
        last_count = sample_size // 2
        columns = "chunk_id, session_id, start_message_id, end_message_id, message_count"
        try:
            rows = list(
                self._connection.execute(
                    f"SELECT {columns} FROM semantic_chunks ORDER BY vector_id ASC LIMIT ?",
                    (first_count,),
                ).fetchall()
            )
            if last_count:
                rows.extend(
                    self._connection.execute(
                        f"SELECT {columns} FROM semantic_chunks ORDER BY vector_id DESC LIMIT ?",
                        (last_count,),
                    ).fetchall()
                )
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(
                f"semantic range sample failed: {type(exc).__name__}"
            ) from exc

        ranges: list[SemanticChunkRange] = []
        seen: set[str] = set()
        for row in rows:
            chunk_id = str(row["chunk_id"])
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            ranges.append(
                SemanticChunkRange(
                    chunk_id=chunk_id,
                    session_id=str(row["session_id"]),
                    start_message_id=str(row["start_message_id"]),
                    end_message_id=str(row["end_message_id"]),
                    message_count=int(row["message_count"]),
                )
            )
        return tuple(ranges)

    def dense_search(
        self,
        identity: SemanticIndexIdentity,
        query_vector: Sequence[float],
        limit: int,
        *,
        session_ids: Sequence[str] | None = None,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
    ) -> tuple[SemanticIndexCandidate, ...]:
        """执行 sqlite-vec ANN 查询并按 chunk range 过滤，不做 Python 全表相似度计算。"""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("semantic dense search limit must be positive")
        self._queryable_state(identity)
        dimension = identity.embedding.dimension
        vector = self._validate_vector(query_vector, dimension)
        table = self._vector_table(dimension)
        clauses = ["v.embedding MATCH ?", "v.k = ?"]
        parameters: list[object] = [self._pack_vector(vector), limit]
        # vec0 必须先限制合法 vector_id 再取 Top-K，否则其他群会挤掉目标群的候选。
        scope_clauses: list[str] = []
        if session_ids is not None:
            if not session_ids:
                return ()
            placeholders = ", ".join("?" for _ in session_ids)
            scope_clauses.append(f"session_id IN ({placeholders})")
            parameters.extend(session_ids)
        if start_timestamp is not None:
            scope_clauses.append("end_timestamp >= ?")
            parameters.append(start_timestamp)
        if end_timestamp is not None:
            scope_clauses.append("start_timestamp < ?")
            parameters.append(end_timestamp)
        if scope_clauses:
            clauses.append(
                "v.vector_id IN (SELECT vector_id FROM semantic_chunks WHERE " + " AND ".join(scope_clauses) + ")"
            )
        try:
            rows = self._connection.execute(
                f"""
                SELECT c.chunk_id, c.parent_id, c.session_id,
                       c.parent_start_message_id, c.parent_end_message_id,
                       c.start_message_id, c.end_message_id,
                       c.start_timestamp, c.end_timestamp,
                       c.message_count, c.effective_chars,
                       v.distance
                FROM {table} AS v
                INNER JOIN semantic_chunks AS c ON c.vector_id = v.vector_id
                WHERE {' AND '.join(clauses)}
                ORDER BY v.distance ASC, c.chunk_id ASC
                """,
                parameters,
            ).fetchall()
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(f"semantic dense search failed: {type(exc).__name__}: {exc}") from exc
        # 所有返回候选已在当前群与外层时间范围内参与 KNN，再执行确定性并列排序。
        candidates = []
        for rank, row in enumerate(rows[:limit], start=1):
            candidates.append(
                SemanticIndexCandidate(
                    chunk_id=str(row["chunk_id"]),
                    parent_id=str(row["parent_id"]),
                    session_id=str(row["session_id"]),
                    parent_start_message_id=str(row["parent_start_message_id"]),
                    parent_end_message_id=str(row["parent_end_message_id"]),
                    start_message_id=str(row["start_message_id"]),
                    end_message_id=str(row["end_message_id"]),
                    start_timestamp=int(row["start_timestamp"]),
                    end_timestamp=int(row["end_timestamp"]),
                    message_count=int(row["message_count"]),
                    effective_chars=int(row["effective_chars"]),
                    distance=float(row["distance"]),
                    dense_rank=rank,
                )
            )
        return tuple(candidates)

    def close(self) -> None:
        """释放独立 derived connection。"""

        self._connection.close()

    def _queryable_state(self, identity: SemanticIndexIdentity) -> SemanticIndexState:
        """集中处理 missing/building/failed/stale，避免 retrieval 偷偷改变策略。"""

        state = self.state()
        if state is None:
            raise SemanticIndexUnavailable("semantic index is unavailable; build it first")
        if state.identity.serialized != identity.serialized:
            raise SemanticIndexStale("semantic index identity is stale; rebuild it")
        if state.status == "building":
            raise SemanticIndexUnavailable("semantic index is building")
        if state.status == "failed":
            message = state.last_error or "semantic index build failed"
            raise SemanticIndexUnavailable(message)
        if state.chunk_count <= 0:
            raise SemanticIndexUnavailable("semantic index has no vector chunks")
        return state

    def _vector_row_counts(self, dimension: int) -> tuple[int, int, int, int]:
        """续建与完整性检查共享 metadata/vector 一一对应检查，不读取向量正文。"""

        metadata_count = int(self._connection.execute("SELECT COUNT(*) FROM semantic_chunks").fetchone()[0])
        table = self._vector_table(dimension)
        exists = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists is None and metadata_count == 0:
            # 模型首次调用前失败时，vec 表尚未创建，零块是合法未完成状态。
            return 0, 0, 0, 0
        vector_count = int(self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        missing = int(
            self._connection.execute(
                f"""
                SELECT COUNT(*) FROM semantic_chunks AS c
                LEFT JOIN {table} AS v ON v.vector_id = c.vector_id
                WHERE v.vector_id IS NULL
                """
            ).fetchone()[0]
        )
        orphan = int(
            self._connection.execute(
                f"""
                SELECT COUNT(*) FROM {table} AS v
                LEFT JOIN semantic_chunks AS c ON c.vector_id = v.vector_id
                WHERE c.vector_id IS NULL
                """
            ).fetchone()[0]
        )
        return metadata_count, vector_count, missing, orphan

    def _create_vector_table(self, dimension: int) -> None:
        table = self._vector_table(dimension)
        try:
            self._connection.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {table}
                USING vec0(vector_id integer primary key, embedding float[{dimension}] distance_metric=cosine)
                """
            )
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(f"failed to create semantic vector table: {type(exc).__name__}") from exc

    def _drop_vector_tables(self) -> None:
        """按 vec0 主表删除向量表；主表删除时 sqlite-vec 会一并清理 shadow tables。"""

        rows = self._connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name LIKE 'semantic_vectors_%'
            """
        ).fetchall()
        for row in rows:
            name = str(row["name"])
            suffix = name.removeprefix("semantic_vectors_")
            # vec0 为每个主表生成 *_chunks、*_info 等 shadow tables；这里只删除
            # 由本类创建且 suffix 为 dimension 的主虚拟表，避免先删 shadow table。
            if suffix.isdigit():
                self._connection.execute(f"DROP TABLE {name}")

    @staticmethod
    def _vector_table(dimension: int) -> str:
        """dimension 已由 EmbeddingModelIdentity 校验为正整数，因此 identifier 可安全生成。"""

        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise ValueError("embedding dimension must be positive")
        return f"semantic_vectors_{dimension}"

    @staticmethod
    def _validate_vector(values: Sequence[float], dimension: int) -> tuple[float, ...]:
        """写入和查询共用 shape/finite 校验，避免 vec0 接收不可诊断数据。"""

        try:
            vector = tuple(float(item) for item in values)
        except (TypeError, ValueError) as exc:
            raise SemanticIndexStorageError("semantic vector contains a non-numeric value") from exc
        if len(vector) != dimension:
            raise SemanticIndexStorageError(
                f"semantic vector dimension mismatch: expected {dimension}, got {len(vector)}"
            )
        if any(not math.isfinite(item) for item in vector):
            raise SemanticIndexStorageError("semantic vector contains a non-finite value")
        return vector

    @staticmethod
    def _pack_vector(vector: Sequence[float]) -> bytes:
        """使用 sqlite-vec 要求的 little-endian float32 二进制表示，不生成 hash。"""

        return struct.pack(f"<{len(vector)}f", *vector)

    @staticmethod
    def _unpack_vector(value: object, dimension: int) -> tuple[float, ...]:
        """把 sqlite-vec 的 float32 blob 恢复为仅供完整性检查的数值。"""

        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise SemanticIndexStorageError("semantic vector sample is not a float32 blob")
        payload = bytes(value)
        expected_bytes = dimension * 4
        if len(payload) != expected_bytes:
            raise SemanticIndexStorageError(
                f"semantic vector sample size mismatch: expected {expected_bytes}, got {len(payload)}"
            )
        return tuple(struct.unpack(f"<{dimension}f", payload))


def _now_ms() -> int:
    """统一使用毫秒时间保存 derived state 更新时间。"""

    return int(time.time() * 1000)
