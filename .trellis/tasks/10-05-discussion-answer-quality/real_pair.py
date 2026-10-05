"""固定生产数据快照和三轮预算，保存真实讨论调查的配对证据。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter

# 在导入 Trivae 前选择冻结代码；各 cell 使用独立进程，避免模块缓存混用。
TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--variant', choices=('baseline', 'candidate'), required=True)
parser.add_argument('--case', choices=('discussion', 'github', 'fact', 'empty', 'reply'), required=True)
parser.add_argument('--repeat', type=int, default=1)
args = parser.parse_args()
code = TASK / 'experiment' / 'baseline' / 'src' if args.variant == 'baseline' else ROOT / 'src'
sys.path.insert(0, str(code))

from trivae.bootstrap.application import create_application  # noqa: E402
from trivae.capabilities.contracts import ExecutionScope  # noqa: E402
from trivae.config.dotenv import load_environment_file  # noqa: E402
from trivae.config.settings import load_settings  # noqa: E402
from trivae.conversation import SQLiteConversationStore  # noqa: E402
from trivae.evaluation.checks import query_result_snapshot  # noqa: E402
from trivae.observability.sqlite import SQLiteTraceStore  # noqa: E402
from trivae.query.contracts import ExecutionOverride, QueryRequest  # noqa: E402

CASES = {
    'discussion': '请整理当前所选群中，从 2026 年 8 月 1 日到已有数据截止日期，关于 Agent 开发怎么学习的讨论。  \n请说明：谁提出了什么学习问题、对应回复给了什么建议、有哪些具体路线和材料，以及不同建议适合什么背景。先给综合结论，再按讨论主题展开，标注日期和来源。  \n对关键提问查看对应回复和必要上下文；如果其他表述可能影响结论，请补充检索。区分群友明确说过的内容与你的归纳，未回答的问题单独说明。  \n优先保留能指导学习的内容，减少闲聊和招聘信息。若覆盖不完整，请说明尚未确认的部分，不要把“没有检索到”写成“没有”。',
    'github': '2026 年 8 月 1 日以来，这个群分享过哪些 GitHub 仓库？请保留具体链接和来源。',
    'fact': '这个群提到过《深入理解 AI Agent》吗？谁在什么时候提到的？',
    'empty': '这个群提到过 trivae-no-such-repository-20261005 吗？只核对这个精确名称。',
    'reply': '群里有没有 Agent 后训练教程推荐？找到提问后，请核对后续回复和具体材料，说明是谁推荐的。',
}


async def main() -> None:
    """走正式 Application，结果和历史均隔离到本地实验目录。"""

    # 保留当前 Provider/model/预算配置，安全快照只输出已有脱敏字段。
    load_environment_file(ROOT / '.env')
    settings = load_settings()
    cell = TASK / 'experiment' / f'{args.variant}-{args.case}-{args.repeat}'
    cell.mkdir(parents=True, exist_ok=True)
    snapshot = TASK / 'experiment' / 'snapshot'
    # Canonical/semantic 来自一次备份；查询不导入或更新消息，各版本读取相同内容。
    application = create_application(
        snapshot / 'trivae.sqlite3',
        semantic_index_path=snapshot / 'trivae.semantic.sqlite3',
        conversation_store=SQLiteConversationStore(cell / 'conversation.sqlite3'),
        trace_store=SQLiteTraceStore(cell / 'trace.sqlite3'),
        evaluation_database_path=cell / 'evaluation.sqlite3',
        feedback_database_path=cell / 'feedback.sqlite3',
    )
    started = perf_counter()
    try:
        # 固定原案例群和数据上界，保留历史背景访问；日期下界仍由原问题表达。
        scope = ExecutionScope(allowed_session_ids=('qq:1039179741',), end_timestamp=1786844190001, max_results=5000)
        request = QueryRequest(
            CASES[args.case], scope, request_id=cell.name, trace_profile='debug',
            execution_override=ExecutionOverride(forced_route='standard_execution'),
        )
        result = await application.query(request)
        # 使用正式 Evaluation 快照，不另造答案解析或改写模型输出。
        row = {
            'variant': args.variant, 'case': args.case, 'repeat': args.repeat,
            'settings': settings.to_safe_dict(), 'query': request.query,
            'scope': {'session_ids': scope.allowed_session_ids, 'end_timestamp': scope.end_timestamp},
            'forced_route': 'standard_execution', 'latency_ms': round((perf_counter() - started) * 1000),
            'query_result': query_result_snapshot(result),
        }
        (cell / 'result.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
        # 正文包含私有聊天，保存到 ignored 实验目录供逐项核对。
        (cell / 'answer.md').write_text(result.final_answer or '', encoding='utf-8')
        # 导出同一 Trace 便于核对实参和模型可见证据，保留 SQLite 原始事件作为事实来源。
        application.export_trace_log(result.trace_id, output_path=cell / 'trace.log', view='raw')
        print(json.dumps({'cell': cell.name, 'status': result.execution_status, 'trace_id': result.trace_id,
                          'tool_rounds': result.runtime_result.tool_rounds,
                          'tools': [call.name for call in result.runtime_result.tool_calls]}, ensure_ascii=False), flush=True)
    except Exception as exc:
        # 实验失败保留明确类型；不换 provider、不重试、不写成质量失败。
        (cell / 'failure.json').write_text(json.dumps({'exception_type': type(exc).__name__}), encoding='utf-8')
        raise
    finally:
        # 关闭连接与客户端，不影响生产应用的生命周期。
        await application.aclose()


if __name__ == '__main__':
    asyncio.run(main())
