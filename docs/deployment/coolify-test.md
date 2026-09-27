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
