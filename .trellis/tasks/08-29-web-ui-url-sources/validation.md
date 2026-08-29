# Validation Record

## 1. Root Cause and Failure Cases

- `real failure`：`web/src/utils/markdown.ts` 原先启用 `MarkdownIt` 的 unrestricted `linkify`。当 canonical source URL 为 `https://github.com/deepseek-ai/deepseek-harness/`、回答正文出现相似或扩展字符串时，renderer 会直接按模型文本生成 href；这是 UI 导航信任边界的问题，不是 Evidence Finalizer 失去 provenance 校验。
- `regression test case`：`src/trivae/query/evidence.py` 原先只用候选正则加 `rstrip()`，中文/全角边界、Markdown 成对括号和 malformed URL 没有独立校验；坏候选可能被裁剪后进入 trusted URL list。
- `real failure`：`web/src/components/chat/SourcesBlock.vue` 原先没有展开状态，所有 source detail 首次渲染；长回答下来源列表可能比正文更长。
- 定位方式：先读取 Evidence snapshot hydration、final source summary 和 Web projection，确认 source selection 链路不应改动；再用 focused regression cases 复现错误 href、边界 URL 与默认展开行为。新回归在产品代码修改前先运行并失败，随后用最小主链路修复。

## 2. Design Rationale / Why Not

- 选择 backend canonical URL tokenization + `urllib.parse.urlsplit` 校验：trusted URL 的事实边界仍在 canonical Message projection，能保留 query/fragment/percent escape，同时拒绝缺 host、坏 percent、坏 port 和非 HTTP(S) 候选。没有引入重型 URL parser 或改变 Source schema。
- 选择 Markdown token 层 exact matching：自动 URL、autolink 与显式 Markdown href 共用同一 trusted set；不可信 link 只移除 anchor wrapper，正文 Markdown 仍可读。最终 HTML 正则无法可靠区分 code、escaped text 和 link token，因此不是安全边界。
- 选择 `SourcesBlock` 实例内 `ref(false)`：它只负责 UI 展示状态，不把状态放入 Pinia、conversation payload 或 backend artifact，因而自然支持多回答和 replay 的独立默认折叠。
- `permanently rejected`：Prompt-only URL 修复、excerpt 相似度猜 URL、Retrieval Top N 直出 Sources、以及为坏 href 加相似 URL fallback；这些都会把确定性导航或 Source 语义重新交给模型/猜测逻辑。
- `currently unnecessary / waiting for evaluation evidence`：没有新增独立 semantic entailment Judge。当前 task 只验证 provenance/scope/locator/canonical metadata 与 UI 导航边界；若未来真实 Evaluation 证明语义误绑是稳定 Failure Case，再单独启动 Evidence/Evaluation 任务。

## 3. Evaluation / Evidence

### Automated gates

| Command | Result |
| --- | --- |
| `PYTHONPATH=src .venv/bin/pytest -q` | `513 passed in 15.71s` |
| `.venv/bin/ruff check src tests` | passed |
| `.venv/bin/mypy src` | passed，100 source files |
| `pnpm test` | 5 files / 23 tests passed |
| `pnpm run typecheck` | passed |
| `pnpm run lint` | passed |
| `pnpm run build` | passed，Vite transformed 123 modules |
| `git diff --check` | passed |
| `python3 ./.trellis/scripts/task.py validate web-ui-url-sources` | passed，`implement.jsonl` / `check.jsonl` 均为 0 entries |

Regression suites cover exact trusted href and `target`/`rel`, rejected prefix/substring/explicit href, Markdown/code/HTML behavior, Chinese/fullwidth URL boundaries, query/fragment/percent escapes, malformed/non-HTTP(S) candidates, Sources expand/collapse/details/empty/multi-instance/replay state.

### Real Web acceptance

Command:

```text
.venv/bin/trivae web --database data/trivae.sqlite3 --port 8710 --no-open
```

Case A — GitHub/resource URL and misleading adjacent prose:

- Trace ID：`trace-012be0958f9a404eb6c1aea943694e73`。
- Answer rendered exactly one external anchor for `https://github.com/deepseek-ai/deepseek-harness/`; its `href` exactly matched the canonical URL and retained `target="_blank"` plus `rel="noopener noreferrer"`。
- The misleading expanded URL did not become an anchor. Clicking the rendered link opened a browser tab whose title and URL were the DeepSeek Harness GitHub page, confirming the actual navigation target。
- The current Sources button started as `▶ Sources · 5` with `aria-expanded=false` and no detail list; expanding showed 5 source items, and the next click collapsed them again。

Case B — long answer and many Sources:

- Trace ID：`trace-e9e15f4d3d2f499291271f011a18edd4`。
- The long answer showed `▶ Sources · 28` initially, with no source list in the DOM. Expansion changed it to `▼ Sources · 28` and rendered all 28 detail items; collapse removed the list again。
- At the same time, the page contained three assistant answers with source counts 12, 5 and 28. Their initial states were all collapsed. After reload, all three remained collapsed and all three Trace IDs were present, proving history replay did not persist an expanded UI state。

## 4. Observability / Boundary / Evolution

- Trace IDs and source counts remain visible through the existing Web Trace footer and finalized source projection. URL rendering does not create a new retrieval or citation path, so a navigation mismatch can be distinguished from a provenance/finalization failure。
- Ownership remains: backend canonical extraction owns `snapshot.urls`; Finalizer/source summary owns which Sources are displayed; Web renderer owns exact navigation eligibility; `SourcesBlock` owns only per-instance presentation state。
- No new retry, fallback, compatibility branch, silent error handling, source guessing, or Source count truncation was added. A future semantic-quality issue would require an evidence-backed Evaluation failure before changing the current Judge boundary。

## 5. Final Decision

All task acceptance criteria are met by automated tests, type/lint/build gates, and the two real Web acceptance cases above. The task directory is ready for the Trellis archive step after the work commit。
