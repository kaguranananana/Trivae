"""验证调度配置和管理操作；所有文件均使用临时目录。"""

from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

from tests.test_ingestion import make_message, write_export

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_DIR / "scripts/macos/launchd_import.py"


@pytest.fixture
def manager() -> ModuleType:
    """加载独立运维脚本，不改变生产 package 的入口。"""

    spec = importlib.util.spec_from_file_location("trivae_launchd_import", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _options(manager: ModuleType, tmp_path: Path, command: str, *extra: str) -> list[str]:
    """每个测试为准备文件、启用文件和日志分配独立路径。"""

    options = [
        command,
        "--label",
        "com.trivae.test-import",
        "--plist-dir",
        str(tmp_path / "prepared"),
        "--launch-agents-dir",
        str(tmp_path / "LaunchAgents"),
    ]
    if command == "install":
        # 只用现有解释器做 help 预检；数据库路径始终属于 tmp_path。
        options.extend(
            [
                "--project-dir",
                str(PROJECT_DIR),
                "--raw-dir",
                str(tmp_path / "raw"),
                "--database",
                str(tmp_path / "canonical.sqlite3"),
                "--log-dir",
                str(tmp_path / "logs"),
            ]
        )
    return [*options, *extra]


def _missing() -> subprocess.CompletedProcess[str]:
    """保留真实 macOS launchctl 对不存在服务的退出码与诊断形状。"""

    return subprocess.CompletedProcess(
        ["/bin/launchctl", "print"], 113, "", 'Bad request.\nCould not find service "test" in domain for user gui\n'
    )


def _success(*arguments: str) -> subprocess.CompletedProcess[str]:
    """模拟成功系统调用，测试不注册真实 LaunchAgent。"""

    return subprocess.CompletedProcess(["/bin/launchctl", *arguments], 0, "", "")


def _preflight(monkeypatch: pytest.MonkeyPatch, manager: ModuleType) -> Mock:
    """使调度单元测试不启动 Trivae，更不会创建数据库。"""

    runner = Mock(return_value=_success())
    monkeypatch.setattr(manager.subprocess, "run", runner)
    return runner


def test_calendar_invokes_virtual_environment_without_polling(manager: ModuleType, tmp_path: Path) -> None:
    """日历、启动补偿和失败重试必须保存在可被系统读取的 plist 中。"""

    virtual_python = tmp_path / "project with spaces/.venv/bin/python"
    virtual_python.parent.mkdir(parents=True)
    virtual_python.symlink_to(PROJECT_DIR / ".venv/bin/python")
    document = manager.build_plist(
        project_dir=tmp_path / "project with spaces",
        python=virtual_python,
        raw_dir=tmp_path / "raw exports",
        database=tmp_path / "db/canonical.sqlite3",
        log_dir=tmp_path / "logs",
    )
    # 通过真实 plist 编解码检查 launchd 将读到的类型和数值。
    loaded = plistlib.loads(plistlib.dumps(document))
    assert loaded["StartCalendarInterval"] == [{"Hour": 10, "Minute": 30}, {"Hour": 22, "Minute": 30}]
    assert loaded["RunAtLoad"] is True
    assert loaded["KeepAlive"] == {"SuccessfulExit": False}
    assert loaded["ThrottleInterval"] == 300
    assert "StartInterval" not in loaded and "WatchPaths" not in loaded
    arguments = loaded["ProgramArguments"]
    assert arguments[:4] == [str(virtual_python), "-m", "trivae", "import-once"]
    assert "--update-indexes" in arguments
    assert arguments[arguments.index("--raw-dir") + 1] == str(tmp_path / "raw exports")
    assert arguments[arguments.index("--database") + 1] == str(tmp_path / "db/canonical.sqlite3")
    assert loaded["WorkingDirectory"] == str(tmp_path / "project with spaces")
    assert Path(loaded["StandardOutPath"]).is_absolute()
    assert Path(loaded["StandardErrorPath"]).is_absolute()
    assert loaded["EnvironmentVariables"]["PYTHONUNBUFFERED"] == "1"
    assert loaded["EnvironmentVariables"]["HF_HUB_OFFLINE"] == "1"


@pytest.mark.parametrize("update_indexes", [True, False])
def test_prepare_does_not_register_launchd_or_touch_database(
    manager: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    update_indexes: bool,
) -> None:
    """准备不自启、不碰数据库；索引默认开启，也允许显式选择只导入。"""

    preflight = _preflight(monkeypatch, manager)
    launchctl = Mock(side_effect=AssertionError("prepare must not call launchctl"))
    monkeypatch.setattr(manager, "_launchctl", launchctl)
    # 同时验证安装参数能传到 plist，而不只验证 build_plist 的默认值。
    extra = [] if update_indexes else ["--no-update-indexes"]
    assert manager.main(_options(manager, tmp_path, "install", *extra)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "prepared" and result["enabled"] is False
    assert result["update_indexes"] is update_indexes
    assert result["integration_required"] is not update_indexes
    prepared = tmp_path / "prepared/com.trivae.test-import.plist"
    assert prepared.is_file()
    document = plistlib.loads(prepared.read_bytes())
    assert ("--update-indexes" in document["ProgramArguments"]) is update_indexes
    assert (document["EnvironmentVariables"].get("HF_HUB_OFFLINE") == "1") is update_indexes
    assert not (tmp_path / "LaunchAgents").exists()
    assert not (tmp_path / "canonical.sqlite3").exists()
    assert not (tmp_path / "raw").exists()
    assert preflight.call_args.args[0] == [
        str(PROJECT_DIR / ".venv/bin/python"),
        "-m",
        "trivae",
        "import-once",
        "--help",
    ]
    assert preflight.call_args.kwargs["cwd"] == PROJECT_DIR
    launchctl.assert_not_called()


def test_enable_installs_and_bootstraps_only_explicitly(
    manager: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """显式启用才创建 LaunchAgents 配置并依赖 RunAtLoad 立即补查。"""

    _preflight(monkeypatch, manager)
    launchctl = Mock(side_effect=[_missing(), _success(), _success()])
    monkeypatch.setattr(manager, "_launchctl", launchctl)
    assert manager.main(_options(manager, tmp_path, "install", "--enable")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["enabled"] is True
    installed = tmp_path / "LaunchAgents/com.trivae.test-import.plist"
    assert installed.read_bytes() == (tmp_path / "prepared/com.trivae.test-import.plist").read_bytes()
    assert (tmp_path / "logs").is_dir()
    target = f"gui/{os.getuid()}/com.trivae.test-import"
    assert [call.args for call in launchctl.call_args_list] == [
        ("print", target),
        ("enable", target),
        ("bootstrap", f"gui/{os.getuid()}", str(installed)),
    ]
    assert not (tmp_path / "canonical.sqlite3").exists()


def test_enable_replaces_loaded_job_after_bootout(
    manager: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """修改配置前停止旧任务，避免留下仍运行旧参数的服务。"""

    _preflight(monkeypatch, manager)
    launchctl = Mock(side_effect=[_success(), _success(), _success(), _success()])
    monkeypatch.setattr(manager, "_launchctl", launchctl)
    assert manager.main(_options(manager, tmp_path, "install", "--enable")) == 0
    assert [call.args[0] for call in launchctl.call_args_list] == ["print", "bootout", "enable", "bootstrap"]


def test_invalid_entry_point_is_visible_and_leaves_no_config(
    manager: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """环境中缺少 import-once 时直接失败，不留下下次登录可加载的配置。"""

    preflight = _preflight(monkeypatch, manager)
    preflight.return_value = subprocess.CompletedProcess(
        ["python", "-m", "trivae"], 2, "", "invalid choice: import-once"
    )
    assert manager.main(_options(manager, tmp_path, "install")) == 1
    failure = json.loads(capsys.readouterr().err)
    assert failure["returncode"] == 2
    assert "invalid choice" in failure["stderr"]
    assert not (tmp_path / "prepared").exists()
    assert not (tmp_path / "LaunchAgents").exists()


def test_prepare_rejects_autoload_directory(
    manager: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """prepare 写入启用目录会在登录时自动启动，因此明确拒绝。"""

    arguments = _options(manager, tmp_path, "install", "--plist-dir", str(tmp_path / "LaunchAgents"))
    assert manager.main(arguments) == 1
    assert "outside Library/LaunchAgents" in capsys.readouterr().err
    assert not (tmp_path / "LaunchAgents").exists()


def test_status_retains_last_exit_code_without_claiming_import_success(
    manager: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """loaded 只表示服务存在，索引未集成的退出码必须保持可见。"""

    output = "state = waiting\nlast exit code = 2\nruns = 3\n"
    monkeypatch.setattr(manager, "_launchctl", Mock(return_value=subprocess.CompletedProcess([], 0, output, "")))
    assert manager.main(_options(manager, tmp_path, "status")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["loaded"] is True
    assert result["launchctl_output"] == output
    assert result["installed"] is False


def test_unexpected_launchctl_failure_is_not_reported_as_unloaded(
    manager: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """权限或域错误必须保留根因，不能转换为正常的未安装状态。"""

    monkeypatch.setattr(
        manager, "_launchctl", Mock(return_value=subprocess.CompletedProcess([], 1, "", "permission denied"))
    )
    assert manager.main(_options(manager, tmp_path, "status")) == 1
    assert "permission denied" in capsys.readouterr().err


def test_uninstall_preserves_raw_database_and_logs(
    manager: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """卸载仅移除本 label 的配置，不触碰业务数据和诊断证据。"""

    for directory in ("prepared", "LaunchAgents", "raw", "logs"):
        (tmp_path / directory).mkdir()
    prepared = tmp_path / "prepared/com.trivae.test-import.plist"
    installed = tmp_path / "LaunchAgents/com.trivae.test-import.plist"
    prepared.write_text("prepared")
    installed.write_text("installed")
    raw = tmp_path / "raw/export.json"
    raw.write_text("{}")
    database = tmp_path / "canonical.sqlite3"
    database.write_bytes(b"database placeholder")
    log = tmp_path / "logs/import.log"
    log.write_text("last failure")
    launchctl = Mock(side_effect=[_success(), _success()])
    monkeypatch.setattr(manager, "_launchctl", launchctl)
    assert manager.main(_options(manager, tmp_path, "uninstall")) == 0
    assert [call.args[0] for call in launchctl.call_args_list] == ["print", "bootout"]
    assert not installed.exists() and not prepared.exists()
    assert raw.read_text() == "{}" and database.read_bytes() == b"database placeholder"
    assert log.read_text() == "last failure"


def test_failed_bootout_preserves_configuration_for_diagnosis(
    manager: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """系统未能停止服务时不报告卸载成功，也不销毁排障所需的配置。"""

    installed = tmp_path / "LaunchAgents/com.trivae.test-import.plist"
    installed.parent.mkdir()
    installed.write_text("installed")
    launchctl = Mock(side_effect=[_success(), subprocess.CompletedProcess([], 1, "", "bootout failed")])
    monkeypatch.setattr(manager, "_launchctl", launchctl)
    assert manager.main(_options(manager, tmp_path, "uninstall")) == 1
    assert "bootout failed" in capsys.readouterr().err
    assert installed.read_text() == "installed"


@pytest.mark.parametrize("script", ["install-import.sh", "status-import.sh", "uninstall-import.sh"])
def test_shell_wrappers_are_runnable_from_another_directory(script: str, tmp_path: Path) -> None:
    """真实执行三个 wrapper 的 --help，不注册服务或连接数据库。"""

    completed = subprocess.run(
        [str(PROJECT_DIR / "scripts/macos" / script), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--label" in completed.stdout and "--plist-dir" in completed.stdout


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("TRIVAE_RUN_LAUNCHD_SMOKE") != "1",
    reason="显式设置 TRIVAE_RUN_LAUNCHD_SMOKE=1 才注册临时 macOS 测试服务",
)
def test_real_launchd_isolated_backlog_and_index_pending(tmp_path: Path) -> None:
    """真实装载、重装、补查和卸载；只操作唯一测试 label 和临时 SQLite。"""

    label = f"com.trivae.import-once-test.{os.getpid()}.{time.time_ns()}"
    python = PROJECT_DIR / ".venv/bin/python"
    paths = [
        "--label",
        label,
        "--plist-dir",
        str(tmp_path / "prepared"),
        "--launch-agents-dir",
        str(tmp_path / "LaunchAgents"),
    ]
    install_options = [
        "--project-dir",
        str(PROJECT_DIR),
        "--raw-dir",
        str(tmp_path / "raw"),
        "--database",
        str(tmp_path / "canonical.sqlite3"),
        "--log-dir",
        str(tmp_path / "logs"),
        "--settle-seconds",
        "0",
        "--min-age-seconds",
        "0",
        # smoke 只验证调度和持久补偿，不加载真实 embedding 模型。
        "--no-update-indexes",
    ]
    (tmp_path / "raw").mkdir()

    def manage(command: str, *extra: str) -> dict:
        """通过真实 CLI 执行，超时同样显式暴露，避免阻塞在系统调度中。"""

        completed = subprocess.run(
            [str(python), str(SCRIPT), command, *paths, *extra],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    def import_state() -> dict:
        """读取正式只读状态，断言数据库持久化与系统退出码一致。"""

        completed = subprocess.run(
            [str(python), "-m", "trivae", "import-once", "--database", str(tmp_path / "canonical.sqlite3"), "--status"],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    def wait_exit(expected: int) -> str:
        """只等短任务退出，不等待五分钟的正常失败节流。"""

        deadline = time.monotonic() + 20
        output = ""
        while time.monotonic() < deadline:
            output = str(manage("status")["launchctl_output"])
            if f"last exit code = {expected}\n" in output and not re.search(r"\bpid = ", output):
                return output
            time.sleep(0.1)
        raise AssertionError(f"launchd task did not finish: {output}")

    try:
        prepared = manage("install", *install_options)
        assert prepared["enabled"] is False
        assert not (tmp_path / "canonical.sqlite3").exists()
        assert not (tmp_path / "LaunchAgents").exists()
        manage("install", *install_options, "--enable")
        wait_exit(0)
        first_run = import_state()["last_run"]["run_id"]
        # 重装会重新 bootstrap，模拟登录补查；立即 kickstart 本身也会受到节流。
        manage("install", *install_options, "--enable")
        wait_exit(0)
        assert import_state()["last_run"]["run_id"] != first_run
        write_export(
            tmp_path / "raw",
            "synthetic.json",
            [make_message("launchd-smoke-1", 1, 1792140000, "isolated launchd smoke record")],
            chat_name="launchd-smoke",
            peer_uid="smoke-only",
            version="1.0",
        )
        manage("install", *install_options, "--enable")
        output = wait_exit(2)
        persisted = import_state()
        assert persisted["files"] == {"completed": 1}
        assert len(persisted["pending_indexes"]) == 2
        assert persisted["retrieval_readiness"] == "pending"
        assert "minimum runtime = 300" in output and "state = spawn scheduled" in output
        assert (tmp_path / "logs" / f"{label}.stderr.log").read_text() == ""
    finally:
        # 无论哪个断言失败，均清理本测试 label，绝不遗留自动任务。
        manage("uninstall")
        removed = manage("status")
        assert not removed["loaded"] and not removed["installed"] and not removed["prepared"]
