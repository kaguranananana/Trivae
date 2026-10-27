"""日报命令入口：样稿、正式运行、显式发送及只读状态。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

from trivae.bootstrap.digest import deliver_report, digest_lock, generate_report, run_daily_digest
from trivae.config.dotenv import load_environment_file
from trivae.data.storage.sqlite_digest import SQLiteDigestState
from trivae.digest.contracts import TIMEZONE
from trivae.digest.mail import MailSettings


def configure_digest_parser(subparsers: argparse._SubParsersAction) -> None:
    """help 与状态检查不读取模型凭据，也不初始化 Canonical 数据库。"""

    parser = subparsers.add_parser("digest", help="Generate and email the daily group-chat digest")
    commands = parser.add_subparsers(dest="digest_command", required=True)
    for name in ("preview", "run", "resume", "send", "status"):
        command = commands.add_parser(name)
        command.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
        command.add_argument("--state-database", type=Path)
        command.add_argument("--output-dir", type=Path, default=Path("data/digests"))
        if name != "status":
            command.add_argument("--env-file", type=Path)
        if name in ("run", "resume", "send"):
            command.add_argument("--mail-env-file", type=Path)
        if name == "run":
            command.add_argument("--delivery-day", type=date.fromisoformat, help="Explicit digest date for catch-up delivery")
        if name == "preview":
            command.add_argument("--date", type=date.fromisoformat, help="Beijing calendar date; default: last 24h")
            command.add_argument("--resume-from", type=Path, help="Explicitly continue this same preview and date")
        if name in ("resume", "send"):
            command.add_argument("--run-id", required=True)


def run_digest_command(args: argparse.Namespace) -> int:
    """失败保留 stderr traceback 和非零退出；不把未发出的样稿报告为推送完成。"""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    state_path = args.state_database or args.database.with_name(args.database.stem + ".digest.sqlite3")
    if args.digest_command == "status":
        if not state_path.is_file():
            print(json.dumps({"status": "not_initialized"}, ensure_ascii=False))
            return 0
        # 状态入口只查询已有表，不调用会建表的状态写入器。
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM digest_runs ORDER BY created_at DESC LIMIT 10").fetchall()
            print(json.dumps({"runs": [dict(row) for row in rows]}, ensure_ascii=False, indent=2))
        return 0
    load_environment_file(args.env_file)
    if args.digest_command == "preview":
        current = datetime.now(TIMEZONE)
        if args.date is None:
            start, end = current - timedelta(days=1), current
        else:
            start = datetime.combine(args.date, time.min, TIMEZONE)
            end = start + timedelta(days=1)
        run_id = args.resume_from.name if args.resume_from else "preview-" + current.strftime("%Y%m%d-%H%M%S-%f")
        directory = args.resume_from or args.output_dir / run_id
        report = asyncio.run(generate_report(args.database, directory, run_id=run_id,
                                             start=int(start.timestamp() * 1000), end=int(end.timestamp() * 1000),
                                             resume=args.resume_from is not None))
        result = {"status": "preview", "report_directory": str(directory.resolve()),
                  "items": len(report["items"]), "messages": report["root_message_count"],
                  "batches": report["batch_count"]}
    else:
        if args.mail_env_file is not None:
            load_environment_file(args.mail_env_file)
        # 发件配置先于任何收费生成校验，缺授权码时仍可独立运行 preview。
        settings = MailSettings.from_environment()
        if args.digest_command == "run":
            result = asyncio.run(run_daily_digest(args.database, state_path, args.output_dir, settings,
                                                   delivery_day=args.delivery_day))
        else:
            with digest_lock(state_path):
                state = SQLiteDigestState(state_path)
                try:
                    if args.digest_command == "resume":
                        run = state.get(args.run_id)
                        previous = state.last_sent()
                        report = asyncio.run(generate_report(
                            args.database, Path(run["report_directory"]), run_id=args.run_id,
                            start=run["start_timestamp"], end=run["end_timestamp"],
                            after_revision=None if previous is None else previous["through_revision"], resume=True,
                        ))
                        state.update(args.run_id, "ready", revision=report["revision"])
                    result = deliver_report(state, args.run_id, settings)
                finally:
                    state.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
