# P3 核验记录

日期：2026-10-16，约 20:30–20:50 UTC。分支 `claude/onchain-p3`，范围见 [PLAN-P3](PLAN-P3.md) v3。

## 1. 全量检查（`make check`）

| 项目 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy strict | 37 个源文件，无问题 |
| pytest | 393 passed（1 个 warning，是仓库原有的 Starlette/httpx 弃用提示） |
| types、frontend type-check | 通过 |
| vitest `src/features/wheelhouse` | 19 个文件，210 个测试全部通过 |

## 2. 黄金样本与独立复算

黄金样本在 2026-10-16 18:29Z 抓取。办法是本地打开已保存的原站 `state-report.html`，加载前后各抓一次 BRK，两次逐字节相同。样本已提交为 `services/analytics/tests/onchain/fixtures/brk-2026-10-16T1829Z/`。

`costbasis.py` 的结果与独立复算 `oracle_c7.py` 的全精度输出相比，三种桶宽的最大相对误差约为 4e-15；与当时的页面读数也逐项一致：
- K 的价位；
- M 的 μ（由 SVG 反推，误差 < 0.01）；
- 表 2；
- 附近价带及其标签；
- 两侧的总量与盈利占比。

## 3. 实时对照（20:39Z，`.local/research-samples/p3-live-20261016T2039Z/`）

步骤：
1. 抓取 BRK 当天的 9 份快照（A）；
2. 置空本机开发库的 `next_due`，触发一轮同步（`computed_at` 20:39:59Z）。库里 9 份快照的 buckets 和 close 与 A **逐份相同**；
3. 本地打开原站页面，读取 $500（默认）、$200、$1000 三种桶宽的读数；
4. 再抓一次 BRK（B），与 A 逐字节相同。

结果：按页面的格式化规则逐格比较 `/onchain/cost-basis` 与页面读数，**三种桶宽全部一致**。

| 项目 | $200 | $500 | $1000 |
|---|---|---|---|
| 表 2 阻力 | 86.0k / 88.0k / 96.0k / 104.0k | 同左 | 86.0k / **90.0k** / 96.0k / 104.0k |
| 表 2 支撑 | 76.0k / 74.0k / 70.0k / 64.0k | 同左 | 同左 |
| 附近价带（8 行 + spot） | 区间、n、标签、距 spot 的百分比一致 | 一致 | 一致 |
| STH 总量 / 盈利占比 | 3.66M / 63% | 3.66M / 68% | 3.66M / 62% |
| LTH 总量 / 盈利占比 | 12.78M / 59% | 12.78M / 59% | 12.78M / 59% |
| spot | $81,296 | 同左 | 同左 |

**网格**：实现采用五日并集，库里保存了 D−1、D−7、D−30、D−90 的快照（P3-R1）。同步后 urpd 表只剩 5 个日期 × 9 份，清理按 P3-R14 生效。

## 4. 浏览器核验

**1440px**
- Key levels（BTC，1h）：
  - 控件行：Cost lines、STH bands、LTH bands 三个开关，Bucket $200/$500/$1000；
  - 开关下方的图例：`STH bands · 3.66M BTC ≥$1k · 68% in profit`，`LTH bands · 12.8M BTC ≥$1k · 59% in profit`。
- 刻度轨：
  - 有 5 个 K 带（STH K2；LTH K2–K5），全部在当前价格范围内；
  - LTH 的半高全宽很宽，在 1h 视图下贯穿整个价格范围，属于规则内的正常现象；
  - 外层 svg 的 `role="group"`。
- 悬停 STH K2：主图上铺开半透明区带；读数行显示 `STH K2 · $82,250 · width $9,799 · 1.91M BTC (52.2%) · strength 100%`。
- 键盘：Tab 聚焦到 K 带，同样会铺开并出现读数；`:focus-visible` 的描边为 3px 青色。
- 5 条模型线都在价格范围之外，按 P1 规则贴底边标注，y 轴不变。
- inspector 的顺序：
  1. Cost-basis levels（表 2，注明 "the 2026-10-16 snapshot was still forming"）；
  2. Nearest occupied bands；
  3. Cost lines；
  4. Cycle；
  5. Source。
- 无横向溢出：`scrollWidth = 1440`。

**窄屏（420px）**
- 刻度轨按 `chartWidth < 600` 变成 16（lane 宽 7），viewBox 为 364。
- 控件行折行，4 个 tab 在同一行。
- 宽表格在原有的 `.wh-table-scroll`（`overflow-x: auto`）里滚动，页面本身无横向溢出。
- 说明：浏览器面板处于后台时不渲染帧（`requestAnimationFrame` 和 ResizeObserver 都不回调），viewBox 会停在 980。截图强制渲染一帧后恢复正常，所以这是环境造成的，不是代码问题。

## 5. 遗留

各 task 审查留下的 Minor 项，在终审的修复轮中统一处理，详见台账：
- 图例的下限写成了 `domain_low`；
- 桶宽不可用时的原因过滤；
- 循环 import；
- 图例行出现时的布局跳动；
- URPD 阶段失败时也要清理；
- 补充测试。
