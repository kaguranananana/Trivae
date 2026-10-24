"""日报的 Composition Root，复用现有模型配置及只读 Canonical 投影。"""

from __future__ import annotations

import fcntl
import json
import logging
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from trivae.config.settings import load_settings
from trivae.data.storage.sqlite_digest import SQLiteDigestState, read_digest_snapshot
from trivae.digest.contracts import TIMEZONE
from trivae.digest.generator import DigestGenerator
from trivae.digest.mail import MailSettings, send_digest_mail
from trivae.digest.render import write_digest_files
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

logger = logging.getLogger(__name__)


@contextmanager
def digest_lock(state_path: Path) -> Iterator[None]:
    """独立内核锁防止人工运行与导入触发同时生成或寄送同一期。"""

    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix(".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("另一项日报任务正在运行") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


async def generate_report(database: Path, directory: Path, *, run_id: str, start: int, end: int,
                          after_revision: int | None = None, resume: bool = False) -> dict[str, Any]:
    """先读完一致性快照，再惰性创建模型；不加载语义向量或另一套检索服务。"""

    snapshot = read_digest_snapshot(database, start_timestamp=start, end_timestamp=end, after_revision=after_revision)
    runtime: OpenAIAgentsRuntimeAdapter | None = None

    async def completion(prompt: str) -> Any:
        """沿用用户已配置的模型和登录状态，不新增 Provider 或凭据。"""

        nonlocal runtime
        if runtime is None:
            runtime = OpenAIAgentsRuntimeAdapter(settings=load_settings())
        return await runtime.complete_text_with_observation(prompt)

    try:
        report = await DigestGenerator(completion).generate(snapshot, directory, run_id=run_id, resume=resume)
        write_digest_files(report, directory)
        return report
    except Exception:
        # 原始失败完整保留后继续抛出；不会用空日报代替模型或格式错误。
        directory.mkdir(parents=True, exist_ok=True)
        # 续跑仍失败时追加新错误，保留第一次中断的现场。
        with (directory / "error.log").open("a", encoding="utf-8") as stream:
            stream.write(traceback.format_exc() + "\n")
        raise
    finally:
        if runtime is not None:
            await runtime.aclose()


def deliver_report(state: SQLiteDigestState, run_id: str, settings: MailSettings) -> dict[str, Any]:
    """复用已落盘正文发送，失败不推进水位；再次发送必须显式选择 run_id。"""

    run = state.get(run_id)
    if run["status"] == "sent":
        return {"status": "already_sent", "run_id": run_id}
    directory = Path(run["report_directory"])
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    subject, text, document = write_digest_files(report, directory)
    state.update(run_id, "sending")
    try:
        message_id = send_digest_mail(settings, subject=subject, text=text, document=document)
    except Exception as exc:
        state.update(run_id, "send_failed", error=f"{type(exc).__name__}: {exc}")
        (directory / "mail-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    # 邮件服务端已接受后才标记 sent；该事实与下一期读取水位使用同一行。
    state.update(run_id, "sent", sent_at=datetime.now(TIMEZONE).isoformat())
    return {"status": "sent", "run_id": run_id, "recipient": settings.recipient,
            "message_id": message_id, "report_directory": str(directory)}


async def run_daily_digest(database: Path, state_path: Path, output: Path, settings: MailSettings,
                           *, now: datetime | None = None) -> dict[str, Any]:
    """每个北京时间日期只发一期，只有成功邮件决定增量读取的起点。"""

    current = datetime.now(TIMEZONE) if now is None else now.astimezone(TIMEZONE)
    day = current.date().isoformat()
    with digest_lock(state_path):
        state = SQLiteDigestState(state_path)
        try:
            existing = state.latest(day)
            if existing is not None and existing["status"] == "sent":
                return {"status": "already_sent", "run_id": existing["run_id"]}
            pending = state.pending_delivery()
            if pending is not None:
                raise RuntimeError(f"已有待确认的日报 {pending['run_id']}，请查看 digest status 并显式使用 digest send")
            previous = state.last_sent()
            end = int(current.timestamp() * 1000)
            start = int((current - timedelta(days=1)).timestamp() * 1000) if previous is None else previous["end_timestamp"]
            first_start = state.first_window_start()
            if previous is None and first_start is not None:
                # 首次生成服务中断后，下一次运行继续原窗口，不能把失败当天的数据漏掉。
                start = min(start, first_start)
            after_revision = None if previous is None else previous["through_revision"]
            run_id = current.strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
            directory = output / run_id
            state.create(run_id, day, start, end, directory, current.isoformat())
            try:
                report = await generate_report(database, directory, run_id=run_id, start=start, end=end,
                                               after_revision=after_revision)
            except Exception as exc:
                state.update(run_id, "generation_failed", error=f"{type(exc).__name__}: {exc}")
                raise
            state.update(run_id, "ready", revision=report["revision"])
            return deliver_report(state, run_id, settings)
        finally:
            state.close()
