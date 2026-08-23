"""独立 sqlite-vec derived index 的 schema、状态和 dense candidate 读取。"""

from __future__ import annotations

import importlib
import json
import math
import sqlite3
import struct
import time
from collections.abc import Sequence
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
                    effective_chars INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS semantic_chunks_session_time
                    ON semantic_chunks(session_id, start_timestamp, end_timestamp);
                """
            )
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(f"failed to create semantic index schema: {type(exc).__name__}") from exc

    def start_rebuild(self, identity: SemanticIndexIdentity, canonical_message_count: int) -> None:
        """原子清空旧 vectors，写入新 identity，并进入 building。"""

        if canonical_message_count < 0:
            raise ValueError("canonical_message_count must be non-negative")
        try:
            with self._connection:
                self._drop_vector_tables()
                self._connection.execute("DELETE FROM semantic_chunks")
                self._connection.execute(
                    """
                    INSERT INTO semantic_index_state(
                        state_id, identity_json, status, canonical_message_count,
                        indexed_message_count, chunk_count, last_error, updated_at
                    ) VALUES (1, ?, 'building', ?, 0, 0, NULL, ?)
                    ON CONFLICT(state_id) DO UPDATE SET
                        identity_json = excluded.identity_json,
                        status = excluded.status,
                        canonical_message_count = excluded.canonical_message_count,
                        indexed_message_count = excluded.indexed_message_count,
                        chunk_count = excluded.chunk_count,
                        last_error = excluded.last_error,
                        updated_at = excluded.updated_at
                    """,
                    (identity.serialized, canonical_message_count, _now_ms()),
                )
        except sqlite3.Error as exc:
            raise SemanticIndexStorageError(f"failed to start semantic rebuild: {type(exc).__name__}") from exc

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
            with self._connection:
                self._create_vector_table(dimension)
                for chunk, vector_values in chunks:
                    vector = self._validate_vector(vector_values, dimension)
                    row = self._connection.execute(
                        """
                        INSERT INTO semantic_chunks(
                            chunk_id, parent_id, session_id, parent_start_message_id,
                            parent_end_message_id, start_message_id, end_message_id,
                            start_timestamp, end_timestamp, message_count, effective_chars
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def update_progress(self, indexed_message_count: int) -> None:
        """更新 canonical processed watermark，不把 chunk 数冒充 coverage。"""

        if indexed_message_count < 0:
            raise ValueError("indexed_message_count must be non-negative")
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    UPDATE semantic_index_state
                    SET indexed_message_count = ?, chunk_count = (
                        SELECT COUNT(*) FROM semantic_chunks
                    ), updated_at = ?
                    WHERE state_id = 1 AND status = 'building'
                    """,
                    (indexed_message_count, _now_ms()),
                )
                if cursor.rowcount != 1:
                    raise SemanticIndexStorageError("semantic rebuild state is not writable")
        except sqlite3.Error as exc:
            if isinstance(exc, SemanticIndexStorageError):
                raise
            raise SemanticIndexStorageError(f"failed to update semantic progress: {type(exc).__name__}") from exc

    def finish(self, status: SemanticIndexStatus, error: str | None = None) -> None:
        """写入显式终态；failed 也保留错误信息，不伪装成 completed。"""

        if status == "building":
            raise ValueError("finish status must be a terminal status")
        try:
            with self._connection:
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
                   chunk_count, last_error, updated_at
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
            )
        except Exception as exc:
            if isinstance(exc, SemanticIndexStorageError):
                raise
            raise SemanticIndexStorageError("semantic index state metadata is invalid") from exc

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
            metadata_count = int(
                self._connection.execute("SELECT COUNT(*) FROM semantic_chunks").fetchone()[0]
            )
            parent_count = int(
                self._connection.execute(
                    "SELECT COUNT(DISTINCT parent_id) FROM semantic_chunks"
                ).fetchone()[0]
            )
            vector_count = int(self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            missing_vector_count = int(
                self._connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM semantic_chunks AS c
                    LEFT JOIN {table} AS v ON v.vector_id = c.vector_id
                    WHERE v.vector_id IS NULL
                    """
                ).fetchone()[0]
            )
            orphan_vector_count = int(
                self._connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table} AS v
                    LEFT JOIN semantic_chunks AS c ON c.vector_id = v.vector_id
                    WHERE c.vector_id IS NULL
                    """
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
        if session_ids is not None:
            if not session_ids:
                return ()
            placeholders = ", ".join("?" for _ in session_ids)
            clauses.append(f"c.session_id IN ({placeholders})")
            parameters.extend(session_ids)
        if start_timestamp is not None:
            clauses.append("c.end_timestamp >= ?")
            parameters.append(start_timestamp)
        if end_timestamp is not None:
            clauses.append("c.start_timestamp < ?")
            parameters.append(end_timestamp)
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
            raise SemanticIndexStorageError(f"semantic dense search failed: {type(exc).__name__}") from exc
        # sqlite-vec applies k before relational filters; return a deterministic bounded result to caller.
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
