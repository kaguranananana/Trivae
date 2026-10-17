#!/usr/bin/env python3
"""在全新临时库对照局部更新与全量重建；可显式启用真实 Qwen provider。"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from trivae.bootstrap.application import create_application
from trivae.retrieval.semantic.builder import SemanticIndexBuilder
from trivae.retrieval.semantic.contracts import EmbeddingModelIdentity, SemanticQuery
from trivae.retrieval.semantic.embedding import SentenceTransformerEmbeddingProvider
from trivae.retrieval.semantic.index import SQLiteSemanticIndex
from trivae.retrieval.semantic.retrieval import SemanticRetrieval


class CountingProvider:
    """记录真实调用数；无 delegate 时使用可解释主题计数向量，不模拟模型性能。"""

    document_batch_size = 8

    def __init__(self, real: bool) -> None:
        self.delegate = SentenceTransformerEmbeddingProvider() if real else None
        self.identity = self.delegate.identity if self.delegate else EmbeddingModelIdentity(
            provider='deterministic-fixture', model='topic-counts', dimension=4,
            pooling='last_token', normalized=True, query_instruction='fixture retrieval',
        )
        self.documents = 0
        self.preloads = 0

    def preload(self) -> None:
        """真实模式只调用现有正式 provider；计数模式不加载任何模型。"""

        self.preloads += 1
        if self.delegate:
            self.delegate.preload()

    @staticmethod
    def vector(text: str) -> tuple[float, ...]:
        """主题词出现次数构成确定性向量，供逐字节回归比较。"""

        values = tuple(float(text.count(term) + 1) for term in ('数据库', '向量', '远程', '月球'))
        norm = math.sqrt(sum(item * item for item in values))
        return tuple(item / norm for item in values)

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.documents += len(texts)
        return self.delegate.embed_documents(texts) if self.delegate else tuple(self.vector(text) for text in texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self.delegate.embed_query(text) if self.delegate else self.vector(text)


def export(path: Path, count: int, *, extra: bool) -> None:
    """每 50 条设置独立时间段；追加消息与末段相连，并加入一条历史补录。"""

    records = []
    for index in range(count):
        text = f'数据库向量索引的第 {index} 条工程讨论，保留消息上下文和来源。'
        records.append(message(str(index), 1_790_000_000_000 + (index // 50) * 3_600_000 + index % 50 * 1000, text))
    if extra:
        last = records[-1]['timestamp']
        records.append(message('appended', last + 1000, '月球基地使用远程激光通信，配置专用数据链路。'))
        records.append(message('late', records[3]['timestamp'] + 500, '历史补录：数据库向量索引采用精确输入比较。'))
    path.write_text(json.dumps({
        'metadata': {'name': 'QQChatExporter', 'version': '5'},
        'chatInfo': {'name': '增量实验群', 'type': 'group', 'peerUid': '100'},
        'messages': records,
    }, ensure_ascii=False), encoding='utf-8')


def message(identity: str, timestamp: int, text: str) -> dict:
    """生成公开协议最小文本记录，交给正式 Parser 处理。"""

    return {
        'id': identity, 'timestamp': timestamp, 'type': 'text',
        'sender': {'uid': 'author', 'name': '工程师'},
        'content': {'text': text, 'elements': [{'type': 'text', 'data': {'text': text}}]},
    }


def snapshot(index: SQLiteSemanticIndex) -> dict[str, tuple[tuple, tuple[float, ...]]]:
    """比较有效 Chunk 与 float32 数值，内部自增 vector_id 不属于业务身份。"""

    state = index.state()
    assert state is not None
    dimension = state.identity.embedding.dimension
    result = {}
    for row in index._connection.execute(
        f'''SELECT c.*, v.embedding FROM semantic_chunks c
        JOIN semantic_vectors_{dimension} v USING(vector_id) ORDER BY c.chunk_id'''
    ):
        metadata = tuple(row[key] for key in row.keys() if key not in ('vector_id', 'embedding'))
        result[row['chunk_id']] = (metadata, index._unpack_vector(row['embedding'], dimension))
    return result


def verify(count: int, real: bool) -> dict:
    """初建、增量和独立全量 oracle 使用同一 provider identity、配置与最终 Canonical。"""

    if count < 4:
        raise ValueError('messages must be at least 4')
    with tempfile.TemporaryDirectory(prefix='trivae-semantic-experiment-') as temporary:
        root = Path(temporary)
        raw = root / 'raw'
        raw.mkdir()
        export(raw / 'fixture.json', count, extra=False)
        provider = CountingProvider(real)
        with create_application(root / 'canonical.sqlite3', semantic_provider=provider) as application:
            application.import_directory(raw)
            current = application._semantic_builder
            assert current is not None
            initial = current.update()
            export(raw / 'fixture.json', count, extra=True)
            imported = application.import_directory(raw)
            incremental = current.update()
            actual = snapshot(current.store)
            # 空批次必须连 preload 都不再调用。
            before = (provider.documents, provider.preloads)
            idle = current.update()
            assert before == (provider.documents, provider.preloads)
            with closing(SQLiteSemanticIndex(root / 'full.sqlite3')) as clean:
                full = SemanticIndexBuilder(
                    application.read_repository, clean, provider,
                    database_identity=current.database_identity, chunker=current.chunker,
                )
                baseline = full.rebuild()
                expected = snapshot(clean)
                assert actual.keys() == expected.keys()
                max_delta = 0.0
                for identity, (metadata, vector) in actual.items():
                    expected_metadata, expected_vector = expected[identity]
                    assert metadata == expected_metadata
                    max_delta = max(max_delta, max(abs(a - b) for a, b in zip(vector, expected_vector, strict=True)))
                # 真实 Qwen batching 可能造成浮点舍入差异，使用明确数值容差。
                assert max_delta <= (1e-4 if real else 0)
                query = SemanticQuery(query='月球基地远程激光通信', limit=1, dense_top_k=min(50, len(actual)))
                left = SemanticRetrieval(
                    application.read_repository, current.store, provider,
                    database_identity=current.database_identity, chunker=current.chunker,
                ).search(query)
                right = SemanticRetrieval(
                    application.read_repository, clean, provider,
                    database_identity=current.database_identity, chunker=current.chunker,
                ).search(query)
                left_ids = tuple(item.internal_message_id for item in left.expanded_messages)
                right_ids = tuple(item.internal_message_id for item in right.expanded_messages)
                assert left_ids == right_ids
                assert 'qq:100:appended' in left_ids
                assert current.store.integrity_report(current.identity).status == 'valid'
                return {
                    'provider': provider.identity.to_dict(), 'real_provider': real,
                    'dataset': 'synthetic independent temporary SQLite',
                    'canonical_total': count + 2, 'inserted': imported.to_dict()['totals']['inserted_count'],
                    'initial': initial.to_dict(), 'incremental': incremental.to_dict(),
                    'full_baseline': baseline.to_dict(), 'idle': idle.to_dict(),
                    'metadata_equal': True, 'max_vector_abs_delta': max_delta,
                    'retrieval_source_ids_equal': True, 'retrieved_ids': left_ids,
                    'embedding_computations_avoided': baseline.embedding_count - incremental.embedding_count,
                }


def main() -> None:
    """结果只写用户指定的新文件，数据库始终由临时目录托管。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--messages', type=int, default=3000)
    parser.add_argument('--real', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.messages, args.real)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({key: report[key] for key in (
        'canonical_total', 'embedding_computations_avoided', 'metadata_equal',
        'max_vector_abs_delta', 'retrieval_source_ids_equal',
    )}, ensure_ascii=False))


if __name__ == '__main__':
    main()
