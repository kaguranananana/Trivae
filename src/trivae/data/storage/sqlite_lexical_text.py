"""Lexical derived index 的确定性文本归一化契约。

unicode61 把连续的字母/数字/CJK 字符视为一个 token，导致两类中文召回缺失：

1. 纯 CJK：连续 Han run 成单 token（v1 用重叠 bigram 解决）；
2. mixed-script：ASCII 与 Han 粘连时（如 `abc推荐`、`repo推荐这个`）整体成单 token，
   v1 的 bigram 重写不建立 Han / non-Han tokenizer 边界（len==2 run 替换结果等于原文；
   首/尾 bigram 与相邻 ASCII 仍粘连）。

v2 在 v1 基础上为每个 maximal Han run 建立显式边界：用空格包裹 run
（bigram 序列或单字），使 unicode61 总能切出独立 token。ASCII 内容逐字不动，
URL/code/identifier 内部语义保持不变。

  doc 含某 Han 子串 ⇔ doc tokens 以保序短语包含查询归一化 bigram 序列
"""

from __future__ import annotations

import re

# derived index 当前 strategy 标识；与 trivae_derived_meta 中记录值比对判 stale。
# v2：在 v1 bigram 基础上增加 Han/ASCII 边界包裹。
FTS_TOKENIZER_STRATEGY_ID = "unicode61+cjk-bigram-v2"

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
