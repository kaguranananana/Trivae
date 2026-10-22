"""实际生产重建与64题parity：独立克隆旧快照，不写入历史实验或在线数据库。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path

from scripts.cjk_bigram_benchmark import write_new
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.structured import LexicalQuery


def index_bytes(path: Path) -> dict[str, int]:
    """统计实际FTS页，排除Canonical正文、free pages与其他索引。"""
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
        return {name: connection.execute("SELECT COALESCE(SUM(pgsize),0) FROM dbstat WHERE name GLOB ?",
                                        (f"{name}_*",)).fetchone()[0]
                for name in ("messages_fts", "messages_han_fts")}


def validate(source: Path, experiment: Path, output: Path) -> None:
    """原题/原Oracle不变，生产count/top10必须等于已登记的隔离候选。"""
    output.mkdir(parents=True, exist_ok=False)
    path = output / "trivae.sqlite3"
    subprocess.run(["cp", "-c", str(source / "snapshot.sqlite3"), str(path)], check=True)
    frozen = json.loads((source / "oracle-v2/frozen.json").read_text())
    expected = {row["case_id"]: row for row in json.loads((experiment / "results.json").read_text())["rows"]}
    # 迭代期源码尚未提交时也保存实际文件全文，不能把HEAD冒充唯一执行实现。
    names = ("sqlite_lexical.py", "sqlite_lexical_text.py", "sqlite_read.py")
    write_new(output / "protocol.json", {"model_requests": 0, "cases": frozen["cases"],
        "source": str(source), "candidate_experiment": str(experiment),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_code": {name: (Path("src/trivae/data/storage") / name).read_text() for name in names}})
    before = index_bytes(path)
    index = SQLiteLexicalIndex(path)
    try:
        stats = index.rebuild()
    finally:
        index.close()
    after = index_bytes(path)
    repository = SQLiteCanonicalReadRepository(path)
    rows = []
    try:
        for case in frozen["cases"]:
            query = LexicalQuery(keyword=case["term"], limit=10,
                session_ids=None if case.get("sessions") is None else tuple(case["sessions"]))
            total = repository.count_lexical_hits(query)
            ids = [hit.message.internal_message_id for hit in repository.read_lexical_hits(query)]
            reference = expected[case["case_id"]]
            assert total == reference["candidate"]["total"], f"count mismatch: {case['case_id']}"
            assert ids == reference["candidate"]["top10"], f"ranking mismatch: {case['case_id']}"
            rows.append({"case_id": case["case_id"], "category": case["category"], "total": total,
                         "top10": ids, "candidate_parity": True})
    finally:
        repository.close()
    result = {"model_requests": 0, "stats": asdict(stats), "before_index_bytes": before,
              "after_index_bytes": after, "cases": rows, "all_64_candidate_parity": len(rows) == 64}
    write_new(output / "result.json", result)
    print({key: value for key, value in result.items() if key != "cases"}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/evaluation/cjk-bigram-v1"))
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate(args.source, args.experiment, args.output)
