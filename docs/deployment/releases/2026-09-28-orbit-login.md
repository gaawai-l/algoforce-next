# 2026-09-28 Orbit 登录体验改版

- 环境：AlgoForceNext / test；Coolify应用资源ID保持不变。
- 变更提交：`835d7b5`；部署ID：`on4xz8fzd5owx7ehqu4c5ymk`。
- 上一运行版本：`61e9136`。
- 状态：2026-09-28 05:36 UTC 部署成功；web、wallet-auth、analytics 镜像SHA均为 `835d7b5b7349de67bdcf1622664e8bfa0a0503ab`。
- 外网验收：登录页与资源200；Orbit标题、新Sonner文案存在，旧说明和第二个Sign in按钮文案消失；两个允许地址均获取Base8453 Orbit SIWE挑战。匿名API401、无Basic challenge、broker403保持。

## 用户可见变化

开发代号 Orbit。登录页面只有轨道图、ORBIT 和 Connect Wallet；钱包选择框采用 RainbowKit compact 模式。连接后自动请求Base签名；已有会话直接进入。拒签/拒绝连接/拒绝切链用Sonner简短提示，拒签后用户可用同一按钮重试，不循环弹出。未授权钱包断开连接，可重新选择。市场页/组合页显示名称与SIWE声明也改为Orbit。

内部API、目录、Cookie和卷名称保持兼容，无数据库迁移，原30天会话继续有效。

## 验证

7项后端测试与7项前端交互测试通过，Vite生产构建成功。前端覆盖自动单次签名、拒签重试、已有会话、账户变化时阻止旧签名认证、切链拒绝、连接拒绝、未授权钱包重新选择。桌面/390px窄屏浏览器检查通过，截图位于主工作区 `.local/test-deploy/orbit-login.png`。独立审查发现的未授权钱包恢复问题已通过新增失败测试复现并修复。

没有操作用户真实钱包签名；签名流程用隔离模拟钱包接口测试。WalletConnect扫码仍需要有效project ID，浏览器钱包连接不受影响。
