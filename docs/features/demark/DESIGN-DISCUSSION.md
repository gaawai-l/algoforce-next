# DeMark 设计讨论记录

日期：2026-09-26。状态：第一轮讨论，未定稿、未授权生产实现。

## 已确认的边界

依据 [会话说明](NEW-SESSION-PROMPT.md)：首期验证 Sequential；其他变体明确 unsupported；核心为纯计算；算法与策略解释分层；保留多序列和历史事件；仅使用已收盘且符合知识截止时间的数据；真实数据、模拟数据和未实现能力分别标明。

设计产物限于本目录。底座、数据库、调度、HTTP、宿主和 UI 由其他工作负责。旧实验规则不作为本专题的已确认默认值。

术语见 [CONTEXT.md](CONTEXT.md)。本记录中的建议均需讨论确认，不能因写入文件而视为接受。

## 第一轮：已有确定规则、缺口与建议

| 主题 | 已有确定规则 | 尚需决定或核验 | 推荐方向及理由（未确认） |
|---|---|---|---|
| 规范来源 | 声明 provider、variant、参数、ruleset version；不混用供应商序列 | 官方公开规则与特定供应商输出冲突时，谁定义正确性 | 官方可核实规则作为基准；公开缺口单列版本化选择；第三方输出用于差异核验，防止从页面表现猜内部算法 |
| Setup | Buy/Sell 对称；close 对四根前 close；连续九次 | price flip 精确定义、相等、中断、完成后继续计数与新 Setup 的边界 | 优先核验严格比较及标准 price flip；不沿用旧实验“不要求 flip”的默认值 |
| Perfection / Countdown | Perfection 独立；Countdown 非连续；计数与资格分离 | 延迟完善、Setup 9 当根、13 延迟、可选资格条件及同根事件顺序 | 每个条件均记录引用 bar 与确认时间；不将“未核验”和“已证明不满足”合并 |
| TDST / Risk Level | 绑定来源序列；明示突破政策；来源失效后不可显示有效 | 极值范围、并列极值、previous close、突破等号、确认政策 | 写出精确公式与独立样本后定稿；full-bar 与 close-only 属于不同规则，不能互换 |
| 多序列与 recycling | 旧有效 13、新 Countdown、反向 Setup、取消历史能够共存 | 同向新 Setup 对未完成 Countdown 的影响、recycling 与取消条件 | 区分“保留历史”和“多个未完成 Countdown 同时推进”；前者确定，后者仍需规则依据 |
| 有效期 | 可表示 expired，并保留历史资格事件 | 官方时间指标与产品过期政策的关系 | 不沿用实验版“13 后 24 根过期”；先明确计时对象和用途 |
| 历史完整性 | 修订可重算；全量与增量共用转换逻辑；无前视 | 有限输入窗口能否覆盖旧序列、缺口后如何重建 | 显式披露历史起点与连续性；固定最近 N 根不能自动保证长期 Countdown 状态完整 |
| 价格精度 | 输入价格为十进制字符串 | tick size、比较精度与元数据来源 | 精确十进制比较；不能从显示小数位猜 tick 或引入未声明 epsilon |

## 依赖顺序

1. 先确认算法的规范目标与差异裁决依据。
2. 据此核验并逐项确认 Setup、Perfection、Countdown、TDST、Risk Level、recycling 和有效期规则。
3. 规则确定后完成同根事件优先级、完整状态转换表及人工逐根样例。
4. 再定公开 Interface、配置、序列、事件、结果、错误和历史完整性语义。
5. 最后形成黄金样本、验收矩阵及最小底座接入清单；用户明确“开始实现”后进入生产实现。

## 底座事实与待协调事项

2026-09-26 读取当前工作区，底座仍在并行变化：

- `Dataset` 携带 `market_at`、`knowledge_at`、已选择的 `StoredBar` 修订和独立 `forming`；类型本身未验证整个序列的排序、重复和截止时间不变量。公开计算 Interface 需约定并验证可信输入边界。
- `Rules` / `Analysis` 当前针对 `baseline-v1`，计算内容为 SMA 与此前窗口极值，尚无正式 DeMark 输出契约。
- 当前基准计算以 `window + 1` 判断预热，不能直接用来证明 DeMark 多序列历史完整。
- `Stream` 当前限定加密现货 24/7、UTC，尚无 tick size 元数据字段。
- 不在本轮修改这些文件；接入前重新核验最新接口。

补充核验：`Repository.read` 默认读取最后 1,000 根、上限 10,000 根，当前 Runtime 使用默认值；任务 checkpoint 仅保存采集批次 ID，不含指标状态。旧快照以 JSON 保存且不覆盖，但读取依赖当前 `Analysis`，扩展模型时需要验证兼容性。相关位置：[repository.py](../../../services/analytics/src/wheelhouse_service/repository.py)、[runtime.py](../../../services/analytics/src/wheelhouse_service/runtime.py)、[market.py](../../../services/analytics/src/wheelhouse_service/market.py)。

## 官方公开资料初核

核验日期：2026-09-26。来源：[Sequential](https://demark.com/sequential-indicator/)、[Indicator List](https://demark.com/indicators-list/)。只核验这两页公开文字；它们不是完整可执行规范。

| 项目 | 已公开明确 | 尚不能据此断言 |
|---|---|---|
| Setup | 连续九根 close 严格低于或高于四根前 close | price flip 的完整起始规则 |
| Perfection | Setup 9 完成及对第 6、7 根的超越要求 | 精确的 8/9 极值比较、等号和延迟完善全部细节 |
| Countdown | Setup 后非连续计数，close 与两根前 high/low 比较 | Setup 9 当根是否参与及基础比较等号 |
| 13 vs 8 | Sell 的 13 high ≥ Countdown 8 close；Buy 的 13 low ≤ Countdown 8 close；未满足用 `+` 延迟 | 延迟后重试的全部流程与同根事件顺序 |
| 8 vs 5 | 官方称其为 elective comparison | 两页未展开精确比较公式，不能猜测补入 |
| Recycling | 提及同向重叠 Setup 延续至 22，以及后续 Setup true range 范围为前一 Setup 的 100%–200% 两类条件 | 所比较 Setup 的选择、范围端点及重置时点的完整定义 |
| Cancellation | 反向 Setup 确认，或 True High < TDST Downside / True Low > TDST Upside，可取消未完成 Countdown | 只用 raw high/low 的 full-bar 判断与 true extremes 等价，尤其存在跳空时 |
| 时间指标 | 官方称反转应在完成 13 后 12 根内发生，否则预期响应较不可能出现 | 第 12 根自动失效；旧实验 24 根有效期是官方规则 |
| 已完成 Countdown | 官方称完成后 permanent and never altered | 历史完成事实永久保留意味着当前反转论据永久有效 |
| Risk Level | 关联完成 Countdown 的风险边界，提及 qualified / disqualified Breakout Rules | 旧实验的“Setup 起至 13 极值 ± 极值 bar true range”和 close 穿越即失效是完整官方公式 |

公开说明还出现 Intersection 与 Termination Count，是否纳入目标规则及其细节需后续核验。研究稿中的“13 才是反转结论”仅记录第三方页面用语；本专题沿用会话说明的“合格衰竭／反转候选”语义，不当作已发生反转。

尚未核验第三方实现库的源码、许可、维护状态或黄金样本。本轮不作“必须自研”或“已有可直接复用库”的结论。

## 初轮待答决策（已由 2026-09-27 的方向澄清取代）

第一轮先确认：当官方可核实规则与 TradingSignal / AlphaBTC 展示结果存在差异时，产品接受什么作为算法正确性的判据？建议采用前者，并明确记录公开规则缺口和有版本的自定义选择；不承诺未经验证的供应商逐根一致性。

## 用户最新方向：先理解全站（2026-09-26）

用户明确希望把朋友 AlphaBTC Regime 的完整功能迁入自己的应用，但认为原界面难理解，要求先实地参考、科普，再讨论怎么做。当前先拓宽为全站功能与概念梳理；上述算法裁决问题暂不催答，也不据「全部抄过来」推断隐藏规则已获确认或本轮开始写生产代码。

本次实时核验与中文指南：[AlphaBTC 功能全景](../../../research/alphabtc-product-walkthrough-2026-09-26.md)。

## 当前确认方向（2026-09-27）

用户确认在自己的 Python 中独立计算，不要求与朋友或 TradingSignal 的所有结果完全一致；核心要求是 Setup 9 与 Countdown 13 算对，其余功能作为辅助分析。UI 按用户自己的要求组织。此澄清不取消此前希望接入完整数据与功能的目标，也不表示本轮授权生产实现。

9/13 的规则研究、变体声明及独立黄金样本验证由本项目负责；不再要求用户向朋友索取源码或证明逐根一致。影响计数正确性的资格条件、取消、recycling 等仍属核心验证范围，不能因称为辅助而省略。公开资料未明确的规则仍需显式记录，不声称完整复制专有算法。

朋友可协助解释辅助算法及数据来源。本轮形成可转发的[辅助算法与数据问题清单](AUXILIARY-QUESTIONS.md)，回答后逐项记录，尚无答案的地方不自行升级为默认实现。

## 最新执行方式（2026-09-27）

用户纠正：经典 DeMark 与朋友新增的市场阶段/单边突破策略要分清；代理先自行试用、查证、反推，不再让用户代问长清单。已将原问题清单标为历史问题池。

用户随后调用 ask-matt，要求先制定计划，审阅后再开工。已读取当前 A0–A5 底座及 INTEGRATION-PROMPT，并形成 [INTEGRATION-PLAN.md](INTEGRATION-PLAN.md)。其中将 `phase` 暂解释为市场阶段识别，推荐先做六态成本分类的完整切片；这是待审方案，不是假定全部算法已定稿。生产实现仍未开始。

## 基础版实施授权与结果（2026-09-27）

用户当前持续目标为「完成基础版 DeMark 到当前项目」，已作为本轮实施授权。完成命名Sequential规则、独立Python模块、正式计算/任务/快照/HTTP与TD tab接入，以及测试和浏览器验收。范围和证据见 [BASIC-SEQUENTIAL.md](BASIC-SEQUENTIAL.md)、[RESULTS.md](RESULTS.md)。Phase及朋友策略层继续保留后续计划，不混入本轮计数结果。

## 最新第一验收目标：AlphaBTC 数据对齐（2026-09-27）

用户再次明确：目标是搭好框架，让DeMark独立计算并展示；第一目标是算出的数据与AlphaBTC一致。这取代此前“不要求平台读数一致”的验收优先级。基础版链路已完成，但AlphaBTC一致性尚未验收，已有手算测试不能证明供应商一致性。

先比较原始DeMark字段：Buy/Sell Setup、Countdown、9/13出现的bar、资格、TDST、Risk Level、生命周期与下根条件；朋友自定义Regime、评分、Phase另列，不因原始计数通过而宣称策略层相同。

对齐顺序：固定同一交易场所/交易对/周期/收盘截止与历史窗口 → 捕获AlphaBTC及其TradingSignal上游对应结果与时间 → 用本地Python回放同一OHLC → 输出逐字段和逐bar差异 → 将真实差异做成回归样本。若行情、缓存时间或历史起点不同，先修输入，不能改算法凑当前数字。

当前未发现阻断框架运行的依赖；尚缺成套同输入对照证据，部分recycling/Risk规则可能与供应商不同。由代理先自行核验，只在具体差异无法解释时向用户提出最小问题。此次运行检查：服务ready、Binance BTCUSDT 1h快照344根、DeMark ready；这只证明链路正在运行，不证明与AlphaBTC一致。
