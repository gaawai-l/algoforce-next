# Coolify test 部署计划

用户授权在 ci.aquiferlabs.io 新建独立项目并对外部署 test。项目 AlgoForceNext，环境 test；继续开发的工作区与部署分支分离。

- 构建固定 Wealthfolio 3.8.0 源码，加仓库内patch/overlay，生成静态Web产物。
- 三个内部服务：nginx统一入口、官方Wealthfolio Rust服务、Python分析服务。只给nginx配置域名。
- 全站 HTTP Basic test 访问保护（独立随机凭据，Coolify环境变量注入）；额外不开放OpenD/账户discover与sync端点。测试数据独立命名卷，不上传本地SQLite或凭据。
- /api/wheelhouse 经同源代理到Python，/api/v1到Wealthfolio；由入口处理HTTPS终止后转发。独立服务不公开端口。
- 测试容器仅允许公开market、demo、分析任务。云端禁用真实broker worker；禁止把单用户test环境当多租户产品。
- 验收：本地镜像构建、无认证401、认证后页面与两后端健康、fixture任务与DeMark结果、容器重启数据持久性；随后在Coolify实际部署并核验HTTPS和同样链路。

自检：构建context采用白名单，不包含.local、任何.env、真实数据、SDK环境；本地开发接口不修改为公网默认；秘密只在运行时；部署分支代码快照只收纳应用所需已测试源码。此部署不授权发布真实财务数据。
