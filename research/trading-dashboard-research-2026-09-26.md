# 自用股票与期权组合 Dashboard 选型

调研日期：2026-09-26。目标：采用现成产品或轻量改造，查看自己的股票、期权持仓和组合表现。暂按美股/美股期权场景；券商、交易市场、是否需要实时 Greeks 尚待确认。未安装运行这些项目，也未连接真实账户；结论基于官方 README、发布记录、代码和 GitHub 元数据。

## 结论

1. **一般情况先试 Wealthfolio**：现成桌面安装包、Docker/web、多账户、收益统计、CSV 导入；已经有期权及显式开平仓支持。适合做自用组合总览，也有 addon 扩展点。
2. **如果用 IBKR，而且日终更新足够，试 BigCatMidori/IBKR-Dashboard**：直接处理 IBKR 账单，自动 Flex 日更、股票和期权按标的汇总、识别部分多腿组合；代码轻，改造入口直观。社区很小，非商业源码可用许可证，不能当作成熟大项目。
3. **如果主要做股票长期配置，可选 Ghostfolio 或 Portfolio Performance**；目前核验的资料不足以把它们推荐为完整期权风险台。
4. **若需求是实时 Delta/Gamma/Theta/Vega、价差策略、保证金与情景损益，以上结论不代表开箱即用**。需先确认券商数据与策略分析能力。OpenBB 可作为数据基础设施，但不等同于现成的个人券商组合产品。

## 候选对比

| 项目 | 最适合 | 已核验能力 | 数据/部署 | 主要边界 |
| --- | --- | --- | --- | --- |
| [Wealthfolio](https://github.com/wealthfolio/wealthfolio) | 默认首选；个人资产总览 | 多账户、多币种、TWR/MWR；期权合约表单；卖出开仓/买入平仓等；插件扩展 | macOS/Windows/Linux、iOS、Docker/web；免费手工/CSV；可选付费 Connect 券商同步 | 未核实完整多腿策略与组合 Greeks；同步覆盖需按券商及资产类型确认 |
| [IBKR Dashboard](https://github.com/BigCatMidori/IBKR-Dashboard) | IBKR 股票+期权，日终看板 | 净值/回撤/收益；按标的汇总衍生品；当前持仓/FIFO；部分期权组合识别；中英文 | Activity/Flex CSV，Flex Web Service 每日抓取；Python/Flask/SQLite，静态 HTML 导出 | 仅 4 stars；账单快照非实时行情；非美元标签、跨基础币种合并有限制 |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | 股票/ETF 为主的 Web 资产看板 | 多账户、交易导入导出、收益图表、资产风险分析 | Docker；Angular/NestJS/PostgreSQL/Redis | README 聚焦股票/ETF/crypto，未找到足够证据证明完整期权生命周期/Greeks |
| [Portfolio Performance](https://github.com/portfolio-performance/portfolio) | 长期绩效记账、偏好成熟桌面软件 | 组合绩效，IBKR Flex 导入；导入代码处理 OPT/FOP 和乘数 | 桌面软件，官方手册与导入体系 | 导入期权交易不等于期权策略风险台；本轮未验证短期权/指派/多腿端到端正确性 |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | 后续接行情和研究数据 | Python/REST 数据基础设施，可接 Workspace | Python/FastAPI；Workspace 是单独的 UI 产品 | 不能把 GitHub 数据平台当成已接通个人券商持仓的完整看板 |

## Wealthfolio：值得先试，但需要区分证据版本

- [README](https://github.com/wealthfolio/wealthfolio#readme)说明本地保存、无需账户的基本使用方式，手工/CSV 免费；Connect 是可选订阅，声明支持 30+ 机构、只读券商同步。**这不保证用户的券商、市场及期权同步都覆盖，也不证明同步为实时。**
- [v3.8.0 发布记录](https://github.com/wealthfolio/wealthfolio/releases/tag/v3.8.0)于 2026-09-07 发布；提供持仓未实现盈亏、合约乘数编辑等改进。
- [PR #1194](https://github.com/wealthfolio/wealthfolio/pull/1194)已于 2026-06-29 合并，明确实现 signed lots、期权 BTO/STO/BTC/STC、股票显式做空和对应 FIFO/P&L。这比尚未勾选 short positions 的 ROADMAP 更可靠。
- [v3.8.0 shortability_policy.rs](https://github.com/wealthfolio/wealthfolio/blob/v3.8.0/crates/core/src/portfolio/snapshot/shortability_policy.rs)允许期权及股票类资产负持仓，股票需显式 short intent。[发布版期权表单](https://github.com/wealthfolio/wealthfolio/blob/v3.8.0/apps/frontend/src/pages/activity/components/forms/fields/option-contract-fields.tsx)包括标的、执行价、到期日、Call/Put。
- [期权 short 设计文档](https://github.com/wealthfolio/wealthfolio/blob/main/docs/features/short-selling/signed-option-shorts-design.md)把多腿策略建模、行权/指派自动化列为 Non Goals。它是 target design，部分内容已被后续实现超越；本轮不能仅凭它认定所有当前能力。对这些高级能力应标“未证实可用”，而非承诺支持。
- [Issue #400](https://github.com/wealthfolio/wealthfolio/issues/400)仍开放，报告期权合约币种错误；这是用户报告，不代表所有账户都受影响。跨币种持仓应在试用时抽样核对。
- [Addon 文档](https://github.com/wealthfolio/wealthfolio/blob/main/docs/addons/index.md)是未来定制入口。优先以扩展方式新增页面，避免一开始长期维护大型 fork。

## IBKR Dashboard：很贴近需求，但只作为条件推荐

依据 [README](https://github.com/BigCatMidori/IBKR-Dashboard#readme)：

- Flex CSV 携带官方日净值、汇率、分类现金流、逐日 MTM；配置 Flex Web Service 后定时抓取增量账单。它不是 TWS 实时持仓/实时 Greeks。
- 当前持仓来自各账户最新账单；同标的的腿折叠，能识别部分期权组合。不要把“组合识别”理解成完整策略生命周期或情景分析。
- 提供无真实账户的 demo 生成脚本及静态导出，适合先看 UI，再导入自己的小样本。
- 已知限制：非 USD 基础币种数字按基础币种计算，但 UI 仍标 USD；不同基础币种子账户不允许合并。历史账单不全也会影响区间与累计展示。
- [许可证](https://github.com/BigCatMidori/IBKR-Dashboard/blob/main/LICENSE)是 PolyForm Noncommercial 1.0.0，允许个人非商业使用；不是 OSI 开源许可证。

## 维护与许可快照

GitHub 元数据是调研当时快照；pushed_at 只说明仓库有推送，不代表稳定版发布日期或质量保证。

| 项目 | Stars（约） | 最近推送 UTC | 最新已核验 release | 许可证 |
| --- | ---: | --- | --- | --- |
| Wealthfolio | 9,055 | 2026-09-25 | v3.8.0 / 2026-09-07 | AGPL-3.0 |
| Ghostfolio | 9,350 | 2026-09-24 | 3.72.0 / 2026-09-20 | AGPL-3.0 |
| Portfolio Performance | 4,076 | 2026-09-22 | 0.87.0 / 2026-08-16 | EPL-1.0 |
| IBKR Dashboard | 4 | 2026-09-09 | 本轮未核验 | PolyForm Noncommercial |
| OpenBB | 73,468 | 2026-09-26 | 本轮未核验 | README 声明 AGPLv3；GitHub API 识别为 Other，具体组件再核对 |

元数据来源：[Wealthfolio API](https://api.github.com/repos/wealthfolio/wealthfolio)、[Ghostfolio API](https://api.github.com/repos/ghostfolio/ghostfolio)、[PP API](https://api.github.com/repos/portfolio-performance/portfolio)、[IBKR Dashboard API](https://api.github.com/repos/BigCatMidori/IBKR-Dashboard)、[OpenBB API](https://api.github.com/repos/OpenBB-finance/OpenBB)。

## 其他一手来源

- [Portfolio Performance 官方手册](https://help.portfolio-performance.info/en/)
- [PP IBKR Flex 导入源代码](https://github.com/portfolio-performance/portfolio/blob/master/name.abuchen.portfolio/src/name/abuchen/portfolio/datatransfer/ibflex/IBFlexStatementExtractor.java)：OPT/FOP 分类、multiplier 与期权符号处理。
- [Ghostfolio README](https://github.com/ghostfolio/ghostfolio#readme)：功能、技术栈、Docker、导入 API；[期权请求 #968](https://github.com/ghostfolio/ghostfolio/issues/968)关闭本身不能证明已实现。
- [OpenBB README](https://github.com/OpenBB-finance/OpenBB#readme)：明确区分 Open Data Platform 与 OpenBB Workspace。

## 最省开发的验证顺序

1. 确认券商及市场，再确定需要日终组合统计还是盘中风险。
2. 先安装 Wealthfolio 稳定版，用少量历史交易试导入：股票买卖、期权买入平仓、卖出开仓平仓、过期、指派及跨币种各选实际存在的样本。
3. 核对数量/正负方向、合约乘数、币种、现金、已实现和未实现损益。能够导入不代表统计一定正确。
4. IBKR 用户同步试轻量 IBKR Dashboard demo/账单导入，比较组合视图与录入成本。
5. 只有现成软件缺少明确的一两个视图时才扩展；若缺的是实时数据/完整策略模型，应重新选型，避免把“加个页面”变成重写系统。

期权专项补充见同目录 `options-dashboard-candidates.md`。
