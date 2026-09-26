我们正在开发 Wheelhouse，一个基于 Wealthfolio 的个人只读投资分析工作台。DeMark 是重点功能，请与我专门讨论并确定 DeMark 计算模块的算法、接口和验证方案。

**本会话先做设计讨论。先阅读现状、指出规则缺口、提出推荐方案，再和我逐项定稿；我明确说“开始实现”后再写生产代码。不要把名称相同的第三方 TD 指标函数直接当作完整实现。**

项目根目录：`/Users/gary/code/AlgoForceNext`。遵循这里的 `AGENTS.md`。与我讨论及设计/验收文档用中文；代码、注释和产品 UI 用英文。保留现有文件，不执行删除操作。

一、先读这些材料

1. 功能规格：`/Users/gary/code/AlgoForceNext/prototypes/wheel-dashboard/MARKET-STRATEGY-SPEC.md`，重点第 5–8、9.3、12、14–15、17 节。
2. 架构：`/Users/gary/code/AlgoForceNext/docs/architecture/wealthfolio-python.md`。
3. 正在建设的架构验收：`/Users/gary/code/AlgoForceNext/docs/architecture/a2-a5-acceptance.md`。
4. 金融规则：`/Users/gary/code/AlgoForceNext/docs/financial-domain.md`。
5. 参考研究：`/Users/gary/code/AlgoForceNext/research/demark-completed-model-study-2026-09-26.md`。
6. 早期实验说明：`/Users/gary/code/AlgoForceNext/docs/implementation/market-engine.md`。其中参数只是未经完整验证的实验选择，不能视为我已认可的最终 DeMark 规则。

A2–A5 架构底座已完成，最终范围与证据见 `docs/architecture/a2-a5-results.md`。讨论前按实际文件确认 Python 接口，不沿用早期实验接口。设计产物请放在 `docs/features/demark/`。设计讨论阶段不要修改底座、数据库迁移、任务调度、HTTP 契约、宿主补丁或 UI，避免并行冲突。现有根目录 `backend/`、`frontend/` 是历史实验，正式功能不要继续写在那里。

二、DeMark 逻辑放在哪里

正式 Python 包位于：
`/Users/gary/code/AlgoForceNext/services/analytics/src/wheelhouse_service/`

建议新增独立计算模块：
`services/analytics/src/wheelhouse_service/indicators/demark/`

模块可以包含模型、配置和状态机；按实际复杂度拆文件。核心计算保持纯逻辑：不访问网络、数据库、FastAPI、系统当前时间、Wealthfolio 或 moomoo。UI 只展示 Python 结果，不再实现第二套 DeMark 算法。

目前的数据与运行模块是：

- `market.py`：`Stream`、`Bar`、`StoredBar`、`Dataset`、规则与分析契约。
- `repository.py`：批次、K 线修订、按知识截止时间读取、快照、任务和 checkpoint。
- `calculation.py`：实时与回放共用的确定性计算入口，目前只有 baseline SMA/滚动区间验证计算。
- `runtime.py`：任务编排、采集、重试、恢复和持久化。
- `sources.py`：行情 Adapter。
- `http.py`：HTTP Adapter。

推荐的外部计算 Interface 形式：

```python
def evaluate_demark(dataset: Dataset, config: DemarkConfig) -> DemarkResult:
    ...
```

这是设计建议，不是要求现在改动底座。请讨论该 Interface 的输入不变量、输出、错误、预热、复杂度和重算规则。内部可使用逐根 `advance` 状态机；全量回放和后续增量更新必须复用相同状态转换，不能维护两套算法。

接入时，由统一计算入口调用 DeMark 模块，任务层仍负责数据与存储。需要扩展规则注册、分析契约或快照结构时，先列出最小接入改动，与架构会话协调后再实施。不要让 DeMark 计算模块直接写任务状态或保存快照。

三、必须覆盖的计算能力

1. **版本与变体**：首期完整验证 Sequential。保留 Combo / Combo relaxed / both 的扩展语义；未实现明确 unsupported。声明 provider、计算变体、参数与 ruleset version，不能混合不同供应商的序列。
2. **Setup**：Buy/Sell 独立；连续 1–9；close 与四根前 close 的比较；明确 price flip、相等价格、中断、反向 Setup 和同向新 Setup 的处理。Setup 9 是趋势持续/可能疲劳的警告，不是已确认反转。
3. **Perfection**：第 6/7/8/9 根的具体极值条件、延迟完善、完善时间及 unknown。不能从图上一个 9 推断 perfected。
4. **Countdown**：非连续计数 1–13；明确开始时机、是否包含 Setup 第 9 根、逐根资格、延迟 13、取消与 recycling。计数值与生命周期分离。
5. **Qualified 13**：保留 Countdown 第 8 根引用、close、13 的比较阈值和资格时间；明确 unqualified / unverified / qualified，缺少证据不能标合格。
6. **TDST**：准确生成规则和 source sequence；true high/low 与 previous close 的含义；full-bar、close-only 等失效策略必须显式命名和验证。
7. **Risk Level**：生成算法、来源范围、极值选择/并列极值、true range、突破政策；qualified13 失效、过期或被替代后，Risk Level 不得继续表示有效。
8. **多序列与生命周期**：一个周期可同时有旧的有效 13、新的同向 Countdown、反向 Setup 和已取消历史。不要用一个可变 td_count 代替整个状态。输出形成、激活、未合格、合格、取消、失效、过期事件。
9. **时间与溯源**：只用已收盘且由底座选择的版本；记录 bar references、确认价格与时间、距 Setup9/13 的 bars 和 elapsed time、下根满足条件、历史合格 13 次数。
10. **数据修订与增量**：缺口、乱序、重复输入、预热不足如何处理；历史 K 线修订后从何处重算，旧快照如何保留；增量运行与从头回放应等价。

四、算法与策略解释分层

DeMark 模块先输出原始结构和生命周期。Watch / Warning / Armed / Candidate、BUY_1/2 和 SELL_1/2、strength score、跨周期调整属于独立解释/策略层，不能混入原始计数算法。

多周期按战略/主方向/setup/confirmation/execution 角色解释，不按多数票决定方向。Buy Setup 表示观察到下行持续、可能出现向上反转；不能直接标成已建立上涨趋势。分数不是概率。Qualified13 不能自动推翻已确认突破，Setup9 不能单独覆盖高周期趋势。

本模块只读分析，不实现下单、改单、撤单、交易解锁、自动执行或账户凭据获取。

五、验证要求

请优先核验官方 DeMARK 资料及可合法使用的可靠参考实现，注明验证日期。区分官方明确规则、供应商特定变体和 Wheelhouse 自定义选择；公开资料不完整时明确不确定点，不能假装完整复现专有算法。

优先复用经源码和样本验证的实现，但先检查许可、维护状态、实际支持范围；“函数叫 TD Sequential”不能证明支持 Countdown、TDST、Risk Level 和多序列。若自己实现，请说明原因和一致性验证办法。

测试针对公开计算 Interface，使用人工逐根推导或可靠外部来源的黄金样本，期望值不能通过被测算法反算。至少覆盖：Buy/Sell 对称性、price flip、相等、中断、perfection/延迟完善、稀疏 Countdown、合格与延迟 13、TDST 各失效策略、Risk Level、反向取消、同向 recycling/并存、过期、缺口、重复与修订、同一输入确定性、逐根/批量等价、历史无前视、多序列保留。

当前协议首期使用加密现货 24/7；股票交易时段与复权不可静默沿用这个假设。明确价格与 tick 比较精度。

六、先给我的设计产物

先给出“已有确定规则 / 尚需决定的规则 / 推荐默认值与理由”对照表，优先提出影响算法正确性的分歧。然后形成：

- 完整状态转换表，以及至少一组人工逐根演算示例。
- `DemarkConfig`、序列/事件/结果模型和公开 Interface。
- 与当前数据/计算/任务/快照底座的接入清单。
- 黄金样本和验收矩阵。
- 实现阶段建议：规则定稿 → 独立模块 → 接入底座 → UI 显示。

请先讨论设计，不要一上来扩写整个应用，也不要把旧实验参数直接升级为正式规则。
