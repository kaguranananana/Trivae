"""固定三个 Development Case 的 3/5 轮配置对照；最多六次 Query，不重试、不调用 Judge。"""
from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import httpx2 as httpx
from evaluation_quality_experiment import TOOLS, HttpLedger

from trivae.bootstrap.application import create_application
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.conversation import SQLiteConversationStore
from trivae.evaluation.contracts import EvaluationCaseBundle, utc_now
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter, _RunState
from trivae.query.runtime.prompt import SYSTEM_PROMPT

ROOT = Path('data/evaluation/tool-round-budget-20261021')


def save(path: Path, value: object) -> None:
    """新产物只创建一次，防止补跑覆盖已观察结果。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


async def execute() -> None:
    """先冻结条件和顺序，再执行 Case 内 AB、BA、AB 的交替对照。"""
    load_environment_file(Path('.env'))
    settings = load_settings()
    # 显式检查当前生产身份，未知收费模型必须在第一次发送之前停止。
    assert (settings.provider, settings.model_name, settings.base_url) == (
        'deepseek', 'deepseek-flash', 'https://api.deepseek.com')
    assert settings.api_key and settings.max_turns == 8 and settings.max_tool_rounds == 3
    output = ROOT / 'runs'
    output.mkdir(exist_ok=False)
    selected = json.loads((ROOT / 'selection.json').read_text())
    assert len(selected) == 3
    cases = [EvaluationCaseBundle.from_json(ROOT / 'cases' / f'{item["case_id"]}.json') for item in selected]
    order = [(case, arm) for index, case in enumerate(cases)
             for arm in (('A', 'B') if index % 2 == 0 else ('B', 'A'))]
    ledger = HttpLedger(ROOT / 'http-budget.jsonl', maximum=36)
    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    assert runtime._provider_client.max_retries == 0
    trace_store = SQLiteTraceStore(output / 'trace.sqlite3')
    application = create_application(
        ROOT / 'trivae.sqlite3', agent_runtime=runtime, semantic_index_path=ROOT / 'trivae.semantic.sqlite3',
        conversation_store=SQLiteConversationStore(output / 'conversation.sqlite3'), trace_store=trace_store,
        evaluation_database_path=output / 'evaluation.sqlite3', feedback_database_path=output / 'feedback.sqlite3')
    runtime.capability_registry = application.capability_registry
    captured = {}

    async def query(request: QueryRequest):
        # 每个 Evaluation Request 新建对话，不把上一组答案带给下一组。
        captured['request_id'] = request.request_id
        captured['result'] = await application.query(request)
        return captured['result']

    runner = EvaluationRunner(query_executor=query, trace_reader=application.read_trace,
                              store=application.evaluation_store, database_path=ROOT / 'trivae.sqlite3')
    current = {}
    original_send = httpx.AsyncClient._send_single_request

    async def counted_send(client, request):
        # 复用既有真实 HTTP debit 账本；本实验没有任何自动重试或追加 Query。
        assert request.url.host == 'api.deepseek.com' and request.url.scheme == 'https'
        number = ledger.debit(arm=current['arm'], case_id=current['case'], output=str(output))
        try:
            response = await original_send(client, request)
        except BaseException as exc:
            ledger.finish(number, error_type=type(exc).__name__)
            raise
        ledger.finish(number, status=response.status_code)
        return response

    try:
        semantic = application.semantic_index_status().to_dict()
        assert semantic['status'] == 'completed'
        assert semantic['canonical_message_count'] == semantic['indexed_message_count'] == 811892
        conditions = []
        for case in cases:
            assert runner.resolve_snapshot(case).snapshot_id == case.dataset_snapshot.snapshot_id
            for arm, rounds in [('A', 3), ('B', 5)]:
                runtime.max_tool_rounds = rounds
                request = QueryRequest(case.query, case.data_access_scope, locale=case.locale,
                                       available_capabilities=TOOLS).to_runtime_request()
                agent = runtime._build_agent(request, runtime._build_context(request),
                                             _RunState(settings.provider, settings.model_name))
                conditions.append({'case_id': case.case_id, 'arm': arm,
                    'settings': replace(settings, max_tool_rounds=rounds).to_safe_dict(),
                    'runtime': runtime.safe_configuration(), 'prompt': SYSTEM_PROMPT,
                    'instructions': agent.instructions(None, agent),
                    'model_settings': agent.model_settings.to_json_dict(),
                    'tools': [{'name': t.name, 'description': t.description, 'schema': t.params_json_schema}
                              for t in agent.tools], 'semantic_index': semantic,
                    'snapshot_id': case.dataset_snapshot.snapshot_id, 'forced_route': 'standard_execution'})
            left, right = json.loads(json.dumps(conditions[-2:] ))
            # 唯一 treatment 是预算配置；动态 Prompt 中的总量与剩余量随之改变。
            for item in (left, right):
                item.pop('arm')
                item['settings'].pop('max_tool_rounds')
                item['runtime']['local_budgets'].pop('max_tool_rounds')
                item.pop('instructions')
            assert left == right
            assert conditions[-1]['instructions'] == conditions[-2]['instructions'].replace(
                '0 consumed, 3 remaining, of 3 total.', '0 consumed, 5 remaining, of 5 total.')
        save(ROOT / 'conditions.json', conditions)
        save(ROOT / 'protocol.json', {'created_at': utc_now(),
            'code_version': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'query_limit': 6, 'http_limit': 36, 'sdk_max_retries': 0, 'paid_judge': False,
            'treatment': 'tool budget configuration end-to-end, including dynamic prompt',
            'order': [{'case_id': c.case_id, 'arm': a} for c, a in order],
            'pricing_url': 'https://api-docs.deepseek.com/quick_start/pricing/',
            'peak_usd_per_million': {'uncached_input': .30, 'cached_input': .006, 'output': 1.20},
            'extreme_cost_upper_usd': 36 * (.30 + 16384 / 1e6 * 1.20),
            'expected_cost_note': '历史同类运行每次约数万至数十万 input tokens；预计总计小于一美元，非账单承诺'})
        print('preflight passed: 3 cases, 6 queries maximum, 36 HTTP maximum', flush=True)
        with patch.object(httpx.AsyncClient, '_send_single_request', counted_send):
            for case, arm in order:
                # 完整顺序在首次调用前保存；每个预定单元只执行一次。
                current.update(arm=arm, case=case.case_id)
                captured.clear()
                runtime.max_tool_rounds = 3 if arm == 'A' else 5
                variant = ControlledVariant(variant_id=f'tool-budget-20261021:{arm}',
                    code_version=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                    provider=settings.provider, model=settings.model_name, available_tools=TOOLS,
                    prompt_identity='production-system-prompt',
                    budget={'max_tool_rounds': runtime.max_tool_rounds, 'max_turns': 8},
                    runtime_configuration={'trace_profile': 'debug'},
                    execution_override=ExecutionOverride(forced_route='standard_execution'))
                before, started = ledger.count, perf_counter()
                record = {'case_id': case.case_id, 'arm': arm}
                try:
                    run = (await runner.run_case(case, variant))[0]
                    result = captured['result']
                    record.update(status=result.execution_status, run=run.to_dict(), result=asdict(result))
                    application.export_trace_log(result.trace_id,
                        output_path=output / f'{case.case_id}-{arm}.log', context_mode='full')
                except Exception as exc:
                    # 原始失败进入分母，不静默替换，不补跑。
                    record.update(status='exception', error_type=type(exc).__name__, error=str(exc),
                                  request_id=captured.get('request_id'))
                record.update(wall_ms=(perf_counter() - started) * 1000, http_requests=ledger.count - before)
                save(output / f'{case.case_id}-{arm}.json', record)
                print(case.case_id, arm, record['status'], record['http_requests'], flush=True)
    finally:
        await application.aclose()


if __name__ == '__main__':
    asyncio.run(execute())
