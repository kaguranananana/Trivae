# Design: Web UI trusted URL rendering 与 Sources 折叠

## 1. Change boundary

### 最小行为差距

当前 canonical Source URL 已经被 Host hydrate 到 `MessageDisplaySnapshot.urls`，但 Markdown renderer 把模型正文中的任意 URL 当作可点击链接；同时 Sources 详情默认展开。目标是只改变 UI 导航可信边界和 Source 展示状态，不改变 Evidence/Citation 的来源选择或验证语义。

### 真实 ownership

```text
Canonical Message
  → extract_urls()
  → ToolMessageItem.urls
  → _hydrate_snapshot()
  → AnswerArtifact / answer_source_summaries()
  → Web SourceItem.snapshot.urls
  → AssistantTurn trusted URL set
  → Markdown token renderer
```

```text
AssistantItem.sources
  → SourcesBlock instance-local expanded=false
  → button toggle
  → existing source detail projection
```

URL 可信来源由 backend canonical snapshot 负责；Markdown 只消费 `SourceItem.snapshot.urls`，不解析 excerpt、不重新检索、不从正文猜 URL。Sources 折叠由每个 `SourcesBlock` 组件实例负责，Sources 数据仍由 finalized Artifact projection 提供。

### 预期文件边界

- `src/trivae/query/evidence.py`：修复 canonical URL tokenization 和 URL validation；不改 source handle、finalizer、scope 或 source summary。
- `tests/test_evidence.py`：先加入可复现 URL Failure Case 和 extraction contract regression。
- `web/src/utils/markdown.ts`：将 unrestricted linkify 改成 token-level exact trusted-link renderer，保留 Markdown 配置和 cache。
- `web/src/components/chat/AssistantTurn.vue`：从 `item.sources[].snapshot.urls` 派生去重 trusted URL 集并传给 renderer。
- `web/src/components/chat/SourcesBlock.vue`：增加实例内 collapsed/expanded 状态，保持现有 source detail markup。
- `web/tests/markdown.test.ts`、`web/tests/SourcesBlock.test.ts`：覆盖 URL/Markdown 和折叠/replay/多实例行为。
- `web/package.json`、`web/pnpm-lock.yaml`：如现有测试运行时没有 DOM mount 能力，只增加 test-only `@vue/test-utils` 与 `happy-dom`。
- `.trellis/spec/project/technical-decisions/web-primary-interface.md`：记录 Web trusted-link 与 Sources collapsed contract；不改 Stage 1.8 Evidence ownership。

## 2. Backend URL extraction design

### Tokenization

保留轻量正则作为 URL 候选扫描器，但把“边界字符”和“合法性”拆开：

1. 候选只从 `http://` / `https://` 开始。
2. 候选扫描器排除空白、尖括号、中文句末标点、全角括号、中文/英文引号以及 CJK 正文字符，避免 URL 与中文正文直接相邻时吞掉后文。
3. ASCII URL 合法字符（query、fragment、`%xx`、reserved characters）不从扫描器中排除。
4. 尾部 ASCII `)`/`]`/`}` 只在没有对应 opening character 时剥离；URL 内部成对括号保留，Markdown 外层括号不会进入结果。
5. 每个候选先检查长度，再用 `urllib.parse.urlsplit` 验证 scheme、非空 netloc、hostname 和 port；访问 `.port` 时捕获解析错误。
6. 对 `%` 做两位十六进制校验；失败候选直接丢弃，不进入 `seen`，不影响后续合法 URL。
7. 通过校验后按首次出现顺序去重，并继续应用 `MAX_SOURCE_URLS` bound。

这样 `https://github.com/foo/bar?x=a%20b#readme` 的 query/fragment 保持原样；`（https://github.com/foo/bar）`、`“https://example.com/a”` 和 `资源https://github.com/foo/bar随后` 只产生 URL 本体；`https://?`、坏 percent、`ftp://` 不会成为 trusted URL。

### 为什么不在 Finalizer/前端重新猜

`extract_urls()` 读取的是 canonical message content，属于可信 Source snapshot 的生成边界；Finalizer 继续只 hydrate 该结果，前端只接收 `snapshot.urls`。这避免把模型 `claims[*].text`、excerpt 或相似字符串引入导航信任判断。

## 3. Frontend trusted Markdown design

### Renderer contract

```ts
renderMarkdown(text: string, trustedUrls?: readonly string[]): string
```

- renderer 默认不启用 MarkdownIt 内置 unrestricted `linkify`，而是在 Markdown token 阶段对 text token 做 exact trusted URL 匹配。
- `trustedUrls` 先去重，并只保留可由 `URL` 解析且 protocol 为 `http:`/`https:` 的原始字符串；不做 URL 规范化后再匹配，href 必须与 canonical 字符串完全相同。
- token matcher 只匹配 trusted URL 本身；若后面紧跟 ASCII URL continuation（如 `ABC`、query/fragment continuation），则不匹配短 prefix；中文正文、中文标点、空白、Markdown 外层标点可作为 token 边界。
- MarkdownIt 的 `link_open` token 读取 href 并做 exact set membership；不在 set 中时只移除 link wrapper，保留 label 的 Markdown children，不输出任何 `<a>`。
- 自动链接和显式 Markdown 链接都在 token 层处理；不使用最终 HTML 正则替换。
- 既有 `link_open` renderer 继续添加 `target="_blank"` 和 `rel="noopener noreferrer"`。因不可信 link token 已在更早阶段移除，renderer 不会给不可信 href 补属性。
- 代码 token、fence token、HTML disabled token 不会进入 text-token matcher；普通 emphasis、paragraph、breaks 和 Markdown label children 保持原有渲染。

### No-Source behavior

非 Tool answer 传入空 trusted set 时，普通 Markdown（标题、强调、列表、代码等）照常工作，但 raw URL、显式 Markdown external href 和 autolink 不产生 `<a href>`。这是“正文 URL 不能独立成为可信导航目标”的确定性边界；用户仍能看到原始 URL 文本。

### Cache

现有 LRU cache 的 key 必须包含 answer text 和 canonical trusted URL set；同一文本在不同 Source 集合下不能复用错误 HTML。URL 集合以排序后的去重内容形成 key，渲染结果仍最多保留现有 32 条。

## 4. Sources component design

- `SourcesBlock` 使用 `ref(false)` 作为实例本地 `expanded` 状态。
- root 在 `sources.length > 0` 时才渲染；button 通过 `type="button"`、`aria-expanded` 和方向指示符表达状态。
- collapsed 时只保留一行 header button；expanded 时在同一组件内显示原有 `<ol>`、message metadata、relation、excerpt 和 structured value。
- `AssistantTurn` 不保存 Source UI 状态，也不把状态放入 Pinia；每个回答组件自然拥有独立状态，conversation replay 新建组件后重新得到 collapsed 初始值。
- 样式沿用 completed Process Group 的 border/background/button spacing，不改变 Source count 或 backend source order。

## 5. Source semantics documentation

Web ADR 补充以下明确语义：Sources 是通过 Finalizer 的 Evidence claim/source 绑定，按 canonical identity 去重后的可审计投影；不是 Retrieval Top N 或随机挑选。`supports/context/contradicts` 表达 Evidence 与 finding 的 relation，Host 只做 provenance/scope/locator/canonical metadata validation，不承担完整自然语言 semantic entailment judge，也不宣称 Sources 已被独立 LLM Judge 认证强相关。

## 6. Compatibility / rollback

- backend `extract_urls` 输出仍是 tuple[str, ...]，只收紧 malformed/边界 token；既有 `snapshot.urls`、conversation codec 和 Web DTO shape 不变。
- frontend `SourceItem`、`StreamEnvelope`、Conversation replay payload 不变；只新增 renderer 参数和组件本地状态。
- 若 frontend test-only DOM dependency 安装失败，不改变产品实现以绕过测试；保留纯 renderer regression，并显式报告组件交互验证阻塞。
- 回滚只需恢复 URL extractor、renderer wiring 和 SourcesBlock 三个产品文件；不触碰 Retrieval、Finalizer 或 persisted Artifact。
