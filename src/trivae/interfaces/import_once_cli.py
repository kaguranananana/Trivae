"""import-once 的薄 CLI Adapter；所有数据库操作属于 bootstrap/data。"""

from __future__ import annotations

import argparse
import json
import logging

from trivae.bootstrap.ingestion import read_import_status, run_import_once
from trivae.data.ingestion.auto_import_contracts import ImportAlreadyRunning
from trivae.data.model import IngestionError


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


def run_import_once_command(args: argparse.Namespace) -> int:
    """输出一次调用的完整 JSON；失败保留 traceback 供 launchd stderr 排障。"""

    if args.status:
        print(json.dumps(read_import_status(args.database), ensure_ascii=False, indent=2))
        return 0
    try:
        report = run_import_once(
            args.database,
            args.raw_dir,
            settle_seconds=args.settle_seconds,
            min_age_seconds=args.min_age_seconds,
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
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return report.exit_code
