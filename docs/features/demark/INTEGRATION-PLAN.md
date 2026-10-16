# DeMark 与市场 Phase 接入计划

日期：2026-09-27。原计划状态：待审草案。

当前进展：用户随后授权目标「完成基础版 DeMark 到当前项目」，本轮按该目标先完成基础Sequential及正式接入，见 [BASIC-SEQUENTIAL.md](BASIC-SEQUENTIAL.md) 与 [RESULTS.md](RESULTS.md)。下列Phase及全站辅助阶段仍为后续规划，不能视为全部获批或已完成。

依据：[接入约定](INTEGRATION-PROMPT.md)、[讨论记录](DESIGN-DISCUSSION.md)、[A2–A5 验收结果](../../architecture/a2-a5-results.md)。本轮读取工作区 HEAD 为 `fc07762`，实施前重新检查与 moomoo/Wheel 并行改动。

## 1. 要交付的行为

用户希望自己取得原始数据，在 Python 中正确计算 DeMark 9/13，并结合市场阶段识别趋势延续、衰竭与单边突破；结果按 Wheelhouse 自己的信息层级展示。不要求与朋友平台的所有读数完全一致，不索取朋友源码。

本计划将用户所说的 `phase` 暂按「市场阶段识别」理解，安排为首个功能切片；施工阶段统一编号 P0–P5，避免与市场 Phase 混称。此范围解释随计划一起供审阅。

本轮只形成计划和研究记录。审阅后才拆成可执行本地任务；不发布远程 issue，不修改共享入口，不因阅读接入提示而自动开始实现。

## 2. 三层职责与证据边界

| 层 | 内容 | 处理原则 |
|---|---|---|
| 经典 DeMark | Setup、Perfection、Countdown、资格、TDST、取消/recycling、Risk Level 等 | 规则来源和变体明确，以独立样本验证。经典体系本身已有趋势延续与突破资格，不能把所有突破概念归朋友原创 |
| 市场 Phase | BTC 成本线关系的六态、四成分周期指数 | 独立于 9/13 的背景；不是 DeMark 计数阶段，不改变原始计数 |
| 朋友的策略组合 | 三态中文 Regime、1h/4h 校准、突破监测、强弱与期权映射 | 先通过页面控制变量实验重建行为表；不能验证的部分保留未知，不直接沿用旧实验参数 |

官方边界：[重新核验报告](../../../research/demark-classical-boundary-2026-09-27.md)。页面实验：[2026-09-27 记录](PAGE-EXPERIMENTS-2026-09-27.md)。

特别区分：六态成本分类、0–100 周期指数、首页五档业务标签，是三个相关但尚未证明可一一映射的结果。首期自动 Phase 推荐采用六态成本分类；四成分指数和五档映射分开排期。不能从一组数值推断综合权重。

## 3. 推荐实施顺序与依赖

| 阶段 | 依赖 | 交付与完成标准 |
|---|---|---|
| P0 规则与数据证据定稿 | 计划获批 | 完成 Phase 六态条件/死区/初始态/缺失态决策表，核验原始数据字段和历史；形成 9/13 精确规则表与手算样本。可独立推进两条研究，不要求等所有辅助问题回答 |
| P1 市场 Phase 首个切片 | P0 中 Phase 规则可验证；共享整合负责人明确 | 固定原始成本样本 → Python 六态分类 → 快照/接口 → Market 页面上下文摘要；随后接同一 Adapter 的真实 BTC 数据。能显示依据、变更时间、stale/unknown、历史回放；模拟和真实分别验收 |
| P2 DeMark 单周期完整 9/13 | P0 中 DeMark 规则定稿；不依赖 Phase 数据源 | 纯计算模块、黄金样本、完整生命周期。独立公开 Interface 可验证 Setup→Countdown→资格/取消；TDST 与 Risk Level 证据可追溯，不输出买卖评分 |
| P3 正式 TD tab 接入 | P2；共享整合负责人明确 | 在现有计算/任务/快照/HTTP 链路接入单周期 DeMark；原图标注 9/13、来源线、状态、下根条件；旧 baseline 快照继续可读 |
| P4 Phase + 多周期 + 单边突破解释 | P1、P3；突破规则证据齐备 | 统一 as-of 组合各周期，明确持续/衰竭/突破候选、确认、失败及证据冲突；Phase 调整解释而不修改 9/13。先保留可解释标签，再决定是否采用强弱评分 |
| P5 补充辅助功能 | 按其真正依赖分别推进 | 周期综合指数、其他链上/波动/资金流、事件、期权观察与回测。信息不足的功能保持 unavailable；不阻塞 P1–P3 |

默认先交付 P1，P2 的规则研究可以同时推进。P1 若卡在页面无法确定的自动分类条件，只针对该决策问用户一次；不把五档手动选择包装成自动 Phase，也不顺手扩张为完整宏观数据平台。

每个接入切片都包含相应存储/接口/显示/验证；独立算法模块可先验收，但未接入前只标记「模块完成」，不标记「功能已上线」。

## 4. Phase 首期具体范围

### 输入与输出

- 输入：BTC 的 TMM、STH 成本、1D–1W 成本的历史序列，指标观察时间、取得时间、来源/定义版本、修订身份；现价只作为上下文，不能擅自替代成本关系公式。
- 页面已显示深度 `ln(1D–1W / TMM)`、价差 `ln(STH / TMM)`，但六态决策表与死区状态保持细节仍需 P0 验证。实现前必须明确零值/无效值、边界等号、死区内保持、首次状态和连续性。
- 输出建议：`phase`、`status`、`effective_at`、`known_at`、`previous_phase`、`changed_at`、来源值与关系证据、`ruleset_version`、历史完整性和问题列表。
- 三条成本线须按共同可用时间对齐；不得混合不同口径的 TMM/realized price 或把不同日期最新值拼成同日结果。对数运算明确局部精度与阈值容差，不从图上舍入值计算。
- 展示六态名称的英文版本与原因；缺数据、定义不兼容或不可判定分别说明，不填默认 phase。
- BTC 链上 Phase 只用于 BTC；不静默把它作为 ETH 或 moomoo 股票的阶段。未来允许宏观参考时另有显式关联。

### 接入约束

现有 `Dataset` 是 OHLCV，不具备三条链上成本线及其版本历史；不得把链上指标伪装成 K 线 OHLC。新增独立 `PhaseInput/PhaseResult` 模型、数据 Adapter 与指标观察/修订存储，但复用现有任务、双截止、不可变快照和 HTTP 基础设施。

建议 Phase 纯算法放在 `indicators/market_phase/`、测试在 `tests/market_phase/`；这是对原接入约定目录范围的**拟议扩展**，随本计划审阅。该模块不依赖 `demark` 计数模块。数据采集放在源 Adapter 层，由共享整合负责人接入；不能让指标内部访问网络。

P1 显示采用 Market 页面中的精简上下文摘要和可展开依据，不新增导航，也不再复制朋友的整页决策流程图。具体视觉稿在 P1 实施时验证。

## 5. DeMark 独立公开模型与 Interface

正式位置：`services/analytics/src/wheelhouse_service/indicators/demark/`；测试位置：`services/analytics/tests/demark/`。

公开入口建议 `evaluate_demark(input, config) -> DemarkResult`。`input` 可用独立不可变模型，由小 Adapter 从 `Dataset` 转换；显式携带截止时间，不读系统时钟。

| 模型 | 核心责任 |
|---|---|
| `DemarkInput` | 单一 stream、顺序 closed bars、bar/revision 引用、行情/知识截止、历史边界证据 |
| `DemarkConfig` | Sequential variant、命名规则集/版本、已验证的精确政策；Combo/relaxed/both 明确 unsupported |
| `DemarkSequence` | 稳定身份、方向、Setup/Countdown 分开、Perfection、8/13 引用、TDST/Risk 来源、当前生命周期 |
| `DemarkEvent` | 形成、完善、激活、延迟/未合格、合格、取消、失效、过期/替代的不可变发生记录；理由与 bar 引用 |
| `DemarkResult` | 序列/事件、下一根条件、bars/elapsed recency、查询范围内合格次数、输入指纹、规则版本、历史完整性 |

`Qualified 13` 的历史发生事实与「当前反转论据是否有效」分别保存；后续失效不抹去历史合格事件。Unknown 与 false/0 分开，缺少资格引用不能默认合格。

公开 Interface 拒绝乱序、重复、错误时区/周期、未来版本及不合法 OHLC；`Dataset.forming` 由 Adapter 排除，若 forming bar 混入核心 closed 输入则报错。缺口属于合法但不完整数据：切分连续段，保留前段历史、停止跨段延续推断，显式标记连续性未知。

内部只有一套逐根状态转换；批量只是顺序调用。价格使用 Decimal 精确比较，不依赖浮点 epsilon 或显示舍入。规则研究必须覆盖同根事件优先级、price flip、等号、延迟资格、反向取消和同向 recycling，不能把这些降为可忽略辅助项。

复杂度按 `O(N + Σ每根需维护的活动序列数 + 输出事件数)` 表述，不在允许多序列时假称严格 O(N)。已结束序列不再逐根更新；历史存储与计算中的活动状态分离，具体性能在样本上测量。

## 6. 黄金样本与算法验收

P0 产出独立手推逐根表：至少完整 Buy 和 Sell、一次未合格后延迟 13、一次取消/recycling；列 OHLC、引用 bar、期望事件及来源。样本期望不能由被测实现生成。第三方画面只作为差异证据，不作为唯一正确性依据。

| 验收组 | 必须覆盖 |
|---|---|
| Setup | Buy/Sell 对称、严格/相等边界、price flip、中断、起点不足、反向/同向新结构 |
| Perfection / 13 | 6/7/8/9 极值边界、延迟完善、稀疏 Countdown、Setup 9 当根、13-vs-8、反复延期、引用证据不足 |
| 生命周期 | true extremes 与跳空、TDST 取消、反向取消、同向 recycling、并存旧合格事件、Risk 失效及显式到期政策 |
| 数据 | 乱序/重复拒绝、forming 排除、缺口、截断前史、Decimal 临界价与配置改变 |
| 确定性 | 同输入相同结果、批量/逐根等价、追加未来 bars 不改已发生历史、旧知识截止隔离迟到修订 |
| Phase | 六态真值表、死区边界/初始化、缺失/不同日期/过期、非法关系、前缀无前视与修订回放 |

当前算法验收状态：**尚未实现、尚无通过结果**。A2–A5 的 23 项测试验证的是底座，不能替代本表。

## 7. 历史、预热、重算与 checkpoint

- Setup 的局部比较至少需要前四根；启用 price flip 又需前一根的比较证据。具体首个可判定位置由 P0 精确规则确认。能开始计数不等于已经知道全部历史状态。
- 稀疏 Countdown 的寿命没有可直接套用的固定窗口上限。320/1,000/10,000 根都不能证明没有窗口前的旧序列。
- 首期推荐从声明的历史锚点全量回放，标记 `complete_from_anchor`、`truncated_before_anchor` 或 `gapped` 等语义；“锚点完整”不冒充全市场历史完整。只有可信初始化状态及连续输入才允许声称跨窗口状态完整。
- 计算模块声明所需历史和不足原因；source/repository 负责分页补齐，图表显示窗口与计算历史分开。现 `Repository.read` 默认 1,000、校验上限 10,000，需独立分页/范围读取入口，保留 baseline 默认行为。
- 今天补到的旧行情只从今天起可知；旧 knowledge cutoff 仍读不到，不允许补齐后改称当时已知。
- 历史修订先保留旧 snapshot，再以新输入版本重算。首期从锚点全量重算；以后才优化为受影响 bar 之前的有效指标 checkpoint。
- 现任务 checkpoint 是批次 ID，不是算法状态。首期不新增持久化指标 checkpoint；未来若增加，必须绑定规则/配置/stream/历史前缀指纹与状态版本。修订、配置变化或截止语义不匹配即失效。
- Phase 同样需要指标观察/修订版本及 knowledge cutoff；不能仅保存当前页面的一个 phase 标签。

## 8. Rules / Analysis 与旧快照兼容方案

建议采用**可选模块配置与结果**，保留 baseline 字段：

- `Rules` 增加可选 `demark`、`market_phase` 配置（默认不启用）；每个模块自带 ruleset/版本。现 `engine_version=baseline-v1` 继续表示基础计算版本，不暗示它覆盖新增模块。
- `Analysis` 增加可空的模块结果，缺字段的旧 JSON 读为未计算；不追加伪造的 0、空信号或自动 phase。
- baseline-only 请求的哈希保持旧规范；新增模块时将配置、模块版本、所有输入引用/历史边界纳入新哈希域。简单给旧 `Rules.model_dump()` 增加 null 会改变现有哈希，必须有兼容测试。
- 含 DeMark 的新快照使用扩展指纹；Phase 增加链上输入版本列表。旧 snapshot ID/payload 不改写。
- 全局 `signal_status=not_implemented` 不能当作新模块可用性的唯一标志，改为由模块结果状态明确能力；状态接口保留 baseline 的事实，新增能力声明。
- 请求和响应结构、能力声明与前端 Zod 校验一起演进。建议使用合同版本 2 并同步宿主校验；这是 API 契约版本，旧快照仍通过兼容读取器可读。最终版本号由共享整合负责人结合 portfolio 改动统一分配。
- `workspace`、快照选择、缓存键与任务幂等需要识别分析配置，不能给 DeMark 请求返回仅含 baseline 的“最新快照”，也不能把不同 Phase 版本混用。

## 9. 共享修改清单与所有权

| 文件/位置 | 拟议改动 | 谁实施 |
|---|---|---|
| `indicators/demark/`、`tests/demark/` | 独立核心、模型、样本、验收 | 本专题获批后可做 |
| `indicators/market_phase/`、`tests/market_phase/` | 独立 Phase 核心与样本 | 新增目录范围随本计划审阅 |
| `docs/features/demark/` | 规则、计划、实验及验收记录 | 本专题 |
| `market.py` | 配置/结果、历史边界与兼容模型 | 用户指定的共享整合负责人 |
| `calculation.py` | 小 Adapter 调用、结果组合与哈希分支；不再实现计数 | 同上 |
| `sources.py` / 新指标源 Adapter | 原始成本数据与行情分页；来源语义验证 | 同上 |
| `repository.py`、migrations | 历史范围读取、Phase 观察/修订与快照引用、配置选择 | 同上；迁移号串行分配 |
| `runtime.py` | 新依赖采集/恢复、配置传递，不包含算法 | 同上 |
| `http.py`、`contracts.py` | 新配置/结果、错误、能力和合同版本 | 同上 |
| OpenAPI、`api-schema.d.ts`、`client.ts` | 生成类型与实际 Zod 运行时校验同时更新 | 同上 |
| `market-page.tsx`、`market-chart.tsx`、样式 | Phase 摘要、TD 标记/详情、缺失/过期状态、URL/缓存上下文 | 同上 |
| 宿主 patch、pyproject | 仅确有必要时变更；无理由不新增依赖 | 同上 |

不修改 `portfolio/`。不继续开发历史 `backend/`、`frontend/`。宿主新增源码落 overlay，通过 `make sync` 同步 `.local/wealthfolio`；不能直接修改忽略的 checkout 作为唯一交付。

本计划的批准不自行指定另一个会话为整合负责人；独立模块可先做，共享修改前由用户指定一个负责会话。

## 10. 交付验证与评审

以公开计算 Interface 验证算法行为；以现有 Repository/任务/HTTP 边界验证接入；避免为每个私有 helper 建镜像测试。UI 只读结果，不重复计算。

回归覆盖 fixture/公开源不混用、形成中 bar、重复/缺口、修订重放、严格双截止、旧快照、任务重启、失败恢复、新增依赖未就绪、服务失联、配置切换与旧缓存隔离。

实施时运行模块 pytest、Python lint/严格类型检查；接入切片运行相关契约测试、`make check`、`make build`。浏览器验证单图 TD 标记、Phase 依据、周期/方法切换、历史回放、错误/过期与窄屏。对 DeMark 多序列和 Phase 历史单独记录性能，不引用 SMA 的 0.0475 秒当作新算法成绩。

最终按 Standards / Spec 两轴审查。计划获批后按 P0–P5 依赖拆本地 tickets，沿用项目本地 tracker 风格，但当前不标 ready-for-agent。

每次交付分别列：独立可合入文件、待整合共享改动、实际通过测试、未验证假设。未做账户接入、期权执行或收益验证时不作相应完成声明。

## 11. 本次审阅重点

建议批准的范围：**Phase 首期采用可验证的六态成本分类，先接一条完整数据到显示链路；DeMark 独立实现正确的 9/13；之后才将二者组合成单边突破解释。** 四成分综合指数、五档映射及期权建议保留后续切片，不用猜测补齐。

需要审阅的主要选择是上述先后顺序、Phase 首期范围、以及新增独立 Phase 目录。共享文件的整合责任在实际接入前确认。当前不要求用户代查大清单：先由代理做页面实验与公开资料核验，只将仍会影响结果的最小缺口带回来。
