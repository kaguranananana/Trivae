"""从既有质量实验 Artifact 生成脱敏统计与原生 ReviewPacket，不调用 Provider。"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import mean, median

from trivae.conversation import deserialize_answer_artifact
from trivae.evaluation.benchmark.gt import build_case_ground_truth
from trivae.evaluation.benchmark.metrics import evaluate_end_to_end_case
from trivae.evaluation.contracts import EvaluationCaseBundle, ReviewPacket
from trivae.evaluation.review import _source_projection


def read(path: Path) -> dict:
    """分析只读取已落盘事实，不重新调用查询或补造缺失结果。"""
    return json.loads(path.read_text())


def write(path: Path, value: object) -> None:
    """只覆盖派生报告；原始运行、Case、Trace、账本均不在此写入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def summarize(root: Path, selection: list[dict], split: str, arm: str) -> tuple[dict, list[dict]]:
    """固定选择集作分母；未运行或异常不从交付率中剔除。"""
    rows, detailed = [], []
    for item in selection:
        cid = item['case_id']
        folder = root / arm if split == 'development' else root / split / cid / arm
        path = folder / f'{cid}.json'
        case = EvaluationCaseBundle.from_json(root / 'cases' / f'{cid}.json')
        gt = build_case_ground_truth(case)
        targets = set(gt.evidence_target_ids)
        data = read(path) if path.exists() else {'status': 'not_run', 'http_requests': 0}
        run = data.get('run', {})
        query, ops = run.get('query_result', {}), run.get('operational_measurements', {})
        result = data.get('result', {})
        runtime = result.get('runtime_result', {})
        direct, returned, final = set(), set(), set()
        for record in runtime.get('tool_results', []):
            # context Tool 的消息可引用，但不冒充 direct retrieval ranking。
            for message in record['message_items']:
                mid = message['message']['internal_message_id']
                returned.add(mid)
                if record['tool_name'] in ('lexical_search', 'semantic_search') and message['is_hit']:
                    direct.add(mid)
        for evidence in (result.get('answer_artifact') or {}).get('evidence_items', []):
            final.update(source['reference']['internal_message_id'] for source in evidence['sources']
                         if 'internal_message_id' in source['reference'])
        # 无省略的正式投影计数可证明完整Host来源送达；发生省略时不猜测可见目标。
        calls = runtime.get('tool_calls', [])
        all_visible = bool(calls) and all(call.get('model_result_omitted_messages') == 0 for call in calls)
        row = {'case_id': cid, 'status': data['status'], 'execution_success': query.get('is_successful') is True,
               'run_id': run.get('run_id'), 'trace_id': run.get('trace_id'),
               'runtime_termination': runtime.get('termination'),
               'failure_code': (query.get('finalization_error') or {}).get('code')
                    or (runtime.get('error') or {}).get('code'),
               'target_denominator': len(targets), 'direct_targets': len(direct & targets),
               'returned_targets': len(returned & targets),
               'model_visible_targets': len(returned & targets) if all_visible else None,
               'final_evidence_targets': len(final & targets),
               'http_requests': data['http_requests'], 'latency_ms': ops.get('latency_ms'),
               'experiment_wall_ms': data.get('latency_ms'),
               'usage': ops.get('usage'), 'trace_completeness': ops.get('trace_completeness'),
               'citation_state': ops.get('citation_state'), 'finalization_status': query.get('finalization_status'),
               'tools': ops.get('agent_tool_behavior', {}).get('tool_sequence', []),
               'human_quality_review': 'pending'}
        rows.append(row)
        detailed.append(evaluate_end_to_end_case(gt, query or None, operational_measurements=ops))
        if query.get('answer_artifact_present'):
            # 使用Conversation正式codec恢复Artifact，并复用原生ReviewPacket的来源投影。
            connection = sqlite3.connect(f'file:{folder / "conversation.sqlite3"}?mode=ro', uri=True)
            try:
                saved = connection.execute('SELECT answer_artifact_json FROM conversation_messages '
                                           'WHERE trace_id=? AND role=?', (run['trace_id'], 'assistant')).fetchone()
            finally:
                connection.close()
            artifact = deserialize_answer_artifact(saved[0])
            packet = ReviewPacket(packet_id=f'quality-review:{run["run_id"]}', run_id=run['run_id'],
                query=case.query, answer_text=artifact.answer_text,
                selected_sources=tuple(_source_projection(source.reference, source.relation)
                                       for evidence in artifact.evidence_items for source in evidence.sources),
                rubric_version=case.review_policy.rubric_version, visible_limitations=artifact.limitations)
            write(root / 'review-packets' / split / cid / f'{arm}.json', packet.to_dict())
        elif run:
            # 失败同样进入评审分母；不把Runtime未通过校验的文本冒充正式答案。
            packet = ReviewPacket(packet_id=f'quality-review:{run["run_id"]}', run_id=run['run_id'],
                query=case.query, answer_text=None, selected_sources=(),
                rubric_version=case.review_policy.rubric_version,
                visible_limitations=(str(row['failure_code'] or data['status']),))
            write(root / 'review-packets' / split / cid / f'{arm}.json', packet.to_dict())
    latencies = [row['latency_ms'] for row in rows if row['latency_ms'] is not None]
    usages = [row['usage'] for row in rows if row['usage'] is not None]
    aggregate = {'run_denominator': len(selection), 'execution_success_numerator': sum(row['execution_success'] for row in rows),
                 'status_counts': dict(Counter(row['status'] for row in rows)),
                 'target_denominator': sum(row['target_denominator'] for row in rows),
                 'direct_targets': sum(row['direct_targets'] for row in rows),
                 'returned_targets': sum(row['returned_targets'] for row in rows),
                 'final_evidence_targets': sum(row['final_evidence_targets'] for row in rows),
                 'http_requests': sum(row['http_requests'] for row in rows),
                 'latency_mean_ms': mean(latencies) if latencies else None,
                 'latency_median_ms': median(latencies) if latencies else None,
                 'latency_observed_runs': len(latencies),
                 'usage_observed_runs': len(usages),
                 'usage': {key: sum(usage.get(key, 0) for usage in usages)
                           for key in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens')},
                 'grounded_answer_human': 'unavailable: human review pending',
                 'claim_citation_support_human': 'unavailable: human review pending', 'currency_cost': None,
                 'cases': rows}
    return aggregate, detailed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--public-output', type=Path)
    args = parser.parse_args()
    root = args.root
    selection = read(root / 'selection.json')['cases']
    output = {'experiment': 'quality-optimization-20261020', 'review_status': 'human_pending',
              'baseline_commit': '8def8d7', 'candidate_commit': '3d9cc0e', 'splits': {}}
    groups = [('development', [row for row in selection if row['split'] == 'development']),
              ('validation', [row for row in selection if row['split'] == 'independent_reused_development'])]
    if (root / 'repeat' / 'protocol.json').exists():
        repeated = read(root / 'repeat' / 'protocol.json')['case_ids']
        groups.append(('repeat', [row for row in selection if row['case_id'] in repeated]))
    for split, chosen in groups:
        output['splits'][split] = {}
        for arm in ('baseline', 'candidate'):
            aggregate, detailed = summarize(root, chosen, split, arm)
            output['splits'][split][arm] = aggregate
            write(root / 'analysis' / f'{split}-{arm}-tier1.json', detailed)
    # 传输账本包含发送前debit和结束事件；失败/预检不重置计数。
    ledger = [json.loads(line) for line in (root / 'http-budget.jsonl').read_text().splitlines()]
    started = [row for row in ledger if row['event'] == 'started']
    finished = [row for row in ledger if row['event'] == 'finished']
    output['http'] = {'maximum': ledger[0]['maximum'], 'started': len(started), 'finished': len(finished),
                      'statuses': dict(Counter(str(row.get('status', row.get('error_type'))) for row in finished))}
    for arm in ('baseline', 'candidate'):
        review = read(root / f'{arm}-assistant-review.json')
        output['splits']['development'][arm]['assistant_provisional'] = {
            field: dict(Counter(case[field] for case in review['cases']))
            for field in ('core_requirements', 'citation_support', 'grounded_answer')}
    audit_path = root / 'analysis' / 'final-integrity-audit.json'
    if audit_path.exists():
        audit = read(audit_path)
        # 不把旧审计计数贴到新运行上；两个身份分母必须与本轮实际产物一致。
        if audit['runs'] != sum(group['run_denominator'] for arms in output['splits'].values() for group in arms.values()):
            raise ValueError('integrity audit run denominator differs from current artifacts')
        if audit['http_started'] != len(started):
            raise ValueError('integrity audit HTTP count differs from current ledger')
        output['integrity'] = {key: value for key, value in audit.items() if key != 'details'}
    write(root / 'analysis' / 'summary.json', output)
    if args.public_output:
        # 白名单统计只含Case身份、计数、配置版本与性能，没有聊天正文、消息定位或密钥。
        write(args.public_output, output)
    # 未来人工可仅看这个隐藏arm/run身份的展示；当前Assistant审核并非blind。
    rng = random.Random(20261020)
    blind, mapping = [], []
    for split in output['splits']:
        for case_dir in sorted((root / 'review-packets' / split).glob('*')):
            arms = ['baseline', 'candidate']
            rng.shuffle(arms)
            for label, arm in zip(('X', 'Y'), arms, strict=True):
                path = case_dir / f'{arm}.json'
                if not path.exists():
                    continue
                packet = read(path)
                blind.append({'split': split, 'case_id': case_dir.name, 'side': label, 'query': packet['query'],
                              'answer_text': packet['answer_text'],
                              'selected_sources': [{key: value for key, value in source.items()
                                  if key not in ('tool_result_id', 'result_item_id')}
                                  for source in packet['selected_sources']],
                              'visible_limitations': packet['visible_limitations'], 'human_review': 'pending'})
                mapping.append({'split': split, 'case_id': case_dir.name, 'side': label, 'arm': arm, 'run_id': packet['run_id']})
    write(root / 'review-packets' / 'blind-display.json', blind)
    write(root / 'review-packets' / 'sealed-display-mapping.json', mapping)
    print(json.dumps({'http': output['http'], 'splits': {s: {a: {k: v for k, v in x.items() if k != 'cases'}
                     for a, x in arms.items()} for s, arms in output['splits'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
