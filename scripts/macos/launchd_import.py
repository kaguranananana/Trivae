#!/usr/bin/env python3
"""准备和管理本地 QCE 增量导入的 macOS LaunchAgent，不包含导入业务。"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_LABEL = "com.trivae.import-once"
DEFAULT_DIGEST_LABEL = "com.trivae.daily-digest"
PROJECT_DIRECTORY = Path(__file__).resolve().parents[2]
LAUNCHCTL = "/bin/launchctl"


def _absolute(value: str | Path) -> Path:
    """固定配置路径，使 launchd 不依赖交互式 shell 的当前目录。"""

    return Path(value).expanduser().resolve()


def build_plist(
    *,
    project_dir: Path,
    python: Path,
    raw_dir: Path,
    database: Path,
    log_dir: Path,
    label: str = DEFAULT_LABEL,
    settle_seconds: float = 5,
    min_age_seconds: float = 60,
    update_indexes: bool = True,
    digest_label: str | None = None,
) -> dict[str, object]:
    """构造只调用正式 import-once 入口的日历调度配置。"""

    # Python 保留 .venv 路径而不解引用软链接，确保解释器读取该虚拟环境。
    python_path = python.expanduser().absolute()
    # 参数逐项传递，不经 shell 展开，目录中的空格也保持为同一个参数。
    arguments = [
        str(python_path),
        "-m",
        "trivae",
        "import-once",
        "--raw-dir",
        str(_absolute(raw_dir)),
        "--database",
        str(_absolute(database)),
        "--settle-seconds",
        str(settle_seconds),
        "--min-age-seconds",
        str(min_age_seconds),
    ]
    environment = {"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
    if digest_label:
        # 只在正式导入成功后唤起独立日报，不再安排一个可能抢先运行的固定发信时间。
        arguments.extend(("--digest-label", digest_label))
    # 正式调度同时补偿已提交批次的索引工作，避免只入库却持续无法检索。
    if update_indexes:
        arguments.append("--update-indexes")
        # 本机模型缓存已验证可用，调度显式离线读取；缓存缺失仍由构建器报告失败。
        environment["HF_HUB_OFFLINE"] = "1"
    # 两个日历事件采用机器本地时区，与用户设置的每天导出时间保持一致。
    calendar = [{"Hour": 10, "Minute": 30}, {"Hour": 22, "Minute": 30}]
    return {
        "Label": label,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(_absolute(project_dir)),
        "StartCalendarInterval": calendar,
        # 登录或重启后登录时补查全部积压，不依赖任务错过了哪一个时间点。
        "RunAtLoad": True,
        # import-once 的非零退出表示导入失败、写入中或索引尚未补齐，需要补偿。
        "KeepAlive": {"SuccessfulExit": False},
        # 连续失败最多每五分钟再启动一次；没有每十五分钟扫描的 StartInterval。
        "ThrottleInterval": 300,
        # 直接追加两份日志，使无 Web UI 的执行结果和 traceback 均可检查。
        "StandardOutPath": str(_absolute(log_dir) / f"{label}.stdout.log"),
        "StandardErrorPath": str(_absolute(log_dir) / f"{label}.stderr.log"),
        "EnvironmentVariables": environment,
    }


def build_digest_plist(*, project_dir: Path, python: Path, database: Path, log_dir: Path,
                       mail_env_file: Path, label: str = DEFAULT_DIGEST_LABEL) -> dict[str, object]:
    """日报按需启动，邮件失败保留状态和日志，不自动反复发送。"""

    return {
        "Label": label,
        "ProgramArguments": [str(python.expanduser().absolute()), "-m", "trivae", "digest", "run",
                             "--database", str(_absolute(database)), "--mail-env-file", str(_absolute(mail_env_file))],
        "WorkingDirectory": str(_absolute(project_dir)),
        # 安装和登录都不提前发信；只有晚间导入确认完成后才 kickstart。
        "RunAtLoad": False,
        "StandardOutPath": str(_absolute(log_dir) / f"{label}.stdout.log"),
        "StandardErrorPath": str(_absolute(log_dir) / f"{label}.stderr.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"},
    }


def _write_plist(path: Path, document: dict[str, object]) -> None:
    """同目录原子替换 plist，避免留下写入一半的调度配置。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件放在目标目录，保证最后一次替换不会跨文件系统。
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".plist", delete=False) as stream:
        temporary_path = Path(stream.name)
        try:
            # plistlib 负责 XML 转义，避免手工模板破坏包含特殊字符的绝对路径。
            plistlib.dump(document, stream, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
            # launchd 在后续登录时需要可读取这个普通用户配置文件。
            temporary_path.chmod(0o644)
            os.replace(temporary_path, path)
        finally:
            # 失败只清理本次临时文件，原有配置仍保持不变。
            temporary_path.unlink(missing_ok=True)


def _launchctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    """保留 launchctl 原始输出；未知错误由调用层明确抛出。"""

    return subprocess.run([LAUNCHCTL, *arguments], text=True, capture_output=True, check=False)


def _require_success(result: subprocess.CompletedProcess[str]) -> None:
    """把系统操作失败连同 stdout/stderr 暴露给操作者。"""

    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)


def _job_status(target: str) -> subprocess.CompletedProcess[str]:
    """只将 launchctl 的服务不存在识别为空状态，不掩盖其他系统错误。"""

    result = _launchctl("print", target)
    # macOS launchctl 对不存在的 gui 服务返回 113，并在 stderr 说明找不到服务。
    missing = result.returncode == 113 and "Could not find service" in result.stderr
    if result.returncode != 0 and not missing:
        _require_success(result)
    return result


def _paths(args: argparse.Namespace) -> tuple[Path, Path, str]:
    """让三个操作使用同一 label 与配置位置。"""

    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", args.label) is None:
        raise ValueError("label must contain only letters, digits, dots and hyphens")
    prepared = _absolute(args.plist_dir) / f"{args.label}.plist"
    installed = _absolute(args.launch_agents_dir) / f"{args.label}.plist"
    # 同一登录用户的 gui 域可获得 Downloads 访问权限；不使用系统级 LaunchDaemon。
    target = f"gui/{os.getuid()}/{args.label}"
    return prepared, installed, target


def install(args: argparse.Namespace) -> dict[str, object]:
    """默认仅准备；显式 --enable 才注册并立即启动 LaunchAgent。"""

    prepared, installed, target = _paths(args)
    # 准备目录必须位于 LaunchAgents 之外，否则下次登录会绕过 --enable 提前执行。
    if prepared.parent == installed.parent or prepared.parent == (Path.home() / "Library/LaunchAgents").resolve():
        raise ValueError("prepared plist directory must be outside Library/LaunchAgents")
    project_dir = _absolute(args.project_dir)
    # 不 resolve Python 软链接，保留 .venv 对依赖环境的选择。
    python = Path(args.python).expanduser().absolute() if args.python else project_dir / ".venv/bin/python"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError(f"Python environment is not executable: {python}; run uv sync in the project first")
    # --help 只校验可安装入口；这里不打开数据库，也不执行任何文件导入。
    preflight = subprocess.run(
        [str(python), "-m", "trivae", "digest" if args.job == "digest" else "import-once", "--help"],
        cwd=project_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    _require_success(preflight)
    raw_dir = _absolute(args.raw_dir) if args.raw_dir else project_dir / "data/raw"
    database = _absolute(args.database) if args.database else project_dir / "data/trivae.sqlite3"
    log_dir = _absolute(args.log_dir)
    document = build_digest_plist(
        project_dir=project_dir, python=python, database=database, log_dir=log_dir,
        mail_env_file=Path(args.mail_env_file) if args.mail_env_file else project_dir / ".env.digest", label=args.label,
    ) if args.job == "digest" else build_plist(
        project_dir=project_dir,
        python=python,
        raw_dir=raw_dir,
        database=database,
        log_dir=log_dir,
        label=args.label,
        settle_seconds=args.settle_seconds,
        min_age_seconds=args.min_age_seconds,
        update_indexes=args.update_indexes,
        digest_label=args.digest_label,
    )
    _write_plist(prepared, document)
    result: dict[str, object] = {
        "status": "prepared",
        "enabled": False,
        "label": args.label,
        "prepared_plist": str(prepared),
        "installed_plist": str(installed),
        "database": str(database),
        "raw_dir": str(raw_dir),
        "log_dir": str(log_dir),
        "update_indexes": args.update_indexes,
        # 这里只说明是否装配索引 updater，不代表生产检索已经验收完成。
        "integration_required": not args.update_indexes,
    }
    if args.job == "digest":
        # 日报不承担文件导入或索引工作，准备结果只描述它实际使用的配置。
        for key in ("raw_dir", "update_indexes", "integration_required"):
            result.pop(key)
        result["mail_env_file"] = str(_absolute(args.mail_env_file or project_dir / ".env.digest"))
    if not args.enable:
        return result
    # 仅显式启用才创建运行日志目录并变更 launchd；prepare 不留下自启动入口。
    log_dir.mkdir(parents=True, exist_ok=True)
    current = _job_status(target)
    if current.returncode == 0:
        # 更新同一任务前先停止旧进程，让核心数据库锁控制并发导入边界。
        _require_success(_launchctl("bootout", target))
    _write_plist(installed, document)
    # enable 清除该用户之前手动 disable 同一 label 的状态。
    _require_success(_launchctl("enable", target))
    # RunAtLoad 会立即补查全部输入，因此只有显式 --enable 才执行此系统操作。
    _require_success(_launchctl("bootstrap", f"gui/{os.getuid()}", str(installed)))
    result.update(status="enabled", enabled=True)
    return result


def status(args: argparse.Namespace) -> dict[str, object]:
    """输出系统任务状态；消息导入与索引状态由正式 --status 命令读取。"""

    prepared, installed, target = _paths(args)
    current = _job_status(target)
    return {
        "label": args.label,
        "service_target": target,
        "prepared_plist": str(prepared),
        "installed_plist": str(installed),
        "prepared": prepared.exists(),
        "installed": installed.exists(),
        "loaded": current.returncode == 0,
        # 保留 runs、state、last exit code 等系统事实，不把 loaded 等同于成功导入。
        "launchctl_output": current.stdout if current.returncode == 0 else current.stderr,
    }


def uninstall(args: argparse.Namespace) -> dict[str, object]:
    """停止并删除本任务配置，保留所有数据库、输入文件和日志。"""

    prepared, installed, target = _paths(args)
    current = _job_status(target)
    if current.returncode == 0:
        # 必须先确认 bootout 成功，再删除配置，失败时仍可用原 plist 排障。
        _require_success(_launchctl("bootout", target))
    installed.unlink(missing_ok=True)
    prepared.unlink(missing_ok=True)
    return {"status": "uninstalled", "label": args.label, "logs_preserved": True}


def _parser() -> argparse.ArgumentParser:
    """三个操作共享可隔离的路径参数，便于测试任务和后续集成。"""

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("install", "status", "uninstall"):
        subparser = commands.add_parser(command)
        subparser.add_argument("--job", choices=("import", "digest"), default="import")
        subparser.add_argument("--label", default=DEFAULT_LABEL)
        subparser.add_argument("--plist-dir", default=Path.home() / "Library/Application Support/Trivae/launchd")
        subparser.add_argument("--launch-agents-dir", default=Path.home() / "Library/LaunchAgents")
        if command == "install":
            subparser.add_argument("--project-dir", default=PROJECT_DIRECTORY)
            subparser.add_argument("--python", help="default: PROJECT/.venv/bin/python")
            subparser.add_argument("--raw-dir")
            subparser.add_argument("--database")
            subparser.add_argument("--digest-label", help="Wake the independent digest worker after evening import")
            subparser.add_argument("--mail-env-file", help="Digest SMTP configuration file; default: PROJECT/.env.digest")
            subparser.add_argument("--log-dir", default=Path.home() / "Library/Logs/Trivae")
            subparser.add_argument("--settle-seconds", type=float, default=5)
            subparser.add_argument("--min-age-seconds", type=float, default=60)
            subparser.add_argument(
                "--update-indexes",
                action=argparse.BooleanOptionalAction,
                default=True,
                help="update pending indexes by default; use --no-update-indexes for isolated import-only runs",
            )
            subparser.add_argument(
                "--enable", action="store_true", help="register and immediately run the prepared LaunchAgent"
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    """输出可保存的 JSON；系统错误保留具体命令和原始错误内容。"""

    args = _parser().parse_args(argv)
    if args.job == "digest" and args.label == DEFAULT_LABEL:
        # 沿用原管理器的安装、状态和卸载逻辑，日报使用独立 label 与日志。
        args.label = DEFAULT_DIGEST_LABEL
    try:
        if args.command == "install":
            result = install(args)
        elif args.command == "status":
            result = status(args)
        else:
            result = uninstall(args)
    except subprocess.CalledProcessError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "command": error.cmd,
                    "returncode": error.returncode,
                    "stdout": error.stdout,
                    "stderr": error.stderr,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError) as error:
        print(
            json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
