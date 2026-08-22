"""Composition Root 与 Application facade。"""

from __future__ import annotations

from pathlib import Path

from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput, ToolEnvelope
from trivae.capabilities.registry import CapabilityRegistry
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.capabilities.tools import SearchMessagesTool
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.model import ImportRunSummary
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import LexicalIndexStats, SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.runtime.contracts import AgentRunRequest, AgentRuntime, RuntimeResult
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import (
    AggregateQuery,
    MessageQuery,
    StructuredAggregateResult,
    StructuredMessageResult,
    StructuredRetrieval,
)


class TrivaeApplication:
    """集中拥有 Store、read adapter、Retrieval 与 Capability lifecycle。"""

    def __init__(
        self,
        store: SQLiteCanonicalStore,
        importer: SharedImporter,
        read_repository: SQLiteCanonicalReadRepository,
        structured_retrieval: StructuredRetrieval,
        lexical_retrieval: LexicalRetrieval,
        capability_registry: CapabilityRegistry,
        lexical_index: SQLiteLexicalIndex | None = None,
        agent_runtime: AgentRuntime | None = None,
    ) -> None:
        self.store = store
        self.importer = importer
        self.read_repository = read_repository
        self.structured_retrieval = structured_retrieval
        self.lexical_retrieval = lexical_retrieval
        self.capability_registry = capability_registry
        self._lexical_index = lexical_index
        # Runtime 是可注入且惰性创建的，检索-only caller 不需要 provider 配置。
        self._agent_runtime = agent_runtime

    def import_directory(self, raw_directory: Path) -> ImportRunSummary:
        """让 CLI 通过 Application 进入 data ingestion，而不是直接读 Store。"""

        return self.importer.import_directory(raw_directory)

    def retrieve_messages(self, query: MessageQuery) -> StructuredMessageResult:
        """Application facade 的 Structured message 入口。"""

        return self.structured_retrieval.retrieve_messages(query)

    def aggregate_messages(self, query: AggregateQuery) -> StructuredAggregateResult:
        """Application facade 的 Structured aggregate 入口。"""

        return self.structured_retrieval.aggregate_messages(query)

    def rebuild_lexical_index(self) -> LexicalIndexStats:
        """显式重建 derived FTS index；导入不会静默伪装为已同步。"""

        if self._lexical_index is None:
            self._lexical_index = SQLiteLexicalIndex(self.store.database_path)
        return self._lexical_index.rebuild()

    def invoke_tool(
        self,
        name: str,
        request: SearchMessagesInput,
        scope: ExecutionScope,
    ) -> ToolEnvelope:
        """通过显式 registry 调用 agent-facing Tool。"""

        return self.capability_registry.invoke(name, request, scope)

    async def run_agent(self, request: AgentRunRequest) -> RuntimeResult:
        """通过同一 Application composition path 执行 Agent Runtime。"""

        if self._agent_runtime is None:
            # 延迟导入和构造 provider，避免应用创建阶段触发密钥校验或网络 client。
            from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

            self._agent_runtime = OpenAIAgentsRuntimeAdapter(
                capability_registry=self.capability_registry,
            )
        return await self._agent_runtime.run(request)

    def close(self) -> None:
        """集中关闭 core resource；不在模块 import 时创建全局资源。"""

        # 先释放 derived/read connections，再关闭 write store，避免生命周期交叉。
        if self._lexical_index is not None:
            self._lexical_index.close()
        self.read_repository.close()
        self.store.close()
        # 应用关闭后不再保留 runtime/provider 引用；client 生命周期不延伸到 Application 之外。
        self._agent_runtime = None

    def __enter__(self) -> TrivaeApplication:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


def create_application(
    database_path: Path,
    agent_runtime: AgentRuntime | None = None,
) -> TrivaeApplication:
    """Composition Root 统一装配 write/read/derived/retrieval/capability 组件。"""

    store = SQLiteCanonicalStore(database_path)
    importer = SharedImporter(store)
    read_repository = SQLiteCanonicalReadRepository(database_path)
    structured_retrieval = StructuredRetrieval(read_repository)
    lexical_retrieval = LexicalRetrieval(read_repository)
    search_capability = SearchMessagesCapability(lexical_retrieval)
    capability_registry = CapabilityRegistry()
    capability_registry.register(SearchMessagesTool(search_capability))
    return TrivaeApplication(
        store=store,
        importer=importer,
        read_repository=read_repository,
        structured_retrieval=structured_retrieval,
        lexical_retrieval=lexical_retrieval,
        capability_registry=capability_registry,
        agent_runtime=agent_runtime,
    )
