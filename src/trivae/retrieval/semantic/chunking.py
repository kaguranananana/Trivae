"""Semantic Retrieval 的 Time-aware Parent + Small Child chunker。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Sequence

from trivae.retrieval.semantic.contracts import (
    SemanticChunk,
    SemanticChunkResult,
    SemanticMessage,
    SemanticQueryError,
)

# 新版索引加入转发 occurrence 与容器边界，旧索引必须显式重建。
SEMANTIC_CHUNKER_VERSION = "trivae-semantic-chunker-v2-forward"


@dataclass(frozen=True)
class SemanticChunkConfig:
    """Semantic chunker 的 v1 baseline；所有字段都会进入 index identity。"""

    parent_gap_seconds: int = 1200
    parent_max_chars: int = 6000
    parent_max_messages: int = 100
    child_min_chars: int = 96
    child_max_chars: int = 480
    child_max_messages: int = 10
    child_overlap_messages: int = 1
    semantic_void_skip_threshold: int = 24
    embedding_max_chars: int = 6000
    header_max_chars: int = 600

    def __post_init__(self) -> None:
        """把错误参数挡在 build 前，避免得到不可解释的 derived index。"""

        for name in (
            "parent_gap_seconds",
            "parent_max_chars",
            "parent_max_messages",
            "child_min_chars",
            "child_max_chars",
            "child_max_messages",
            "embedding_max_chars",
            "header_max_chars",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SemanticQueryError(f"{name} must be a positive integer")
        if isinstance(self.child_overlap_messages, bool) or not isinstance(self.child_overlap_messages, int):
            raise SemanticQueryError("child_overlap_messages must be a non-negative integer")
        if self.child_overlap_messages < 0 or self.child_overlap_messages >= self.child_max_messages:
            raise SemanticQueryError("child_overlap_messages must be smaller than child_max_messages")
        if (
            isinstance(self.semantic_void_skip_threshold, bool)
            or not isinstance(self.semantic_void_skip_threshold, int)
            or self.semantic_void_skip_threshold < 0
        ):
            raise SemanticQueryError("semantic_void_skip_threshold must be non-negative")
        if self.child_min_chars > self.child_max_chars:
            raise SemanticQueryError("child_min_chars must not exceed child_max_chars")

    def to_dict(self) -> dict[str, object]:
        """固定字段顺序返回可进入 identity 的 config projection。"""

        return {key: value for key, value in asdict(self).items()}

    @property
    def serialized(self) -> str:
        """用 canonical JSON 表示 config，不写 hash。"""

        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


DEFAULT_SEMANTIC_CHUNK_CONFIG = SemanticChunkConfig()


# 这些值是高噪声群聊中没有独立语义的短确认/填充消息；它们仍保留在 range 中。
_VOID_FILLERS = frozenset(
    {
        "好",
        "好的",
        "嗯",
        "嗯嗯",
        "哦",
        "噢",
        "额",
        "呃",
        "哈",
        "哈哈",
        "哈哈哈",
        "呵呵",
        "在",
        "在吗",
        "收到",
        "行",
        "可以",
        "是",
        "是的",
        "对",
        "对的",
        "ok",
        "okay",
        "👍",
        "👌",
        "🙏",
        "？",
        "?",
    }
)
_VOID_CONTENT_MARKERS = frozenset(
    {
        "[图片]",
        "[语音]",
        "[视频]",
        "[文件]",
        "[表情]",
        "[动画表情]",
        "[位置]",
        "[名片]",
        "[红包]",
        "[转账]",
        "[撤回消息]",
    }
)
_VOID_CONTENT_PREFIXES = ("[图片", "[语音", "[视频", "[文件", "[表情", "[动画表情", "[位置", "[名片", "[红包", "[转账")
_VOID_MESSAGE_TYPES = frozenset({"image", "voice", "video", "file", "emoji", "location", "system", "recall"})
# 仅去掉 QCE 已知资源占位符；图片等类型仍可携带需要检索的实际文字。
_FORWARD_MEDIA_MARKER = re.compile(r"\[(?:图片|语音|视频|文件|表情|动画表情|位置|名片|红包|转账)(?::[^\]\n]*)?\]")


def _semantic_content(message: SemanticMessage) -> str:
    """转发正文按实际剩余文字判定，不让 QQ 的图片优先类型覆盖 caption。"""

    content = message.normalized_content.strip()
    if message.forward is not None:
        return _FORWARD_MEDIA_MARKER.sub("", content).strip()
    return content


def is_semantic_void(message: SemanticMessage) -> bool:
    """判断消息是否应该从 embedding input 排除，但不从 canonical range 删除。"""

    content = _semantic_content(message)
    if message.system or message.recalled or not content:
        return True
    # 原生消息规则保持不变；转发只跳过纯资源占位符，不丢弃混合消息里的实际正文。
    if message.forward is None:
        if message.message_type.lower() in _VOID_MESSAGE_TYPES:
            return True
        if content in _VOID_CONTENT_MARKERS:
            return True
        if any(content.startswith(prefix) for prefix in _VOID_CONTENT_PREFIXES):
            return True
    normalized = content.lower().rstrip("。.!！?？、,，~～ \t\n")
    return normalized in _VOID_FILLERS


def _effective_text(message: SemanticMessage) -> str:
    """只在派生 embedding 文本中保留有效正文。"""

    return "" if is_semantic_void(message) else _semantic_content(message)


def _effective_chars(messages: Sequence[SemanticMessage]) -> int:
    """用正文字符数控制 chunk，不让 filler 消息撑大 semantic unit。"""

    return sum(len(_effective_text(message)) for message in messages)


def _format_timestamp(timestamp: int) -> str:
    """canonical Unix milliseconds 统一转为 UTC 可读时间。"""

    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _build_embedding_input(
    messages: Sequence[SemanticMessage],
    config: SemanticChunkConfig,
) -> str:
    """构造 bounded contextual embedding input，正文优先于 header。"""

    effective = [message for message in messages if not is_semantic_void(message)]
    if not effective:
        return ""

    # header 固定使用小预算，避免异常长群名/昵称挤掉真正正文。
    source = messages[0].session_display.strip() or messages[0].session_id
    participants: list[str] = []
    for message in effective:
        name = message.sender_name.strip() or message.sender_user_id or "unknown"
        if name not in participants:
            participants.append(name)
    # scope 时间始终来自当前群；内部原始时间只作为转发记录的独立事实。
    forwarded = messages[0].forward is not None
    time_label = "转发时间范围" if forwarded else "时间范围"
    header_lines = [
        f"[来源] {source}",
        f"[{time_label}] {_format_timestamp(messages[0].timestamp)} - {_format_timestamp(messages[-1].timestamp)}",
        f"[参与者] {'、'.join(participants)}",
    ]
    if forwarded:
        header_lines.append("[记录类型] 合并转发内部消息；原始群聊未知")
    header = "\n".join(header_lines)[: config.header_max_chars]

    body_lines: list[str] = []
    for message in effective:
        sender = message.sender_name.strip() or message.sender_user_id or "unknown"
        # 原始时间未知时明确保留缺失，不拿外层转发时间冒充内部发送时间。
        if message.forward is not None:
            original = message.forward.original_timestamp
            original_time = "未知" if original is None else _format_timestamp(original)
            sender = f"{sender}（内部原始时间 {original_time}）"
        body_lines.append(f"{sender}: {_effective_text(message)}")
    body = "\n".join(body_lines)
    # 先给 header，再用总长度护栏截断，保证输入一定有界。
    remaining = max(0, config.embedding_max_chars - len(header) - 2)
    return f"{header}\n\n{body[:remaining]}"[: config.embedding_max_chars]


class SemanticChunker:
    """无数据库、无模型副作用的确定性 Parent/Child chunker。"""

    def __init__(
        self,
        config: SemanticChunkConfig = DEFAULT_SEMANTIC_CHUNK_CONFIG,
        version: str = SEMANTIC_CHUNKER_VERSION,
    ) -> None:
        self.config = config
        self.version = version

    def starts_new_parent(
        self,
        previous: SemanticMessage,
        current: SemanticMessage,
        parent: Sequence[SemanticMessage],
    ) -> bool:
        """供 streaming builder 与纯函数 chunking 共享同一 Parent boundary 规则。"""

        if previous.session_id != current.session_id:
            return True
        # 不同转发树、不同直接父容器和原生群消息必须形成独立语义段。
        if self._container(previous) != self._container(current):
            return True
        if current.timestamp - previous.timestamp > self.config.parent_gap_seconds * 1000:
            return True
        if len(parent) >= self.config.parent_max_messages:
            return True
        return _effective_chars(parent) + len(_effective_text(current)) > self.config.parent_max_chars

    def chunk_parent(self, parent: Sequence[SemanticMessage]) -> SemanticChunkResult:
        """对一个已经确定边界的 Parent 生成 Small Child。"""

        if not parent:
            return SemanticChunkResult(self.version, self.config.to_dict(), (), 0, 0)
        if any(message.session_id != parent[0].session_id for message in parent):
            raise SemanticQueryError("one parent must contain one session")
        if any(self._container(message) != self._container(parent[0]) for message in parent):
            raise SemanticQueryError("one parent must contain one forward container")

        chunks: list[SemanticChunk] = []
        skipped = 0
        current: list[SemanticMessage] = []
        new_messages = 0

        def close_child() -> None:
            nonlocal current, new_messages, skipped
            if not current:
                return
            effective_chars = _effective_chars(current)
            # 即使 threshold 配成 0，纯 void child 也不能流入 provider；canonical range 仍保留在源库。
            # 转发容器可能只有一条短正文；仍需索引「情感锚点」这样的真实内部内容。
            below_native_threshold = (
                parent[0].forward is None and effective_chars < self.config.semantic_void_skip_threshold
            )
            if effective_chars == 0 or below_native_threshold:
                skipped += 1
            else:
                parent_id = self._parent_id(parent)
                start = current[0]
                end = current[-1]
                chunks.append(
                    SemanticChunk(
                        chunk_id=self._child_id(parent_id, start, end),
                        parent_id=parent_id,
                        session_id=start.session_id,
                        parent_start_message_id=parent[0].internal_message_id,
                        parent_end_message_id=parent[-1].internal_message_id,
                        start_message_id=start.internal_message_id,
                        end_message_id=end.internal_message_id,
                        start_timestamp=start.timestamp,
                        end_timestamp=end.timestamp,
                        message_count=len(current),
                        effective_chars=effective_chars,
                        embedding_input=_build_embedding_input(current, self.config),
                    )
                )
            # overlap 只从已结束 child 的尾部保留，不把同一段 overlap 单独再次输出。
            seed = current[-self.config.child_overlap_messages :] if self.config.child_overlap_messages else []
            current = list(seed)
            new_messages = 0

        for message in parent:
            current.append(message)
            new_messages += 1
            effective_chars = _effective_chars(current)
            should_close = effective_chars >= self.config.child_max_chars or len(current) >= self.config.child_max_messages
            if should_close and (effective_chars >= self.config.child_min_chars or len(current) >= self.config.child_max_messages):
                close_child()

        if current and (new_messages > 0 or not chunks):
            close_child()
        return SemanticChunkResult(
            chunker_version=self.version,
            chunker_config=self.config.to_dict(),
            chunks=tuple(chunks),
            skipped_void_chunks=skipped,
            parent_count=1,
        )

    def chunk(self, messages: Sequence[SemanticMessage]) -> SemanticChunkResult:
        """对有序消息序列执行 session/time/size Parent segmentation。"""

        parents: list[list[SemanticMessage]] = []
        current: list[SemanticMessage] = []
        for message in messages:
            if current and self.starts_new_parent(current[-1], message, current):
                parents.append(current)
                current = []
            current.append(message)
        if current:
            parents.append(current)

        chunks: list[SemanticChunk] = []
        skipped = 0
        for parent in parents:
            result = self.chunk_parent(parent)
            chunks.extend(result.chunks)
            skipped += result.skipped_void_chunks
        return SemanticChunkResult(
            chunker_version=self.version,
            chunker_config=self.config.to_dict(),
            chunks=tuple(chunks),
            skipped_void_chunks=skipped,
            parent_count=len(parents),
        )

    def _parent_id(self, parent: Sequence[SemanticMessage]) -> str:
        """Parent ID 只依赖稳定 message identity、version 和 readable config identity。"""

        return (
            f"parent:{parent[0].session_id}:{parent[0].internal_message_id}:"
            f"{parent[-1].internal_message_id}:v={self.version}:config={self.config.serialized}"
        )

    @staticmethod
    def _container(message: SemanticMessage) -> tuple[str, str, str] | None:
        """只比较来源 occurrence，禁止把重复转发误合并成原生会话。"""

        if message.forward is None:
            return None
        return (
            message.forward.root_message_id,
            message.forward.parent_message_id,
            message.forward.container_path,
        )

    @staticmethod
    def _child_id(parent_id: str, start: SemanticMessage, end: SemanticMessage) -> str:
        """Child ID 不包含正文，重建时相同 canonical range 会得到相同 identity。"""

        return f"child:{parent_id}:{start.internal_message_id}:{end.internal_message_id}"
