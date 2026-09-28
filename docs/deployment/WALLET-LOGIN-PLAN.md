# Base 钱包登录设计与实施计划

用户已指定 RainbowKit、Base、两个允许地址，并明确要求先取消 Basic Auth、直接实施。按此授权执行，不再增加逐阶段确认。

目标：先开放 test 以解除阻塞，再上线钱包签名认证。首次签名建立 30 天会话，同一浏览器可直接进入；退出清除并撤销会话。连接钱包不等于认证，不进行交易。

架构：独立 React/RainbowKit 登录页由现有 nginx 服务；Node/viem 认证服务负责 SIWE、Base 主网白名单验证与持久会话。nginx auth_request 保护应用与 Python/Rust API。健康探针和登录资源公开。Broker worker 与 discover/sync 禁用维持原状。与 Wealthfolio overlay 和计算代码隔离。

白名单由部署环境配置，地址是 0x11890834531ad1127863895fa83983bfc6347bb0 和 0x092b5f11c081b7f607e7dbf0167d5f9267da215e。Base chain ID 8453。登录挑战使用服务端生成的随机 nonce，绑定浏览器挑战 Cookie、固定 origin、chain、签发与过期时间；成功/失败验证均消费挑战。服务端通过 viem 验证 EOA 与 Base 合约钱包签名。只把消息摘要发送给配置的 Base RPC 进行必要验证，不发送账户持仓。

会话采用随机不透明 token，HttpOnly/Secure/SameSite=Lax Cookie，服务端仅持久化哈希、地址和到期时间，重启后保留；退出删除对应会话。认证请求要求同源，限制正文大小、挑战数和请求频率。未配置白名单/origin 时启动失败。登录错误不设置 WWW-Authenticate，因此不再弹用户名密码框。

RainbowKit 优先支持浏览器发现的钱包；WalletConnect 扫码仅在配置真实 project ID 时启用，不伪造项目 ID。没有扩展时明确提示安装兼容钱包。移动端扫码若无 project ID，作为明确限制交付。

- [ ] 1. 先写并运行失败测试：白名单签名成功、错误地址/链/域名/签名、nonce 重放/过期、会话持久化/过期/退出、同源限制。
- [ ] 2. 实现独立认证服务与登录 UI，固定依赖锁；通过测试及 UI 构建。
- [ ] 3. nginx/Compose/Dockerfile 接入 auth_request 与持久卷；保留临时无 Basic Auth 的线上热修复到正式部署。
- [ ] 4. 容器验证未登录页面跳转、API 401、无 Basic challenge、合法测试签名访问两个 API、跨域403、broker403、退出和重启。
- [ ] 5. 正常推送发布分支、Coolify 构建部署；核对 SHA 与外网状态、登录页浏览器交互。真实白名单钱包签名由用户在自己的钱包完成。

自检：应用服务不暴露主机端口；授权在服务端强制执行；旧 Basic Auth 彻底停用；不会打包其他 agent 未提交工作；无私钥/助记词采集；无数据库破坏或生产变更。

## 执行记录

- 线上 nginx 热修复已生效：2026-09-28，匿名首页200，broker sync403；旧配置备份在原容器 `/etc/nginx/default.conf.before-wallet`。用户可先正常使用。
- 任务1/2：先观察缺失 auth/server 模块的测试失败，再实现；7项签名/HTTP测试通过，登录页 Vite 构建通过。
- 决定：未提供 WalletConnect project ID，先提供 injected/EIP-6963 钱包连接，并支持后续通过构建参数启用扫码；不使用伪造 ID。影响：手机外部浏览器扫码暂不可用。
- 任务3/4：认证镜像构建成功；nginx 配置检查通过。隔离容器以一次性测试钱包完成签名，首页与两个 API 均200，匿名API401且无 Basic challenge，fixture任务创建成功，broker403。认证容器重启后旧Cookie仍有效；退出后同一Cookie被拒绝。
- 浏览器已看到 RainbowKit 连接弹窗并发现 OKX Wallet、MetaMask；未替用户连接或签署。真实钱包签名仍需用户自己确认。
- 独立审查无 P1/P2；剩余真实合约钱包和 WalletConnect 扫码未验收。依赖审计无 high/critical，仍有钱包SDK传递依赖的 low/moderate 报告。
