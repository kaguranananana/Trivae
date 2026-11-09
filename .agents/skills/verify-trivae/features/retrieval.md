# 群聊检索

用户在所选聊天范围内寻找明确的字词，或用不同措辞查询相似内容，再回到原始消息。

## Sub-features

- `lexical-scope` 验证群范围、命中上限和截断。
- `lexical-freshness` 验证旧索引显式报错，重建后新消息可查。
- `lexical-cjk` 验证中文子串命中。
- `semantic-source` 验证向量命中可回查 Canonical 消息，重开后索引仍有效。
- `import-search` 验证一次导入更新索引后可搜到原生和转发内容。

## How to get to it (user POV)

在 Web 问答中选择群聊范围并发起查询，或从 `trivae chat --database <db>` 提问。Agent 可使用 `lexical_search` 和 `semantic_search`。导入并自动更新索引的用户入口是 `trivae import-once`。

## Driving it with pytest

前提是已完成 Skill 的 Launch。fixture 负责导入合成群聊和构建索引。

- 全文检索运行 `tests/test_lexical_retrieval.py::LexicalRetrievalTests::test_fts5_rebuild_and_session_scoped_bounded_hits` 与同类的 `test_new_canonical_message_requires_explicit_rebuild`。群 `qq:100` 内共有五条 `alpha` 命中，最多返回三条且标记截断。新增消息后旧索引报错，重建后恢复。
- 中文子串运行 `tests/test_chinese_lexical_regression.py::ChineseLexicalRetrievalTests::test_chinese_substring_query_hits_all_containing_messages`，将 FTS 命中与 fixture 中包含子串的消息集合核对。
- 语义检索运行 `tests/test_semantic_retrieval.py::SemanticRetrievalTests::test_application_builds_independent_semantic_index_and_recovers_canonical_messages`。命中原文 `qq:100:m1`，向量及 metadata 一致，重开后索引仍有效。
- 导入更新运行 `tests/test_import_index_updates.py::test_real_updater_makes_new_native_and_forwarded_messages_available_to_agent`。检查无待更新索引，转发内部命中回到 `qq:12345:outer`，语义索引状态为 `completed`。

## Gotchas

- 固定向量只验证索引、检索与原文回查，真实模型的语义排序需要自己的数据和参考标注。
- 普通 `trivae import` 与更新索引是分开的操作。旧索引的错误是可观察的产品状态。
