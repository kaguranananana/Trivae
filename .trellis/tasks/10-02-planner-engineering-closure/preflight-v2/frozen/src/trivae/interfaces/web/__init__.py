"""Local Web interface：把 TrivaeApplication 投影为 ChatLab 风格 Web UI 的后端。

Web 只是 interface：所有执行经 Application facade，事件经 UI-neutral QueryStreamEvent，
conversation/trace 均复用正式 Store，不在接口层建立第二套数据。
"""

from .contracts import (
    ConversationCreateRequest,
    ConversationRenameRequest,
    QueryStopRequest,
    QueryStreamRequest,
    ScopeRequest,
    WebScopeError,
)
from .server import WebServerSettings, run_web_server

__all__ = [
    "ConversationCreateRequest",
    "ConversationRenameRequest",
    "QueryStopRequest",
    "QueryStreamRequest",
    "ScopeRequest",
    "WebScopeError",
    "WebServerSettings",
    "run_web_server",
]
