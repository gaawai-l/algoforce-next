# BTC 链上与永续融合 P5（优化清单 O1–O6）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标**：在已与原站逐数对上的 v1 之上，按主 spec §4 逐项实现 O1–O6。每一项都满足以下要求：
- 单独实现；
- 单独加测试；
- 可以单独开启；
- 界面写明当前用的口径；
- 验收记录写清开启前后的差异。

**架构**：新增规则开关 `Rules`。
- 纯计算函数和 worker 都显式接收开关；
- 派生结果连同当时的开关一起保存；
- 视图返回生成该数据时所用的规则，前端据此显示口径。

**技术栈**：同 P1–P4。

**Spec**：主 spec [SPEC.md](SPEC.md) §4；O6 另见 [P4 spec](../btc-perp-states/SPEC.md)。spec §4 每项只有一行，本计划的"规则细化"把它们写成可执行的规则，以本计划为准。用户已授权全部阶段连续执行。v1、v2 各经过一轮独立评审后修订为 v3，v3 的复核意见也已改入，修订记录见文末。

**前提**：P3 和 P4 都已合并到 main，从 main 开分支 `claude/onchain-p5`。

## 计划层面的裁定

| 编号 | 裁定 | 理由 |
|---|---|---|
| P5-R1 | 环境变量 `WHEELHOUSE_RULES` 的取值规则：<br>• 逗号分隔的代号 `O1`–`O6`，大小写不敏感，忽略空白和重复；<br>• 未设置或为空字符串时，取默认值，即全部开启；<br>• 单独写 `v1` 表示全部关闭；`v1` 与其他代号同时出现时，启动失败；<br>• 无法识别的值同样让服务启动失败 | 空字符串很容易由 compose 文件意外产生，不能把它解释为"全部关闭" |
| P5-R2 | 每份派生载荷都写入生成时所用的 `rules`，即 `sorted(rules_for_view(view, 配置))`，视图原样返回。<br>• 比较时按集合比较。配置与载荷中的规则不一致时，onchain 的 worker 立刻只从库里重新派生（不访问 BRK）；永续不单独重派生，由首轮覆盖（见 Task 7a）。完成之前，视图带 `rules_pending: true`。<br>• 新增的载荷字段都有默认值，旧载荷可读：`rules=[]`，`latest_day=None`，`latest_urpd_day=None`；为 None 时新鲜度按 v1 公式计算 | 保证界面显示的口径就是生成这些数字的口径；只切换一个视图无关的规则时，不误报 pending |
| P5-R3 | 各视图涉及的规则：<br>• 周期：O1、O4<br>• levels：O1、O5<br>• cost-basis：O1、O5<br>• 卖压：O1、O2、O3<br>• 永续：O1、O6<br><br>`rules_for_view` 只返回"已对该视图实现"且"已开启"的规则，所以载荷和视图里也只有这些 | 写清楚哪些规则影响哪个视图 |
| P5-R4 | 以下各处都改为必填的关键字参数 `rules`：纯函数、`OnchainSync`、onchain 的 `create_router`；永续侧的 `compute_states`、`PerpsSync`、perps 的 `create_router` 在 Task 7a 再加，之前 `http.py` 只把 `rules` 传给 onchain。现有测试传 `frozenset()`，数值不变。`create_app(rules=None)` 表示取 `Settings.from_env().rules`；凡是断言 v1 数值、经由 `create_app` 的测试都显式传 `rules=frozenset()` | 避免"默认关闭"与"默认开启"互相矛盾 |
| P5-R5 | **已收盘日** `closed_day(at) = (at − 2h).date() − 1 天`，2h 即 `GRACE_END`。辅助函数放在 `onchain/models.py`，与 `GRACE_END` 同处。day1 行和 URPD 都按这个定义 | 两边口径一致；D−1 的值在 02:00 前可能还会被修订 |
| P5-R6 | O5 的 GMM 保留，k 仍取峰数；只修正"没有峰"时走的 BIC，见规则细化 | 价带和表 2 依赖 M |
| P5-R7 | 1d–1w 线名为 `one_day_to_week`，在 `LINE_ORDER` 中排最后。它既画成成本线，也作为候选计入价带和表 2。对表 2 的影响写进验收记录；如果它总是占住紧邻 spot 的那一段，就在记录中提出"只画线"的建议 | 用户在 mockup 中确认过 "1d–1w cost" 这一行；同时如实记录影响 |
| P5-R8 | 验收时，先让 P5 代码按默认规则完整跑完一轮（O1 需要的 C 集合快照由这一轮取到），再把本机库复制两份，再用只派生、不取数的命令 `python -m wheelhouse_service.derive`（Task 1a 新建，Task 7a 扩展到永续），分别在 `v1` 和默认规则下各跑一次，比较两份载荷 | 避免两次实时运行之间数据本身的变化混进对比 |
| P5-R9 | 永续的保留期改为 125 天、回填改为 121 天，**不随开关变化**。<br>• v1 的状态、阈值、表 1 只用 90 天参考窗口，数值不变；<br>• `/perps/status` 的方向核对（`direction_check`）和 `bybit_qty` 遍历整个网格，样本范围随之扩大到 121 天。清算从采集开始才有，所以采集满 91 天之前两者结果相同；<br>• 代价是首次多拉约 30 天的 Binance 日包 | 开关切换时不必补数据，取数逻辑也不依赖规则 |
| P5-R10 | 永续的 `Thresholds.n_all` 改为 `n_px` 和 `n_oi`，不做旧载荷兼容 | P4 从未发布，只有本机开发库有永续载荷，重启后首轮即被覆盖 |

## 规则细化

### O1 只用已收盘的数据（开关 `O1`）

未收盘的那一行照样画出来，但不进入阈值、状态和价位。

**两个锚**
- **C** = `closed_day(at)`，是读数的日期上限，也是 URPD 取数和保留的锚。`at` 是本轮开始的时刻：`_derive` 新增参数 `closed: date`，由 `_refresh` 用同一个 `at` 算出，使取数和派生用同一个 C，重试跨过 02:00 时也不会把仍可能修订的一天当作已收盘；`derive_from_store` 用已存的 `computed_at` 算出。
- **F** = URPD 派生所用的日期。取 C 和 C−1 中第一个满足条件的日期：`URPD_SET` 的 9 份快照都已存，且每份的 `fetched_at ≥ 该日次日 00:00 + 2h`（已定稿）。都不满足时 F 为 None。
- C 的快照在 C 次日 02:00 之后取到，所以一取到就是定稿的。因此正常情况下 F = C；只有 C 的某份快照取数失败时，F 才退到 C−1。

**新鲜度**（防止视图每天被误标为过期）
- 新鲜度按 `latest_day` 计算；`as_of` 只表示读数所用的已收盘日。为 None（旧载荷）时，按 v1 公式。
- `latest_day` 的定义：
  - 周期：最新一个四条序列都有值的日期，即 v1 会用作 `as_of` 的那一天；
  - levels：最新一个全部模型线序列都有值的日期（v1 的 `last_complete` 结果）；
  - cost-basis：`min(levels 的 latest_day, D)`。D 是库中最新的 `all lin500` 快照日，即 v1 的 `_urpd()` 或 `_recent_urpd()` 给出的那一份。D 为 None 时 `latest_day` 也为 None，回退 v1 公式，视图显示 stale；`_refresh` 照常追加 `urpd_missing`。
  - v1 下这三个值与原公式算出的日期相同，所以无论开关如何都写入。
- levels 载荷新增 `latest_urpd_day = D`。
- `/onchain/status`：
  - day1 取 cycle 与 levels 两者 `latest_day` 的较大值，为 None 时回退到 `as_of`；
  - urpd 取 levels 的 `latest_urpd_day`，为 None 时回退到 `urpd_date`。
- 视图不暴露 `latest_day` 和 `latest_urpd_day`；`model_dump` 时排除这两个字段。
- hourly 数据照 P2 的 `latest_at` 处理。

**周期**
- 只用日期 ≤ C 的行；
- `forming_at` 恒为 None；
- badge 写 "as of <日期> close"（新文案 `cycle.closedAsOf`）。

**levels 和 cost-basis**
- 模型线取 `last_complete(rows, rules=..., through=C)`。
- `_derive` 按 F 从库里读 `all lin500`，不再用 `_urpd()` 返回的 D。读到的快照用于：
  - median 线；
  - `levels.urpd_date` 和 `onchain_close`，因此 spot 是 F 的收盘价，口径文字要写出来；
  - cost-basis 的当天快照。
- 网格用的历史日期为 F−1、F−7、F−30、F−90。
- F 为 None 时：median 线缺失，cost-basis 照 v1 清空；共享原因码加上 `urpd_not_final`（不带后缀，属于防御性原因码），并加入 `LEVELS_REASONS`、`COST_BASIS_SHARED`、`URPD_REASONS`。
  - `_derive` 返回 O1 下是否得到 F，`_refresh` 据此在拼装共享原因码时追加；
  - `derive_from_store` 不更新 `sync_state.reasons`。由于重派生会把 `next_due` 设为 now，下一轮会立刻修正。
- O1 下 `_recent_urpd` 的"不早于昨天"只用来判断 D，与 F 无关。

**sync 的取数和清理**（O1 开启时）
- v1 的取数（D 和 D 的历史日期）不变。
- 另外按 `closed_days(at)` 取数。它返回有序 list：C、C−1，以及两者各自的 `C−n` 与 `C−1−n`（n ∈ `PAST_DAYS`），去重后共 9 个日期，顺序为 C、C−1、C−2、C−7、C−8、C−30、C−31、C−90、C−91（先两个锚，其余由近到远）。
  - 每个日期取 `URPD_SET` 的 9 份；已定稿的不再取。
  - 遇到第一个 `BrkError` 就停止这一步，记日志 `onchain_urpd_closed_failed code=...`，不让 stage 失败，下一轮再补。`client.urpd` 返回 None 不算失败，只是跳过这一份。
  - 这一步不依赖 D：D 取不到（v1 的 `_urpd` 返回 None 或抛错）时照样执行。
  - 首次开启最多取 81 份，之后每天新增 C、C−7、C−30、C−90 四天，共 36 份。
- 清理：`_urpd` 中每一次 `prune_urpd(keep)` 都并上 `closed_days(at)`。由于 C−1 总在保留集合中，F 退到 C−1 时数据一定还在，不需要记"上一个 F"。

**卖压**
- 函数改为 `seller_pressure(rows, *, rules, computed_at)`。
- `closed_at` = 最后一个已收盘的小时（满足 P2-R5：`computed_at ≥ t + 1h`）；没有已收盘的行时为 None。
- 当前读数和图例的默认行都取 `closed_at` 那一行。
- O2 关闭时，阈值窗口锚定在 `closed_at`：`(closed_at − 720h, closed_at]`。
- 未收盘的那一行照样画，不进入阈值样本，level 为 null，也不计入 run。

**永续**
- forming 块照样画，但不判定，也不进入阈值样本。
- `covered_days` 不变，仍计入 forming 块；O6 关闭时，`collecting` 改为按去掉 forming 块后的已覆盖块数判断，与阈值样本一致。
- 表 1 的 `latest` 和 `latest_uncovered` 改为取最后一个已收盘的块。

### O2 卖压阈值逐小时滚动（开关 `O2`）

- **阈值**：每个小时 h，取 `[h − 720h, h)` 内的保留行，每张图分别按 R-7 计算 P95 和 P75。
  - 值为 null 的点（gap、分母 ≤ 0）不计入样本。
  - 样本少于 168 个时，阈值为 null。
- **level**：值 ≥ P95 为 `extreme`，≥ P75 为 `warning`，否则为 `none`；阈值为 null 时，level 也为 null。
- **run**：
  - 起点：O1 开启时为 `closed_at`，关闭时为最后一行；
  - 从起点往回数，连续 level ≥ warning 的**时钟小时**数；
  - 遇到缺失的行（O3 关闭时被丢掉的小时）或值为 null 的点，计数就此中断；
  - 起点的 level 为 null 时，run 为 null，不记为 0。
- **契约**：
  - 点新增 `p95`、`p75`、`level`；每张图新增 `run`。O2 关闭时，这四个值都为 null。
  - `loss_levels`、`share_levels`、`supply_levels` 的结构不变，O2 下取起点那个小时的 p95、p75 和样本数。
  - 每个点多三个字段，API 响应约增加 300KB（未压缩）。
- **页头**：Extreme 和 Warning 显示起点那个小时的阈值，`n` 为样本数。
- **回看长度**：模块常量 `LOOKBACK` 改为函数 `lookback(rules)`。v1 为 2600 小时；O2 为 2160 + 720 = 2880 小时，库里有 3000 小时，够用。sync 读 hour1 时用 `tail=lookback(rules) + 1`。
- **不变式**：样本数 ≥ 168 的小时 h，其 p95 和 p75 等于把数据截到 h − 1 后按 v1 算出的阈值。

### O3 卖压不再丢行（开关 `O3`）

- **没有出块的小时**：11 条 hour1 序列全部为 null。
  - 价格、全部累计序列（包括 <1h 的）和 4 条供应序列，都沿用上一行；
  - 流量记 0，并标 `no_block`；
  - 下一行照常计算差分；
  - 如果这样的小时恰好是窗口的第一行，就丢掉它。
- **部分缺失**：<1h 以外的序列中，有的为 null，有的不为 null。
  - 依赖该序列的腿记为 null，并标 `gap`；下一行以 null 为基准，同样处理；
  - 图 1 中只要有一条腿为 null，合计就为 null；
  - 值为 null 的点不进入阈值样本；
  - 契约中的 `PressureLossPoint.lth`、`PressureLossPoint.sth` 和 `PressurePoint.value` 改为可以为 null。
- **<1h 序列为 null**：沿用 v1 的处理，即保留该行、`xgap` 加 1、不扣除。O3 不改变这一点。
- **只有价格缺失**：这一行的价格为 null，其余照常。
- **QC**：O3 开启时，`hour_gap` 的阈值收紧为 > 1h，因为不再丢行。
- **界面**：悬停时显示 no-block 或 gap；图上不画成 0。
- **P2 fixture 上的期望值**（v1 → O3）：
  - kept：2576 → 2598；
  - 图 1 的 n：716 → 720；
  - 图 2 的 n：716 → 718（没出块的小时分母为 0）；
  - 图 3 的 n：716 → 720。

### O4 周期按日历计天（开关 `O4`）

- **缺失日**：只处理**中间的**缺失日，即四条序列中任一条缺失或 ≤ 0、而前后都有完整日的日期。
  - 这些日子沿用上一状态，分量为 null，不参与门控；
  - 它们算在所属 Episode 之内：该 Episode 的 `end` 是下一段起点的前一天，`days` 包含这些日子。
- **as_of**：最后一个四条序列都有值的日期。末尾不完整的日子不会把 run 延长。
- **天数**：按日历计，`Episode.days` 也一样。
- **验证范围**：P1 fixture 没有缺失日，O4 在它上面的差异为 0，这一点写进记录；O4 的效果用合成数据测试。

### O5 价位稳定可复现（开关 `O5`）

- **价格域**：KDE 和 GMM 的价格域固定为 `all` 快照 close 的 ±50%。
  - 保留中心价（floor + 桶宽/2）在 `[0.5c, 1.5c]` 内的行；
  - 域写成 `[第一行的 floor, 最后一行的 floor + 桶宽]`；
  - 切片仍按这个域截取。
  - 以 close 81217.6 为例：lin500 为 [40500, 122000]，lin200 为 [40600, 121800]，lin1000 为 [41000, 122000]。
  - 界面要写明三点：带宽约为 0.02 × 价格域宽度；SHARE 只算域内的权重；域外的模型线不计入候选。
- **BIC**：
  - `n` = 参与拟合的正权重行数；
  - `logL = Σ_i (w_i / Σw · n) · log p(x_i)`；
  - `BIC = −2·logL + (3k − 1)·ln n`；
  - O5 下 `select_components` 的 `rows` 参数不再使用，n 由权重得出。
  - 验收时在黄金样本上把峰数强制设为 0，记录每个 cohort 和桶宽选出的 k。如果总是撞上限 5，就重新评估是否去掉 GMM（spec §4 允许）。
- **1d–1w 线**：按 P5-R7。以下各处都随开关变化：
  - `LINE_ORDER`、`LINE_SERIES`、`last_complete`；
  - `_derive` 中检查模型线条数的地方，以及 `cost_basis` 中检查线名集合的地方；
  - `LEVELS_REASONS` 和 `COST_BASIS_SHARED`。
- **分项记录差异**：内部函数 `_cost_basis(today, past, bucket, lines, *, fixed_domain: bool, new_bic: bool)` 承担计算；公开的 `cost_basis(..., rules)` 按 O5 把两个布尔值同时开或关。1d–1w 线的影响，靠传入的 `lines` 中有无这条线来区分。验收脚本和差异测试直接调用内部函数，三项各自开启。

### O6 永续状态去掉前视（开关 `O6`，P5-R9、P5-R10）

- **判定范围**：只判定与 30 天视图重叠的块，即载荷中的 `blocks`。块 b 的参考窗口为 `[b.t0 − 90d, b.t0)`，取自整个网格；网格回填 121 天，所以够用。`covered_days` 和 QC 仍用 v1 的 90 天参考窗口。
- **样本**（窗口内）：
  - 清算阈值：清算已覆盖的块；
  - 价格阈值：`imputed.dpx` 为假的块；
  - OI 阈值：`imputed.doi` 为假的块。
- **最少样本**：每个阈值各自至少 42 块（4h）或 21 块（8h），即 `COLLECTING_DAYS × BLOCKS_PER_DAY`。不足的阈值为 null；四个阈值中任一为 null，b 不判定。
- **分位数**：R-7。`quantile_r7` 由 Task 5a 移到 `wheelhouse_service/stats.py`；永续新增 import 它用于 O6，v1 的 `quantile` 保留。
- **dPx**：以 `b.t0 − 600` 那个桶的价格为基准，到块最后一个桶为止。基准或终点缺失时，记 `imputed.dpx = True`。
- **squeeze**：还要求该侧清算 > 0。
- **补 0 的块**：`imputed.dpx`、`imputed.doi`、`imputed.sums` 任一为真，即不判定。各自的样本按上面的规则剔除。
- **判定条件**：除以上各条外，仍要求块 `covered`，与 v1 相同。
- **结构**（契约随之修改）：
  - `Thresholds` 的四个阈值可为 null；样本数改为 `n_liq`、`n_px`、`n_oi`。v1 下 `n_px = n_oi` = 参考块数（O1 时去掉 forming 块）。
  - `Block.thresholds: Thresholds | None = None`，仅在 O6 下填写；不判定的块也填，用来说明缺了什么。
  - 参考块 R：最后一个块；O1 开启时为最后一个已收盘的块。不论 R 本身是否被判定，O6 下顶层的 `StatesResult.thresholds` 都取 R 的阈值，`collecting` 取 R 的 `n_liq` 是否小于 42/21。
  - 没有 R 时（`blocks` 为空），四个阈值为 null，各样本数为 0，`collecting` 为真。
- **Max move**：表 1 的 `max_move` 是展示用的涨跌幅，不参与判定，不随 O6 改，仍以 run 首块的首桶价为基准。
- **界面**：Parameters 显示顶层阈值；悬停时显示该块自己的阈值。没有判定的块说明原因，由块的字段推出：
  - forming（O1）；
  - imputed；
  - 参考块不足（阈值为 null）。

## 全局约束

- 开关参数的传递见 P5-R4。
- `rules=frozenset()` 时，P1–P4 的全部测试结果不变。断言整份载荷的测试可以加上新字段，但数值不变。
- 每项开关都有：
  - 一个开启前后的差异测试；
  - 一个 sync 层面的测试，证明开关确实传到了纯函数。
- 文案走 `i18n.ts`，en 与 zh 的键保持一致；新的原因码在 `onchain-text.ts` 的 `reasonText` 中有对应文案。
- 检查运行 `make check`；改了契约后先运行 `make contract`；改了 `http.py` 的组装后，单独运行 `deploy/test/test_composition.py`。

## 评审重点（Review Focus）

1. **`rules=()` 时数值不变**：P1–P4 的对照测试在所有 Task 中都必须通过。
2. **O1 跨日与新鲜度**：
   - 在 10:40 和 01:30 读取，视图（含 `/status`）都是 fresh，`as_of` 为已收盘日，不使用未收盘值；
   - 00:12、01:12、02:12 三个时刻，以及 02:12 时 C 的一份快照取数失败，cost-basis 一直可用，F 分别为 C、C、C 和 C−1。
   - 测试在 Task 2、Task 3a、Task 3b、Task 5a。
3. **换规则重启**：标签显示的是生成数据时的规则；规则不一致时只从库里重新派生，期间显示 `rules_pending`；派生沿用已存的 `computed_at`。测试在 Task 1a。
4. **O3 没有出块的小时**：保留该行，流量为 0，界面不画成 0 值柱。测试在 Task 4。
5. **O6 部分判定**：同一视图里，前面的块因参考块不足而不判定，后面的块正常判定；表 1 和图都如实显示。测试在 Task 7a 和 7b。

---

## 文件结构

| 文件 | 改动 |
|---|---|
| `wheelhouse_service/rules.py`（新建） | `Rule`、`Rules`、`ALL_RULES`、`parse_rules`、`rules_for_view`、`IMPLEMENTED` |
| `wheelhouse_service/stats.py`（新建，Task 5a） | `quantile_r7`，从 `onchain/pressure.py` 迁来；`pressure.py` 保留 `from ..stats import quantile_r7` |
| `wheelhouse_service/derive.py`（新建） | P5-R8 的只派生命令，`python -m wheelhouse_service.derive --data-dir DIR [--rules SPEC]` |
| `settings.py`、`http.py` | `Settings.rules`，`create_app(rules=None)` |
| `onchain/models.py` | `closed_day`、载荷新字段 |
| `onchain/cycle.py`、`pressure.py`、`levels.py`、`costbasis.py`、`sync.py`、`store.py`、`api.py` | O1–O5 |
| `perps/states.py`、`perps/sync.py`、`perps/api.py`、`perps/models.py` | O1、O6、P5-R9 |
| 前端：`onchain-contract.ts`、`perps-contract.ts`、`perp-states-sample.json`、`cycle-badge.tsx`、`seller-charts.tsx`、`onchain-levels.tsx`、`onchain-text.ts`、`cost-basis-panel.tsx`、`perp-states.tsx`、`perp-charts.tsx`、`i18n.ts` | 口径、`closedAsOf`、O2 的阶梯线、O3 的 gap 显示、1d–1w 线、O6 的部分判定 |
| `docs/features/btc-perp-states/SPEC.md` 第 86 行 | 保留期改为 125 天 |
| `docs/deployment/RELEASING.md` | `WHEELHOUSE_RULES` 的说明与回滚注意事项 |
| `docs/features/btc-onchain-perp/P5-VERIFICATION.md` | 记录 |

---

### Task 1a：规则开关与载荷中的规则（后端）

**Interfaces**
- `rules.py`：
  - `Rule = Literal["O1", "O2", "O3", "O4", "O5", "O6"]`、`Rules = frozenset[Rule]`、`ALL_RULES`；
  - `parse_rules(text: str | None) -> Rules`，按 P5-R1，无法解析时抛 `ValueError`；
  - `View = Literal["cycle", "levels", "costbasis", "pressure", "perps"]`；
  - `IMPLEMENTED: dict[View, Rules]`，此时全部为空，每个 Task 完成后加入它实现的规则；
  - `rules_for_view(view: View, rules: Rules) -> list[Rule]`：`sorted(rules & IMPLEMENTED[view])`。
- `Settings.rules: Rules`，默认 `ALL_RULES`，`from_env` 用 `parse_rules`。
- `OnchainSync(store, client, *, rules)` 和 onchain `create_router(..., *, rules)` 改为必填参数（P5-R4）。
- 四份 onchain 载荷都新增 `rules: list[Rule] = []`。
- 视图新增 `rules: list[Rule]`（取自载荷）和 `rules_pending: bool`（按 P5-R2 用集合比较）。没有载荷时，`rules` 为空，`rules_pending` 为假。
- `OnchainSync.derive_from_store() -> None`：只读库，按 `self.rules` 重新派生全部视图。
  - day1 视图的派生时刻取已存的 cycle、levels、costbasis 载荷中最新的 `computed_at`；三者都没有时跳过；
  - D 取 `_recent_urpd(该时刻)`；
  - 卖压沿用已存卖压载荷的 `computed_at` 作为 `hour1_at`，`hour1_missing` 用 `_stored_hour1_missing()`；没有卖压载荷时跳过。
- `OnchainSync.rederive_if_rules_changed(now) -> bool`：任一已存载荷的规则与 `rules_for_view(view, self.rules)` 不同，就调用 `derive_from_store()`，并把 `next_due` 设为 `now`，使新规则需要的取数立刻进行。`start()` 的线程在进入循环前调用一次。
- `derive.py`：`main(argv)` 解析 `--data-dir`（必填）和 `--rules`（缺省时读环境变量），对 `DIR/onchain.sqlite` 调用 `derive_from_store()`。`OnchainSync` 需要的客户端传一个 `BrkClient()`，它不会被调用（测试断言没有请求）。这个命令只用于库的副本，帮助文本要写明。
- `RELEASING.md`：说明 `WHEELHOUSE_RULES` 的取值（P5-R1）和默认值。回滚到 P5 之前的版本时，旧代码读新载荷会因 `extra="forbid"` 校验失败，直到下一轮派生覆盖（onchain ≤ 1 小时，perps ≤ 10 分钟）。

**测试**
- `parse_rules`：大小写、空白、重复、`v1`、`v1,O2`（报错）、空字符串、None、无法识别的值。
- 旧载荷（没有 `rules` 字段）可以读取，`rules` 为空。
- 这一步 `IMPLEMENTED` 全空，`rules_for_view` 恒为 `[]`，所以下面三条测试用 monkeypatch 临时设置 `IMPLEMENTED`（例如 `{"cycle": frozenset({"O1"})}`，其余为空）。
- 用不同规则重启：重派生之前，标签仍是旧载荷的规则，同时显示 `rules_pending`；`rederive_if_rules_changed` 之后两者一致，`computed_at` 不变，`next_due` 等于 now，且整个过程没有调用 BRK 客户端。
- 只改变与某视图无关的规则时，该视图不显示 pending。
- `derive` 命令在库的副本上运行，载荷的 `rules` 按参数改变。
- 现有测试改为传 `rules=frozenset()`，数值不变；`deploy/test/test_composition.py` 通过。

**提交**：`feat(onchain): add rule switches and store the rules with each payload`

### Task 1b：口径显示（前端）

- 契约：四个 onchain 视图新增 `rules` 和 `rules_pending`，运行 `make contract`，zod 同步。
- 口径写在 Source 区块、卖压页头、cycle badge 的 tooltip 中：
  - `rules` 为空时显示 "original v1"；
  - 否则列出规则代号和简短名称，en 与 zh 都要有；
  - `rules_pending` 为真时，加一行提示 "Recomputing with the configured rules"。
- **测试**：空规则、多条规则、pending 三种显示。
- **提交**：`feat(onchain): show which rules produced each view`

### Task 2：O4 和 O1 用在周期上

**Interfaces**
- `classify(rows, *, rules: Rules, closed_day: date | None)`；`_derive` 传入 `closed_day(at)`。
- 周期载荷写入 `latest_day`；视图的新鲜度按 `latest_day` 判断，为 None 时按 `as_of`。
- `IMPLEMENTED["cycle"]` 加入 O1、O4。

**测试**
- `rules=()` 与 P1 一致：Breakout、09-23 起、第 24 天、48 次切换。
- O4（合成数据）：
  - 中间的缺失日沿用上一状态，并算进所属 Episode 的 `end` 和 `days`；
  - 末尾的缺失日不延长 run；
  - 天数按日历计；
  - 值 ≤ 0 视为缺失。
- O1：在 10:40 和 01:30 读取，都是 fresh，`as_of` = 已收盘日，`forming_at` 为 None。
- 前端：badge 显示 `closedAsOf`。
- sync 测试：开启 O4 后，派生出的载荷随之改变。
- 开启前后的差异：在 P1 fixture 上，列出 O1、O4、O1+O4 时的 state、since、day、changes；O4 在这份数据上差异为 0，写明原因。

**提交**：`feat(onchain): count cycle days by calendar and use closed days`

### Task 3a：O1 用在 levels 和 cost-basis 上（派生与视图）

**Interfaces**
- `last_complete(rows, *, rules, through: date | None)`；`model_lines(values, urpd, *, rules)`（O5 在 Task 6 才用到 `rules`）。
- `store.final_urpd_day(candidates: Sequence[date]) -> date | None`：返回第一个满足条件的候选日，条件是 `URPD_SET` 的 9 份都已存且都已定稿（`fetched_at ≥ 次日 00:00 + 2h`）。
- `_derive(..., closed: date)` 在 O1 下用 `final_urpd_day((closed, closed − 1 天))` 得到 F，从库里读 F 的 `all lin500`，用法见规则细化；返回值告诉 `_refresh` 是否要追加 `urpd_not_final`。
- 载荷：levels 新增 `latest_day` 和 `latest_urpd_day`，cost-basis 新增 `latest_day`；O1 关闭时也写入。
- 视图的新鲜度和 `/status` 按规则细化计算；视图 `model_dump` 时排除这两个新字段。
- 新增原因码 `urpd_not_final`。
- `IMPLEMENTED["levels"]` 和 `IMPLEMENTED["costbasis"]` 加入 O1。

**准备**：补抓黄金样本对应的历史快照。黄金样本抓取于 10-16 18:29Z，此时 C = 10-15，所以要抓 10-14、10-08、09-15、07-17 四天，每天 9 份。这些是公开且已定稿的数据，存入黄金目录，并在 README 中说明。

**测试**（直接构造库的内容，不经过取数）
- O1 关闭时与 P3 一致。
- `final_urpd_day`：
  - C 的 9 份都已定稿时，返回 C；
  - C 缺一份或有一份未定稿时，返回 C−1；
  - 两天都不满足时，返回 None，此时 cost-basis 不可用，共享原因码含 `urpd_not_final`。
- `_derive` 用 F 的快照：median、`urpd_date`、`onchain_close` 都来自 F，而 `latest_urpd_day` 是 D。
- 新鲜度：在 10:40 读 levels、cost-basis 和 `/status`，都是 fresh。
- sync 测试：开启 O1 后，`_derive` 读的是 F 的快照，载荷随之改变。
- 开启前后的差异：在 P3 黄金样本上比较表 2。

**提交**：`feat(onchain): derive levels from closed days and final URPD snapshots`

### Task 3b：O1 下 URPD 的取数和清理

**Interfaces**
- `closed_days(at) -> list[date]`，有序，定义见规则细化，放在 `onchain/sync.py`。
- `OnchainSync` 在 O1 下执行规则细化中的"取数和清理"：在 `_urpd` 之后执行，不论 `_urpd` 成功、返回 None 还是抛错。
- 前端：`reasonText` 为 `urpd_not_final` 加 en 和 zh 文案。

**测试**（用 BRK 的模拟传输，T 为某一天）
- 00:12：D = T 还不存在，F = C = T−2；
- 01:12：D = T 已存在，F = T−2；
- 02:12：这一轮取到 T−1 的 9 份，F = T−1；
- 02:12，T−1 的一份快照取数抛 `BrkError`：F = T−2，保留集合中仍有 T−2 及其历史日期，取数在这个错误处停止，排在后面的日期这一轮不再请求。

每个时刻 cost-basis 都可用，原因码正确，清理之后库里只剩 v1 保留集合与 `closed_days(at)` 的并集。另外两条：
- D 取数抛错时，closed 的取数照样进行；
- 已定稿的快照不再重取；
- `client.urpd` 返回 None 时跳过这一份，继续取后面的。

**提交**：`feat(onchain): fetch and keep the closed-day URPD snapshots`

### Task 4：O3 卖压不再丢行（后端加前端）

**Interfaces**：`seller_pressure(rows, *, rules)`（`computed_at` 到 Task 5a 再加）；契约中的腿可以为 null；点新增 `no_block` 和 `gap`；O3 开启时 QC 的 `hour_gap` 阈值为 1h。`IMPLEMENTED["pressure"]` 加入 O3。

**测试**
- `rules=()` 时与 P2 一致，kept 为 2576。
- O3 在 P2 fixture 上：kept 为 2598，图 1、图 2、图 3 的 n 分别为 720、718、720；没出块的小时流量为 0；供应序列沿用上一行。
- 部分缺失：对应的腿为 null，并标 gap；图 1 合计为 null。
- <1h 序列为 null：行保留，`xgap` 加 1，与 v1 相同。
- 窗口第一行就是没出块的小时：丢掉。
- 只有价格缺失。
- 前端：gap 的点不画柱，悬停显示 no-block 或 gap。
- sync 测试：开关确实传到了纯函数。

**提交**：`feat(onchain): keep seller pressure rows across no-block hours`

### Task 5a：O1 与 O2 用在卖压上（后端）

**Interfaces**
- 新建 `stats.py`，把 `quantile_r7` 迁过去；`pressure.py` 保留 `from ..stats import quantile_r7`，现有测试的 import 不变。
- `seller_pressure(rows, *, rules, computed_at)`；`lookback(rules)` 取代 `LOOKBACK`。
- 点新增 `p95`、`p75`、`level`；每张图新增 `run`；载荷新增 `closed_at`。O2 关闭时这些都为 null，含义见规则细化。
- `_derive` 把 `hour1_at` 作为 `computed_at` 传入，读 hour1 时用 `tail=lookback(rules) + 1`。
- `IMPLEMENTED["pressure"]` 加入 O1、O2。

**测试**
- `rules=()` 时与 P2 一致。
- O2 的不变式：样本数 ≥ 168 的小时 h，其阈值等于把数据截到 h − 1 后按 v1 算出的阈值。
- 最早 168 小时的阈值为 null；放进一个停服空洞后，空洞之后的头几个小时也为 null。
- 一个未来的极值点，不影响更早小时的阈值。
- level 和 run：遇到缺失的行或 null 点都中断；起点为 null 时 run 为 null。
- O2 下 `loss_levels` 等于起点小时的 p95、p75 和样本数。
- O1：
  - 未收盘行不进入阈值，也不作当前读数，它的 level 为 null；
  - 只有一行且仍在形成时，`closed_at` 为 None。
- sync 测试：开启 O2 后读 hour1 的长度为 `lookback(rules) + 1`，载荷带逐点阈值；`computed_at` 取自 `hour1_at`。

**提交**：`feat(onchain): roll seller thresholds hourly from closed hours`

### Task 5b：O1 与 O2 用在卖压上（前端）

- 阈值线改为阶梯线，用每个点的 p95 和 p75；为 null 的地方断开。
- 页头显示当前的 level 和 run；为 null 时显示 `—`。
- O1 开启时，图例默认显示 `closed_at` 那一行。
- **测试**：阶梯线、level 和 run、null 的显示、图例的默认行。
- **提交**：`feat(onchain): show rolling seller thresholds with level and run`

### Task 6：O5 价位

**Interfaces**
- `cost_basis(..., rules)` 与内部的 `_cost_basis(..., fixed_domain, new_bic)`，见规则细化；`select_components` 在 `new_bic` 下不用 `rows`。
- `LineName` 新增 `one_day_to_week`；1d–1w 线的接入各处见规则细化。
- 前端新增这条线的名称文案，以及价格域的说明文字。
- `IMPLEMENTED["levels"]` 和 `IMPLEMENTED["costbasis"]` 加入 O5。

**测试**
- `rules=()` 时与 P3 黄金样本完全相同。
- O5 的价格域：用 `rules={O5}`（spot 为 D=10-16 的 close 81217.6；O1 开启时 spot 是 F 的 close，域不同），三种桶宽的精确边界见规则细化。
- BIC：
  - 构造中等分离的两簇数据，使 v1 选 1、新公式选 2；
  - 单个高斯分布时，新公式仍选 1；
  - 记录黄金样本在峰数强制为 0 时各自选出的 k。
- 1d–1w：W 用 P1 fixture 中 10-16 的值（注明它与 URPD 不是同一时刻），线出现在候选中；对表 2 的影响写进报告。
- sync 测试：开启 O5 后，levels 载荷带 1d–1w 线，cost-basis 载荷随之改变。
- 开启前后的差异：用内部函数分别记录"价格域""BIC""1d–1w 线"三项。

**提交**：`feat(onchain): fix cost-basis domain, BIC and add the 1d-1w line`

### Task 7a：O6（后端）

**Interfaces**
- `compute_states(grid, window, *, rules)`；`PerpsSync(..., *, rules)` 和 perps `create_router(..., *, rules)`，由 `http.py` 传入。
- 新增模块函数 `derive_states(store, *, start: int, at: datetime, rules: Rules) -> dict[Exchange, Grid | list[str]]`，内容即现在的 `PerpsSync._derive`，后者改为调用它。
- `StoredStates.rules: list[Rule] = []`；`PerpStatesView` 新增 `rules` 和 `rules_pending`。`states_view` 从 `StoredStates` 取 `rules`，不从 `states` 的字段展开。
- 永续不单独重派生：首轮不延迟，取数后立刻派生，pending 最多持续一轮。
- P5-R9：`RETENTION_DAYS` 120 → 125，`PerpsSync.horizon_days` 默认 90 → 120（`start` 为 121 天前）；同步修改 P4 SPEC 第 86 行。
- 规则细化中 O6 的结构（P5-R10）；运行 `make contract`，更新 zod、`perps-contract.ts` 中的样例生成器（如 `collecting()`），并重新生成 `perp-states-sample.json`。
- `derive` 命令扩展到 `DIR/perps.sqlite`：`at` 取已存载荷的 `computed_at`，`start` 按 `_round` 的算法由 `at` 算出。
- `IMPLEMENTED["perps"]` 加入 O6。

**测试**
- `rules=()` 时与 P4 一致，包括本地 parity；v1 的 `n_px = n_oi` = 参考块数。
- 回填 121 天、保留 125 天：v1 的状态、阈值、表 1 不变（P5-R9）；方向核对与 `bybit_qty` 的样本范围变为整个网格，写一条断言说明。
- O6：
  - 只看过去：改动未来的块，不影响过去块的状态和阈值；
  - 使用 R-7；
  - dPx 的基准是 `t0 − 600` 那个桶，基准缺失时不判定；
  - squeeze 要求该侧清算 > 0；
  - imputed 的块不判定，并按特征剔出各自的样本；
  - 每个阈值各自检查最少样本；
  - 部分判定：前面的块参考不足、后面的块正常判定，表 1 的 `judged` 与之一致；
  - 顶层 `thresholds` 和 `collecting` 取自参考块 R，R 本身未判定时也一样；`blocks` 为空时阈值为 null、样本数为 0、`collecting` 为真。
- sync 测试：开关确实传到了 `compute_states`；载荷带 `rules`。

**提交**：`feat(perps): rank perp states against the past only`

### Task 7b：O1 用在永续上，加前端

**Interfaces**
- `compute_states` 在 O1 下：forming 块不判定，也不进入参考样本；表 1 的 `latest` 和 `latest_uncovered` 取最后一个已收盘的块。
- `IMPLEMENTED["perps"]` 加入 O1。
- 前端：
  - 口径和 `rules_pending` 的显示，同 Task 1b；
  - 图 1、图 2 中没判定的块，悬停说明原因（forming、imputed、参考块不足）；
  - O6 下 Parameters 显示顶层阈值和 `n_liq`、`n_px`、`n_oi`，悬停某块时显示该块的阈值；
  - 阈值为 null 时显示 `—`。

**测试**
- 只开 O1：阈值样本不含 forming 块，forming 块不判定，`latest` 是最后一个已收盘的块；`covered_days` 仍计入 forming 块，`collecting` 按去掉 forming 块后的数量判断。
- 前端：部分判定的视图中，表 1 显示、未判定块的悬停文字、块阈值的悬停、null 阈值。

**提交**：`feat(perps): use closed blocks and show per-block thresholds`

### Task 8：核验与记录

- [ ] 运行 `make check`，并单独运行 `deploy/test/test_composition.py`。
- [ ] 按 P5-R8，用 `derive` 命令在库的两份副本上分别派生，然后比较：
  - 周期：state、since、day；
  - 价位：表 2、F 与 D；
  - 卖压：阈值、level、run、kept；
  - 永续：状态计数、`judged`。
- [ ] 浏览器核验，1440 和 390 两种宽度：
  - 口径文字与 `rules_pending`；
  - `closedAsOf`；
  - 阶梯阈值线、level/run；
  - gap 的显示；
  - 1d–1w 线和价格域说明；
  - 永续的部分判定与块阈值。
- [ ] 写 `P5-VERIFICATION.md`，然后提交。

## 评审修订记录

### v3 复核后的文字修正

| 评审意见 | 处理 |
|---|---|
| 1：O6 顶层阈值与 `collecting` 的取值是循环定义 | 改为参考块 R（最后一个块，O1 时为最后一个已收盘块），不论 R 是否被判定；`blocks` 为空时的取值；Task 7a 测试同步 |
| 2：`closed_days` 是集合，"遇错即停"的顺序没定 | 改为有序 list（C、C−1，其余由近到远）；只有 `BrkError` 算失败，返回 None 只是跳过 |
| 3：P5-R9 的"v1 数值不受影响"与方向核对不符 | P5-R9 写明状态、阈值、表 1 不变，方向核对与 `bybit_qty` 的样本范围随网格扩大；Task 7a 加断言 |
| 4：Task 1a 的测试在 `IMPLEMENTED` 全空时无法产生差异 | 测试用 monkeypatch 临时设置 `IMPLEMENTED` |
| Minor | D 为 None 时 cost-basis 的 `latest_day`；C 用本轮开始的 `at`（`_derive` 新增 `closed` 参数）；O5 域测试用 `rules={O5}`；P5-R8 先跑完整一轮再复制库；P5-R2 的重派生只对 onchain；`derive.py` 的客户端；Task 3a、5a、6 的 sync 测试；Task 4 的签名；`urpd_not_final` 的拼装路径；`max_move` 不随 O6 改；O1 下永续的 `covered_days` 与 `collecting` |

### v2 → v3

| 评审意见 | 处理 |
|---|---|
| 1：`/status` 仍会每天过期；`latest_day` 没定义 | 写出三个视图的 `latest_day` 和 levels 的 `latest_urpd_day`；`/status` 的 day1 和 urpd 都改用它们；视图不暴露 |
| 2：F 一词有两个意思，取数和保留没有锚 | 拆成 C（读数上限、取数和保留的锚）与 F（派生日期）；改为无状态的 `closed_days(at)`，候选 {C, C−1} 都保留，不再需要"上一个 F" |
| 3：只看 `all lin500` 会在切换时清空 cost-basis | `final_urpd_day` 要求 9 份都已定稿；参数改为候选日序列；`urpd_not_final` 改为不带后缀的防御性原因码 |
| 4：O1 下 `_derive` 用哪份 urpd 没写 | `_derive` 按 F 从库里读；closed 的取数不依赖 D；`_recent_urpd` 只用于 D |
| 5：C3 的细节 | 载荷存 `rules_for_view` 的结果，集合比较；重派生沿用已存 `computed_at`；`next_due` 设为 now；旧载荷的默认值；永续由首轮覆盖，`rules` 从 `StoredStates` 取 |
| 6：lin200 的域写错 | 改为 [40600, 121800]，并写明域的端点定义 |
| 7：O6 与 P4 现状不符 | 写出 `Thresholds`、`Block.thresholds`、顶层取值；`quantile_r7` 的迁移归 Task 5a；保留期与回填作为 P5-R9 无条件修改，并改 P4 SPEC；判定范围为 30 天视图内的块；imputed 的含义；`n_all` 的改名为 P5-R10 |
| 8：Task 7 没有前端且过大 | 拆成 7a（O6 后端）和 7b（永续 O1 与前端），前端覆盖部分判定 |
| 9：只派生命令没有负责的 Task | Task 1a 新建 `derive_from_store` 和 `derive.py`；Task 7a 抽出 `derive_states` 并扩展命令；Task 8 只调用 |
| 10：O2 的契约空白 | `*_levels` 取起点小时；O2 关闭时四个新值为 null；`closed_at` 可为 None；缺失的行与 null 点都中断 run；`lookback(rules)`；不变式只对样本 ≥168 的小时 |
| 11：任务规模 | Task 1、3、7 各拆成 a/b；Task 6 用内部函数分项记录 |
| Minor | `v1` 与其他代号同时出现时启动失败；perps 的 `rules` 参数在 7a 加入；补全 `model_lines`、`last_complete`、`select_components` 的签名；`closed_day` 放 `models.py`；O4 的 Episode 边界；O3 中 <1h 序列的处理；`urpd_not_final` 的前端文案；只开 O1 的永续测试；O2 的载荷体积；回滚与部署文档；O1 下 spot 的口径 |

### v1 → v2

| 评审意见 | 处理 |
|---|---|
| C1：O1 会让 day1 视图每天被判为过期 | 新增 `latest_day`，新鲜度按最新一行（含未收盘）计算 |
| C2：O1 下 URPD 的取数和清理仍以今天为锚 | 以 F 为锚取数和清理，保留上一个 F；新增 `urpd_not_final`；补抓 F 的历史日期（v3 改为 C 与 `closed_days`） |
| C3：规则标签可能与数字不符 | 载荷中存 `rules`；规则不一致时重新派生，期间显示 `rules_pending`；新字段都有默认值 |
| I1：O1 用在卖压上需要计算时刻 | 新增 `computed_at` 参数；`closed_at`；图例默认取 `closed_at` 那一行 |
| I2：O2 的定义依赖 O1 | 窗口本身不含当前小时；run 的起点与中断条件；回看 2880 小时；不变式测试 |
| I3：O3 规则不完整 | 明确"没出块"的定义、沿用哪些序列、null 腿、QC、前端显示，并写出 fixture 上的期望值 |
| I4：O4 末尾的缺失日会延长 run | 只处理中间的缺失日 |
| I5：已收盘日有两种定义 | 统一为 P5-R5 |
| I6：1d–1w 线需要接入多处 | 列出要改的各处；`LINE_ORDER` 中排最后；W 的数据来源；记录对表 2 的影响（P5-R7） |
| I7：BIC 的测试看不出差别 | 改用 v1 选 1、新公式选 2 的数据；记录黄金样本选出的 k |
| I8：O6 与 P4 冲突 | 按阈值分别统计样本；imputed 不进样本；dPx 的基准；保留期 125 天；每块带阈值；`stats.py` |
| I9：Task 的先后顺序 | 写明前提；perps 归 Task 7 |
| I10：开关的默认值互相矛盾 | P5-R4 |
| I11：前端有缺口 | `closedAsOf`；文件表补全；gap 的显示与图例的默认行 |
| I12：Task 8 的方法 | P5-R8 |
| Minor | P5-R1 的取值规则；P5-R3 的对应表；O5 价格域的精确值和说明文字；O5 的差异分三项记录；用停服空洞测试 null；未收盘行的 level；`final_urpd_day` 的约定；拆分 Task 5 |
