"""从已保存的 QQ canonical JSON 恢复合并转发树，不写入普通消息事实。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Literal

from trivae.data.ingestion.qq_export import QQExportParser
from trivae.data.model import CanonicalMessage
from trivae.retrieval.structured import ForwardProvenance, MessageProjection, RetrievalError

# 数字定位链逐层记录 element 下标和 message 下标，可逆且不依赖内部消息 ID 唯一性。
FORWARD_ID_MARKER = "#forward:"
FORWARD_PROJECTION_VERSION = "qq-forward-occurrence-v1"
_FORWARD_LOCATOR = re.compile(r"\d+\.\d+(?:\.\d+\.\d+)*\Z")


@dataclass(frozen=True)
class ForwardMessageTree:
    """一次 canonical root 解析的正文投影与缺失内容事实。"""

    root: MessageProjection
    messages: tuple[MessageProjection, ...]


def classify_forward_change(
    message: CanonicalMessage, previous_content: dict[str, Any], incoming_content: dict[str, Any],
) -> Literal["equal", "enriched", "less_complete", "conflict"]:
    """按正式转发 occurrence 比较已知事实，只接受保留全部旧事实的单调补齐。"""

    # 两棵树使用同一真实根身份；预览、显示名和 DFS 序号不属于内部正文的实质比较字段。
    root = MessageProjection(
        internal_message_id=message.internal_message_id, session_id=message.session_id,
        source_message_id=message.source_message_id, sender_user_id=message.sender_user_id,
        sender_platform_id=message.sender_platform_id, sender_uin=message.sender_uin,
        sender_name=message.sender_name, timestamp=message.timestamp, seq=message.seq,
        message_type=message.message_type, normalized_content=message.content_text,
        reply_to_source_message_id=message.reply_to_source_message_id, recalled=message.recalled,
        system=message.system,
    )

    def facts(content: dict[str, Any]) -> dict[str, tuple[object, ...]]:
        """直接复用读取层的树解析和正文语义，避免导入比较与正式检索理解不同。"""
        tree = project_forward_tree(root, content)
        return {
            item.internal_message_id: (
                item.source_message_id, item.sender_platform_id, item.sender_uin,
                item.message_type, item.normalized_content, item.reply_to_source_message_id,
                item.recalled, item.system,
                None if item.forward is None else item.forward.original_timestamp,
            )
            for item in (tree.root, *tree.messages)
        }

    previous, incoming = facts(previous_content), facts(incoming_content)
    # 已知位置的正文或稳定身份被改写时必须保留冲突，不能用“更长”覆盖旧事实。
    if any(previous[key] != incoming[key] for key in previous.keys() & incoming.keys()):
        return "conflict"
    if previous.keys() < incoming.keys():
        # 新版包含所有旧 occurrence，并新增可恢复正文；整份 incoming 可成为可信来源。
        return "enriched"
    if incoming.keys() < previous.keys():
        return "less_complete"
    # 互补但各自缺失已知位置的版本不能直接互相覆盖；保留原始版本供明确归并。
    return "equal" if previous.keys() == incoming.keys() else "conflict"


def forward_message_id(root_message_id: str, positions: tuple[int, ...]) -> str:
    """每个转发位置拥有独立 occurrence，重复 ID、重复正文和跨群均不会合并。"""

    return root_message_id + FORWARD_ID_MARKER + ".".join(str(position) for position in positions)


def split_forward_message_id(internal_message_id: str) -> tuple[str, tuple[int, ...]] | None:
    """把短 occurrence locator 还原成 root 与数组位置；普通 ID 原样交给 canonical。"""

    root_id, marker, locator = internal_message_id.rpartition(FORWARD_ID_MARKER)
    if not marker or not _FORWARD_LOCATOR.fullmatch(locator):
        return None
    return root_id, tuple(int(position) for position in locator.split("."))


def _own_content_text(content: dict[str, Any]) -> str:
    """转发 summary/preview 不是消息正文，只采集容器真实 text elements。"""

    elements = content.get("elements", [])
    if any(isinstance(element, dict) and element.get("type") == "forward" for element in elements):
        # QCE 会把预览复制到 content.text；必须排除该字段，防止空 messages 被当作已展开。
        texts = [
            str(element["data"]["text"])
            for element in elements
            if isinstance(element, dict)
            and element.get("type") == "text"
            and isinstance(element.get("data"), dict)
            and element["data"].get("text") is not None
        ]
        return QQExportParser._normalize_content_text("\n".join(texts))
    return QQExportParser._normalize_content_text(QQExportParser._optional_text(content.get("text")) or "")


def project_forward_tree(
    root: MessageProjection,
    content: dict[str, Any],
    *,
    source_file: str | None = None,
    source_record_index: int | None = None,
) -> ForwardMessageTree:
    """递归解析已保留 JSON；缺失节点保留路径，格式错误显式指向 root 和路径。"""

    descendants: list[MessageProjection] = []

    def fail(path: str, field: str) -> RetrievalError:
        return RetrievalError(f"Invalid QQ forward content: {root.internal_message_id}/{path}: {field}")

    def visit(
        parent: MessageProjection,
        parent_content: dict[str, Any],
        prefix: str,
        positions: tuple[int, ...],
    ) -> tuple[str, ...]:
        elements = parent_content.get("elements", [])
        if not isinstance(elements, list):
            raise fail(prefix, "elements must be an array")
        missing: list[str] = []
        for element_index, element in enumerate(elements):
            if not isinstance(element, dict) or element.get("type") != "forward":
                continue
            element_path = f"{prefix}.elements[{element_index}]"
            data = element.get("data")
            if not isinstance(data, dict):
                raise fail(element_path, "data must be an object")
            children = data.get("messages")
            # QCE 未展开时 messages 为空或缺失；只表达缺失，不猜测 preview 的完整性。
            if children is None or children == []:
                missing.append(element_path)
                continue
            if not isinstance(children, list):
                raise fail(element_path, "data.messages must be an array")
            for message_index, child in enumerate(children):
                path = f"{element_path}.data.messages[{message_index}]"
                if not isinstance(child, dict) or not isinstance(child.get("content"), dict):
                    raise fail(path, "message/content must be an object")
                child_content = child["content"]
                child_elements = child_content.get("elements", [])
                if not isinstance(child_elements, list):
                    raise fail(path, "content.elements must be an array")
                timestamp = child.get("timestamp")
                if isinstance(timestamp, str) and re.fullmatch(r"-?\d+", timestamp):
                    timestamp = int(timestamp)
                if timestamp is not None and (isinstance(timestamp, bool) or not isinstance(timestamp, int)):
                    raise fail(path, "timestamp must be an integer or null")
                sender = child.get("sender") or {}
                if not isinstance(sender, dict):
                    raise fail(path, "sender must be an object")
                uid, uin, identity = QQExportParser._sender_identity(sender)
                child_positions = (*positions, element_index, message_index)
                occurrence = forward_message_id(root.internal_message_id, child_positions)
                # 当前群的时间与 session 始终继承外层，不能让内部时间越过查询范围。
                projection = MessageProjection(
                    internal_message_id=occurrence,
                    session_id=root.session_id,
                    session_display=root.session_display,
                    source_message_id=QQExportParser._optional_text(child.get("id")),
                    sender_user_id=f"qq:{identity}" if identity else None,
                    sender_platform_id=uid,
                    sender_uin=uin,
                    sender_name=QQExportParser._optional_text(sender.get("name")),
                    timestamp=root.timestamp,
                    # DFS ordinal 只表示该 occurrence 树内的位置，不冒充平台原始 seq。
                    seq=len(descendants),
                    message_type=QQExportParser._canonical_message_type(child, child_elements),
                    normalized_content=_own_content_text(child_content),
                    reply_to_source_message_id=QQExportParser._reply_target(child_elements),
                    recalled=bool(child.get("recalled", False)),
                    system=bool(child.get("system", False)),
                    forward=ForwardProvenance(
                        root_message_id=root.internal_message_id,
                        parent_message_id=parent.internal_message_id,
                        path=path,
                        original_timestamp=timestamp,
                        root_source_message_id=root.source_message_id,
                        source_file=source_file,
                        source_record_index=source_record_index,
                    ),
                )
                # 先占位再递归，确保父节点顺序在子节点之前且同树 ordinal 唯一。
                ordinal = len(descendants)
                descendants.append(projection)
                child_missing = visit(projection, child_content, f"{path}.content", child_positions)
                descendants[ordinal] = replace(projection, unexpanded_forward_paths=child_missing)
                missing.extend(child_missing)
        return tuple(missing)

    unexpanded_paths = visit(root, content, "content", ())
    return ForwardMessageTree(
        root=replace(root, normalized_content=_own_content_text(content), unexpanded_forward_paths=unexpanded_paths),
        messages=tuple(descendants),
    )
