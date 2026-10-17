# Research: ChatLab Semantic 增量索引参考

- Query: ChatLab 如何处理 Semantic 追加、历史补录、重切、存储事务与恢复？
- Scope: internal（本机参考 checkout）
- Date: 2026-10-17

## Findings

本机参考仓库 `../ChatLab`，origin 为 `kaguranananana/ChatLab`；直接读取 `.git/HEAD` 与 ref 得到 main commit `088d3ee54d7bb77ba61ed589fd2a414ce55dec66`，没有执行任何 git 命令或修改参考仓库。

### Files found / Code patterns

- `packages/node-runtime/src/semantic-index/warmup/runner.ts`：构建与续建编排。第 65–84 行每次读取全部消息并全量重切，依据游标的新 stream position 与历史 indexedMessages 判断非追加；历史补录直接删除整个聊天索引并重新 embedding。
- 同文件第 93–111 行：纯追加找到覆盖旧游标的 Child，再找该 Child 所属 Parent 的最早 Child 起点，从该位置删除所有后继旧 Chunk，把 resumeIndex 回退至起点前。
- 同文件第 119–175 行：只对游标后新结果调用 embedding，逐批写入，单独写业务进度。第 178–184 行设置 completed 或 failed；已写批次保留供续建。
- `packages/node-runtime/src/semantic-index/store.ts`：第 120–173 行写 Chunk metadata 与 vec0 同一事务；唯一 Chunk ID 已存在则忽略，支持续建幂等。第 250–290 行按聊天顺序位置成对删除 metadata / vec0，事务内保证这一删除操作原子性。
- `packages/node-runtime/src/semantic-index/service.ts`：第 461–470 行仅凭消息数增加触发 build、减少触发 rebuild；第 829–853 行显式 rebuild 清空后运行 warmup。
- `packages/node-runtime/src/semantic-index/chunker.ts`：Parent/Child 纯函数，与向量存储分离。

### External references / primary links

以下链接固定到本机已阅读 commit，属于源实现本身：

- [warmup/runner.ts](https://github.com/kaguranananana/ChatLab/blob/088d3ee54d7bb77ba61ed589fd2a414ce55dec66/packages/node-runtime/src/semantic-index/warmup/runner.ts#L65)
- [store.ts](https://github.com/kaguranananana/ChatLab/blob/088d3ee54d7bb77ba61ed589fd2a414ce55dec66/packages/node-runtime/src/semantic-index/store.ts#L250)
- [service.ts](https://github.com/kaguranananana/ChatLab/blob/088d3ee54d7bb77ba61ed589fd2a414ce55dec66/packages/node-runtime/src/semantic-index/service.ts#L461)

### Related specs

- `.trellis/spec/backend/database-guidelines.md`：Canonical 是事实源；Chunk 只提供派生 acquisition metadata；Semantic identity 与 source revision 校验。
- `.trellis/spec/backend/forwarded-message-guidelines.md`：转发 occurrence、容器边界和双时间。
- `.trellis/spec/project/engineering-principles.md`：根因优先，禁止内容摘要指纹，禁止无依据兼容与降级。

### 对 Trivae 的适用结论

可复用“重切是纯函数、追加要回退 Parent、metadata/vec0 同事务”的设计原则。不能照抄其消息数/游标作为完整变化检测，也不能照抄历史补录全量 embedding；用户明确要求覆盖相同数量的正文/转发变化及历史局部更新。ChatLab 允许部分构建检索，Trivae 的既有 revision/readiness 约束更严格，必须沿用 Trivae 约束。

## Caveats / Not Found

- 这是本机 checkout 指定 commit 的静态审计，不宣称它是远端最新版本。未联网、未 fetch；本任务无需远端当前状态。
- ChatLab 的实现存储内容指纹，但 Trivae 项目禁止新增该机制；参考事实不构成采用授权。
- 参考实现的跨批写入、进度写入并不是整次增量发布事务；不能据此声称整次更新原子性。
