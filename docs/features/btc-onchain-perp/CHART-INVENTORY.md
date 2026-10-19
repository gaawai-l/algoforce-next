# 原站图表盘点与本地复刻现状

日期：2026-10-19。原站线上版本于 2026-10-18 在已登录的 Chrome 中核对。

## 原站

| 页面 | URL | 数据源 |
|---|---|---|
| state-report | https://alphabtc-regime.vercel.app/onchain/state-report | BRK（bitview.space，公开，免费） |
| onchain-seller | https://alpha-vol.vercel.app/onchain-seller.html | BRK |
| perp-squeeze | https://alpha-vol.vercel.app/perp-squeeze.html | Glassnode（经公司 DataX 网关，我们无法使用） |

研究资料（不入库）：`.local/research-samples/alpha-dashboards-2026-10-16/`。其中包括：
- 各页的 `NOTES.md`：源码分析，带行号；
- `raw/`：已登录时保存的页面 HTML，以及拆出来的作者脚本；
- `tools/`：复算脚本。

本地对应位置：Wealthfolio overlay 的 Market intelligence（`/market-intelligence`）。

## 合计

三个页面共 **16 张图、2 张表**，另有 Analyst Take（人工撰写的文字）和页头的周期状态。

目前本地做了：
- **9 张图**：onchain-seller 的 3 张，perp-squeeze 的 4 张，state-report 的 2 张（图 7 的刻度轨版本、页头周期）；
- **1 张表**：state-report 的表 2；
- **perp-squeeze 的表 1**：已实现，但因为缺清算数据显示不出来。

## state-report（数据：BRK）

| 图表 | 需要的数据 | 缺数据？ | 本地现状 |
|---|---|---|---|
| 图 1A Sell Side Breakdown by LTH & STH · Relative | BRK hour1：`{sth,lth}_realized_{profit,loss}_cumulative`、`{sth,lth}_transfer_volume_in_{profit,loss}_cumulative`（含 `_usd`），<1h 和 1h–1d 群体用于剔除 | 不缺 | **没做**（用户急需） |
| 图 1B 同上 · Absolute | 同上 | 不缺 | **没做**（用户急需） |
| 图 2 Sell Side by All Age Cohorts | BRK hour1：23 个币龄群体的已实现盈亏，合并成 12 档或 6 档 | 不缺 | 没做（P1 spec 划出范围） |
| 图 3 Buy & Sell Side By Cost Basis | BRK URPD：all/sth/lth 今天与 1/7/30/90 天前的快照，STH 用 lin200，All 和 LTH 用 lin500 | 不缺 | **没做，也不在 spec 的"不做"清单里，是漏掉的** |
| 图 4 同上 · Age Breakdown | BRK 分币龄的 URPD，day1 最高/最低价约 5600 天 | 不缺 | 没做（spec 划出范围） |
| 图 5 Net Supply Change By Size Cohorts | BRK hour1：12 档 `addrs_*` 的供应 | 不缺 | 没做（spec 划出范围） |
| 图 6 Net Realized P&L By Size Cohorts | BRK hour1：12 档的已实现盈亏与已实现市值 | 不缺 | 没做（spec 划出范围） |
| 图 7 Supply by Cost Basis | BRK URPD | 不缺 | 做成了价格图右侧的刻度轨（已确认的 UI 方案），**不是原图样式** |
| 图 8 Cost Basis Distribution, All Coins | BRK：365 个日快照（All 档 1461 个） | 不缺，但首次要取 365 次 | 没做（spec 划出范围） |
| 表 2 Price Levels | BRK URPD | 不缺 | **已做**，与原站逐格一致 |
| Analyst Take | 人工撰写；原站模板本身是空的 | — | 没做 |
| 页头周期 | BRK day1 | 不缺 | **已做**（cycle badge） |

## onchain-seller（数据：BRK）

| 图表 | 缺数据？ | 本地现状（2026-10-18 13:00 那根，与原站对照） |
|---|---|---|
| 图 1 Total Realized Loss By Cohorts | 不缺 | 已做。阈值：原站 Extreme $32.8M / Warning $8.66M，本地 $32.6M / $8.66M（本地默认开 O2，阈值逐小时滚动） |
| 图 2 STH Realized Loss Share of Sell Side | 不缺 | 已做。阈值：原站 56.7% / 22.5%，本地一致 |
| 图 3 STH Supply in Loss | 不缺 | 已做。阈值：原站 34.3% / 26.4%，本地 34.3% / 26.2% |
| Supplementary 标签页 | — | 原站这一页是空的 |

## perp-squeeze（原站数据：Glassnode）

| 图表 | 缺数据？ | 本地现状 |
|---|---|---|
| Parameters（Exchange：All venues / Binance / Bybit / Hyperliquid；State window；Show） | 缺 Hyperliquid，以及多家交易所汇总的 All venues | 只有 Binance、Bybit 和两家相加 |
| 表 1 Perp States | **缺历史清算**，以及 Bybit 的主动买卖差 | 已实现，采满 7 天才显示 |
| 图 1 Long/Short Squeezes & Unwinds | 同上 | 同上 |
| 图 2 New Long/Short, Spot-led | 同上 | 同上 |
| 图 3 Price vs OI | 不缺 | 已做，完整 |
| 图 4 Volume Delta & Liquidations | 清算缺；Bybit 买卖差缺 | 只显示采集开始之后的部分 |

缺的数据改由 Coinalyze 补，方案见 [PROPOSAL-COINALYZE.md](../btc-perp-states/PROPOSAL-COINALYZE.md)。

## 本地显示问题（2026-10-18 观察）

- Claude 桌面应用会自动停掉它启动的预览服务。服务一停，数据就停在那一刻，或者页面整体显示不出来。2026-10-18 那次，服务被停了约 20 小时。
- 本地默认开着 O1–O6，读数会和原站有细小差别。设 `WHEELHOUSE_RULES=v1` 时，计算与原站一致。
- 用户反馈"已做好的页面完全显示不出来"，原因还要逐页排查。

本机启动方式见 `.claude/launch.json`（不入库）：
- analytics：`WHEELHOUSE_PORT=8787 … .venv-foundation/bin/python -m wheelhouse_service`；
- overlay：先 `make sync`，再在 `.local/wealthfolio` 运行 pnpm 的 frontend dev，端口 1420，代理到 :8088 上的 Wealthfolio 后端和 :8787。

## 原站源码

- 页面里的前端脚本已经保存在 `raw/`。
- 服务端部分（perp-squeeze 的 `serve.py`、`gn_fetch.py`）在原作者的另一个 GitHub 账号下。
- 本机为此生成了一把专用于读取的密钥 `~/.ssh/id_ed25519_dashboards`，指纹 `SHA256:cXwJHXtjETKxal70GAOr/yQvf5m+4odBZK8+EBqa/2o`，等对方添加后告知仓库地址。
- 读取方式：
  ```
  GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_dashboards -o IdentitiesOnly=yes" git clone git@github.com:<owner>/<repo>.git .local/<repo>
  ```
  只读，克隆到 `.local/`，不提交。
