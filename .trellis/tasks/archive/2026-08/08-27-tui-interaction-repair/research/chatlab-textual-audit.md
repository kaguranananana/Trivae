# ChatLab and Textual audit

## ChatLab current implementation

- Audited commit: `dcee433174f3889d0832abfa74426243deccdb68` (2026-08-27).
- Current source: https://github.com/ChatLab/ChatLab/blob/dcee433174f3889d0832abfa74426243deccdb68/src/components/AIChat/chat/chatMessageProcessSegments.ts
  - active run uses `mode='timeline'`; completed run uses one process segment;
  - process blocks remain in source order;
  - manual open override wins; error segments default open.
- Current renderer: https://github.com/ChatLab/ChatLab/blob/dcee433174f3889d0832abfa74426243deccdb68/src/components/AIChat/chat/ChatMessage.vue
  - thinking and Tool each use a disclosure header separated from detail body;
  - Tool detail uses `displayResult ?? result`, explicitly described as safe text sent to AI;
  - completed Tool result is copyable and scroll-bounded;
  - Answer remains outside completed process group and carries highest prose weight.
- Relevant history:
  - process folding: https://github.com/ChatLab/ChatLab/commit/a98b9b55bf1f035cb37224ec68e006ce7e0194a6
  - safe Tool result disclosure: https://github.com/ChatLab/ChatLab/commit/2ec99e5880153c5d1823b69a19193df11ab1789e
  - unified process detail: https://github.com/ChatLab/ChatLab/commit/c44180ca119987d1e24de93c2ca34adcca9c6233
  - failed process stays open: https://github.com/ChatLab/ChatLab/commit/dd2d5dd39fe2077c3862d1db6dd8f0ef130811b3

## Textual selection contract

- Repository currently resolves Textual 1.0.0. Its release supports Input/TextArea selection/copy but not arbitrary Static/Markdown selection:
  https://github.com/Textualize/textual/releases/tag/v1.0.0
- Textual 2.0.0 added arbitrary selection, `Widget.ALLOW_SELECT`, Screen selection and Ctrl+C copy:
  https://github.com/Textualize/textual/releases/tag/v2.0.0
- Current latest stable checked on 2026-08-27 is 8.2.8:
  https://github.com/Textualize/textual/releases/tag/v8.2.8
- Current official source exposes `Screen.get_selected_text()`, `Screen.action_copy_text()` and `Widget.get_selection()`:
  https://github.com/Textualize/textual/blob/06dbeef4bb70fb718236aa418ed658ef4667a126/src/textual/screen.py
  https://github.com/Textualize/textual/blob/06dbeef4bb70fb718236aa418ed658ef4667a126/src/textual/widget.py
- Compatibility probe with Textual 8.2.8: 25/26 existing TUI tests passed; one failed only because the test reads removed `Static.renderable`. `Markdown.update`, `Collapsible`, Worker flow and Pilot run remained operational in the targeted suite.

## Local root-cause evidence

- Current targeted baseline: 37 tests passed under Textual 1.0.0.
- A direct reducer reproduction with three public-summary segments and two tools produced exactly:

```text
thinking thinking completed 'ABC'
tool:a tool completed None
tool:b tool completed None
```

  This proves current green tests do not cover segment boundaries.
- Existing real DeepSeek validation records public reasoning and actual order `thinking → tool/retrieval → thinking → answer`; no reasoning/content delta is persisted to Trace by design. See archived task `08-23-interactive-cli-streaming-events/validation.md` and `08-27-tui-chat-projection/validation.md`.
- Tool Result detail loss occurs after capability execution: RuntimeContext already owns bounded `ToolResultRecord`, but RuntimeEvent tool completion carries only `RuntimeToolCall`; normalized terminal payload keeps status/error only. The missing projection is therefore Runtime→Query, not Widget data fetching.

