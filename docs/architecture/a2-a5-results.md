# A2–A5 验收结果

核验日期：2026-09-26。验收范围见 [A2–A5 契约](a2-a5-acceptance.md)。本轮完成的是 Wealthfolio + Python 数据与计算架构；完整 DeMark 功能由独立设计会话推进。

| 阶段 | 交付结果 | 验证 |
|---|---|---|
| A2 | 独立 SQLite、校验和迁移、标准化 OHLCV、原始批次、K 线修订和观察记录 | 幂等导入、历史修订选择、空值、形成中数据、旧 schema 升级和重开数据库 |
| A3 | 同一纯计算入口、规则/输入指纹、预热、历史双截止、不可变快照、持久化任务、租约、重试、收盘调度 | 手算 SMA/此前区间样本、回放前缀一致、知识隔离、缺口重置、旧快照保留、租约竞争和有限重试 |
| A4 | Wealthfolio 原生路由内单张 K 线图、方法 tabs、周期、数据源、任务/数据质量、定时刷新、快照和回放 | 类型化 HTTP、运行时校验、错误反馈、浏览器交互和窄屏 |
| A5 | 可复跑的 `verify_a5.py`、CI 启动验证入口、实际公开行情和真实进程恢复测试 | 同源完整链路、重复任务、进程退出自动重启、checkpoint 复用、性能记录 |

## 实际运行证据

本机 macOS 27 ARM64，Python 3.14.6；通过 Wealthfolio 的 `127.0.0.1:1420/api/wheelhouse/v1` 同源代理执行：

- fixture：320 根已收盘 K 线，显示 simulated；重复请求键返回相同任务。
- Binance 官方公开现货接口：319 根已收盘 K 线，fresh；形成中 K 线单独标记并排除。
- checkpoint 保存后实际终止 Python：监督程序重启进程，任务在租约到期后第二次领取完成；批次 ID 保持相同，`ingested` 事件只有一次，旧快照仍可读。
- 1,000 根 K 线摄取、读取、计算及快照保存：0.0516 秒，目标小于 2 秒。该数字不包含外部网络延迟，不是大规模容量保证。
- 详细本机证据保存在 `.local/a5-verification/`，包含时间、环境、计数和耗时，不包含账户信息；目录不提交。

公开 K 线来源于 Binance `/api/v3/klines`，2026-09-26 再次核验官方文档与实际响应。收盘时间由其包含式毫秒边界规范化为下一周期的排除式边界；取得时间在响应到达后记录。

## 数据与回放语义

- 所有数值以规范化十进制字符串保存；价格最多 18 位小数，不能把缺失成交量填为零。
- Stream 区分 source、venue、symbol、base/quote currency、timeframe、session、timezone 和价格编码。首期只接受已支持的 BTC/USDT、ETH/USDT 加密现货 24/7。
- 每个 snapshot 固定输入 revision IDs、规则窗口、engine version、行情截止及知识截止。数据修订只追加，不修改旧 snapshot。
- `as_known` 只能使用知识截止前已取得的版本；`retrospective` 明确使用较晚取得的历史数据，不代表当年的实际信息集。
- 计算和历史查询最多取最近 1,000 根；API 回放必须显式提供两个截止时间，不自动回填缺少的历史数据。
- 基础验证算法是 SMA 和此前 N 根 high/low，预热要求 N+1 根。缺口重置预热并标记 unavailable。原始 DeMark 计数、评分和交易策略没有混入该模块。

## 可恢复运行与限制

- 任务在 SQLite 事务中领取，使用 30 秒租约和所有权 token。中断后过期租约可恢复，过期持有者不能覆盖结果。
- 最多 3 次尝试，失败退避 2 秒、4 秒；保留每次事件与错误码。公开源错误不会切换模拟源。
- 采集完成后保存 checkpoint，恢复任务从该批次继续。定时任务由用户显式启用，周期收盘后 2 秒触发；错过多个周期时只合并一次刷新。
- 开发监督程序每分钟最多自动重启 Python 3 次，重复失败后停止并保留数据。前台约 10 秒检测服务连接，workspace 每 2 秒读取状态。
- HTTP、后台任务和 CLI 均不提供券商交易功能。独立 Python 数据库不读取或修改 Wealthfolio 账户数据库。
- 当前为本地可信单用户开发环境。完整 DeMark/Regime/Breakout、moomoo、股票日历与复权、Tauri 包和远程认证部署仍是后续工作。

## 复跑

```sh
make setup
make dev
# 在另一个终端执行
make check
make build
make verify-a5
.venv-foundation/bin/python scripts/verify_a5.py --live --restart
```

`--restart` 会中断本工作区自己的 Python 进程以验证恢复；不要在执行重要导入时运行。CI 使用 `scripts/ci_a5.py` 启动隔离的本地开发链路并验证 fixture，不依赖外部行情可用性。远端 CI 尚未执行，本机已运行相应检查。
