"""只读重放真实漏检案例，比较关键词召回与回复窗口，不调用模型。"""

from __future__ import annotations

import json
from pathlib import Path

from trivae.capabilities.contracts import ExecutionScope, GetMessageContextInput, SearchMessagesInput
from trivae.capabilities.get_message_context import GetMessageContextCapability
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.capabilities.tools import GetMessageContextTool, LexicalSearchTool
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.retrieval.lexical import LexicalRetrieval


def main() -> None:
    """固定原 Trace 的群和时间参数，仅验证正式工具是否能把证据送到模型。"""

    # 从诊断脚本的位置定位项目，避免依赖调用时的工作目录。
    root = Path(__file__).resolve().parents[3]
    # 原样复用 Trace 的实际范围，不重新解释用户日期或扩大访问范围。
    scope = ExecutionScope(
        allowed_session_ids=("qq:1039179741",),
        start_timestamp=1785542400000,
        end_timestamp=1786844190001,
        max_results=5000,
    )
    # 正式读取适配器使用只读连接，不改写 canonical 消息、索引或历史回答。
    repository = SQLiteCanonicalReadRepository(root / "data/trivae.sqlite3")
    try:
        # 两种工具都复用产品的 Capability、Envelope 和模型投影链路。
        search = LexicalSearchTool(SearchMessagesCapability(LexicalRetrieval(repository)))
        context = GetMessageContextTool(GetMessageContextCapability(repository))
        searches = []
        for keyword in ("教程", "agent"):
            # 关闭自动邻居扩展，使关键词命中数与后面的显式回复读取分开比较。
            envelope = search.invoke(
                SearchMessagesInput(keyword=keyword, limit=5000, context_before=0, context_after=0), scope,
            )
            # 通过正式记录入口获取 canonical 消息，不从 SQLite Row 拼装产品结果。
            record = build_tool_result_record(
                run_id="retrieval-quality-probe", tool_call_id=f"search-{keyword}",
                tool_result_id=f"search-{keyword}/result", tool_name="lexical_search",
                envelope=envelope, scope=scope,
            )
            # 只记录本案例需要核对的消息；这些条件是诊断观察项，不进入产品策略。
            relevant = [item.message.normalized_content for item in record.message_items
                        if "后训练" in item.message.normalized_content
                        or "深入理解ai agent" in item.message.normalized_content]
            searches.append({"keyword": keyword, "returned_messages": len(record.message_items),
                             "observed_messages": relevant})

        windows = []
        for after in (2, 8, 20, 40):
            # 围绕真实提问比较不同窗口，参数是实验变量，不代表选定的新默认值。
            envelope = context.invoke(GetMessageContextInput(
                message_id="qq:1039179741:7672753794157725770", context_before=2, context_after=after,
            ), scope)
            # 构造正式 ToolResultRecord，保证观察到的消息拥有可引用的来源。
            record = build_tool_result_record(
                run_id="retrieval-quality-probe", tool_call_id=f"context-{after}",
                tool_result_id=f"context-{after}/result", tool_name="get_message_context",
                envelope=envelope, scope=scope,
            )
            # 使用现有 16k 投影预算核对书籍证据确实能进入模型输入。
            projection = project_tool_result_for_model(envelope, record, token_budget=16000)
            visible = json.dumps(projection["data"], ensure_ascii=False)
            windows.append({
                "context_after": after, "returned_messages": len(record.message_items),
                "book_recommendation_visible": "build a llm from scratch" in visible.lower(),
                "book_detail_visible": "这本书很详细" in visible,
                "model_projection": projection["model_projection"],
            })
        # 输出可保存的实验结果；不把工具召回成功宣称为模型回答质量提升。
        print(json.dumps({"trace_id": "trace-c61ed0f5f2c64fd88229d8c398be5947",
                          "searches": searches, "context_windows": windows}, ensure_ascii=False, indent=2))
    finally:
        # 不论诊断成功或异常，都关闭只读连接；异常不吞掉。
        repository.close()


if __name__ == "__main__":
    main()
