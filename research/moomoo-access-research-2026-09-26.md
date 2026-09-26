# moomoo 订单、成交和组合读取方案

调研日期：2026-09-26。基于官方在线文档 v10.11、官方 Skills ZIP 内源码，以及社区仓库。本轮未安装服务、未修改 MCP 配置、未登录或读取真实账户。

## 结论

有官方数据接口，也有社区 MCP；不需要先退回截图录入。优先验证官方 moomoo OpenD + moomoo-api SDK 的只读接口，再决定接现成 MCP 还是用官方查询脚本导出 JSON/CSV。MCP 是让 AI 调用接口的包装，不是取得账户数据的唯一方式，也不会自动替现成 dashboard 建好数据映射。

官方当前提供 AI Skills：`install-moomoo-opend` 和 `moomooapi`。本轮查到的是官方 SDK/Skills 和第三方 MCP，未找到官方发布的 MCP server 的明确证据。

## 官方支持的数据

| 数据 | Python 接口 | 重要说明 |
| --- | --- | --- |
| 账户列表 | get_acc_list | 需选择开户券商实体、实盘 REAL 和正确 acc_id |
| 股票/期权持仓 | position_list_query | 数量、方向、币种、市值、成本、浮盈亏；期权数量单位为张 |
| 未结订单和近期订单 | order_list_query | 官方描述包括所有未结订单、24 小时内已成交或撤销订单，不等同全量历史 |
| 历史订单 | history_order_list_query | 订单号、状态、方向、数量、已成交数量和成交均价 |
| 当日成交 | deal_list_query | 逐笔成交，与订单不是一对一关系 |
| 历史成交 | history_deal_list_query | deal_id/order_id、标的、方向、成交价、数量、时间；仅实盘 |
| 资金、现金流、费用 | accinfo_query / acc_cash_flow_query / order_fee_query | 建立完整组合账本还需这些数据，不只读取委托订单 |

官方历史订单/成交查询默认最近 90 天；可传 start/end 查询指定时期。这不是“最多只能查 90 天”的证据。本轮未验证用户实际账户的最早可查日期和数据完整性。两种历史查询均注明单 acc_id 每 30 秒最多 10 次请求。

最新持仓接口还记录了 `show_option_strategy_view`，可返回组合策略维度、combo_id、strategy_type 等字段；历史订单也有 combo_legs。能否覆盖用户所在地区、账户以及使用的 SDK/OpenD 版本，需实测；旧 MCP 可能没包装这些新参数。

官方 QA 特别说明：从单市场账户迁移到综合账户后，历史订单/成交可能仍在旧的 DISABLED 账户，查询全部历史时不能只取 ACTIVE 账户。

## 前提与推荐实施方式

1. 本机安装并运行官方 moomoo OpenD，用户本人完成登录及首次 API 问卷/协议。
2. SDK/查询工具连本机 OpenD，通常为 `127.0.0.1:11111`。持续同步时网关需运行。
3. 区分开户主体与交易市场：例如新加坡开户也可能交易美股；不能把 TrdMarket.US 当成美国开户实体。
4. 只开放账户、持仓、订单、成交、资金等读取工具即可满足本次目标。官方查询示例和 Skills 查询脚本没有前置调用 unlock_trade；下单相关解锁不是读取流程的目标。
5. 先读取账户列表和一小段成交，与 App 对账，再建立导出或同步流程。进入 dashboard 时还要处理期权代码、乘数、开平仓、币种和费用映射。

官方支持表列出了 moomoo US、SG、AU、MY、CA、JP 等实体的美股/美股期权交易能力，但其他市场存在区别；需要用户确认开户地区，不能据此保证每个资产、权限和接口全覆盖。行情权限和读取自己的账户记录是不同问题；实时期权行情/Greeks 需另查行情权限，不能因为能读成交就推断实时行情免费可用。

## 官方 Skills 源码核验

从官方 ZIP 在内存中读取文件，没有安装或执行其中脚本。存在：

- `skills/moomooapi/scripts/trade/get_accounts.py`
- `skills/moomooapi/scripts/trade/get_portfolio.py`
- `skills/moomooapi/scripts/trade/get_all_portfolios.py`
- `skills/moomooapi/scripts/trade/get_orders.py`
- `skills/moomooapi/scripts/trade/get_history_orders.py`
- `skills/moomooapi/scripts/trade/get_order_fill_list.py`
- `skills/moomooapi/scripts/trade/get_history_order_fill_list.py`
- `skills/moomooapi/scripts/trade/get_order_fee.py`
- `skills/moomooapi/scripts/trade/get_acc_cash_flow.py`

`get_history_order_fill_list.py` 调用 `history_deal_list_query`，支持 --start/--end、--acc-id、--trd-env、--security-firm、--json；官方包有查询脚本可复用，无需从零编写全部 API 调用。整个 Skills 包也含下单/改单/撤单脚本，不能把整个包称为只读包。

## MCP 候选

详细代码核验见 [社区候选报告](moomoo-mcp-candidates.md)。简要结果：

- [Litash/moomoo-api-mcp](https://github.com/Litash/moomoo-api-mcp)：约 30 stars；支持账户持仓、订单、成交和历史查询，但也有实盘下单/改单/撤单；不宜原样用于只读看板。Apache-2.0。
- [iwanbk/moomoo-mcp](https://github.com/iwanbk/moomoo-mcp)：约 1 star；Go，当前版本只读，覆盖账户/持仓/历史订单/成交，适合作为候选，但成熟度有限，需检查券商实体和实盘开关的具体实现。
- [kimtaedoo/moomoo-api-read-only-mcp](https://github.com/kimtaedoo/moomoo-api-read-only-mcp)：名字相关，但 get_trades 是市场逐笔行情，不是个人订单成交；不满足这次读取个人账户的目标。

## 兜底方案

如果 API 无法适配账户或用户不想配置 OpenD，优先用该地区 App/桌面版提供的成交导出或账单文件（具体入口及 CSV/PDF 格式待账户地区确认），再考虑截图。

截图可以录入当前组合快照，也可以逐笔抄录成交，但持仓截图本身不能还原完整历史收益。期权需完整标的/合约代码或标的+到期日+行权价+Call/Put、多空方向、张数、成本/成交价、币种、时间；无法看清的字段标待确认。区分委托价与实际成交价，按订单号/成交号或截图重叠行去重。

## 官方来源

- [OpenAPI 简介与支持地区/市场](https://openapi.moomoo.com/moomoo-api-doc/en/intro/intro.html)
- [权限与额度](https://openapi.moomoo.com/moomoo-api-doc/en/intro/authority.html)
- [官方 AI Integration & OpenClaw / Skills](https://openapi.moomoo.com/moomoo-api-doc/en/intro/ai.html)
- [官方 Skills ZIP](https://openapi.moomoo.com/skills/opend-skills.zip)
- [持仓接口](https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-position-list.html)
- [订单接口](https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-order-list.html)
- [历史订单](https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-history-order-list.html)
- [历史成交](https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-history-order-fill-list.html)
- [账户选择与迁移历史 QA](https://openapi.moomoo.com/moomoo-api-doc/en/qa/trade.html)
