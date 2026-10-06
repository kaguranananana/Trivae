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
# 实验命令从仓库根目录执行；任务归档后仍使用同一工作目录。
ROOT = Path.cwd()
parser = argparse.ArgumentParser()
parser.add_argument('--variant', choices=('baseline', 'candidate'), required=True)
parser.add_argument('--case', choices=('discussion', 'github', 'fact', 'empty', 'reply', 'archify', 'concept', 'recent', 'empty_window', 'sql', 'person', 'categories', 'materials'), required=True)
parser.add_argument('--repeat', type=int, default=1)
parser.add_argument('--preflight-only', action='store_true')
args = parser.parse_args()
code = TASK / 'experiment' / args.variant / 'src'
sys.path.insert(0, str(code))

from trivae.bootstrap.application import create_application  # noqa: E402
from trivae.capabilities.contracts import ExecutionScope  # noqa: E402
from trivae.config.dotenv import load_environment_file  # noqa: E402
from trivae.config.settings import load_settings  # noqa: E402
from trivae.conversation import SQLiteConversationStore  # noqa: E402
from trivae.evaluation.checks import query_result_snapshot  # noqa: E402
from trivae.observability.sqlite import SQLiteTraceStore  # noqa: E402
from trivae.query.contracts import ExecutionOverride, QueryRequest  # noqa: E402
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter, _RunState  # noqa: E402

# 复用已有实测 HTTP recorder；不复制隐藏 reasoning 或请求鉴权 header。
sys.path.append(str(ROOT / 'evaluation/planner-p1-stability'))
from run_p1_e2e import HTTPRecorder, usage_for  # noqa: E402

CASES = {
    'discussion': '请整理当前所选群中，从 2026 年 8 月 1 日到已有数据截止日期，关于 Agent 开发怎么学习的讨论。  \n请说明：谁提出了什么学习问题、对应回复给了什么建议、有哪些具体路线和材料，以及不同建议适合什么背景。先给综合结论，再按讨论主题展开，标注日期和来源。  \n对关键提问查看对应回复和必要上下文；如果其他表述可能影响结论，请补充检索。区分群友明确说过的内容与你的归纳，未回答的问题单独说明。  \n优先保留能指导学习的内容，减少闲聊和招聘信息。若覆盖不完整，请说明尚未确认的部分，不要把“没有检索到”写成“没有”。',
    'github': '2026 年 8 月 1 日以来，这个群分享过哪些 GitHub 仓库？请保留具体链接和来源。',
    'fact': '这个群提到过《深入理解 AI Agent》吗？谁在什么时候提到的？',
    'empty': '这个群提到过 trivae-no-such-repository-20261005 吗？只核对这个精确名称。',
    'reply': '群里有没有 Agent 后训练教程推荐？找到提问后，请核对后续回复和具体材料，说明是谁推荐的。',
}

# 复用已暴露 Development 问题与原访问范围；不是新 Holdout 或完整 benchmark。
DEV_CASES = {
    'archify': 'dev-context-archify',
    'concept': 'dev-para-ts-learning',
    'recent': 'dev-temporal-2d',
    'empty_window': 'dev-zero-empty-1',
}
DEV_SCOPES = {}
for name, case_id in DEV_CASES.items():
    document = json.loads((ROOT / 'evaluation/cases/benchmark/dev' / f'{case_id}.json').read_text())
    CASES[name] = document['query']
    DEV_SCOPES[name] = ExecutionScope(**document['data_access_scope'])
# 三类补充问题覆盖计数、人物和类别决策；两侧使用相同问题及上轮固定群范围。
CASES.update({
    'sql': '按 UTC 算，2026 年 8 月 14 日当前所选群有多少条消息？请给出计数与来源。',
    'person': '最近两天 Red Herring 在当前所选群聊过哪些内容？先确认这个成员，再按日期说明。',
    'categories': '2026 年 8 月 1 日以来，当前所选群分享过哪些 GitHub 仓库和 Skills？按类别列举，保留链接与来源。',
    'materials': '群里分享过哪些学习全栈开发的课程、视频或文档？请保留具体材料和来源。',
})


async def main() -> None:
    """走正式 Application，结果和历史均隔离到本地实验目录。"""

    # 保留当前 Provider/model/预算配置，安全快照只输出已有脱敏字段。
    load_environment_file(ROOT / '.env')
    settings = load_settings()
    cell = TASK / 'experiment' / f'{args.variant}-{args.case}-{args.repeat}'
    cell.mkdir(parents=True, exist_ok=False)
    snapshot = TASK / 'experiment' / 'snapshot'
    # Canonical/semantic 来自一次备份；查询不导入或更新消息，各版本读取相同内容。
    # 只在已有注入边界加入观测，模型参数和工具执行保持正式实现。
    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    recorder = HTTPRecorder(cell)
    application = create_application(
        snapshot / 'trivae.sqlite3',
        agent_runtime=runtime,
        semantic_index_path=snapshot / 'trivae.semantic.sqlite3',
        conversation_store=SQLiteConversationStore(cell / 'conversation.sqlite3'),
        trace_store=SQLiteTraceStore(cell / 'trace.sqlite3'),
        evaluation_database_path=cell / 'evaluation.sqlite3',
        feedback_database_path=cell / 'feedback.sqlite3',
    )
    runtime.capability_registry = application.capability_registry
    started = perf_counter()
    try:
        # 固定原案例群和数据上界，保留历史背景访问；日期下界仍由原问题表达。
        scope = ExecutionScope(allowed_session_ids=('qq:1039179741',), end_timestamp=1786844190001, max_results=5000)
        scope = DEV_SCOPES.get(args.case, scope)
        request = QueryRequest(
            CASES[args.case], scope, request_id=cell.name, trace_profile='debug',
            execution_override=ExecutionOverride(forced_route='standard_execution'),
        )
        # 记录实际 SDK builder 的完整初始策略、描述与 Schema；不调用 Provider。
        runtime_request = request.to_runtime_request()
        agent = runtime._build_agent(runtime_request, runtime._build_context(runtime_request),
                                     _RunState(provider=settings.provider, model=settings.model_name))
        initial = {
            'instructions': agent.instructions(None, agent),
            'tools': [{'name': tool.name, 'description': tool.description,
                       'schema': tool.params_json_schema, 'strict': tool.strict_json_schema} for tool in agent.tools],
            'settings': settings.to_safe_dict(), 'model_settings': agent.model_settings.to_json_dict(),
            'query': request.query, 'scope': {'sessions': scope.allowed_session_ids,
                       'start': scope.start_timestamp, 'end': scope.end_timestamp, 'max_results': scope.max_results},
        }
        (cell / 'initial_contract.json').write_text(json.dumps(initial, ensure_ascii=False, indent=2))
        if args.preflight_only:
            print(json.dumps({'cell': cell.name, 'preflight': True, 'network_requests': 0}), flush=True)
            return
        # 双侧每个独立进程均预热 embedding，预热耗时单列，不算 Provider/查询延迟。
        warm_started = perf_counter()
        application.semantic_provider.preload()
        (cell / 'warmup.json').write_text(json.dumps({'preload_ms': (perf_counter()-warm_started)*1000}))
        runtime._provider_client._client.event_hooks = {'request': [recorder.request], 'response': [recorder.response]}
        started = perf_counter()
        result = await application.query(request)
        # 使用正式 Evaluation 快照，不另造答案解析或改写模型输出。
        row = {
            'variant': args.variant, 'case': args.case, 'repeat': args.repeat,
            'settings': settings.to_safe_dict(), 'query': request.query,
            'scope': {'session_ids': scope.allowed_session_ids, 'end_timestamp': scope.end_timestamp},
            'usage': usage_for(recorder.records(0)), 'http_requests': len(recorder.requests),
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
