"""Lexical derived index 的确定性文本归一化契约。

unicode61 tokenizer 把连续 Han 字符 run 存成单个 token，导致中文子串查询
（例如 "推荐" 无法命中 "真心推荐"）召回缺失。本模块在 rebuild 时把每个
Han run 归一化为重叠 bigram 序列，query 侧使用同一函数，保证：

  doc 含某 Han run 子串 ⇔ doc index tokens 以保序短语包含查询归一化 bigram 序列

非 Han 内容逐字不动；ASCII/URL/code 的 unicode61 exact 语义保持不变。
"""

from __future__ import annotations

import re

# derived index 当前 strategy 标识；与 trivae_derived_meta 中记录值比对判 stale。
FTS_TOKENIZER_STRATEGY_ID = "unicode61+cjk-bigram-v1"

# 连续 Han 意字符 run：CJK 扩展 A + 基本区 + 兼容表意区。
_HAN_RUN_PATTERN = re.compile("[\u3400-\u9fff\uf900-\ufaff]{2,}")


def normalize_lexical_index_text(text: str) -> str:
    """把每个长度 ≥2 的连续 Han run 替换为空格分隔的重叠 bigram。

    单个 Han 字符无法构成 bigram，按原字保留，使单字查询仍可命中单字文档。
    非 Han 输入原样返回，不做任何大小写或标点处理（交给 unicode61）。
    """

    def _replace(match: re.Match[str]) -> str:
        characters = match.group(0)
        return " ".join(
            f"{characters[index]}{characters[index + 1]}" for index in range(len(characters) - 1)
        )

    if not isinstance(text, str):
        raise TypeError("lexical index text must be a string")
    return _HAN_RUN_PATTERN.sub(_replace, text)


def normalize_lexical_query_term(term: str) -> str:
    """查询词复用同一归一化函数；保留独立名字以表达 shared-contract 入口。"""

    return normalize_lexical_index_text(term)
