# 2026-09-28 Sirius 永续行情发布

- 版本：`1fab597`；部署ID：`usjukgqekfc7q08v8sgsjsb6`。
- 上一运行版本：`835d7b5`。
- 状态：2026-09-28 07:00 UTC 部署成功；实际镜像SHA `1fab597f62a2b94ae00c73dc9036f1f5d8d79dae`。
- 默认入口：`/market-intelligence?method=td`。

## 行为

开发代号 Sirius（天狼星）。页面固定 Binance USDⓈ-M USDT 永续，不显示数据源选择和手动刷新按钮；支持BTCUSDT、ETHUSDT、MUUSDT。主图进入即加载，页面可见时60秒自动刷新；跨周期按收盘时间/缺失状态自动补齐，失败后有界重试，活动任务不重复入队。历史快照不自动刷新。

使用官方 `/fapi/v1/klines` 成交价K线；DeMark只处理已收盘K线。旧spot数据保留且按venue隔离，不转换成永续；旧spot采集请求拒绝，不能向spot键写永续数据。fixture只保留内部测试能力，界面没有入口、不回退假数据。没有删除数据或数据库迁移。

官方exchangeInfo核验：BTC/ETH为PERPETUAL，MU为TRADIFI_PERPETUAL股权类合约；三者USDT计价和保证金，TRADING。核验日期2026-09-28。

## 验证

145项Python测试、15项市场前端测试、14项钱包测试通过；Ruff、TypeScript与登录构建通过。SDK协议测试因独立部署分支缺少broker脚本而排除，与本次改动无关。

三个标的真实1h数据各499根已收盘K线成功计算DeMark并返回fresh；本地浏览器额外核验MU全周期自动加载、桌面及390px布局。MU日线只有174根已收盘历史，准确显示历史不足，不补假数据。

独立审查发现跨周期面板原先只自动一次且保留刷新按钮，已补测试后修复为自动周期刷新。测试截图主工作区 `.local/test-deploy/sirius-mu-market.png`。


## 线上完成验收

- 默认根路径302至 `/market-intelligence?method=td`；Sirius登录页和资源200，SIWE声明更新为Sirius。
- 匿名API401、无Basic challenge、broker403，钱包认证保持。
- 通过线上analytics HTTP任务队列实际拉取BTCUSDT/ETHUSDT/MUUSDT × 5m/15m/1h/4h/1d，共15组，全部succeeded、fresh、DeMark非空，venue均为binance-usdm-perpetual。
- 14组结果各499根已收盘K线，MU1d为174根；结果已保存到test正常业务库，全部为官方公开行情，无模拟回退。
- web、wallet-auth、analytics运行镜像与目标SHA一致，Coolify完成。
