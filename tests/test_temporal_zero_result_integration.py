"""temporal browsing 集成回归：no-args 默认契约 与 zero-result 全链路行为。

Evaluation framework 说明（ADR 一致）：
- 「模型是否优先选择 get_recent_messages」依赖真实 provider 推理，不能用脚本化断言替代；
  该验收由真实 smoke trace 取证（见 problem record / task 报告）。
- 本文件用 ScriptedModel 锁定可确定性验证的部分：SDK `{}` 合法调用直达 Capability 成功
  （contract 漂移回归）、no-args 解析语义、以及 honest no_result 在 finalize 层合法通过。
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_ingestion import make_message, write_export
from trivae.capabilities.contracts import ExecutionScope
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.capabilities.registry import CapabilityRegistry
from trivae.capabilities.tools import RecentMessagesTool
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import parse_model_no_result_candidate
from trivae.query.runtime.contracts import AgentRunRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.structured import StructuredRetrieval

SESSION = "qq:940"
BASE = 1_786_700_000_000

HONEST_NO_RESULT_JSON = (
    '{"kind": "no_result",'
    ' "summary": "在解析的时间范围内没有找到任何消息，覆盖状态为 complete。",'
    ' "limitations": []}'
)


class TemporalNoArgsIntegrationTests(unittest.TestCase):
    """get_recent_messages({}) 必须是合法调用：默认 relative recent 2 days。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database_path = directory / "integration.sqlite3"
        messages = [
            make_message("i1", 1, BASE, "第一条", sender_uid="u_a"),
            make_message("i2", 2, BASE + 86_400_000, "第二条", sender_uid="u_b"),
        ]
        export = write_export(
            directory,
            "Integration(940).json",
            messages,
            chat_name="Integration",
            peer_uid=None,
            version="5.5.64",
        )
        self.store = SQLiteCanonicalStore(self.database_path)
        SharedImporter(self.store).import_paths([export])
        self.repository = SQLiteCanonicalReadRepository(self.database_path)
        registry = CapabilityRegistry()
        registry.register(
            RecentMessagesTool(RecentMessagesCapability(StructuredRetrieval(self.repository)))
        )
        self.runtime = OpenAIAgentsRuntimeAdapter(
            registry,
            model=ScriptedModel(
                [
                    ModelStep(output=[function_call("get_recent_messages", {}, call_id="f1")]),
                    ModelStep(output=[assistant_message("done")]),
                ]
            ),
            max_turns=3,
            max_tool_rounds=2,
        )
        self.request = AgentRunRequest(
            "最近聊了什么？",
            ExecutionScope(allowed_session_ids=(SESSION,), start_timestamp=None, end_timestamp=None),
            available_capabilities=("get_recent_messages",),
        )

    def tearDown(self) -> None:
        self.repository.close()
        self.store.close()
        self.temporary.cleanup()

    def test_sdk_empty_args_reach_capability_ok(self) -> None:
        result = asyncio.run(self.runtime.run(self.request))
        self.assertEqual(len(result.tool_calls), 1)
        call = result.tool_calls[0]
        self.assertEqual(call.name, "get_recent_messages")
        self.assertEqual(call.status, "ok")
        self.assertIsNone(call.error_code)

    def test_no_args_default_window_resolves_archive_latest(self) -> None:
        from trivae.capabilities.contracts import GetRecentMessagesInput

        input_request = GetRecentMessagesInput()
        time_range = input_request.time_range
        self.assertIsNotNone(time_range)
        if time_range is not None:
            resolved = time_range.to_dict()
            self.assertEqual(resolved["amount"], 2)
            self.assertEqual(resolved["unit"], "day")
            self.assertEqual(resolved["anchor"], "archive_latest")

    def test_zero_result_final_candidate_parses_cleanly(self) -> None:
        candidate = parse_model_no_result_candidate(HONEST_NO_RESULT_JSON)
        self.assertIn("没有找到任何消息", candidate.summary)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
