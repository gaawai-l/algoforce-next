# 股票与期权组合 Dashboard：期权细分候选

查询日期：2026-09-26。仅检查公开 GitHub README、源代码、GitHub API；未部署、未用真实券商报表验收。Stars 是当日快照；最后提交是默认分支最新 commit，并不等于业务功能持续维护。

## 结论

若使用 IBKR，优先试 **BigCatMidori/IBKR-Dashboard** 的演示和报表导入；若以 Wheel、卖 put/covered call 为主，试 **premium-tracker**；若重视多腿策略、roll 生命周期和日志，试 **GammaLedger**。后三者都不能直接认定为带券商实时期权 Greeks 的成熟终端。**finx-tracker** 是旧的开发底座，不适合以省心为优先的用户。

| 项目 | 适用情况 | 数据与部署 | 维护 / 许可 |
|---|---|---|---|
| [IBKR-Dashboard](https://github.com/BigCatMidori/IBKR-Dashboard) | 股票+期权整体组合、收益曲线、按标的汇总、当前持仓 | Activity/Flex CSV；Flex Web Service 每日自动拉取；Flask+SQLite；中英文；可生成 demo.html | 4 stars；最新提交 2026-09-09；PolyForm Noncommercial 1.0.0，源码可用但不是 OSI 开源 |
| [premium-tracker](https://github.com/Marfusios/premium-tracker) | IBKR 卖期权 / Wheel、权利金、抵押现金风险 | Activity CSV 在浏览器处理；React/TS；静态网站 | 11 stars；最新提交 2025-08-19；README 写 MIT，但未发现 LICENSE 文件、GitHub license 为 null |
| [GammaLedger](https://github.com/r-brown/GammaLedger) | Wheel/PMCC/价差/Iron Condor、多腿及 roll 生命周期 | OFX/QFX 导入、手动录入；浏览器 localStorage；Vite/TS；有在线应用 | 22 stars；最新提交 2026-09-19；LICENSE 为 AGPLv3，但 package.json 写 ISC，元数据不一致 |
| [finx-tracker](https://github.com/westonplatter/finx-tracker) | 开发者自己扩展期权/期货策略 P&L | 依赖相邻 finx-reports-ib 项目导入 trades/positions；Django+Docker Compose | 9 stars；默认分支最新提交 2023-06-23（依赖更新）；BSD-3-Clause |

## IBKR-Dashboard：最贴近股票与期权同时查看

README 明确支持从最新报表读取 holdings/cash、FIFO 成本和浮盈亏；同一 underlying 的期权腿可折叠，并为识别出的组合命名。支持多账户合并、TWR、单位净值、费用和按标的 P&L。数据是报表时点 / 每日更新，不能据此承诺盘中实时行情或 Greeks。部署只需 Python 3.9+、Flask、qrcode；前端无 build step。可以先运行 tools/make_demo.py 看界面。

限制：非 USD 基础货币数据虽按实际基础货币计算，但 UI 仍标 USD；不同基础货币子账户不能合并。历史不足会影响 since-inception 结果。使用少量报表与 IBKR 官方结果核对后再作日常工具。

来源：[README / 功能与 Known limitations](https://github.com/BigCatMidori/IBKR-Dashboard/blob/main/README.md)、[许可](https://github.com/BigCatMidori/IBKR-Dashboard/blob/main/LICENSE)、[最新提交 API](https://api.github.com/repos/BigCatMidori/IBKR-Dashboard/commits?per_page=1)、[仓库元信息](https://api.github.com/repos/BigCatMidori/IBKR-Dashboard)。

## premium-tracker：Wheel 专项，轻量但维护较旧

README 支持自动识别完成 / 进行中的 Wheel cycles，计算总 P&L、权利金、持有周期和年化；对 short put 抵押金按 ITM/OTM 拆分，计算潜在现金缺口；另有 NAV、TWR、assignment rate、premium capture、AROC。所有 CSV 处理在浏览器，没有后端依赖。

尚未发现真实盘中行情、期权链、Greeks 或通用多腿策略引擎的明确依据。README 的 clone 地址还是 your-username 占位符；README 宣称免 build，但需实际确认当前代码运行方式。更适合尝试现成功能，不宜未经许可澄清就当作许可完备的二开底座。

来源：[README](https://github.com/Marfusios/premium-tracker/blob/main/README.md)、[仓库文件树](https://api.github.com/repos/Marfusios/premium-tracker/git/trees/HEAD?recursive=1)、[元信息 / license=null](https://api.github.com/repos/Marfusios/premium-tracker)、[最新提交](https://api.github.com/repos/Marfusios/premium-tracker/commits?per_page=1)。

## GammaLedger：期权领域功能最丰富，但须看代码而非宣传

README v2 宣称支持 CSP、Covered Call、Bull Put Spread、Bear Call Spread、PMCC、Iron Condor，以及 open/rolled/assigned/closed 生命周期。OFX/QFX 导入和本地浏览器存储，适合交易日志及策略绩效；可先试 [在线应用](https://gammaledger.com/app/)。

关键核实：README 多处写“real-time Greeks”，但实际 [portfolio-greeks.ts](https://github.com/r-brown/GammaLedger/blob/main/src/ui/dashboard/portfolio-greeks.ts) 顶部明确：**Rough Black-Scholes estimate (flat sigma, no live IV)**。代码聚合净 Delta、每日 Theta、Vega，spot 优先 Finnhub cache、其次 leg 快照；不是来自券商的实时期权 IV/Greeks。STOCK legs 被计入 Delta，说明支持策略内股票腿；但 README FAQ 又说普通股票组合追踪是未来项，不应推荐为已经验证的通用股票+期权组合终端。

README 也存在旧“无需构建、直接开 index.html”与 v2 Vite 的描述混杂。[package.json](https://github.com/r-brown/GammaLedger/blob/main/package.json) 当前有 dev/build/build:local 和 TypeScript checks。README 宣称“数据不离开设备”，同时有外部 AI 分析与 Finnhub，不能将这句绝对化；使用外部功能需检查实际发送的数据。

许可以 [LICENSE](https://github.com/r-brown/GammaLedger/blob/main/LICENSE) AGPLv3 为主要依据，package.json 的 ISC 需作者澄清。README 把 AGPL 描述为非商业免费，不能据此解释 AGPL 本身禁止商业使用。

来源：[README](https://github.com/r-brown/GammaLedger/blob/main/README.md)、上述代码/许可链接、[元信息](https://api.github.com/repos/r-brown/GammaLedger)、[最新提交](https://api.github.com/repos/r-brown/GammaLedger/commits?per_page=1)。

## finx-tracker：历史候选，仅作底座参考

portfolio_management → finx-pm → finx-tracker 是 README 指向的迁移链。当前项目目标为从券商导入 trades/positions，让用户声明策略、关联交易并按 portfolio/strategy/group 报 P&L。依赖另一个 finx-reports-ib 项目，不是单一点击安装的应用。最新默认分支 commit 是 2023 年依赖更新，故不建议将其置于省维护方案首位。

来源：[README](https://github.com/westonplatter/finx-tracker/blob/main/README.md)、[最新提交](https://api.github.com/repos/westonplatter/finx-tracker/commits?per_page=1)、[元信息](https://api.github.com/repos/westonplatter/finx-tracker)。

## 搜索排除与研究边界

TradeTracker 搜索多数是同名营销联盟 API 或极小项目，未找到可靠的同名主流股票期权 dashboard，不应仅凭名字推荐。OptionsTracker 同名候选 stars 很少，尚无足够证据优于上列项目。yjthay/ib_dashboard 虽描述涉及期权，但 README 仍为旧 Dash/GCP 教程，部署 Python 3.7 / 2019 依赖，不列推荐。thomasgho/risk-dash 是真实 IBKR live dashboard，README 只确认按策略查看 volatility/beta、需要市场数据订阅，未确认完整期权 Greeks 或交易生命周期，故不扩大其能力范围。
