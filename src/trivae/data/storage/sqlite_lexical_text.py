"""Lexical derived index 的确定性文本归一化契约。

unicode61 把连续的字母/数字/CJK 字符视为一个 token，导致两类中文召回缺失：

1. 纯 CJK：连续 Han run 成单 token（v1 用重叠 bigram 解决）；
2. mixed-script：ASCII 与 Han 粘连时（如 `abc推荐`、`repo推荐这个`）整体成单 token，
   v1 的 bigram 重写不建立 Han / non-Han tokenizer 边界（len==2 run 替换结果等于原文；
   首/尾 bigram 与相邻 ASCII 仍粘连）。

v2 在 v1 基础上为每个 maximal Han run 建立显式边界：用空格包裹 run
（bigram 序列或单字），使 unicode61 总能切出独立 token。ASCII 内容逐字不动，
URL/code/identifier 内部语义保持不变。

Recall 契约（精确表述）：
- 长度 ≥2 的 Han 子串 ⇔ doc tokens 以保序短语包含查询归一化 bigram 序列（完整召回）；
- 整个keyword为一个Han字符时，原bigram无法命中内部字符，故使用独立unigram主索引，
  完整召回该字符，不改变既有bigram正文、短语和BM25；不在零命中后追加LIKE补查。
- 多词 AND 的独立单字 term 在单字索引求交；其他 term 保留原 bigram 短语和排序。
"""

from __future__ import annotations

import re

# derived index 当前 strategy 标识；与 trivae_derived_meta 中记录值比对判 stale。
# bigram v2保持原样；新增单字索引必须显式重建，旧索引不得冒充支持单字。
FTS_TOKENIZER_STRATEGY_ID = "unicode61+cjk-bigram-v2+han-unigram-v1"

# 连续 Han 意字符 run：CJK 扩展 A + 基本区 + 兼容表意区。
_HAN_RUN_PATTERN = re.compile("[\u3400-\u9fff\uf900-\ufaff]+")


def normalize_lexical_index_text(text: str) -> str:
    """把每个 maximal Han run 替换为空格边界内的重叠 bigram 序列。

    - 长度 ≥2：生成 n−1 个重叠 bigram（真心推荐 → 真心 心推 推荐）；
    - 长度 ==1：单字无法构成 bigram，原字保留；
    - 所有 run 一律以空格包裹，保证与相邻 ASCII/数字形成 tokenizer 边界，
      同时不触碰任何非 Han 字符（foo_bar/github.com/openai-sdk 不变）。
    """

    def _replace(match: re.Match[str]) -> str:
        characters = match.group(0)
        if len(characters) < 2:
            return f" {characters} "
        bigrams = " ".join(
            f"{characters[index]}{characters[index + 1]}" for index in range(len(characters) - 1)
        )
        return f" {bigrams} "

    if not isinstance(text, str):
        raise TypeError("lexical index text must be a string")
    normalized = _HAN_RUN_PATTERN.sub(_replace, text)
    # 相邻 run 的包裹会产生连续空格；折叠为单空格保持索引文本规整。
    return re.sub(" {2,}", " ", normalized).strip()


def normalize_lexical_query_term(term: str) -> str:
    """查询词复用同一归一化函数；保留独立名字以表达 shared-contract 入口。"""

    return normalize_lexical_index_text(term)


def normalize_lexical_unigram_text(text: str) -> str:
    """仅供单字FTS：保留每个Han字符及出现次数，不混入原bigram列。"""
    # 只索引原文Han字符，不引入preview、词义扩展或ASCII前缀匹配。
    return " ".join(character for run in _HAN_RUN_PATTERN.findall(text) for character in run)


def is_single_han_term(term: str) -> bool:
    """按查询形态选择单字主索引，非命中失败后的fallback。"""
    return len(term) == 1 and _HAN_RUN_PATTERN.fullmatch(term) is not None
