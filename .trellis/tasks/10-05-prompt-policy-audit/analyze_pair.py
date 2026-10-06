"""从冻结配对实测归档生成事实索引；不以关键词结果替代语义质量评审。"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent / 'experiment'


def message_projections(node: Any) -> list[dict[str, Any]]:
    """递归读取实际工具投影中的消息，不重新检索或补造上下文。"""

    if isinstance(node, dict):
        # 只有 Host 提供的消息投影同时含来源与正文，其他 metadata 不计作消息。
        if 'source_id' in node and 'content' in node:
            return [node]
        return [item for value in node.values() for item in message_projections(value)]
    if isinstance(node, (list, tuple)):
        return [item for value in node for item in message_projections(value)]
    return []


def summarize(cell: Path) -> dict[str, Any]:
    """保存执行、工具、完整输入与关键案例证据，保留原始答案供人工核对。"""

    row = json.loads((cell / 'result.json').read_text())
    result = row['query_result']
    # 读取完整 HTTP body，避免把 20k Trace capture 误当模型实际输入。
    requests = [json.loads(line)['serialized_request']
                for line in (cell / 'provider_requests.jsonl').read_text().splitlines()]
    final_input = requests[-1]['messages']
    calls = [call['function'] for message in final_input if message['role'] == 'assistant'
             for call in message.get('tool_calls', [])]
    # SDK 工具正文是 Python literal 字典；按实际格式解析，不改变生产序列化。
    messages = [projection for message in final_input if message['role'] == 'tool'
                for projection in message_projections(ast.literal_eval(message['content']).get('data'))]
    # 这些词只构造已知 Failure Case 的核查 packet，不是通用评分或生产策略。
    recommendations = [message for message in messages
                       if 'build a' in message['content'].lower() or '这本书很详细' in message['content']]
    first_body = json.loads(json.dumps(requests[0]))
    # 只移除两侧允许不同的首个 system 策略，用其余实际 HTTP 字段校验控制条件。
    assert first_body['messages'][0]['role'] == 'system'
    instruction = first_body['messages'][0].pop('content')
    return {
        'cell': cell.name, 'status': result['execution_status'],
        'finalization': result['finalization_status'], 'diagnostic_codes': result['diagnostic_codes'],
        'runtime': result['runtime'], 'calls': calls, 'latency_ms': row['latency_ms'], 'usage': row['usage'],
        'first_body_without_system': first_body, 'first_body_chars': len(json.dumps(requests[0], ensure_ascii=False)),
        'instructions_chars': len(instruction), 'tools_chars': len(json.dumps(requests[0].get('tools'), ensure_ascii=False)),
        'known_recommendation_projections': recommendations,
        'answer_text': result['answer_text'], 'sources': result['evidence_sources'],
        'content_blocks': result['content_blocks'], 'citation_bindings': result['citation_bindings'],
    }


def main() -> None:
    """按已冻结顺序逐 cell 归档；未完成项保持 pending，不当成成功或零值。"""

    parser = argparse.ArgumentParser()
    parser.add_argument('--schedule', default='schedule.json')
    parser.add_argument('--output', default='review-packet.json')
    args = parser.parse_args()
    schedule = json.loads((ROOT / args.schedule).read_text())
    rows: list[dict[str, Any]] = []
    pairs = []
    for item in schedule:
        pair = []
        for variant in item['variants']:
            cell = ROOT / f"{variant}-{item['case']}-{item['repeat']}"
            if (cell / 'result.json').exists():
                row = summarize(cell)
                rows.append(row)
                pair.append(row)
            elif (cell / 'failure.json').exists():
                # 实验异常单列保留，不用另一次成功覆盖。
                rows.append({'cell': cell.name, 'status': 'exception',
                             'failure': json.loads((cell / 'failure.json').read_text())})
        if len(pair) == 2:
            equal = pair[0]['first_body_without_system'] == pair[1]['first_body_without_system']
            # 原始首个请求除策略外须完全相同；不是比较工具规划或后续历史相同。
            assert equal, f"non-policy request drift: {item['case']}"
            pairs.append({'case': item['case'], 'repeat': item['repeat'], 'non_policy_body_equal': equal})
    (ROOT / args.output).write_text(json.dumps({'rows': rows, 'pairs': pairs}, ensure_ascii=False, indent=2))
    print(json.dumps({'recorded_cells': len(rows), 'planned_cells': 2 * len(schedule),
                      'complete_pairs': len(pairs),
                      'statuses': {status: sum(row['status'] == status for row in rows)
                                   for status in {row['status'] for row in rows}}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
