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

## Perps（永续状态）

analytics 服务内常驻 perps 的 REST worker，由 `WHEELHOUSE_PERPS` 控制，默认开启（`0`/`false`/`off` 关闭）。清算和买卖量从 Coinalyze 取数（P6 起）。

- **总开关与采集器开关**：
  - WebSocket 采集器由 `WHEELHOUSE_PERPS_COLLECTORS` 控制，默认关闭（取值 `1`/`0`、`true`/`false`、`on`/`off`），只在对照时打开，不参与任何视图。
  - **`WHEELHOUSE_PERPS` 是总开关**：它为 `off` 时，即使 `WHEELHOUSE_PERPS_COLLECTORS=on`，采集器也不启动。
  - 写 compose 时注意空字符串：这两个变量写成空值会被当成非法值，服务启动失败。要用默认值就不要设置。
- **`WHEELHOUSE_COINALYZE_KEY`**：Coinalyze 的 API key，在 Coolify 里设为 secret，不写进仓库、日志或发布记录。
  - `deploy/test/compose.yaml` 已经把它传给 analytics：`WHEELHOUSE_COINALYZE_KEY: ${WHEELHOUSE_COINALYZE_KEY:-}`。变量存在但为空，等于没有 key。
  - 没有 key 时，perps 的清算和 Coinalyze 的买卖量、OI 不可用，视图显示 key 的提示（见下文的部署后检查），不会用假数据代替。
  - **同一个 key 最多两个进程同时使用**：免费 key 每分钟 40 次，每个进程自己限在 20 次以内。本机开发和 test 各占一个；核验时另起的服务要先停掉其他进程，或者另用一个 key。
- **出站网络**：需要放行到 `fapi.binance.com`、`data.binance.vision`、`api.bybit.com`、`api.coinalyze.net` 的 HTTPS。只有打开采集器对照时，才需要到 `fstream.binance.com` 和 `stream.bybit.com` 的 WSS。
- **停机**：Compose 给 analytics 设了 `stop_grace_period: 40s`。收到 SIGTERM 后，worker 在下一个请求前放弃本轮（在途请求最长 20 秒）；打开了采集器时，它同时关闭连接并结束覆盖区间（最长 8 秒）；之后等待 worker 线程结束最长 25 秒。
- **部署后检查**：用合法钱包会话（与 `verify.py --session-file` 相同）请求 `/api/wheelhouse/v1/perps/status`：
  - `hosts` 中 `api.coinalyze.net` 有 `last_success`，没有持续的 `error`：
    - `key_missing`：secret 没有传进容器；
    - `401`：key 无效或还没生效（新生成的 key 可能要几分钟），下一轮（最多 10 分钟）自动重试；
    - `429`、`403`：被限流或被 Cloudflare 挡住，`backoff_until` 之后自动恢复；
  - `markets` 有 4 项（binance、bybit、okx、hyperliquid），`ok` 都是 `true`。它在第一轮的 Coinalyze 取数结束后才出现，之后每天核对一次；有一项 `ok: false` 时，对应交易所的 Coinalyze 数据不用，相关视图带 `coinalyze_units:<venue>`；
  - 首轮回填结束后，请求 `/api/wheelhouse/v1/perps/states?exchange=all&window=4h`：`covered_days` 约 90，`reasons` 中没有 `collecting:`，也没有 `rest_error:api.coinalyze.net:`；
  - `direction_check` 的 binance、bybit、okx 在样本足够后不是 `inverted`；
  - 其他 host 的 `error` 也不持续。
  `deploy/test/verify.py` 不检查这些项目，需要手动核对并写进发布记录。
- **采集器对照**（仅在打开采集器时）：`collectors` 中 3 个流都是 `live: true`；各流的 `problems` 是本进程启动以来的计数（`rotated`、`stopped` 属正常生命周期，其余如 `stalled`、`half_open`、`connect_failed`、`coverage_split` 是故障或空洞）。采集器关闭时，这些流不是 `live` 不是故障。
- **覆盖空洞**：清算历史来自 Coinalyze，重新部署不会再留下清算空洞。只有打开采集器对照时，每次重新部署才会让采集的覆盖断开。

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

**迁移 003（P6）同样如此。** 它新增 `cz_series` 表，并删除旧形状的方向核对结果。应用之后，P6 之前的镜像（迁移最高到 002）读到更新的库，会以同样的 "Perps database is newer than this application" 拒绝启动，整个 analytics 服务都起不来。所以回滚到 P6 之前的版本，要连同数据卷一起处理：先停写，再按发布第 3 步取得的备份恢复 `perps.sqlite`（该备份必须在迁移 003 之前取得，并已验证能恢复）。只回滚镜像不会让服务恢复。

**onchain 迁移 002（SR-8）同样如此。** 它新增 `urpd_history` 表，不改已有的表。应用之后，SR-8 之前的镜像（onchain 迁移最高到 001）打开 `onchain.sqlite` 时，会以 "On-chain database is newer than this application" 拒绝启动；onchain router 在 lifespan 里建库，所以整个 analytics 服务都起不来。发布前按第 3 步备份 `onchain.sqlite`，这份备份必须在迁移 002 之前取得，并已验证能恢复。回滚只能二选一：先停写，用这份备份恢复 `onchain.sqlite`，再回滚镜像；或者保持前进，修复后再发布。只回滚镜像不会让服务恢复。

在新镜像上运行 derive CLI（`python -m wheelhouse_service.derive --data-dir <目录>`）同样会对该目录里的 `onchain.sqlite` 应用迁移 002：用它演练的只能是备份的副本，演练过的库不能再当回滚用的备份。

P5 起派生载荷带有 `rules` 等新字段。回滚到 P5 之前的版本时，旧代码读这些载荷会因 `extra="forbid"` 校验失败，相关视图报错，直到下一轮派生把载荷覆盖（onchain ≤ 1 小时，perps ≤ 10 分钟）；等待即可，不要为此删除数据卷。

## test 与后续生产环境

test 使用 RainbowKit/Base 钱包签名与服务端白名单认证，保持独立卷和 broker worker 关闭，只用于公开行情与模拟数据。配置细节见 [部署说明](../../deploy/test/README.md)。

生产环境尚未建立。正式发布前另行确定目标环境、域名、身份认证、备份恢复和账户数据接入方式；test 发布授权不等同于生产发布授权。届时可评估 CI 构建并推送不可变镜像、将同一镜像从 test 晋升到生产；这不是当前已实现的发布流程。
