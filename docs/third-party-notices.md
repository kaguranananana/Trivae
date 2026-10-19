# 第三方来源与许可证

## Trivae 的许可状态

当前仓库未声明 Trivae 整体的分发许可证。这里不授予 MIT、Apache-2.0 或其他项目级许可，也不将第三方许可证自动视为 Trivae 全仓许可证。公开源码前，需要维护者完成下述代码来源与许可适用范围确认，再补齐正式许可及必要声明。

## ChatLab

- 上游：[ChatLab/ChatLab](https://github.com/ChatLab/ChatLab)。归属：ChatLab 项目及其贡献者。
- 上游许可证：[GNU Affero General Public License v3.0](https://github.com/ChatLab/ChatLab/blob/0edc64d99a243eb2de5e32213082807bc419e942/LICENSE)；本仓库附有[许可证原文](licenses/ChatLab-AGPL-3.0.txt)，仅作为该第三方来源的许可副本。
- Trivae 的架构参考了 ChatLab；以下前端文件还明确记录了相关实现来源，不仅是产品定位上的参考。

| 本仓库文件 | 来源与本地变化 |
| --- | --- |
| [processSegments.ts](../web/src/components/chat/processSegments.ts) | 文件头标记继承上游 `src/components/AIChat/chat/chatMessageProcessSegments.ts`；时间线/完成态分组逻辑可对应。Trivae 对回调名称、类型检查和界面过程块作了适配。 |
| [AssistantTurn.vue](../web/src/components/chat/AssistantTurn.vue) | 记录参考 ChatLab ChatMessage 模式，使用 Trivae 的过程块、回答与来源投影。 |
| [chat.ts](../web/src/stores/chat.ts) | 记录参考 ChatLab aiChat buffer 模式；接入 Trivae 的 HTTP 流、scope 和会话持久化契约。 |

2026-10-19 审查已核实上游 `0edc64d99a243eb2de5e32213082807bc419e942` 的 LICENSE 与过程分段源码，以及本仓库上述来源标记；这不是对全部历史代码的逐行原创性或衍生关系认定。现有源码中的来源说明保留。

**公开前待办**：维护者需核实实际引入时版本及覆盖范围，确认衍生部分及组合分发的许可要求，保留适用的上游版权、许可和修改声明；涉及 AGPL 覆盖的网络交互部署，还需核对对应源代码提供要求。单独列出致谢并不能替代这些义务。未确认这些条件前，不应把本仓库标为已完成开源许可审查。

## QQ Chat Exporter

感谢 [shuakami/qq-chat-exporter](https://github.com/shuakami/qq-chat-exporter) 项目及其贡献者提供 QQ 聊天记录导出工具与结构化 JSON 格式。Trivae 的 QQ 导入适配器读取该工具生成的导出文件，完成解析、规范化和入库；此处致谢不表示上游团队参与了 Trivae 的开发或提供官方背书。

上游项目声明采用 [GPL-3.0](https://github.com/shuakami/qq-chat-exporter/blob/master/LICENSE)。当前此项集成为导出文件格式对接，不将导出工具作为 Trivae 内置组件分发；用户单独使用该工具时应遵守其许可和使用说明。

## 依赖与模型

Python 依赖见 [pyproject.toml](../pyproject.toml) 和 `uv.lock`，前端依赖见 [package.json](../web/package.json) 和 `pnpm-lock.yaml`。依赖与模型各自沿用其许可证和使用条款，未被本页重新许可。默认语义索引使用 `Qwen/Qwen3-Embedding-0.6B`；下载和分发模型前应核对其模型卡。当前未使用第三方产品截图或品牌图片；产品预览取自 Trivae 对真实群聊的查询，展示技术主题和公开资源链接，不展示成员身份或完整聊天原文。
