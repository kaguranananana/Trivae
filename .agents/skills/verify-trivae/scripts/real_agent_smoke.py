"""Explicitly opt-in, bounded real-provider query on *synthetic* Trivae data.

This is a production Query-path smoke test, NOT a representative Benchmark score.
No provider is contacted unless verify-agent.sh --run passes all preflight gates.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from fixture_server import FixedRouter, populate_fixture

from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.config.settings import ModelSettings
from trivae.query.contracts import ExecutionOverride, QueryRequest


def provider_settings() -> ModelSettings:
    required = ("TRIVAE_VERIFY_API_KEY", "TRIVAE_VERIFY_BASE_URL", "TRIVAE_VERIFY_PROVIDER", "TRIVAE_VERIFY_MODEL")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise ValueError("Missing explicit smoke configuration: " + ", ".join(missing))
    if os.environ.get("TRIVAE_VERIFY_ALLOW_SPEND") != "YES":
        raise ValueError("Real Provider smoke requires explicit TRIVAE_VERIFY_ALLOW_SPEND=YES")
    endpoint = urlsplit(os.environ["TRIVAE_VERIFY_BASE_URL"])
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError("Provider endpoint must use HTTPS with no URL credentials")
    if os.environ["TRIVAE_VERIFY_PROVIDER"] not in {"deepseek", "opencode-go"}:
        raise ValueError("Only explicit API-key compatible providers are supported by this smoke")
    return ModelSettings(
        api_key=os.environ["TRIVAE_VERIFY_API_KEY"],
        base_url=os.environ["TRIVAE_VERIFY_BASE_URL"],
        provider=os.environ["TRIVAE_VERIFY_PROVIDER"],
        model_name=os.environ["TRIVAE_VERIFY_MODEL"],
        max_turns=4,
        max_tool_rounds=2,
        max_output_tokens=1200,
        completion_max_tokens=300,
    )


async def run() -> int:
    settings = provider_settings()
    with tempfile.TemporaryDirectory(prefix="trivae-real-agent-smoke.") as workspace:
        root = Path(workspace)
        raw = populate_fixture(root)
        application = create_application(root / "canonical.sqlite3", agent_settings=settings, router=FixedRouter())
        try:
            application.import_directory(raw)
            application.rebuild_lexical_index()
            result = await asyncio.wait_for(
                application.query(
                    QueryRequest(
                        "请查找这个技术项目的实际使用反馈。需要引用直接回复的原始消息作为证据。",
                        ExecutionScope(allowed_session_ids=("qq:100",), end_timestamp=2_500, max_results=10),
                        available_capabilities=("lexical_search", "get_message_context"),
                        execution_override=ExecutionOverride(forced_route="standard_execution"),
                    )
                ),
                timeout=120,
            )
            tools = [record.tool_name for record in result.runtime_result.tool_results]
            sources = [
                source.reference.internal_message_id
                for evidence in (result.answer_artifact.evidence_items if result.answer_artifact else ())
                for source in evidence.sources
                if getattr(source.reference, "internal_message_id", None)
            ]
            passed = bool(result.is_successful and "qq:100:reply" in sources)
            # Only bounded public metadata; do not persist answer text or credentials.
            print(
                json.dumps(
                    {
                        "status": "passed" if passed else "failed",
                        "trace_id": result.trace_id,
                        "tools": tools,
                        "bound_source_ids": sources,
                        "real_provider": True,
                        "max_model_turns": 4,
                        "max_tool_rounds": 2,
                        "max_output_tokens_per_turn": 1200,
                    },
                    ensure_ascii=False,
                )
            )
            return 0 if passed else 1
        finally:
            await application.aclose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        # Provider SDK errors may include request bodies: never echo exception details.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
