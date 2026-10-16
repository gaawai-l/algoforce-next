# 基础版 Sequential 实现契约

日期：2026-09-27。授权：用户当前目标「完成基础版 DeMark 到当前项目」。本文件是这次实现与验收的范围，不将此前 Phase/全站复制计划整体当作本轮完成条件。

## 已交付目标与边界

在现有 Wealthfolio Market intelligence 的 TD Sequential tab 中，显示独立 Python 计算的 Setup、Countdown、完善状态、延迟/合格13、TDST、Risk Level、历史生命周期与来源。复用 A0–A5 的数据、任务、回放、快照和 HTTP。真实与模拟数据明确区分，输入窗口前历史未知。

本版支持 crypto spot、24/7、UTC 的已支持标的/周期。Combo、朋友的市场 Phase、Regime 校准、单边突破策略、评分、期权建议与交易执行不属于基础版；它们继续保留在后续计划。经典 DeMark 自带的 TDST/取消/回收不能因此省略。

公开规则依据见 [RULE-EVIDENCE.md](RULE-EVIDENCE.md)。由于官方完整专有规则未公开，本版命名 `wheelhouse-sequential-1`，明确政策而不声称平台逐根一致。没有移植第三方代码；已核验 Python 候选缺少完整非连续 Countdown。

## 精确规则

以 Buy 为例，Sell 对称：

- 前根 `C[t-1] >= C[t-5]` 且当前 `C[t] < C[t-4]` 形成 price flip，当前为 Setup1；随后严格 `<` 连续至9，等号中断。默认必须 flip；关闭 flip 的参数明确记录。
- Setup9 收盘确认后冻结前9根 TDST。Buy 为最高 true high，Sell 为最低 true low。true high=`max(high, previous close)`，true low=`min(low, previous close)`。
- s8或s9 low严格小于s6和s7，Setup完成时完善；否则等待后续严格突破。已取消/回收的未完成Countdown停止追踪延迟完善。本版 strict perfection 与某些供应商的非严格版本不同。
- s9当根起检查 Countdown，Buy `close <= low[t-2]`，Sell `close >= high[t-2]`，不连续。完善不是启动门槛。
- 到12后，13候选同时要求 Buy `low <= d8.close` / Sell `high >= d8.close`。普通资格满足但13资格不满足时发 deferred13，接受计数保持12，状态为 `count13_unqualified`，图上 `+`。不伪造已合格13。
- 可选8-vs-5关闭；变体与参数记录在结果中。
- 反向 Setup9取消旧未完成 Countdown；Buy true low严格高于TDST / Sell true high严格低于TDST同样取消。可配置 close-only，但明确属于不同政策。
- 同向后续 Setup9首九根 true-high/true-low 范围为旧来源 Setup 的100%–200%（含端点，旧range>0）时回收旧未完成 Countdown。否则二者可并存，这是本版明确选择。
- 同向**后续**连续Setup run达到22时回收较早的同向未完成 Countdown；原来源 run自身到22不自我回收。新序列从自己的Setup9正常追踪，不在回收时回写过去事件。各轮旧13的历史资格永久保留。
- 同根先更新Setup、处理相反/同向结构取消回收，再TDST检查、完善、Countdown；取消优先于当根13候选。每序列每bar最多计数一次。
- Risk：d1至d13全跨度（含未计数bar），选最低true low/最高true high，向外扩展该bar true range；并列取最早bar。此扫描与并列政策明确为Wheelhouse选择，不冒充完整官方专有公式。
- 默认收盘严格穿Risk线使当前论据失效，等号不失效；可选true-extreme整根确认。历史qualified13不改写。默认无自动TTL，可显式配置到期bar数；官方12-bar metric不机械当作过期规则。

## 公开 Interface 与状态

`evaluate_demark(dataset, config) -> DemarkResult` 是批量入口，`SequentialSession(...).advance(stored_bar)` 是相同转换逻辑的增量接口。没有持久化算法checkpoint，不访问网络/数据库/系统时间。调用者提供行情与知识截止。

输入拒绝乱序、重复ID/时间、forming混入closed、错误周期网格、不合法OHLC、未来/尚未取得版本。独立forming列表不计入。缺口后记录continuity_lost，停止跨缺口延续；缺口前历史保留，旧风险有效性变unknown。缺口不会伪造已证明的取消。

`setup_status` 与 `countdown_status` 分开；历史qualified13与 `risk_status` 分开。bar8、确认价/时间、TDST和Risk来源、每次事件、下根条件、bars及elapsed recency均可追溯。elapsed以当前最后closed bar为参照；有缺口时bar距离只指观测bar数量，并显示不完整。

价格计算采用局部80位Decimal，不依赖调用方上下文、不以tick或显示位数猜测epsilon。图表可以将价格转显示坐标，但阈值明细保留完整十进制原文。

## 接入与兼容

- `Rules.demark` 可选，未启用时baseline-only；`Analysis.demark` 可空，旧snapshot读回时明确未计算。
- 默认UI刷新同时请求baseline与命名Sequential结果；HTTP API仍可发baseline-only。TD tab不从SMA或旧快照编造计数。
- baseline-only哈希沿用原规则序列化（不添加demark=null）；启用时加入完整DeMark输入指纹与配置。输入修订改变产生新快照，旧payload不覆盖。
- 本次为向后兼容的可选字段扩展，合同版本仍1，能力增加 `demark_sequential_basic`；宿主生成类型与运行时schema同步。旧服务缺少新字段时新版客户端会明确报告不兼容，而非展示虚假成功。
- DeMark任务读取全部已存且符合双截止的历史，不沿用最近1000根截断；baseline仍保留默认1000根。公开行情初次仍取得既有320根窗口，不宣称全历史完整；结果恒明确window_only/gapped/empty。
- 不自动下载过去尚未知的数据来填旧知识截止。用户刷新与既有摄取可追加历史，历史修订从已存锚点全量重算。采集batch checkpoint继续沿用，恢复不重下已取得批次。
- 现有单图中B9/S9为完成Setup，B13/S13为合格Countdown，B+/S+为延期；选定序列详情与价格线联动，历史有效性、旧风险价格和事件分开显示。
- `signal_status=not_implemented` 仍指全局交易策略层；DeMark可用性取模块status与能力，不能把计数候选当自动交易信号。

## 验收表

通过公开计算、Repository、任务、HTTP验证：Buy/Sell镜像、flip/等号、中断、完善/延期、稀疏Countdown、13引用和延期、TDST true-extreme、反向取消、range100/200边界及后续22回收、Risk未计数极值及并列、失效/TTL、缺口、重复/未来/形成中、Decimal、前缀不改历史、逐根与批量一致、修订与旧snapshot、1000根外旧13、任务checkpoint恢复、Combo拒绝。

浏览器须核验fixture与公开数据、刷新、序列选择、历史事件、TD与Key levels切换、周期切换、回放及窄屏。最终检查结果记录在 RESULTS.md，未记录通过的项目不能宣称完成。

## v2 对照配置补充（2026-09-27）

用户导出的TradingSignal500根样本显示：同向新Setup不满足回收时保留原Countdown，不额外启动；完善状态仅在Setup9当根确认。新增`same_side_policy=retain_active`与`perfection_policy=strict_at_nine`，配合`wheelhouse-sequential-2`供UI默认刷新使用。v1原规则与旧快照保留。v2下后续run22回收时被压制的新Countdown从当前bar开始激活，不追认过去事件。

此更新修正参考平台对齐行为，不改写经典规则来源。该样本561标记全匹配，详见 [EXPORTED-ALIGNMENT-RESULTS.md](EXPORTED-ALIGNMENT-RESULTS.md)。
