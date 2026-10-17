"""自动导入的索引装配：复用既有构建器，不复制 FTS/转发/语义底层算法。"""

from __future__ import annotations

import logging
from contextlib import closing
from pathlib import Path

from trivae.data.ingestion.auto_import_contracts import IndexKind, IndexWork
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.semantic.builder import SemanticIndexBuilder
from trivae.retrieval.semantic.contracts import EmbeddingProvider
from trivae.retrieval.semantic.embedding import SentenceTransformerEmbeddingProvider
from trivae.retrieval.semantic.index import SQLiteSemanticIndex
from trivae.retrieval.structured import MessageQuery

logger = logging.getLogger(__name__)


class LocalImportIndexUpdater:
    """每种索引合并一轮新增批次，只在持久待办存在时调用现有构建入口。"""

    def __init__(self, database_path: Path, *, semantic_provider: EmbeddingProvider | None = None) -> None:
        self.database_path = database_path.resolve()
        self.semantic_path = self.database_path.with_name(f"{self.database_path.stem}.semantic.sqlite3")
        self.semantic_provider = semantic_provider

    def update(self, index_kind: IndexKind, work: tuple[IndexWork, ...]) -> None:
        """成功返回后由导入编排确认队列；异常原样交回失败持久化边界。"""

        logger.info("Import index work started: kind=%s batches=%d", index_kind, len(work))
        if index_kind == "lexical":
            # 现有 FTS 构建在同一事务更新外层、转发投影及版本，不能只追加入库行数。
            with closing(SQLiteLexicalIndex(self.database_path)) as lexical:
                stats = lexical.rebuild()
            logger.info("Import lexical index completed: %s", stats)
            return

        # 模型仅在真的有语义索引待办时装配，不影响空目录或纯重复执行。
        provider = self.semantic_provider or SentenceTransformerEmbeddingProvider()
        with (
            closing(SQLiteCanonicalReadRepository(self.database_path)) as repository,
            closing(SQLiteSemanticIndex(self.semantic_path)) as semantic,
        ):
            builder = SemanticIndexBuilder(
                repository, semantic, provider, database_identity=self.database_path.name
            )
            state = semantic.state()
            # identity、数量和 revision 必须都一致，才属于既有续建契约允许的同一源快照。
            same_snapshot = (
                state is not None
                and state.identity.serialized == builder.identity.serialized
                and state.canonical_message_count == repository.count_messages(MessageQuery(limit=1))
                and state.canonical_revision == repository.canonical_revision()
            )
            if same_snapshot and state is not None and state.status == "completed":
                # 索引已提交、队列确认前中断时，补确认即可，不重复计算整库向量。
                logger.info("Import semantic index already committed for current snapshot")
                return
            # 只对同源未完成构建续建；新数据改变源水位时，使用现有正式重建路径。
            resume = same_snapshot and state is not None and state.status in {"building", "failed", "partial"}
            stats_semantic = builder.rebuild(resume=resume)
            logger.info("Import semantic index completed: %s", stats_semantic.to_dict())


def create_import_index_updater(database_path: Path) -> LocalImportIndexUpdater:
    """给薄 CLI 提供装配入口，不创建 Query / Evaluation 或外部模型服务。"""

    return LocalImportIndexUpdater(database_path)
