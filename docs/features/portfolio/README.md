# moomoo / Wheel / Risk 本地使用说明

本阶段按 [计划及自检](PLAN.md) 实施。当前三个页面在 Wealthfolio 的同一侧栏：Brokerage、Wheel cycles、Risk exposure。

## 首次连接

1. `make setup-broker` 安装固定版本官方 `moomoo-api 10.11.7108` 到独立 `.venv-moomoo`。本机已安装并完成导入验证。
2. 从 [moomoo 官方 OpenD 文档](https://openapi.moomoo.com/moomoo-api-doc/en/intro/intro.html) 安装/启动 OpenD，并由账户所有者登录。应用仅访问 `127.0.0.1:11111`；不索取密码、不要求交易解锁。
3. 在 Brokerage 点击 Discover read-only accounts，明确选择 FUTUSG / REAL 的实际 acc_id，输入开始/结束日期，再同步。Disabled 账户不被自动过滤，以便追查迁移前历史。
4. 每次范围最多90天，账户查询之间至少30秒；这是本应用的批次限制，不代表券商只能查90天。费用首批最多20个成交订单；超出或无权限时保持缺失。资金流水按请求起止日期查询创建日期，原始清算/结算日期分别保留；需与券商对账后才能作为完整区间净入金。
5. 检查原始持仓、现金、订单、成交、费用和资金流水。真实合约乘数/Greeks单位不凭代码或显示位数猜测，先在 metadata/observation 表单登记可核实的来源。

2026-09-27 已从官方发布包安装并启动 OpenD GUI 10.11.7108，macOS 签名与公证检查通过；当前停留在登录页，尚未打开 API 端口，因此账户发现、真实账户历史覆盖和余额对账尚未完成。SDK导入与隔离协议测试通过不代表已连接账户。离线时UI显示OPEND OFFLINE，错误不会切换为演示数据。

## Wheel账本

- 明确创建一个 underlying/currency 对应的cycle；从原始成交逐笔分类，或录入有证据的缺失历史/生命周期事件。订单绝不直接进账。
- 每个fill完整归入一个cycle；同一broker fill（含后续修订）不能重复分类。拆分一个fill跨多个cycle目前不支持。
- `buy_open / sell_open / buy_close / sell_close` 明确开平仓，缺少起始lot时拒绝计算。Roll用独立平仓/开仓事件和相同roll group，保留历史。
- `assign / exercise` 按显式期权记录关闭lot并生成实际乘数的股票交割；可关联 underlying delivery fill，防止再次当股票交易导入。本版适用单一股票交付、交付股数等于乘数的合约；多资产/现金组合交付等复杂调整合约需单独建模，不能套此规则。
- `cash_settle` 的price是每股现金结算值，按实际乘数结算并关闭option lot，不生成股票。`expire`以零值关闭，premium不重复加一次。
- 同一时刻的事件使用用户保存顺序；有同秒成交时须按broker顺序逐笔记录。原始记录保留，用户确认UTC时间；不猜测broker无时区字符串。
- FIFO收益政策：option premium单独实现，assignment股票按strike成本，部分平仓按比例释放opening fee。此分析口径不等同税务调整成本基础。已实现、未实现、净现金、premium gross分别展示。
- 费用未知则net结果 unavailable；可增加审计fee overlay。交易或交割记录修订后，关联旧revision的cycle为incomplete，财务汇总暂停，用户通过reconcile填入新revision和核实后的时间/费用。
- cycle open lots与当前持仓快照比较，不一致明确提示，不能把cycle总和声称为完整账户收益。

## 风险

按每标的聚合股数等价Delta/Gamma；Dollar Delta乘标的spot并按FX换入base。quoted Greeks按long-option口径录入，position quantity带符号，multiplier显式。支持per-share/per-contract、Theta per-day/per-year（365）、Vega每vol百分点/每unit volatility（100）转换。

账户持仓、报价、FX超过15分钟或者处于未来时刻不用于完整当前risk。缺字段不填零；整体不完整时组合合计null，完整标的仍可查看。Theta是敏感度，不是保证收益。当前实际moomoo Greeks单位和行情权限未核验，因此不自动使用未标明单位的SDK数值；用户可录入带来源、时间、单位的观察。演示固定在历史时刻计算并明确simulated。

## 存储与安全

独立 `portfolio.sqlite` 与分析数据库相邻，位于忽略提交的 `.local/analytics/`，文件权限0600；migration与DeMark分开。SDK只读子进程有50秒超时，stdout/stderr不转发到服务日志， SDK日志在导入前禁用。无真实数据写入仓库、fixture或Wealthfolio账本；也没有复制到外部分析服务。

## 验证来源

2026-09-27 已核验安装包版本与实际方法：`OpenSecTradeContext(... SecurityFirm.FUTUSG)`、`get_acc_list`、`position_list_query`、`accinfo_query`、`history_order_list_query`、`history_deal_list_query`、`order_fee_query`、`get_acc_cash_flow`。后者是当前SDK方法名，修正旧研究中的 `acc_cash_flow_query`。

- [官方历史成交](https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-history-order-fill-list.html)
- [官方持仓](https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-position-list.html)
- [官方市场快照字段](https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-market-snapshot.html)
- SDK包版本见 `scripts/broker/requirements.lock`，与Web服务依赖隔离。
