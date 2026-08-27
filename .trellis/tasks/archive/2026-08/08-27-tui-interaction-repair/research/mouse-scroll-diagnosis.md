# A3 根因诊断：鼠标滚动真机问题定位（2026-08-27）

## 现象

Pilot 直接向 #history 注入 `MouseScrollUp` 的测试通过，但用户真机（macOS 中文
IME 环境）滚轮无法滚动（handoff addendum A3）。

## 两级验证结论：代码层与协议层均无故障

### 第 1 层：冒泡 Pilot 测试（新增长期回归）

`tests/test_tui_app.py::TuiAppInteractionTests::test_wheel_bubbles_from_inner_children_to_history`

构造长历史（AnswerBlock Markdown 40 行正文 + ProcessRow 完成态行 +
ProcessGroupWidget），把 wheel 事件发往**视口内实际命中 #history 后代的屏幕坐标**
（模拟真机悬停），断言：

- 从 AnswerBlock 正文区域向上滚 → `follow_tail` 解除、`scroll_y < max_scroll_y`；
- Home 回顶后从 ProcessGroupWidget 区域向下逐格滚动 → 到达真实底部后
  `follow_tail` 恢复、`is_vertical_scroll_end == True`。

结果一次通过 —— 说明 Textual 8.2.8 下 mouse scroll 冒泡链路
（内层 widget → Vertical → FollowTailHistory）无截获者；
`FollowTailHistory.on_mouse_scroll_*` 与基类滚动行为组合正常。

### 第 2 层：SGR mouse 序列端到端解析验证（一次性脚本）

脚本位置（不入库）：`/var/folders/.../opencode/verify_sgr_mouse.py`
模拟真实终端发送的 xterm SGR 编码 bytes，直接喂给 Textual 8.2.8 输入解析器
`textual._xterm_parser.XTermParser`：

```
OK  '\x1b[<64;10;5M' -> MouseScrollUp x=9 y=4
OK  '\x1b[<64;1;1M\x1b[<65;3;7M' -> ['MouseScrollUp', 'MouseScrollDown'] coords=[(0, 0), (2, 6)]
```

`\x1b[<64;x;yM`（wheel up）与 `\x1b[<65;x;yM`（wheel down）、包括两个事件同 chunk
的边界切分，全部正确解码为带正确坐标的 Mouse 事件。

## 结论

app 代码与 Textual 8.2.8 解析层都能正确处理真实 SGR 滚轮序列；剩余解释是**用户
终端应用的鼠标事件直通限制**（例如 Warp 在部分模式下把滚轮翻译成方向键、或未开启
mouse reporting 直通——其已知的 wheel 处理问题）。按 addendum 约定不引入任何
workaround 代码；终端兼容矩阵已记录在
`.trellis/spec/backend/product-experience-guidelines.md` §10，
待用户确认实际终端型号后归档该条目。

## 2026-08-27 二次故障：根因定案（iTerm2 Mouse Reporting 被永久关闭）

用户终端确认为 iTerm2。二次故障现象：滚动与拖选**同时**失效，且失灵前
iTerm2 弹出一个带 "Permanently" 按钮的对话框，用户点击后立即出现故障。

### 硬证据（本机 plist）

`defaults read com.googlecode.iterm2`：

```
"Mouse Reporting" = 0;
Name = Default;    ← 该键位于 Default profile 内
```

iTerm2 默认该值为启用（1/true）。用户点击弹窗的 Permanently 后，iTerm2 把
Default profile 的鼠标上报永久关闭。后果：iTerm2 不再把滚轮/拖选转成 mouse
事件发给 TUI 应用 → app 的 mouse scroll 与 Textual in-app selection 同时失效
（两条症状同一通道，与 app 内代码无关——本轮冒泡/协议两级测试均绿即为佐证）。

### 恢复步骤（用户侧 UI 操作）

1. iTerm2 → Settings (⌘,) → Profiles → Default → **Terminal** 标签页
2. 找到 **Mouse reporting** 相关复选框，重新勾选启用
3. 重跑 `uv run trivae chat` 验证滚轮与拖选恢复

临时自救（不修设置也能用）：按住 **Option/Alt 拖选** 可绕过 mouse reporting
做 iTerm2 本地选择（官方 FAQ 证实的行为）。

### 经验记录

- TUI 首次开启 mouse reporting 时 iTerm2 会弹权限确认；选 Deny/Permanently
  分支即产生本故障。用户应选 Allow（或 Allow permanently）。
- 终端兼容矩阵 §10 的"待用户确认"条目随之关闭：实际终端为 iTerm2，通道级
  故障与 Trivae 代码无关，无需任何 app 侧 workaround。
