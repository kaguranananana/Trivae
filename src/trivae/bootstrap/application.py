"""Composition Root 与 Application facade。"""

from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path

from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput, ToolEnvelope
from trivae.capabilities.registry import CapabilityRegistry
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.capabilities.tools import SearchMessagesTool
from trivae.conversation import Conversation, ConversationStore, SQLiteConversationStore
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.model import ImportRunSummary
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import LexicalIndexStats, SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.contracts import QueryContractError, QueryRequest, QueryResult
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import Planner, SoftPlanner
from trivae.query.router import Router, RuleRouter
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
        router: Router | None = None,
        planner: Planner | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self.store = store
        self.importer = importer
        self.read_repository = read_repository
        self.structured_retrieval = structured_retrieval
        self.lexical_retrieval = lexical_retrieval
        self.capability_registry = capability_registry
        if conversation_store is None:
            raise ValueError("conversation_store is required")
        self.conversation_store = conversation_store
        self._lexical_index = lexical_index
        # Runtime 是可注入且惰性创建的，检索-only caller 不需要 provider 配置。
        self._agent_runtime = agent_runtime
        self._router = router
        self._planner = planner
        self._query_orchestrator: QueryOrchestrator | None = None
        self._closed = False

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

    def create_conversation(self) -> Conversation:
        """通过 Application facade 创建 Conversation，不让接口层直接访问 Store。"""

        self._ensure_open()
        return self.conversation_store.create_conversation()

    def read_conversation(self, conversation_id: str) -> Conversation:
        """读取可 replay 的 User/Assistant 历史及结构化 AnswerArtifact。"""

        self._ensure_open()
        return self.conversation_store.get_conversation(conversation_id)

    async def run_agent(self, request: AgentRunRequest) -> RuntimeResult:
        """通过同一 Application composition path 执行 Agent Runtime。"""

        self._ensure_open()
        return await self._get_agent_runtime().run(request)

    async def query(self, request: QueryRequest) -> QueryResult:
        """Query 的正式 Application 入口，standard/planned 共享同一 runtime。"""

        self._ensure_open()
        conversation = self._conversation_for_request(request)
        effective_request = request
        if request.conversation_id is not None:
            # 有持久化 conversation 时，Store 是 history source of truth，拒绝混入手工历史。
            if request.prior_context:
                raise QueryContractError(
                    "prior_context cannot be combined with a persisted conversation_id"
                )
            effective_request = replace(request, prior_context=conversation.to_model_context())
        runtime = self._get_agent_runtime()
        if self._query_orchestrator is None:
            completion = getattr(runtime, "complete_text", None)
            if not callable(completion):
                completion = None
            self._router = self._router or RuleRouter(completion=completion)
            self._planner = self._planner or SoftPlanner(completion=completion)
            self._query_orchestrator = QueryOrchestrator(
                runtime,
                self._router,
                self._planner,
                capability_names=self.capability_registry.names(),
            )
        result = await self._query_orchestrator.run(effective_request)
        artifact = result.answer_artifact
        if result.is_successful:
            if artifact is None:
                # QueryResult contract 若出现不一致必须显式暴露，不能伪造持久化成功。
                raise RuntimeError("successful query is missing its validated answer artifact")
            self.conversation_store.commit_turn(conversation.conversation_id, request.query, artifact)
        return replace(result, conversation_id=conversation.conversation_id)

    def _conversation_for_request(self, request: QueryRequest) -> Conversation:
        """解析 Query 的 conversation identity；无 id 时创建空 conversation。"""

        if request.conversation_id is None:
            return self.create_conversation()
        return self.read_conversation(request.conversation_id)

    def _get_agent_runtime(self) -> AgentRuntime:
        """惰性构造 provider runtime，保持检索-only Application 无 provider 依赖。"""

        if self._agent_runtime is None:
            # 延迟导入和构造 provider，避免应用创建阶段触发密钥校验或网络 client。
            from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

            self._agent_runtime = OpenAIAgentsRuntimeAdapter(
                capability_registry=self.capability_registry,
            )
        return self._agent_runtime

    def _ensure_open(self) -> None:
        """关闭后的 Application 不能静默重建资源或继续发起请求。"""

        if self._closed:
            raise RuntimeError("application is closed")

    async def aclose(self) -> None:
        """先关闭 runtime/provider，再关闭 data resources；重复调用安全且无副作用。"""

        if self._closed:
            return
        self._closed = True
        runtime = self._agent_runtime
        try:
            if runtime is not None:
                close = getattr(runtime, "aclose", None)
                if callable(close):
                    result = close()
                    if inspect.isawaitable(result):
                        await result
        finally:
            # 即使某一个 close 失败，也继续释放其余资源；原始 close 异常最终仍会向上暴露。
            try:
                try:
                    if self._lexical_index is not None:
                        self._lexical_index.close()
                finally:
                    try:
                        self.conversation_store.close()
                    finally:
                        try:
                            self.read_repository.close()
                        finally:
                            self.store.close()
            finally:
                self._agent_runtime = None
                self._query_orchestrator = None

    def close(self) -> None:
        """同步 lifecycle 包装；运行中的 event loop 必须显式使用 await aclose。"""

        try:
            import asyncio

            asyncio.get_running_loop()
        except RuntimeError:
            import asyncio

            asyncio.run(self.aclose())
            return
        raise RuntimeError("application.close() cannot run inside an event loop; use await aclose()")

    def __enter__(self) -> TrivaeApplication:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    async def __aenter__(self) -> TrivaeApplication:
        self._ensure_open()
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.aclose()


def create_application(
    database_path: Path,
    agent_runtime: AgentRuntime | None = None,
    *,
    router: Router | None = None,
    planner: Planner | None = None,
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
    conversation_store = SQLiteConversationStore(database_path)
    return TrivaeApplication(
        store=store,
        importer=importer,
        read_repository=read_repository,
        structured_retrieval=structured_retrieval,
        lexical_retrieval=lexical_retrieval,
        capability_registry=capability_registry,
        conversation_store=conversation_store,
        agent_runtime=agent_runtime,
        router=router,
        planner=planner,
    )
