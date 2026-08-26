"""对本地 SQLite archive 重放 Agent/https lexical projection budget。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from benchmark import _configurations, _measure_projection
from trivae.capabilities.contracts import ExecutionScope, ToolEnvelope
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import build_tool_result_record
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import LexicalQuery


def main() -> None:
    """只输出 bounded retrieval/record/projection facts，不输出 archive 正文。"""

    database_path = Path("data/trivae.sqlite3")
    repository = SQLiteCanonicalReadRepository(database_path)
    retrieval = LexicalRetrieval(repository)
    try:
        for label in ("Agent", "https"):
            for count in (100, 300, 1_000):
                query = LexicalQuery(keyword=label, limit=count, context_before=0, context_after=0)
                retrieval_started = time.perf_counter()
                result = retrieval.search(query)
                retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
                envelope = ToolEnvelope("ok", result, {}, None)
                record_started = time.perf_counter()
                record = build_tool_result_record(
                    run_id="archive-benchmark-run",
                    tool_call_id="archive-benchmark-run/tool-call/1",
                    tool_result_id="archive-benchmark-run/tool-call/1/result",
                    tool_name="lexical_search",
                    envelope=envelope,
                    scope=ExecutionScope(max_results=count),
                )
                record_ms = (time.perf_counter() - record_started) * 1000
                for variant, config in _configurations():
                    facts, projection_ms, peak_allocated_kib = _measure_projection(
                        envelope,
                        record,
                        config,
                    )
                    print(
                        json.dumps(
                            {
                                "benchmark": "1m_dynamic_archive_projection",
                                "database": str(database_path),
                                "query": label,
                                "requested_hits": count,
                                "total_hits": result.total_hits,
                                "returned_messages": result.returned_messages,
                                "canonical_message_count": len(record.message_items),
                                "retrieval_partial": result.partial,
                                "retrieval_truncated": result.truncated,
                                "variant": variant,
                                "retrieval_ms": round(retrieval_ms, 3),
                                "record_build_ms": round(record_ms, 3),
                                "projection_ms_median": projection_ms,
                                "projection_peak_allocated_kib_median": peak_allocated_kib,
                                **facts,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
    finally:
        # archive read connection 由脚本显式关闭，避免实验结果混入 harness lifecycle failure。
        repository.close()


if __name__ == "__main__":
    main()
