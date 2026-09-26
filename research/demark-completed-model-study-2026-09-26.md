# DeMark 已实现模型专题研究

研究日期：2026-09-26  
研究范围：AlphaBTC Regime 的 Demark Regime 模块，以及其上游 TradingSignal TD 序列详情。  
原则：只记录页面已经实现、能够看到数据或明确规则的部分；不纳入待接数据、占位主题和未完成事件模型。

> 页面数据会实时变化。本文重点是模型结构与字段含义，具体价格和计数仅是 2026-09-26 盘点快照。

## 1. 先分清三个层次

AlphaBTC 页面把三个不同概念串成了一条决策链：

1. **TD Sequential / DeMark 原始信号层**：计算 Setup 1–9、Countdown 1–13、TDST、Risk Level 和信号生命周期。
2. **多周期解释层**：同时读取 5m、15m、1h、4h、1D，判断哪些周期正在形成趋势、趋势已确立或已经衰竭。
3. **Regime 校准层**：用日内 1h 状态校准 5m/15m/1h，用跨天 4h 状态校准 4h/1D 的信号置信度。

链上 BTC Cycle Index 是另一套成本基础模型，只提供宏观市场环境，不参与 TD 9/13 的计数。

## 2. DeMark 状态机

### 2.1 Setup 1–8：趋势形成中

- 价格连续朝一个方向推进，但尚未得到趋势确立结论。
- 页面同时维护买方 Setup 和卖方 Setup。
- 页面说明中的方向口径：买方 Setup 对应一段下跌；卖方 Setup 对应一段上涨。
- Dashboard 应显示方向、当前计数、下一根计数条件和最后一次推进时间。

### 2.2 Setup 9：趋势确立

- Setup 连续数满 9 根，页面将这段推进标为“趋势确立”。
- Setup 9 同时意味着趋势已经推进了一段距离，因此是疲劳提醒，不是追涨或追跌指令。
- TDST 由这一段 Setup 定义，是下一阶段判断趋势延续或计数取消的关键边界。

页面对 9 的一句话定义：**9 是提醒，不是最终反转结论。**

### 2.3 Setup 9 后的两条路径

页面采用的 DeMark 原版失效判断是“整根 K 线越过 TDST”，不是只有收盘价穿过：

1. 整根 K 线越过 TDST：当前计数被取消，之前更大的趋势继续。
2. 没有越过 TDST：Countdown 继续推进，目标为 13。

因此，`TDST` 不是普通支撑阻力线，而是 Setup 9 后的趋势验证和 Countdown 生命周期边界。

### 2.4 Countdown 1–12：等待衰竭

- 趋势方向在显示上仍保持原方向。
- Countdown 表示距离趋势衰竭还有多远，不代表新的趋势方向。
- Countdown 不要求像 Setup 一样每根连续计数，所以时间跨度可能明显更长。
- 页面会同时保留多轮、双方向的 Countdown；一轮可能是 active，另一轮可能是 cancelled 或 qualified13。

### 2.5 Countdown 13：趋势衰竭

- 页面把 13 定义为 DeMark 体系中最强的趋势结束信号。
- 上涨 Countdown 13：上涨衰竭，产生逆向偏空观察或 SELL 信号。
- 下跌 Countdown 13：下跌衰竭，产生逆向偏多观察或 BUY 信号。
- 13 可以成为逆向交易入场依据，但是否仍然有效必须继续观察 Risk Level。

页面对 13 的一句话定义：**13 才是反转结论。**

### 2.6 第 8 根收盘门槛

Sequential 模式的第 13 根还需要越过 Countdown 第 8 根的收盘价门槛。

- 页面在日线明细中明确显示 `第 8 根收盘（13 的门槛）`。
- 因此 `countdown_count = 13` 和 `qualified13` 应当是两个不同字段。
- Dashboard 不应只保存数字 13，还必须保存其是否满足资格条件。

### 2.7 Risk Level

- Risk Level 是 qualified 13 反转交易的失效线和止损参考。
- 页面口径是收盘越过 Risk Level 后，当前反转论据失效。
- Risk Level 只对仍然有效的 13 有意义；上一个 13 失效后，页面显示 `—（上一个 13 已失效）`。
- 页面 AI 解读把“13 出现 + Risk Level 未破”作为共振反转仍有效的核心依据。

### 2.8 信号生命周期

TradingSignal 已实现至少三种状态：

- `active`：当前 Countdown 仍在推进。
- `cancelled`：计数因规则失效或被新的结构替代。
- `qualified13`：Countdown 已完成且满足 13 的资格条件。

这比只显示 0–13 更重要。自有 dashboard 应把计数和生命周期分开存储。

## 3. Sequential 与 Combo

页面内置说明提供四个算法模式：

### Sequential

- 常规行情默认模式。
- Setup 满 9 后才开始 Countdown。
- 第 13 根还必须越过第 8 根收盘门槛。
- 最快约 22 根 K 线形成结论。
- 过滤条件较多，假信号相对较少，但确认更慢。

### Combo

- 从 Setup 第 1 根开始并行计数。
- 每一根需要同时满足四个条件。
- 最短 13 根形成结论。
- 更适合推进干净的单边趋势，震荡行情可能长期数不完。

### Combo 宽松

- 第 11 根起只要求收盘继续创新低或新高。
- 急涨急跌时更容易完成计数。
- 代价是信号更多，失败概率也更高。

### 两者

- 同时绘制 Sequential 与 Combo。
- 页面建议用两套算法互相印证；两边同时到 13 属于更强信号。
- 切换模式会改变图上计数，同一段行情的两个 13 不一定对应同一根 K 线。

当前 AlphaBTC 从 TradingSignal 拉取的 URL 参数是 `opts=td:sequential`，即使用 Sequential。

## 4. TradingSignal 已实现的字段

每个周期详情已经暴露以下字段：

- 当前阶段：趋势形成中 / 趋势确立 / 上涨衰竭 / 下跌衰竭。
- 当前方向：上升或下降。
- 当前 Setup 计数。
- 买方 Setup、卖方 Setup。
- 买方 Countdown、卖方 Countdown。
- 每条 Countdown 的生命周期状态。
- 下一根 K 线继续计数所需的收盘条件。
- 第 8 根收盘门槛。
- TDST。
- Risk Level。
- Risk Level 与现价距离。
- TDST 与现价距离。
- 距上次 Setup 9 的 K 线数量。
- 距上次 qualified 13 的 K 线数量。
- 历史 qualified 13 次数。
- 信号出现时间。
- 信号确认 K 线收盘价。
- AI 多周期解释和人工专家解读。

## 5. 多周期共振如何工作

页面不是把五个周期简单投票，而是允许同一时刻存在互相矛盾的信号：

- 大周期用于定义主要方向和行情是否已经充分衰竭。
- 小周期用于确定更精确的转向时点。
- 一个周期可以同时存在一轮已完成的 13，以及一轮新形成中的反方向 Setup。
- “小周期先转向、大周期尚未走完”是页面明确接受的正常状态。

盘点快照的结构：

| 周期 | 已完成/有效结构 | 新结构 | 页面解释 |
|---|---|---|---|
| 5m | 上涨已确立，Countdown 2/13 | - | 新一轮短周期上涨尚早 |
| 15m | 上涨 qualified 13 | 新上涨 Setup 4/9 | 小级别上涨衰竭，Risk Level 决定反转是否继续有效 |
| 1h | 下跌 qualified 13 | 新上涨 Setup 1/9 | 下跌衰竭偏多，新的上涨尚在起步 |
| 4h | 旧上涨 qualified 13，且曾 9+13 同时出现 | 新上涨 Countdown 2/13；另有 Setup 1/9 | 中周期上涨衰竭仍偏空，但新结构正在形成 |
| 1D | 上涨 Countdown 9/13 | 新下跌 Setup 2/9 | 大周期上涨尚未完成衰竭，仍限制过早做空 |

这说明最终判断不能使用“取最新一行”这种简化方法，必须保留同周期的多轮结构。

## 6. 逐周期明细快照

### 5m

- 当前阶段：上升趋势确立，Countdown 2/13。
- 下一根条件：收盘高于约 84,071.8。
- TDST：约 83,896.2。
- 上一个 13 已失效，因此当前无有效 Risk Level。
- 买方 Countdown：13/13，`qualified13`。
- 卖方 Countdown：2/13，`active`。
- 历史 qualified 13：4 次。

### 15m

- 当前阶段：新一轮上升趋势形成中，Setup 4/9。
- 同时保留上一轮上涨 Countdown 13/13，状态 `qualified13`。
- Risk Level：约 84,335.6，现价距离很近，是当前重点失效线。
- TDST：约 83,700.5。
- 买方 Countdown：0/13，`cancelled`。
- 卖方 Countdown：13/13，`qualified13`。
- 距上次 qualified 13：1 根 K 线。
- 历史 qualified 13：4 次。

### 1h

- 当前阶段：新一轮上升趋势形成中，Setup 1/9。
- 上一轮下跌 Countdown 13/13 已形成下跌衰竭，产生偏多反转依据。
- 下一根条件：收盘高于约 83,980.9。
- Risk Level：约 81,974.4。
- TDST：约 86,625.8。
- 买方与卖方 Countdown 均保留一轮 `qualified13`。
- 距上次 qualified 13：10 根 K 线。
- 历史 qualified 13：5 次。

### 4h

- 已有一轮上涨 9+13 同时出现，被页面标为“强烈上涨衰竭”。
- qualified 13 的确认价约为 86,500；随后 12 根下跌约 2.29%。
- 对应 Risk Level 约 88,211，盘点时尚未被突破，因此旧反转依据仍有效。
- 当前又有一轮上升趋势确立，Countdown 2/13。
- 同时存在一轮新 Setup 1/9。
- 当前 TDST 约 80,596.4。
- 这正是同一周期必须支持多轮并行结构的例子。

### 1D

- 当前主要结构：上升趋势确立，Countdown 9/13。
- 下一根条件：收盘高于约 85,258.6。
- 第 8 根收盘门槛：约 86,616.3。
- TDST：约 62,747.1。
- 上一个 13 已失效，因此无当前 Risk Level。
- 买方 Setup：2/9；卖方 Countdown：9/13，`active`。
- 买方 Countdown：5/13，`cancelled`。
- 距上次 qualified 13：249 根 K 线。
- 历史 qualified 13：1 次。

## 7. AlphaBTC 的 Regime 校准

AlphaBTC 在原始 TD 信号之外增加两层状态校准：

### 短期 Regime

- 基准周期：1h。
- 作用周期：5m、15m、1h。
- 当前状态：阴跌爆拉。
- 触发含义：下跌 Countdown 13 完成，反转出现。
- 页面明确说明该状态会调整短周期信号置信度。

### 长期 Regime

- 基准周期：4h。
- 作用周期：4h、1D。
- 当前状态：突破减弱。
- 触发含义：上涨 Setup 9 确认，衰减计数仍在进行。
- 页面明确说明该状态会调整长周期信号置信度。

### 三态映射

AlphaBTC 把原始 DeMark 数据压缩成三个业务状态：

1. 反转阴跌：Setup 9 后转跌，但 13 反转尚未出现。
2. 突破减弱：上涨 Setup 9 已确认，Countdown 仍在推进。
3. 阴跌爆拉：下跌 Countdown 13 完成，向上反转出现。

这三个状态是业务层标签，不是 DeMark 原始术语。实现时应保留原始计数，再由规则生成业务标签，不能只保存标签。

## 8. AlphaBTC 的 BUY 1 / BUY 2 / SELL 1 / SELL 2

从页面表现可以确认：

- 第一信号对应 Setup 9 或趋势衰减阶段，强度通常较低。
- 第二信号对应 Countdown 13/反转确认，置信度通常高于第一信号。
- BUY 表示下跌趋势衰竭后的偏多反转。
- SELL 表示上涨趋势衰竭后的偏空反转。
- 信号保存确认 K 线的收盘价和离当前的时间。
- Regime 校准会调整最终置信度等级。

页面没有直接展示精确的置信度计算公式，因此目前只能确认输入与输出，不能把弱/中等/中等偏强的内部权重当作已知算法。

## 9. 已实现的新趋势监测

AlphaBTC 还把新的 Setup 进度做成独立监测器：

- 周期：5m / 15m / 1h / 4h / 1D。
- 当前 Setup 计数和目标 9。
- 新趋势方向。
- 预计完成时间。
- 状态统一为“形成中”。

它解决的问题是：13 出现后不能只盯旧反转，还要同时观察反方向的新 Setup 是否正在建立。

## 10. Dashboard 正确的数据结构

一个周期不能只存一条记录。推荐结构：

```text
demark_cycle_snapshot
  symbol
  timeframe
  observed_at
  price
  selected_algorithm
  current_business_regime

demark_sequence
  sequence_id
  timeframe
  side                 # buy / sell
  setup_count
  setup_status         # forming / established
  countdown_count
  countdown_status     # active / cancelled / qualified13
  setup_confirmed_at
  countdown_confirmed_at
  signal_close_price
  next_count_condition
  countdown_8_close
  tdst
  risk_level
  risk_level_valid
  bars_since_setup9
  bars_since_qualified13

demark_signal
  signal_type          # BUY_1 / BUY_2 / SELL_1 / SELL_2
  source_sequence_id
  raw_confidence
  regime_adjustment
  final_confidence
  invalidation_price
  invalidated_at
```

## 11. Dashboard 展示顺序

为了避免用户把 9 当 13、把方向当建议，单周期卡建议按以下顺序展示：

1. 当前业务结论：趋势形成 / 趋势确立 / 衰竭。
2. Setup 与 Countdown 两条进度。
3. 当前 active、cancelled、qualified13 状态。
4. 下一根计数条件。
5. TDST、Risk Level、第 8 根门槛。
6. 信号确认价、出现时间、距当前 K 线数。
7. Regime 调整前后置信度。
8. 同周期其他仍然有效的历史轮次。

## 12. 对模型的准确理解

- DeMark 不是简单的“9 买、13 卖”。方向取决于计数对应的是上涨还是下跌。
- Setup 9 表示趋势确立兼疲劳提醒，仍可能继续运行。
- Countdown 13 才是衰竭信号，但还需要满足资格门槛。
- 13 出现后也不是永久有效，Risk Level 被突破后必须失效。
- TDST 管理 Setup 9 之后的结构是否延续；Risk Level 管理 13 之后的反转是否失效。
- 一个周期可能同时存在旧 13、新 Countdown 和反方向新 Setup。
- 多周期共振不是多数投票，而是大周期方向与小周期时点的组合。
- AlphaBTC 的“阴跌爆拉/突破减弱”等是业务层 regime 标签，不是原始 DeMark 状态。
