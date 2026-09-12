# GPT-6 Astra 科普：来源与评分口径

资料核查日期：2026-09-06。视频是公开评测解读，不是本次 API 实测。不包含厂商赞助或付费实测结果。

## 来源

- S1：https://openai.com/index/gpt-6-astra/ 。官网首页可见 GPT-6 Astra 发布入口及 2026-09-03 日期；全文未稳定取得。不得把本文未读到的规格称为官方确认。
- S2：https://artificialanalysis.ai/models/gpt-6-astra 。max、Intelligence Index v4.2：55；输入/输出每百万 token $10/$50；64.3 token/s；页面延迟 384.30s；约 1M 上下文；文字和图片输入、文字输出。
- S3：https://artificialanalysis.ai/models/gpt-6-astra-high 。high、v4.2：53；60.8 token/s；页面延迟 96.05s；价格同 S2。
- S4：https://artificialanalysis.ai/models/gpt-6-astra-non-reasoning 。non-reasoning、v4.2：48。速度 N/A，TTFT 未报告，不能补造。
- S5：https://artificialanalysis.ai/articles/benchmarking-gpt-6-astra 。2026-09-03 发布日评测采用 v4.1.1：Astra 和 Sol 综合均 61。Coding Agent Index：Astra + Codex 67；文章列出的领先组合 Fable 5.1 + Claude Code 70。Astra max 在 Codex 内 token 消耗约 Sol max 的三分之一，同等支出附近提高约 2 点；不能将代理系统结果解读为裸模型隔离实验。输入/输出标价由 Sol $4/$20 变为 Astra $10/$50。
- S6：https://artificialanalysis.ai/methodology/intelligence-benchmarking 。当前 v4.2 十项评测：代理 30%、编程 20%、广泛能力 30%、高阶科学 20%。主要为英文任务。不能将综合指数解释为正确率或 IQ。

## 重要限制

1. 61 和 55 来自不同指数版本，不作能力退化比较。
2. 页面 FAQ 称 TTFT，而正文有首个答案 token 的表述，两者可能不一致。视频仅标为“页面所报延迟”，说明歧义，不把它视为所有请求的服务承诺。
3. 官方首页和第三方型号交叉一致；具体价格、模态、上下文仅归因于第三方页面，API 官方文档未读取成功。
4. LMArena 页面连接超时，没有引入它的名次或成绩。证据主要来自一家独立评测机构，不构成多家共识。
5. 不虚构中文、语音、稳定性等十分制评分。不把未测任务包装成实测演示。
6. 成本算例：100000 / 1000000 × 10 + 10000 / 1000000 × 50 = $1.50。无缓存，输出为全部计费输出（含适用推理 token），不含工具及其他费用，不是 ChatGPT 订阅价。
7. 最后的选型建议是编辑判断。片中的十任务对照是建议方法，不是已经实施的测评。

## 展示方式

每章以 source_ids 显示来源编号。全部实际文案和图表数据保存在 content.json。字幕与配音段落来自同一文案；字幕为按文本长度估时，并非词级强制对齐。
