"""真实 sqlite-vec 上的局部重切、输入复用与原子发布回归。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_ingestion import make_message, write_export
from tests.test_semantic_resume import _ResumeProvider
from trivae.bootstrap.application import create_application
from trivae.retrieval.semantic.builder import SemanticIndexBuilder
from trivae.retrieval.semantic.chunking import SemanticChunkConfig, SemanticChunker
from trivae.retrieval.semantic.contracts import SemanticEmbeddingError, SemanticIndexStale, SemanticQuery
from trivae.retrieval.semantic.index import SQLiteSemanticIndex
from trivae.retrieval.semantic.retrieval import SemanticRetrieval

CONFIG = SemanticChunkConfig(
    parent_gap_seconds=20, parent_max_messages=5,
    child_min_chars=1, child_max_chars=100, child_max_messages=2,
    child_overlap_messages=1, semantic_void_skip_threshold=0,
)


def import_messages(application, root: Path, messages: list[dict], name: str = 'part.json') -> None:
    """复用正式 QQ importer，在独立临时 Canonical 库累计导入。"""

    raw = root / 'raw'
    raw.mkdir(exist_ok=True)
    write_export(raw, name, messages, chat_name='增量群', peer_uid='100', version='5')
    application.import_directory(raw)


def messages(start: int, count: int, *, base: int = 1_790_000_000_000, step: int = 1000) -> list[dict]:
    """构造带稳定来源 ID 的连续消息，远隔时间段用来验证安全边界。"""

    return [make_message(f'm{i}', i, base + i * step, f'数据库索引设计第{i}条完整说明') for i in range(start, start + count)]


def builder(application, provider=None, config=CONFIG):
    """Builder 与检索共享同一个 chunker identity。"""

    result = application._semantic_builder
    assert result is not None
    result.chunker = SemanticChunker(config)
    if provider is not None:
        result.provider = provider
    return result


def rows(index: SQLiteSemanticIndex) -> tuple:
    """内部 rowid 不是 Chunk 身份；按 Chunk ID 比较有效元数据与 float32 字节。"""

    dimension = index.state().identity.embedding.dimension
    return tuple(tuple(row) for row in index._connection.execute(
        f'''SELECT c.chunk_id, c.parent_id, c.session_id, c.parent_start_message_id,
        c.parent_end_message_id, c.start_message_id, c.end_message_id, c.start_timestamp,
        c.end_timestamp, c.message_count, c.effective_chars, c.embedding_input, v.embedding
        FROM semantic_chunks c JOIN semantic_vectors_{dimension} v USING(vector_id) ORDER BY c.chunk_id'''
    ))


def assert_full_equivalent(application, tmp_path: Path, incremental: SemanticIndexBuilder) -> None:
    """全量重建 oracle 独立落库，同时比较候选分数与 canonical 来源恢复。"""

    clean = SQLiteSemanticIndex(tmp_path / 'oracle.sqlite3')
    try:
        full = SemanticIndexBuilder(
            application.read_repository, clean, _ResumeProvider(),
            database_identity=incremental.database_identity, chunker=incremental.chunker,
        )
        full.rebuild()
        assert rows(incremental.store) == rows(clean)
        assert incremental.store.integrity_report(incremental.identity).status == 'valid'
        # 取全部候选再比较，避免有限 K 在相同分数上的内部 rowid tie-break 干扰。
        limit = clean.state().chunk_count
        if limit:
            actual = incremental.store.dense_search(incremental.identity, (0., 0., 1.), limit)
            expected = clean.dense_search(full.identity, (0., 0., 1.), limit)
            assert actual == expected
            actual_retrieval = SemanticRetrieval(
                application.read_repository, incremental.store, incremental.provider,
                database_identity=incremental.database_identity, chunker=incremental.chunker,
            )
            expected_retrieval = SemanticRetrieval(
                application.read_repository, clean, full.provider,
                database_identity=full.database_identity, chunker=full.chunker,
            )
            query = SemanticQuery(query='数据库索引', dense_top_k=limit, limit=min(limit, 20))
            left = actual_retrieval.search(query)
            right = expected_retrieval.search(query)
            assert left.hits == right.hits
            assert left.expanded_messages == right.expanded_messages
    finally:
        clean.close()


def test_first_build_and_no_change_never_reload_provider(tmp_path: Path) -> None:
    provider = _ResumeProvider()
    with create_application(tmp_path / 'app.sqlite3', semantic_provider=provider) as application:
        import_messages(application, tmp_path, messages(0, 8))
        current = builder(application)
        first = current.update()
        assert first.build_mode == 'full'
        before = rows(current.store)
        idle = _ResumeProvider()
        current.provider = idle
        stats = current.update()
        assert stats.build_mode == 'unchanged'
        assert stats.embedding_count == idle.preload_count == 0
        assert idle.documents == []
        import_messages(application, tmp_path, messages(0, 8))
        assert current.update().embedding_count == 0
        assert rows(current.store) == before


@pytest.mark.parametrize('operation', ['append', 'late', 'boundary', 'content', 'delete', 'move', 'void', 'rename'])
def test_local_changes_match_full_and_keep_remote_segment(tmp_path: Path, operation: str) -> None:
    database = tmp_path / 'app.sqlite3'
    with create_application(database, semantic_provider=_ResumeProvider()) as application:
        import_messages(application, tmp_path, messages(0, 12) + messages(100, 12))
        current = builder(application)
        current.update()
        old_remote = tuple(tuple(row) for row in current.store._connection.execute(
            'SELECT * FROM semantic_chunks WHERE start_timestamp >= 1790000100000 ORDER BY vector_id'
        ))
        provider = _ResumeProvider()
        current.provider = provider
        if operation in ('append', 'late', 'boundary'):
            offset = {'append': 12000, 'late': 3500, 'boundary': 4500}[operation]
            import_messages(application, tmp_path, [make_message('new', 99, 1_790_000_000_000 + offset, '远程连接新增配置说明')], 'new.json')
        else:
            with sqlite3.connect(database) as connection:
                if operation == 'content':
                    connection.execute("UPDATE messages SET content_text='情感锚点正文已修改' WHERE source_message_id='m3'")
                elif operation == 'delete':
                    # 独立 fixture 不启用外键；复现真实 Canonical mutation 后的索引维护。
                    connection.execute("DELETE FROM messages WHERE source_message_id='m3'")
                elif operation == 'move':
                    connection.execute("UPDATE messages SET timestamp=1790000003500 WHERE source_message_id='m0'")
                elif operation == 'void':
                    connection.execute("UPDATE messages SET system=1 WHERE source_message_id='m3'")
                else:
                    connection.execute("UPDATE chat_sessions SET name='更新后的群名'")
        stats = current.update()
        assert stats.build_mode == 'incremental'
        assert stats.embedding_count == len(provider.documents)
        if operation != 'rename':
            remote = tuple(tuple(row) for row in current.store._connection.execute(
                'SELECT * FROM semantic_chunks WHERE start_timestamp >= 1790000100000 ORDER BY vector_id'
            ))
            assert remote == old_remote
            assert stats.embedding_count < stats.chunk_count
        assert_full_equivalent(application, tmp_path, current)


@pytest.mark.parametrize('interruption', ['embedding', 'write', 'source'])
def test_failed_update_rolls_back_and_restarts_without_full_recompute(tmp_path: Path, interruption: str) -> None:
    database = tmp_path / 'app.sqlite3'
    with create_application(database, semantic_provider=_ResumeProvider()) as application:
        import_messages(application, tmp_path, messages(0, 12) + messages(100, 12))
        current = builder(application)
        current.update()
        previous = rows(current.store)
        revision = current.store.state().canonical_revision
        import_messages(application, tmp_path, messages(12, 4), 'new.json')
        if interruption == 'embedding':
            current.provider = _ResumeProvider(fail_batch=1)
            with pytest.raises(SemanticEmbeddingError):
                current.update()
        elif interruption == 'write':
            with patch.object(current.store, 'finish', side_effect=KeyboardInterrupt):
                with pytest.raises(KeyboardInterrupt):
                    current.update()
        else:
            class ChangingProvider(_ResumeProvider):
                def embed_documents(self, texts):
                    with sqlite3.connect(database) as connection:
                        connection.execute("UPDATE messages SET content_text='情感锚点并发变更' WHERE source_message_id='m3'")
                    return super().embed_documents(texts)
            current.provider = ChangingProvider()
            with pytest.raises(SemanticIndexStale, match='changed during'):
                current.update()
        assert rows(current.store) == previous
        assert current.store.state().canonical_revision == revision
        assert current.store.state().last_error
    # 真正关闭并重开两个库，再从旧发布水位重算受影响段。
    with create_application(database, semantic_provider=_ResumeProvider()) as application:
        current = builder(application)
        stats = current.update()
        assert stats.build_mode == 'incremental'
        assert stats.reused_chunk_count > stats.embedding_count
        assert_full_equivalent(application, tmp_path, current)


def test_model_and_chunker_changes_require_full_rebuild(tmp_path: Path) -> None:
    with create_application(tmp_path / 'app.sqlite3', semantic_provider=_ResumeProvider()) as application:
        import_messages(application, tmp_path, messages(0, 8))
        current = builder(application)
        current.update()
        current.chunker = SemanticChunker(replace(CONFIG, child_max_messages=3))
        assert current.update().build_mode == 'full'
        provider = _ResumeProvider()
        provider.identity = replace(provider.identity, model='new-model')
        current.provider = provider
        stats = current.update()
        assert stats.build_mode == 'full'
        assert stats.embedding_count == stats.chunk_count


def test_forward_inner_mutation_same_outer_count_updates_exact_inputs(tmp_path: Path) -> None:
    database = tmp_path / 'app.sqlite3'
    with create_application(database, semantic_provider=_ResumeProvider()) as application:
        root = make_message('forward', 99, 1_790_000_050_000, '[聊天记录]', message_type='forward')
        children = [make_message(f'child{i}', i, i * 1000, f'内部数据库讨论{i}') for i in range(6)]
        root['content']['elements'] = [{'type': 'forward', 'data': {'messages': children}}]
        import_messages(application, tmp_path, messages(0, 12) + [root] + messages(100, 12))
        current = builder(application)
        current.update()
        provider = _ResumeProvider()
        current.provider = provider
        children[2]['content']['text'] = '远程连接内部消息发生变化'
        children.append(make_message('added', 7, 7000, '新增情感锚点转发证据'))
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE messages SET content_json=? WHERE source_message_id='forward'", (json.dumps(root['content'], ensure_ascii=False),))
        stats = current.update()
        assert stats.embedding_count > 0
        assert stats.reused_chunk_count > stats.embedding_count
        assert all('第100条' not in text for text in provider.documents)
        assert_full_equivalent(application, tmp_path, current)


def test_changed_snapshot_after_failed_full_build_cannot_publish_incomplete_base(tmp_path: Path) -> None:
    """失败全量的未覆盖历史不能被一次局部变更误标 completed。"""

    with create_application(tmp_path / 'app.sqlite3', semantic_provider=_ResumeProvider(fail_batch=2)) as application:
        import_messages(application, tmp_path, messages(0, 12) + messages(100, 12))
        current = builder(application)
        with pytest.raises(SemanticEmbeddingError):
            current.update()
        import_messages(application, tmp_path, messages(12, 1), 'new.json')
        current.provider = _ResumeProvider()
        stats = current.update()
        assert stats.build_mode == 'full'
        assert stats.embedding_count == stats.chunk_count
        assert_full_equivalent(application, tmp_path, current)


def test_effectively_unchanged_inputs_and_void_segment_do_not_load_model(tmp_path: Path) -> None:
    """无关 raw 变化仍推进 revision，但完整比较后复用全部向量；纯 void 段无模型工作。"""

    database = tmp_path / 'app.sqlite3'
    with create_application(database, semantic_provider=_ResumeProvider()) as application:
        import_messages(application, tmp_path, messages(0, 12))
        current = builder(application)
        current.update()
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE messages SET raw_payload_json='{}' WHERE source_message_id='m3'")
        provider = _ResumeProvider()
        current.provider = provider
        stats = current.update()
        assert stats.embedding_count == provider.preload_count == 0
        assert stats.reused_chunk_count == stats.chunk_count
        import_messages(application, tmp_path, [make_message('void', 999, 1_790_000_999_000, '嗯')], 'void.json')
        stats = current.update()
        assert stats.embedding_count == provider.preload_count == 0
        assert_full_equivalent(application, tmp_path, current)


@pytest.mark.parametrize('change', ['delete_bridge', 'delete_many', 'insert_bridge', 'move_session'])
def test_gap_boundaries_include_old_and_new_components(tmp_path: Path, change: str) -> None:
    """旧时间位置与新连通段共同决定范围，删除桥接消息不能漏掉任一侧。"""

    database = tmp_path / 'app.sqlite3'
    with create_application(database, semantic_provider=_ResumeProvider()) as application:
        import_messages(application, tmp_path, messages(0, 15, step=15000) + messages(16, 8, step=15000))
        current = builder(application)
        current.update()
        with sqlite3.connect(database) as connection:
            if change == 'delete_bridge':
                connection.execute("DELETE FROM messages WHERE source_message_id='m7'")
            elif change == 'delete_many':
                connection.execute("DELETE FROM messages WHERE source_message_id IN ('m5','m6','m7','m8','m9')")
            elif change == 'move_session':
                connection.execute("INSERT INTO chat_sessions(session_id, platform, external_chat_id, name, chat_type) VALUES('qq:200','qq','200','另一群','group')")
                connection.execute("UPDATE messages SET session_id='qq:200' WHERE source_message_id='m7'")
        if change == 'insert_bridge':
            # 两个旧段通过新消息相连，需要重新计算两侧 Parent，而不能尾追加。
            import_messages(application, tmp_path, [make_message('bridge', 99, 1_790_000_225_000, '远程连接桥接消息')], 'bridge.json')
        current.provider = _ResumeProvider()
        assert current.update().build_mode == 'incremental'
        assert_full_equivalent(application, tmp_path, current)


def test_abrupt_process_exit_rolls_back_vec_and_metadata(tmp_path: Path) -> None:
    """子进程写入 vec0 后直接退出，重开必须只看到旧发布版本，再完成局部重放。"""

    import subprocess
    import sys

    database = tmp_path / 'app.sqlite3'
    with create_application(database, semantic_provider=_ResumeProvider()) as application:
        import_messages(application, tmp_path, messages(0, 12) + messages(100, 12))
        current = builder(application)
        current.update()
        previous = rows(current.store)
        revision = current.store.state().canonical_revision
        import_messages(application, tmp_path, messages(12, 4), 'new.json')
    # os._exit 不运行异常处理/finally，覆盖真实进程终止而非可捕获异常。
    process = subprocess.run([sys.executable, '-c', '''
import os
import sys
from pathlib import Path
from tests.test_semantic_incremental import builder
from tests.test_semantic_resume import _ResumeProvider
from trivae.bootstrap.application import create_application
with create_application(Path(sys.argv[1]), semantic_provider=_ResumeProvider()) as application:
    current = builder(application)
    original = current.store.insert_chunks
    def stop_after_write(chunks):
        original(chunks)
        os._exit(73)
    current.store.insert_chunks = stop_after_write
    current.update()
''', str(database)], capture_output=True, text=True)
    assert process.returncode == 73, process.stderr
    with create_application(database, semantic_provider=_ResumeProvider()) as application:
        current = builder(application)
        assert rows(current.store) == previous
        assert current.store.state().canonical_revision == revision
        stats = current.update()
        assert stats.build_mode == 'incremental'
        assert stats.reused_chunk_count > stats.embedding_count
        assert_full_equivalent(application, tmp_path, current)


def test_legacy_interrupted_build_migrates_instead_of_comparing_missing_inputs(tmp_path: Path) -> None:
    """升级时遇到旧失败全量构建，自动入口明确重建输入凭据，不能卡在续建比较。"""

    with create_application(tmp_path / 'app.sqlite3', semantic_provider=_ResumeProvider(fail_batch=2)) as application:
        import_messages(application, tmp_path, messages(0, 12))
        current = builder(application)
        with pytest.raises(SemanticEmbeddingError):
            current.update()
        with current.store._connection:
            current.store._connection.execute('UPDATE semantic_chunks SET embedding_input=NULL')
            current.store._connection.execute('UPDATE semantic_index_state SET embedding_input_format=0')
        current.provider = _ResumeProvider()
        stats = current.update()
        assert stats.build_mode == 'full'
        assert stats.embedding_count == stats.chunk_count
        assert_full_equivalent(application, tmp_path, current)


@pytest.mark.parametrize('ordering', ['characters', 'same_timestamp', 'missing_seq'])
def test_character_limits_and_tied_ordering_preserve_full_semantics(tmp_path: Path, ordering: str) -> None:
    """字符上限传播、相同时间与缺失 seq 都沿用原有确定性排序及切分。"""

    config = replace(CONFIG, parent_max_messages=100, parent_max_chars=100) if ordering == 'characters' else CONFIG
    with create_application(tmp_path / 'app.sqlite3', semantic_provider=_ResumeProvider()) as application:
        original = messages(0, 14) + messages(100, 8)
        if ordering != 'characters':
            for item in original[:14]:
                item['timestamp'] = 1_790_000_000_000
                if ordering == 'missing_seq':
                    item.pop('seq', None)
        import_messages(application, tmp_path, original)
        current = builder(application, config=config)
        current.update()
        incoming = make_message(
            'late', None if ordering == 'missing_seq' else 4,
            1_790_000_003_500 if ordering == 'characters' else 1_790_000_000_000,
            '远程连接新增长文本' * 8,
        )
        import_messages(application, tmp_path, [incoming], 'late.json')
        current.provider = _ResumeProvider()
        stats = current.update()
        assert stats.build_mode == 'incremental'
        assert stats.reused_chunk_count > 0
        assert_full_equivalent(application, tmp_path, current)
