"""Application 启动与运行状态的 bounded projection。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trivae.config.settings import ModelSettings
from trivae.retrieval.semantic.contracts import SemanticIndexStatusReport

ProviderStatus = Literal["ready", "not_configured"]
DatabaseStatus = Literal["ready", "unavailable"]


@dataclass(frozen=True)
class ProviderReadiness:
    """表示配置与本机授权是否可用，不在启动时发起网络健康检查。"""

    status: ProviderStatus
    provider: str | None
    model: str | None
    error_code: str | None = None
    message: str | None = None
    auth_mode: str | None = None
    protocol: str | None = None

    @classmethod
    def from_settings(cls, settings: ModelSettings) -> ProviderReadiness:
        """从已校验 settings 创建不含密钥的 provider projection。"""

        # 普通 API key Provider 保留配置预检；订阅 Provider 必须检查本机授权事实。
        if settings.provider == "chatgpt-plan":
            # 延迟导入避免检索-only 启动依赖 OAuth 存储；status 不发起网络请求。
            from trivae.auth import ChatGPTAuthError, ChatGPTAuthStore

            try:
                auth = ChatGPTAuthStore().status()
            except (ChatGPTAuthError, OSError) as exc:
                # 损坏或不可读凭证明确暴露，不能伪装为已登录。
                return cls(
                    status="not_configured", provider=settings.provider, model=settings.model_name,
                    error_code=getattr(exc, "code", type(exc).__name__), message=str(exc),
                    auth_mode="chatgpt_oauth", protocol="responses",
                )
            # authenticated 同时涵盖未过期 access token 与可刷新的 session。
            authenticated = bool(auth["authenticated"])
            # 登录成功不等于获准消费订阅额度；scope 必须由 Auth Store 的事实判断。
            plan_enabled = bool(auth["plan_usage_enabled"])
            return cls(
                status="ready" if authenticated and plan_enabled else "not_configured",
                provider=settings.provider,
                model=settings.model_name,
                error_code=None if authenticated and plan_enabled else (
                    "CHATGPT_PLAN_SCOPE_REQUIRED" if authenticated else "CHATGPT_LOGIN_REQUIRED"
                ),
                message=None if authenticated and plan_enabled else (
                    "ChatGPT plan usage scopes are missing; run trivae auth login --provider chatgpt"
                    if authenticated else "Run trivae auth login --provider chatgpt"
                ),
                auth_mode="chatgpt_oauth",
                protocol="responses",
            )

        return cls(
            status="ready",
            provider=settings.provider,
            model=settings.model_name,
        )

    @classmethod
    def not_configured(cls, error_code: str, message: str) -> ProviderReadiness:
        """保留稳定配置错误码，让用户知道需要修复什么。"""

        return cls(
            status="not_configured",
            provider=None,
            model=None,
            error_code=error_code,
            message=message,
        )

    def to_dict(self) -> dict[str, object]:
        """输出 safe provider 状态，不输出 API key 或原始配置对象。"""

        result: dict[str, object] = {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "error_code": self.error_code,
            "message": self.message,
        }
        # 只扩展 ChatGPT projection，旧 Provider 的 readiness 输出保持原结构。
        if self.auth_mode is not None:
            result["auth_mode"] = self.auth_mode
            result["protocol"] = self.protocol
        return result


@dataclass(frozen=True)
class ApplicationReadiness:
    """CLI 启动和 /status 共用的单一状态投影。"""

    database_status: DatabaseStatus
    session_count: int | None
    message_count: int | None
    database_error_code: str | None
    database_message: str | None
    semantic: SemanticIndexStatusReport | None
    semantic_error_code: str | None
    semantic_message: str | None
    provider: ProviderReadiness

    def to_dict(self) -> dict[str, object]:
        """生成可复制的 bounded 状态，保留 semantic identity 但不含向量正文。"""

        return {
            "database": {
                "status": self.database_status,
                "session_count": self.session_count,
                "message_count": self.message_count,
                "error_code": self.database_error_code,
                "message": self.database_message,
            },
            "semantic": (
                None
                if self.semantic is None
                else self.semantic.to_dict()
            ),
            "semantic_error_code": self.semantic_error_code,
            "semantic_message": self.semantic_message,
            "provider": self.provider.to_dict(),
        }
