# test 发布计划（2026-11-04）：main 与发布分支汇合

## 目标

把 main（`27f2690`，链上 Flows、perps/Coinalyze、图 3–8、BRK 10-30 升级修复）发布到 Coolify test，同时保留发布分支 `codex/test-environment`（`2e5ce61`）上 main 没有的三项功能：

1. **On-chain cycle check**（`8e6e068`）：六状态、0–100 周期指数、短线抛压，`GET /market-cycle`；
2. **Macro watch**（`158b81b`）：下次 FOMC 倒计时和 10Y−1Y 利差，`GET /macro-watch`；
3. **Strategy flow**（`35bc924`）：手动周期决策流程，纯前端，选择存浏览器本地。

三项都只在 TD 页、BTCUSDT 下出现，位于 regime check 之后、replay 之前（与发布分支相同）。

## 现状核对

- 两条分支没有有效的共同历史（merge-base 是 `62a5ac2` 文档提交）；main 的 `47e096b` 是当时未提交工作的快照。
- 逐项核对：发布分支截至 `45735e2` 的代码、部署修正和 DeMark 修复（`530ccd0`、`45735e2`）都已在 main 中（`summary.py`、`alphabtc.py`、`compare_alphabtc_context.py` 与 main 逐字节一致；`deploy/test` 只多了 main 的后续改动）。
- 发布分支独有的只有 5 个提交：`2f27cc1`（文档）、`8e6e068`、`158b81b`、`35bc924`、`2e5ce61`（文档）。
- 直接 `git merge` 会因无共同历史产生 25 个 add/add 冲突，所以不走普通合并，改为"移植 + 汇合提交"（见下文）。
- 例外：`530ccd0`、`45735e2` 带的 regime 测试和夹具（Bybit 现货、精确比价、03:50/04:07/04:31/09:15 四个快照）main 里是更早的 Binance 容差版本。从 `45735e2` 取回 `tests/regime/`，在 main 代码上 119 项通过；`034955Z` 夹具不再被引用，按规则保留文件。
- 最近一次有记录的 test 部署是 `1f4d9dc`（09-28 Bybit 现货）；`2e5ce61` 是否上线过没有记录，部署前在 Coolify 核对实际运行 SHA。
- 与 RELEASING 第 2 步的有意偏离：候选以 main 为基础组装，而不是在发布分支上逐个集成，因为发布分支的内容除上述 5 个提交和 regime 测试外都已在 main。

## 移植中必须改的地方

- **BRK 10-30 升级让 cycle check 失效**，已在线上核实：
  - `utxos_X_old_*` 返回 404，改为 `age_X_*`；
  - `unrealized_profit_to_mcap_ratio` 和 `unrealized_loss_to_mcap_ratio` 已移除，用 `unrealized_profit / market_cap` 和 `unrealized_loss / market_cap` 计算。拿 09-24 至 09-27 的数据对比，结果与 09-27 夹具的旧值在 6 位小数内一致；
  - 其余序列（`sth_realized_price`、`true_market_mean`、`realized_*_sum_24h`、`supply_in_*`、`realized_cap`、`sth_supply*`）仍可用；
  - 本地名称保持不变，指标代码和夹具不改；只在取数层把本地名映射到 BRK 名，并派生这两个比率，做法与 main 的 `brk.REMOTE_COHORTS` 相同；任何一个分量缺失都报缺失，不补 0。
- **模块名冲突**：发布分支的 `wheelhouse_service/onchain.py` 会被 main 的 `onchain/` 包遮蔽，改名为 `bitview.py`，`cycle.py` 的 import 同步修改。
- **http.py**：按 main 当前的 `create_app` 结构加入两个端点及其缓存和注入参数；TTL 不变（cycle 900 s，失败时 60 s；macro 3600 s，失败时 60 s）。
- **前端**：`market-page.tsx` 加三个组件；`client.ts` 加 `getMarketCycle`、`getMacroWatch`；`i18n.ts` 合入新文案键；`market.css` 合入样式。改完后运行 `make contract`，重新生成 `openapi.json` 和 `api-schema.d.ts`。
- **命名冲突**（复核发现）：main 的 cycle badge 已用 `cycle.title`、`cycle.stateLabel`、`cycle.unavailable`、`cycle.state.*`，文案不同；cycle check 的键改用 `cycleCheck.*`。`indicators/cycle/alphabtc.py` 的 `PressurePoint` 与 `onchain/pressure.py` 重名，会让 OpenAPI 改用带模块前缀的长名，改名为 `CyclePressurePoint`；`api-schema.d.ts` 相对 main 只有新增。
- 不改 main 现有的 cycle badge、seller pressure 等功能。cycle check 与 cycle badge 的六状态会有部分重复，这一点保留，在发布记录里注明。

## 汇合方式

1. 在独立 worktree 中，从 main 新建分支 `claude/test-release-1104`，依次 cherry-pick 上述 5 个提交，解决冲突，再单独提交 BRK 适配。
2. 验证通过后，用 `git commit-tree` 生成汇合提交 M：tree 取自 `claude/test-release-1104`，父提交依次为 `claude/test-release-1104` 和 `origin/codex/test-environment`。
   - 推送前比较 M 与 `origin/codex/test-environment`，列出 M 删除的文件，逐个确认是有意删除（例如 `onchain.py` 改名）。
3. M 同时是两条分支的快进：
   - 正常 push 到 `codex/test-environment`，不使用 force；M 新增了 `.github/workflows/`，HTTPS 凭据缺 workflow scope，用 SSH 推送，推送会触发该 workflow 的 CI；
   - push 前确认 main 没有前移，再把 main 快进到 M。之后两条分支共享历史，下次发布不会再出现 add/add 冲突。

## 验证

- 在候选上运行 `make check` 和 `make build`。
- 用真实 BRK、美联储和 FRED 数据调用 `/market-cycle` 和 `/macro-watch`，确认状态为 fresh 或 stale，`error` 为 null。
- 浏览器检查：本地 preview 用 worktree 的独立端口，看 TD 页 BTC 下三个面板，以及 390px 窄屏；同时回归 Flows 各子视图。
  - 本机 DNS 拦截 Bybit 和 Binance，主图会显示 STALE，这是网络环境造成的，不是功能问题。
- 数据库：market 和 portfolio 迁移与发布分支一致；test 上还没有 onchain 和 perps 库，会新建，不存在迁移回滚问题。
  - 部署前仍对 market 库做一次备份（用户在 Coolify 操作，或确认 test 没有需要保留的数据）。
- **配置**：在 Coolify 中设置 secret `WHEELHOUSE_COINALYZE_KEY`。出站网络需要放行 `bitview.space`、`api.coinalyze.net`、`www.federalreserve.gov`、`fred.stlouisfed.org`，以及 RELEASING 中 perps 需要的 `fapi.binance.com`、`data.binance.vision`、`api.bybit.com`（compose 本身没有出站限制）。

## 发布与验收（需要用户操作的部分）

1. 用户在 Coolify 设置 Coinalyze secret，然后点 Deploy。
2. 我核对部署日志中的 SHA 是否等于 M。
3. 匿名验收：运行 `verify.py`，确认登录页可访问、匿名 API 返回 401 且没有 Basic challenge、broker 返回 403。
4. 登录后的验收需要钱包会话，由用户在 OKX Wallet 放行 test 域名后进行：
   - perps 的 status 和 states；
   - 图 8 的 cost-basis-history；
   - TD 页的三个面板。
   - 首次部署后 onchain 回填要 13 轮（约 12 小时）才补齐图 8 的 All，perps 首轮要拉 121 天；验收时 All 不完整属正常。
   - `/market-cycle` 冷缓存时要向 BRK 取约 24 条日线，前端默认 5 s 超时可能不够，验收时注意首次加载。
5. 在 `docs/deployment/releases/2026-11-04-onchain-perps.md` 写发布记录：时间、范围、来源提交、实际部署 SHA、Coolify deployment ID、上一可用 SHA、验证结果和已知问题。

## 风险与回滚

- **回滚方式**：在 Coolify 中重新部署上一个可用 SHA，命名卷保留。
- **onchain 和 perps 库是新建的**：回到旧版本时这两个库不会被读取，不影响旧版本运行。
- **免费 Coinalyze key 最多 2 个进程同时使用**：本机开发和 test 各占一个，验证期间不要另起第三个进程。
