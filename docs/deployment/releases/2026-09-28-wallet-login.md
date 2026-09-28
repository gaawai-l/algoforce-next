# 2026-09-28 Base 钱包登录发布

- 环境：Coolify / AlgoForceNext / test / Wheelhouse-test。
- 实际部署 SHA：`61e9136f23de1d82ac70827600e83e3a7ed7cca4`（功能提交 `30e2a69` + HTTPS跳转修正）。
- 上一版本：`8f48316adfd43ad78b919d9f0a81f9fb1001cb3d`。
- 最终 Deployment ID：`irg5wqgtgx6lzhspiivt698c`；首轮为 `qieecn8a14kwmncbfgra7p5o`。
- 入口：https://gfbk0bsvzvpdv2tonftg9cp6.45.32.124.189.sslip.io
- 首次钱包部署：`30e2a69` 已成功上线并通过外网HTTP验收。
- 后续修正：`61e9136` 将 nginx 登录跳转改为相对路径（HTTPS代理后保持协议）；已固化到镜像，于 2026-09-28 04:13 UTC 成功部署，容器镜像SHA一致，健康检查和外网验收再次通过。

## 变更

按用户明确要求，首先热修复关闭 Basic Auth，匿名首页200，broker403。随后发布 RainbowKit + Base (8453) SIWE 签名登录；仅允许已提供的两个钱包地址，服务端检查授权。30天浏览器会话通过 HttpOnly/Secure Cookie 保持；重启保留，退出撤销。新增独立 wallet-auth 服务及命名卷，现有 analytics/Wealthfolio 数据卷和加密密钥保留，无数据库迁移。

连接钱包 → Sign in with wallet → 钱包确认签名 → 进入工作台。会话管理及退出：`/login/?manage=1`。只做身份签名，不发送交易。未配置 WalletConnect project ID 时使用浏览器扩展或钱包内置浏览器，不提供外部浏览器扫码。

## 已验证

- 7项 Node测试通过：白名单、域名/链/nonce篡改、错误签名、浏览器挑战绑定、重放、过期、会话持久化与退出、HTTP同源、Cookie属性。
- 登录页 Vite 构建与认证 Docker 镜像构建成功。
- 隔离 nginx 容器中，测试钱包签名登录后首页和两个 API 均200，匿名API401且无 Basic challenge，fixture任务创建成功，broker403。
- 认证容器重启后会话仍有效，退出后旧 Cookie 被拒绝。
- 浏览器测试 RainbowKit弹窗，可发现 OKX Wallet、MetaMask；390px窄屏布局通过。
- 独立代码审查无P1/P2。

真实白名单钱包的最终签名由用户在自己的钱包操作，尚未代签或宣称验收通过。依赖审计无 high/critical，钱包 SDK 传递依赖仍有 low/moderate 报告。

## 外网验收

首页302到相对 `/login/`，登录页200；两个API匿名401且无 `WWW-Authenticate`；跨源认证403，broker sync403。两个用户地址均可获取正确Base8453 SIWE消息与Secure/HttpOnly挑战Cookie，陌生地址和无效签名401，未授予会话。

线上浏览器导航超时后，浏览器工具因页面协议策略拒绝继续检查；未绕过工具限制。实际浏览器交互/窄屏验收在本地同一登录构建上完成，线上以HTTPS/API和静态资源检查为证。

## 回滚

优先修复或回退钱包代码并保留数据卷。直接回退到旧版本镜像会恢复历史 Basic Auth，与用户当前要求冲突；若需回退应用功能，应保留本次移除 Basic Auth 的配置。不得删除会话或业务数据卷解决构建失败。
