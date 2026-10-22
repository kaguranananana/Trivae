"""合并转发的真实 Failure Case 形态：具体子消息检索、来源恢复与派生失效。"""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

from tests.test_ingestion import make_message, write_export
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import LexicalIndexError, LexicalQuery, MessageQuery, RetrievalError, ScopeFilters


def make_forward_message(
    message_id: str,
    timestamp: int,
    children: list[dict],
    *,
    text: str = "",
    sender_uid: str = "u_sender",
) -> dict:
    """QCE 会把 preview 写进 content.text，fixture 必须复现这个事实。"""

    message = make_message(message_id, None, timestamp, "预览秘密：摘要不等于完整正文", sender_uid=sender_uid)
    message["content"]["elements"] = [
        {"type": "forward", "data": {"messages": children, "preview": "预览秘密", "messageCount": len(children)}}
    ]
    if text:
        message["content"]["elements"].append({"type": "text", "data": {"text": text}})
    return message


def forward_children() -> list[dict]:
    """同一个内部 ID 在同树重复出现，仍必须保留每个数组位置。"""

    remote = make_message("inner-remote", None, 100, "可以通过远程连接排查问题", sender_uid="u_inner")
    anchor = make_message("inner-anchor", None, 200, "这个讨论提到了情感锚点", sender_uid="u_original")
    nested = make_forward_message(
        "inner-container", 150, [anchor, make_message("deep-peer", None, 210, "深层上下文", sender_uid="u_original")]
    )
    missing = make_forward_message("inner-unexpanded", 300, [])
    return [remote, nested, missing, make_message("inner-peer", None, 400, "检查网络设置"), copy.deepcopy(remote)]


@dataclass
class ForwardFixture:
    """测试资源只存在临时目录，不读写真实聊天或 Evaluation。"""

    path: Path
    source: Path
    store: SQLiteCanonicalStore
    reader: SQLiteCanonicalReadRepository
    index: SQLiteLexicalIndex
    lexical: LexicalRetrieval


@pytest.fixture
def forward_fixture(tmp_path: Path) -> Iterator[ForwardFixture]:
    first = write_export(
        tmp_path,
        "forward(100).json",
        [
            make_message("ordinary-before", 1, 9_000, "普通消息 alpha"),
            make_forward_message("outer-a", 10_000, forward_children()),
            make_message("ordinary-after", 3, 11_000, "群聊普通邻居"),
            make_forward_message("outer-b", 20_000, forward_children()),
            make_forward_message("outer-mixed", 30_000, [], text="真实外层正文"),
        ],
        chat_name="测试群一",
        peer_uid="100",
        version="0.1.0",
    )
    other = write_export(
        tmp_path,
        "forward(200).json",
        [make_forward_message("outer-a", 40_000, forward_children())],
        chat_name="测试群二",
        peer_uid="200",
        version="0.1.0",
    )
    path = tmp_path / "canonical.sqlite3"
    store = SQLiteCanonicalStore(path)
    SharedImporter(store).import_paths([first, other])
    reader = SQLiteCanonicalReadRepository(path)
    index = SQLiteLexicalIndex(path)
    index.rebuild()
    yield ForwardFixture(path, first, store, reader, index, LexicalRetrieval(reader))
    index.close()
    reader.close()
    store.close()


def search(fixture: ForwardFixture, keyword: str, **kwargs: object):
    """只经生产 LexicalRetrieval，包含实际 FTS 与自动 context。"""

    return fixture.lexical.search(LexicalQuery(keyword=keyword, limit=50, **kwargs))


def test_failure_phrases_find_concrete_children_with_canonical_provenance(forward_fixture: ForwardFixture) -> None:
    fixture = forward_fixture
    remote = search(fixture, "远程连接", session_ids=("qq:100",), context_before=0, context_after=0)
    anchor = search(fixture, "情感锚点", session_ids=("qq:100",), context_before=0, context_after=0)
    assert remote.total_hits == 4
    assert anchor.total_hits == 2
    hit = next(hit.message for hit in remote.hits if hit.message.internal_message_id == "qq:100:outer-a#forward:0.0")
    assert hit.source_message_id == "inner-remote"
    assert hit.sender_user_id == "qq:uid:u_inner"
    assert hit.sender_platform_id == "u_inner"
    assert hit.timestamp == 10_000
    assert hit.forward is not None
    assert hit.forward.original_timestamp == 100
    assert hit.forward.root_message_id == "qq:100:outer-a"
    assert hit.forward.parent_message_id == "qq:100:outer-a"
    assert hit.forward.path == "content.elements[0].data.messages[0]"
    assert hit.forward.source_file == "forward(100).json"
    assert hit.forward.source_record_index == 1
    assert hit.forward.root_source_message_id == "outer-a"
    deep = next(hit.message for hit in anchor.hits if hit.message.forward.root_message_id == "qq:100:outer-a")
    assert deep.forward.parent_message_id == "qq:100:outer-a#forward:0.1"
    assert deep.forward.path == "content.elements[0].data.messages[1].content.elements[0].data.messages[0]"
    assert fixture.reader.read_message_by_id(deep.internal_message_id) == deep


def test_occurrences_preserve_repeated_paths_and_cross_group_sources(forward_fixture: ForwardFixture) -> None:
    fixture = forward_fixture
    all_hits = search(fixture, "远程连接", context_before=0, context_after=0)
    identities = {hit.message.internal_message_id for hit in all_hits.hits}
    assert len(identities) == 6
    assert "qq:100:outer-a#forward:0.0" in identities
    assert "qq:100:outer-a#forward:0.4" in identities
    assert "qq:100:outer-b#forward:0.0" in identities
    assert "qq:200:outer-a#forward:0.0" in identities
    other = search(fixture, "情感锚点", session_ids=("qq:200",), context_before=2, context_after=2)
    assert other.total_hits == 1
    assert {message.session_id for message in other.expanded_messages} == {"qq:200"}
    assert {message.forward.root_message_id for message in other.expanded_messages} == {"qq:200:outer-a"}


def test_time_scope_uses_forwarded_at_and_keeps_original_time_separate(forward_fixture: ForwardFixture) -> None:
    result = search(
        forward_fixture, "远程连接", session_ids=("qq:100",), start_timestamp=10_000, end_timestamp=10_001
    )
    assert result.total_hits == 2
    assert all(message.timestamp == 10_000 for message in result.expanded_messages)
    assert all(message.forward.root_message_id == "qq:100:outer-a" for message in result.expanded_messages)
    original_window = search(forward_fixture, "远程连接", start_timestamp=90, end_timestamp=110)
    assert original_window.total_hits == 0
    by_sender = search(forward_fixture, "远程连接", sender_user_ids=("qq:uid:u_inner",))
    assert by_sender.total_hits == 6


def test_empty_forward_never_indexes_preview_and_reports_scope_gaps(forward_fixture: ForwardFixture) -> None:
    fixture = forward_fixture
    missing = search(fixture, "预览秘密", session_ids=("qq:100",))
    assert missing.total_hits == 0
    assert missing.coverage.status == "partial"
    assert missing.coverage.known_gaps == ("unexpanded_forward_content",)
    assert missing.metadata.details["unexpanded_forward_nodes"] == 3
    root = fixture.reader.read_message_by_id("qq:100:outer-a")
    assert root.normalized_content == ""
    assert root.unexpanded_forward_paths == ("content.elements[0].data.messages[2].content.elements[0]",)
    empty = fixture.reader.read_message_by_id("qq:100:outer-a#forward:0.2")
    assert empty.normalized_content == ""
    assert empty.unexpanded_forward_paths == root.unexpanded_forward_paths
    mixed = search(fixture, "真实外层正文", context_before=0, context_after=0)
    assert mixed.total_hits == 1
    assert mixed.hits[0].message.internal_message_id == "qq:100:outer-mixed"
    assert fixture.reader.forward_content_gaps(ScopeFilters(start_timestamp=0, end_timestamp=1)) == ()


def test_context_and_range_stay_within_direct_forward_container(forward_fixture: ForwardFixture) -> None:
    reader = forward_fixture.reader
    deep_id = "qq:100:outer-a#forward:0.1.0.0"
    peer_id = "qq:100:outer-a#forward:0.1.0.1"
    context = reader.read_message_context("qq:100", deep_id, 10, 10)
    assert [message.internal_message_id for message in context] == [deep_id, peer_id]
    assert reader.read_message_range("qq:100", deep_id, peer_id, 10) == context
    assert len(reader.read_message_range("qq:100", deep_id, peer_id, 1)) == 1
    with pytest.raises(RetrievalError, match="direct parent"):
        reader.read_message_range("qq:100", deep_id, "qq:100:outer-a#forward:0.4", 20)
    with pytest.raises(RetrievalError, match="direct parent"):
        reader.read_message_range("qq:100", deep_id, "qq:100:outer-b#forward:0.1.0.0", 20)
    with pytest.raises(RetrievalError, match="outside scope"):
        reader.read_message_context_scoped("qq:100", deep_id, 1, 1, ScopeFilters(end_timestamp=10_000))


def test_derived_rebuild_keeps_canonical_statistics_and_original_json(forward_fixture: ForwardFixture) -> None:
    fixture = forward_fixture
    before = fixture.store.connection.execute(
        "SELECT internal_message_id, content_json, raw_payload_json FROM messages ORDER BY internal_message_id"
    ).fetchall()
    counts = {table: fixture.store.count(table) for table in ("messages", "memberships", "users")}
    stats = fixture.index.rebuild()
    assert stats.canonical_messages == 6
    assert stats.forwarded_messages == 21
    assert stats.indexed_messages == 27
    assert stats.unexpanded_forward_nodes == 4
    assert fixture.reader.count_messages(MessageQuery()) == 6
    assert fixture.reader.count_forwarded_messages() == 21
    assert len(tuple(fixture.reader.iter_semantic_messages(1))) == 6
    assert len(tuple(fixture.reader.iter_forwarded_messages(1))) == 21
    assert {table: fixture.store.count(table) for table in counts} == counts
    assert [tuple(row) for row in before] == [tuple(row) for row in fixture.store.connection.execute(
        "SELECT internal_message_id, content_json, raw_payload_json FROM messages ORDER BY internal_message_id"
    ).fetchall()]
    ordinary = search(fixture, "alpha", context_before=0, context_after=0)
    assert ordinary.total_hits == 1
    assert ordinary.hits[0].message.forward is None


def test_derived_text_is_not_used_as_evidence_and_locator_survives_drop(forward_fixture: ForwardFixture) -> None:
    fixture = forward_fixture
    child_id = "qq:100:outer-a#forward:0.0"
    with sqlite3.connect(fixture.path) as connection:
        connection.execute("UPDATE forwarded_messages SET content_text = '错误的派生正文' WHERE internal_message_id = ?", (child_id,))
    result = search(fixture, "远程连接", context_before=0, context_after=0)
    canonical = next(hit.message for hit in result.hits if hit.message.internal_message_id == child_id)
    assert canonical.normalized_content == "可以通过远程连接排查问题"
    revision = fixture.reader.canonical_revision()
    fixture.index.drop()
    assert fixture.reader.read_message_by_id(child_id) == canonical
    assert fixture.reader.canonical_revision() == revision
    assert fixture.reader.read_message_context("qq:100", child_id, 0, 0) == (canonical,)
    fixture.index.rebuild()
    assert fixture.reader.canonical_revision() == revision


def test_same_count_canonical_edit_invalidates_index_and_coverage_inventory(forward_fixture: ForwardFixture) -> None:
    fixture = forward_fixture
    assert len(fixture.reader.forward_content_gaps(ScopeFilters())) == 4
    revision = fixture.reader.canonical_revision()
    root = fixture.store.connection.execute("SELECT content_json FROM messages WHERE internal_message_id='qq:100:outer-a'").fetchone()
    content = json.loads(root["content_json"])
    empty = content["elements"][0]["data"]["messages"][2]
    empty["content"]["elements"][0]["data"]["messages"] = [make_message("now-expanded", None, 350, "新增完整正文")]
    fixture.store.connection.execute(
        "UPDATE messages SET content_json=? WHERE internal_message_id='qq:100:outer-a'",
        (json.dumps(content, ensure_ascii=False, separators=(",", ":")),),
    )
    fixture.store.connection.commit()
    assert fixture.reader.canonical_revision() == revision + 1
    assert fixture.reader.count_messages(MessageQuery()) == 6
    assert fixture.reader.count_forwarded_messages() == 22
    assert len(fixture.reader.forward_content_gaps(ScopeFilters())) == 3
    with pytest.raises(LexicalIndexError, match="revision is stale"):
        search(fixture, "新增完整正文")
    fixture.index.rebuild()
    assert search(fixture, "新增完整正文").total_hits == 1


def test_rebuild_failure_rolls_back_fts_projection_and_version(forward_fixture: ForwardFixture) -> None:
    fixture = forward_fixture
    before = search(fixture, "情感锚点", context_before=0, context_after=0)
    with patch("trivae.data.storage.sqlite_lexical._row_to_forward_tree", side_effect=RuntimeError("projection failed")):
        with pytest.raises(RuntimeError, match="projection failed"):
            fixture.index.rebuild()
    after = search(fixture, "情感锚点", context_before=0, context_after=0)
    assert before.hits == after.hits
    assert fixture.reader.count_messages(MessageQuery()) == 6
    with sqlite3.connect(fixture.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM forwarded_messages").fetchone()[0] == 21
        connection.execute("UPDATE trivae_derived_meta SET value='old-version' WHERE key='lexical_forward_projection'")
    with pytest.raises(LexicalIndexError, match="forward projection is stale"):
        search(fixture, "情感锚点")
    fixture.index.rebuild()
    assert search(fixture, "情感锚点").total_hits == 3


def test_duplicate_export_keeps_first_canonical_source_and_internal_tree(forward_fixture: ForwardFixture, tmp_path: Path) -> None:
    fixture = forward_fixture
    variant = make_forward_message("outer-a", 10_000, [make_message("replacement", None, 100, "后来的不同导出")])
    second = write_export(tmp_path, "later(100).json", [variant], chat_name="测试群一", peer_uid="100", version="0.1.0")
    revision = fixture.reader.canonical_revision()
    SharedImporter(fixture.store).import_paths([second])
    assert fixture.reader.canonical_revision() == revision
    assert fixture.reader.count_messages(MessageQuery()) == 6
    child = fixture.reader.read_message_by_id("qq:100:outer-a#forward:0.0")
    assert child.source_message_id == "inner-remote"
    assert child.forward.source_file == fixture.source.name
    assert search(fixture, "后来的不同导出").total_hits == 0
    assert search(fixture, "远程连接").total_hits == 6


def test_multiple_forward_elements_have_independent_context(forward_fixture: ForwardFixture, tmp_path: Path) -> None:
    """同一父消息的两个 forward elements 不代表同一份原始会话。"""

    fixture = forward_fixture
    root = make_forward_message("two-containers", 50_000, [make_message("left", None, 1, "左侧讨论")])
    root["content"]["elements"].append(
        {"type": "forward", "data": {"messages": [make_message("right", None, 2, "右侧讨论")]}}
    )
    path = write_export(tmp_path, "multiple(100).json", [root], chat_name="测试群一", peer_uid="100", version="0.1.0")
    SharedImporter(fixture.store).import_paths([path])
    left_id = "qq:100:two-containers#forward:0.0"
    right_id = "qq:100:two-containers#forward:1.0"
    left = fixture.reader.read_message_by_id(left_id)
    assert left.forward.container_path == "content.elements[0]"
    assert fixture.reader.read_message_context("qq:100", left_id, 10, 10) == (left,)
    with pytest.raises(RetrievalError, match="forward container"):
        fixture.reader.read_message_range("qq:100", left_id, right_id, 20)


def test_single_han_recovers_forward_occurrences_without_preview(forward_fixture: ForwardFixture) -> None:
    """单字也以真实转发位置恢复；时间按外层过滤，preview不能成为正文。"""
    result = forward_fixture.lexical.search(LexicalQuery(
        keyword="程", session_ids=("qq:100",), end_timestamp=15_000, limit=20,
        context_before=0, context_after=0,
    ))
    assert result.total_hits == 2
    assert {hit.message.internal_message_id for hit in result.hits} == {
        "qq:100:outer-a#forward:0.0", "qq:100:outer-a#forward:0.4",
    }
    assert all(hit.message.forward is not None and hit.message.timestamp == 10_000 for hit in result.hits)
    preview = forward_fixture.lexical.search(LexicalQuery(keyword="密", context_before=0, context_after=0))
    assert preview.total_hits == 0
