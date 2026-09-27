# Coolify test 环境

2026-09-27 用户授权在 `https://ci.aquiferlabs.io/` 新建独立项目部署。

- 项目：AlgoForceNext；项目ID `jeykrtxdh6xkmg1i9yv9y0mp`。
- 环境：test；环境ID `ycxk0md1s9omsznw5xllzshv`。
- 应用：Wheelhouse-test；应用ID `gidpexzvnovlk6zfpoa8nz1c`。
- 服务器：OPENSTEP_Vultr；应用独立资源和命名卷，不修改已有项目。
- 源码：`gaawai-l/algoforce-next` 的 `codex/test-environment`，本地main与其他agent工作区保持不变。
- Compose路径 `/deploy/test/compose.yaml`，base `/`，仅web服务绑定域名。

入口采用测试专用Basic Auth，浏览器Origin验证通过后转发到内部Python/Rust服务。HTTPS由Coolify处理，密码哈希及独立加密key在平台环境变量配置。本地凭据仅保存在忽略提交的 `.local/test-deploy/credentials.json`；不在本文记录秘密。

构建白名单不包含本地数据库、.env、OpenD、SDK虚拟环境或broker登录数据。Broker worker在test composition明确关闭，入口阻止真实账户发现与同步。此环境适用于共享测试公开行情和模拟数据，不是多租户生产服务。

本地验收：两镜像构建成功；匿名访问页面及两API为401，正确凭据访问200，跨源请求403、broker sync403；通过容器完整执行fixture DeMark320根任务，重启Python容器后旧快照仍可读取。单元测试验证broker worker不会启动，market worker正常启动。部署审查发现的worker开关与Python依赖锁问题已修复并由Standards/Spec两轴复核关闭。

远端部署结果和最终URL以实际Coolify运行与外网验证后补充。

## Coolify兼容修正

平台使用仓库根作为Compose project-directory，因此compose build.context为`.`，不是相对于YAML子目录的`../..`。测试哈希使用base64包裹APR1，容器入口解码，避免平台dotenv插值破坏美元符号。nginx使用Docker DNS动态解析后端，避免单独重建Python容器后保留旧IP。

当前部署候选：`87a404578ade9effa307c50ae5dd89c588c6a4b6`；远端部署ID `uoc1gzdxznislnu9bnofjpja`。HTTPS配置：`https://gfbk0bsvzvpdv2tonftg9cp6.45.32.124.189.sslip.io`，禁用搜索索引。

## 远端完成验证

部署 `uoc1gzdxznislnu9bnofjpja` 成功，Coolify显示Running。HTTPS证书验证通过，HTTP自动跳转HTTPS。未登录页面、Wealthfolio API和Python API均401；独立凭据登录后均200；跨源POST403、真实broker discover/sync403。通过外网运行fixture分析任务返回320根及DeMark；Binance公开现货刷新返回319根、fresh、74个DeMark序列。

测试库初始化为英文、暗色、USD、UTC，未添加真实账户。访问说明（含密码）仅位于本机 `.local/test-deploy/ACCESS.md`，不提交仓库。验收截图 `.local/test-deploy/coolify-running.png`。平台整体状态的“no healthcheck”指官方Wealthfolio服务未定义Compose健康探针；已通过实际HTTP检查验证两后端及入口。

后续发布：继续开发在原分支进行；完成评审后生成新的test分支提交，在同一Coolify应用手动Deploy。当前不自动部署未审阅的main变更。测试域名由服务器的sslip规则生成，后续可绑定自定义DNS，不影响应用架构。
