# P2 核验记录

日期：2026-10-16，约 18:25–18:50 UTC。分支 `claude/onchain-p2`，范围见 [PLAN-P2](PLAN-P2.md)。

## 1. 全量检查（`make check`）

| 项目 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy strict | 36 个源文件，无问题 |
| pytest | 332 passed |
| types、frontend type-check | 通过 |
| vitest `src/features/wheelhouse` | 17 个文件，152 个测试全部通过 |

pytest 有 1 个 warning，是仓库原有的 Starlette/httpx 弃用提示，与 P2 无关。

## 2. 本地服务

- 用分支代码重启 Python 服务（:8787）；`make sync` 后重启 Vite（:1420）。
- 旧进程上一轮同步把 `next_due` 记为 19:12。为了立刻取 hour1，把本机开发库 `.local/analytics/onchain.sqlite` 的 `next_due` 置空，worker 随即同步。
- 同步结果：
  - `last_success_at` 为 18:41:08Z；
  - day1、URPD、hour1 都是 fresh；
  - hour1 最后一行 18:00；
  - `reasons` 为空。

## 3. 与原站对照（裁定 P2-X4、P2-X5）

原站会话已过期，代理不输入密码。改为在 `127.0.0.1:8899` 打开已保存的原站页面 `onchain-seller.html`（2026-10-16 保存，与线上同一份代码），页面照常实时请求 bitview.space。

每次对照前后各抓一次 BRK 数据。两次抓取中，每条 hour1 序列的最后两行都相同，说明页面用的就是这份数据。

**黄金样本**（18:28Z，`.local/research-samples/p2-golden-20261016T1828Z/`）

| 读数 | 原站页面 | compute.py | `pressure.py` |
|---|---|---|---|
| Data | 18:00 UTC | 18:00 | `last_at` 18:00 |
| LTH loss | $85.2k | $0.085M | 85200.0 |
| STH loss | $17.2M | $17.162M | 17162200.0 |
| 图 1 P95 / P75 | $37.6M / $9.39M | $37.590M / $9.387M | 37589550.0 / 9386875.0，n 716 |
| 图 2 当前 | 88.2% | 88.22% | 0.88217122 |
| 图 2 P95 / P75 | 56.1% / 22.0% | 56.12% / 22.03% | 0.56119760 / 0.22025205 |
| 图 3 当前 | 35.4% | 35.43% | 0.35428932 |
| 图 3 P95 / P75 | 36.5% / 26.1% | 36.52% / 26.11% | 0.36524741 / 0.26110941 |
| kept / xgap | — | 2577 / 0 | 2577 / 0 |

**接口实时对照**（18:41Z，`p2-live-20261016T1841Z/`）
- `/onchain/seller-pressure` 由 worker 在 18:41 计算，`forming_at` 为 18:00。
- 同一时刻原站页面的读数、compute.py 的复算与接口三方一致：

| 读数 | 原站页面 | 接口 |
|---|---|---|
| LTH loss | $252k | 252400.0 |
| STH loss | $17.9M | 17944300.0 |
| 图 2 当前 | 64.5% | 0.64471311 |
| 图 3 当前 | 34.7% | 0.34718246 |
| 价格 | $81.3k | 81268.49 |
| 三张图的 P95 / P75 | 与黄金样本相同 | 与黄金样本相同 |

结论：在页面显示精度内逐项一致；与独立复算全精度一致。

## 4. 浏览器核验

**1440px**
- Flows → Seller pressure：三张图上下排列，默认 30d。
- 页头：`Resolution 1h · Data 2026-10-16 18:00 UTC · Source Bitcoin Research Kit · includes the forming hour`。
- 每张图都有 Extreme/Warning 数值、图例当前值、右侧价格轴，以及三段说明（全部展开，不在 `<details>` 中）。
- forming 点各 1 个。
- 键盘：聚焦图 1 后按 3 次左方向键，读数移到 15:00；焦点框为 2px 青色实线（`:focus-visible`）。
- 中英文切换正常。

**390px**
- 无横向溢出：`scrollWidth = 390`。
- 4 个 tab 在同一行。
- 三段说明上下排列。
- 坐标轴文字没有越出 svg。task 审查曾担心窄屏会截断，实测没有。
- 控制台无错误。

## 5. 遗留与说明

- 阈值金额按计划写成 1 位小数（`$9.4M`），原站用 3 位有效数字（`$9.39M`）。两者都是同一个数值，v1 要照原站界面，在最终评审的修订中改为 3 位有效数字。
- task 审查留下的 Minor 项，记在台账中，由最终评审统一处理：
  - stale 时的 forming 文案；
  - "last update" 实际传入的是 `last_at`；
  - svg 的 `role`；
  - `n` 只在 title 中显示；
  - 文件体量。
