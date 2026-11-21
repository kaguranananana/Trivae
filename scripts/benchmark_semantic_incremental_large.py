#!/usr/bin/env python3
"""在大规模真实冻结快照上对照语义索引局部增量更新与全量重建吞吐。"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from contextlib import closing
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path
from time import perf_counter

from trivae.bootstrap.application import create_application
from trivae.evaluation.workspace import EvaluationWorkspace
from trivae.retrieval.semantic.builder import _LONG_INPUT_ISOLATION_CHARS
from trivae.retrieval.semantic.chunking import (
    DEFAULT_SEMANTIC_CHUNK_CONFIG,
    SEMANTIC_CHUNKER_VERSION,
    SemanticChunker,
    is_semantic_void,
)
from trivae.retrieval.semantic.contracts import (
    EmbeddingModelIdentity,
    SemanticChunk,
    SemanticMessage,
    SemanticQuery,
)
from trivae.retrieval.semantic.embedding import SentenceTransformerEmbeddingProvider
from trivae.retrieval.semantic.index import SQLiteSemanticIndex
from trivae.retrieval.semantic.retrieval import SemanticRetrieval
from trivae.retrieval.structured import MessageQuery

_T_CRITICAL_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    24: 2.064, 30: 2.042, 31: 2.040,
}


class CountingRealProvider:
    """包装正式 SentenceTransformerEmbeddingProvider，只计数与透传，不改模型行为。"""

    def __init__(self, delegate: SentenceTransformerEmbeddingProvider | None = None) -> None:
        self.delegate = delegate or SentenceTransformerEmbeddingProvider()
        self.reset_counters()

    @property
    def identity(self) -> EmbeddingModelIdentity:
        return self.delegate.identity

    @property
    def document_batch_size(self) -> int:
        return self.delegate.document_batch_size

    def reset_counters(self) -> None:
        self.preloads = 0
        self.document_calls = 0
        self.documents = 0
        self.embedded_inputs: list[str] = []

    def preload(self) -> None:
        self.preloads += 1
        self.delegate.preload()

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.document_calls += 1
        self.documents += len(texts)
        self.embedded_inputs.extend(texts)
        return self.delegate.embed_documents(texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self.delegate.embed_query(text)


def _sysctl(key: str) -> str | None:
    try:
        out = subprocess.check_output(["sysctl", "-n", key], text=True, stderr=subprocess.DEVNULL)
        return out.strip()
    except Exception:
        return None


def _environment_info(provider: SentenceTransformerEmbeddingProvider) -> dict[str, object]:
    import sentence_transformers
    import sqlite_vec
    import torch

    mem_bytes_str = _sysctl("hw.memsize")
    mem_gib = round(int(mem_bytes_str) / (1024**3), 2) if mem_bytes_str and mem_bytes_str.isdigit() else None
    model = provider._model
    device = str(getattr(model, "device", None)) if model is not None else None
    dtype = str(next(model.parameters()).dtype) if model is not None else None
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_brand": _sysctl("machdep.cpu.brand_string"),
        "memory_gib": mem_gib,
        "python": platform.python_version(),
        "torch": getattr(torch, "__version__", None),
        "mps_available": bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()),
        "sentence_transformers": getattr(sentence_transformers, "__version__", None),
        "sqlite_vec": getattr(sqlite_vec, "__version__", None),
        "model_device": device,
        "model_dtype": dtype,
    }


def _stage_batch_files(raw_dir: Path, batch_glob: str, target_dir: Path) -> list[dict[str, object]]:
    """通过软链接把选定真实导出文件隔离到临时目录，不触碰原 raw 目录。"""

    files = sorted(raw_dir.glob(batch_glob))
    if not files:
        raise FileNotFoundError(f"no raw files matched {batch_glob!r} in {raw_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    staged: list[dict[str, object]] = []
    for index, source in enumerate(files):
        raw_payload = json.loads(source.read_text(encoding="utf-8"))
        msg_count = len(raw_payload.get("messages", [])) if isinstance(raw_payload, dict) else 0
        link = target_dir / source.name
        link.symlink_to(source.resolve())
        staged.append({
            "index": index,
            "file_size_bytes": source.stat().st_size,
            "raw_message_count": msg_count,
        })
    return staged


def _percentile(sorted_values: Sequence[int], pct: float) -> float:
    if not sorted_values:
        return 0.0
    pos = (len(sorted_values) - 1) * pct
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(sorted_values[low])
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


def _length_distribution(chunks: Sequence[SemanticChunk]) -> dict[str, object]:
    lengths = sorted(len(chunk.embedding_input) for chunk in chunks)
    isolated = sum(1 for length in lengths if length > _LONG_INPUT_ISOLATION_CHARS)
    return {
        "count": len(lengths),
        "min_chars": lengths[0] if lengths else 0,
        "mean_chars": round(sum(lengths) / len(lengths), 2) if lengths else 0.0,
        "p50_chars": round(_percentile(lengths, 0.50), 2),
        "p90_chars": round(_percentile(lengths, 0.90), 2),
        "p99_chars": round(_percentile(lengths, 0.99), 2),
        "max_chars": lengths[-1] if lengths else 0,
        "long_input_isolated_count": isolated,
        "long_input_isolated_ratio": round(isolated / len(lengths), 6) if lengths else 0.0,
    }


def _collect_full_corpus_chunks(
    repository,
    chunker: SemanticChunker,
    *,
    read_batch_size: int = 256,
) -> tuple[list[SemanticChunk], dict[str, object]]:
    """按正式 SemanticIndexBuilder.rebuild 同一顺序全量流式分块并统计真实扫描分块耗时。"""

    started = perf_counter()
    canonical_count = repository.count_messages(MessageQuery(limit=1))
    forwarded_count = repository.count_forwarded_messages()
    chunks: list[SemanticChunk] = []
    parent: list[SemanticMessage] = []
    parent_count = 0
    skipped_void_chunks = 0
    eligible = void = eligible_forwarded = void_forwarded = 0

    projections = chain(
        repository.iter_semantic_messages(read_batch_size),
        repository.iter_forwarded_messages(read_batch_size),
    )
    for projection in projections:
        message = SemanticMessage.from_projection(projection)
        void_flag = is_semantic_void(message)
        if message.forward is None:
            eligible += int(not void_flag)
            void += int(void_flag)
        else:
            eligible_forwarded += int(not void_flag)
            void_forwarded += int(void_flag)
        if parent and chunker.starts_new_parent(parent[-1], message, parent):
            result = chunker.chunk_parent(parent)
            parent_count += 1
            skipped_void_chunks += result.skipped_void_chunks
            chunks.extend(result.chunks)
            parent = []
        parent.append(message)
    if parent:
        result = chunker.chunk_parent(parent)
        parent_count += 1
        skipped_void_chunks += result.skipped_void_chunks
        chunks.extend(result.chunks)

    elapsed_ms = (perf_counter() - started) * 1000
    stats = {
        "canonical_message_count": canonical_count,
        "forwarded_message_count": forwarded_count,
        "total_message_count": canonical_count + forwarded_count,
        "eligible_message_count": eligible,
        "semantic_void_message_count": void,
        "eligible_forwarded_message_count": eligible_forwarded,
        "semantic_void_forwarded_message_count": void_forwarded,
        "parent_count": parent_count,
        "chunk_count": len(chunks),
        "skipped_void_chunks": skipped_void_chunks,
        "scan_and_chunk_elapsed_ms": round(elapsed_ms, 2),
        "length_distribution": _length_distribution(chunks),
    }
    return chunks, stats


def _verify_full_chunk_parity(
    store: SQLiteSemanticIndex,
    expected_chunks: Sequence[SemanticChunk],
) -> dict[str, object]:
    """逐行比对增量发布后的全部 semantic_chunks 元数据与 embedding_input。"""

    started = perf_counter()
    expected_map = {
        chunk.chunk_id: (
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
        )
        for chunk in expected_chunks
    }
    actual_count = 0
    missing_in_expected = 0
    field_mismatches = 0
    seen_ids: set[str] = set()
    query = """
        SELECT chunk_id, parent_id, session_id, parent_start_message_id, parent_end_message_id,
               start_message_id, end_message_id, start_timestamp, end_timestamp,
               message_count, effective_chars, embedding_input
        FROM semantic_chunks
    """
    for row in store._connection.execute(query):
        actual_count += 1
        chunk_id = str(row["chunk_id"])
        seen_ids.add(chunk_id)
        expected_tuple = expected_map.get(chunk_id)
        if expected_tuple is None:
            missing_in_expected += 1
            continue
        actual_tuple = (
            row["parent_id"],
            row["session_id"],
            row["parent_start_message_id"],
            row["parent_end_message_id"],
            row["start_message_id"],
            row["end_message_id"],
            row["start_timestamp"],
            row["end_timestamp"],
            row["message_count"],
            row["effective_chars"],
            row["embedding_input"],
        )
        if actual_tuple != expected_tuple:
            field_mismatches += 1
    missing_in_actual = len(expected_map) - len(seen_ids & expected_map.keys())
    elapsed_ms = (perf_counter() - started) * 1000
    all_equal = (
        actual_count == len(expected_map)
        and missing_in_expected == 0
        and missing_in_actual == 0
        and field_mismatches == 0
    )
    return {
        "expected_chunk_count": len(expected_map),
        "actual_chunk_count": actual_count,
        "missing_in_expected": missing_in_expected,
        "missing_in_actual": missing_in_actual,
        "field_mismatches": field_mismatches,
        "all_chunks_exact_match": all_equal,
        "verify_elapsed_ms": round(elapsed_ms, 2),
    }


def _verify_new_vectors_parity(
    store: SQLiteSemanticIndex,
    provider: SentenceTransformerEmbeddingProvider,
    embedded_inputs: Sequence[str],
) -> dict[str, object]:
    """对增量新计算的全部向量独立重算并比对 float32 绝对误差。"""

    if not embedded_inputs:
        return {"checked_vectors": 0, "max_abs_delta": 0.0, "within_tolerance": True}
    state = store.state()
    assert state is not None
    dimension = state.identity.embedding.dimension
    table = f"semantic_vectors_{dimension}"
    unique_inputs = list(dict.fromkeys(embedded_inputs))
    stored_vectors: list[tuple[float, ...]] = []
    valid_inputs: list[str] = []
    for text in unique_inputs:
        row = store._connection.execute(
            f"SELECT v.embedding FROM semantic_chunks c JOIN {table} v USING(vector_id) "
            "WHERE c.embedding_input = ? LIMIT 1",
            (text,),
        ).fetchone()
        if row is not None:
            valid_inputs.append(text)
            stored_vectors.append(store._unpack_vector(row[0], dimension))

    batch_size = provider.document_batch_size
    recomputed: list[tuple[float, ...]] = []
    pending = list(valid_inputs)
    while pending:
        long_offset = next(
            (idx for idx, text in enumerate(pending) if len(text) > _LONG_INPUT_ISOLATION_CHARS),
            None,
        )
        if long_offset == 0:
            take = 1
        elif long_offset is not None:
            take = min(batch_size, long_offset)
        else:
            take = min(batch_size, len(pending))
        recomputed.extend(provider.embed_documents(tuple(pending[:take])))
        del pending[:take]

    max_delta = 0.0
    for left, right in zip(stored_vectors, recomputed, strict=True):
        delta = max(abs(a - b) for a, b in zip(left, right, strict=True))
        if delta > max_delta:
            max_delta = delta
    return {
        "checked_vectors": len(valid_inputs),
        "max_abs_delta": max_delta,
        "tolerance": 1e-4,
        "within_tolerance": max_delta <= 1e-4,
    }


def _benchmark_stratified_full_rebuild(
    all_chunks: Sequence[SemanticChunk],
    provider: SentenceTransformerEmbeddingProvider,
    identity,
    *,
    canonical_count: int,
    forwarded_count: int,
    canonical_revision: int,
    sample_windows: int,
    window_size: int,
) -> dict[str, object]:
    """在全库流式分块上做系统分层连续窗口采样，经真实模型编码与 sqlite-vec 写入测全量重建吞吐。"""

    total = len(all_chunks)
    if sample_windows <= 0 or window_size <= 0 or total < sample_windows * window_size:
        raise ValueError("invalid stratified sample parameters for corpus size")
    stride = (total - window_size) / max(1, sample_windows - 1) if sample_windows > 1 else 0.0
    window_starts = [round(i * stride) for i in range(sample_windows)]
    sampled_chunks: list[SemanticChunk] = []
    for start in window_starts:
        sampled_chunks.extend(all_chunks[start : start + window_size])

    batch_size = provider.document_batch_size
    window_results: list[dict[str, object]] = []
    total_embed_ms = 0.0
    total_write_ms = 0.0
    total_batches = 0
    total_isolated_batches = 0

    with tempfile.TemporaryDirectory(prefix="trivae-stratified-full-") as tmpdir:
        clean_db = Path(tmpdir) / "stratified_full.semantic.sqlite3"
        with closing(SQLiteSemanticIndex(clean_db)) as store:
            store.start_rebuild(
                identity,
                canonical_count,
                canonical_revision=canonical_revision,
                forwarded_message_count=forwarded_count,
            )
            for win_idx, start in enumerate(window_starts):
                window_chunks = list(all_chunks[start : start + window_size])
                win_embed_ms = 0.0
                win_write_ms = 0.0
                win_batches = 0
                win_isolated = 0
                win_started = perf_counter()
                pending = list(window_chunks)
                while pending:
                    long_offset = next(
                        (
                            idx
                            for idx, chunk in enumerate(pending)
                            if len(chunk.embedding_input) > _LONG_INPUT_ISOLATION_CHARS
                        ),
                        None,
                    )
                    if long_offset == 0:
                        take = 1
                        win_isolated += 1
                    elif long_offset is not None:
                        take = min(batch_size, long_offset)
                    else:
                        take = min(batch_size, len(pending))
                    batch = tuple(pending[:take])
                    t0 = perf_counter()
                    vectors = provider.embed_documents(tuple(chunk.embedding_input for chunk in batch))
                    t1 = perf_counter()
                    store.insert_chunks(tuple(zip(batch, vectors, strict=True)))
                    t2 = perf_counter()
                    win_embed_ms += (t1 - t0) * 1000
                    win_write_ms += (t2 - t1) * 1000
                    win_batches += 1
                    del pending[:take]
                win_total_ms = (perf_counter() - win_started) * 1000
                total_embed_ms += win_embed_ms
                total_write_ms += win_write_ms
                total_batches += win_batches
                total_isolated_batches += win_isolated
                cps = len(window_chunks) / (win_total_ms / 1000)
                window_results.append({
                    "window_index": win_idx,
                    "corpus_chunk_offset": start,
                    "chunk_count": len(window_chunks),
                    "batch_count": win_batches,
                    "isolated_long_batches": win_isolated,
                    "mean_chars": round(sum(len(c.embedding_input) for c in window_chunks) / len(window_chunks), 2),
                    "embedding_elapsed_ms": round(win_embed_ms, 2),
                    "index_write_elapsed_ms": round(win_write_ms, 2),
                    "total_elapsed_ms": round(win_total_ms, 2),
                    "chunks_per_second": round(cps, 4),
                })
                print(
                    f"[stratified {win_idx + 1:02d}/{sample_windows}] "
                    f"offset={start:6d} chunks={len(window_chunks)} "
                    f"time={win_total_ms / 1000:.2f}s ({cps:.2f} chunks/s)",
                    flush=True,
                )
            store.finish("partial")

    sampled_count = len(sampled_chunks)
    total_embed_write_ms = total_embed_ms + total_write_ms
    overall_cps = sampled_count / (total_embed_write_ms / 1000)
    per_chunk_ms_values = [float(item["total_elapsed_ms"]) / int(item["chunk_count"]) for item in window_results]
    mean_ms_per_chunk = statistics.mean(per_chunk_ms_values)
    stdev_ms_per_chunk = statistics.stdev(per_chunk_ms_values) if len(per_chunk_ms_values) > 1 else 0.0
    se_ms_per_chunk = stdev_ms_per_chunk / math.sqrt(len(per_chunk_ms_values))
    t_crit = _T_CRITICAL_95.get(len(per_chunk_ms_values) - 1, 2.0)
    ci95_low_ms_per_chunk = max(0.0, mean_ms_per_chunk - t_crit * se_ms_per_chunk)
    ci95_high_ms_per_chunk = mean_ms_per_chunk + t_crit * se_ms_per_chunk

    return {
        "method": "systematic_stratified_contiguous_windows",
        "sample_windows": sample_windows,
        "window_size": window_size,
        "sampled_chunk_count": sampled_count,
        "corpus_chunk_count": total,
        "sample_fraction": round(sampled_count / total, 6),
        "sample_length_distribution": _length_distribution(sampled_chunks),
        "embedding_batch_size": batch_size,
        "total_batches": total_batches,
        "isolated_long_batches": total_isolated_batches,
        "embedding_elapsed_ms": round(total_embed_ms, 2),
        "index_write_elapsed_ms": round(total_write_ms, 2),
        "embed_plus_write_elapsed_ms": round(total_embed_write_ms, 2),
        "overall_chunks_per_second": round(overall_cps, 4),
        "ms_per_chunk_mean": round(mean_ms_per_chunk, 3),
        "ms_per_chunk_stdev": round(stdev_ms_per_chunk, 3),
        "ms_per_chunk_ci95": [round(ci95_low_ms_per_chunk, 3), round(ci95_high_ms_per_chunk, 3)],
        "estimated_full_embed_write_seconds": round((total * mean_ms_per_chunk) / 1000, 2),
        "estimated_full_embed_write_ci95_seconds": [
            round((total * ci95_low_ms_per_chunk) / 1000, 2),
            round((total * ci95_high_ms_per_chunk) / 1000, 2),
        ],
        "windows": window_results,
    }


def _read_historical_auto_import_full_rebuilds(live_db: Path) -> list[dict[str, object]]:
    """只读读取本机既有库中历史全量重建记录作为独立旁证（不修改任何生产库）。"""

    if not live_db.exists():
        return []
    conn = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT run_id, started_at, finished_at, status, summary_json "
            "FROM auto_import_runs WHERE started_at < '2026-10-19' AND status = 'completed' ORDER BY rowid ASC"
        ).fetchall()
        records: list[dict[str, object]] = []
        for run_id, started_at, finished_at, status, summary_json in rows:
            dt = (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds()
            if dt < 3600:
                continue
            payload = json.loads(summary_json)
            totals = payload.get("import", {}).get("totals", {})
            cum = conn.execute(
                "SELECT SUM(inserted_count) FROM import_batches WHERE started_at <= ?",
                (finished_at,),
            ).fetchone()[0]
            records.append({
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "wall_seconds": round(dt, 2),
                "wall_hours": round(dt / 3600, 2),
                "inserted_in_run": totals.get("inserted_count"),
                "cumulative_canonical_messages_at_finish": int(cum or 0),
                "caveat": "production auto_import_runs wall-clock includes import, FTS rebuild, and any host sleep/load",
            })
        return records
    finally:
        conn.close()


def _run_incremental_scenario(
    *,
    freeze_manifest: Path,
    raw_dir: Path,
    batch_glob: str,
    provider: CountingRealProvider,
    mode_label: str,
    run_full_verification: bool,
    sample_windows: int,
    window_size: int,
    output_dir: Path,
) -> dict[str, object]:
    """在独立 APFS 克隆工作库上运行真实日常导入与增量语义更新。"""

    with EvaluationWorkspace.create(freeze_manifest) as workspace:
        staged_dir = workspace.directory / "staged_raw"
        staged_files = _stage_batch_files(raw_dir, batch_glob, staged_dir)
        provider.reset_counters()
        with create_application(
            workspace.database_path,
            semantic_index_path=workspace.semantic_index_path,
            semantic_provider=provider,
        ) as app:
            builder = app._semantic_builder
            assert builder is not None
            initial_state = builder.store.state()
            assert initial_state is not None
            base_revision = initial_state.canonical_revision
            before_snapshot = {
                "canonical_message_count": initial_state.canonical_message_count,
                "forwarded_message_count": initial_state.forwarded_message_count,
                "chunk_count": initial_state.chunk_count,
                "canonical_revision": initial_state.canonical_revision,
                "supports_incremental": builder.store.supports_incremental(),
            }

            import_started = perf_counter()
            import_summary = app.import_directory(staged_dir)
            import_elapsed_ms = (perf_counter() - import_started) * 1000
            import_dict = import_summary.to_dict()
            totals = import_dict["totals"]

            ranges = app.read_repository.semantic_change_ranges(
                base_revision, builder.chunker.config.parent_gap_seconds
            )
            affected_sessions = len({session_id for session_id, _, _ in ranges})

            print(
                f"[{mode_label}] imported files={totals['files']} received={totals['received_count']} "
                f"inserted={totals['inserted_count']} dup={totals['duplicate_count']} "
                f"conflict={totals['conflict_count']} ranges={len(ranges)} sessions={affected_sessions}",
                flush=True,
            )

            incremental_stats = builder.update()
            inc_dict = incremental_stats.to_dict()
            embedded_inputs_snapshot = list(provider.embedded_inputs)
            provider_counters = {
                "preloads": provider.preloads,
                "document_calls": provider.document_calls,
                "documents_embedded": provider.documents,
            }

            print(
                f"[{mode_label}] incremental done: mode={incremental_stats.build_mode} "
                f"chunks={incremental_stats.chunk_count} embedded={incremental_stats.embedding_count} "
                f"reused={incremental_stats.reused_chunk_count} "
                f"total={incremental_stats.elapsed_ms / 1000:.2f}s "
                f"(load={incremental_stats.model_load_elapsed_ms / 1000:.2f}s, "
                f"embed={incremental_stats.embedding_elapsed_ms / 1000:.2f}s, "
                f"write={incremental_stats.index_write_elapsed_ms / 1000:.2f}s)",
                flush=True,
            )

            # 空更新验证：二次调用必须 0 模型调用、0 preload。
            before_idle = (provider.documents, provider.preloads)
            idle_stats = builder.update()
            after_idle = (provider.documents, provider.preloads)
            assert before_idle == after_idle
            assert idle_stats.build_mode == "unchanged"
            assert idle_stats.embedding_count == 0

            integrity = builder.store.integrity_report(builder.identity)
            assert integrity.status == "valid", f"integrity failed: {integrity}"

            # 真实语义检索烟雾：不保存正文，只记录命中统计。
            retrieval_check: dict[str, object] = {"executed": False}
            if embedded_inputs_snapshot:
                retrieval_started = perf_counter()
                sample_query_text = embedded_inputs_snapshot[0][:240]
                retrieval = SemanticRetrieval(
                    app.read_repository,
                    builder.store,
                    provider,
                    database_identity=builder.database_identity,
                    chunker=builder.chunker,
                )
                search_result = retrieval.search(
                    SemanticQuery(query=sample_query_text, limit=5, dense_top_k=20)
                )
                retrieval_ms = (perf_counter() - retrieval_started) * 1000
                retrieval_check = {
                    "executed": True,
                    "hit_count": len(search_result.hits),
                    "total_hits": search_result.total_hits,
                    "expanded_message_count": len(search_result.expanded_messages),
                    "top_score": round(search_result.hits[0].score, 6) if search_result.hits else None,
                    "elapsed_ms": round(retrieval_ms, 2),
                }

            result: dict[str, object] = {
                "mode": mode_label,
                "storage": workspace.record_storage(),
                "before": before_snapshot,
                "staged_files_count": len(staged_files),
                "staged_raw_messages_total": sum(int(f["raw_message_count"]) for f in staged_files),
                "import": {
                    "totals": totals,
                    "elapsed_ms": round(import_elapsed_ms, 2),
                },
                "change_ranges": {
                    "range_count": len(ranges),
                    "affected_session_count": affected_sessions,
                },
                "incremental": inc_dict,
                "provider_counters": provider_counters,
                "reuse_rate": round(
                    incremental_stats.reused_chunk_count / incremental_stats.chunk_count, 6
                )
                if incremental_stats.chunk_count
                else 0.0,
                "idle_replay": {
                    "build_mode": idle_stats.build_mode,
                    "embedding_count": idle_stats.embedding_count,
                    "reused_chunk_count": idle_stats.reused_chunk_count,
                    "elapsed_ms": round(idle_stats.elapsed_ms, 4),
                    "provider_calls_delta": after_idle[0] - before_idle[0],
                    "preload_calls_delta": after_idle[1] - before_idle[1],
                },
                "integrity": integrity.to_dict(),
                "retrieval_smoke": retrieval_check,
            }

            if run_full_verification:
                print(f"[{mode_label}] scanning full corpus for exact chunk parity...", flush=True)
                chunker = SemanticChunker(DEFAULT_SEMANTIC_CHUNK_CONFIG, SEMANTIC_CHUNKER_VERSION)
                all_chunks, scan_stats = _collect_full_corpus_chunks(app.read_repository, chunker)
                parity = _verify_full_chunk_parity(builder.store, all_chunks)
                assert parity["all_chunks_exact_match"], f"full chunk parity mismatch: {parity}"
                print(
                    f"[{mode_label}] full chunk parity PASSED: "
                    f"{parity['actual_chunk_count']}/{parity['expected_chunk_count']} exact match "
                    f"(scan+chunk={scan_stats['scan_and_chunk_elapsed_ms'] / 1000:.2f}s)",
                    flush=True,
                )

                print(
                    f"[{mode_label}] verifying float32 vector parity on {len(embedded_inputs_snapshot)} new chunks...",
                    flush=True,
                )
                vec_parity = _verify_new_vectors_parity(builder.store, provider.delegate, embedded_inputs_snapshot)
                assert vec_parity["within_tolerance"], f"vector parity failed: {vec_parity}"
                print(
                    f"[{mode_label}] vector parity PASSED: checked={vec_parity['checked_vectors']} "
                    f"max_abs_delta={vec_parity['max_abs_delta']:.2e}",
                    flush=True,
                )

                print(
                    f"[{mode_label}] running stratified full-rebuild benchmark "
                    f"({sample_windows} windows x {window_size} chunks = {sample_windows * window_size})...",
                    flush=True,
                )
                stratified = _benchmark_stratified_full_rebuild(
                    all_chunks,
                    provider.delegate,
                    builder.identity,
                    canonical_count=int(scan_stats["canonical_message_count"]),
                    forwarded_count=int(scan_stats["forwarded_message_count"]),
                    canonical_revision=app.read_repository.canonical_revision(),
                    sample_windows=sample_windows,
                    window_size=window_size,
                )
                scan_s = float(scan_stats["scan_and_chunk_elapsed_ms"]) / 1000.0
                est_embed_write_s = float(stratified["estimated_full_embed_write_seconds"])
                ci_low_s, ci_high_s = stratified["estimated_full_embed_write_ci95_seconds"]
                warm_full_est_s = scan_s + est_embed_write_s
                warm_full_ci_s = [round(scan_s + float(ci_low_s), 2), round(scan_s + float(ci_high_s), 2)]
                result["full_corpus_scan_and_chunk"] = scan_stats
                result["full_chunk_parity"] = parity
                result["new_vectors_parity"] = vec_parity
                result["stratified_full_rebuild"] = {
                    **stratified,
                    "estimated_full_rebuild_warm_total_seconds": round(warm_full_est_s, 2),
                    "estimated_full_rebuild_warm_total_minutes": round(warm_full_est_s / 60, 2),
                    "estimated_full_rebuild_warm_total_hours": round(warm_full_est_s / 3600, 2),
                    "estimated_full_rebuild_warm_ci95_seconds": warm_full_ci_s,
                    "estimated_full_rebuild_warm_ci95_hours": [
                        round(warm_full_ci_s[0] / 3600, 2),
                        round(warm_full_ci_s[1] / 3600, 2),
                    ],
                }

        output_dir.mkdir(parents=True, exist_ok=True)
        partial_path = output_dir / f"{mode_label}.json"
        partial_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        workspace.mark_results_persisted()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--freeze-manifest",
        type=Path,
        default=Path("data/evaluation/frozen-20261028-validated/freeze.json"),
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--batch-glob", default="*_20261028_10*.json")
    parser.add_argument("--sample-windows", type=int, default=16)
    parser.add_argument("--window-size", type=int, default=64)
    parser.add_argument(
        "--live-db-for-history",
        type=Path,
        default=Path("data/trivae.sqlite3"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    started = perf_counter()
    # 1. 冷启动进程增量实测（新 provider 未预加载模型）。
    cold_provider = CountingRealProvider()
    cold_result = _run_incremental_scenario(
        freeze_manifest=args.freeze_manifest,
        raw_dir=args.raw_dir,
        batch_glob=args.batch_glob,
        provider=cold_provider,
        mode_label="cold_incremental",
        run_full_verification=False,
        sample_windows=args.sample_windows,
        window_size=args.window_size,
        output_dir=args.output_dir,
    )

    # 2. 暖模型增量实测 + 全库分块一致性核验 + 新向量误差核验 + 全库分层重建吞吐基准。
    # 复用已加载并预热过的真实模型，保证暖模型增量与分层全量重建处于同一热态。
    warm_provider = CountingRealProvider(delegate=cold_provider.delegate)
    env_info = _environment_info(warm_provider.delegate)
    warm_result = _run_incremental_scenario(
        freeze_manifest=args.freeze_manifest,
        raw_dir=args.raw_dir,
        batch_glob=args.batch_glob,
        provider=warm_provider,
        mode_label="warm_incremental_and_full_baseline",
        run_full_verification=True,
        sample_windows=args.sample_windows,
        window_size=args.window_size,
        output_dir=args.output_dir,
    )

    cold_inc = cold_result["incremental"]
    warm_inc = warm_result["incremental"]
    strat = warm_result["stratified_full_rebuild"]
    warm_inc_s = float(warm_inc["elapsed_ms"]) / 1000.0
    cold_inc_s = float(cold_inc["elapsed_ms"]) / 1000.0
    cold_load_s = float(cold_inc["model_load_elapsed_ms"]) / 1000.0
    warm_full_s = float(strat["estimated_full_rebuild_warm_total_seconds"])
    cold_full_s = warm_full_s + cold_load_s

    summary = {
        "schema": "trivae-semantic-incremental-large-benchmark-v1",
        "environment": env_info,
        "experiment_inputs": {
            "freeze_manifest": str(args.freeze_manifest),
            "batch_glob": args.batch_glob,
            "sample_windows": args.sample_windows,
            "window_size": args.window_size,
        },
        "headline": {
            "before_canonical_messages": warm_result["before"]["canonical_message_count"],
            "before_forwarded_messages": warm_result["before"]["forwarded_message_count"],
            "before_chunks": warm_result["before"]["chunk_count"],
            "inserted_messages": warm_result["import"]["totals"]["inserted_count"],
            "received_messages": warm_result["import"]["totals"]["received_count"],
            "duplicate_messages": warm_result["import"]["totals"]["duplicate_count"],
            "conflict_messages": warm_result["import"]["totals"]["conflict_count"],
            "after_canonical_messages": warm_inc["canonical_message_count"],
            "after_forwarded_messages": warm_inc["forwarded_message_count"],
            "after_total_messages": warm_inc["canonical_message_count"] + warm_inc["forwarded_message_count"],
            "after_chunks": warm_inc["chunk_count"],
            "affected_messages": warm_inc["affected_message_count"],
            "affected_chunks": warm_inc["affected_chunk_count"],
            "removed_chunks": warm_inc["removed_chunk_count"],
            "newly_embedded_chunks": warm_inc["embedding_count"],
            "reused_chunks": warm_inc["reused_chunk_count"],
            "vector_reuse_rate": warm_result["reuse_rate"],
            "vector_reuse_percent": round(float(warm_result["reuse_rate"]) * 100, 3),
            "embedding_compute_reduction_percent": round(
                (1.0 - warm_inc["embedding_count"] / warm_inc["chunk_count"]) * 100, 3
            ),
            "cold_model_load_seconds": round(cold_load_s, 2),
            "cold_incremental_total_seconds": round(cold_inc_s, 2),
            "warm_incremental_total_seconds": round(warm_inc_s, 2),
            "warm_incremental_embed_seconds": round(float(warm_inc["embedding_elapsed_ms"]) / 1000.0, 2),
            "warm_incremental_write_seconds": round(float(warm_inc["index_write_elapsed_ms"]) / 1000.0, 2),
            "warm_incremental_other_overhead_seconds": round(
                (
                    float(warm_inc["elapsed_ms"])
                    - float(warm_inc["model_load_elapsed_ms"])
                    - float(warm_inc["embedding_elapsed_ms"])
                    - float(warm_inc["index_write_elapsed_ms"])
                )
                / 1000.0,
                2,
            ),
            "idle_replay_ms": warm_result["idle_replay"]["elapsed_ms"],
            "full_scan_and_chunk_seconds": round(
                float(warm_result["full_corpus_scan_and_chunk"]["scan_and_chunk_elapsed_ms"]) / 1000.0, 2
            ),
            "stratified_chunks_per_second": strat["overall_chunks_per_second"],
            "estimated_full_rebuild_warm_seconds": round(warm_full_s, 2),
            "estimated_full_rebuild_warm_hours": round(warm_full_s / 3600.0, 2),
            "estimated_full_rebuild_warm_ci95_hours": strat["estimated_full_rebuild_warm_ci95_hours"],
            "estimated_full_rebuild_cold_seconds": round(cold_full_s, 2),
            "estimated_full_rebuild_cold_hours": round(cold_full_s / 3600.0, 2),
            "warm_speedup_factor": round(warm_full_s / warm_inc_s, 1),
            "cold_speedup_factor": round(cold_full_s / cold_inc_s, 1),
            "full_chunk_parity_exact": warm_result["full_chunk_parity"]["all_chunks_exact_match"],
            "new_vectors_max_abs_delta": warm_result["new_vectors_parity"]["max_abs_delta"],
        },
        "cold_incremental_run": cold_result,
        "warm_incremental_and_full_baseline_run": warm_result,
        "historical_production_full_rebuilds": _read_historical_auto_import_full_rebuilds(args.live_db_for_history),
        "total_benchmark_elapsed_seconds": round(perf_counter() - started, 2),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "benchmark_result.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n=== BENCHMARK HEADLINE ===")
    print(json.dumps(summary["headline"], ensure_ascii=False, indent=2))
    print(f"Saved full benchmark JSON to: {report_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
