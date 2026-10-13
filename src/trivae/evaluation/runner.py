"""Evaluation Runner：只编排输入、生产 Query 调用、Trace 读取和持久化。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Awaitable, Callable, Mapping, cast

from trivae.observability.contracts import TraceProfile, TraceProjection
from trivae.query.completion import CompletionProviderError
from trivae.query.contracts import QueryRequest, QueryResult
from trivae.query.evidence import scope_snapshot

from .checks import (
    build_evaluation_result,
    operational_measurements,
    query_result_snapshot,
    run_deterministic_checks,
)
from .contracts import (
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationRun,
    EvaluationSuite,
    scope_identity,
    utc_now,
)
from .store import EvaluationStore
from .variant import ControlledVariant

QueryExecutor = Callable[[QueryRequest], Awaitable[QueryResult]]
TraceReader = Callable[[str], TraceProjection]
SnapshotResolver = Callable[[], DatasetSnapshot]


class EvaluationRunner:
    """通过 Application-level callable 执行 Evaluation，不拥有 Runtime/Router 实例。"""

    def __init__(
        self,
        *,
        query_executor: QueryExecutor,
        trace_reader: TraceReader,
        store: EvaluationStore,
        database_path: Path | None = None,
        snapshot_resolver: SnapshotResolver | None = None,
    ) -> None:
        if not callable(query_executor) or not callable(trace_reader):
            raise EvaluationContractError("EvaluationRunner requires query_executor and trace_reader")
        if database_path is None and snapshot_resolver is None:
            raise EvaluationContractError("EvaluationRunner requires database_path or snapshot_resolver")
        self._query_executor = query_executor
        self._trace_reader = trace_reader
        self._store = store
        self._database_path = database_path
        self._snapshot_resolver = snapshot_resolver

    def resolve_snapshot(self, case: EvaluationCaseBundle) -> DatasetSnapshot:
        """解析当前 Canonical DB，并拒绝 Case 指向漂移/不可用 Snapshot。"""

        if case.dataset_snapshot.status != "available":
            raise EvaluationContractError(
                f"Case Snapshot {case.dataset_snapshot.snapshot_id} is {case.dataset_snapshot.status}"
            )
        if self._snapshot_resolver is not None:
            resolved = self._snapshot_resolver()
        else:
            if self._database_path is None:
                raise EvaluationContractError("database_path is required for snapshot resolution")
            resolved = DatasetSnapshot.from_database(self._database_path)
        if resolved.status != "available":
            raise EvaluationContractError(f"resolved Snapshot is {resolved.status}")
        return resolved

    async def run_case(
        self,
        case: EvaluationCaseBundle,
        variant: ControlledVariant,
        *,
        suite_id: str = "single_case",
        suite_version: int = 1,
        repetitions: int = 1,
    ) -> tuple[EvaluationRun, ...]:
        """执行一个 Case；repetitions 由调用方控制，默认只执行一次。"""

        if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
            raise EvaluationContractError("repetitions must be a positive integer")
        if isinstance(suite_version, bool) or not isinstance(suite_version, int) or suite_version <= 0:
            raise EvaluationContractError("suite_version must be a positive integer")
        if not isinstance(case, EvaluationCaseBundle) or not isinstance(variant, ControlledVariant):
            raise EvaluationContractError("run_case requires an EvaluationCaseBundle and ControlledVariant")
        resolved_snapshot = self.resolve_snapshot(case)
        if resolved_snapshot.snapshot_id != case.dataset_snapshot.snapshot_id:
            raise EvaluationContractError(
                "resolved Snapshot does not match the Case; create a new Case version instead of silently rebinding"
            )

        runs: list[EvaluationRun] = []
        for repetition in range(repetitions):
            run, raised = await self._run_one(
                case=case,
                variant=variant,
                suite_id=suite_id,
                suite_version=suite_version,
                resolved_snapshot=resolved_snapshot,
                repetition=repetition,
            )
            runs.append(run)
            if raised is not None:
                # 运行事实已经保存；原始 Query 异常继续向调用方暴露，不伪造成功。
                raise raised
        return tuple(runs)

    async def run_suite(
        self,
        suite: EvaluationSuite,
        cases: Mapping[str, EvaluationCaseBundle],
        variant: ControlledVariant,
        *,
        repetitions: int = 1,
    ) -> tuple[EvaluationRun, ...]:
        """按 Suite 的 versioned references 执行 Case，不复制 Case Truth。"""

        if not isinstance(suite, EvaluationSuite):
            raise EvaluationContractError("run_suite requires an EvaluationSuite")
        selected: list[EvaluationCaseBundle] = []
        for reference in suite.case_references:
            case = cases.get(reference.identity)
            if case is None:
                case = cases.get(reference.case_id)
            if case is None or case.identity != reference.identity:
                raise EvaluationContractError(f"Suite Case reference cannot be resolved: {reference.identity}")
            selected.append(case)
        all_runs: list[EvaluationRun] = []
        for case in selected:
            all_runs.extend(
                await self.run_case(
                    case,
                    variant,
                    suite_id=suite.suite_id,
                    suite_version=suite.version,
                    repetitions=repetitions,
                )
            )
        return tuple(all_runs)

    async def _run_one(
        self,
        *,
        case: EvaluationCaseBundle,
        variant: ControlledVariant,
        suite_id: str,
        suite_version: int,
        resolved_snapshot: DatasetSnapshot,
        repetition: int,
    ) -> tuple[EvaluationRun, Exception | None]:
        run_id = f"eval-run:{case.case_id}:v{case.version}:{variant.variant_id}:{uuid.uuid4().hex}"
        request_id = f"eval-request:{run_id}"
        started_at = utc_now()
        request = QueryRequest(
            query=case.query,
            scope=case.data_access_scope,
            request_id=request_id,
            locale=case.locale,
            data_snapshot={
                "snapshot_id": case.dataset_snapshot.snapshot_id,
                "schema_version": case.dataset_snapshot.schema_version,
                "message_count": case.dataset_snapshot.message_count,
                "relevant_time_range": list(case.dataset_snapshot.relevant_time_range),
                "evaluation_case": case.identity,
                "repetition": repetition,
            },
            available_capabilities=variant.available_tools,
            trace_profile=self._trace_profile(variant),
            execution_override=variant.execution_override,
        )
        result: QueryResult | None = None
        trace: TraceProjection | None = None
        raised: Exception | None = None
        exception_type: str | None = None
        exception_message: str | None = None
        try:
            # 生产 execution 的唯一入口；Runner 不接触 Runtime/Tool/Retrieval 实例。
            result = await self._query_executor(request)
        except Exception as exc:
            raised = exc
            exception_type = type(exc).__name__
            # 仅 Provider-neutral 已脱敏异常可保存根因，未知 callback 仍不复制正文。
            exception_message = (
                str(exc) if isinstance(exc, CompletionProviderError)
                else "query executor raised before returning QueryResult"
            )
            trace_id = getattr(exc, "trace_id", None)
            if isinstance(trace_id, str) and trace_id:
                try:
                    trace = self._trace_reader(trace_id)
                except Exception:
                    # Trace Store failure 作为缺失 Trace 的 deterministic check 保存；不伪造完整性。
                    trace = None
        else:
            if result.trace_id is not None:
                try:
                    trace = self._trace_reader(result.trace_id)
                except Exception as exc:
                    # 读取失败不改变已经返回的 QueryResult，只把 diagnosability 事实标为不可用。
                    exception_type = type(exc).__name__
                    exception_message = "trace reader failed after QueryResult returned"

        checks = run_deterministic_checks(
            case=case,
            snapshot=resolved_snapshot,
            variant=variant,
            request=request,
            result=result,
            trace=trace,
        )
        completed_at = utc_now()
        query_snapshot = query_result_snapshot(result)
        answer_reference = None
        if result is not None and result.answer_artifact is not None and result.conversation_id is not None:
            answer_reference = f"conversation:{result.conversation_id}:latest_assistant_artifact"
        terminal_status = (
            "exception"
            if raised is not None
            else result.termination
            if result is not None
            else "unknown"
        )
        trace_reference = (
            result.trace_id
            if result is not None
            else None
            if trace is None
            else trace.trace_id
        )
        run = EvaluationRun(
            run_id=run_id,
            case_id=case.case_id,
            case_version=case.version,
            suite_id=suite_id,
            suite_version=suite_version,
            snapshot_id=case.dataset_snapshot.snapshot_id,
            scope_identity=scope_identity(case.data_access_scope),
            variant_id=variant.variant_id,
            query_request_id=request_id,
            query_request={
                "request_id": request.request_id,
                "query": request.query,
                "locale": request.locale,
                "scope": scope_snapshot(request.scope),
                "data_snapshot": dict(request.data_snapshot),
                "available_capabilities": list(request.available_capabilities),
                "diagnostic_expectations": None
                if case.diagnostic_expectations is None
                else dict(case.diagnostic_expectations),
                "execution_override": request.execution_override.to_dict(),
            },
            terminal_status=terminal_status,
            query_result=query_snapshot,
            answer_artifact_reference=answer_reference,
            trace_id=trace_reference,
            deterministic_checks=checks,
            operational_measurements=operational_measurements(result, trace),
            started_at=started_at,
            completed_at=completed_at,
            execution_override=request.execution_override.to_dict(),
            exception_type=exception_type,
            exception_message=exception_message,
        )
        self._store.save_run(run)
        self._store.save_result(build_evaluation_result(run_id=run_id, checks=checks, result=result, trace=trace))
        return run, raised

    @staticmethod
    def _trace_profile(variant: ControlledVariant) -> TraceProfile:
        """从受控 Runtime config 读取 profile；非法值显式交给 QueryRequest 拒绝。"""

        value = variant.runtime_configuration.get("trace_profile", "normal")
        return cast(TraceProfile, value if isinstance(value, str) else "invalid")
