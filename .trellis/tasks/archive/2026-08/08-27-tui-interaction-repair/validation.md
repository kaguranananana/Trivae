# TUI interaction repair validation

## Automated verification

- `.venv/bin/python -m pytest -q`：438 passed。
- `.venv/bin/ruff check src tests`：通过。
- `.venv/bin/mypy src`：91 个源码文件通过。
- `.venv/bin/python -m compileall -q src tests`：通过。
- `git diff --check`：通过。
- 全量 pytest 同时覆盖 plain CLI renderer，确认 TUI 投影扩展没有改变普通终端渲染主链路。

## Deterministic interaction coverage

- Projection 覆盖三段独立 thinking、两个 Tool 与最终 Answer 的时间线顺序；hidden 或未标记 reasoning 不会进入 TUI state。
- Tool detail 覆盖 call identity、同名并发、乱序事件、20 items、800 chars/field 与 16,000 chars 总预算；preview omission 与 canonical partial/truncated 分开断言。
- Retrieval 只通过 `parent_operation_id` 关联精确 Tool，不再猜测最后一个 running Tool。
- Pilot 使用真实 `scroll_y/max_scroll_y` 验证 wheel、PageUp、PageDown、Home、End、新 round 和 stream append 的 Follow Tail 状态转换。
- Pilot 使用 Textual 原生 selection 验证 Answer、Thinking、Tool Result 拖选与 Ctrl+C；同时验证运行时中断、空闲 no-op、header-only toggle 和正文不折叠。
- 成功、失败、中断三个终态都会关闭 running thinking/tool，Answer delta 与 authoritative completed replacement 保持原有行为。

## Real PTY smoke

- 通过真实 `.venv/bin/trivae chat` 启动会话选择器，数据库加载成功并进入“全部群聊”。
- 提交复杂查询：`请总结最近群聊中关于 GitHub 项目、AI 技能或学习资源的推荐，按类别列出具体名称和链接，并说明证据来源与覆盖边界。`
- Runtime 生成 5 步计划；TUI 最终收束为 9 个过程步骤，过程中出现 Tool 前后多个独立 thinking 行，没有被合并成单行。
- 实际执行两次 recent-message 查询与两次 lexical search；其中一次检索展示 `93 hits / 93 msgs / +93 ctx / total 93 / 2.7s`，Tool 与 retrieval summary 保持同一操作行。
- Provider 确实提供 public summary；只验证其存在与生命周期顺序，未把正文写入本验收记录，也未持久化 hidden chain-of-thought。
- 87 秒后过程组完成并折叠，最终 Answer 与“来源与证据”区域正常显示；输入框恢复可用，无残留 spinner。
- `/exit` 在空闲终态正常退出，进程返回码为 0；此前独立 smoke 也验证了 Ctrl+Q 显式退出。

## Result

全部 Acceptance Criteria 已满足。工作区代码尚未提交，因此按 `trellis-finish-work` 规则暂不归档任务；提交后即可执行任务归档和 session journal 记录。
