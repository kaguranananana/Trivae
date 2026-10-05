"""只读重放失败 Trace 的六次 recent 查询，验证真实数据上的 Finalizer。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from trivae.capabilities.contracts import ExecutionScope, GetRecentMessagesInput
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.capabilities.tools import RecentMessagesTool
from trivae.conversation.serialization import deserialize_answer_artifact, serialize_answer_artifact
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import build_tool_result_record, finalize_answer
from trivae.retrieval.structured import StructuredRetrieval


def main() -> None:
    """固定工具参数和已有数据，验证已定位的时间契约，不调用模型 Provider。"""

    # 定位项目根目录，不修改原始数据库和历史 Trace。
    root = Path(__file__).resolve().parents[3]
    trace_path = root / "data/traces/trace-4f2e4c48080a439f809ad3d79e3ee1d0.log"
    payloads = []
    # 直接提取真实事件，保留模型当时实际提交的窗口和 limit。
    for section in re.split(r"\n\[event ", trace_path.read_text())[1:]:
        header, body = section.split("payload:\n", 1)
        payload = json.loads(body.split("\nfailure:\n", 1)[0])
        if "operation: tool.call.started\n" in header and payload["tool_name"] == "get_recent_messages":
            payloads.append(payload["request"])
    # 复用原所选群，读取 canonical 数据而不创建 Application 或写入真实会话。
    scope = ExecutionScope(allowed_session_ids=("qq:1039179741",), max_results=5000)
    repository = SQLiteCanonicalReadRepository(root / "data/trivae.sqlite3")
    try:
        tool = RecentMessagesTool(RecentMessagesCapability(StructuredRetrieval(repository)))
        records = []
        # 每次真实检索均通过正式 Tool 与 ToolResultRecord 构造入口。
        for index, request in enumerate(payloads, start=1):
            envelope = tool.invoke(GetRecentMessagesInput(**request), scope)
            records.append(build_tool_result_record(
                run_id="run-trace-replay", tool_call_id=f"run-trace-replay/tool-call/{index}",
                tool_result_id=f"run-trace-replay/tool-call/{index}/result",
                tool_name="get_recent_messages", envelope=envelope, scope=scope,
            ))
        # 使用最小事实答案触发完整引用校验，排除模型生成差异。
        sources = [record.message_source_handle(record.message_items[0]) for record in records]
        candidate = json.dumps({"claims": [{
            "text": "各检索窗口均返回消息，覆盖情况逐窗保存。", "finding": "各窗存在消息",
            "criterion": "每窗均有 canonical 来源", "sufficiency": "partial",
            "sources": sources, "limitations": [],
        }], "limitations": []}, ensure_ascii=False)
        artifact = finalize_answer(candidate, run_id="run-trace-replay", tool_results=tuple(records), scope=scope)
        # 核对 codec 没有丢失六窗时间与覆盖事实。
        replay = deserialize_answer_artifact(serialize_answer_artifact(artifact))
        assert replay.retrieval_windows == artifact.retrieval_windows
        assert len(artifact.retrieval_windows) == len(payloads) == 6
        print(json.dumps({"status": "valid", "windows": [window.to_dict() for window in artifact.retrieval_windows]},
                         ensure_ascii=False, indent=2))
    finally:
        repository.close()


if __name__ == "__main__":
    main()
