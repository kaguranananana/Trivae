"""Isolated live FastAPI fixture for browser verification; never opens project data or a provider.

Run only via verify-web.sh, with an empty scratch directory. Production Application,
real SDK adapters, real SQLite and Web routes; the only substituted boundary is the LLM.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Direct script execution does not implicitly add the repository root to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import uvicorn
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.interfaces.web.server import create_web_app
from trivae.query.router import RouteDecision
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter


class FixedRouter:
    async def route(self, context: object) -> RouteDecision:
        return RouteDecision(
            route="standard_execution", confidence=1.0, source="rule", reason="isolated browser verification"
        )


def populate_fixture(root: Path) -> Path:
    # The far-away reply is not merely the next message. No real chat records.
    raw = root / "raw"
    raw.mkdir()
    items = [make_message("anchor", 0, 1_000, "分享一个技术项目")]
    items.extend(make_message(f"noise-{i}", i, 1_000 + i, "无关讨论") for i in range(1, 144))
    items.append(make_message("reply", 144, 2_000, "实际用过，值得推荐", reply_to="anchor"))
    write_export(raw, "reply(100).json", items, chat_name="回复实验", peer_uid=None, version="5.5.64")
    return raw


def scripted_model(invalid_citation: bool) -> ScriptedModel:
    claim = {
        "text": "有人实际用过并推荐这个项目。",
        "finding": "有人实际用过并推荐这个项目。",
        "criterion": "用户实际使用反馈",
        "sufficiency": "sufficient",
        "sources": ["invalid-source" if invalid_citation else "m2-2"],
        "limitations": [],
    }
    return ScriptedModel(
        [
            ModelStep(
                output=[
                    function_call(
                        "lexical_search",
                        {
                            "keyword": "分享一个技术项目",
                            "limit": 1,
                            "context_before": 0,
                            "context_after": 0,
                        },
                        call_id="search",
                    )
                ]
            ),
            ModelStep(
                output=[
                    function_call(
                        "get_message_context",
                        {
                            "source_id": "m1-1",
                            "context_before": 0,
                            "context_after": 0,
                            "include_replies": True,
                        },
                        call_id="context",
                    )
                ]
            ),
            ModelStep(
                output=[assistant_message(json.dumps({"claims": [claim], "limitations": []}, ensure_ascii=False))]
            ),
        ]
    )


async def serve(root: Path, port: int, invalid_citation: bool) -> None:
    raw = populate_fixture(root)
    database = root / "canonical.sqlite3"
    application = create_application(database, router=FixedRouter())
    try:
        application.import_directory(raw)
        application.rebuild_lexical_index()
        application._agent_runtime = OpenAIAgentsRuntimeAdapter(
            application.capability_registry,
            model=scripted_model(invalid_citation),
            max_turns=4,
        )
        app = create_web_app(application, host="127.0.0.1")
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
            )
        )
        await server.serve()
    finally:
        await application.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--invalid-citation",
        action="store_true",
        help="Negative control: bad LLM citation, must fail browser assertions",
    )
    args = parser.parse_args()
    if args.scratch.resolve() == Path.cwd().resolve() or any(args.scratch.iterdir()):
        parser.error("scratch must exist, be empty and not be the project directory")
    asyncio.run(serve(args.scratch, args.port, args.invalid_citation))
