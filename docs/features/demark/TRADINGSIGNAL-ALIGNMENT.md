# TradingSignal 15m 数据源与对照核查

日期：2026-09-27。用户最新验收优先级：先与 TradingSignal BTC/USDT、15m、Sequential 一致，再处理 AlphaBTC 的辅助解释。当前状态：**来源核验完成一侧，对齐未完成**。

## 本地来源：已证实为 Binance 现货

`sources.py` 的 BinanceSource 直接调用 `https://data-api.binance.vision/api/v3/klines`，symbol=BTCUSDT、interval=15m。没有通过 TradingSignal 转取数据，也没有失败后回退Bybit或模拟源。

抽查本地选定快照最后20根，用相同开收盘区间重新从该Binance端点读取，OHLC逐字段Decimal比较无差异。证据 `.local/demark-verification/tradingsignal/binance-20bar-check.json`。不是仅凭UI写着Binance认定来源。

## TradingSignal：页面请求和返回已观察

用户URL首次加载可能短暂显示默认4h，因此已显式点击15m与TD序列，确认页面标题BTC/USDT · 15m · TD序列。

公开前端和真实浏览器Network均显示：

- K线：`/api/klines?symbol=BTC%2FUSDT&timeframe=15m&limit=500`。
- TD：`/api/methods?symbol=BTC%2FUSDT&timeframe=15m&method=td9`。
- 跨周期：`/api/methods?symbol=BTC%2FUSDT&method=td9&across=1`。

正常网页TD响应200，已读到symbol、timeframe、method、count=500、result.mode=sequential及部分markers。独立脚本调用其API返回api_key_required；没有伪造浏览器请求头、转移凭据或绕过认证。

尚未完整取得TradingSignal的实际OHLC响应/provider字段，因此不能证明这批行情来自Binance还是备选源，也不能宣称双方输入相同。站点先前公开介绍Binance不可达会切Bybit，但具体本次来源仍待证据。

## 已得到的差异证据

| 检查 | 观察 | 结论边界 |
|---|---|---|
| 历史窗口 | 对方响应count500；我们首次请求320，之后追加已存历史 | 当前历史合格次数不能直接拿不同窗口对比 |
| 窗口起始Setup | 已捕获47个独立Setup标记；与匹配时间段Binance计算，默认flip策略44个匹配，起点前三个缺少；关闭flip该47个全部匹配 | 仅覆盖Setup，未取得对方OHLC；只说明初始化政策可能不同，不证明13一致 |
| 15m快照约22:56 UTC+8 | TradingSignal Buy Setup3、TDST83830.40、距9为64根、距13为52根、历史13为4 | 保存的是当时页面读数，不能与后来动态读数混用 |
| 本地同一推定起点、500根Binance诊断 | 截止15:00 UTC：Buy Setup3、TDST83838、距9为64根、历史合格13为6 | 源数据未证实相同；价格与历史13均有差异，不可仅调参数凑数 |
| 收盘口径 | TradingSignal在15:00 UTC之前已展示包含14:45那根的Setup3，本地只收盘时为2 | 强烈提示对方含形成中bar，但仍需原始响应确认，不能把其“形成中的趋势”checkbox当证据 |

重复的AX正文已按marker id去重，实际47个而不是94个。样本没有9或13完成事件，不把47个Setup匹配说成全算法通过。

## 对照工具

新增 `scripts/verification/compare_tradingsignal.py`：离线读取Binance原始K线JSON与正常导出的TradingSignal TD JSON，显式指定收盘截止，输出同时间数字Setup/Countdown标记差异、local-only标记与快照摘要。脚本不请求TradingSignal、不读取浏览器凭据、不作为生产计算依赖。

已运行部分样本：499根closed输入，47个Setup参考标记，默认配置44个匹配、3个窗口起点差异。参考是部分样本，所以local-only数量不是完整错误数。证据存 `.local/demark-verification/tradingsignal/diagnostic-report.json`。

## 未完成条件与下一步

需要一份可合法完整读取的同次15m K线与TD响应（含来源、时间和完整序列），才能判断数据源差异与算法差异。最小外部输入可以是作者/用户导出的这两个JSON，不需要源码；或已有授权的开发者API访问。

在这之前不修改生产规则以贴合猜测。取得样本后先逐字段对齐OHLC，再固定历史起点与closed/forming口径，最后核验13启动、资格、回收/取消和Risk，并将差异形成独立回归样本。

本次完整文本提取尝试在临时data页面被浏览器安全策略拒绝，未继续从该页面提取或改用其他方式绕过；目前使用的部分样本来自拒绝前已合法取得的页面可见记录。

## 后续：完整导出已收到

用户已提供两份JSON；完整同输入验收见 [EXPORTED-ALIGNMENT-RESULTS.md](EXPORTED-ALIGNMENT-RESULTS.md)。此前缺少完整样本的阻塞已解除。原算法多出的2个13已定位为同向Countdown并存政策；v2配置在此样本561/561标记全部匹配。实际行情供应商和形成中展示仍独立处理，不把单样本通过扩写为实时全场景一致。
