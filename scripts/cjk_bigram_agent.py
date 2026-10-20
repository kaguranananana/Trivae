"""隔离实验索引经真实 Application.query 的配对 Flash 验证，硬限制 HTTP 总量。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import httpx2 as httpx

from scripts.cjk_bigram_benchmark import ORDER, ROOT, open_index, write_new
from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation.contracts import (
    CaseProvenance,
    DatasetSnapshot,
    EvaluationCaseBundle,
    utc_now,
)
from trivae.evaluation.variant import ControlledVariant
from trivae.query.contracts import ExecutionOverride
from trivae.retrieval.structured import LexicalQuery, MessageHit


class ExperimentLexicalReader:
    """只替换 lexical count/hits；Canonical 恢复、Scope 与上下文继续由生产 owner 处理。"""

    def __init__(self, root: Path, strategy: str, canonical: SQLiteCanonicalReadRepository) -> None:
        self.connection = open_index(root, strategy)
        self.strategy = strategy
        self.canonical = canonical

    def __getattr__(self, name: str) -> object:
        """其余只读能力委托给同一个 Canonical adapter，不创建另一套事实。"""
        return getattr(self.canonical, name)

    def sql(self, query: LexicalQuery, *, scored: bool) -> tuple[str, list]:
        """两侧共用生产 Scope SQL，A 仅移除查询文本的 bigram 转换。"""
        sql, parameters = self.canonical._lexical_match_union(query, scored=scored)
        if self.strategy == 'A':
            # 每个 term 仍是独立 quoted literal，保留生产多词 AND 契约。
            expression = ' AND '.join('"' + term.replace('"', '""') + '"' for term in query.terms)
            parameters[0] = expression
            parameters[len(parameters) // 2] = expression
        return sql, parameters

    def count_lexical_hits(self, query: LexicalQuery) -> int:
        """在真实 A/B FTS 上计数，不让旧索引冒充生产 v2 metadata。"""
        sql, parameters = self.sql(query, scored=False)
        return self.connection.execute(f'SELECT COUNT(*) FROM ({sql})', parameters).fetchone()[0]

    def read_lexical_hits(self, query: LexicalQuery) -> tuple[MessageHit, ...]:
        """按相同 BM25 和 tie-break 排序，再从 Canonical 恢复证据正文。"""
        sql, parameters = self.sql(query, scored=True)
        rows = self.connection.execute(f'{sql} ORDER BY {ORDER} LIMIT ?', [*parameters, query.limit]).fetchall()
        hits = []
        for row in rows:
            message = self.canonical.read_message_by_id(row['internal_message_id'])
            if message is None or message.session_id != row['session_id']:
                raise AssertionError('experiment hit cannot be recovered from canonical')
            hits.append(MessageHit(message=message, matched_terms=query.terms,
                                   score=row['lexical_score'], score_type='fts5_bm25'))
        return tuple(hits)


async def run(root: Path, *, continuation: bool = False) -> None:
    """新目录只执行一次；逐请求计数，失败保留真实记录且不重试。"""
    output = root / ('agent-continuation' if continuation else 'agent')
    # 首批已有 17 次完成调用和 1 次中断前完成调用，另预留 1 次可能的在途请求。
    previous_debit = 19 if continuation else 0
    output.mkdir(exist_ok=False)
    load_environment_file(Path('.env'))
    os.environ['TRIVAE_ROUTER_JEV_ENABLED'] = 'false'
    settings = load_settings()
    if (settings.provider, settings.model_name, settings.base_url) != (
        'deepseek', 'deepseek-flash', 'https://api.deepseek.com'
    ) or not settings.api_key:
        raise ValueError('official Flash environment preflight failed')
    frozen = json.loads((root / 'frozen.json').read_text())
    snapshot = DatasetSnapshot.from_database(root / 'snapshot.sqlite3')
    protocol = {
        'created_at': utc_now(), 'settings': settings.to_safe_dict(),
        'case_ids': frozen['agent_case_ids'], 'repetitions': 1, 'http_limit': 40,
        'tools': ['lexical_search', 'get_message_context'], 'scope_max_results': 10,
        'forced_route': 'standard_execution', 'context_window_limit': 0,
        'prompt': '查找消息中包含“{term}”的记录，最多列出3条并引用原文；若确实没有找到请明确说明。',
        'adapter': 'both arms same ExperimentLexicalReader; identical canonical restoration and context; '
                   'A raw MATCH, B production normalization; no readiness override or metadata forgery',
        'previous_http_budget_debit': previous_debit,
        'transport_module': 'httpx2 (current installed OpenAI SDK)',
        'limitations': ['lexical-only controlled tool surface, not default full Agent',
                        'single repetition; semantic factual/citation correctness requires human review'],
    }
    write_new(output / 'protocol.json', protocol)
    http_calls: list[dict] = []
    original_send = httpx.AsyncClient._send_single_request

    async def counted_send(client: httpx.AsyncClient, request: httpx.Request) -> httpx.Response:
        """计数实际传输尝试；不保存请求体、Header、密钥或响应正文。"""
        if request.url.host != 'api.deepseek.com':
            raise RuntimeError('unexpected provider host in controlled experiment')
        if len(http_calls) + previous_debit >= 40:
            raise RuntimeError('CJK experiment HTTP budget exhausted')
        item = {'number': len(http_calls) + 1, 'case_id': current['case_id'],
                'strategy': current['strategy'], 'started_at': utc_now()}
        http_calls.append(item)
        # 失败请求同样落盘，不能依靠成功响应低估真实用量。
        try:
            response = await original_send(client, request)
            item['status'] = response.status_code
            return response
        except Exception as exc:
            item['error_type'] = type(exc).__name__
            raise
        finally:
            (output / 'http.json').write_text(json.dumps(http_calls, indent=2))

    current: dict[str, str] = {}
    records = []
    application = create_application(root / 'snapshot.sqlite3')
    canonical = application.read_repository
    adapters = {strategy: ExperimentLexicalReader(root, strategy, canonical) for strategy in ('A', 'B')}
    original_query = application.query
    captured = {}

    async def capture(request):
        """EvaluationRunner 继续通过 Application.query 执行，额外保留私有完整 Artifact。"""
        result = await original_query(request)
        captured['result'] = result
        return result

    application._evaluation_runner._query_executor = capture
    try:
        with patch.object(httpx.AsyncClient, '_send_single_request', counted_send):
            for number, case_id in enumerate(protocol['case_ids']):
                if continuation and number < 4:
                    continue
                spec = next(case for case in frozen['cases'] if case['case_id'] == case_id)
                case = EvaluationCaseBundle(
                    case_id=case_id, version=1, suite_tags=('cjk-agent-v1',), dataset_snapshot=snapshot,
                    data_access_scope=ExecutionScope(max_results=10),
                    query=protocol['prompt'].format(term=spec['term']),
                    uncertainty_constraints=('References are exhaustive literal IDs in frozen.json; semantic review pending',),
                    provenance=CaseProvenance('cjk-bigram-v1', 'frozen literal benchmark', utc_now()),
                )
                case.to_json(output / f'{case_id}.json')
                for strategy in (('A', 'B') if number % 2 == 0 else ('B', 'A')):
                    if continuation and case_id == 'cjk-45' and strategy == 'A':
                        # 已中断的 A 保留 aborted 事实，不重试以制造完整配对。
                        continue
                    current.update(case_id=case_id, strategy=strategy)
                    if len(http_calls) + previous_debit >= 40:
                        records.append({**current, 'status': 'not_run_budget'})
                        continue
                    application.lexical_retrieval.repository = adapters[strategy]
                    variant = ControlledVariant(
                        variant_id=f'cjk-agent-{strategy}-v1', code_version='201a81b+evaluation-snapshot-fix',
                        provider=settings.provider, model=settings.model_name,
                        available_tools=tuple(protocol['tools']), index_identity=f'isolated-cjk-{strategy}',
                        runtime_configuration={'trace_profile': 'debug'},
                        execution_override=ExecutionOverride(forced_route='standard_execution', context_window_limit=0),
                    )
                    started = perf_counter()
                    before = len(http_calls)
                    captured.clear()
                    try:
                        runs = await application.evaluate_case(case, variant)
                        result = captured['result']
                        record = {**current, 'status': result.execution_status,
                                  'run': runs[0].to_dict(), 'artifact': None if result.answer_artifact is None
                                  else asdict(result.answer_artifact)}
                    except Exception as exc:
                        # 批次显式保存异常并继续其他配对；不替换答案、不重试失败项。
                        record = {**current, 'status': 'exception', 'error_type': type(exc).__name__,
                                  'error': str(exc).replace(settings.api_key, '[REDACTED]')}
                    record.update(latency_ms=(perf_counter() - started) * 1000,
                                  http_requests=len(http_calls) - before)
                    records.append(record)
                    write_new(output / f'{case_id}-{strategy}.json', record)
                    print(case_id, strategy, record['status'], record['http_requests'], flush=True)
    finally:
        for adapter in adapters.values():
            adapter.connection.close()
        await application.aclose()
        write_new(output / 'records.json', records)
        write_new(output / 'summary.json', {'requests': len(http_calls), 'runs': len(records),
                                          'status_counts': {status: sum(row['status'] == status for row in records)
                                                            for status in sorted({row['status'] for row in records})}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--continue-interrupted', action='store_true')
    args = parser.parse_args()
    asyncio.run(run(ROOT, continuation=args.continue_interrupted))
