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
    """只表示配置是否可用，不在启动时发起网络健康检查。"""

    status: ProviderStatus
    provider: str | None
    model: str | None
    error_code: str | None = None
    message: str | None = None

    @classmethod
    def from_settings(cls, settings: ModelSettings) -> ProviderReadiness:
        """从已校验 settings 创建不含密钥的 provider projection。"""

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

        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "error_code": self.error_code,
            "message": self.message,
        }


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
