"""冻结真实语料，并对隔离的 unicode61 / CJK v2 索引执行单变量实验。"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter

from trivae.data.ingestion.qq_forward import _own_content_text
from trivae.data.storage.sqlite_forward import FORWARD_CONTENT_PREDICATE
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_lexical_text import normalize_lexical_index_text
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation.benchmark.gt import CaseGroundTruth
from trivae.evaluation.benchmark.metrics import score_ranking
from trivae.evaluation.contracts import DatasetSnapshot, utc_now
from trivae.retrieval.structured import LexicalQuery

ROOT = Path('data/evaluation/cjk-bigram-v1')
CONFIG = Path('evaluation/experiments/cjk-bigram-v1/queries.json')
ORDER = 'lexical_score ASC, timestamp ASC, missing_seq ASC, order_seq ASC, internal_message_id ASC'


def write_new(path: Path, value: object) -> None:
    """只创建新产物，防止覆盖冻结输入和正式结果。"""
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def connect(path: Path) -> sqlite3.Connection:
    """连接实验库；所有正式 Canonical 读取都显式只读。"""
    connection = sqlite3.connect(path, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def prepare(root: Path, source: Path) -> None:
    """SQLite 一致性备份后重建生产投影，正文及身份只在本地落盘。"""
    root.mkdir(parents=True, exist_ok=False)
    # 只读连接从生产库取得一致快照，所有重建写入新文件。
    original = sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro', uri=True)
    snapshot = connect(root / 'snapshot.sqlite3')
    original.backup(snapshot)
    original.close()
    snapshot.close()
    index = SQLiteLexicalIndex(root / 'snapshot.sqlite3')
    stats = index.rebuild()
    index.close()
    snapshot = connect(root / 'snapshot.sqlite3')
    # 原文投影完全复用生产 forward-own-text 函数，不把 preview 纳入 Oracle。
    snapshot.create_function('own_text', 1, lambda value: _own_content_text(json.loads(value)))
    snapshot.execute('ATTACH DATABASE ? AS experiment', (str(root / 'documents.sqlite3'),))
    snapshot.execute(f'''CREATE TABLE experiment.documents AS
        SELECT m.internal_message_id, m.session_id, m.timestamp, m.seq,
            CASE WHEN {FORWARD_CONTENT_PREDICATE} THEN own_text(m.content_json)
                 ELSE m.content_text END AS content_text
        FROM messages AS m
        UNION ALL
        SELECT internal_message_id, session_id, timestamp, seq, content_text FROM forwarded_messages''')
    snapshot.commit()
    manifest = {
        'created_at': utc_now(), 'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'sqlite': sqlite3.sqlite_version, 'production_rebuild': asdict(stats),
        'snapshot': DatasetSnapshot.from_database(root / 'snapshot.sqlite3').to_dict(),
        'metadata': dict(snapshot.execute('SELECT key,value FROM trivae_derived_meta')),
        'scope': 'all 12 sessions; per-case scope frozen before execution',
        'oracle': 'SQLite instr(lower(text),lower(term)), full text including NUL, ASCII case insensitive; canonical own text + forwarded occurrences',
        'human_verified': False,
    }
    write_new(root / 'manifest.json', manifest)
    snapshot.close()
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


def discover(root: Path) -> None:
    """仅按原始正文发现混排词；不读取 A/B 结果或排名。"""
    connection = connect(root / 'documents.sqlite3')
    patterns = re.compile(r'[A-Za-z]{2,12}[\u4e00-\u9fff]{2,5}|[\u4e00-\u9fff]{2,5}[A-Za-z]{2,12}')
    counts: dict[str, int] = {}
    # 固定 ID 顺序扫描；统计真实出现频率，不用 Candidate 命中筛选题目。
    for row in connection.execute('SELECT content_text FROM documents ORDER BY internal_message_id'):
        for term in set(patterns.findall(row[0])):
            counts[term] = counts.get(term, 0) + 1
    print(json.dumps(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:100], ensure_ascii=False))
    connection.close()


def freeze(root: Path, config: Path) -> None:
    """先冻结 Query、Scope、Reference 和性能协议，正式执行不再改写。"""
    specs = json.loads(config.read_text())
    connection = connect(root / 'documents.sqlite3')
    cases = []
    for number, spec in enumerate(specs, 1):
        term = spec['term']
        # instr 对完整文本执行字面子串判定；与 LIKE 不同，它不在 NUL 处截断。
        sessions = spec.get('sessions')
        filters = '' if sessions is None else ' AND session_id IN (' + ','.join('?' for _ in sessions) + ')'
        ids = [row[0] for row in connection.execute(
            "SELECT internal_message_id FROM documents WHERE instr(lower(content_text), lower(?)) > 0" + filters
            + ' ORDER BY internal_message_id', [term, *(sessions or [])])]
        cases.append({'case_id': f'cjk-{number:02}', **spec, 'reference_ids': ids,
                      'reference_completeness': 'exhaustive_literal', 'human_verified': False})
    write_new(root / 'frozen.json', {
        'created_at': utc_now(), 'cases': cases, 'top_k': 10, 'timing_repeats': 5,
        'timing': 'warm, alternating A/B order per case and repeat; count+top10 SQL, excludes readiness/projection',
        'agent_case_ids': ['cjk-01', 'cjk-21', 'cjk-33', 'cjk-34', 'cjk-45', 'cjk-46', 'cjk-57', 'cjk-61'],
        'agent_protocol': 'candidate Application.query only if baseline readiness cannot safely accept A; max 40 HTTP',
    })
    print([(case['case_id'], case['term'], len(case['reference_ids'])) for case in cases])
    connection.close()


def build_index(root: Path, strategy: str) -> dict[str, object]:
    """唯一处理变量是索引正文转换；两侧 schema、插入顺序和 SQLite 设置一致。"""
    path = root / f'{strategy}.sqlite3'
    if path.exists():
        raise FileExistsError(path)
    connection = connect(path)
    connection.execute('ATTACH DATABASE ? AS corpus', (str(root / 'documents.sqlite3'),))
    connection.execute('CREATE VIRTUAL TABLE messages_fts USING fts5(internal_message_id UNINDEXED, '
                       "session_id UNINDEXED, source_message_id UNINDEXED, content_text, tokenize='unicode61')")
    transform = normalize_lexical_index_text if strategy == 'B' else str
    connection.create_function('experiment_text', 1, transform)
    started = perf_counter()
    connection.execute('INSERT INTO messages_fts SELECT internal_message_id,session_id,NULL,'
                       'experiment_text(content_text) FROM corpus.documents')
    connection.commit()
    elapsed = (perf_counter() - started) * 1000
    connection.close()
    return {'insert_commit_ms': elapsed, 'bytes': path.stat().st_size}


def match_sql(repository: SQLiteCanonicalReadRepository, case: dict, strategy: str, *, scored: bool) -> tuple[str, list]:
    """复用生产 Scope 和 union SQL，只让 A 使用未归一化的 literal MATCH。"""
    query = LexicalQuery(keyword=case['term'], limit=10,
                         session_ids=None if case.get('sessions') is None else tuple(case['sessions']))
    sql, parameters = repository._lexical_match_union(query, scored=scored)
    if strategy == 'A':
        # 两个 union 分支各有一个 MATCH 参数；其余绑定完全保留生产实现。
        expression = ' AND '.join('"' + term.replace('"', '""') + '"' for term in query.terms)
        parameters[0] = expression
        parameters[len(parameters) // 2] = expression
    return sql, parameters


def open_index(root: Path, strategy: str) -> sqlite3.Connection:
    """实验 FTS 位于主库；Canonical 两种投影以只读附库视图参与同一生产 SQL。"""
    connection = connect(root / f'{strategy}.sqlite3')
    uri = f'{(root / "snapshot.sqlite3").resolve().as_uri()}?mode=ro'
    connection.execute('ATTACH DATABASE ? AS canonical', (uri,))
    for table in ('messages', 'forwarded_messages'):
        connection.execute(f'CREATE TEMP VIEW {table} AS SELECT * FROM canonical.{table}')
    return connection


def summarize(rows: list[dict]) -> dict:
    """同时保留 Query macro 与消息 micro；空 GT 不进入 Recall/Hit/MRR。"""
    result = {}
    for strategy in ('A', 'B'):
        positive = [row for row in rows if row['reference_count']]
        all_reference = sum(row['reference_count'] for row in positive)
        metrics = {}
        for name in ('recall_at_k', 'hit_at_k', 'mrr_at_k'):
            outcomes = [next(m for m in row[strategy]['metrics'] if m['name'] == name) for row in positive]
            numerator = sum(m['hits'] for m in outcomes)
            denominator = sum(m['denominator'] for m in outcomes)
            metrics[name] = {'macro': sum(m['value'] for m in outcomes) / len(outcomes) if outcomes else None,
                             'micro': numerator / denominator if denominator else None, 'numerator': numerator, 'denominator': denominator,
                             'queries': len(outcomes)}
        full_hits = sum(row[strategy]['full_true_positive'] for row in positive)
        full_returns = sum(row[strategy]['total'] for row in rows)
        top_returns = sum(len(row[strategy]['top10']) for row in rows)
        top_hits = sum(row[strategy]['top_true_positive'] for row in rows)
        latencies = sorted(value for row in rows for value in row[strategy]['latency_ms'])
        metrics.update({
            'completeness': {'macro': sum(row[strategy]['full_true_positive'] / row['reference_count']
                                        for row in positive) / len(positive) if positive else None,
                             'micro': full_hits / all_reference if all_reference else None, 'numerator': full_hits, 'denominator': all_reference},
            'literal_precision_at_10': {'numerator': top_hits, 'denominator': top_returns,
                                       'value': top_hits / top_returns if top_returns else None},
            'full_false_positive': full_returns - full_hits,
            'missing': all_reference - full_hits,
            'zero_correct': sum(row[strategy]['total'] == 0 for row in rows if not row['reference_count']),
            'zero_cases': sum(not row['reference_count'] for row in rows),
            'latency_median_ms': median(latencies), 'latency_p95_ms': latencies[math.ceil(.95 * len(latencies)) - 1],
        })
        result[strategy] = metrics
    return result


def run(root: Path, *, reuse_indexes: bool = False) -> None:
    """正式结果只创建一次；保存全深度身份、前十排名和每次耗时。"""
    if (root / 'results.json').exists():
        raise FileExistsError(root / 'results.json')
    frozen = json.loads((root / 'frozen.json').read_text())
    if reuse_indexes:
        # 仅显式复用已登记的相同快照索引，不重新解释任何 strategy metadata。
        build = json.loads((root / 'build.json').read_text())
    else:
        build = {strategy: build_index(root, strategy) for strategy in ('A', 'B')}
        write_new(root / 'build.json', build)
    connections = {strategy: open_index(root, strategy) for strategy in ('A', 'B')}
    repository = SQLiteCanonicalReadRepository(root / 'snapshot.sqlite3')
    rows = []
    for index, case in enumerate(frozen['cases']):
        reference = set(case['reference_ids'])
        gt = CaseGroundTruth(case['case_id'], tuple(reference), (), None, None, not reference, (),
                             'exhaustive', case['category'], 'development')
        row = {'case_id': case['case_id'], 'term': case['term'], 'category': case['category'],
               'reference_count': len(reference)}
        for strategy, connection in connections.items():
            sql, parameters = match_sql(repository, case, strategy, scored=True)
            ranked = connection.execute(f'{sql} ORDER BY {ORDER}', parameters).fetchall()
            ids = [hit['internal_message_id'] for hit in ranked]
            row[strategy] = {
                'total': len(ids), 'all_ids': ids, 'top10': ids[:10],
                'top_true_positive': len(set(ids[:10]) & reference),
                'full_true_positive': len(set(ids) & reference), 'latency_ms': [],
                'metrics': [outcome.to_dict() for outcome in score_ranking(gt, ids[:10], ks=(10,), mrr_k=10)],
            }
            # 每侧先 warm 一次；正式样本使用同一 count+top10 SQL，不混入全深度枚举。
            connection.execute(f'SELECT COUNT(*) FROM ({sql})', parameters).fetchone()
            connection.execute(f'{sql} ORDER BY {ORDER} LIMIT 10', parameters).fetchall()
        for repeat in range(frozen['timing_repeats']):
            for strategy in (('A', 'B') if (index + repeat) % 2 == 0 else ('B', 'A')):
                sql, parameters = match_sql(repository, case, strategy, scored=True)
                started = perf_counter()
                connections[strategy].execute(f'SELECT COUNT(*) FROM ({sql})', parameters).fetchone()
                connections[strategy].execute(f'{sql} ORDER BY {ORDER} LIMIT 10', parameters).fetchall()
                row[strategy]['latency_ms'].append((perf_counter() - started) * 1000)
        query = LexicalQuery(keyword=case['term'], limit=10,
                             session_ids=None if case.get('sessions') is None else tuple(case['sessions']))
        production_ids = [hit.message.internal_message_id for hit in repository.read_lexical_hits(query)]
        if production_ids != row['B']['top10'] or repository.count_lexical_hits(query) != row['B']['total']:
            raise AssertionError(f'production parity failed: {case["case_id"]}')
        row['production_parity'] = True
        rows.append(row)
        print(case['case_id'], case['term'], len(reference), row['A']['total'], row['B']['total'], flush=True)
    result = {'created_at': utc_now(), 'build': build, 'rows': rows,
              'overall': summarize(rows),
              'categories': {category: summarize([row for row in rows if row['category'] == category])
                             for category in sorted({row['category'] for row in rows})}}
    write_new(root / 'results.json', result)
    for connection in connections.values():
        connection.close()
    repository.close()
    # 公开汇总不携带真实聊天身份和正文；完整结果留在 ignored data/evaluation。
    public = {key: value for key, value in result.items() if key != 'rows'}
    public['rows'] = [{**{key: value for key, value in row.items() if key not in ('A', 'B')},
                       **{strategy: {key: value for key, value in row[strategy].items()
                                      if key not in ('all_ids', 'top10')} for strategy in ('A', 'B')}} for row in rows]
    write_new(Path('evaluation/experiments/cjk-bigram-v1') / f'{root.name}-summary.json', public)


def time_only(root: Path) -> None:
    """Agent 和测试均结束后独立复测 SQL 延迟，避免并发写入干扰性能结论。"""
    frozen = json.loads((root / 'frozen.json').read_text())
    connections = {side: open_index(root, side) for side in ('A', 'B')}
    repository = SQLiteCanonicalReadRepository(root / 'snapshot.sqlite3')
    rows = []
    for number, case in enumerate(frozen['cases']):
        samples = {side: [] for side in ('A', 'B')}
        statements = {side: match_sql(repository, case, side, scored=True) for side in ('A', 'B')}
        # 每题先对两侧预热；仅比较相同 count+top10 工作负载，不计生产 readiness 和正文恢复。
        for repeat in range(frozen['timing_repeats'] + 1):
            for side in (('A', 'B') if (number + repeat) % 2 == 0 else ('B', 'A')):
                sql, parameters = statements[side]
                started = perf_counter()
                connections[side].execute(f'SELECT COUNT(*) FROM ({sql})', parameters).fetchone()
                connections[side].execute(f'{sql} ORDER BY {ORDER} LIMIT 10', parameters).fetchall()
                if repeat:
                    samples[side].append((perf_counter() - started) * 1000)
        rows.append({'case_id': case['case_id'], 'category': case['category'], 'samples': samples})
    summary = {}
    for side in ('A', 'B'):
        values = sorted(value for row in rows for value in row['samples'][side])
        summary[side] = {'samples': len(values), 'median_ms': median(values),
                         'p95_ms': values[math.ceil(.95 * len(values)) - 1]}
    write_new(root / 'latency-final.json', {'created_at': utc_now(), 'protocol': frozen['timing'],
                                          'summary': summary, 'rows': rows})
    for connection in connections.values():
        connection.close()
    repository.close()
    print(json.dumps(summary), flush=True)


def main() -> None:
    """按显式阶段执行，冻结和正式比较不得混在一次自适应采样中。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'discover', 'freeze', 'run', 'time'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--source', type=Path, default=Path('data/trivae.sqlite3'))
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--reuse-indexes', action='store_true')
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare(args.root, args.source)
    elif args.stage == 'discover':
        discover(args.root)
    elif args.stage == 'freeze':
        freeze(args.root, args.config)
    elif args.stage == 'time':
        time_only(args.root)
    else:
        run(args.root, reuse_indexes=args.reuse_indexes)


if __name__ == '__main__':
    main()
