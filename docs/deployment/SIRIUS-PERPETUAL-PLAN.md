# Sirius 永续行情改版

开发代号 Sirius（天狼星）。默认进入 `method=td`，市场页固定 Binance USDⓈ-M USDT 永续，移除数据源与手动刷新控件，增加 MUUSDT。

2026-09-28 从部署服务器请求官方 `https://fapi.binance.com/fapi/v1/exchangeInfo`：BTCUSDT/ETHUSDT 为 PERPETUAL，MUUSDT 为 TRADIFI_PERPETUAL（underlyingType EQUITY），三者 quoteAsset/marginAsset USDT、status TRADING。K线改用 `/fapi/v1/klines` 的成交价OHLCV，不使用现货或标记价格冒充。

- [x] 新增测试：永续接口/MU身份、旧现货与永续数据隔离、页面自动刷新/失败恢复/隐藏暂停。
- [x] Stream新增 `binance-usdm-perpetual` venue，Binance默认该venue；保留历史spot模型可读，禁止新永续请求进入旧spot key。fixture仅保留内部测试，用户界面不提供也不回退。
- [x] 市场页固定真实永续与BTC/ETH/MU，默认td；进入后自动请求，页面可见时每60秒刷新，重试受限，服务已有任务时不重复请求；缺失/失败明确显示，不伪装实时。继续仅使用已收盘K线计算DeMark。
- [x] 更新API schema/前端契约、Sirius登录与产品名称；运行测试、构建、三标的真实行情计算与浏览器验收。
- [x] 发布test并核对SHA、接口与真实合约结果，记录限制。

自检：旧行情不能改变venue后复用；后台旧spot任务必须拒绝继续拉取而不能写入永续；MU base_currency=MU。API明确指定fixture仍用于隔离测试，不出现在默认应用。标的失败不回退spot或fixture。


## 验证记录

- 145项Python测试通过；独立部署分支缺少 `scripts/broker/moomoo_reader.py`，与本次无关的SDK协议测试不具备运行文件，明确排除该文件后验证其余全部测试。
- 15项相关市场前端测试、14项钱包测试通过，Ruff及TypeScript检查通过，登录页生产构建成功。
- 真实币安BTCUSDT/ETHUSDT/MUUSDT各499根已收盘小时K线完成DeMark计算，状态fresh。MU日线仅174根，页面明确历史不足，不填充虚构数据。
- 本机无法直连fapi，隔离本地验收服务通过已有SSH服务器抓取真实公开行情后计算；该验收桥接只在忽略提交的.local脚本中。线上直接请求fapi，无该桥接依赖。
- 桌面/390px窄屏浏览器检查MU页面：默认TD、永续标识、无来源/刷新按钮、5个周期自动得到真实结果。截图 `.local/test-deploy/sirius-mu-market.png`。
- 审查发现跨周期面板仍手动刷新；新增失败测试复现后移除按钮，复用60秒自动刷新，提交前检查各周期活动任务，历史快照视图不自动采集。
- 站点根路径和钱包默认返回均进入 `/market-intelligence?method=td`。

最终发布 `usjukgqekfc7q08v8sgsjsb6` 完成，SHA `1fab597f62a2b94ae00c73dc9036f1f5d8d79dae`；线上15组真实永续任务全部成功且fresh，默认入口/登录/匿名API保护检查通过。
