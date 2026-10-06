# V01：单fact case首工具探测

- Case=frozen-fact@v1：当前群是否提到《深入理解 AI Agent》、谁、何时。
- Baseline=当前production原文；Candidate=P15累计候选；DeepSeek/deepseek-flash；每侧最大1 HTTP请求，总上限2。
- 两侧实际conditions完全相等；实际HTTP body除了Base Prompt均相等，动态suffix及用户输入、工具Schema、model_settings全部保持。
- Baseline：lexical_search(keyword=深入理解 AI Agent, limit=100)，同轮另选lexical_search(keyword=深入理解, limit=100)。
- Candidate：lexical_search(keyword=深入理解 AI Agent, limit=5000, context_before=2, context_after=2)。
- 各1 Provider请求、0 Host tool调用、0 retrieval、0 evidence；latency分别1286/1006ms。实验FirstToolProbeStop失败终态是预期，不作完整Query成功。
- Baseline usage因截断事件未排空缺失，保持unknown。Candidate经H05保存SDK usage：input8349/output115/total8464/cached2048。总token与API费用unknown，绝不写成0，也不从字符数/延迟推断质量或节省。

Decision=Inconclusive。确认同一精确问题的首轮lexical routing，观察到limit和同轮call数变化；没有证据送达、作者/日期或答案语义数据，不能判定好坏、semantic equivalence或release接受。没有新重复、完整Tool Loop、Judge或full gate；V01上限2已用完，后续回零成本scope。

真实artifacts保存在ignored data/evaluation/prompt-v01-20261006：原文、请求、Trace、模型选择、ledger、离线review.json。未重写历史6个frozen合同。H05修复后也没有回填或重跑Baseline。
