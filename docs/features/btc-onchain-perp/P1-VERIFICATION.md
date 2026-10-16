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

## 7. 整分支终审与修复（同日补记）

终审结论为"修复后可合并"，严重问题 0 项，重要问题 1 项。

**重要问题**：URPD 接口持续报错时，Median 会退回到任意旧的快照，而界面不显示快照日期，旧数据看起来像当前读数。
- 后端：退回时只接受日期不早于运行日前一天的快照，更旧的一律视同没有，不出 Median，reason 记 `urpd_missing`。
- URPD 阶段失败不再给周期视图带上 `brk_unavailable`，错误只记在 `/status` 的 `last_error` 里。
- 前端：Source 行显示 URPD 日期；URPD 日期早于 levels 的 as_of 时，Median 在 inspector 和图上都标出自己的日期。
- 对应提交：`522789e`、`73a945b`。

**同一批顺带修复的小问题**
- refreshing 提示移到折叠区块之外，手机上也能看到。
- Perp 占位文案写明缺哪类数据源：Glassnode、Coinalyze 或自建清算采集器。
- 测试辅助代码的类型错误（`b2066ae`）。
- 周期徽章改用 `isError` 判断请求失败。

修复后经过一次限定范围的复审：6 项全部解决，没有引入新问题。浏览器复核：Source 显示"URPD 筹码分布 2026-10-16 UTC"；URPD 日期与 as_of 相同，所以 Median 不加日期标记。

**环境问题**：本机 Vite 的文件监听不会收到 `foundation.py sync` 写入 `.local/wealthfolio` 的改动。每次 sync 之后，都要重启 `pnpm --filter frontend dev`，页面才会更新。原因未查，可能与路径位于 `.local` 下有关。

## 8. 执行中的裁定

| 编号 | 裁定 | 判错的代价 |
|---|---|---|
| R1 | 按用户要求，在主 checkout 的 `claude/btc-onchain-perp` 分支上执行，不另开 worktree | 与用户未跟踪的遗留文件共用一个 checkout |
| R2 | 各任务只在本地提交，推送统一放到最后。push 被拒是因为 OAuth token 缺 `workflow` scope：本地 main 上还没推送的 60cab3e、f85e118 改动了 `.github/workflows` | 在用户刷新 token 之前，提交都停留在本地 |
| R3 | `last_complete` 返回的数值以 BRK 序列名为键，`model_lines` 也按同样的键读取 | 改个名而已 |
| R4 | 周期只保留 W、STH、TMM、`price_close` 四条都有值且大于 0 的日期，这是原站的规则；spec §3.1 正文只写了三条成本序列 | 只缺 `price_close` 的日期会被跳过 |
| R5 | spec 中"最后一行超过 3 天视为过期"的 QC，由更严格的 `day1_state` 覆盖 | 无，只是更早标为 stale |
| R6 | URPD 报错时，仍用新序列派生周期和模型线；后由 R12 修正 | — |
| R7 | 把 `.local/wealthfolio` 中唯一一行过期的宿主补丁（`href` 少了 `?method=td`）按已提交的补丁对齐 | 无持久影响，checkout 可以重新生成 |
| R8 | `CycleView.changes` 改为可空，覆盖计划原文的 `int`，以免缺失数据显示成 0 | 契约多一个可空字段 |
| R9 | reasons 按模块过滤：cycle 只保留自己依赖的序列缺失和 `brk_unavailable`；levels 只保留模型线序列缺失、`urpd_missing` 和 `brk_unavailable` | 跨模块的问题只能在 `/status` 中看到 |
| R10 | Flows 下隐藏 Replay、Audit、OHLC，与确认过的 mockup 一致；页头现价和后台刷新保留 | 要恢复只需改回一个条件 |
| R11 | Task 11 由主会话亲自执行，并用分支代码替换本机遗留的 Python 和 Vite 孤儿进程，同时启动 wealthfolio 容器 | 用户的长跑开发进程被等价的新进程替换 |
| R12 | 修正 R6：URPD 退回快照的日期不早于运行日前一天，否则不出 Median；URPD 失败不再影响周期视图；前端显示 URPD 日期，并标出旧的 Median | URPD 中断超过一天后，Median 会缺失，但缺失是如实显示的 |

**暂缓处理的问题**（详见 `.superpowers/sdd/PLAN-P1/progress.md`）
- 午夜宽限期内，forming 标记会消失，每天不超过 1 小时。
- BRK 整天不可达、数据却仍是 fresh 时，徽章不提示。
- 越界的多行贴边标注可能进入绘图区。
- `UrpdBucket` 把用不到的字段设为必填。
- stale 日期格式不统一。
- `market-page` 用错误消息字符串判断失败，这个隐患目前不会触发。
- 各任务评审中记下的若干 Minor 项。
