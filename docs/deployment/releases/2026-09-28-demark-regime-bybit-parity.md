# test 发布记录：DeMark Regime 规则修复（Bybit 行情对照）（2026-09-28）

按[发布流程](../RELEASING.md)执行。

## 版本

- 发布时间：2026-09-28 约 09:07 UTC 开始 Coolify 部署，耗时 03m27s。
- 来源提交：`530ccd0877bce24796826dc73908eb44e0aab203`（`fix(demark): match TradingSignal rounds, countdown step and setup close`），分支 `codex/test-environment`，直接接在 `7fc0f6c` 之后。
- 实际部署 SHA：`530ccd0877bce24796826dc73908eb44e0aab203`（部署日志中 web、analytics、wallet-auth 三个镜像标签均为该完整 SHA）。
- Coolify deployment ID：`16wgacnuac9gz2pwbifohagl`，状态 Success。Deploy 由用户点击。
- 访问 URL：`https://gfbk0bsvzvpdv2tonftg9cp6.45.32.124.189.sslip.io`。
- 上一可用版本：`1f4d9dc`，deployment `vs7owpv1hbyzeikpnoqnpj3b`。

## 变更范围

- `indicators/demark/summary.py` 四处规则修复，依据见 [PARITY-LOG](../../features/demark-regime/PARITY-LOG.md)：
  - rounds 不列 retain_active 压住的未完善同向 9；
  - 反向 setup 段仍保留风险位有效的合格 13 那一轮；
  - 13 合格当根 countdownStep 报 13；
  - S9 的 countdown 已开始计数后被取消，setupClose 为空。
- `indicators/regime/alphabtc.py` 仅改注释。
- 测试夹具换成 Bybit 现货行情（TradingSignal 自身的行情源），共 6 份 AlphaBTC 快照；去掉行情源豁免，价格要求精确相等。
- 新增 `scripts/verification/compare_alphabtc_context.py`（默认 Bybit），不进镜像。

## 迁移与配置

无数据库、Compose、Dockerfile、环境变量或 API 变化；命名卷保留。

## 验证

候选（发布 worktree，提交前）：

- regime 测试 109 passed；去掉四处修复后 7 个用例失败。
- analytics 全部 207 passed，1 failed：`test_sdk_protocol`，发布分支缺 broker 脚本，与前两次发布相同的既有排除项。
- ruff（services/analytics）、mypy 27 个文件通过。
- 对照脚本以 Bybit 现货重放 6 份快照 × 5 个周期：结构、risk、s9/s13、置信度、Regime 全部一致，价格残差 0。

外网（部署完成后）：

- `deploy/test/verify.py` exit 0：钱包登录页 passed、匿名 API 被拦（401）、无 Basic Auth、broker sync 被拦。

浏览器（用户已登录的 Chrome，约 09:13 UTC）：

- BTC `/market-intelligence?symbol=BTCUSDT&timeframe=5m&method=td`：来源 Bybit 现货；跨周期区块 5 个周期均为"最新"、窗口 499；日内（1h）反转阴跌、跨天（4h）突破减弱，与 09:15 抓取的 AlphaBTC 数据推出的 Regime 一致。
- 同刻 AlphaBTC 快照（09:15:11）用 Bybit 回放发现 5m rounds 与 provisional 两处新差异，已在后续提交修复（见 PARITY-LOG），本次部署尚不含该修复。

## 已知问题

- 生产只用已收盘 K 线，会比 AlphaBTC（含形成中 K 线）慢一根，页面数值不能与 AlphaBTC 同刻逐项相等。
- `530ccd0` 中，5m 同向新段且 13 风险位已破时仍列出旧的 13 轮次，provisional 也会误报；修复待下次发布。

## 追加发布：`45735e2`（同日）

- 提交 `45735e27fd8a2475ab2d78f91fd78cca24f437aa`（`fix(demark): drop broken-risk 13 rounds on same-side runs`），修复上面"已知问题"中的 rounds 与 provisional。
- Coolify deployment `gyf4gbmzu05owmedrsqymfl8`，Success，03m29s；上一版本 `530ccd0`。
- `deploy/test/verify.py` 通过（登录页、匿名 API 拦截、无 Basic Auth、broker 拦截）。
- 浏览器（用户在 Chrome 放行 OKX 警告后，约 10:00 UTC）：5 个周期均为"最新"，日内 反转阴跌、跨天 突破减弱；同刻 AlphaBTC 数据用本版本回放全部一致。

## 追加发布：`35bc924`（同日，含 `2f27cc1`、`8e6e068`、`158b81b`）

- 内容：AlphaBTC 6.2 之后部分的计划与问题清单；链上六态 + 周期指数 + 短线抛压（`/market-cycle`）；FOMC 倒计时 + 10Y−1Y 利差（`/macro-watch`）；手动决策流程 ④–⑧；回测复现报告。
- Coolify deployment `xky0lbfcg13pfczcjisutf2o`，Success，09m12s；上一版本 `45735e2`。
- `deploy/test/verify.py` 通过。
- 浏览器（用户 Chrome）：BTC TD 页三个新区块均显示实时数据：突破第 5 天、周期指数 42（周期中段）、短线抛压 90.0% 未触发；下次 FOMC 为 2026-10-28 18:00 UTC；利差 +0.67% 未倒挂（FRED 09-24）；手动流程默认"初期突破 / 突破衰减"，日内 regime 反转阴跌。截图时页面繁忙未能截取，按页面文字核对。
