"""隔离检验单字索引列：保持既有bigram短语，不以LIKE补查掩盖漏召回。"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
from pathlib import Path
from statistics import median
from time import perf_counter

from scripts.cjk_bigram_benchmark import ORDER, match_sql, write_new
from trivae.data.storage.sqlite_lexical_text import normalize_lexical_index_text
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository

HAN_CHARACTER = re.compile("[\u3400-\u9fff\uf900-\ufaff]")


def han_unigrams(text: str) -> str:
    """单独列存储逐字token，避免插入bigram序列而破坏连续中文短语。"""
    return " ".join(HAN_CHARACTER.findall(text))


def build(source: Path, output: Path, *, candidate: bool, separate: bool) -> dict:
    """两侧同schema/顺序；仅候选的单字列非空，不修改正式索引。"""
    connection = sqlite3.connect(output, uri=True)
    connection.execute("ATTACH DATABASE ? AS corpus", (f"{(source / 'documents.sqlite3').resolve().as_uri()}?mode=ro",))
    columns = "internal_message_id UNINDEXED, session_id UNINDEXED, source_message_id UNINDEXED, content_text"
    connection.execute(f"CREATE VIRTUAL TABLE messages_fts USING fts5({columns}"
                       + ("" if separate else ", han_chars") + ", tokenize='unicode61')")
    if separate:
        connection.execute(f"CREATE VIRTUAL TABLE messages_han_fts USING fts5({columns}, tokenize='unicode61')")
    connection.create_function("bigram_text", 1, normalize_lexical_index_text)
    connection.create_function("unigram_text", 1, han_unigrams if candidate else lambda _: "")
    started = perf_counter()
    # 普通消息与转发正文复用已冻结的同一投影，不重新解释来源或preview。
    connection.execute("INSERT INTO messages_fts SELECT internal_message_id, session_id, NULL, "
                       "bigram_text(content_text)" + ("" if separate else ", unigram_text(content_text)")
                       + " FROM corpus.documents")
    if separate and candidate:
        # 独立索引只服务单汉字查询，原bigram索引的文档长度与BM25完全不变。
        connection.execute("INSERT INTO messages_han_fts SELECT internal_message_id, session_id, NULL, "
                           "unigram_text(content_text) FROM corpus.documents")
    connection.commit()
    elapsed = (perf_counter() - started) * 1000
    count = connection.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    connection.close()
    return {"insert_commit_ms": elapsed, "bytes": output.stat().st_size, "documents": count}


def open_index(path: Path, source: Path) -> sqlite3.Connection:
    """生产Scope SQL经只读Canonical视图执行，不绕过session或转发过滤。"""
    connection = sqlite3.connect(path, uri=True)
    connection.row_factory = sqlite3.Row
    uri = f"{(source / 'snapshot.sqlite3').resolve().as_uri()}?mode=ro"
    connection.execute("ATTACH DATABASE ? AS canonical", (uri,))
    for table in ("messages", "forwarded_messages"):
        connection.execute(f"CREATE TEMP VIEW {table} AS SELECT * FROM canonical.{table}")
    return connection


def run(source: Path, output: Path, *, separate: bool = False) -> None:
    """先冻结原64题及原文Oracle；保存全部排名、覆盖与交替耗时。"""
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((source / "oracle-v2/frozen.json").read_text())
    write_new(output / "protocol.json", {"source": str(source), "cases": frozen["cases"],
        "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_code": Path(__file__).read_text(), "model_requests": 0, "repeats": 3,
        "separate_index": separate,
        "candidate": "isolated Han unigram column/table; original bigram MATCH preserved",
        "unchanged": "bigram normalization, MATCH, scope SQL, BM25, stable tie-break, top10"})
    builds = {arm: build(source, output / f"{arm}.sqlite3", candidate=arm == "candidate", separate=separate)
              for arm in ("baseline", "candidate")}
    connections = {arm: open_index(output / f"{arm}.sqlite3", source) for arm in builds}
    old = {row["case_id"]: row["B"] for row in json.loads((source / "oracle-v2/results.json").read_text())["rows"]}
    repository = object.__new__(SQLiteCanonicalReadRepository)
    rows = []
    try:
        for index, case in enumerate(frozen["cases"]):
            reference = set(case["reference_ids"])
            sql, parameters = match_sql(repository, case, "B", scored=True)
            # 实验baseline固定原bigram主索引；当前生产已支持单字主索引，不能混入对照。
            sql = sql.replace("messages_han_fts", "messages_fts")
            row = {key: case[key] for key in ("case_id", "term", "category")}
            row["reference_count"] = len(reference)
            def arm_sql(arm: str) -> str:
                # 只按查询形态选择其主索引，不在零命中后补查另一种匹配语义。
                if separate and arm == "candidate" and HAN_CHARACTER.fullmatch(case["term"]):
                    return sql.replace("messages_fts", "messages_han_fts")
                return sql

            for arm, connection in connections.items():
                # 全深度覆盖与前十相关性分开记录，不把命中扩容当作排序提升。
                ids = [hit["internal_message_id"] for hit in connection.execute(f"{arm_sql(arm)} ORDER BY {ORDER}", parameters)]
                row[arm] = {"total": len(ids), "all_ids": ids, "top10": ids[:10],
                            "full_tp": len(set(ids) & reference), "top_tp": len(set(ids[:10]) & reference),
                            "latency_ms": []}
            assert row["baseline"]["total"] == old[case["case_id"]]["total"], "baseline total drift"
            assert row["baseline"]["top10"] == old[case["case_id"]]["top10"], "baseline rank drift"
            if separate and not HAN_CHARACTER.fullmatch(case["term"]):
                assert row["candidate"]["all_ids"] == row["baseline"]["all_ids"], "non-single ranking drift"
            for repeat in range(3):
                order = ("baseline", "candidate") if (index + repeat) % 2 == 0 else ("candidate", "baseline")
                for arm in order:
                    started = perf_counter()
                    connections[arm].execute(f"SELECT COUNT(*) FROM ({arm_sql(arm)})", parameters).fetchone()
                    connections[arm].execute(f"{arm_sql(arm)} ORDER BY {ORDER} LIMIT 10", parameters).fetchall()
                    row[arm]["latency_ms"].append((perf_counter() - started) * 1000)
            rows.append(row)
            print(case["case_id"], case["term"], row["baseline"]["full_tp"], row["candidate"]["full_tp"], flush=True)
    finally:
        for connection in connections.values():
            connection.close()
    summary = {arm: {"full_tp": sum(row[arm]["full_tp"] for row in rows),
                     "top_tp": sum(row[arm]["top_tp"] for row in rows),
                     "latency_median_ms": median(value for row in rows for value in row[arm]["latency_ms"])}
               for arm in builds}
    write_new(output / "results.json", {"builds": builds, "rows": rows, "summary": summary,
        "top10_changed": [row["case_id"] for row in rows if row["baseline"]["top10"] != row["candidate"]["top10"]]})
    print({"builds": builds, "summary": summary}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/evaluation/cjk-bigram-v1"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--separate-index", action="store_true")
    args = parser.parse_args()
    run(args.source, args.output, separate=args.separate_index)
