"""Trivae CLI：只做参数解析、Application 调用和结果投影。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from trivae.bootstrap.application import create_application
from trivae.data.model import IngestionError


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI parser，不在 import 时初始化数据库或外部服务。"""

    parser = argparse.ArgumentParser(prog="trivae", description="Trivae high-noise chat intelligence system")
    subparsers = parser.add_subparsers(dest="command")
    import_parser = subparsers.add_parser("import", help="Import QQ chat exports into the Canonical Store")
    import_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory containing QQChatExporter JSON files",
    )
    import_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/trivae.sqlite3"),
        help="SQLite Canonical Store path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行 CLI；已分类 ingestion error 转成非零状态，未知异常继续暴露。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "import":
        parser.print_help()
        return 0

    try:
        # Application 负责 lifecycle，CLI 不直接创建 Parser/Store，也不复制导入语义。
        with create_application(args.database) as application:
            summary = application.import_directory(args.raw_dir)
    except IngestionError as exc:
        # 已分类错误需要给调用方可读信息；未知异常不在这里被吞掉。
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 1 if summary.has_errors else 0
