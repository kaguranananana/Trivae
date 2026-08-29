# 修复 Web UI URL 渲染与 Sources 展示

## Goal

修复 Trivae Web UI 中“回答正文把模型抄错的 URL 变成可点击链接”的问题，并让 Sources 默认折叠，降低长来源列表对正文阅读的干扰。

用户应当只能点击当前最终 Answer Artifact 中由 canonical Message Source 提供、且与 `snapshot.urls` 完全一致的 HTTP(S) URL；来源仍然保持可审计，展开后可以查看现有完整详情。

## Background / Confirmed Facts

- `query/evidence.py` 已在 `ToolMessageItem` 建立时从完整 canonical message 提取 `urls`，在 excerpt 截断前保存，并在 `_hydrate_snapshot()` 中写入可信 `MessageDisplaySnapshot.urls`。
- `answer_source_summaries()` 按最终 Evidence/source 顺序聚合，并按 canonical identity 去重；Web projection 只从 finalized Artifact 投影 Sources，不从 Retrieval Top N、excerpt 或前端相似度猜来源。
- `query/evidence.py` 当前 URL pattern 没有覆盖全角括号、中文引号和中文正文直接相邻边界，也没有用标准库校验 scheme/netloc；现有 `rstrip()` 会把合法/非法尾部统一裁剪，当前可复现 `https://?` 被接纳为 `https://`。
- `web/src/utils/markdown.ts` 当前启用 `linkify: true`，未接收 trusted URL 集合；因此 canonical `https://github.com/foo/bar` 对应的正文 `https://github.com/foo/barABC` 会被 MarkdownIt 直接渲染为 href `https://github.com/foo/barABC`，Markdown `[repo](https://github.com/foo/barABC)` 也会生成错误 href。
- `AssistantTurn.vue` 当前仅调用 `renderMarkdown(item.answer)`，没有把 `item.sources[].snapshot.urls` 传给 renderer。
- `SourcesBlock.vue` 当前显示 header 和全部详情，没有本地展开状态；历史 replay 会复用相同 Source 数据，但组件默认行为尚未定义为 collapsed。
- 现有 Python Evidence 回归只有基础句号/逗号去重测试；现有 Web 测试覆盖 store/process segments，但没有 Markdown trusted-link 或 Sources 组件交互测试。

## Requirements

### R1. Canonical URL extraction

- 扩展 `extract_urls()` 的真实聊天 tokenization：支持 HTTP/HTTPS、query、fragment、`%xx`、多 URL、重复 URL、中文标点/全角括号/引号、Markdown 括号和 URL 与中文文本直接相邻。
- 只允许能通过 `urllib.parse` scheme/netloc 校验、且 percent escape 合法的 URL 进入 trusted URL list；`ftp`、缺少 host、畸形 URL 不进入列表。
- 保留现有 `MAX_SOURCE_URLS`、`MAX_SOURCE_URL_CHARS` 和首次出现顺序；不裁掉 query/fragment 中的合法字符，不把中文边界标点带入 URL。

### R2. Trusted Markdown links

- `renderMarkdown(text, trustedUrls)` 或等价接口接收当前 Answer 的 canonical trusted URL 集合；`AssistantTurn` 从 `item.sources[].snapshot.urls` 读取并去重后传入。
- 自动 linkify 只允许与 trusted URL 完全一致的 URL token；prefix、substring、相似域名、编辑距离和模型猜测都不能成为 href。
- Markdown `[label](href)`、autolink 和自动 URL 都必须经过同一 exact trusted URL 校验；不可信 href 作为普通 Markdown/text 展示，不产生 `<a href>`。
- 保持 `target="_blank"`、`rel="noopener noreferrer"`、HTML 禁用、普通 Markdown、代码块和 inline code 行为。
- 没有 Sources 的非 Tool answer 仍保留普通 Markdown 排版，但正文 URL 和显式 Markdown 外链不获得外部可点击 href，避免模型正文自行成为可信导航目标。
- 不使用最终 HTML 正则替换建立安全边界；校验必须发生在 Markdown token/render 层。

### R3. Sources 默认折叠

- `SourcesBlock` 默认只显示 `▶ Sources · N` 单行按钮；点击后显示 `▼ Sources · N` 和现有全部来源详情，再次点击收起。
- 展开状态只存在于当前 Assistant Turn 的组件实例内；新回答、历史 replay 和多个 Assistant Turn 互不共享，且默认均 collapsed。
- 使用真实 `<button type="button">` 和 keyboard-friendly semantics；不删除 index、author、session、timestamp、relation、excerpt、structured value 或现有 source kind 展示。
- Sources 为空时不显示整个 block；不裁剪来源数量，不修改 Evidence relation/source summarization contract。

### R4. Evidence / Source 语义保持不变

- 保持 `Model claim sources → SourceHandleReference → current Tool Result → provenance/scope validation → trusted snapshot hydration → answer_source_summaries() → Web Sources` 主链路。
- 不把 Retrieval Top N、最近消息、excerpt 相似度或前端自行选取的结果当作 Sources。
- 文档/注释继续明确：Host 校验 source provenance、scope、locator 和 canonical metadata，但 `validate_answer_artifact()` 不承担完整自然语言 semantic entailment judge；`supports/context/contradicts` 是 Evidence semantic relation，最终 Sources 不是随机来源，也不等于独立 LLM Judge 的强相关性认证。

## In Scope

- `src/trivae/query/evidence.py` 的 URL 提取与对应 backend regression tests。
- Web Markdown token-level trusted URL renderer、AssistantTurn trusted URL wiring、SourcesBlock collapsed interaction 与 frontend tests。
- 必要的 frontend test-only dependencies/configuration。
- Web primary interface / Evidence technical decision 中新增的 trusted-link 和 collapsed Source contract 记录。
- 真实 `trivae web` 浏览器验收：GitHub/resource URL case、多 Source 长答案 case、Sources 展开/replay，并记录 Trace ID 和结果。

## Out of Scope

- Retrieval、Evidence selection、Citation finalization、provenance、scope、coverage、conversation persistence 或 Query pipeline 重构。
- Prompt-only URL 修复、模型重试、fallback、降级、自动替换来源或根据相似度猜 URL。
- 新增 deep-link 类型、Structured Source 的伪造 URL、全量聊天浏览器或新的 Source 数据模型。
- 不改变 Source 数量、Evidence relation 语义或最终 Answer Artifact schema。

## Acceptance Criteria

- [x] canonical Message URL 可完整提取；中文标点、全角括号/引号、Markdown 括号不会进入 URL。
- [x] query、fragment、`%xx`、多个 URL、重复 URL、中文相邻 URL 和数量 bound 有回归测试；malformed/非 HTTP(S) URL 被排除。
- [x] trusted canonical URL exact match 可点击且 href 完全一致；扩展/截断/错误 Markdown href 不产生外链。
- [x] 普通 Markdown、代码块、inline code、HTML 禁用、target/rel 行为保持；无 Sources answer 的 URL 不会成为未经验证的外链。
- [x] Sources 初始 collapsed，显示 `Sources · N`；点击展开完整详情，再次点击收起；空列表不显示。
- [x] 多个 Assistant Turn 和 conversation replay 的 Sources 状态相互独立且默认 collapsed。
- [x] 既有 Evidence hydration、provenance、scope、coverage、citation/source summary 测试全部继续通过。
- [x] 相关 Python/Web unit、typecheck、lint、build 通过；真实 Web UI 至少完成两类验收并记录实际 Trace ID。

## Risks / Deferred Items

- URL 与英文标点直接相邻时，某些字符同时可能是 URL 合法字符和句末标点；实现必须优先保证 exact trusted contract，并以边界回归测试固定选择，不扩大为模糊猜测。
- 已持久化的旧 Artifact 可能没有 `urls` 字段；既有 codec 的 additive replay 兼容性保持不变，前端只对实际存在且合法的 trusted URL 建立链接。
- 本任务验证 Host 的确定性来源绑定和 UI 导航边界，不新增 semantic entailment judge；回答与来源的自然语言强相关性仍由现有 Evidence contract、Prompt 和后续 Evaluation 负责。
- 真实 Web 验收依赖当前本地数据库、语义索引、Provider 配置和浏览器环境；若 Provider/环境失败，保留 trace/error 证据并区分于本任务代码 Failure。
