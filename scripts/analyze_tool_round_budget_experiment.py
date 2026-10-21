"""离线比较预算实验的原始 QueryResult、GT 与逐轮证据；不调用 Provider。"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from trivae.evaluation.benchmark.gt import build_case_ground_truth
from trivae.evaluation.benchmark.metrics import evaluate_end_to_end_case
from trivae.evaluation.contracts import EvaluationCaseBundle

ROOT = Path('data/evaluation/tool-round-budget-20261021')


def analyze() -> None:
    """保留检索、最终选据和来源绑定三种含义，不能互相替代。"""
    pairs, details, packets = [], [], []
    for selection in json.loads((ROOT / 'selection.json').read_text()):
        cid = selection['case_id']
        case = EvaluationCaseBundle.from_json(ROOT / 'cases' / f'{cid}.json')
        gt = build_case_ground_truth(case)
        target = set(gt.evidence_target_ids)
        pair, retrieved = {'case_id': cid, 'reason': selection['reason']}, {}
        for arm in ('A', 'B'):
            data = json.loads((ROOT / 'runs' / f'{cid}-{arm}.json').read_text())
            result, run = data.get('result', {}), data.get('run', {})
            runtime = result.get('runtime_result', {})
            artifact = result.get('answer_artifact') or {}
            query, ops = run.get('query_result', {}), run.get('operational_measurements', {})
            calls = runtime.get('tool_calls', [])
            rounds = {call['tool_call_id']: call['round'] for call in calls}
            by_round, direct = {}, set()
            for record in runtime.get('tool_results', []):
                # 同轮并行工具的消息先合并，再计算新增量，避免重复计数。
                ids = by_round.setdefault(rounds[record['tool_call_id']], set())
                for item in record['message_items']:
                    mid = item['message']['internal_message_id']
                    ids.add(mid)
                    if item['is_hit'] and record['tool_name'] in ('lexical_search', 'semantic_search'):
                        direct.add(mid)
            seen, growth = set(), []
            for number, ids in sorted(by_round.items()):
                growth.append({'round': number, 'unique_returned': len(ids), 'new_messages': len(ids - seen),
                               'new_target_ids': sorted((ids - seen) & target)})
                seen.update(ids)
            final = {source['reference']['internal_message_id'] for e in artifact.get('evidence_items', [])
                     for source in e['sources'] if 'internal_message_id' in source['reference']}
            retrieved[arm] = seen
            # 失败终态可能只保留 last_usage；逐个 model.usage 相加才是已观测请求用量。
            connection = sqlite3.connect(f'file:{ROOT / "runs/trace.sqlite3"}?mode=ro', uri=True)
            events = [(op, json.loads(payload)) for op, payload in connection.execute(
                'SELECT operation,payload_json FROM trace_events WHERE trace_id=? ORDER BY sequence',
                (run.get('trace_id'),))]
            connection.close()
            usage = {}
            for op, payload in events:
                if op == 'model.usage':
                    for key, value in payload['usage'].items():
                        usage[key] = usage.get(key, 0) + value
            # current_tool_round 标注下一次调用，不代表该轮实际执行了工具。
            actual_rounds = max(rounds.values(), default=0)
            usage_complete = usage.get('requests', 0) == data['http_requests']

            cached = usage.get('cached_input_tokens', 0)
            # 本次所有请求发生在周三 UTC 14 时（非高峰）；同时保存峰时上界便于账单核对。
            peak_cost = ((usage.get('input_tokens', 0) - cached) * .30 + cached * .006
                         + usage.get('output_tokens', 0) * 1.20) / 1e6
            pair[arm] = {'run_id': run.get('run_id'), 'trace_id': run.get('trace_id'), 'status': data['status'],
                'rounds': actual_rounds, 'reported_rounds': runtime.get('tool_rounds'), 'calls': len(calls),
                'tools_by_round': {str(n): [c['name'] for c in calls if c['round'] == n] for n in by_round},
                'unique_returned': len(seen), 'direct_targets': len(direct & target),
                'returned_targets': len(seen & target), 'final_targets': len(final & target),
                'target_denominator': len(target),
                'context_final_hits': len(final & set(gt.required_context_message_ids)),
                'growth': growth, 'finalization_status': result.get('finalization_status'),
                'finalization_diagnostics': result.get('finalization_diagnostics'),
                'projection_omitted_messages': sum(c.get('model_result_omitted_messages', 0) for c in calls),
                'citation_state': ops.get('citation_state'), 'latency_ms': ops.get('latency_ms'),
                'wall_ms': data['wall_ms'], 'http_requests': data['http_requests'], 'usage': usage, 'terminal_usage': runtime.get('usage'), 'usage_complete': usage_complete,
                'estimated_usd_at_published_offpeak_rate': peak_cost / 2,
                'estimated_usd_peak_upper': peak_cost, 'provider_reported_currency_cost': None,
                'unobserved_request_max_usd': (data['http_requests'] - usage.get('requests', 0)) * (.30 + .0196608) / 2}
            details.append({'case_id': cid, 'arm': arm, 'tier1': evaluate_end_to_end_case(gt, query, operational_measurements=ops)})
            packets.append({'case_id': cid, 'arm': arm, 'query': case.query,
                'blocks': artifact.get('content_blocks'), 'bindings': artifact.get('citation_bindings'),
                'evidence': artifact.get('evidence_items'), 'limitations': artifact.get('limitations')})
        pair['B_messages_absent_A'] = len(retrieved['B'] - retrieved['A'])
        pair['B_new_target_ids'] = sorted((retrieved['B'] - retrieved['A']) & target)
        pairs.append(pair)
    events = [json.loads(line) for line in (ROOT / 'http-budget.jsonl').read_text().splitlines()]
    summary = {'pairs': pairs, 'queries': len(pairs) * 2,
        'http_started': sum(e['event'] == 'started' for e in events),
        'http_finished': sum(e['event'] == 'finished' for e in events),
        'http_status': dict(Counter(str(e.get('status')) for e in events if e['event'] == 'finished')),
        'estimated_observed_usd_lower': sum(p[a]['estimated_usd_at_published_offpeak_rate'] for p in pairs for a in ('A', 'B')),
        'estimated_total_usd_upper': sum(p[a]['estimated_usd_at_published_offpeak_rate'] + p[a]['unobserved_request_max_usd'] for p in pairs for a in ('A', 'B'))}
    for name, value in [('comparison', summary), ('tier1', details), ('review-packets', packets)]:
        (ROOT / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    analyze()
