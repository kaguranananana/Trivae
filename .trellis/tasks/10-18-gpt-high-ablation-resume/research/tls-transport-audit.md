# TLS 调用路径只读审计（2026-10-19）

本次只读审计生产代码、已保留的失败诊断、本机公开路由与进程状态；没有发起网络探测、OAuth 读取或真实 Provider 请求，没有修改生产代码、系统网络、候选 Prompt、索引或预算。真实网络差分由主 Agent 单独执行。

## 已确认的调用边界

- `chatgpt_responses.py` 与 `chatgpt.py` 都直接导入 `httpx==0.28.1`，实际使用 `httpcore==1.0.9`；实际解释器为 Python 3.12。`httpx2==2.12.0` 是另一个包，`httpx.AsyncClient is httpx2.AsyncClient` 实测为 false，没有项目级 `sys.modules` 替换。已安装 OpenAI SDK 内部使用 httpx2，但 ChatGPT 订阅推理走自有 SDK Model，不走该内部 client；更换 OpenAI SDK 版本无法直接改变本次 TLS 实现。
- `ChatGPTAuthManager` 自建 `httpx.AsyncClient(timeout=30.0, follow_redirects=False)`；模型目录 GET 和必要的认证请求共用该 client。`ChatGPTResponsesModel` 自建另一个 `httpx.AsyncClient(timeout=60.0)`，POST `https://api.openai.com/v1/responses` 使用此独立 client。账号目录验证成功，只能证明 Auth 那条连接成功，不能证明 Responses 另建的 TLS 连接成功。
- 两者没有配置 SSL 降级、手动 cipher、自动重试、HTTP/2、连接上限或显式 transport/proxy。httpx 默认是 `verify=True`、`trust_env=True`、HTTP/1.1、100 最大连接、20 keepalive、5 秒 keepalive 过期，transport 的连接重试默认为零。Router、Planner 与 Runtime 收集同一 Responses Model 的 SSE，未另建推理传输。
- Client 在创建时建立代理 mount；httpx 的 `get_environment_proxies()` 调用 `urllib.request.getproxies()`，该函数在 macOS 会读系统代理，清空 `HTTP_PROXY/HTTPS_PROXY` 并不能证明直连。`NO_PROXY=*` 或 `trust_env=False` 可以跳过 HTTP 代理，但不能绕过系统 TUN。
- SSL 默认使用 certifi CA；只有 `trust_env=True` 且显式存在 `SSL_CERT_FILE/SSL_CERT_DIR` 时采用相应配置。不能为 EOF 或空 ConnectError 而关闭证书验证，也不能在没有证书验证错误证据时猜测 CA 根因。

## 流和连接生命周期

- `_stream()` 用 `async with client.stream(...)` 包裹整个 HTTP 流；收到已验证 `response.completed` 后发布 Usage 等事实、yield 并 return。异常、终态失败和取消都会退出 HTTP 上下文。
- `stream_response()` 额外使用 `aclosing(self._stream(...))`，SDK 在中间 delta 后关闭生成器也会显式关闭内部流。`collect_response()` 消费同一生成器，普通 Completion 不使用另一套流协议。
- 如果 Provider 在 completed SSE 后尚未传完 HTTP chunked body，提前关闭会使 httpcore 正常关闭这条 HTTP/1.1 连接，下一轮新建连接。`http11._response_closed()` 只有请求/响应 h11 状态均 DONE 才放回 IDLE，否则直接 `aclose()`。这会增加下一轮握手机会，但不是把不完整连接错误放回池的证据，也不能为减少握手而无限等待 SSE 后缀或削弱终态检查。
- `scripts/run_prompt_screening.py` 在 finally 保存 ledger 并 `await application.aclose()`；Application 依次关闭 Runtime、Model 的推理与认证 client。真实多轮使用同一 event loop，未发现跨 `asyncio.run()` 复用 client 的代码路径。
- HTTP budget hook 只添加到 Responses client，位于发送前，失败握手也占用次数；目录和认证不被当作模型请求。原 52/120 计数不能因网络失败回退。

## 空 ConnectError 的诊断限制

保留的失败 traceback 分别出现 `http_proxy.py.start_tls`（HTTP CONNECT 后握手）和 `connection.py.start_tls`（连接池直接握手）。失败都发生在 HTTP 响应头前，尚未进入 SSE Parser，不能归因为 metadata、工具 schema 或 Prompt。

httpcore AnyIO backend 会将 `EndOfStream`、`BrokenResourceError`、`ssl.SSLError` 映射为 ConnectError。已安装 AnyIO TLS 实现对握手时 `SSLEOFError/UNEXPECTED_EOF_WHILE_READING`，在 `standard_compatible=False` 时执行 `raise EndOfStream from None`；该异常的字符串为空。旧 ignored 诊断只遍历 `__cause__`，因此可能只留下两个空 ConnectError。此处是源码支持的机制解释，不是已捕获某次失败的底层 EOF 结论。新无凭据诊断宜同时记录 `__context__` 类型与脱敏消息、httpcore trace 中的连接阶段，不应改业务错误分类来假装已定位。

## 本机公开网络状态

- 系统 HTTP/HTTPS/SOCKS 代理均启用，地址 `127.0.0.1:7892`。
- 当前 7892 监听者为 `yeshayunCore`，对应“夜煞云”应用；机器上同时存在 Clash Verge service，但它不是该端口的当前监听者。旧 Clash 磁盘配置的 mixed-port 为 7897，不能把它当作当前活跃代理配置。
- 主 Agent 实测 `api.openai.com` 返回 `198.18.0.30` 与 `fdfe:dcba:9876::1d`。本次 `route -n get` 证实这两个地址均走 `utun4`，网关分别为 `198.18.0.1` 与 `fdfe:dcba:9876::1`。所以即便连接池是 `AsyncConnectionPool`，DNS/路由仍可能经过本机 fake-IP/TUN；过去“direct”只能解释为绕开 HTTP CONNECT，不能解释为绕过所有本机代理。
- 没有读取或输出订阅节点密钥、完整代理配置、用户连接清单或 OAuth 凭据；没有切换节点、关闭 TUN 或改 DNS。仅凭当前路由不能证明具体上游节点故障。

## 可检验的最小假设与决策边界

1. **当前间歇路由/上游连接问题**：固定同域、SNI、SSL 校验、HTTP/1.1，重复无凭据 GET 并记录每次新建连接、IPv4/IPv6、HTTP 代理与 TUN 路由身份。若相同 client 在业务外也失败，可排除 SDK/SSE/Prompt；若当前连续成功，表述应为当前未复现，不能追认之前根因已修复。
2. **独立 client 或早关流增加握手机会**：在无凭据请求里重放“目录 GET → 第二 client 请求 → 早关 response → 再请求”，比较新建连接与复用连接，不启用隐藏重试。若差分稳定出现才考虑最小生命周期修复；目前代码没有不完整连接回池或取消泄漏证据。
3. **IPv6 fake-IP 与 IPv4 路径差异**：保持域名/SNI/证书校验不变，只在独立诊断中固定连接地址族；必须观察失败与路由关联才能决定配置，不在生产添加自动 IPv4 fallback。
4. **TLS ClientHello/实现差异**：若 curl 与 Python 在同一节点、地址族及新建连接条件下稳定分离，再比较 SSL/OpenSSL 和 httpx/httpx2；目前不能用更换 SDK 或 transport 当作已证明的修复。

在没有稳定差分或明确外部变化证据前，不建议生产加重试、共享认证 client、加长超时、切换 HTTP/2、降低 TLS 校验或吞掉 ConnectError。网络恢复后，应先做一条受原预算门禁控制的真实 High 完整多轮，再继续原配对实验，保留全部失败记录。

## 本次校验

- 本地 import/构造签名/SSL/代理解析/AnyIO/httpcore 源码检查完成，无外部网络。
- `uv run --all-extras pytest -q tests/test_chatgpt_responses.py -k 'cancel_closes or read_timeout or real_sdk_two_turn or stream_closes'`：**2 passed，37 deselected，0.91 秒**；选中的两个测试分别覆盖取消关闭与超时错误可见性，没有声称覆盖真实网络。
- 文件变化仅本研究记录；未修改生产和测试文件。真实 TLS 根因与恢复验收仍待主 Agent 当前差分探测及真实请求事实。

## 后续差分反证与撤销（同日）

主 Agent 随后捕获到同域无凭据 IPv6 连接的 `ConnectError → EndOfStream → SSLEOFError`，并曾观察 IPv4 连续 60 次通过。基于该阶段证据，子任务在脚本里试作显式 IPv4、原有公开 client 注入、双连接生命周期与冻结条件的选择，并先完成五个红测试、再通过 27 个定向测试及 420 个 static 回归。但后续 100 次新 TLS 对照出现 IPv4 仅 20 次成功、IPv6 仅 30 次成功，**地址族稳定性假设被反证**。

收到反证后，已立即撤销本子任务全部尚未提交的 `scripts/run_prompt_screening.py` 修改及新增 `test_prompt_screening_network.py`，原脚本恢复 HEAD 内容，没有保留 IPv4 参数、重试或降级；没有模型请求、提交或预算变化。上述测试只证明试作工程合同，不构成网络修复，也不作为保留试作的理由。

继续只读检查共同核心路径：

- 当前核心公开 TCP 监听为 `127.0.0.1:7892` 和 `127.0.0.1:7874`；后者常用于本机 DNS，但本次没有对端口服务身份额外猜测或改配置。
- macOS unified log 近 20 分钟针对 `yeshayunCore/yeshayun` 的 TLS、handshake、EOF 过滤返回 **0 条**；用户态应用数据目录未发现日志文件，`lsof` 也未给出可读日志路径。
- 存在本机 `yeshayunSocket` Unix socket，单次无凭据 `GET /version`（3 秒超时）返回 ReadTimeout，不能将它认定为可用 HTTP 控制器。没有尝试授权、配置接口或端口控制。
- 只检查了应用 SQLite 的表结构，其表用于 profile、规则和 proxy group；未查询订阅 URL、节点值或凭据。

当前没有可读取的核心错误日志，能够把客户端证实的 TLS EOF 进一步归因到具体远端、节点或规则。IPv4/IPv6 都失败仍与共同 TUN/上游路径相容，但不是已证明某个节点故障的证据；保留该不确定性。

## 已实施的传输错误可观测性修复

真实探测已经确认 AnyIO 隐藏的 SSLEOF 上下文，因此仅在 `chatgpt_responses.py` 捕获 `httpx.TransportError` 时，新增 `transport_exception_chain` 安全观测：依次记录异常类型及经现有 `auth.redact()` 脱敏、最多 500 字的消息；优先显式 `__cause__`，没有 cause 时读取 `__context__`，包括 `from None` 隐藏的真实 EOF。没有复制 Request、header、body、traceback 或隐藏推理。非 TransportError 不新增上下文记录。

此改动**仅修复根因不可见**，不解决外部 TLS EOF，也不修改 Provider 请求、TLS 校验、连接配置、自动重试、SSE 终态或 `PROVIDER_ERROR/REQUEST_TIMEOUT` 分类。此前和主 Agent 已启动的实验进程不因磁盘修改自动获得新行为；版本与真实观测应按实际运行记录报告。

测试先红：真实同形的 `httpx.ConnectError → httpcore.ConnectError → anyio.EndOfStream（suppress_context）→ ssl.SSLEOFError` 与 timeout 两项均因缺失诊断字段失败。修复后 `test_chatgpt_responses.py` 和 `test_prompt_screening.py` 共 **62 passed（1.60 秒）**；Ruff 通过，mypy **128 个源文件通过**。测试同时确认 EOF 可见且 secret 脱敏、无 header 投影、observer 获得相同诊断、timeout 分类不变、非传输错误不展开上下文、实际 HTTP 发送与原总账本仍为一次，下一请求在发送前预算拒绝。未用真实推理复测，也未提交代码，由主 Agent 统一处理后续验收与提交。
