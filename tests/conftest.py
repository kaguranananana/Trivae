from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def disable_router_jev_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """让普通测试保持离线；Provider contract 测试使用本地 mock transport。"""

    monkeypatch.setenv("TRIVIAE_ROUTER_JEV_ENABLED", "false")
