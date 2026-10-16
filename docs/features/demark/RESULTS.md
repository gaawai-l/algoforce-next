# 基础版 DeMark 验收结果

日期：2026-09-27。对应用户目标：**完成基础版 DeMark 到当前项目**。本次验收以 [BASIC-SEQUENTIAL.md](BASIC-SEQUENTIAL.md) 为准；Phase、朋友的突破策略和期权辅助功能仍属后续计划。

## 实现与真实接入

- 正式 Python 纯计算模块：`services/analytics/src/wheelhouse_service/indicators/demark/`。
- 独立黄金样本：[GOLDEN-SAMPLES.md](GOLDEN-SAMPLES.md)；来源及公开规则缺口：[RULE-EVIDENCE.md](RULE-EVIDENCE.md)。
- `Rules.demark` / `Analysis.demark` 接入现有 calculate、Runtime、Repository、HTTP、OpenAPI、宿主生成类型与 Zod 校验。
- TD tab 已显示真实计算的 Buy/Sell Setup、非连续 Countdown、完善状态、延期13、合格13、TDST、Risk、历史事件、来源引用、下一根条件及时间距离。
- 历史资格与当前风险有效性分开。旧 baseline-only 快照继续可读，图表与详情均显示「未计算」，不伪造0或无事件。
- 全量与逐根共享 SequentialSession.advance；DeMark任务读取全部已存选定历史，baseline保留原1000根默认。没有隐式历史补齐或跨知识截止借用修订。

## 实际命令

2026-09-27 本机 `.venv-foundation` Python 3.14.6：

| 验证 | 结果 |
|---|---|
| `python -m pytest services/analytics/tests/demark -q` | 24项通过 |
| `make check` | Python lint、严格类型检查通过；当次全套65项通过；宿主类型检查与5项客户端/图表测试通过 |
| `make build` | 完整宿主Web构建通过；最新日志 `built in 8.50s` |
| 两轴代码审查 | 初审3项P2均修复，限定复核无未解决P1/P2 |
| `git diff --check`（本功能范围） | 通过 |

全套65项含并行portfolio工作区的测试，不把它们当作本功能新增测试。现有Starlette/httpx弃用提示、npmrc变量提示以及上游sourcemap/大chunk构建提示仍存在，未阻止检查/构建。没有远端CI或部署声明。

本机完整检查/构建日志：`.local/demark-verification/check.log`、`build.log`，不提交生成目录。

## 逐项功能证据

| 要求 | 权威证据 |
|---|---|
| Buy/Sell 9与13正确、各自资格和引用分离 | `test_sequential.py` 的手算Buy、Sell镜像、deferred13、资格等号案例 |
| price flip、相等中断、严格perfection及延迟 | 对应接口测试；引用作者一手2005文章与当前官方规则 |
| TDST true extremes及close变体 | 跳空首根不能取消/后续确认、close-policy对照测试 |
| 反向取消、同向range和后续22回收 | 首9范围100%/200%/超过200%、原run22不自回收、后续run22测试 |
| Risk极值、未计数bar、并列、失效与过期 | 风险76/124黄金值、未计数极值45、严格等号、显式TTL、true-extreme风险政策 |
| 缺口/重复/未来/形成中/Decimal | 公开evaluate输入测试；缺口不伪造取消；调用方低Decimal精度不改变结果 |
| 批量/逐根一致、前缀无前视 | 每次advance的result与同前缀evaluate一致，过去事件前缀不变 |
| 修订、双截止及旧snapshot | `test_demark_integration.py` 修改历史bar后新结果变化、旧snapshot及旧knowledge结果不变 |
| 长寿命历史不被1000根截断 | 1031根任务仍保留b25的旧13；baseline读取仍返回1000根 |
| 任务重启恢复与HTTP | 持久化batch checkpoint恢复不再采集；HTTP回读同一DeMark结果；Combo请求422 |
| 多序列保留 | 实际公开1h快照同时展示forming Sell与多个历史有效Buy/Sell13 |
| 前端缺失态/缩窗对齐 | 两项market-chart.test.tsx回归测试及浏览器旧snapshot验证 |
| 只读与原有功能兼容 | 既有HTTP/任务/来源测试、Key levels浏览器回归；未增加交易执行 |

## 浏览器证据

访问现有 Wealthfolio 同源路由：
`http://127.0.0.1:1420/market-intelligence?source=binance&symbol=BTCUSDT&timeframe=1h&method=td`

本轮实际操作并观察：

1. fixture刷新：320根，SIMULATED，图上9/13与后台结果一致，保留3次历史合格13。
2. 选择结束序列：旧Sell13仍显示历史资格，但Risk invalidated且不绘制有效风险线，历史风险值可展开查看。
3. Binance 1h刷新：324根已收盘，形成中bar单列排除，PUBLIC SPOT / FRESH。所选Buy序列于2026-09-25 22:00 UTC合格，门槛84226.16，Risk82006.43；这些仅为验收快照，不是持续行情建议。
4. 回放至2026-09-25 21:00 UTC：303根，所选同一Buy序列回到12/13，合格时间/确认价/Risk均未生成；下根基础条件与13资格分别显示。
5. 切回baseline旧快照：图表显示DeMark not calculated，详情要求刷新/回放；没有无事件误报。
6. Key levels与TD方法切换可用。Binance 4h刷新成功，319根，TD页能显示当前Countdown4；回到1h恢复对应数据。
7. 390px页面 `scrollWidth == innerWidth == 390`；图表viewBox跟随宽度为326，标记保持可读，底部日期简化后无重叠。随后恢复默认视口。
8. TDST从Setup9确认时点开始，Risk从qualified13确认时点开始；取消/回收后的TDST按终止时点截断，不把未来线画到过去。

截图：`.local/demark-verification/desktop.png`、`mobile.png`。桌面预览保留在应用内浏览器。

## 审查修复

Standards轴：旧快照无事件误报；缩小图表窗口后事件选择与OHLC不一致。均已修复并添加前端回归测试。

Spec轴：已合格但风险失效、尚未完善的序列跨缺口继续完善。已扩大continuity_lost覆盖范围，保留先前已证明的失效事实，增加独立公开接口回归测试。

后续复核：上述问题及图表确认时点/ResizeObserver变化未发现未解决P1/P2。

## 性能与边界

本机纯计算、合成连续OHLC、含多轮序列：1000根81序列1247事件约0.0337秒；10000根812序列12633事件约0.8476秒。记录在 `.local/demark-verification/performance.json`。不含网络/数据库/UI时间，不代表无限历史容量保证。

当前算法仍标注输入起点之前历史未知，不能把320根或全部已存历史等同于全市场历史。Risk扫描与并列、recycling端点/并存和收盘风险失效采用公开声明的Wheelhouse规则版本，不保证与某个专有平台逐根一致。

本次没有改写朋友的Phase/Regime含义，也没有将它们混入9/13计算。没有发布站点、执行交易或提交账户数据。

## 2026-09-27 空白周期修复

用户切换周期后出现0根和无快照。检查发现各stream分别存储，部分周期尚未采集，旧页面只读取已有快照而不自动初始化；5m的旧公开快照也没有DeMark结果。

新增首次加载hook：取得workspace后，对当前stream缺失行情、缺少DeMark或过期结果自动刷新一次；回放、已有活动任务、服务离线及错误状态不自动重试。空白区增加加载进度与手动加载按钮；未指定来源时默认Binance，显式fixture仍保留模拟标记。

已通过真实任务更新BTC五周期，5m618、15m319、1h344、4h324、1d319根，全部DeMark ready。另用ETH15m验证无需点击刷新即可从空白进入319根和可用计数。数据量为当次快照，之后会变化。

前端type-check通过；首次加载的单次执行/多stream/轮询不重复提交回归测试通过。浏览器实际验证5m图表与ETH15m自动加载。截图 `.local/demark-verification/5m-loaded.png`。

## TradingSignal导出同输入回归（2026-09-27）

收到用户两份完整JSON后，确认原并存政策额外产生2个13。新增v2 retain_active/strict_at_nine配置后，500根561标记全匹配、499根closed前缀560标记全匹配；4个13时间、Risk价格与失效时间匹配。DeMark专项29项通过。完整检查当次81项Python及9项前端测试通过（含并行功能）；限定审查发现的22回收激活问题已修复并复核。具体证据与限制见 [EXPORTED-ALIGNMENT-RESULTS.md](EXPORTED-ALIGNMENT-RESULTS.md)。不同实际行情源与forming显示尚未视为一致。

## 2026-09-28 旧运行服务导致页面空白修复

用户原链接 `http://127.0.0.1:1420/market-intelligence?timeframe=15m&method=td` 空白。实际workspace有321根K线，但存活的旧Python进程返回的v1配置缺少新加same_side_policy，新前端Zod拒绝整份workspace，继而禁用自动刷新；此前只验证新源码进程的测试未覆盖旧运行实例。

通过公开getWorkspace客户端测试复现：旧v1返回导致incompatible。新增仅对已知v1缺失字段恢复其历史parallel语义的兼容读取；v2缺字段仍拒绝，不默认猜政策。页面显示实际接口错误原因。5项客户端测试与前端type-check通过。

检查当前任务无活动市场job后，正常终止旧本地Python服务并启动新源码服务，保留数据库。真实浏览器打开并刷新用户原链接，自动刷新成功，325根15m已收盘、DeMark v2、fresh，图上S9/S13可见，当前Buy Setup7。截图`.local/demark-verification/15m-runtime-fixed.png`。这是当次快照，不表示与TradingSignal实时行情源已一致。

## 2026-09-28 图表优先布局

用户要求参考TradingSignal占比，让左图成为重点。实际查看参考页后，压缩顶部状态/控件留白，成功任务不常驻占用首屏；桌面约79%图表/21%辅助栏，取消1480px内容宽度上限。图表高度随视口调整且SVG坐标同步高度，侧栏独立滚动，说明与行情时间折叠。移动端详情置于图表下方。

验证1440×1000与390×844：宽屏图表区域约1017px、侧栏270px，图高700px；窄屏无页面横向溢出，切换可见bar数正常。恢复默认视口后保存 `.local/demark-verification/chart-first-layout.png`。前端type-check与2项图表回归测试通过；不涉及算法或数据源修改。

## 2026-09-28 标记颜色与收盘刷新

用户反馈9/13颜色不易区分，S9/S13出现慢并询问缓存。调整标记与图例：Setup9浅蓝`#8fcaff`，qualified13金黄`#ffcf66`，延期+紫色；B/S文字与上下位置保留方向信息。标记加粗，事件按bar建立React memo索引，避免鼠标移动时对每根K线反复扫描全部事件。

诊断实测：已有workspace快照读取13–38ms；真实15m刷新任务约1288ms，采集完成到快照保存约24ms。已有SQLite行情/快照缓存及React Query内存缓存；不可变历史snapshot设置staleTime Infinity。没有用这组数字声称网络延迟恒定。

发现原页面只首次自动刷新，且这组周期后台schedule均未启用，收盘后可能继续显示旧结果。新增页面可见时的收盘边界刷新：expected_next_close后2秒请求一次，工作区重复轮询不重复提交，隐藏/卸载/历史回放不启动，回到前台补一次。后台已启用调度时不再重复触发前台任务。原持久化调度开关改名Keep refreshing in background，前台自动更新另有明确文案。

用假的时钟在公开hook边界验证收盘前不触发、收盘后一次、下一根继续、禁用/回放不触发、后台隐藏不触发与回前台补齐、卸载清理；新逻辑前先复现失败，后5项刷新/图表测试通过，前端type-check通过。实际浏览器显示S9浅蓝、S13金黄及前台更新提示，数据326根；截图`.local/demark-verification/marker-colors-refresh.png`。

算法仍只确认已收盘K线。TradingSignal的形成中bar预览可能更早变化，不将尚未收盘的9/13提前写成已确认事件。

## 2026-09-28 时间范围扩展

已将公开源单次获取扩展为500根，图表可显示500/全部缓存，加入自动密度、近7天、周五窗口和底部区间拖动。显示范围只操作本地缓存，不改变DeMark计算范围。参考核验与验收见 [CHART-TIME-RANGE.md](../ui/CHART-TIME-RANGE.md)。
