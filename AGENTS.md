# AlgoForceNext

## 语言（最高优先级）

- 与用户对话：中文。
- 代码、标识符、代码注释、commit message：英文。
- 实现计划、spec（需求、设计、验收规范）及其他项目文档：中文；代码片段、标识符、API 名称保留英文。
- 产品 UI 沿用已确认的英文界面，不改变上述规则。

## 项目背景与边界

Sirius（天狼星）是当前开发代号，面向 moomoo 新加坡账户的个人只读投资工作台，涵盖股票与期权持仓、Wheel 策略记账、组合 Greeks 和市场分析。

当前实现基于 Wealthfolio 前端 overlay 与 Python analytics 服务，已部署独立 Coolify test 环境。历史 HTML/CSS/JavaScript 原型（`prototypes/`）仅作参考；正式实现以 `integrations/wealthfolio`、`services/analytics` 和项目脚本为准。

- 账户能力限于只读分析，不实现下单、改单、撤单、交易解锁或自动执行。
- 真实账单、持仓、截图与凭据不进入公开产物、演示数据或日志；账户连接不代表允许向无关外部服务发送金融数据。
- 明确区分模拟数据、真实数据和未实现的集成；缺失或过期数据不能伪装为零值或实时数据，也不用 mock/fake 数据做运行时兜底。
- 保留文件和目录；需要移除时请用户手动删除。
- `.env` 与密钥不提交；只在用户要求时才 commit / push，在 main 上先开分支。

## 常用命令

从仓库根目录运行，以 `Makefile` 与 `scripts/foundation.py` 为准：

```sh
make setup    # create the Python environment and install dependencies
make dev      # run the analytics service and Wealthfolio overlay locally
make check    # run the project checks
make contract # re-export the OpenAPI contract and regenerate TypeScript types
make verify-a5
```

改动 `services/analytics/src/wheelhouse_service/contracts.py` 后必须运行 `make contract`。Python 测试位于 `services/analytics/tests`。

## 执行与完成

已授权的本地工作持续做到可用、可评审：完成实现、相关验证以及发现问题的修复，无需逐步确认。只有缺失信息实质影响范围、正确性或外部承诺时才询问。先运行验证命令并看到输出，再声明完成。

- **非平凡的基建/架构改动：**先写中文计划，独立复核后再执行。
- **UI：**复用共享 shell；在浏览器检查改动页面、受影响控件和窄屏，交付可运行预览并说明模拟部分。
- **记账、导入、风险：**用脱敏样例独立核对预期结果，覆盖本次涉及的金融边界（见金融领域规则）。
- **正式实现：**验证范围与改动相称；检查通过后仅因新改动、失败或未解决问题追加检查。
- **调研与选型：**依据官方文档、源码或发布记录，注明核验日期；区分已验证能力与待验证假设。
- 改动保持外科手术式：只动必须动的，风格跟随现有代码，不顺手重构。

## 已确认的 UI

- 英文暗色赛博朋克：近黑底、青色主强调、紫色次强调、克制辉光、可读数据和清晰键盘焦点。标题用 Orbitron，界面文字用 Inter，金融数值用 JetBrains Mono。
- Overview、Wheel cycles、Risk exposure、Market intelligence 共用一个左侧栏，小屏折叠同一导航。设计修正应用到共享 shell。
- Market intelligence：市场/标的 → TD Sequential / Key levels / Fibonacci 方法 tabs → 周期控件 → 一张大图与当前方法详情。方法 tabs 与应用导航分开；三方法卡片网格、并排图表和市场简报布局是已否定的方案。

## 当前市场数据约定

市场页默认 `method=td`。BTCUSDT 固定 Bybit 现货（`/v5/market/kline?category=spot`）；ETHUSDT、MUUSDT 保持 Binance USDⓈ-M USDT 永续（`/fapi/v1/klines`）。各来源/市场使用独立 venue；界面不提供 fixture 或现货切换，不使用假数据回退。主图与跨周期数据自动刷新，保留缺失/过期状态。

## 按任务读取

仅加载当前任务相关资料；以下是入口，不是每次修改前的必读清单。

- **发布 test、修改部署或回滚：**[发布流程](docs/deployment/RELEASING.md)。沿用独立发布分支和 Coolify 服务器构建；仅集成已完成并验证的提交，交付时记录实际部署 SHA 与外网验收结果。开发完成本身不触发发布。
- **钱包登录、白名单或会话：**[钱包登录需求](docs/deployment/AUTH-REQUIREMENTS.md)、[认证服务说明](services/wallet-auth/README.md)。页面与 API 的授权由服务端强制检查。
- **券商接入、记账/导入/Greeks/指标计算或展示含义：**[金融领域规则](docs/financial-domain.md)。
- **连接 moomoo 或评估券商 MCP：**[官方接入研究](research/moomoo-access-research-2026-09-26.md)、[MCP 源码审查](research/moomoo-mcp-candidates.md)；实施前重新核验版本相关结论。
- **应用底座或 Wealthfolio 扩展方式：**[看板选型研究](research/trading-dashboard-research-2026-09-26.md)、[Python host ADR](docs/adr/0001-wealthfolio-python-host.md)；比较 Wheel 工具读[期权候选](research/options-dashboard-candidates.md)。
- **analytics 服务：**[服务说明](services/analytics/README.md)、[A2–A5 验收](docs/architecture/a2-a5-acceptance.md)。
- **市场分析页面与指标：**[市场原型说明](prototypes/wheel-dashboard/MARKET-PROTOTYPE.md)（以末尾已确认层级为准）、[市场引擎](docs/implementation/market-engine.md)。
- **历史原型：**[原型说明](prototypes/wheel-dashboard/README.md)；共享导航在同目录 `app-shell.js` 与 `app-shell.css`。
