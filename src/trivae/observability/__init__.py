"""M6 Trace / Observability public boundary。"""

from trivae.observability.collector import (
    CapturePolicy,
    TraceableAgentRuntime,
    TraceCaptureError,
    TraceCollector,
    TraceOperationContext,
)
from trivae.observability.contracts import (
    FailureInfo,
    ImportBatchDiagnostic,
    ImportDiagnosticsProjection,
    ImportErrorDiagnostic,
    NormalizedQueryEvent,
    StoredTrace,
    TraceContractError,
    TraceFailure,
    TraceMetrics,
    TraceProfile,
    TraceProjection,
    TraceStore,
    TraceTimelineItem,
)
from trivae.observability.projection import project_import_diagnostics, project_trace
from trivae.observability.sqlite import (
    ImportDiagnosticsError,
    SQLiteImportDiagnosticsReader,
    SQLiteTraceStore,
    TraceStoreError,
)
from trivae.observability.text import TraceTextLogError, TraceTextLogWriter, format_trace_text

__all__ = [
    "CapturePolicy",
    "FailureInfo",
    "ImportBatchDiagnostic",
    "ImportDiagnosticsError",
    "ImportDiagnosticsProjection",
    "ImportErrorDiagnostic",
    "NormalizedQueryEvent",
    "SQLiteImportDiagnosticsReader",
    "SQLiteTraceStore",
    "StoredTrace",
    "TraceCaptureError",
    "TraceCollector",
    "TraceContractError",
    "TraceFailure",
    "TraceMetrics",
    "TraceOperationContext",
    "TraceProfile",
    "TraceProjection",
    "TraceStoreError",
    "TraceStore",
    "TraceTextLogError",
    "TraceTextLogWriter",
    "TraceTimelineItem",
    "TraceableAgentRuntime",
    "project_import_diagnostics",
    "project_trace",
    "format_trace_text",
]
