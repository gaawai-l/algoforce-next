# test 发布记录：DeMark Regime 跨周期上下文（2026-09-28）

按[发布流程](../RELEASING.md)执行。

## 版本

- 发布时间：2026-09-28 约 02:38 UTC 开始 Coolify 部署，耗时 07m57s。
- 来源提交：`8f48316adfd43ad78b919d9f0a81f9fb1001cb3d`（`feat(market): add DeMark regime cross-timeframe context`），分支 `codex/test-environment`。
- 实际部署 SHA：`8f48316adfd43ad78b919d9f0a81f9fb1001cb3d`（部署日志 `Importing … codex/test-environment (commit sha 8f48316…)`；analytics 镜像标签为同一完整 SHA）。
- Coolify deployment ID：`ezmw7scmtgzvny7pjjz7uotk`，状态 Success。
- 访问 URL：`https://gfbk0bsvzvpdv2tonftg9cp6.45.32.124.189.sslip.io`。
- 上一可用版本：`87a404578ade9effa307c50ae5dd89c588c6a4b6`，deployment `uoc1gzdxznislnu9bnofjpja`。

## 变更范围

- 新增只读接口 `GET /api/wheelhouse/v1/market-context`：5 个周期各取 499 根已收盘 K 线，给出 DeMark 主序列摘要、AlphaBTC 规则的日内（1h）/跨天（4h）regime 与信号档位；capabilities 增加 `market_context`。规则见 [SPEC](../../features/demark-regime/SPEC.md)。
- Market intelligence 页面 TD 方法下新增 regime 核对区块（数据核对用，非最终 UI）。
- 同批带上此前本地已验证、尚未发布的 Market 页面依赖：DeMark v2 规则（`wheelhouse-sequential-2`）、i18n、周期下拉、图表范围，以及行情源窗口上限 500。
- `deploy/test/verify.py` 增加 market-context 冒烟检查。

## 迁移与配置

无数据库结构变化，无 Compose、Dockerfile 或环境变量变化；命名卷保留。

## 验证

候选（发布 worktree，提交前）：

- `make check` exit 0：ruff 通过，mypy 27 个文件无错，pytest 143 passed，前端 build:types / type-check 通过，vitest 29 passed。
- 本地两镜像构建成功；镜像内 `/market-context` 返回 200。

外网（部署完成后，Basic Auth 仍开启时）：

- 匿名访问 `/`、`/api/v1/settings`、`/api/wheelhouse/v1/status` 均 401；匿名 `/api/wheelhouse/v1/market-context` 401；`/healthz` 200。
- 跨源 POST `/api/wheelhouse/v1/jobs`（Origin `https://unrelated.example`）403；POST `portfolio/sync`、`portfolio/discover` 均 403（nginx 在认证前拦截）。

外网（同日用户在部署外去掉 Basic Auth 之后；Coolify 无新部署，运行版本仍为 `ezmw7scmtgzvny7pjjz7uotk` / `8f48316`）：

- `deploy/test/verify.py` 的认证版不再适用（其 401 断言会失败）；改用等价的匿名脚本逐项复验，exit 0：`/`、`/api/v1/healthz`、`/api/wheelhouse/v1/status` 200；status capabilities 含 `market_context`；跨源 POST 403、broker sync 403；fixture DeMark 任务 succeeded，320 根、`data_state=simulated`；`/market-context?source=fixture&symbol=BTCUSDT` 200，1h simulated、intraday `rev`（其余周期未刷新 fixture，为 unavailable，符合预期）。
- 浏览器（内置浏览器，800 宽视口）打开 `/market-intelligence?timeframe=1h&method=td`，数据源 Binance 公开现货：页面自动为其余周期提交刷新，5 个周期全部 Fresh、窗口 499 根；核对区块显示 Intraday regime · 1h = Selloff exhausted（阴跌爆拉），Swing regime · 4h = Breakout decay（突破减弱），三个看板选项与各周期数据行正常显示（未逐一点击切换）；本次加载的全部 API 请求 200，无新增控制台错误。窄屏布局沿用本地 390px 检查结论，未在外网重复。

## 已知问题

- test 的 Basic Auth 已在部署流程外关闭（未进 git）：当前任何人可访问并提交 fixture/公开行情刷新任务（broker 仍被 nginx 拦截）。按 `8f48316` 重新部署会恢复 Basic Auth；`deploy/test/verify.py`、`docs/deployment/coolify-test.md` 与 RELEASING.md 仍按有认证描述，需要随该变更一起更新。

- test 只有 fixture（模拟）行情时，各周期状态为 simulated，fixture 仅 320 根，`history_complete` 为 false，不会触发补齐刷新；regime 标注为模拟数据。
- 成功标准 2（5 份新 AlphaBTC 快照对照）尚未完成。
