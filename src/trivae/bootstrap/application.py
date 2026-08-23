"""Composition Root 与 Application facade。"""

from __future__ import annotations

import inspect
import logging
import uuid
from dataclasses import replace
from pathlib import Path

from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput, ToolEnvelope
from trivae.capabilities.registry import CapabilityRegistry
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.capabilities.tools import SearchMessagesTool
from trivae.conversation import Conversation, ConversationStore, SQLiteConversationStore
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.model import ChatSession, ImportRunSummary
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import LexicalIndexStats, SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation import (
    ControlledVariant,
    EvaluationCaseBundle,
    EvaluationRun,
    EvaluationRunner,
    EvaluationStore,
    EvaluationSuite,
    PairedComparison,
    SQLiteEvaluationStore,
    create_paired_comparison,
)
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
from trivae.query.evidence import scope_snapshot
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import Planner, SoftPlanner
from trivae.query.router import Router, RuleRouter
from trivae.query.runtime.contracts import AgentRunRequest, AgentRuntime, RuntimeResult
from trivae.query.streaming import QueryStreamAdapter, QueryStreamEventHandler
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
        trace_store: TraceStore | None = None,
        import_diagnostics_reader: SQLiteImportDiagnosticsReader | None = None,
        evaluation_store: EvaluationStore | None = None,
        evaluation_runner: EvaluationRunner | None = None,
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
        self._trace_store = SQLiteTraceStore(store.database_path) if trace_store is None else trace_store
        # 导出 facade 与 Trace Store 使用同一数据库相邻目录，保证 CLI 不直接操作文件系统语义。
        self._trace_log_writer = TraceTextLogWriter(store.database_path.parent / "traces")
        self._import_diagnostics_reader = import_diagnostics_reader or SQLiteImportDiagnosticsReader(
            store.database_path
        )
        self.evaluation_store = evaluation_store or SQLiteEvaluationStore(
            store.database_path.with_name(f"{store.database_path.stem}.evaluation.sqlite3")
        )
        self._lexical_index = lexical_index
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
    ) -> QueryResult:
        """Query 的正式 Application 入口，standard/planned 共享同一 runtime。"""

        self._ensure_open()
        request_id = request.request_id or f"request-{uuid.uuid4().hex}"
        trace_id = f"trace-{uuid.uuid4().hex}"
        traced_request = replace(request, request_id=request_id)
        # 一个 adapter 同时消费 normalized facts 与 Runtime delta，并独立分配 Query live sequence。
        stream_adapter = None if on_event is None else QueryStreamAdapter(on_event, trace_id=trace_id)
        trace = TraceCollector(
            self._trace_store,
            trace_id=trace_id,
            request_id=request_id,
            profile=request.trace_profile,
            event_observer=(
                None if stream_adapter is None else stream_adapter.handle_normalized_event
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
                    None if stream_adapter is None else stream_adapter.handle_runtime_event
                ),
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
                    self.conversation_store.commit_turn(conversation.conversation_id, request.query, artifact)
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
                    outcome="ok",
                    payload={"conversation_id": conversation.conversation_id},
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
    owned_conversation_store = (
        SQLiteConversationStore(database_path) if conversation_store is None else conversation_store
    )
    owned_evaluation_store = evaluation_store or SQLiteEvaluationStore(
        evaluation_database_path
        or database_path.with_name(f"{database_path.stem}.evaluation.sqlite3")
    )
    return TrivaeApplication(
        store=store,
        importer=importer,
        read_repository=read_repository,
        structured_retrieval=structured_retrieval,
        lexical_retrieval=lexical_retrieval,
        capability_registry=capability_registry,
        conversation_store=owned_conversation_store,
        agent_runtime=agent_runtime,
        router=router,
        planner=planner,
        trace_store=trace_store,
        evaluation_store=owned_evaluation_store,
    )
