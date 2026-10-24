"""import-once 的薄 CLI Adapter；所有数据库操作属于 bootstrap/data。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from datetime import datetime

from trivae.bootstrap.import_indexes import create_import_index_updater
from trivae.bootstrap.ingestion import read_import_status, run_import_once
from trivae.data.ingestion.auto_import_contracts import ImportAlreadyRunning
from trivae.data.model import IngestionError
from trivae.digest.contracts import TIMEZONE


def configure_import_once_parser(subparsers: argparse._SubParsersAction) -> None:
    """仅声明参数，不在 help 或状态解析时创建任何资源。"""

    from pathlib import Path

    parser = subparsers.add_parser(
        "import-once", help="Import stable new/changed QCE files and recover unfinished work"
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    parser.add_argument("--settle-seconds", type=float, default=5, help="Interval between file stability samples")
    parser.add_argument(
        "--min-age-seconds", type=float, default=60, help="Required quiet period since last file change"
    )
    parser.add_argument("--status", action="store_true", help="Read persisted import/index status without writing")
    parser.add_argument("--digest-label", help="Start this independent digest LaunchAgent after successful evening import")
    parser.add_argument(
        "--update-indexes",
        action="store_true",
        help="Process committed new-data index work using the existing FTS/semantic builders",
    )


def run_import_once_command(args: argparse.Namespace) -> int:
    """输出一次调用的完整 JSON；失败保留 traceback 供 launchd stderr 排障。"""

    if args.status:
        print(json.dumps(read_import_status(args.database), ensure_ascii=False, indent=2))
        return 0
    # 正式调度显式打开索引处理；只读状态和手工 Canonical-only 入口不加载模型。
    updater = create_import_index_updater(args.database) if args.update_indexes else None
    if args.update_indexes:
        # 无人值守时将构建开始/完成事实写入 stderr 日志，长构建期间仍可定位阶段。
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        report = run_import_once(
            args.database,
            args.raw_dir,
            settle_seconds=args.settle_seconds,
            min_age_seconds=args.min_age_seconds,
            index_updater=updater,
        )
    except (IngestionError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "error", "error_code": getattr(exc, "error_code", type(exc).__name__), "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 75 if isinstance(exc, ImportAlreadyRunning) else 1
    except Exception:
        # 未知异常绝不转换为成功，正常 Python traceback 保留真实失败位置。
        logging.getLogger(__name__).exception("import-once failed")
        raise
    result = report.to_dict()
    if report.exit_code == 0 and args.digest_label and datetime.now(TIMEZONE).hour >= 22:
        # 独立 LaunchAgent 拥有模型、邮件及自己的退出码；导入不等待长时间的日报生成。
        target = f"gui/{os.getuid()}/{args.digest_label}"
        subprocess.run(["/bin/launchctl", "kickstart", target], check=True, capture_output=True, text=True)
        result["digest_dispatch"] = {"status": "started", "label": args.digest_label}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return report.exit_code
