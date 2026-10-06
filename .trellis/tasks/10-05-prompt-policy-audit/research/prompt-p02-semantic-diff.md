# P02 semantic diff

Parent：P01开发候选；唯一production baseline继续是原始SYSTEM_PROMPT。

- Removed：仅`context_before/context_after must be non-negative integers. `（60字符）。
- Moved：Base候选 → lexical/legacy既有工具description + SDK严格非负整数字段 + typed input检查。
- Reworded：无；Added：两个字段`Field(strict=True, ge=0)`与中文职责注释。
- Unchanged high-risk policy：默认窗口2、讨论20/40扩展示例、何时展开、negative、temporal、stop、retrieval顺序与全文其他字节均保留。semantic_search及get_message_context参数本轮不改。

真实SDK修改前18项红灯：bool/string/float被转换后进入registry；负值在Host已有拒绝，但Schema没有minimum。补齐后16种非法输入在SDK解析阶段显式失败、registry零调用；两adapter的0/20合法窗口保持原消息计数。单侧上界不凭空新增。

不再要求Base承担非负类型判断：Tool description仍公开同一约束，真实SDK执行严格解析，typed input继续执行本来已有的非负检查。模型仍负责选择窗口大小和讨论调查的停止时机。

累计候选20,286字符；全串相等测试证明每步只删除manifest声明的单一片段。接受L0开发候选，不发布到production，不声明真实模型行为等价。Provider=0。

新增minimum会改变可见tool contract；旧frozen artifact继续保留原合同，当前harness必须拒绝条件不匹配。不得自动重标历史schema为新schema或付费刷新baseline。后续真实筛选需显式处理一致的工具条件。
