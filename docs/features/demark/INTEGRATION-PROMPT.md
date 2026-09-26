你正在负责 DeMark 算法研究。请基于已经完成的 A0–A5 底座规划接入，不新建另一套应用。先读根 AGENTS.md、docs/architecture/a2-a5-results.md，以及实际代码；底座完成点是 fc07762，主会话正在新增 moomoo/Wheel 模块。请继续保留你已确认的算法决策，本提示只规定接入方式。

## 模块与调用

正式代码位于 `services/analytics/src/wheelhouse_service/`。将算法放在 `indicators/demark/`，测试放在 `services/analytics/tests/demark/`。公开入口建议 `evaluate_demark(dataset, config) -> DemarkResult`，输入契约可使用独立模型再由小 Adapter 转换现有 Dataset。计算核心是纯 Python，显式接收数据/配置/截止时间；保留 Decimal 精确比较，不自行联网、读写数据库、取系统当前时间或执行交易。

现有调用链为 `sources.py → repository.py → runtime.py → calculation.py → snapshot → HTTP → Wealthfolio`：

- `market.py`：Stream、Bar、StoredBar、Dataset、Rules、Analysis；带 source/venue/symbol/currency/timeframe/session/timezone、revision_id、market_at、knowledge_at。
- `Repository.read` 选择知识截止前最新修订及已收盘 bar；公开 Interface 自己检查排序、重复、gap、形成中排除等不变量。默认只取最近 1,000 根，不能当作长期 Countdown 的完整历史。
- `calculation.py` 当前只有 baseline-v1 的 SMA/此前区间；`runtime.py` 实时/回放共用同一计算入口，并维护采集批次 checkpoint。
- 原始批次与 bar 修订、不可变快照分别保存；不要覆盖旧快照，不能把迟到修订放进旧知识截止。

DeMark 模块输出至少包括：variant/ruleset/参数版本、输入指纹、历史起点和完整性、多 Buy/Sell sequence、Setup 与 Countdown 分离、Perfection、13-vs-8 资格引用、TDST、Risk Level、生命周期事件、bars/elapsed recency 和下根条件。原始序列与评分/跨周期策略解释分层。

## 最小接入方案先写成文档

在 `docs/features/demark/INTEGRATION-PLAN.md` 写出：

1. 独立模块、公开模型、黄金样本及算法验收结果。
2. Rules/Analysis 扩展方式。保持 baseline 和旧 snapshot 可读；新增可选 DeMark 输出或带版本 discriminator 的结果，禁止给旧结果补假值。
3. 历史需求与 replay/checkpoint：确定最小历史需求、历史不足标志、全量/逐根等价；若需增量状态，配置和输入版本改变时失效，不能复用失配 checkpoint。
4. 历史补齐由 source/repository 提供，算法只声明依赖；不要把固定 320/1,000 根当成状态完整性的证明。
5. 接入 `calculation.py` 的小 Adapter、HTTP/OpenAPI 变更、前端生成类型、TD tab 显示方式。
6. 回归兼容清单：fixture/公开源、形成中 bar、缺口、重复、修订重放、旧快照、任务重启和严格知识截止。

## 并行修改约定

你可在自己的 `indicators/demark/`、`tests/demark/` 和 `docs/features/demark/` 工作。主会话拥有新 `portfolio/` 模块及对应页面。共享文件 `market.py`、`calculation.py`、`runtime.py`、`http.py`、`contracts.py`、migration编号、pyproject、OpenAPI/schema、宿主patch、market-page.tsx 先形成具体差异清单，再由用户指定一个会话整合；避免双方同时修改。自行新建文件不等于可改共享入口。

宿主真实 checkout 为 `.local/wealthfolio`，可提交的新增源码在 `integrations/wealthfolio/overlay/`，用 `make sync` 同步；旧根 `backend/` 和 `frontend/` 只作参考。不提交生成目录、个人数据或上游 checkout。

先完成算法与接入设计，是否实施遵循你当前会话用户授权。交付时列出可以直接合入的独立文件、待协调共享文件、通过的测试和未验证假设。DeMark 计数正确性由研究规则与独立黄金样本证明，不能仅凭页面看起来有 9/13。
