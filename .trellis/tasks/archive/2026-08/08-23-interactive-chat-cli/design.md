# Technical Design

## Behavior Gap

当前 CLI 只有一次性/已有命令入口，缺少“选择群聊后持续提问”的 interface adapter。核心 Query path 已存在，缺口在于入口如何获取 session metadata、组装 trusted scope、维护两个独立的 CLI 状态，以及把结果投影为人工可读输出。

## Boundary and Data Flow

```text
trivae chat
  -> CLI parser
  -> Application factory
  -> Application.list_sessions() / existing read contract
  -> selected_session_id -> ExecutionScope
  -> QueryRequest(query, scope, conversation_id)
  -> TrivaeApplication.query()
  -> final_answer / trace_id / conversation_id projection
```

CLI 只负责参数、输入循环和输出。Session 列表由 Application facade 暴露已有 Canonical Read 能力；Query 仍唯一进入 `TrivaeApplication.query()`。`selected_session_id` 与 `conversation_id` 作为不同局部状态维护。

## Expected Changes

- `src/trivae/interfaces/cli.py`：新增 chat command、session picker、输入循环和最小错误/结果 projection；使用现有 CLI 风格，不引入 Rich/Textual。
- `src/trivae/bootstrap/application.py`：若现有公开 facade 不足，只增加一个返回现有 session metadata 的薄 read 方法；不新建数据库访问体系。
- `tests/`：使用 fake Application / scripted input / fake QueryResult，覆盖 parser、scope、conversation、result projection、退出和既有命令回归。

## Error Semantics

已分类的 Settings、Application、Query、Scope 类错误按现有 CLI 错误风格输出安全可读消息；Ctrl+C/EOF 是正常结束；未知异常不使用 catch-all 静默吞掉，保留 traceback 或现有可诊断行为。

## Non-goals

不增加动态换群、会话浏览、Trace viewer、Provider selector、第二套 Provider/Runtime/Retrieval 路径、streaming renderer、配置框架或核心 Query 语义修改。
