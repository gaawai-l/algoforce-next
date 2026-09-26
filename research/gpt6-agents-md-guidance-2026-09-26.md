# GPT-6 与 AGENTS.md：起草依据

核验日期：2026-09-26。以下页面已实际读取正文；不是仅凭搜索摘要。这里记录写法依据，项目约束以根目录 `AGENTS.md` 为准。

## 官方一手来源

1. [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)，2026-09-11，Eric Provencher。
   - GPT-6 Astra 下应重新检查 skills、AGENTS.md 和任务提示，减少过时或多余的约束。
   - 文档按任务需要读取；不要规定每次修改前通读架构、数据库、部署文档。
   - 渐进披露：根文档提供清晰的触发条件和链接，把具体工作流放在对应文档。
   - 审视过强的审批措辞，明确允许自主完成的范围。
   - 定义完成条件，避免模型做到第一版就停下；但如果任务本身要求设计确认，交付可评审原型就是合理边界。

2. [Using GPT-6 / Model guidance](https://developers.openai.com/api/docs/guides/latest-model)，查询时页面列出 GPT-6 Astra、Sol、Luna。
   - Prompting best practices 建议明确主动执行、用户指令与技能优先级、写作风格、按改动规模验证。
   - 对可逆的小改动避免机械追加测试；所需检查完成后，只有新改动、失败或未解决问题才扩大检查。
   - 多 agent 指导是可按 harness/workflow 调整的选项，不是 AGENTS.md 必须强制并行的要求。本项目没有因此新增默认委派规则。
   - 根目录说明不负责设置模型参数；本次没有迁移 API、修改模型或修改全局 Codex 配置。

3. [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。原官方入口 `https://developers.openai.com/codex/guides/agents-md` 当前转到此页面。
   - Codex 在运行开始时构建指令链，支持全局与项目目录分层。
   - 每层优先 `AGENTS.override.md`，其次 `AGENTS.md`，再按配置的备用文件名查找；每目录最多选一个文件。
   - 默认合并文档预算为 32 KiB。这是发现机制的限制，不是建议把根文件写满。
   - 未找到项目根目录时，仅检查当前目录。本工作区尚未初始化 Git，因此应从工作区根目录启动；本次没有为文档任务擅自初始化仓库。
   - 验证加载可在新 Codex 会话要求列出有效指令来源。本轮只检查文件本身，不声称已经在独立会话完成自动加载验证。

## 这份草稿的设计

- 使用标准大小写 `AGENTS.md`，放在 `/Users/gary/code/AlgoForceNext/`。
- 采用英文编写给 agent 的指令；保留中文用户沟通和英文产品 UI 的明确区分。
- 记录真实项目背景：个人使用、moomoo 新加坡账户、只读、股票和期权、Wheel、组合 Greeks、Market 三方法评估。
- 把已确认的 UI 决策写成稳定约束：一个共享左侧栏、市场方法 tab、大图加当前分析详情、英文赛博朋克；明确旧的并排卡片方案已被否定。
- 仅把 Wealthfolio 写为首选复用候选，没有宣称它已经集成，也没有锁定 fork/addon/独立应用或前后端技术栈。
- 明确真实查询与交易执行的边界，同时允许自主完成已授权的本地修改、只读调研和相关验证。
- 对资金、期权和 Greeks 的关键不变量直接说明；具体候选能力、OpenD 接入研究和原型说明按任务链接读取。
- 沿用用户不删除文件的个人规则，不采用官方示例中的删除操作；官方示例仅是格式示例，并不覆盖用户授权和偏好。

## 草稿状态

这是基于现有对话和研究起草的项目工作约定，尚非生产架构设计。当前没有真实券商连接、正式数据库、生产测试任务或已部署服务。正式实现后，应更新状态与启动/验证入口，避免把原型事实长期当作生产事实。
