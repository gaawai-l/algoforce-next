# P1 核验记录

日期：2026-10-16，约 15:25–15:45 UTC。分支 `claude/btc-onchain-perp`，范围见 [PLAN-P1](PLAN-P1.md)。

## 1. 全量检查（`make check`）

| 项目 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy strict | 35 个源文件，无问题 |
| pytest | 262 passed |
| types、frontend type-check | 通过 |
| vitest `src/features/wheelhouse` | 16 个文件，104 个测试全部通过 |

pytest 有 1 个 warning，是仓库原有的 Starlette/httpx 弃用提示，与 P1 无关。

## 2. 本地服务

开始时三个本地服务中只有两个在跑，而且都是 2026-09 遗留的孤儿进程，代码是 P1 之前的版本：
- Python 服务：pid 31743，已运行 18 天；
- Vite：进程组 45069，已运行 20 天，文件监听已经失效，`client.ts` 一直按旧的时间戳提供，页面报错 `does not provide an export named 'usd'`。

Wealthfolio 容器（:8088）没有运行。

处理：按 `make dev` 的方式逐个重启，环境变量与之相同。
- `docker compose up -d --no-recreate wealthfolio`；
- 用分支代码重启 Python（`WHEELHOUSE_PORT=8787`）；
- 重启 `pnpm --filter frontend dev`（`WF_ENABLE_VITE_PROXY=true`，`VITE_DEV_PORT=1420`，接口代理指向 8088 和 8787）。

`.local/wealthfolio` 中有一行宿主补丁与已提交的补丁不一致（`href` 少了 `?method=td`），已按已提交的补丁对齐，之后 `foundation.py sync` 通过。

## 3. 接口与数值

worker 首次同步用时 2.8 秒，BRK 版本 0.12.2，day1 与 URPD 都是 fresh。

**`/onchain/cycle`**
- `breakout`，自 2026-09-23 起，第 24 天，共 48 次切换，49 个分段；
- `forming_at` 为 2026-10-16T00:00Z（含今日未收盘值）；
- 三个分量都支持当前状态：

| 分量 | 当前值 | 死区 |
|---|---|---|
| depth | +6.09 | 7.00 |
| pvs | +10.03 | 6.80 |
| spread | −3.95 | 1.25 |

**`/onchain/levels`**：5 条模型线与 BRK 2026-10-16 最后一行（位置 6497）逐一相等。

| 模型线 | 本服务 | BRK 最后一行 |
|---|---|---|
| True mean | 77,482.32 | 77,482.32 |
| Short-term | 74,484.59 | 74,484.59 |
| Average | 53,846.21 | 53,846.21 |
| Long-term | 49,242.75 | 49,242.75 |
| Median（由 `all` lin500 URPD 计算） | 63,725.35 | — |

**与原站对照**：在已登录的 Edge 中读取 alpha-vol onchain-seller 页头，显示 "Breakout · since 23 Sep 2026 · day 24"，与本服务一致。

## 4. 浏览器核验（内置浏览器）

| 场景 | 结果 |
|---|---|
| 1440px，BTC，Key levels | 通过 |
| 点击页头徽章 | 通过 |
| Flows | 通过 |
| ETH | 通过 |
| 390px | 通过 |

各场景的具体检查点：
- **1440px，BTC，Key levels**：
  - 页头徽章为"周期 · 突破 · 第 24 天 自 9月23日 起 含今日（形成中）"；
  - 4 个方法 tab；
  - 图上 3 条在价格范围内的虚线标签在绘图区内，下沿贴边标注"↓ 平均成本 $53,846 · 长期成本 $49,243"，没有改变 y 轴；
  - inspector 中有成本模型线、周期（含三个分量和死区）、来源（"Bitcoin Research Kit · bitview.space · BRK 0.12.2 · 截至 2026-10-16 UTC"，以及 oracle 价格说明和 STH (<150d)）；
  - 无横向溢出；
  - 在新开标签页中，控制台无错误。
- **点击页头徽章**：从 TD tab 点击后，切到 Key levels，`#wh-onchain-cycle` 进入视口（top 92px）并展开。
- **Flows**：
  - 在 Fibonacci 上按 → 键，焦点移到 Flows；
  - seller 视图显示"卖压视图尚未实现"，没有任何数字；
  - 时间周期按钮、Replay、Audit、OHLC 都不显示；
  - 切到 Perp 后 URL 带 `flow=perp`，显示"未连接 — 永续数据源待接入"。
- **ETH**：不显示徽章，没有叠加线，Key levels 显示"链上成本线仅支持 BTC。"。
- **390px**：
  - `scrollWidth` 为 390，无横向溢出；
  - 徽章独占一行（宽 352px，与所在行同宽）；
  - 4 个 tab 平铺；
  - Cycle 与来源区块默认折叠。

## 5. 与 mockup 的差异

| 差异 | 说明 |
|---|---|
| 5 条模型线统一用中性色虚线 | mockup 按线区分颜色。实现时为了避开已有的 SMA（紫色）和前窗口高低线（玫红、青色）的配色，改用统一的中性色。是否改回分色由用户决定 |
| 徽章位置 | mockup 中徽章在标题旁；实现中放在 symbol 所在 toolbar 行的末尾（现价之后）。窄屏下独占一行，符合 mockup |
| 无刻度轨、无最近价位表 | 按计划属于 P3 |

## 6. 未覆盖

- **已保存快照下的 latestOnly 提示**：本地库没有已保存的快照，没在浏览器中验证；单元测试已覆盖。
- **推送**：本分支未推送，因为 OAuth token 缺 `workflow` scope，原因见 SDD 记录。
