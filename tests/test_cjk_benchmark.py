"""实验适配器在真实 SQLite 上保护 Scope、投影与评分分母。"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from scripts.cjk_bigram_benchmark import summarize
from tests.test_evaluation import _snapshot
from trivae.evaluation.contracts import DatasetSnapshot, EvaluationContractError


def test_snapshot_keeps_full_structured_source_identity() -> None:
    """复现 80 个真实来源使快照身份超过 4,000 字符的失败。"""
    sources = json.dumps([{'source_id': f'source-{i}', 'file_name': '群聊导出文件' * 12} for i in range(80)])
    snapshot = replace(_snapshot(), source_identity=sources,
                       canonical_database_identity=f'sqlite-canonical-v1:sources={sources}',
                       deterministic_fingerprint=json.dumps({'sources': sources}))
    restored = DatasetSnapshot.from_dict(snapshot.to_dict())
    assert restored.source_identity == sources
    assert restored.deterministic_fingerprint == snapshot.deterministic_fingerprint
    # 身份字段的放宽不应改变普通短标识符的契约。
    import pytest
    with pytest.raises(EvaluationContractError, match='snapshot_id exceeds'):
        replace(snapshot, snapshot_id='x' * 4001)


def test_literal_oracle_rejects_spaced_mixed_false_positive() -> None:
    """v2 对混排短语忽略原始空格边界；必须如实记录字面误匹配。"""
    from trivae.data.storage.sqlite_lexical_text import normalize_lexical_index_text
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE VIRTUAL TABLE f USING fts5(text)')
    connection.execute('INSERT INTO f VALUES (?)', (normalize_lexical_index_text('AI 应用'),))
    expression = '"' + normalize_lexical_index_text('AI应用') + '"'
    assert connection.execute('SELECT COUNT(*) FROM f WHERE f MATCH ?', (expression,)).fetchone()[0] == 1
    assert connection.execute("SELECT 'AI 应用' LIKE '%AI应用%'").fetchone()[0] == 0
    connection.close()


def test_summary_does_not_score_empty_reference_as_recall() -> None:
    """空 GT 只计无结果判定，不能虚构满分 Recall。"""
    row = {'reference_count': 0,
           **{strategy: {'metrics': [], 'full_true_positive': 0, 'total': 0,
                          'top10': [], 'top_true_positive': 0, 'latency_ms': [1.]}
              for strategy in ('A', 'B')}}
    result = summarize([row])
    assert result['A']['recall_at_k']['macro'] is None
    assert result['A']['completeness']['micro'] is None
    assert result['B']['zero_correct'] == 1


def test_experiment_uses_production_keyword_and_scope_contract() -> None:
    """接口不接受 terms 入参；多词必须延用生产 literal AND 语义。"""
    from scripts.cjk_bigram_benchmark import match_sql
    from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
    # SQL 组装不访问连接，可以直接使用生产实例的无状态方法。
    repository = object.__new__(SQLiteCanonicalReadRepository)
    sql, a = match_sql(repository, {'term': 'HTTP 500', 'sessions': ['qq:900']}, 'A', scored=True)
    _, b = match_sql(repository, {'term': 'HTTP 500', 'sessions': ['qq:900']}, 'B', scored=True)
    assert a == b == ['"HTTP" AND "500"', 'qq:900', '"HTTP" AND "500"', 'qq:900']
    assert 'forwarded_messages' in sql


def test_full_text_oracle_handles_nul_without_changing_literal_semantics() -> None:
    """真实 Failure Case：LIKE 在 NUL 处结束，不能充当整条消息的穷举 Oracle。"""
    connection = sqlite3.connect(':memory:')
    text = '前文\x00模型与 DeepSeek；foo_bar 100%'
    assert connection.execute('SELECT ? LIKE ?', (text, '%模型%')).fetchone()[0] == 0
    for term in ('模型', 'deepseek', 'foo_bar', '100%'):
        assert connection.execute('SELECT instr(lower(?), lower(?)) > 0', (text, term)).fetchone()[0] == 1
    assert connection.execute('SELECT instr(lower(?), lower(?)) > 0', (text, 'fooXbar')).fetchone()[0] == 0
    connection.close()


def test_real_snapshot_constructor_and_case_roundtrip_with_eighty_sources(tmp_path) -> None:
    """从真实表结构构造并序列化多来源 Snapshot，覆盖最初失败的完整主链路。"""
    from tests.test_evaluation import _case
    from trivae.evaluation.contracts import EvaluationCaseBundle
    path = tmp_path / 'snapshot.sqlite3'
    connection = sqlite3.connect(path)
    connection.executescript('''CREATE TABLE sources(source_id, file_name, adapter, format_version, platform,
                             external_chat_id); CREATE TABLE messages(timestamp); CREATE TABLE import_batches(id);''')
    connection.executemany('INSERT INTO sources VALUES (?,?,?,?,?,?)',
                           [(str(i), f'export-{i}.json', 'qce', '1', 'qq', str(i)) for i in range(80)])
    connection.commit()
    connection.close()
    snapshot = DatasetSnapshot.from_database(path)
    assert len(snapshot.canonical_database_identity) > 4000
    restored = EvaluationCaseBundle.from_dict(_case(snapshot).to_dict())
    assert restored.dataset_snapshot == snapshot


def test_isolated_indexes_preserve_forward_scope_and_baseline_identity(tmp_path) -> None:
    """真实导入→快照→两种 FTS→生产证据恢复，验证实验没有伪造策略或混入 preview。"""
    from scripts.cjk_bigram_agent import ExperimentLexicalReader
    from scripts.cjk_bigram_benchmark import build_index, prepare
    from tests.test_forward_retrieval import make_forward_message
    from tests.test_ingestion import make_message, write_export
    from trivae.data.ingestion.importer import SharedImporter
    from trivae.data.storage.sqlite import SQLiteCanonicalStore
    from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
    from trivae.retrieval.structured import LexicalQuery
    source = tmp_path / 'source.sqlite3'
    store = SQLiteCanonicalStore(source)
    paths = [write_export(tmp_path, 'forward(100).json', [
        make_forward_message('outer', 1000, [make_message('a', 1, 100, '我推荐这个项目'),
                                            make_message('b', 2, 200, '推荐')]),
        make_message('ordinary', 2, 2000, '真心推荐')], chat_name='测试一', peer_uid='100', version='1'),
        write_export(tmp_path, 'other(200).json', [make_message('other', 1, 3000, '推荐')],
                     chat_name='测试二', peer_uid='200', version='1')]
    SharedImporter(store).import_paths(paths)
    store.close()
    root = tmp_path / 'experiment'
    prepare(root, source)
    for strategy in ('A', 'B'):
        build_index(root, strategy)
    canonical = SQLiteCanonicalReadRepository(root / 'snapshot.sqlite3')
    adapters = {side: ExperimentLexicalReader(root, side, canonical) for side in ('A', 'B')}
    query = LexicalQuery(keyword='推荐', session_ids=('qq:100',), end_timestamp=1500, limit=10)
    assert adapters['A'].count_lexical_hits(query) == 1
    assert adapters['B'].count_lexical_hits(query) == 2
    assert adapters['B'].read_lexical_hits(query) == canonical.read_lexical_hits(query)
    assert all(hit.message.forward is not None for hit in adapters['B'].read_lexical_hits(query))
    assert adapters['B'].count_lexical_hits(LexicalQuery(keyword='预览秘密')) == 0
    # A 的数据库就是原文 unicode61，不能冒充 v2 或拥有生产 strategy metadata。
    assert adapters['A'].connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='trivae_derived_meta'").fetchone()[0] == 0
    for adapter in adapters.values():
        adapter.connection.close()
    canonical.close()
