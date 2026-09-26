# moomoo SG 只读接入、Wheel 账本与组合风险计划

2026-09-27。用户授权开始第 2、3 项，先计划、自检、实施。采用 ask-matt 主流程：基于既有需求形成规格和本地依赖任务，再用公开接口测试逐片实现，最后规范/规格两轴审查。用户已授权连续实施，无需每个内部步骤重复确认。

## 目标与范围

在真实 Wealthfolio 宿主增加 Brokerage、Wheel cycles、Risk exposure 页面，支持官方 OpenD 只读账户选择、持仓/现金/订单/成交采集；数据仅存在本机。Wheel 账本支持显式 cycle 分配、股票与短期权 FIFO、部分成交、滚仓、到期、指派/行权事件、费用及现金流分列。Greeks 按标的聚合，缺少乘数、报价、FX 或完整历史时结果明确不完整。

真实 OpenD 未运行（2026-09-27，本机11111端口未监听）。只能由用户在官方 OpenD 完成登录。本轮完成连接能力及断连处理，真实账户历史覆盖和对账仍取决于登录及权限；不能宣称已接通。测试用 fictional account，独立演示空间；模拟数据不会写进真实账户。

## 实施决策

- 正式 Python 包新增独立 portfolio 子模块；独立 portfolio SQLite，避免抢占 DeMark/行情 migration 编号；Wealthfolio 账本继续由其原模块拥有，此模块是只读券商镜像与策略分析，不自动双写上游账本。
- moomoo 官方 SDK 在独立子进程/虚拟环境运行，避免其 protobuf/pandas 依赖影响 FastAPI 服务。仅使用固定白名单查询，FUTUSG + REAL，按 acc_id 显式选择，连接限定loopback，设置子进程超时；SDK输出/错误不得带账户数据进日志。
- 每次导入保留原始采集及时间，按 broker/source/account/record type/record id 去重与保留修订。订单绝不当成交；持仓是快照；资金流水不自动变成交易；费用只在明确关联时进入盈亏。
- 合约元数据是显式输入：类型、underlying、币种、到期、strike、multiplier。不通过字符串猜非标准交割。元数据或费用缺失保持 null/unresolved；无法安全归一化的记录保留并显示待映射。
- 账本采用显式 cycle event 的 FIFO，premium gross、净现金、realized/unrealized、费用分开。现金结算/到期事件无重复 premium。指派需显式引用期权及股票两条事件，股票按strike计成本，期权 premium 独立实现；报表说明此方法非税务成本基础。
- 覆盖不足时不以当前快照伪造起始交易。未知开平、缺起始lot、费用、期权元数据阻止确定性盈亏。关联和生命周期补充作为带作者/理由/时间的本地 overlay，不覆盖 broker 原值。
- Greeks 仅对已给定单位和时效的报价计算；long-contract per-share规范化，quantity带符号，乘数实际值。Delta/Gamma按underlying；dollar delta乘spot及FX；Theta为每日敏感度、Vega为每vol百分点。缺任何required输入给出partial/incomplete，不能填0。

## 顺序与公开测试接口

1. 连接与镜像闭环：配置检测 → 账户列表 → 显式选择 → 同步 → 原始/归一化记录 → 宿主页。公开只读适配器与HTTP测试断连、账户/firm/env、超时、拒绝交易调用。
2. Wheel账本闭环（依赖1）：导入成交 → 显式cycle及事件 → FIFO计算 → timeline/summary。公开账本Interface用手算黄金样本验证。
3. 风险闭环（依赖1）：持仓/报价/元数据 → 规范化Greeks → 每标的和组合显示。公开风险Interface验证short sign、multiplier、FX、stale和缺值。
4. 验收（依赖2、3）：浏览器、类型、全测试、SDK真实环境前提、两轴审查、提交。真实账户若无OpenD，交付明确操作入口与连接状态，不伪造验收通过。

## 自检（实施前）

- [x] 已按官方SDK/文档核验版本与只读入口；交易环境REAL不是交易授权。
- [x] 发现本机无OpenD，本轮实现与真实验收分离，不索取密码。
- [x] 重复导入、费用重复扣除、指派重复收入、非标准乘数、FX缺失均纳入测试。
- [x] 不用持仓快照反推完整历史；真实元数据缺失不会被fixture默认值替代。
- [x] 与DeMark独立目录/独立存储；共享http/宿主patch/OpenAPI由本会话统一整合。
- [x] 停止开发自动交易能力；所有用户“动作”均是本地分类/分析记录。

自检结论：可开始实施。主要风险是实际OpenD和账户覆盖未验证，以及SDK不能保证完整呈现指派/到期语义；采用显式补充事件、来源保留和不完整标识处理。

## 实施后说明

代码及本地验收已完成，详见 [使用说明](README.md) 和 [验收/审查](VERIFICATION.md)。真实连接验收受OpenD未运行限制，保持待验证。新增成交修订待复核流程、显式同秒顺序与cash_settle来自审查修正，未扩展交易执行能力。
