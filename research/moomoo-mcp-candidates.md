# moomoo MCP 候选源码核验

核验日期：2026-09-26。仅读取公开仓库与源码，未安装、运行、登录 OpenD 或连接真实账户。账户地区与官方 API 权限另见主调研。

## 结论

存在可读取个人持仓、当日订单、历史订单和成交的第三方 MCP，不必先走截图录入。三个候选中，`iwanbk/moomoo-mcp` 当前源码只读且功能匹配；`Litash/moomoo-api-mcp` 更受关注、同样提供查询，但也默认注册交易写工具；`kimtaedoo/moomoo-api-read-only-mcp` 只有市场行情，名字虽然只读，却无法读取个人账户。

这些都是社区项目，不是已核实的 moomoo 官方 MCP。共同需要本地或可访问的 OpenD 网关；MCP 本身不是完整投资组合 Dashboard。

| 项目 | 持仓/资产 | 当日订单/成交 | 历史订单/成交 | 写入能力 | 维护与许可 |
|---|---|---|---|---|---|
| [iwanbk/moomoo-mcp](https://github.com/iwanbk/moomoo-mcp) | 有 | 有 | 有 | 当前无下单工具 | 1 star；最新发布 v0.2，2026-07-16；README/LICENSE 明示 Apache-2.0（GitHub API 识别为 Other） |
| [Litash/moomoo-api-mcp](https://github.com/Litash/moomoo-api-mcp) | 有 | 有 | 有 | 默认含下单、改单、撤单 | 30 stars；main 最后提交 2026-05-03；最新 release v0.1.8，2026-04-12；Apache-2.0 |
| [kimtaedoo/moomoo-api-read-only-mcp](https://github.com/kimtaedoo/moomoo-api-read-only-mcp) | 无 | 无个人账户数据 | 无 | 仅行情只读 | 0 stars；最后提交 2026-04-15；未发现 release 或 LICENSE |

stars 仅是本次 API 快照，不代表质量或已做实盘验证。源码核验针对 main 的下列 commit，不保证旧 release 已包含 main 的全部能力。

## 1. iwanbk：功能最匹配的只读候选，但规模很小

核验 commit：`cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96`。

- [README](https://github.com/iwanbk/moomoo-mcp/blob/cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96/README.md) 提供 macOS/Linux/Windows 预编译发行说明，要求先运行并登录 OpenD，默认 `127.0.0.1:11111`，MCP 走 stdio。
- [orders.go 工具注册](https://github.com/iwanbk/moomoo-mcp/blob/cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96/internal/tools/orders.go#L36) 实际注册 `get_orders`、`get_deals`、`get_history_orders`、`get_history_deals`。
- [底层 orders.go](https://github.com/iwanbk/moomoo-mcp/blob/cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96/internal/moomoo/orders.go#L129) 实际调用 SDK 的当日订单、成交、历史订单、历史成交接口，并传入历史日期过滤。
- `GetOpenOrderListWithContext` 名称容易令人误会仅限 open orders，但[依赖源码](https://github.com/hyperjiang/futu/blob/v1.7.0/sdk_ctx.go#L205) 实际调用 `TrdGetOrderList`，没有附加订单状态过滤。不能仅根据函数名断言只返回未完成订单。
- [trade.go](https://github.com/iwanbk/moomoo-mcp/blob/cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96/internal/moomoo/trade.go#L246) 实际实现 GetPositions；其 Position 结构包含代码、名称、方向、数量、价格、成本、市值和盈亏，但没有专门的 Greeks 或多腿组合字段，不能当作完整期权风控模型。
- [trading.go](https://github.com/iwanbk/moomoo-mcp/blob/cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96/internal/tools/trading.go) 只有 package 声明，交易工具未实现。README 明确列为以后计划，未来升级需重新核验只读性。
- [go.mod](https://github.com/iwanbk/moomoo-mcp/blob/cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96/go.mod) 依赖社区 Go SDK `github.com/hyperjiang/futu v1.7.0`，不是官方 Python `moomoo-api`。

### 需要注意的实盘开关

[config.go](https://github.com/iwanbk/moomoo-mcp/blob/cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96/internal/config/config.go#L28) 用 `MOOMOO_TRADE_PASSWORD` / `_MD5` 是否为空决定 `SimulateOnly`；[tradeHeader](https://github.com/iwanbk/moomoo-mcp/blob/cfa9be96eb5183fc100bbd3d7d5849ffbe8dde96/internal/moomoo/trade.go#L174) 拒绝在 SimulateOnly 时查 REAL。

这是该项目自己的软件开关。README 明确说目前不将密码传给 OpenD、不会解锁交易。因此不能据此声称“moomoo 官方要求读取账户必须提供交易密码”。若采用，建议先把此开关改为显式允许只读实盘的布尔配置，避免为只读查询存入无实际用途的真实交易密码。没有做此修改或运行验证。

## 2. Litash：查询齐全，但不应原样当只读 MCP

核验 commit：`18a91eb954bd4095bf9971fb80c9ddf81e7f7793`。

- [account.py](https://github.com/Litash/moomoo-api-mcp/blob/18a91eb954bd4095bf9971fb80c9ddf81e7f7793/src/moomoo_mcp/tools/account.py#L105) 注册持仓查询、账户资金、账户摘要等工具。
- [trading.py](https://github.com/Litash/moomoo-api-mcp/blob/18a91eb954bd4095bf9971fb80c9ddf81e7f7793/src/moomoo_mcp/tools/trading.py) 实际注册四种订单/成交查询，也注册 `place_order`、`modify_order`、`cancel_order`。工具参数默认 `trd_env="REAL"`。
- [trade_service.py](https://github.com/Litash/moomoo-api-mcp/blob/18a91eb954bd4095bf9971fb80c9ddf81e7f7793/src/moomoo_mcp/services/trade_service.py#L554) 实际调用官方 Python SDK 的 `order_list_query`、`deal_list_query`、`history_order_list_query`、`history_deal_list_query`。
- [server.py](https://github.com/Litash/moomoo-api-mcp/blob/18a91eb954bd4095bf9971fb80c9ddf81e7f7793/src/moomoo_mcp/server.py#L35) 会尝试使用环境变量自动 unlock；同文件末尾无条件 import trading 工具模块。
- [pyproject.toml](https://github.com/Litash/moomoo-api-mcp/blob/18a91eb954bd4095bf9971fb80c9ddf81e7f7793/pyproject.toml#L34) 依赖 `moomoo-api>=3.3.0`，本地服务连接 OpenD。

交易工具文案要求 AI 在操作前确认，但这不是技术层面的只读隔离。若选此项目，应限制注册的工具为账户和订单查询，并去掉自动解锁路径。未安装或修改上游项目。

## 3. kimtaedoo：仅行情，不满足读取个人订单

核验 commit：`f51ca213a9ee8d5f9ec275c18a9067d0875be738`。

- [server.py](https://github.com/kimtaedoo/moomoo-api-read-only-mcp/blob/f51ca213a9ee8d5f9ec275c18a9067d0875be738/src/moomoo_api_read_only_mcp/server.py) 仅注册 health_check、get_quote、get_order_book、get_candles、get_trades、get_market_status。
- [client.py](https://github.com/kimtaedoo/moomoo-api-read-only-mcp/blob/f51ca213a9ee8d5f9ec275c18a9067d0875be738/src/moomoo_api_read_only_mcp/client.py#L191) 的 `get_trades` 调用 `OpenQuoteContext.get_rt_ticker`：这是证券市场逐笔成交，不是用户的订单成交。
- [pyproject.toml](https://github.com/kimtaedoo/moomoo-api-read-only-mcp/blob/f51ca213a9ee8d5f9ec275c18a9067d0875be738/pyproject.toml) 使用 Python `moomoo-api>=9.4.5408`；源码没有 OpenSecTradeContext 或账户工具。

## 建议

先核实账户所属券商实体及 OpenAPI 可访问性，再试只读 MCP。若目标是仪表盘日常同步，直接复用这些项目底层查询接口定时落库同样可行，MCP 主要解决助手交互读取。读取已执行成交记录比只读取委托订单更适合还原投资组合；期权到期、行权/指派、手续费、现金流水和合约乘数仍需单独验证，不能仅凭订单列表推定完整组合账务。
