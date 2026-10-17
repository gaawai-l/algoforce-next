# 发布流程

## 当前方式

test 沿用手动 Coolify 发布。环境、应用、URL 和首次验收记录见 [test 环境](coolify-test.md)；构建定义以 [Dockerfile](../../deploy/test/Dockerfile) 和 [Compose](../../deploy/test/compose.yaml) 为准。

发布链路：开发提交 → 集成到 `codex/test-environment` → 正常 push → Coolify 手动 Deploy → 服务器构建 → 外网验收。

Coolify 在 OPENSTEP_Vultr 拉取仓库并构建 web、analytics 和 wallet-auth 镜像，镜像保存在该服务器。前端构建包含本仓库 overlay；analytics 镜像安装本仓库 Python 包，包含选定提交中的 DeMark 计算逻辑。Wealthfolio 后端使用固定 digest 的官方镜像。当前没有向镜像仓库推送自建镜像，也没有 GitHub Actions 自动发布；后续可另行建设 CI 和镜像仓库。

## 每次发布

1. **确定范围。** 用户要求发布 test 后，先列出本次功能、来源提交、配置及数据库影响和验证计划，自检范围是否完整。开发 agent 应交付已提交代码、测试结果及已知限制；其他 agent 尚未完成的工作留在原工作区。
2. **组装候选。** 读取远端发布分支和 Coolify 实际运行 SHA，记录上一可用版本。在干净、独立的 checkout/worktree 中基于现有 `codex/test-environment` 集成已评审提交及必要依赖，保留该分支上的部署修正。检查最终差异，不把主工作区全部未提交文件打包发布。`scripts/deployment/snapshot_test.py` 仅用于首次创建分支，已有分支时会退出，不用于日常发布。
3. **验证候选。** 在候选代码上运行 `make check`、`make build` 及本次功能验收；按项目脚本准备依赖。涉及 API 变更时核对生成的 OpenAPI/前端类型与实现一致。检查镜像构建白名单覆盖必要源码，排除凭据、数据库和本地运行文件。涉及数据库迁移时先取得一致性备份并确认恢复方法；SQLite 使用备份接口或停写后备份，不直接复制正在写入的数据库文件。通过后记录候选完整 SHA。
4. **发布。** 正常 push 现有发布分支，在同一 Coolify test 应用触发 Deploy。协调发布期间分支不再前移，核对部署日志中的实际源码 SHA 等于候选 SHA；不一致时重新核实，不能把别的版本当作本次发布成功。服务器按 Dockerfile 构建并替换服务，保留 test 命名卷。已有部署正在运行时先查看状态，避免重复触发。
5. **外网验收。** Coolify 构建成功后运行下方验收脚本，并在浏览器检查本次改动页面及关键交互。涉及 DeMark 时确认任务完成、结果可展示、数据源和模拟/真实行情状态准确。只看到 Running 或健康接口成功不足以完成发布。
6. **记录交付。** 在发布记录中写明时间、变更范围、来源提交、实际部署 SHA、Coolify deployment ID、访问 URL、验证结果、迁移/配置影响、上一可用版本及已知问题。凭据保留在私有配置中。向用户报告实际结果；构建或验收失败则说明失败阶段，不能声称已上线成功。

外网验收使用安装了 `httpx` 的 Python 环境，从候选仓库根目录执行（替换 URL 与私有凭据文件路径）：

```sh
python deploy/test/verify.py 'https://<test-domain>'
# 完整业务验收使用合法钱包会话，私有文件包含 session_cookie：
python deploy/test/verify.py 'https://<test-domain>' --session-file '/absolute/private/session.json'
```

脚本默认检查登录页、匿名 API 401（无 Basic challenge）、跨源请求和 broker sync 被阻止。提供合法钱包会话时进一步检查认证访问，并创建一个 fixture 分析任务验证 DeMark 返回值。此任务会写入 test 模拟数据；浏览器功能验收仍需按本次改动补充。

## Perps 采集（永续状态）

analytics 服务内常驻 perps 的 REST worker 和 WebSocket 采集器，由 `WHEELHOUSE_PERPS` 控制，默认开启（`0`/`false`/`off` 关闭）。

- **出站网络**：需要放行到 `fstream.binance.com` 和 `stream.bybit.com` 的 WSS，以及到 `fapi.binance.com`、`data.binance.vision`、`api.bybit.com` 的 HTTPS。
- **停机**：Compose 给 analytics 设了 `stop_grace_period: 30s`。收到 SIGTERM 后，worker 在下一个请求前放弃本轮（在途请求最长 20 秒），采集器同时关闭连接并结束覆盖区间（最长 8 秒）。
- **部署后检查**：用合法钱包会话（与 `verify.py --session-file` 相同）请求 `/api/wheelhouse/v1/perps/status`：
  - `collectors` 中 3 个流都是 `live: true`；
  - 各流的 `problems` 是本进程启动以来的计数（`rotated`、`stopped` 属正常生命周期，其余如 `stalled`、`half_open`、`connect_failed`、`coverage_split` 是故障或空洞），用来解释覆盖空洞；
  - 运行一天后，`direction_check.bybit_qty.events` 应在增长；
  - `hosts` 中没有持续的 `error`。
  `deploy/test/verify.py` 不检查这些项目，需要手动核对并写进发布记录。
- **覆盖空洞**：每次重新部署 analytics 都会让两条连接同时断开，至少留下一个未覆盖的块。在采集满 7 天之前（spec 的起步门槛），尽量把 analytics 的部署攒在一起做，减少空洞。

## 规则开关（`WHEELHOUSE_RULES`）

analytics 在原版（v1）规则之上提供可选规则 O1–O6，由 `WHEELHOUSE_RULES` 选择：

- 逗号分隔的代号 `O1`–`O6`，大小写不敏感，忽略空白和重复，例如 `O1,O4`；
- 未设置或为空字符串时取默认值，即全部开启（compose 容易意外产生空字符串，所以空值不表示全部关闭）；
- 单独写 `v1` 表示全部关闭；`v1` 与其他代号同时出现，或出现无法识别的值（包括多余的逗号），服务启动失败。

改规则需要重启 analytics。onchain worker 启动时发现已存载荷的规则与配置不一致，会先只从库里重新派生（不访问 BRK，计算时间不变），再立刻开始一轮取数；完成之前，相关视图带 `rules_pending: true`。

perps worker 启动时不从库里重新派生：启动后立即开始的第一轮取数按新规则重新派生全部永续视图，这一轮完成之前，规则不一致的视图带 `rules_pending: true`。首次以 P5 版本启动时，这一轮还要把回填从 91 天扩到 121 天，多拉约 30 天的 Binance 日包，比平常一轮慢；之后切换规则不需要补数据。不运行相应 worker 的进程（例如 `WHEELHOUSE_PERPS=0` 时的 perps）不会重新派生，相应视图也不标 `rules_pending`。

## 失败与回滚

保留失败日志与实际运行版本，先判断旧版本是否仍可用。需要回滚时选择已验收的历史部署镜像或提交，通过 Coolify 支持的回滚/指定提交重新部署，并重复外网验收。若平台不支持指定提交，则在发布分支创建经过检查的正常回退提交再部署，保留分支历史，不 force push。

数据库格式变化时，先判断旧代码能否读取现有卷；代码回滚不等于数据库回滚。例如 `perps.sqlite` 应用迁移 002 之后，更早的镜像会以 "Perps database is newer than this application" 拒绝启动，而且即使 `WHEELHOUSE_PERPS=0` 也会创建这个库，整个 analytics 服务都起不来；回滚到这类版本之前要先确认这一点。数据恢复必须有已验证的备份和明确授权，禁止通过删除命名卷来修复发布失败。

P5 起派生载荷带有 `rules` 等新字段。回滚到 P5 之前的版本时，旧代码读这些载荷会因 `extra="forbid"` 校验失败，相关视图报错，直到下一轮派生把载荷覆盖（onchain ≤ 1 小时，perps ≤ 10 分钟）；等待即可，不要为此删除数据卷。

## test 与后续生产环境

test 使用 RainbowKit/Base 钱包签名与服务端白名单认证，保持独立卷和 broker worker 关闭，只用于公开行情与模拟数据。配置细节见 [部署说明](../../deploy/test/README.md)。

生产环境尚未建立。正式发布前另行确定目标环境、域名、身份认证、备份恢复和账户数据接入方式；test 发布授权不等同于生产发布授权。届时可评估 CI 构建并推送不可变镜像、将同一镜像从 test 晋升到生产；这不是当前已实现的发布流程。
