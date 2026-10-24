"""日报主链路回归：真实导入、增量覆盖、原文引用和邮件交付水位。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

import trivae.bootstrap.digest as bootstrap
from tests.test_ingestion import make_message, write_export
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_digest import SQLiteDigestState, read_digest_snapshot
from trivae.digest.contracts import TIMEZONE
from trivae.digest.generator import DigestGenerator, make_batches, make_excerpts, parse_items, parse_synthesis
from trivae.digest.mail import MailSettings, send_digest_mail
from trivae.digest.render import render_digest
from trivae.interfaces.cli import main
from trivae.query.completion import CompletionObservation, CompletionProviderError


def _import(database: Path, directory: Path, messages: list[dict], *, group: str = "12345", name: str = "技术群") -> None:
    """始终走真实 QQ Parser 和 SharedImporter，使修订及回复身份与产品一致。"""

    path = write_export(directory, f"群聊({group}).json", messages, chat_name=name, peer_uid=group, version="0.1.0")
    with SQLiteCanonicalStore(database) as store:
        summary = SharedImporter(store).import_paths((path,))
        assert not summary.has_errors


def _item(handle: str, quote: str) -> dict:
    """表达编辑层必要字段，不预设分数或每种方向的固定条数。"""

    return {"category": "practice", "title": "具体的实战经验", "summary": "部署方式有适用条件。",
            "why_it_matters": "可以结合实际项目判断。", "action": "阅读原始讨论。",
            "sources": [{"id": handle, "quote": quote}]}


def test_incremental_snapshot_keeps_late_messages_and_old_reply_parent(tmp_path: Path) -> None:
    """发言时间早于昨日截止的迟到消息也进入新一期，旧父消息只标作上下文。"""

    database = tmp_path / "chat.sqlite3"
    _import(database, tmp_path, [make_message("old", 1, 1000, "原来的部署方案")])
    previous = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    _import(database, tmp_path, [make_message("late", 2, 500, "迟到但有价值的经验"),
                                 make_message("reply", 3, 3000, "这个方案有条件", reply_to="old")])
    snapshot = read_digest_snapshot(database, start_timestamp=2000, end_timestamp=4000,
                                    after_revision=previous.revision)
    assert snapshot.root_count == 2
    assert {message.source_message_id for message in snapshot.messages} == {"old", "late", "reply"}
    excerpts = make_excerpts(snapshot)
    assert [item.message.source_message_id for item in excerpts if item.context_only] == ["old"]
    assert "这个方案有条件" in "\n".join(item.text for item in excerpts)


def test_forward_enrichment_enters_next_digest_without_new_canonical_root(tmp_path: Path) -> None:
    """原来未展开的转发补齐时，沿现有修订日志重新读到完整内部正文。"""

    database = tmp_path / "chat.sqlite3"
    root = make_message("forward", 1, 1000, "预览不能当正文", message_type="forward")
    root["content"]["elements"] = [{"type": "forward", "data": {"messages": []}}]
    _import(database, tmp_path, [root])
    old = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    assert old.missing_forward_paths
    root["content"]["elements"][0]["data"]["messages"] = [make_message("inside", 2, 900, "补齐的实战说明")]
    _import(database, tmp_path, [root])
    snapshot = read_digest_snapshot(database, start_timestamp=2000, end_timestamp=3000, after_revision=old.revision)
    assert snapshot.root_count == 1
    assert not snapshot.missing_forward_paths
    assert [item.text for item in make_excerpts(snapshot)] == ["补齐的实战说明"]


def test_long_text_is_fully_partitioned_and_batches_preserve_all_excerpts(tmp_path: Path) -> None:
    """长消息尾部及高消息量必须实际进入输入，不能只统计为已读取。"""

    database = tmp_path / "chat.sqlite3"
    text = "技术细节" * 8000 + "最后才提到关键限制"
    _import(database, tmp_path, [make_message("long", 1, 1000, text)])
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    excerpts = make_excerpts(snapshot)
    assert "".join(item.text for item in excerpts) == text
    batches = make_batches(excerpts, batch_chars=16000)
    assert len(batches) >= 3
    assert [item.handle for batch in batches for item in batch] == [item.handle for item in excerpts]
    assert "最后才提到关键限制" in batches[-1][-1].text


@pytest.mark.parametrize("kind", ["unknown_source", "invented_quote", "bad_json"])
def test_generator_exposes_invalid_model_output_and_keeps_raw_trace(tmp_path: Path, kind: str) -> None:
    """错误先落真实响应，再显式失败，不修JSON、不编来源、不生成假空日报。"""

    database = tmp_path / "chat.sqlite3"
    _import(database, tmp_path, [make_message("one", 1, 1000, "真实原文")])
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    response = "not json" if kind == "bad_json" else json.dumps({"items": [
        _item("missing" if kind == "unknown_source" else "m1", "不存在的摘录" if kind == "invented_quote" else "真实原文")
    ]}, ensure_ascii=False)
    directory = tmp_path / "report"
    with pytest.raises(ValueError):
        asyncio.run(DigestGenerator(lambda prompt: response).generate(snapshot, directory, run_id="test"))
    assert json.loads((directory / "trace.jsonl").read_text().splitlines()[-1])["content"] == response
    assert not (directory / "report.json").exists()


def test_grouped_digest_preserves_discussion_and_prioritizes_related_links(tmp_path: Path) -> None:
    """分群阅读和综合保留具体原文；群名和相关链接靠前，引用默认收起且不夹带无关网址。"""

    from html.parser import HTMLParser

    class DigestMarkup(HTMLParser):
        """检查原始发言确实位于默认关闭的展开区域，而非仅换了一个标题。"""

        def __init__(self) -> None:
            super().__init__()
            self.details_count = 0
            self.in_details = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "details":
                assert "open" not in dict(attrs)
                self.details_count += 1
                self.in_details = True
            if tag == "blockquote":
                assert self.in_details

        def handle_endtag(self, tag: str) -> None:
            if tag == "details":
                self.in_details = False

    database = tmp_path / "chat.sqlite3"
    link_quote = "支持使用 https://example.com/project?a=1&b=2"
    original = link_quote + "\n实际参数是单进程，每次处理两百条。\n其他话题 https://example.com/unrelated"
    _import(database, tmp_path, [make_message("one", 1, 1000, original),
                                 make_message("reply", 2, 1200, "暂时不推荐 <script>bad()</script>", reply_to="one")])
    _import(database, tmp_path, [make_message("two", 1, 1500, "另一群讨论了面试复盘")],
            group="67890", name="另一个群")
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    responses = iter([
        {"items": [{**_item("m1", link_quote), "sources": [
            {"id": "m1", "quote": link_quote}, {"id": "m2", "quote": "暂时不推荐"}]}]},
        {"items": [{**_item("m3", "面试复盘"), "title": "面试复盘的讨论"}]},
        {"items": [{**_item("m1", link_quote),
                    "summary": "项目用来处理消息。支持使用，但也有暂时不推荐的不同意见 <script>bad()</script>。"
                               "\n\n实际参数是单进程，每次处理两百条。仍需按具体条件判断。",
                    "sources": ["r1", "r2"]},
                   {**_item("m3", "面试复盘"), "title": "面试复盘的讨论", "sources": ["r3"]}]},
    ])
    calls: list[str] = []

    def complete(prompt: str) -> str:
        """只替代模型边界，其余读取、引用校验及渲染均使用产品实现。"""

        calls.append(prompt)
        if len(calls) == 3:
            # 关键参数不在候选摘要或摘录里，最终综合必须真的收到对应原文及群身份。
            material = json.loads(prompt.rsplit("\n", 1)[-1])
            assert material["source_excerpts"][0]["text"] == original
            assert material["items"][0]["group"] == "技术群"
            assert material["items"][0]["session_id"] != material["items"][1]["session_id"]
        return json.dumps(next(responses), ensure_ascii=False)

    report = asyncio.run(DigestGenerator(complete).generate(snapshot, tmp_path / "report", run_id="test"))
    assert len(calls) == 3 and report["group_count"] == 2 and report["batch_count"] == 2
    assert "暂时不推荐" in calls[0]
    subject, text, document = render_digest(report)
    assert "2 个话题" in subject
    assert "支持使用" in text and "暂时不推荐" in text
    assert "每次处理两百条" in text
    assert "<script>" not in document and "&lt;script&gt;" in document
    assert "href='https://example.com/project?a=1&amp;b=2'" in document
    assert "href='https://example.com/unrelated'" not in document
    assert document.index("群聊：技术群") < document.index("具体的实战经验")
    assert document.index("相关资源链接") < document.index("项目用来处理消息") < document.index("展开原始发言")
    assert document.index("群聊：另一个群") < document.index("面试复盘的讨论")
    assert "来源：" not in text
    markup = DigestMarkup()
    markup.feed(document)
    assert markup.details_count == 2
    for item in report["items"]:
        for reference in item["sources"]:
            assert reference["quote"] in report["sources"][reference["id"]]["text"]


def test_synthesis_rejects_mixing_sources_from_different_groups(tmp_path: Path) -> None:
    """一个群的标题不能笼罩另一群的观点；同题跨群材料也必须分别整理。"""

    database = tmp_path / "chat.sqlite3"
    _import(database, tmp_path, [make_message("one", 1, 1000, "支持这个方案")])
    _import(database, tmp_path, [make_message("two", 2, 1500, "反对这个方案")], group="67890", name="另一个群")
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    sources = {item.handle: item for item in make_excerpts(snapshot)}
    references = {"r1": {"id": "m1", "quote": "支持这个方案"}, "r2": {"id": "m2", "quote": "反对这个方案"}}
    response = json.dumps({"items": [{**_item("m1", "支持这个方案"), "sources": ["r1", "r2"]}]})
    with pytest.raises(ValueError, match="混合了不同群"):
        parse_synthesis(response, sources, references)


def test_resource_url_stops_before_chinese_text_following_domain(tmp_path: Path) -> None:
    """真实样稿里‘网址这是我的’被识别成中文域名；资源链接应保留网址本身。"""

    database = tmp_path / "chat.sqlite3"
    original = "https://vreport.tri4t.xyz这是我的"
    _import(database, tmp_path, [make_message("one", 1, 1000, original)])
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    report = asyncio.run(DigestGenerator(lambda prompt: json.dumps({"items": [_item("m1", original)]})).generate(
        snapshot, tmp_path / "report", run_id="url"))
    _, text, document = render_digest(report)
    assert "href='https://vreport.tri4t.xyz'" in document
    assert "href='https://vreport.tri4t.xyz这是我的'" not in document
    assert "- https://vreport.tri4t.xyz\n" in text
    assert report["items"][0]["sources"][0]["quote"] == original


def test_empty_digest_makes_no_model_request(tmp_path: Path) -> None:
    """空的真实时间窗有明确结果，不消耗模型也不声称全群没有有用内容。"""

    database = tmp_path / "chat.sqlite3"
    _import(database, tmp_path, [])
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    complete = Mock(side_effect=AssertionError("empty window must not call model"))
    report = asyncio.run(DigestGenerator(complete).generate(snapshot, tmp_path / "report", run_id="test"))
    assert report["items"] == [] and report["batch_count"] == 0
    assert "没有新增" in render_digest(report)[1]


def test_old_context_cannot_be_the_only_source_for_a_new_item(tmp_path: Path) -> None:
    """前情用于理解回复，不能单独把旧内容重新包装为今日发现。"""

    database = tmp_path / "chat.sqlite3"
    _import(database, tmp_path, [make_message("old", 1, 1000, "旧方案"),
                                 make_message("new", 2, 3000, "有新进展", reply_to="old")])
    snapshot = read_digest_snapshot(database, start_timestamp=2000, end_timestamp=4000)
    sources = {item.handle: item for item in make_excerpts(snapshot)}
    old = next(item for item in sources.values() if item.context_only)
    with pytest.raises(ValueError, match="只有旧上下文"):
        parse_items(json.dumps({"items": [_item(old.handle, "旧方案")]}, ensure_ascii=False), sources)


def test_failed_mail_keeps_checkpoint_and_explicit_resend_reuses_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实生成产物经历拒收、显式再发、重复调用，水位只随成功邮件推进。"""

    database = tmp_path / "chat.sqlite3"
    _import(database, tmp_path, [make_message("one", 1, 1000, "真实原文")])
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    directory = tmp_path / "report"
    report = asyncio.run(DigestGenerator(lambda prompt: json.dumps({"items": [_item("m1", "真实原文")]})).generate(
        snapshot, directory, run_id="one"))
    state = SQLiteDigestState(tmp_path / "digest.sqlite3")
    state.create("one", "2026-10-24", 0, 2000, directory, "2026-10-24T22:33:00+08:00")
    state.update("one", "ready", revision=report["revision"])
    settings = MailSettings("smtp.example.com", 465, "user", "private", "from@example.com", "to@example.com")
    sender = Mock(side_effect=RuntimeError("server refused"))
    monkeypatch.setattr(bootstrap, "send_digest_mail", sender)
    try:
        with pytest.raises(RuntimeError, match="server refused"):
            bootstrap.deliver_report(state, "one", settings)
        assert state.last_sent() is None and state.get("one")["status"] == "send_failed"
        assert (directory / "mail-error.log").exists()
        sender.side_effect, sender.return_value = None, "<accepted@example.com>"
        assert bootstrap.deliver_report(state, "one", settings)["status"] == "sent"
        assert state.last_sent()["through_revision"] == snapshot.revision
        assert bootstrap.deliver_report(state, "one", settings)["status"] == "already_sent"
        assert sender.call_count == 2
    finally:
        state.close()


def test_smtp_sends_alternative_bodies_and_does_not_expose_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """校验 MIME 与 SMTP 实际调用，发送必须使用明确的收发件人和 TLS。"""

    import trivae.digest.mail as mail

    settings = MailSettings("smtp.example.com", 465, "user", "private", "from@example.com", "to@example.com")
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    connection.send_message.return_value = {}
    smtp = Mock(return_value=connection)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", smtp)
    result = send_digest_mail(settings, subject="晚报", text="完整正文", document="<p>完整正文</p>")
    assert result.startswith("<") and "private" not in repr(settings)
    connection.login.assert_called_once_with("user", "private")
    message = connection.send_message.call_args.args[0]
    assert message["To"] == "to@example.com" and message.is_multipart()
    assert {part.get_content_type() for part in message.iter_parts()} == {"text/plain", "text/html"}
    assert connection.send_message.call_args.kwargs["to_addrs"] == ["to@example.com"]
    assert smtp.call_args.args == ("smtp.example.com", 465)


def test_daily_run_sends_once_and_next_day_picks_up_late_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """串起正式生成与交付，每日重复触发不发第二封，下一天读取未交付变更。"""

    database = tmp_path / "chat.sqlite3"
    now = datetime(2026, 10, 24, 22, 33, tzinfo=TIMEZONE)
    stamp = int((now - timedelta(hours=2)).timestamp() * 1000)
    _import(database, tmp_path, [make_message("one", 1, stamp, "真实原文")])
    snapshots = []

    async def generate(database: Path, directory: Path, *, run_id: str, start: int, end: int,
                       after_revision: int | None = None) -> dict:
        """只把模型换成可重复返回值，增量读取与落盘均走正式实现。"""

        snapshot = read_digest_snapshot(database, start_timestamp=start, end_timestamp=end, after_revision=after_revision)
        snapshots.append(snapshot)
        return await DigestGenerator(lambda prompt: '{"items":[]}').generate(snapshot, directory, run_id=run_id)

    monkeypatch.setattr(bootstrap, "generate_report", generate)
    sender = Mock(return_value="<accepted@example.com>")
    monkeypatch.setattr(bootstrap, "send_digest_mail", sender)
    state_path = tmp_path / "digest.sqlite3"
    settings = MailSettings("smtp.example.com", 465, "user", "private", "from@example.com", "to@example.com")
    assert asyncio.run(bootstrap.run_daily_digest(database, state_path, tmp_path / "reports", settings, now=now))["status"] == "sent"
    _import(database, tmp_path, [make_message("late", 2, stamp - 100000, "迟到新消息")])
    assert asyncio.run(bootstrap.run_daily_digest(database, state_path, tmp_path / "reports", settings, now=now))["status"] == "already_sent"
    assert sender.call_count == 1
    asyncio.run(bootstrap.run_daily_digest(database, state_path, tmp_path / "reports", settings, now=now + timedelta(days=1)))
    assert sender.call_count == 2
    assert [message.source_message_id for message in snapshots[-1].messages] == ["late"]


def test_cli_status_is_readonly_before_first_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """状态检查不能创建数据库、生成报告或调用模型。"""

    database = tmp_path / "missing.sqlite3"
    assert main(["digest", "status", "--database", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_initialized"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("hour,exit_code,expected", [(22, 0, 1), (10, 0, 0), (22, 75, 0), (22, 1, 0)])
def test_only_successful_evening_import_dispatches_independent_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hour: int, exit_code: int, expected: int,
) -> None:
    """上午、失败或尚在写入时不发日报，晚间成功才启动独立服务。"""

    import trivae.interfaces.import_once_cli as command

    class Clock(datetime):
        """固定北京时间，不依赖测试机器的当前时刻。"""

        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 10, 24, hour, 33, tzinfo=TIMEZONE)

    report = Mock(exit_code=exit_code)
    report.to_dict.return_value = {"status": "completed" if exit_code == 0 else "failed"}
    monkeypatch.setattr(command, "run_import_once", Mock(return_value=report))
    monkeypatch.setattr(command, "datetime", Clock)
    dispatcher = Mock()
    monkeypatch.setattr(command.subprocess, "run", dispatcher)
    assert main(["import-once", "--database", str(tmp_path / "chat.sqlite3"),
                 "--digest-label", "com.trivae.test-digest"]) == exit_code
    assert dispatcher.call_count == expected
    if expected:
        assert dispatcher.call_args.args[0][:2] == ["/bin/launchctl", "kickstart"]


def test_missing_mail_configuration_fails_before_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缺授权码时可先看样稿；正式运行不能先花费模型调用再发现无法发件。"""

    for key in ("TRIVAE_SMTP_HOST", "TRIVAE_SMTP_USERNAME", "TRIVAE_SMTP_PASSWORD", "TRIVAE_MAIL_FROM", "TRIVAE_MAIL_TO"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="邮件配置缺失"):
        main(["digest", "run"])
    assert not list(tmp_path.iterdir())


def test_initial_generation_failure_does_not_lose_previous_window_on_next_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首期尚未发送时跨日运行，仍须覆盖失败当天的输入，不能重新缩成最近24小时。"""

    database = tmp_path / "chat.sqlite3"
    now = datetime(2026, 10, 24, 22, 33, tzinfo=TIMEZONE)
    stamp = int((now - timedelta(hours=12)).timestamp() * 1000)
    _import(database, tmp_path, [make_message("missed", 1, stamp, "失败后仍需覆盖的正文")])
    snapshots = []

    async def generate(database: Path, directory: Path, *, run_id: str, start: int, end: int,
                       after_revision: int | None = None) -> dict:
        """第一次模拟已观察到的模型服务失败，第二天按真实选择器读取。"""

        snapshot = read_digest_snapshot(database, start_timestamp=start, end_timestamp=end, after_revision=after_revision)
        snapshots.append(snapshot)
        if len(snapshots) == 1:
            raise RuntimeError("provider interrupted")
        return await DigestGenerator(lambda prompt: '{"items":[]}').generate(snapshot, directory, run_id=run_id)

    monkeypatch.setattr(bootstrap, "generate_report", generate)
    monkeypatch.setattr(bootstrap, "send_digest_mail", Mock(return_value="<accepted@example.com>"))
    settings = MailSettings("smtp.example.com", 465, "user", "private", "from@example.com", "to@example.com")
    state_path = tmp_path / "digest.sqlite3"
    with pytest.raises(RuntimeError, match="provider interrupted"):
        asyncio.run(bootstrap.run_daily_digest(database, state_path, tmp_path / "reports", settings, now=now))
    asyncio.run(bootstrap.run_daily_digest(database, state_path, tmp_path / "reports", settings, now=now + timedelta(days=1)))
    assert [message.source_message_id for message in snapshots[-1].messages] == ["missed"]


def test_explicit_resume_reuses_successful_batches_and_only_calls_failed_synthesis(tmp_path: Path) -> None:
    """复现已观察到的综合HTTP520，续跑只发一次请求，旧成功批次和失败记录均保留。"""

    database = tmp_path / "chat.sqlite3"
    _import(database, tmp_path, [make_message("one", 1, 1000, "实际使用体验")])
    _import(database, tmp_path, [make_message("two", 2, 1500, "另一种体验")], group="67890")
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    responses = iter([{"items": [_item("m1", "实际使用体验")]}, {"items": [_item("m2", "另一种体验")]}])

    def complete(prompt: str) -> str:
        """前两批成功，最后综合返回与实际运行同类的Provider错误。"""

        if "以下是完整分批阅读" in prompt:
            raise CompletionProviderError("HTTP_520", CompletionObservation(transport={"status_code": 520}))
        return json.dumps(next(responses), ensure_ascii=False)

    directory = tmp_path / "report"
    with pytest.raises(CompletionProviderError):
        asyncio.run(DigestGenerator(complete).generate(snapshot, directory, run_id="one"))
    resumed = Mock(return_value=json.dumps({"items": [{**_item("m1", "实际使用体验"), "sources": ["r1"]}]}))
    report = asyncio.run(DigestGenerator(resumed).generate(snapshot, directory, run_id="one", resume=True))
    assert resumed.call_count == 1 and report["batch_count"] == 2
    events = [json.loads(line) for line in (directory / "trace.jsonl").read_text().splitlines()]
    assert sum(event["event"] == "request" for event in events) == 4
    assert sum(event["event"] == "response" for event in events) == 3
    assert sum(event["event"] == "reused_completed_stage" for event in events) == 2
    assert next(event for event in events if event["event"] == "provider_error")["observation"]["transport"]["status_code"] == 520


def test_resume_does_not_mix_saved_batches_with_a_changed_snapshot(tmp_path: Path) -> None:
    """数据库正常增量更新后，不允许把上一快照的正文与当前输入拼成一份日报。"""

    database = tmp_path / "chat.sqlite3"
    _import(database, tmp_path, [make_message("one", 1, 1000, "实际原文")])
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    directory = tmp_path / "report"
    asyncio.run(DigestGenerator(lambda prompt: '{"items":[]}').generate(snapshot, directory, run_id="one"))
    _import(database, tmp_path, [make_message("two", 2, 1500, "新入库正文")])
    changed = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    complete = Mock(side_effect=AssertionError("changed snapshot must not reuse or call model"))
    with pytest.raises(ValueError, match="数据快照已经变化"):
        asyncio.run(DigestGenerator(complete).generate(changed, directory, run_id="one", resume=True))
    assert complete.call_count == 0


def test_synthesis_binds_original_quote_and_rejects_model_rewritten_excerpt(tmp_path: Path) -> None:
    """实际失败是综合丢了原文中的‘里’字；新契约只选编号，摘录由程序原样绑定。"""

    database = tmp_path / "chat.sqlite3"
    text = "默认不应该是存浏览器缓存里吗。"
    _import(database, tmp_path, [make_message("one", 1, 1000, text)])
    snapshot = read_digest_snapshot(database, start_timestamp=0, end_timestamp=2000)
    sources = {item.handle: item for item in make_excerpts(snapshot)}
    references = {"r1": {"id": "m1", "quote": text}}
    content = json.dumps({"items": [{**_item("m1", text), "sources": ["r1"]}]}, ensure_ascii=False)
    items = parse_synthesis(content, sources, references)
    assert items[0]["sources"] == [{"id": "m1", "quote": text}]
    old_output = json.dumps({"items": [_item("m1", text.replace("里", ""))]}, ensure_ascii=False)
    with pytest.raises(ValueError, match="候选之外的编号"):
        parse_synthesis(old_output, sources, references)
