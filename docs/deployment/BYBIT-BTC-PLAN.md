# BTC 切换 Bybit 现货

用户已确认 TradingSignal K线与Bybit现货BTCUSDT一致，要求BTC读取Bybit，MU保持币安永续。ETH未要求调整，保持币安永续。沿用当前自动刷新、TD默认入口和闭合K线计算。

- [x] 测试并实现 Bybit V5 spot K线适配：时间周期映射、逆序转正序、已收盘边界、API错误与身份校验，不回退币安/fixture。
- [x] 新增 source=bybit/venue=bybit-spot 隔离存储；默认BTC使用Bybit，ETH/MU仍Binance。旧源快照保留可读。
- [x] 更新前端来源路由、标签、契约；相关测试与构建、同窗历史导出核对。
- [x] 发布test并重算BTC全部周期、验证MU/ETH未改变来源，保存验收记录。

2026-09-28 部署服务器已成功访问官方 `/v5/market/kline?category=spot&symbol=BTCUSDT&interval=60`。来源切换不改算法，不将形成中观察冒充已收盘。

## 验证

- 官方Bybit同窗499根闭合OHLC与用户此前TradingSignal导出499/499完全匹配，最大价差0；同输入v2算法560/560标记匹配，无缺失/多出，Risk Level无差异。证据 `.local/bybit-comparison/`；仅说明该固定样本，不承诺所有实时窗口一致。
- 159项Python测试、17项相关前端测试通过，TypeScript与Ruff通过。排除独立部署分支缺少broker脚本的SDK协议测试，原因同前次发布。
- 独立审查无P1/P2；另补充Bybit429/10006/10016可重试测试。
- 浏览器BTC显示Bybit现货、499根已收盘K线、TDST85005.10；MU/ETH保留币安永续配置。无数据源选择，无模拟回退。

线上部署 `vs7owpv1hbyzeikpnoqnpj3b` 成功，版本 `1f4d9dc`；BTC五周期全部Bybit/fresh，MU/ETH Binance来源保持，外网保护与健康检查通过。
