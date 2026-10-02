"""Trace 文件定位与 macOS Finder reveal（仅 local trusted mode）。

浏览器无法安全控制本机 Finder；backend 负责把 trace_id resolve 成真实日志文件，
校验路径边界后以参数数组调用 ``open -R``。前端永远只传 trace_id，不传路径。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from trivae.bootstrap.application import TrivaeApplication
from trivae.observability.sqlite import TraceStoreError
from trivae.observability.text import TraceTextLogError


class TraceRevealError(Exception):
    """Reveal in Finder 失败的显式错误；error_code 供 API 投影。"""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def resolve_trace_log_path(application: TrivaeApplication, trace_id: str) -> Path:
    """把 trace_id resolve 为 traces 目录内的真实日志文件；必要时先导出。"""

    if not isinstance(trace_id, str) or not trace_id.strip():
        raise TraceRevealError("TRACE_ID_INVALID", "trace_id must be a non-empty string")
    normalized = trace_id.strip()
    try:
        # 读不到 canonical trace 时直接拒绝，不猜测文件系统。
        application.read_trace(normalized)
    except TraceStoreError as exc:
        raise TraceRevealError("TRACE_NOT_FOUND", f"trace is unavailable: {exc}") from exc

    writer = application._trace_log_writer
    try:
        path = writer.log_path(normalized)
    except TraceTextLogError as exc:
        raise TraceRevealError("TRACE_ID_INVALID", str(exc)) from exc
    if not path.exists():
        # 文本日志是 derived projection；query 过程中未导出时按同样规则补一次。
        try:
            path = application.export_trace_log(normalized)
        except (TraceStoreError, TraceTextLogError) as exc:
            raise TraceRevealError("TRACE_FILE_NOT_FOUND", f"trace log is unavailable: {exc}") from exc
    resolved = path.resolve()
    if resolved.parent != writer.directory.resolve():
        # Defense-in-depth：即使 writer 规则被修改，也不能 reveal 目录之外的文件。
        raise TraceRevealError("TRACE_PATH_OUTSIDE_ALLOWED_DIRECTORY", "trace path is outside the allowed directory")
    return resolved


def reveal_trace_in_finder(application: TrivaeApplication, trace_id: str) -> dict[str, object]:
    """在 macOS Finder 中显示 trace 日志文件；只允许本机 trusted mode 调用。"""

    path = resolve_trace_log_path(application, trace_id)
    if sys.platform != "darwin":
        raise TraceRevealError("REVEAL_UNSUPPORTED_PLATFORM", "reveal is only supported on macOS")
    try:
        # 参数数组 + 无 shell：路径不会被解释为 shell 片段。
        subprocess.run(
            ["open", "-R", str(path)],
            check=True,
            timeout=10,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise TraceRevealError("REVEAL_FAILED", f"finder reveal failed: {exc}") from exc
    return {"status": "revealed", "trace_id": trace_id.strip(), "path": str(path)}


def trace_log_path_payload(application: TrivaeApplication, trace_id: str) -> dict[str, object]:
    """Copy Path 用的只读路径信息。"""

    path = resolve_trace_log_path(application, trace_id)
    return {"trace_id": trace_id.strip(), "path": str(path)}
