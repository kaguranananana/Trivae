"""Local Web server：FastAPI app 工厂、静态托管与 ``trivae web`` 启动入口。

第一阶段只支持 localhost 信任模式；显式绑定非回环地址时，
Reveal in Finder 等本机 OS 能力自动禁用。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.config.dotenv import load_environment_file

from .routes import create_api_router
from .streaming import QueryStopRegistry

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8710
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_WEB_DIST_CANDIDATES = (
    Path(__file__).resolve().parents[4] / "web" / "dist",
    Path.cwd() / "web" / "dist",
)


@dataclass(frozen=True)
class WebServerSettings:
    """``trivae web`` 的启动配置。"""

    database_path: Path
    host: str = DEFAULT_WEB_HOST
    port: int = DEFAULT_WEB_PORT
    open_browser: bool = True


def _resolve_dist_directory() -> Path | None:
    """定位已构建的 frontend 产物；缺失时 API 仍可独立运行。"""

    for candidate in _WEB_DIST_CANDIDATES:
        if (candidate / "index.html").is_file():
            return candidate.resolve()
    return None


def create_web_app(
    application: TrivaeApplication,
    *,
    host: str = DEFAULT_WEB_HOST,
) -> FastAPI:
    """构造 FastAPI app：API 路由 + 可选 SPA 静态托管。"""

    app = FastAPI(title="Trivae Local Web", docs_url=None, redoc_url=None)
    allow_reveal = host in LOCAL_HOSTS
    registry = QueryStopRegistry()
    app.include_router(create_api_router(application, registry=registry, allow_reveal=allow_reveal))
    dist = _resolve_dist_directory()
    if dist is not None:
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        logging.getLogger(__name__).warning(
            "WEB_DIST_MISSING message='frontend build not found; run pnpm -C web build' path=%s",
            _WEB_DIST_CANDIDATES[0],
        )
    return app


def _open_browser(url: str) -> None:
    """在 daemon thread 中打开浏览器，不阻塞 uvicorn 启动。"""

    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - 打不开浏览器不改变服务可用性
        logging.getLogger(__name__).warning("WEB_BROWSER_OPEN_FAILED url=%s", url)


def run_web_server(settings: WebServerSettings) -> int:
    """``trivae web`` 的正式入口：创建 Application、启动 uvicorn、自动打开浏览器。"""

    import uvicorn

    load_environment_file(None)
    url = f"http://{settings.host}:{settings.port}"
    with create_application(settings.database_path) as application:
        app = create_web_app(application, host=settings.host)
        if settings.open_browser:
            threading.Timer(1.0, _open_browser, args=(url,)).start()

        async def serve() -> None:
            """在 Uvicorn 的服务 loop 内释放 Query Provider 的 async transport。"""

            try:
                server = uvicorn.Server(
                    uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning")
                )
                await server.serve()
            finally:
                await application.aclose()

        asyncio.run(serve())
    return 0


__all__ = ["WebServerSettings", "create_web_app", "run_web_server"]
