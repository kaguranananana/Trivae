"""前端引用定位必须来自正式绑定，并验证历史搜索先过滤再分页。"""

import asyncio
from pathlib import Path

import httpx

from tests.test_conversation import _artifact
from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.interfaces.web.projection import project_answer_blocks
from trivae.interfaces.web.server import create_web_app


def test_answer_blocks_use_evidence_bindings_not_source_order() -> None:
    """两段各绑定不同证据，不能把全体来源塞给每一段。"""
    artifact = _artifact()
    blocks = project_answer_blocks(artifact)
    assert blocks == [
        {"block_id": "claim-1", "text": artifact.content_blocks[0].text, "source_indices": [1]},
        {"block_id": "claim-2", "text": artifact.content_blocks[1].text, "source_indices": [2]},
    ]


def test_history_api_searches_old_full_text_before_scope_and_page_limit(tmp_path: Path) -> None:
    """目标在最近100条以外、标题与摘要之外，仍应被全文检索命中。"""

    async def scenario() -> None:
        application = create_application(tmp_path / "history.sqlite3")
        try:
            scope = ExecutionScope()
            target = application.create_conversation(scope)
            # 目标词位于长问题尾部，首120字标题和最终回答预览均不含它。
            application.conversation_store.commit_turn(target.conversation_id, "背景" * 120 + " needle%_", _artifact())
            for _ in range(101):
                application.create_conversation(scope)
            other = application.create_conversation(ExecutionScope(allowed_session_ids=("other",)))
            application.conversation_store.commit_turn(other.conversation_id, "needle%_", _artifact())
            app = create_web_app(application, host="127.0.0.1")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                first = (await client.get("/api/conversations", params={"scope_mode": "all", "limit": 100})).json()
                assert len(first) == 100
                assert target.conversation_id not in {item["conversation_id"] for item in first}
                search = await client.get("/api/conversations", params={"scope_mode": "all", "query": "NEEDLE%_"})
                assert search.status_code == 200
                assert [item["conversation_id"] for item in search.json()] == [target.conversation_id]
                second = (await client.get("/api/conversations", params={"scope_mode": "all", "limit": 100, "offset": 100})).json()
                assert len(second) == 2
                assert not {item["conversation_id"] for item in first}.intersection(item["conversation_id"] for item in second)
        finally:
            await application.aclose()

    asyncio.run(scenario())
