# 市场分析实验稿（历史技术验证）

此文记录早期独立应用实验，后续架构已改为 [Wealthfolio 宿主 + Python](../architecture/wealthfolio-python.md)。以下参数和业务实现尚未作为正式阶段验收，`make dev` 不加载此实验。

日期：2026-09-26。来源：`prototypes/wheel-dashboard/MARKET-STRATEGY-SPEC.md` v1.0。

## 技术选型与集成边界

采用独立 Python 分析包、FastAPI、SQLite 和 React/TypeScript 客户端。前端复用原型的 `app-shell.js`、`app-shell.css` 与本地字体。保留原型供对照；原型持仓页面仍是模拟数据。

2026-09-26 读取 Wealthfolio v3.8.0 官方源码与文档，确认：

- `packages/addon-sdk/src/types.ts` 提供 `router.add`、`sidebar.addItem` 和 React component 路由。
- `packages/addon-sdk/src/host-api.ts` 提供 `portfolio.getHoldings` 与 `network.request`。
- `docs/addons/addon-architecture.md` 明确 addon 在 opaque-origin iframe 中运行，网络和持仓能力均经过权限桥接。

证据地址均以 `https://github.com/wealthfolio/wealthfolio/blob/v3.8.0/` 为前缀。以上是静态源码核验，不是安装测试；未验证宿主网络桥对 loopback 的具体限制和 Python 服务生命周期。当前交付独立伴随应用，保留可复用的 HTTP 契约，不声称已接通 Wealthfolio 或 moomoo。

## 已授权的测试边界

用户接受技术方案后，以公开的 `analyze` / `replay` 接口验证状态转换、历史回放、重复输入和多周期对齐；以存储公开接口验证幂等持久化；以 HTTP 接口验证缺失/过期数据、输入校验和只读边界。测试预期来自独立构造的逐根 K 线案例和原规格，不复制内部算法。

## 本地 Sequential 变体

规则 ID：`wheelhouse-sequential-v1`。这是显式定义的研究变体，未声称复制 DeMARK 专有实现或 TradingSignal 输出。

- Setup：连续 9 根 close 严格低于/高于 4 根前 close。相等默认中断；可配置允许相等。
- Price flip 默认不要求；开启时要求前一根不满足、当前满足比较条件。
- Perfection：buy 的第 8 或 9 根 low 不高于第 6、7 根 low；sell 对称。允许第 9 根后延迟完善。
- 完成 Setup 的当根可参与 Countdown。buy close ≤ 两根前 low；sell close ≥ 两根前 high；非连续累计。
- 13 候选须 buy low ≤ Countdown 第 8 根 close，sell high ≥ 第 8 根 close；否则保留 `count13_unqualified` 并等待后续满足两项条件的 K 线。
- TDST：buy 为 Setup 九根的最高 true high（max(high, previous close)），sell 为最低 true low。默认整个 candle 越过边界才取消尚未完成的 Countdown；可配置 close-only。
- Risk：buy 使用从 Setup 起至 qualified13 的最低 low 减该极值 bar 的 true range；sell 使用最高 high 加 true range。默认 close 越过即失效。
- 已完成的同向序列继续独立保留；默认同向新 Setup 并存，不自动 recycling。可配置新同向 Setup 完成时取消旧 active Countdown。反向 Setup 9 默认取消未完成 Countdown。
- 有效期默认 qualified13 后 24 根当前周期 K 线。失效、取消和过期均保存状态转换，不能恢复为有效。
- 同时保存规则参数、版本、provider、session、timezone；Combo 不支持并返回明确错误。

## 突破与多周期规则

滚动边界仅使用当前 bar 之前的窗口，默认 20 根。突破触发后冻结边界，后续确认/失败始终对照同一边界。默认最小 tick buffer 是调用配置，而非跨资产通用报价精度。

ATR 使用 Wilder 14；RV 使用 20 根 log return 的样本标准差（每 bar 单位，不年化）；布林带宽使用 20 根总体标准差、上下 2σ。百分位只使用当前及过去最多 100 个已完成值，至少 20 个值才有效。成交量 z-score 对照此前 20 根，标准差为零时保持 unavailable。

确认至少需要三个独立证据家族，并且必须有价格接受；高分不能绕过家族门槛。缺失 OI、funding、CVD 和链上成本时不伪造对应证据。Regime Plus 只能输出输入支持的分类。

每个周期分别计算，截至同一 `as_of` 只消费已收盘且当时已经取得的输入；不对更大周期使用尚未收盘的 bar。1D/4h 定义战略/主方向，1h/15m/5m 定义 setup/confirmation/execution；不能按票数决定方向。

## 首次运行与能力边界

默认使用固定历史时间的合成 OHLCV，界面明确显示 Simulated / Historical replay，指标由 Python 实算。可选择公开现货行情；失败显示错误，不降级成伪实时演示。账户、链上成本、订单簿、OI、真实期权链未接入。期权输出是通用分析注释，真实持仓、Greeks、流动性和保证金缺失时不能标为账户建议。

历史回放用于验证确定性和状态转换，不等于含费用、滑点、执行规则的收益回测；不展示胜率或校准概率。
