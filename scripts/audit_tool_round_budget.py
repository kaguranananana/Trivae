"""只读审计本地 Evaluation 与 Trace；不调用模型，不读取封存 Holdout 内容。"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from trivae.evaluation.benchmark.gt import build_case_ground_truth
from trivae.evaluation.contracts import EvaluationCaseBundle


def read_trace_log(path: Path) -> list[dict]:
    """解析正式文本导出，保留事件事实；字符串裁剪不推断为模型输入裁剪。"""
    events = []
    for block in path.read_text().split('[event ')[1:]:
        # operation 和 payload 来自同一事件块，避免跨事件错误关联。
        op = re.search(r'^operation: (.+)$', block, re.M)
        payload = re.search(r'\npayload:\n(.*?)\nfailure:\n', block, re.S)
        limitations = re.search(r'^limitations: (.+)$', block, re.M)
        if op and payload:
            events.append({'operation': op[1], 'payload': json.loads(payload[1]),
                           'limitations': limitations[1] if limitations else ''})
    return events


def audit(root: Path, output: Path) -> None:
    """按运行身份去重，并按实验批次、Provider、模型、Variant、源码版本分组。"""
    rows, copies, excluded, errors = {}, [], [], []
    databases = sorted(root.rglob('*.sqlite3')) + [Path('data/trivae.evaluation.sqlite3')]
    for path in databases:
        # Holdout 只记录文件身份，不打开运行正文或 GT。
        if any(word in str(path).lower() for word in ('holdout', 'sealed')) or output in path.parents:
            excluded.append(str(path))
            continue
        connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'evaluation_runs' not in tables:
                continue
            for run_id, case_id, payload in connection.execute('SELECT run_id,case_id,payload_json FROM evaluation_runs'):
                # 主库可能含封存 Case；只取已公开 Development/Calibration/实验身份。
                if path == Path('data/trivae.evaluation.sqlite3') and not case_id.startswith(('dev-', 'cal-', 'pu-', 'quality-', 'frozen-')):
                    excluded.append(f'{path}:{case_id}')
                    continue
                data = json.loads(payload)
                if run_id in rows:
                    copies.append({'run_id': run_id, 'copy': str(path), 'primary': rows[run_id]['database']})
                    continue
                ops = data.get('operational_measurements', {})
                identity = {}
                for check in data.get('deterministic_checks', []):
                    if check['name'] == 'variant_identity' and '{' in check.get('message', ''):
                        identity = json.loads(check['message'][check['message'].index('{'):])
                # 精确源码版本缺失时显式 unavailable，不用当前版本补齐历史身份。
                rows[run_id] = {'database': str(path), 'run_id': run_id, 'case_id': case_id,
                    'case_version': data['case_version'], 'trace_id': data.get('trace_id'),
                    'variant': data['variant_id'], 'provider': ops.get('provider') or identity.get('provider') or 'unavailable',
                    'model': ops.get('model') or identity.get('model') or 'unavailable',
                    'code': identity.get('code_version', 'unavailable'), 'started_at': data['started_at'],
                    'rounds': ops.get('tool_rounds'), 'calls': ops.get('tool_calls'),
                    'config': ops.get('model_configuration'), 'terminal': data['terminal_status'],
                    'termination': ops.get('termination'), 'finalization': ops.get('finalization_status', ops.get('finalization_state')),
                    'ops': ops, 'query_result': data.get('query_result') or {}, 'snapshot_id': data['snapshot_id']}
        except (sqlite3.Error, ValueError) as exc:
            errors.append({'path': str(path), 'error': str(exc)})
        finally:
            connection.close()
    # 原始 Benchmark JSON 也属于历史来源；独立于 SQLite 枚举，避免漏掉旧基线。
    raw_only = 0
    for path in sorted(root.rglob('raw-records.json')):
        if any(word in str(path).lower() for word in ('holdout', 'sealed')) or output in path.parents:
            continue
        records = json.loads(path.read_text())
        report_path = path.parent / 'report.json'
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        environment = report.get('environment') or {}
        for record in records:
            if record.get('split') not in ('development', 'calibration'):
                continue
            run_id = record['run_id']
            if run_id not in rows:
                raw_only += 1
                ops = record.get('operational_measurements', {})
                identity = next((v for v in report.get('variants', [])
                                 if v.get('variant_id') == record['variant_id']), {})
                metrics = {m['name']: m for m in record.get('metrics', [])}
                valid = metrics.get('valid_answer', {})
                rows[run_id] = {'database': str(path), 'run_id': run_id, 'case_id': record['case_id'],
                    'case_version': int(run_id.split(':v')[1].split(':')[0]),
                    'trace_id': record.get('trace_id'), 'variant': record['variant_id'],
                    'provider': ops.get('provider') or identity.get('provider') or 'unavailable',
                    'model': ops.get('model') or identity.get('model') or 'unavailable',
                    'code': identity.get('code_version', 'unavailable'),
                    'started_at': environment.get('created_at', 'unavailable'),
                    'rounds': ops.get('tool_rounds'), 'calls': ops.get('tool_calls'),
                    'config': ops.get('model_configuration'), 'terminal': record['run_status'],
                    'termination': ops.get('termination'),
                    'finalization': ops.get('finalization_status', ops.get('finalization_state')),
                    'ops': ops, 'query_result': {'is_successful': valid.get('value') == 1},
                    'snapshot_id': environment.get('canonical_snapshot_id', 'unavailable')}
            row = rows[run_id]
            row.setdefault('raw_sources', []).append(str(path))
            # Variant 中的 code_version 常滞后；执行环境版本另外记录，不能冒充同一个版本。
            if environment.get('git_commit'):
                row['execution_code'] = environment['git_commit']
            row['historical_metrics'] = record.get('metrics', [])
    # 某些早期 raw 只含 run_id；从正式日志头关联 trace_id，不搜索聊天正文作身份判断。
    log_by_run = {}
    for path in Path('data').rglob('trace-*.log'):
        if any(word in str(path).lower() for word in ('holdout', 'sealed')) or output in path.parents:
            continue
        with path.open() as stream:
            header = ''.join(next(stream, '') for _ in range(7))
        match = re.search(r'^request_id: eval-request:(.+)$', header, re.M)
        if match:
            log_by_run[match[1]] = path.stem
    for row in rows.values():
        if row['trace_id'] is None:
            row['trace_id'] = log_by_run.get(row['run_id'])
    # 只对已纳入分母的 trace_id 读事件，不把独立 Router/Planner probe 混入 Query。
    trace_paths = {}
    for path in Path('data').rglob('*.log'):
        if path.name.startswith('trace-') and not any(word in str(path).lower() for word in ('holdout', 'sealed')):
            trace_paths.setdefault(path.stem, path)
    for row in rows.values():
        events = []
        trace_db = Path(row['database']).parent / 'trace.sqlite3'
        if trace_db.exists():
            connection = sqlite3.connect(f'file:{trace_db}?mode=ro', uri=True)
            try:
                for op, payload, limitations in connection.execute(
                    'SELECT operation,payload_json,limitations_json FROM trace_events WHERE trace_id=? ORDER BY sequence',
                    (row['trace_id'],)):
                    events.append({'operation': op, 'payload': json.loads(payload), 'limitations': json.loads(limitations)})
            finally:
                connection.close()
            if events:
                row['trace_source'] = str(trace_db)
        if not events and row['trace_id'] in trace_paths:
            path = trace_paths[row['trace_id']]
            events = read_trace_log(path)
            row['trace_source'] = str(path)
        row['trace_readable'] = bool(events)
        row['finalizing_events'] = sum(e['operation'] == 'runtime.finalizing' for e in events)
        row['budget_events'] = sum('tool_budget_exhausted' in e['limitations'] for e in events)
        row['runtime_started'] = any(e['operation'] == 'runtime.run' for e in events)
        completed = [e['payload'] for e in events if e['operation'] == 'runtime.tool.completed']
        row['trace_rounds'] = max((p.get('tool_round', 0) or 0 for p in completed), default=None)
        # operational_measurements 是正式终态投影；事件用作交叉核对，不能用模型轮次代替工具轮次。
        if row['rounds'] is None and row['trace_rounds'] is not None:
            row['rounds'] = row['trace_rounds']
        if row['rounds'] is None and events and not completed and row['runtime_started']:
            row['rounds'] = 0
        row['reported_rounds'] = row['rounds']
        row['trace_disagreement'] = row['trace_rounds'] is not None and row['trace_rounds'] != row['rounds']
        # 已复现的 observer 异常分支把 turn_started 的下一轮编号当成已用轮次。
        # 这类失败只按真实 tool_completed 记录统计，原终态字段单独保留供复核。
        if row['trace_disagreement'] and any(e['operation'] == 'runtime.run'
                and e['payload'].get('diagnostic_type') == 'AnswerDeltaParseError' for e in events):
            row['rounds'] = row['trace_rounds']
            row['round_correction'] = 'observer failure: next model turn is not consumed tool round'
        row['max_rounds'] = ((row['config'] or {}).get('local_budgets') or {}).get('max_tool_rounds')
        # 老配置未保存时，只有真实 finalizing 的轮次才能证明该次触顶。
        row['cap_hit'] = row['finalizing_events'] > 0
        row['cap3_hit'] = row['cap_hit'] and row['rounds'] == 3
        path = Path(row['database'])
        row['batch'] = str(path.parent) if path.name == 'evaluation.sqlite3' else str(path)
        if path == Path('data/trivae.evaluation.sqlite3'):
            row['batch'] += ':' + row['started_at'][:10]
    # 只匹配同 Case/version 的公开 Development GT；不借用新版本解释旧运行。
    truths = {}
    case_paths = (list(Path('evaluation/cases/benchmark/dev').glob('*.json'))
                  + list(Path('evaluation/cases/benchmark/calibration').glob('*.json'))
                  + list(Path('evaluation/cases/planner-utility').glob('*.json'))
                  + list(Path('data/evaluation/quality-optimization-20261020/cases').glob('quality-*.json')))
    for path in case_paths:
        value = json.loads(path.read_text())
        # 旧实验目录的 targets sidecar 不是 CaseBundle，明确按 schema 身份排除。
        if not isinstance(value, dict) or 'case_id' not in value:
            continue
        case = EvaluationCaseBundle.from_dict(value)
        truths[(case.case_id, case.version)] = build_case_ground_truth(case)
    for row in rows.values():
        truth = truths.get((row['case_id'], row['case_version']))
        if truth is not None:
            query = row['query_result']
            sources = query.get('evidence_sources', {})
            final = {mid for source in sources.get('sources', []) for mid in source['message_ids']}
            row['gt'] = {'targets': len(truth.evidence_target_ids),
                'final_hits': len(final & set(truth.evidence_target_ids)),
                'required_context': len(truth.required_context_message_ids),
                'context_hits': len(final & set(truth.required_context_message_ids)),
                'projection_omitted': sources.get('omitted'),
                'target_ids': truth.evidence_target_ids, 'context_ids': truth.required_context_message_ids}
    for row in rows.values():
        for metric in row.get('historical_metrics', []):
            if metric['name'] == 'evidence_recall' and metric['availability'] == 'available':
                row['historical_evidence_recall'] = metric
            if metric['name'] == 'context_recovery' and metric['availability'] == 'available':
                row['historical_context_recovery'] = metric
    groups = defaultdict(list)
    for row in rows.values():
        key = (row['batch'], row['provider'], row['model'], row['variant'], row.get('execution_code', row['code']))
        groups[key].append(row)
    summaries = []
    for key, members in sorted(groups.items()):
        analyzable = [r for r in members if r['rounds'] is not None]
        hits = [r for r in members if r['cap3_hit']]
        scored = [r for r in hits if r.get('gt', {}).get('targets', 0) > 0
                  and r['query_result'].get('is_successful') is True]
        summaries.append(dict(zip(('batch', 'provider', 'model', 'variant', 'code'), key)) | {
            'total': len(members), 'analyzable': len(analyzable),
            'round_distribution': dict(Counter(str(r['rounds']) for r in analyzable)),
            'round_percent': {str(n): sum(r['rounds'] == n for r in analyzable) / len(analyzable)
                              for n in range(4)} if analyzable else {},
            'trace_readable': sum(r['trace_readable'] for r in members),
            'cap3': len(hits), 'cap3_rate_analyzable': len(hits) / len(analyzable) if analyzable else None,
            'finalizing_events': sum(r['finalizing_events'] for r in members),
            'budget_events': sum(r['budget_events'] for r in members),
            'hit_query_success': sum(r['query_result'].get('is_successful') is True for r in hits),
            'hit_finalization_failed': sum(r['finalization'] == 'failed' for r in hits),
            'hit_other_failed': sum(r['query_result'].get('is_successful') is not True
                                    and r['finalization'] != 'failed' for r in hits),
            'hit_gt_scored_successful': len(scored),
            'hit_gt_missing_final_targets': sum(r['gt']['final_hits'] < r['gt']['targets'] for r in scored),
            'hit_gt_context_missing': sum(r['gt']['context_hits'] < r['gt']['required_context'] for r in scored),
            'hit_terminal': dict(Counter(r['terminal'] for r in hits)),
            'hit_finalization': dict(Counter(str(r['finalization']) for r in hits)),
            'hit_runtime_termination': dict(Counter(str(r['termination']) for r in hits))})
    output.mkdir(parents=True, exist_ok=True)
    result = {'unique_runs': len(rows), 'analyzable': sum(r['rounds'] is not None for r in rows.values()),
              'trace_readable': sum(r['trace_readable'] for r in rows.values()), 'excluded': excluded,
              'duplicate_copies': copies, 'raw_only_runs': raw_only, 'errors': errors, 'groups': summaries, 'runs': list(rows.values())}
    (output / 'history-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('groups', 'runs', 'excluded', 'duplicate_copies')}, ensure_ascii=False))
    print('groups', len(summaries), 'duplicates', len(copies), 'excluded', len(excluded))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('data/evaluation'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    audit(args.root, args.output)
