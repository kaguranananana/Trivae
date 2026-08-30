"""Composition Root 与 Application facade。"""

from __future__ import annotations

import inspect
import logging
import sqlite3
import uuid
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

from trivae.bootstrap.process_warmup import warm_tqdm_multiprocessing_lock
from trivae.bootstrap.status import ApplicationReadiness, ProviderReadiness
from trivae.capabilities.contracts import (
    ExecuteSQLInput,
    ExecutionScope,
    FindMembersInput,
    GetMessageContextInput,
    GetSchemaInput,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
)
from trivae.capabilities.execute_sql import ExecuteSQLCapability
from trivae.capabilities.find_members import FindMembersCapability
from trivae.capabilities.get_message_context import GetMessageContextCapability
from trivae.capabilities.get_schema import GetSchemaCapability
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.capabilities.registry import CapabilityRegistry
from trivae.capabilities.scope import scope_filters
from trivae.capabilities.search_messages import LexicalSearchCapability, SearchMessagesCapability
from trivae.capabilities.semantic_search import SemanticSearchCapability
from trivae.capabilities.tools import (
    ExecuteSQLTool,
    FindMembersTool,
    GetMessageContextTool,
    GetSchemaTool,
    LexicalSearchTool,
    RecentMessagesTool,
    SearchMessagesTool,
    SemanticSearchTool,
)
from trivae.config.settings import SettingsError, load_settings
from trivae.conversation import (
    Conversation,
    ConversationScopeError,
    ConversationScopeSelector,
    ConversationStore,
    ConversationSummary,
    SQLiteConversationStore,
    TurnProcessCollector,
)
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.model import ChatSession, ImportRunSummary
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import LexicalIndexStats, SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation import (
    BlindAnnotationPacket,
    ControlledVariant,
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationRun,
    EvaluationRunner,
    EvaluationStore,
    EvaluationSuite,
    PairedComparison,
    RetrievalAnnotationWorkflow,
    RetrievalQuerySet,
    SealedRetrievalPacket,
    SQLiteEvaluationStore,
    create_paired_comparison,
)
from trivae.feedback import FeedbackRecord, SQLiteFeedbackStore
from trivae.feedback.contracts import FeedbackError, FeedbackRating, FeedbackStore, feedback_for_query
from trivae.observability.collector import TraceCollector
from trivae.observability.contracts import (
    FailureInfo,
    ImportDiagnosticsProjection,
    TraceProjection,
    TraceStage,
    TraceStore,
)
from trivae.observability.projection import project_trace
from trivae.observability.sqlite import SQLiteImportDiagnosticsReader, SQLiteTraceStore, TraceStoreError
from trivae.observability.text import TraceTextLogError, TraceTextLogWriter, TraceTextView
from trivae.observability.transcript import TranscriptContextMode
from trivae.query.contracts import QueryContractError, QueryRequest, QueryResult
from trivae.query.evidence import MessageSource, SourceInspectionError, scope_snapshot
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import Planner, SoftPlanner
from trivae.query.router import Router, RuleRouter
from trivae.query.runtime.contracts import AgentRunRequest, AgentRuntime, RuntimeResult
from trivae.query.streaming import (
    DEFAULT_THINKING_VISIBILITY_POLICY,
    QueryStreamAdapter,
    QueryStreamEvent,
    QueryStreamEventHandler,
    ThinkingVisibilityPolicy,
)
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.semantic.builder import SemanticIndexBuilder
from trivae.retrieval.semantic.contracts import (
    EmbeddingProvider,
    SemanticBuildStats,
    SemanticError,
    SemanticIndexIntegrityReport,
    SemanticIndexStatusReport,
)
from trivae.retrieval.semantic.embedding import SentenceTransformerEmbeddingProvider
from trivae.retrieval.semantic.index import SQLiteSemanticIndex
from trivae.retrieval.semantic.retrieval import SemanticRetrieval
from trivae.retrieval.structured import (
    AggregateQuery,
    MessageProjection,
    MessageQuery,
    RetrievalError,
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
        semantic_index: SQLiteSemanticIndex | None = None,
        semantic_provider: EmbeddingProvider | None = None,
        semantic_retrieval: SemanticRetrieval | None = None,
        semantic_builder: SemanticIndexBuilder | None = None,
        agent_runtime: AgentRuntime | None = None,
        router: Router | None = None,
        planner: Planner | None = None,
        conversation_store: ConversationStore | None = None,
        trace_store: TraceStore | None = None,
        import_diagnostics_reader: SQLiteImportDiagnosticsReader | None = None,
        evaluation_store: EvaluationStore | None = None,
        evaluation_runner: EvaluationRunner | None = None,
        feedback_store: FeedbackStore | None = None,
    ) -> None:
        self.store = store
        self.importer = importer
        self.read_repository = read_repository
        self.structured_retrieval = structured_retrieval
        self.lexical_retrieval = lexical_retrieval
        self.capability_registry = capability_registry
        self.semantic_provider = semantic_provider
        self.semantic_retrieval = semantic_retrieval
        self._semantic_builder = semantic_builder
        if conversation_store is None:
            raise ValueError("conversation_store is required")
        self.conversation_store = conversation_store
        self._trace_store = SQLiteTraceStore(store.database_path) if trace_store is None else trace_store
        # 导出 facade 与 Trace Store 使用同一数据库相邻目录，保证 CLI 不直接操作文件系统语义。
        self._trace_log_writer = TraceTextLogWriter(store.database_path.parent / "traces")
        self._import_diagnostics_reader = import_diagnostics_reader or SQLiteImportDiagnosticsReader(
            store.database_path
        )
        self.evaluation_store = evaluation_store or SQLiteEvaluationStore(
            store.database_path.with_name(f"{store.database_path.stem}.evaluation.sqlite3")
        )
        self._feedback_store = feedback_store or SQLiteFeedbackStore(
            store.database_path.with_name(f"{store.database_path.stem}.feedback.sqlite3")
        )
        self._lexical_index = lexical_index
        self._semantic_index = semantic_index
        # Runtime 是可注入且惰性创建的，检索-only caller 不需要 provider 配置。
        self._agent_runtime = agent_runtime
        self._router = router
        self._planner = planner
        self._query_orchestrator: QueryOrchestrator | None = None
        self._evaluation_runner = evaluation_runner or EvaluationRunner(
            query_executor=self.query,
            trace_reader=self.read_trace,
            store=self.evaluation_store,
            database_path=store.database_path,
        )
        self._closed = False

    def import_directory(self, raw_directory: Path) -> ImportRunSummary:
        """让 CLI 通过 Application 进入 data ingestion，而不是直接读 Store。"""

        return self.importer.import_directory(raw_directory)

    def list_sessions(self) -> tuple[ChatSession, ...]:
        """通过 Application facade 读取可供接口层选择的 Canonical sessions。"""

        # 接口层不直接接触 read repository；Application 负责生命周期和边界检查。
        self._ensure_open()
        # 读取由既有只读 adapter 完成，Application 不复制 SQL 或 session projection 逻辑。
        return self.read_repository.list_sessions()

    def readiness(self) -> ApplicationReadiness:
        """读取启动所需的本地状态，不扫描重建 derived index，也不访问网络。"""

        self._ensure_open()
        database_status: Literal["ready", "unavailable"] = "ready"
        session_count: int | None = None
        message_count: int | None = None
        database_error_code: str | None = None
        database_message: str | None = None
        try:
            session_count = len(self.list_sessions())
            message_count = self.read_repository.count_messages(MessageQuery(limit=1))
        except (sqlite3.Error, RetrievalError) as exc:
            database_status = "unavailable"
            database_error_code = type(exc).__name__
            database_message = "canonical database status is unavailable"

        semantic: SemanticIndexStatusReport | None = None
        semantic_error_code: str | None = None
        semantic_message: str | None = None
        try:
            semantic = self.semantic_index_status()
        except (SemanticError, RuntimeError) as exc:
            semantic_error_code = getattr(exc, "error_code", type(exc).__name__)
            semantic_message = str(exc)

        try:
            provider = ProviderReadiness.from_settings(load_settings())
        except SettingsError as exc:
            provider = ProviderReadiness.not_configured(type(exc).__name__, str(exc))

        return ApplicationReadiness(
            database_status=database_status,
            session_count=session_count,
            message_count=message_count,
            database_error_code=database_error_code,
            database_message=database_message,
            semantic=semantic,
            semantic_error_code=semantic_error_code,
            semantic_message=semantic_message,
            provider=provider,
        )

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

    def rebuild_semantic_index(self) -> SemanticBuildStats:
        """显式重建 Qwen3 semantic derived index；模型/向量错误不会被 lexical 结果掩盖。"""

        self._ensure_open()
        if self._semantic_builder is None:
            raise RuntimeError("semantic index builder is not configured")
        return self._semantic_builder.rebuild()

    def semantic_index_status(self) -> SemanticIndexStatusReport:
        """返回当前 provider/chunker 与 derived index 的可运维状态。"""

        self._ensure_open()
        if self._semantic_builder is None or self._semantic_index is None:
            raise RuntimeError("semantic index status is not configured")
        # 当前 canonical message count 是 stale 判断的 watermark，不把 chunk 数当作覆盖范围。
        canonical_count = self.read_repository.count_messages(MessageQuery(limit=1))
        return SemanticIndexStatusReport.from_state(
            self._semantic_builder.identity,
            self._semantic_index.state(),
            canonical_count,
        )

    def validate_semantic_index(self, *, sample_size: int = 16) -> SemanticIndexIntegrityReport:
        """验证 derived rows，并从 Canonical Store 抽样恢复真实 message range。"""

        self._ensure_open()
        if self._semantic_builder is None or self._semantic_index is None:
            raise RuntimeError("semantic index validation is not configured")
        identity = self._semantic_builder.identity
        report = self._semantic_index.integrity_report(identity, sample_size=sample_size)
        ranges = self._semantic_index.sample_ranges(identity, sample_size=sample_size)
        recovered = 0
        invalid = 0
        for item in ranges:
            messages = self.read_repository.read_message_range(
                item.session_id,
                item.start_message_id,
                item.end_message_id,
                item.message_count,
            )
            # 长度、session 与首尾 locator 必须同时匹配，避免“能读到一些消息”被误报为成功。
            matches = (
                len(messages) == item.message_count
                and bool(messages)
                and all(message.session_id == item.session_id for message in messages)
                and messages[0].internal_message_id == item.start_message_id
                and messages[-1].internal_message_id == item.end_message_id
            )
            if matches:
                recovered += 1
            else:
                invalid += 1
        status: Literal["valid", "invalid"] = (
            "valid" if report.status == "valid" and invalid == 0 else "invalid"
        )
        return replace(
            report,
            status=status,
            sampled_range_count=len(ranges),
            recovered_range_count=recovered,
            invalid_range_count=invalid,
        )

    def materialize_evaluation_snapshot(self) -> DatasetSnapshot:
        """通过 Application facade 生成不含聊天正文的当前 Canonical Snapshot。"""

        self._ensure_open()
        # Snapshot contract 自己使用 read-only connection；Application 不复制其 SQL 语义。
        return DatasetSnapshot.from_database(self.store.database_path)

    def generate_retrieval_annotation_packet(
        self,
        query_set: RetrievalQuerySet,
        lexical_variant: ControlledVariant,
        semantic_variant: ControlledVariant,
    ) -> tuple[BlindAnnotationPacket, SealedRetrievalPacket]:
        """通过 Tool facade 运行 paired retrieval，并生成分离的 blind/sealed packet。"""

        self._ensure_open()
        workflow = RetrievalAnnotationWorkflow(
            snapshot_resolver=self.materialize_evaluation_snapshot,
            tool_invoker=self.invoke_tool,
            context_reader=self.read_repository.read_message_context,
            range_reader=self.read_repository.read_message_range,
        )
        return workflow.generate(query_set, lexical_variant, semantic_variant)

    def invoke_tool(
        self,
        name: str,
        request: (
            SearchMessagesInput
            | SemanticSearchInput
            | GetMessageContextInput
            | FindMembersInput
            | GetSchemaInput
            | ExecuteSQLInput
        ),
        scope: ExecutionScope,
    ) -> ToolEnvelope:
        """通过显式 registry 调用 agent-facing Tool。"""

        return self.capability_registry.invoke(name, request, scope)

    def create_conversation(self, scope: ExecutionScope | None = None) -> Conversation:
        """通过 Application facade 创建带 trusted scope 的 Conversation。"""

        self._ensure_open()
        return self.conversation_store.create_conversation(scope)

    def read_conversation(self, conversation_id: str) -> Conversation:
        """读取可 replay 的 User/Assistant 历史及结构化 AnswerArtifact。"""

        self._ensure_open()
        return self.conversation_store.get_conversation(conversation_id)

    def list_conversations(
        self,
        limit: int = 20,
        selector: ConversationScopeSelector | None = None,
    ) -> tuple[ConversationSummary, ...]:
        """通过 Application facade 读取 bounded conversation history metadata。

        ``selector`` 原样透传给 Conversation Store；scope 匹配逻辑只存在于 Store
        的 SQL predicate，Application 不复制第二份过滤实现。
        """

        self._ensure_open()
        return self.conversation_store.list_summaries(limit, selector=selector)

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        """通过 Application facade 显式 rename 一个 AI conversation。"""

        self._ensure_open()
        return self.conversation_store.rename_conversation(conversation_id, title)

    def delete_conversation(self, conversation_id: str) -> None:
        """删除 AI conversation 聚合；canonical chat 数据不受影响。"""

        self._ensure_open()
        self.conversation_store.delete_conversation(conversation_id)

    def resume_conversation(self, conversation_id: str) -> Conversation:
        """恢复带有明确 scope contract 的 Conversation，拒绝猜测旧权限。"""

        conversation = self.read_conversation(conversation_id)
        if conversation.scope is None:
            raise ConversationScopeError(
                "conversation scope metadata is unavailable; this conversation cannot be resumed"
            )
        return conversation

    def save_feedback(
        self,
        *,
        conversation_id: str,
        trace_id: str,
        run_id: str | None,
        scope: ExecutionScope,
        rating: FeedbackRating,
        note: str | None = None,
    ) -> FeedbackRecord:
        """将 good/bad 保存到独立反馈 Store，不进入 Evaluation Ground Truth。"""

        self._ensure_open()
        if run_id is None or not run_id:
            raise FeedbackError("feedback requires a completed runtime run identity")
        try:
            trace = self.read_trace(trace_id)
        except TraceStoreError as exc:
            raise FeedbackError("feedback trace is unavailable") from exc
        if trace.terminal_status != "completed":
            raise FeedbackError("feedback requires a completed query trace")
        context_events = tuple(
            event
            for event in trace.timeline
            if event.operation == "context.prepared"
        )
        if not any(event.payload.get("conversation_id") == conversation_id for event in context_events):
            raise FeedbackError("feedback trace does not belong to the conversation")
        trace_run_ids = {
            event.payload.get("run_id")
            for event in trace.timeline
            if isinstance(event.payload.get("run_id"), str)
        }
        if run_id not in trace_run_ids:
            raise FeedbackError("feedback run identity does not match the trace")
        conversation = self.read_conversation(conversation_id)
        if conversation.scope is None:
            raise ConversationScopeError(
                "feedback cannot be bound because conversation scope metadata is unavailable"
            )
        if conversation.scope != scope:
            raise ConversationScopeError("feedback scope does not match the conversation scope")
        pending = feedback_for_query(
            conversation_id=conversation_id,
            trace_id=trace_id,
            run_id=run_id,
            scope=scope,
            rating=rating,
            note=note,
        )
        return self._feedback_store.save(pending)

    def read_feedback(self, conversation_id: str, trace_id: str) -> FeedbackRecord | None:
        """读取当前 Query 的用户体验反馈。"""

        self._ensure_open()
        return self._feedback_store.get(conversation_id, trace_id)

    def inspect_message_source(
        self,
        source: MessageSource,
        scope: ExecutionScope,
        *,
        before: int = 2,
        after: int = 2,
    ) -> tuple[MessageProjection, ...]:
        """在 trusted scope 内重新读取来源及 bounded 上下文，绝不依赖 Answer 快照正文。"""

        self._ensure_open()
        if not isinstance(source, MessageSource):
            raise SourceInspectionError("source inspection requires a message source")
        if source.snapshot is None:
            raise SourceInspectionError("message source has no trusted display snapshot")
        if scope.allowed_session_ids is not None and source.session_id not in scope.allowed_session_ids:
            raise SourceInspectionError("message source is outside the current scope")

        # 来源查看复用 canonical read adapter，并由同一个 scope_filters 编译边界。
        try:
            messages = self.read_repository.read_message_context_scoped(
                source.session_id,
                source.internal_message_id,
                before,
                after,
                scope_filters(scope),
            )
        except RetrievalError as exc:
            # 读取失败保留明确的来源查看语义，调用方仍可看到原始异常作为 cause。
            raise SourceInspectionError("canonical source context is unavailable") from exc

        if not messages or not any(message.internal_message_id == source.internal_message_id for message in messages):
            raise SourceInspectionError("canonical source context does not contain the cited message")
        if any(message.session_id != source.session_id for message in messages):
            raise SourceInspectionError("canonical source context crossed the conversation boundary")
        return messages

    def read_trace(self, trace_id: str) -> TraceProjection:
        """从 Application facade 读取 deterministic Trace projection，不暴露 raw SQL。"""

        self._ensure_open()
        return project_trace(self._trace_store.read_trace(trace_id))

    def export_trace_log(
        self,
        trace_id: str,
        *,
        output_path: Path | None = None,
        view: TraceTextView = "transcript",
        context_mode: TranscriptContextMode = "delta",
    ) -> Path:
        """从既有 Trace 事实生成可直接打开的纯文本日志。"""

        self._ensure_open()
        # 先读取 canonical StoredTrace，再交给 observability writer 做纯 projection。
        stored_trace = self._trace_store.read_trace(trace_id)
        try:
            return self._trace_log_writer.export(
                stored_trace,
                output_path=output_path,
                view=view,
                context_mode=context_mode,
            )
        except TraceTextLogError as exc:
            # Application 向 CLI 暴露稳定 TraceStoreError，而不是泄漏 writer 实现类型。
            raise TraceStoreError("trace text log export failed") from exc

    async def evaluate_case(
        self,
        case: EvaluationCaseBundle,
        variant: ControlledVariant,
        *,
        repetitions: int = 1,
    ) -> tuple[EvaluationRun, ...]:
        """Evaluation 只通过 Application facade 调用生产 QueryOrchestrator。"""

        self._ensure_open()
        return await self._evaluation_runner.run_case(case, variant, repetitions=repetitions)

    async def evaluate_suite(
        self,
        suite: EvaluationSuite,
        cases: dict[str, EvaluationCaseBundle],
        variant: ControlledVariant,
        *,
        repetitions: int = 1,
    ) -> tuple[EvaluationRun, ...]:
        """Suite orchestration 复用同一个 Runner，不复制业务执行链。"""

        self._ensure_open()
        return await self._evaluation_runner.run_suite(suite, cases, variant, repetitions=repetitions)

    def read_evaluation_run(self, run_id: str) -> EvaluationRun:
        """读取 Evaluation Store 中的单次 Run，不重新执行 Query。"""

        self._ensure_open()
        get_run = getattr(self.evaluation_store, "get_run", None)
        if not callable(get_run):
            raise RuntimeError("configured evaluation store cannot read runs")
        return get_run(run_id)

    def compare_evaluation_runs(
        self,
        case: EvaluationCaseBundle,
        baseline_variant: ControlledVariant,
        candidate_variant: ControlledVariant,
        baseline_run_ids: tuple[str, ...],
        candidate_run_ids: tuple[str, ...],
        *,
        randomization_seed: str | None = None,
    ) -> PairedComparison:
        """在 Application 边界验证 Run 后持久化 blind PairedComparison。"""

        self._ensure_open()
        get_run = getattr(self.evaluation_store, "get_run", None)
        if not callable(get_run):
            raise RuntimeError("configured evaluation store cannot read runs")
        baseline_runs = tuple(get_run(run_id) for run_id in baseline_run_ids)
        candidate_runs = tuple(get_run(run_id) for run_id in candidate_run_ids)
        comparison = create_paired_comparison(
            case=case,
            baseline_variant=baseline_variant,
            candidate_variant=candidate_variant,
            baseline_runs=baseline_runs,
            candidate_runs=candidate_runs,
            randomization_seed=randomization_seed,
        )
        self.evaluation_store.save_comparison(comparison)
        return comparison

    def read_import_diagnostics(
        self,
        *,
        source_file: str | None = None,
        batch_id: str | None = None,
    ) -> ImportDiagnosticsProjection:
        """读取既有 ImportBatch/ImportError 事实的诊断 projection。"""

        self._ensure_open()
        return self._import_diagnostics_reader.read(source_file=source_file, batch_id=batch_id)

    async def run_agent(self, request: AgentRunRequest) -> RuntimeResult:
        """通过同一 Application composition path 执行 Agent Runtime。"""

        self._ensure_open()
        return await self._get_agent_runtime().run(request)

    async def query(
        self,
        request: QueryRequest,
        *,
        on_event: QueryStreamEventHandler | None = None,
        abort_event: object | None = None,
        thinking_visibility_policy: Collection[str] | None = None,
        provisional_answer_streaming: bool = False,
    ) -> QueryResult:
        """Query 的正式 Application 入口，standard/planned 共享同一 runtime。

        ``abort_event`` 是可选优雅取消信号；提供 is_set()/wait() 的对象即可，
        终态为 aborted。``thinking_visibility_policy`` 控制哪些 provider reasoning
        delta 进入实时事件（默认保持 CLI/TUI 的 public_summary 保守行为）。
        """

        self._ensure_open()
        request_id = request.request_id or f"request-{uuid.uuid4().hex}"
        trace_id = f"trace-{uuid.uuid4().hex}"
        traced_request = replace(request, request_id=request_id)
        # 过程摘要收集与 live streaming 共用同一个 adapter 事件流；两个消费者互不影响顺序。
        process_collector = TurnProcessCollector()
        user_handler = on_event

        def dispatch_stream_event(event: QueryStreamEvent) -> None:
            """单一分发点：先持久化事实收集，再通知 interface handler。"""

            process_collector.handle(event)
            if user_handler is not None:
                user_handler(event)

        # 一个 adapter 同时消费 normalized facts 与 Runtime delta，并独立分配 Query live sequence。
        stream_adapter = QueryStreamAdapter(
            dispatch_stream_event,
            trace_id=trace_id,
            thinking_visibility_policy=self._resolve_thinking_policy(thinking_visibility_policy),
            provisional_answer_streaming=provisional_answer_streaming,
        )
        trace = TraceCollector(
            self._trace_store,
            trace_id=trace_id,
            request_id=request_id,
            profile=request.trace_profile,
            event_observer=(
                stream_adapter.handle_normalized_event
            ),
        )
        trace.emit(
            stage="query",
            operation="query.received",
            phase="started",
            operation_id="query",
            payload={
                "query": request.query,
                "conversation_id": request.conversation_id,
                "trace_profile": request.trace_profile,
                # Scope/override 是 Evaluation identity；这里仅记录 trusted contract 快照。
                "scope": scope_snapshot(traced_request.scope),
                "execution_override": traced_request.execution_override.to_dict(),
            },
        )
        terminal_emitted = False
        try:
            conversation = self._conversation_for_request(traced_request)
            effective_request = traced_request
            if traced_request.conversation_id is not None:
                # 有持久化 conversation 时，Store 是 history source of truth，拒绝混入手工历史。
                if traced_request.prior_context:
                    raise QueryContractError(
                        "prior_context cannot be combined with a persisted conversation_id"
                    )
                effective_request = replace(traced_request, prior_context=conversation.to_model_context())
            trace.emit(
                stage="context",
                operation="context.prepared",
                phase="completed",
                operation_id="context",
                parent_operation_id="query",
                outcome="ok",
                payload={
                    "conversation_id": conversation.conversation_id,
                    "prior_context_count": len(effective_request.prior_context),
                },
            )
            runtime = self._get_agent_runtime()
            if self._query_orchestrator is None:
                # Router 仍只需要文本；Planner 优先使用同一 runtime 提供的 metadata-aware boundary。
                completion = getattr(runtime, "complete_text", None)
                if not callable(completion):
                    completion = None
                planner_completion = getattr(runtime, "complete_text_with_observation", None)
                if not callable(planner_completion):
                    planner_completion = completion
                completion_request = getattr(runtime, "completion_request_projection", None)
                planner_request = completion_request() if callable(completion_request) else None
                # 两个 optional completion 仍共享同一 provider/runtime，不创建第二个 Planner client。
                self._router = self._router or RuleRouter(completion=completion)
                self._planner = self._planner or SoftPlanner(
                    completion=planner_completion,
                    completion_request=planner_request,
                )
                self._query_orchestrator = QueryOrchestrator(
                    runtime,
                    self._router,
                    self._planner,
                    capability_names=self.capability_registry.names(),
                )
            result = await self._query_orchestrator.run(
                effective_request,
                trace=trace,
                runtime_event_observer=(
                    stream_adapter.handle_runtime_event
                ),
                abort_event=abort_event,
            )
            artifact = result.answer_artifact
            if result.is_successful:
                if artifact is None:
                    # QueryResult contract 若出现不一致必须显式暴露，不能伪造持久化成功。
                    raise RuntimeError("successful query is missing its validated answer artifact")
                trace.emit(
                    stage="conversation",
                    operation="answer.commit.started",
                    phase="started",
                    operation_id="conversation.commit",
                    parent_operation_id="query",
                    payload={"conversation_id": conversation.conversation_id},
                )
                try:
                    self.conversation_store.commit_turn(
                        conversation.conversation_id,
                        request.query,
                        artifact,
                        trace_id=trace.trace_id,
                        process_projection=process_collector.to_projection(),
                    )
                except Exception as exc:
                    trace.emit(
                        stage="conversation",
                        operation="answer.commit.failed",
                        phase="failed",
                        operation_id="conversation.commit",
                        parent_operation_id="query",
                        outcome="error",
                        payload={"exception_type": type(exc).__name__},
                        failure=FailureInfo(
                            error_code="CONVERSATION_COMMIT_FAILED",
                            origin_stage="conversation",
                            observed_stage="conversation",
                            category="persistence",
                            handling="propagated",
                            cause_operation_id="conversation.commit",
                            diagnostic_reference=type(exc).__name__,
                        ),
                    )
                    trace.emit(
                        stage="query",
                        operation="query.failed",
                        phase="failed",
                        operation_id="query",
                        outcome="error",
                        payload={
                            "error_code": "CONVERSATION_COMMIT_FAILED",
                            "error_message": "conversation commit failed",
                        },
                        failure=FailureInfo(
                            error_code="CONVERSATION_COMMIT_FAILED",
                            origin_stage="conversation",
                            observed_stage="query",
                            category="persistence",
                            handling="propagated",
                            cause_operation_id="conversation.commit",
                        ),
                    )
                    terminal_emitted = True
                    logging.getLogger(__name__).error(
                        "QUERY_COMMIT_FAILED trace_id=%s request_id=%s exception_type=%s",
                        trace.trace_id,
                        trace.request_id,
                        type(exc).__name__,
                    )
                    setattr(exc, "trace_id", trace.trace_id)
                    raise
                trace.emit(
                    stage="conversation",
                    operation="answer.commit.completed",
                    phase="completed",
                    operation_id="conversation.commit",
                    parent_operation_id="query",
                    outcome="ok",
                    payload={"conversation_id": conversation.conversation_id},
                )
                trace.emit(
                    stage="query",
                    operation="query.completed",
                    phase="completed",
                    operation_id="query",
                    outcome="partial" if result.is_degraded else "ok",
                    payload={
                        "conversation_id": conversation.conversation_id,
                        "execution_status": result.execution_status,
                        "finalization_status": result.finalization_status,
                        "finalization_diagnostics": (
                            None
                            if result.finalization_diagnostics is None
                            else result.finalization_diagnostics.to_dict()
                        ),
                    },
                )
                terminal_emitted = True
            else:
                is_aborted = result.termination == "aborted"
                error_code = (
                    result.finalization_error.code
                    if result.finalization_error is not None
                    else result.runtime_result.error.code
                    if result.runtime_result.error is not None
                    else "QUERY_NOT_COMPLETED"
                )
                origin_stage: TraceStage = (
                    "citation"
                    if result.finalization_error is not None
                    else "runtime"
                )
                error_message = (
                    result.finalization_error.message
                    if result.finalization_error is not None
                    else result.runtime_result.error.message
                    if result.runtime_result.error is not None
                    else "query did not complete"
                )
                trace.emit(
                    stage="query",
                    operation="query.aborted" if is_aborted else "query.failed",
                    phase="aborted" if is_aborted else "failed",
                    operation_id="query",
                    outcome="aborted" if is_aborted else "error",
                    payload={
                        "termination": result.termination,
                        "error_code": error_code,
                        # Finalizer/Runtime message 已是 Trivae-owned secret-safe contract。
                        "error_message": error_message,
                    },
                    failure=FailureInfo(
                        error_code=error_code,
                        origin_stage=origin_stage,
                        observed_stage="query",
                        category="cancellation" if is_aborted else "query_terminal",
                        handling="returned_to_caller",
                        cause_operation_id="runtime.run" if origin_stage == "runtime" else "answer.finalization",
                    ),
                )
                terminal_emitted = True
            return replace(result, conversation_id=conversation.conversation_id, trace_id=trace.trace_id)
        except Exception as exc:
            if not terminal_emitted:
                trace.emit(
                    stage="query",
                    operation="query.failed",
                    phase="failed",
                    operation_id="query",
                    outcome="error",
                    payload={
                        "exception_type": type(exc).__name__,
                        "error_code": "QUERY_EXCEPTION",
                        "error_message": "query execution failed",
                    },
                    failure=FailureInfo(
                        error_code="QUERY_EXCEPTION",
                        origin_stage="query",
                        observed_stage="query",
                        category="exception",
                        handling="propagated",
                        cause_operation_id="query",
                        diagnostic_reference=type(exc).__name__,
                    ),
                )
            setattr(exc, "trace_id", trace.trace_id)
            raise

    @staticmethod
    def _resolve_thinking_policy(
        thinking_visibility_policy: Collection[str] | None,
    ) -> "ThinkingVisibilityPolicy":
        """校验可见性策略取值；未知值显式失败，不静默丢弃。"""

        if thinking_visibility_policy is None:
            return DEFAULT_THINKING_VISIBILITY_POLICY
        values = tuple(thinking_visibility_policy)
        allowed = {"public_summary", "provider_reasoning"}
        invalid = sorted(set(values) - allowed)
        if invalid:
            raise QueryContractError(f"unknown thinking visibility values: {invalid}")
        return cast("ThinkingVisibilityPolicy", frozenset(values))

    def _conversation_for_request(self, request: QueryRequest) -> Conversation:
        """解析 conversation identity，并拒绝跨 scope 复用持久化历史。"""

        if request.conversation_id is None:
            return self.create_conversation(request.scope)
        conversation = self.read_conversation(request.conversation_id)
        if conversation.scope is None:
            raise QueryContractError(
                "conversation scope metadata is unavailable; start a new conversation"
            )
        if conversation.scope != request.scope:
            raise QueryContractError("conversation scope does not match the current trusted scope")
        return conversation

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
                        if self._semantic_index is not None:
                            self._semantic_index.close()
                    finally:
                        try:
                            self.conversation_store.close()
                        finally:
                            try:
                                self.read_repository.close()
                            finally:
                                try:
                                    self._import_diagnostics_reader.close()
                                finally:
                                    try:
                                        close_trace_store = getattr(self._trace_store, "close", None)
                                        if callable(close_trace_store):
                                            close_trace_store()
                                    finally:
                                        try:
                                            close_evaluation_store = getattr(self.evaluation_store, "close", None)
                                            if callable(close_evaluation_store):
                                                close_evaluation_store()
                                        finally:
                                            try:
                                                close_feedback_store = getattr(self._feedback_store, "close", None)
                                                if callable(close_feedback_store):
                                                    close_feedback_store()
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
    trace_store: TraceStore | None = None,
    conversation_store: ConversationStore | None = None,
    evaluation_database_path: Path | None = None,
    evaluation_store: EvaluationStore | None = None,
    feedback_database_path: Path | None = None,
    feedback_store: FeedbackStore | None = None,
    semantic_index_path: Path | None = None,
    semantic_index: SQLiteSemanticIndex | None = None,
    semantic_provider: EmbeddingProvider | None = None,
) -> TrivaeApplication:
    """Composition Root 统一装配 write/read/derived/retrieval/capability 组件。"""

    # 在 stdio 仍是真实终端的阶段预热 tqdm multiprocessing lock：
    # 所有 CLI 命令路径共用本工厂，而 chat 的 TUI 分支在 TrivaeChatApp.run()
    # 中才会把 sys.stderr 替换成 _PrintCapture(fileno()==-1)；提前建锁使后续
    # 嵌入模型加载不再触发 CPython 3.14 resource_tracker 的坏 fd 缺陷窗口。
    warm_tqdm_multiprocessing_lock()
    resolved_database_path = database_path.resolve()
    resolved_semantic_path = (
        semantic_index_path or database_path.with_name(f"{database_path.stem}.semantic.sqlite3")
    ).resolve()
    if resolved_semantic_path == resolved_database_path:
        raise ValueError("semantic index must use a separate database path")
    if semantic_index is not None and semantic_index.database_path.resolve() == resolved_database_path:
        raise ValueError("semantic index must use a separate database path")

    store = SQLiteCanonicalStore(database_path)
    importer = SharedImporter(store)
    read_repository = SQLiteCanonicalReadRepository(database_path)
    structured_retrieval = StructuredRetrieval(read_repository)
    lexical_retrieval = LexicalRetrieval(read_repository)
    search_capability = SearchMessagesCapability(lexical_retrieval)
    lexical_capability = LexicalSearchCapability(lexical_retrieval)
    owned_semantic_provider = semantic_provider or SentenceTransformerEmbeddingProvider()
    if semantic_index is None:
        owned_semantic_index = SQLiteSemanticIndex(resolved_semantic_path)
    else:
        owned_semantic_index = semantic_index
    database_identity = database_path.name
    semantic_builder = SemanticIndexBuilder(
        read_repository,
        owned_semantic_index,
        owned_semantic_provider,
        database_identity=database_identity,
    )
    semantic_retrieval = SemanticRetrieval(
        read_repository,
        owned_semantic_index,
        owned_semantic_provider,
        database_identity=database_identity,
    )
    capability_registry = CapabilityRegistry()
    capability_registry.register(SearchMessagesTool(search_capability))
    capability_registry.register(LexicalSearchTool(lexical_capability))
    capability_registry.register(SemanticSearchTool(SemanticSearchCapability(semantic_retrieval)))
    capability_registry.register(RecentMessagesTool(RecentMessagesCapability(structured_retrieval)))
    capability_registry.register(GetMessageContextTool(GetMessageContextCapability(read_repository)))
    capability_registry.register(FindMembersTool(FindMembersCapability(read_repository)))
    # Stage C 继续复用同一个 canonical read adapter；SQL Tool 不建立第二套查询管线。
    capability_registry.register(GetSchemaTool(GetSchemaCapability(read_repository)))
    capability_registry.register(ExecuteSQLTool(ExecuteSQLCapability(read_repository)))
    owned_conversation_store = (
        SQLiteConversationStore(database_path) if conversation_store is None else conversation_store
    )
    owned_evaluation_store = evaluation_store or SQLiteEvaluationStore(
        evaluation_database_path
        or database_path.with_name(f"{database_path.stem}.evaluation.sqlite3")
    )
    owned_feedback_store = feedback_store or SQLiteFeedbackStore(
        feedback_database_path
        or database_path.with_name(f"{database_path.stem}.feedback.sqlite3")
    )
    return TrivaeApplication(
        store=store,
        importer=importer,
        read_repository=read_repository,
        structured_retrieval=structured_retrieval,
        lexical_retrieval=lexical_retrieval,
        capability_registry=capability_registry,
        semantic_index=owned_semantic_index,
        semantic_provider=owned_semantic_provider,
        semantic_retrieval=semantic_retrieval,
        semantic_builder=semantic_builder,
        conversation_store=owned_conversation_store,
        agent_runtime=agent_runtime,
        router=router,
        planner=planner,
        trace_store=trace_store,
        evaluation_store=owned_evaluation_store,
        feedback_store=owned_feedback_store,
    )
