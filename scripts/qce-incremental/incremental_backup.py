#!/usr/bin/env python3
"""QCE 时间水位导出，并按需串行接入 Trivae 入库及索引；只使用标准库。"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
LOCK_PATH = ROOT / ".run.lock"
TOKEN_PATH = Path.home() / ".qq-chat-exporter/security.json"


class QCEUnavailable(RuntimeError):
    """仅连接尚未恢复允许等待；认证和业务错误直接暴露。"""


def log(message):
    """无人值守运行也保存带本机时区的阶段日志。"""
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}", flush=True)


def read_json(path):
    """配置或状态损坏直接报错，不重置已确认水位。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save_atomic(path, document):
    """完整写出并原子替换，进程中断不会留下半份游标。"""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate_config(cfg):
    """只校验执行依赖的配置，不猜测群号或重置错误参数。"""
    groups = cfg.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("config.json 的 groups 必须至少包含一个群")
    seen = set()
    for group in groups:
        group_id = str(group.get("id", "")).strip()
        if not group_id.isdecimal():
            raise ValueError("groups.id 必须是 QQ 群号")
        if group_id in seen:
            raise ValueError(f"群号重复: {group_id}")
        seen.add(group_id)
    for key in ("initial_lookback_hours", "overlap_minutes", "settle_minutes",
                "wait_for_api_minutes", "task_timeout_minutes"):
        if not isinstance(cfg.get(key), int) or cfg[key] < 0:
            raise ValueError(f"{key} 必须是非负整数")
    if not cfg.get("output_dir") or not Path(cfg["output_dir"]).is_absolute():
        raise ValueError("output_dir 必须明确设置为 Trivae raw 目录的绝对路径")
    if "initial_start_time" in cfg and not isinstance(cfg["initial_start_time"], int):
        raise ValueError("initial_start_time 必须为 Unix 秒")
    base = cfg.get("base_url", "http://127.0.0.1:40653").rstrip("/")
    # 沿用原脚本的本机 API 边界，不把本机 QCE Token 发送给其他主机。
    if not base.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("base_url 必须指向本机 QCE HTTP API")
    return base


def api(base, token, method, endpoint, body=None):
    """使用 QCE 本机 Bearer 会话；每个已接受的导出 POST 只发送一次。"""
    raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(base + endpoint, data=raw, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    try:
        with urlopen(request, timeout=30) as response:
            document = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"QCE HTTP {exc.code}: {exc.read(2048).decode('utf-8', 'replace')}") from exc
    except (URLError, TimeoutError) as exc:
        raise QCEUnavailable(f"无法连接 QCE: {exc}") from exc
    if not isinstance(document, dict) or document.get("success") is not True:
        raise RuntimeError(f"QCE API 返回错误: {str(document)[:1000]}")
    return document["data"]


def wait_for_qce(base, token, max_minutes):
    """休眠后只等待连接恢复，401 等实际错误立即交给用户处理。"""
    deadline = time.monotonic() + max_minutes * 60
    while True:
        try:
            api(base, token, "GET", "/api/tasks")
            return
        except QCEUnavailable as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise QCEUnavailable(f"QCE 未就绪，已等待 {max_minutes} 分钟") from exc
            log(f"等待 QCE 连接恢复：{exc}")
            time.sleep(min(15, remaining))


def check_file(task, group_id):
    """QCE 终态、JSON、条数和群身份均通过后才允许提交导出水位。"""
    if not task.get("filePath"):
        raise RuntimeError("任务完成但没有返回 filePath")
    path = Path(task["filePath"])
    if path.suffix.lower() != ".json" or not path.is_file():
        raise RuntimeError(f"导出结果不是 JSON 文件: {path}")
    document = read_json(path)
    if not isinstance(document, dict) or not isinstance(document.get("messages"), list):
        raise RuntimeError(f"文件缺少 QCE JSON messages 数组: {path}")
    count = len(document["messages"])
    if task.get("messageCount") != count:
        raise RuntimeError(f"导出消息数不一致：任务 {task.get('messageCount')}，文件 {count}")
    actual = document.get("chatInfo", {}).get("peerUid")
    # 既有 QCE 格式中 peerUid 可选；存在时必须与目标群一致。
    if actual is not None and str(actual) != group_id:
        raise RuntimeError(f"导出文件群号不符：期望 {group_id}，实际 {actual}")
    return path, count


def export_group(base, token, group_id, name, start, end, cfg, *, pending=None, on_created=None):
    """恢复已经提交的任务；只有不存在待处理任务时才创建新导出。"""
    if pending is None:
        body = {
            "peer": {"chatType": 2, "peerUid": group_id, "guildId": ""},
            "sessionName": name,
            "format": "JSON",
            "filter": {"startTime": start, "endTime": end},
            "options": {
                "prettyFormat": False, "includeSystemMessages": True,
                "includeResourceLinks": True, "preferGroupMemberName": True,
                # 本机 QCE 的此选项实际控制跳过资源下载，仍保留消息结构及资源链接。
                "filterPureImageMessages": cfg.get("skip_resource_downloads", True),
                "outputDir": cfg["output_dir"],
            },
        }
        result = api(base, token, "POST", "/api/messages/export", body)
        task_id = result.get("taskId")
        if not task_id:
            raise RuntimeError("QCE 未返回 taskId")
        # 接到 taskId 立即持久化；后续超时或进程退出都继续查询同一个任务。
        pending = {"task_id": task_id, "start_time": start, "end_time": end}
        if on_created:
            on_created(pending)
    task_id = pending["task_id"]
    deadline = time.monotonic() + cfg["task_timeout_minutes"] * 60
    while True:
        task = api(base, token, "GET", "/api/tasks/" + task_id)
        status = task.get("status")
        if status == "completed":
            path, count = check_file(task, group_id)
            return task_id, path, count
        if status in ("failed", "cancelled", "partial"):
            raise RuntimeError(f"任务 {task_id} 状态 {status}: {task.get('error') or task.get('message')}")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"等待任务 {task_id} 超时；保留 taskId，下次恢复查询")
        time.sleep(3)


def run_import(args, cfg):
    """导出结束才串行执行正式导入入口，复用数据库锁及持久索引待办。"""
    command = [sys.executable, "-m", "trivae", "import-once", "--raw-dir", cfg["output_dir"],
               "--database", str(args.database), "--settle-seconds", str(args.settle_seconds),
               "--min-age-seconds", str(args.min_age_seconds)]
    if args.update_indexes:
        command.append("--update-indexes")
    if args.digest_label:
        command.extend(("--digest-label", args.digest_label))
    log("开始 Trivae 入库及索引补偿")
    return subprocess.run(command, cwd=PROJECT, check=False).returncode


def main():
    """逐群提交成功水位；部分失败仍让成功文件进入原有导入主链路。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--then-import", action="store_true")
    parser.add_argument("--database", type=Path, default=PROJECT / "data/trivae.sqlite3")
    parser.add_argument("--settle-seconds", type=float, default=5)
    parser.add_argument("--min-age-seconds", type=float, default=60)
    parser.add_argument("--update-indexes", action="store_true")
    parser.add_argument("--digest-label")
    args = parser.parse_args()
    config_path = args.config.expanduser().resolve() if args.config else CONFIG_PATH
    # 每个配置独占同目录的水位和锁，移动项目时不会读到其他部署的进度。
    state_path = config_path.with_name("state.json") if args.config else STATE_PATH
    lock_path = config_path.with_name(".run.lock") if args.config else LOCK_PATH
    cfg = read_json(config_path)
    base = validate_config(cfg)
    if args.status:
        print(json.dumps(read_json(state_path) if state_path.exists() else
                         {"version": 1, "progress": {}}, ensure_ascii=False, indent=2))
        return 0
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("已有导出流水线运行，本轮退出 75，等待系统补偿")
            return 75
        # 必须先持有锁再读状态，否则可能覆盖前一个进程刚提交的新水位。
        state = read_json(state_path) if state_path.exists() else {"version": 1, "progress": {}}
        progress = state["progress"]
        now = int(time.time())
        end = now - cfg["settle_minutes"] * 60
        jobs = []
        for group in cfg["groups"]:
            gid = str(group["id"]).strip()
            previous = progress.get(gid, {}).get("end_time")
            # 只有第一次使用初始起点，以后始终从上次成功水位减去重叠区间补齐。
            start = (cfg.get("initial_start_time", now - cfg["initial_lookback_hours"] * 3600)
                     if previous is None else previous - cfg["overlap_minutes"] * 60)
            pending = progress.get(gid, {}).get("pending")
            if pending:
                start, stop = pending["start_time"], pending["end_time"]
            else:
                stop = end
            if start < stop:
                jobs.append((gid, group.get("name") or gid, max(0, start), stop, pending))
        if args.dry_run:
            for gid, name, start, stop, pending in jobs:
                begin = datetime.fromtimestamp(start).astimezone().isoformat(timespec="seconds")
                finish = datetime.fromtimestamp(stop).astimezone().isoformat(timespec="seconds")
                log(f"[dry-run] {name} ({gid}): {begin} ~ {finish}; pending={pending is not None}")
            return 0
        token = read_json(TOKEN_PATH)["accessToken"]
        wait_for_qce(base, token, cfg["wait_for_api_minutes"])
        failed = 0
        completed_files = []
        for gid, name, start, stop, pending in jobs:
            log(f"开始导出 {name} ({gid}): {start} ~ {stop}")

            def persist_pending(task):
                # 保留旧成功水位并单独记录在途区间，失败不推进 end_time。
                progress.setdefault(gid, {})["pending"] = task
                save_atomic(state_path, state)

            try:
                # 已明确失败/取消的终态允许下一次重新创建；在途任务继续原 taskId。
                if pending:
                    task = api(base, token, "GET", "/api/tasks/" + pending["task_id"])
                    if task["status"] in ("failed", "cancelled", "partial"):
                        log(f"原任务 {pending['task_id']} 已终止，重新导出未提交区间")
                        pending = None
                tid, path, count = export_group(base, token, gid, name, start, stop, cfg,
                                               pending=pending, on_created=persist_pending)
                # 验证成功才替换整群状态，同时清除已完成的 pending。
                progress[gid] = {"end_time": stop, "last_task_id": tid, "last_file": str(path),
                                 "last_count": count, "updated_at": datetime.now().astimezone().isoformat()}
                save_atomic(state_path, state)
                completed_files.append(path)
                log(f"完成 {name}: {count} 条，{path.name}")
            except (RuntimeError, OSError, ValueError):
                failed += 1
                traceback.print_exc()
                log(f"失败 {name} ({gid})，成功水位未推进")
        # 恢复旧在途任务后如仍落后本次截止时间，显式请求 launchd 再补一次。
        behind = any(progress.get(str(g["id"]), {}).get("end_time", 0) < end for g in cfg["groups"])
        # 导出部分成功仍可入库，但不提前发出缺群或落后窗口的日报。
        if args.then_import:
            if completed_files and args.min_age_seconds > 0:
                # 刚导出的文件必须先满足原导入器的静置契约，否则每轮都会产生新的 deferred。
                latest_write = max(path.stat().st_mtime for path in completed_files)
                remaining = args.min_age_seconds - (time.time() - latest_write)
                if remaining > 0:
                    log(f"等待导出文件静置 {remaining:.1f} 秒，再执行入库")
                    time.sleep(remaining)
            if failed or behind:
                args.digest_label = None
            result = run_import(args, cfg)
            if result:
                return result
        log(f"本轮结束：成功 {len(jobs) - failed} 群，失败 {failed} 群，仍待补齐={behind}")
        return 1 if failed else (75 if behind else 0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, KeyError):
        traceback.print_exc()
        sys.exit(1)
