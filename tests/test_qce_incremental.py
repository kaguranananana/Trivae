"""验证导出时间水位、休眠补偿及实际流水线边界，不使用私人聊天。"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/qce-incremental/incremental_backup.py'


@pytest.fixture
def backup(tmp_path, monkeypatch):
    """每次加载使用独立配置、游标和锁，避免操作生产任务。"""
    spec = importlib.util.spec_from_file_location('qce_incremental_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cfg = json.loads(SCRIPT.with_name('config.example.json').read_text())
    cfg['groups'] = [{'id': '100', 'name': '测试群'}]
    cfg['output_dir'] = str(tmp_path / 'raw')
    monkeypatch.setattr(module, 'CONFIG_PATH', tmp_path / 'config.json')
    monkeypatch.setattr(module, 'STATE_PATH', tmp_path / 'state.json')
    monkeypatch.setattr(module, 'LOCK_PATH', tmp_path / '.lock')
    monkeypatch.setattr(module, 'TOKEN_PATH', tmp_path / 'security.json')
    module.CONFIG_PATH.write_text(json.dumps(cfg))
    module.TOKEN_PATH.write_text(json.dumps({'accessToken': 'test-token'}))
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT)])
    monkeypatch.setattr(module.time, 'time', lambda: 1_000_000)
    module.original_wait_for_qce = module.wait_for_qce
    monkeypatch.setattr(module, 'wait_for_qce', lambda *args: None)
    return module


def test_state_is_read_after_lock(backup, monkeypatch, capsys):
    """等待拿锁时前一个进程已提交的水位必须生效，不能用锁外的旧状态覆盖。"""
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--dry-run'])
    monkeypatch.setattr(backup.fcntl, 'flock', lambda *args: backup.STATE_PATH.write_text(
        json.dumps({'version': 1, 'progress': {'100': {'end_time': 900_000}}})))
    assert backup.main() == 0
    assert backup.datetime.fromtimestamp(898_200).astimezone().isoformat(timespec='seconds') in capsys.readouterr().out


def test_file_count_mismatch_does_not_advance(backup, tmp_path):
    """QCE 已完成但实际文件少于报告条数时必须报错，不能提交不完整水位。"""
    path = tmp_path / 'partial.json'
    path.write_text(json.dumps({'chatInfo': {'peerUid': '100'}, 'messages': [{}]}))
    with pytest.raises(RuntimeError, match='消息数'):
        backup.check_file({'filePath': str(path), 'messageCount': 2}, '100')


def test_sleep_gap_uses_last_success_not_lookback(backup, monkeypatch):
    """即使错过多天，仍从上次成功水位补齐，不把缺口裁成最近 72 小时。"""
    backup.STATE_PATH.write_text(json.dumps({'version': 1, 'progress': {'100': {'end_time': 100_000}}}))
    captured = []

    def export(*args, **kwargs):
        captured.append((args[4], args[5]))
        return 'task-1', Path('result.json'), 0

    monkeypatch.setattr(backup, 'export_group', export)
    assert backup.main() == 0
    assert captured == [(98_200, 999_100)]
    assert backup.read_json(backup.STATE_PATH)['progress']['100']['end_time'] == 999_100


def test_export_failure_keeps_success_cursor(backup, monkeypatch):
    """任务异常明确非零退出，失败群仍停留在原成功水位。"""
    original = {'version': 1, 'progress': {'100': {'end_time': 100_000}}}
    backup.STATE_PATH.write_text(json.dumps(original))

    def fail(*args, **kwargs):
        raise RuntimeError('QCE 导出失败')

    monkeypatch.setattr(backup, 'export_group', fail)
    assert backup.main() == 1
    assert backup.read_json(backup.STATE_PATH) == original


def test_pending_task_is_resumed_without_second_post(backup, monkeypatch, tmp_path):
    """进程中断或轮询超时后复用原 taskId，成功后再补剩余区间。"""
    path = tmp_path / 'export.json'
    path.write_text(json.dumps({'messages': [], 'chatInfo': {'peerUid': '100'}}))
    pending = {'task_id': 'accepted-1', 'start_time': 98_200, 'end_time': 800_000}
    backup.STATE_PATH.write_text(json.dumps({'version': 1, 'progress': {
        '100': {'end_time': 100_000, 'pending': pending}}}))
    calls = []

    def api(base, token, method, endpoint, body=None):
        calls.append((method, endpoint))
        return {'status': 'completed', 'filePath': str(path), 'messageCount': 0}

    monkeypatch.setattr(backup, 'api', api)
    assert backup.main() == 75
    assert calls == [('GET', '/api/tasks/accepted-1'), ('GET', '/api/tasks/accepted-1')]
    assert backup.read_json(backup.STATE_PATH)['progress']['100']['end_time'] == 800_000
    assert 'pending' not in backup.read_json(backup.STATE_PATH)['progress']['100']


def test_timeout_persists_accepted_task(backup, monkeypatch):
    """首次查询即超时时，已被 QCE 接受的任务必须仍可恢复。"""
    cfg = backup.read_json(backup.CONFIG_PATH)
    cfg['task_timeout_minutes'] = 0
    backup.CONFIG_PATH.write_text(json.dumps(cfg))
    monkeypatch.setattr(backup, 'api', lambda base, token, method, endpoint, body=None:
                        {'taskId': 'accepted-2'} if method == 'POST' else {'status': 'running'})
    assert backup.main() == 1
    saved = backup.read_json(backup.STATE_PATH)['progress']['100']
    assert saved['pending']['task_id'] == 'accepted-2'
    assert saved.get('end_time') is None


def test_export_request_retains_resource_links(backup, monkeypatch, tmp_path):
    """跳过附件下载仍保留资源链接，并把完成文件写入项目 raw 目录。"""
    cfg = backup.read_json(backup.CONFIG_PATH)
    path = tmp_path / 'export.json'
    path.write_text(json.dumps({'messages': [], 'chatInfo': {'peerUid': '100'}}))
    requests = []

    def api(base, token, method, endpoint, body=None):
        requests.append((method, body))
        return ({'taskId': 'new-1'} if method == 'POST' else
                {'status': 'completed', 'filePath': str(path), 'messageCount': 0})

    monkeypatch.setattr(backup, 'api', api)
    backup.export_group('local', 'token', '100', '测试群', 1, 2, cfg)
    options = requests[0][1]['options']
    assert options['includeResourceLinks'] is True
    assert options['filterPureImageMessages'] is True
    assert options['outputDir'] == cfg['output_dir']
    assert requests[0][1]['filter'] == {'startTime': 1, 'endTime': 2}


def test_auth_error_is_not_retried(backup, monkeypatch):
    """认证失效无需等十分钟，直接保留原错误。"""
    calls = []

    def api(*args):
        calls.append(args)
        raise RuntimeError('QCE HTTP 401')

    monkeypatch.setattr(backup, 'api', api)
    with pytest.raises(RuntimeError, match='401'):
        backup.original_wait_for_qce('local', 'token', 10)
    assert len(calls) == 1


def test_pipeline_import_failure_is_not_success(backup, monkeypatch):
    """导出水位与入库状态各司其职，索引失败仍返回原非零码让系统补偿。"""
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--then-import', '--update-indexes', '--min-age-seconds', '0'])
    monkeypatch.setattr(backup, 'export_group', lambda *args, **kwargs: ('ok', Path('result.json'), 0))
    commands = []

    def run(command, **kwargs):
        from subprocess import CompletedProcess
        commands.append(command)
        return CompletedProcess(command, 2)

    monkeypatch.setattr(backup.subprocess, 'run', run)
    assert backup.main() == 2
    assert '--update-indexes' in commands[0]
    assert commands[0][1:4] == ['-m', 'trivae', 'import-once']
    assert backup.read_json(backup.STATE_PATH)['progress']['100']['end_time'] == 999_100


def test_pipeline_waits_for_import_quiet_period(backup, monkeypatch, tmp_path):
    """新导出不能每次因 60 秒门槛被延后，从而陷入永远导出/永远 deferred 的循环。"""
    import os
    path = tmp_path / 'result.json'
    path.write_text('{}')
    os.utime(path, (999_990, 999_990))
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--then-import'])
    monkeypatch.setattr(backup, 'export_group', lambda *args, **kwargs: ('ok', path, 0))
    waits = []
    monkeypatch.setattr(backup.time, 'sleep', waits.append)
    monkeypatch.setattr(backup, 'run_import', lambda *args: 0)
    assert backup.main() == 0
    assert waits == [50]


def test_pipeline_real_import_is_idempotent(backup, monkeypatch, tmp_path):
    """实际调用正式 CLI 两轮，把同一份 QCE 消息入库一次并保留真实索引待办。"""
    import sqlite3

    from tests.test_ingestion import make_message, write_export
    raw = Path(backup.read_json(backup.CONFIG_PATH)['output_dir'])
    raw.mkdir()
    path = write_export(raw, 'test(100).json', [make_message('one', 1, 1_790_000_000_000, '增量导入测试')],
                        chat_name='测试群', peer_uid='100', version='5.5.64')
    database = tmp_path / 'canonical.sqlite3'
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--then-import', '--database', str(database),
                                    '--settle-seconds', '0', '--min-age-seconds', '0'])
    monkeypatch.setattr(backup, 'export_group', lambda *args, **kwargs: ('ok', path, 1))
    assert backup.main() == 2
    assert backup.main() == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT count(*) FROM messages').fetchone()[0] == 1


def test_failed_group_does_not_dispatch_digest(backup, monkeypatch, tmp_path):
    """部分群失败可以导入成功文件，但不能把缺群窗口当作晚报就绪。"""
    cfg = backup.read_json(backup.CONFIG_PATH)
    cfg['groups'].append({'id': '200', 'name': '失败群'})
    backup.CONFIG_PATH.write_text(json.dumps(cfg))
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--then-import', '--min-age-seconds', '0',
                                    '--digest-label', 'com.trivae.daily-digest'])

    def export(*args, **kwargs):
        if args[2] == '200':
            raise RuntimeError('导出失败')
        return 'ok', tmp_path / 'result.json', 0

    dispatched = []
    monkeypatch.setattr(backup, 'export_group', export)
    monkeypatch.setattr(backup, 'run_import', lambda args, cfg: dispatched.append(args.digest_label) or 0)
    assert backup.main() == 1
    assert dispatched == [None]
    progress = backup.read_json(backup.STATE_PATH)['progress']
    assert progress['100']['end_time'] == 999_100
    assert '200' not in progress


def test_dry_run_does_not_call_qce_or_write_progress(backup, monkeypatch):
    """设置预览不创建导出任务或伪造成功水位。"""
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--dry-run'])

    def unexpected(*args):
        pytest.fail('预览不应调用 QCE')

    monkeypatch.setattr(backup, 'api', unexpected)
    assert backup.main() == 0
    assert not backup.STATE_PATH.exists()
