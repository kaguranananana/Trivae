"""真实发现的评审映射歧义回归：复测与开发集复用Case时不能混淆。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import evaluation_quality_report as report


def test_review_identity_keeps_split_and_failed_side(tmp_path: Path, monkeypatch) -> None:
    """同Case跨split有独立身份；失败展示保留，运行归属只存在封存映射。"""
    def save(path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    save(tmp_path / 'selection.json', {'cases': [{'case_id': 'shared-case', 'split': 'development'}]})
    save(tmp_path / 'repeat/protocol.json', {'case_ids': ['shared-case']})
    for arm in ('baseline', 'candidate'):
        save(tmp_path / f'{arm}-assistant-review.json', {'cases': []})
    (tmp_path / 'http-budget.jsonl').write_text('{"event":"budget","maximum":120}\n')
    for split in ('development', 'repeat'):
        for arm in ('baseline', 'candidate'):
            # 用实际带arm的运行标识模拟泄漏风险；失败的一侧没有正式答案。
            save(tmp_path / 'review-packets' / split / 'shared-case' / f'{arm}.json', {
                'run_id': f'{split}:quality:{arm}:run', 'query': 'A resource question',
                'answer_text': None if arm == 'candidate' else 'A source-grounded answer',
                'selected_sources': [{'tool_result_id': f'quality:{arm}:tool',
                                      'result_item_id': 'private-locator', 'snapshot': {'excerpt': 'evidence'}}],
                'visible_limitations': ['INVALID_FINAL_OUTPUT'] if arm == 'candidate' else [],
            })
    # 此测试只验证派生评审身份；真实GT/Tier1已有独立生产链路验证。
    monkeypatch.setattr(report, 'summarize', lambda *args: ({'cases': []}, []))
    monkeypatch.setattr(sys, 'argv', ['report', '--root', str(tmp_path)])
    report.main()
    display = json.loads((tmp_path / 'review-packets/blind-display.json').read_text())
    mapping = json.loads((tmp_path / 'review-packets/sealed-display-mapping.json').read_text())
    identities = [(row['split'], row['case_id'], row['side']) for row in mapping]
    assert len(identities) == len(set(identities)) == 4
    assert {(row['split'], row['side']) for row in display} == {
        ('development', 'X'), ('development', 'Y'), ('repeat', 'X'), ('repeat', 'Y')}
    # 映射按同一稳定身份关联，不能只靠列表位置碰巧正确。
    indexed = {(row['split'], row['case_id'], row['side']): row for row in mapping}
    for row in display:
        linked = indexed[(row['split'], row['case_id'], row['side'])]
        assert linked['run_id'] == f'{row["split"]}:quality:{linked["arm"]}:run'
        assert (row['answer_text'] is None) == (linked['arm'] == 'candidate')
        assert 'tool_result_id' not in row['selected_sources'][0]
        assert 'result_item_id' not in row['selected_sources'][0]
    assert 'quality:baseline' not in json.dumps(display)
    assert 'quality:candidate' not in json.dumps(display)
