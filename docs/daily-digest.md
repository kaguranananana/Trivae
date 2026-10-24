# 群聊邮件晚报

晚报沿用 QQ → QCE → Canonical 数据库。四个方向为工具与开源资源、技术实战与踩坑、有价值的讨论、求职与面试。按内容决定条数，先列最多五项今日精选，再列延伸阅读；每项保存讨论详情、价值、可执行建议、群名、时间和连续原文摘录。

## 生成样稿

```sh
.venv/bin/python -m trivae digest preview --date 2026-10-23
```

`--date` 使用北京时间自然日，不传时读取最近24小时。样稿保存到本机 `data/digests/preview-*/`：`report.html`、`report.md`、`report.json`、完整正文分段清单 `inventory.json` 及模型请求/响应/安全观测 `trace.jsonl`。异常写入 `error.log` 后继续抛出，不生成假空日报。样稿不发送邮件，也不推进正式日报水位。原始聊天与以上工件均不提交Git。

时间范围内的 Canonical 根消息在一个只读事务中读取，并复用正式转发树恢复内部正文；明确的直接回复父消息额外读入并标记为前情。系统通知和空正文不送模型，其他文字均按群、按实际体量分批阅读，长消息连续分段；各批提炼后再跨群综合。片段编号与连续原文摘录必须匹配，综合不得新增候选之外的引用配对。引用校验不等于语义上自动证明每句结论，仍应查看样稿。

这条路径不重新构建语义索引，也不把普通问答的一次有限检索冒充全天覆盖。分批阅读保证已选择文字实际进入模型输入，不保证所有有用主题必然被模型保留；图片/语音未做OCR或转写，未展开转发会明确披露。链接按钮只取自被引用的原文，不从模型生成的网址构造。

## 邮件配置与发送

复制 `.env.digest.example` 为本机 `.env.digest`，填写 SMTP 服务、发件地址、收件地址及授权码。模型仍读取原来的 `.env` 和登录状态；不需要另一份模型密钥。QQ邮箱使用 `smtp.qq.com:465`、SSL及邮箱授权码；授权码的获取与管理见[QQ邮箱官方帮助](https://help.mail.qq.com/detail/0/985)。不要将授权码写入聊天或Git。

```sh
# 正式生成并发送；初期读取最近24小时，之后读取上次成功邮件水位以后的变更。
.venv/bin/python -m trivae digest run --mail-env-file .env.digest

# 状态检查不创建数据库、不调用模型、不发信。
.venv/bin/python -m trivae digest status

# 检查失败原因后，显式发送已生成的同一份正文，不重新调用模型。
.venv/bin/python -m trivae digest send --run-id <日报运行编号> --mail-env-file .env.digest

# 仅在已检查模型生成失败后显式续跑；成功批次不会再次请求模型。
.venv/bin/python -m trivae digest resume --run-id <日报运行编号> --mail-env-file .env.digest

# 样稿续跑须继续使用相同日期与原目录。
.venv/bin/python -m trivae digest preview --date 2026-10-23 --resume-from data/digests/<原样稿目录>
```

邮件同时包含纯文本和HTML。日报运行及发送状态保存在同目录的 `trivae.digest.sqlite3`，与Canonical分开。只有SMTP接受邮件后才标记 `sent` 并推进水位；同一北京时间日期已经成功发送时，再次触发只返回 `already_sent`。生成与发送失败均保留原始错误；已有 `ready`、`sending`、`send_failed` 运行时，自动入口会明确停止，需检查后使用 `digest send`。SMTP接受表示服务器已接收，不等同于已经进入收件箱；进程若在SMTP接受与本地确认之间中断，应先查发件箱再决定是否显式重发。

正式增量沿用 `canonical_message_changes` 的revision、群与消息时间定位实际变化，因此迟到旧消息、转发正文补齐都可进入下一期。只在成功发信后推进，不用原消息时间截断新入库数据。独立进程锁防止人工运行和系统触发同时发送；没有自动模型重试、端口切换或渠道降级。

首份真实样稿曾在16批全部完成后遇到综合请求HTTP520，因此提供显式续跑。它逐字段比较完整输入清单及Canonical revision，再逐字比较每个阶段的原始prompt；只重用引用重新校验通过的原响应，Trace单独记录 `reused_completed_stage`，不伪造新HTTP或重复记Usage。快照或prompt变化时明确退出，不能混用旧批次。原失败日志追加保留；需要下一次生成请求时必须由操作者显式执行续跑，不在定时任务中自动循环。

## 接入晚间导入

复用现有macOS调度管理器，但日报有独立的按需LaunchAgent：

```sh
# 默认仅准备，不注册系统服务、不发送邮件。
.venv/bin/python scripts/macos/launchd_import.py install --job digest

# 配置好发件信息并核对样稿后启用独立worker；安装本身不会发信。
.venv/bin/python scripts/macos/launchd_import.py install --job digest --enable

# 原导入时间仍为10:30和22:30；晚间全部导入及索引成功后才唤起日报。
./scripts/macos/install-import.sh --digest-label com.trivae.daily-digest --enable

# 日报有自己的进程状态、标准输出及错误日志。
.venv/bin/python scripts/macos/launchd_import.py status --job digest
```

若现有导入使用自定义数据库、raw目录或label，更新导入时应继续传入这些已有参数。`--digest-label` 可选，未配置时导入行为保持原契约；北京时间22点之后的成功导入才dispatch，上午、失败、文件待稳定或索引pending都不会触发。日报没有第二个固定发送时间，也没有失败后自动反复发信的KeepAlive。导入退出码只代表导入及dispatch，邮件结果必须查看日报状态与日志，不能以导入成功代替邮件成功。

这是本机用户LaunchAgent，依赖机器运行且用户已登录。模型网络沿用现有环境；若本机已验证需要代理，可在本机 `.env.digest` 中显式配置该进程所需的 `HTTPS_PROXY`，不改全局网络，也不会在程序内自动换连接路径。
