# Wealthfolio 宿主扩展与独立 Python 分析进程

2026-09-26：根据用户明确选择，以 Wealthfolio v3.8.0 为应用宿主，账户和组合数据继续由其 Rust/SQLite 模块负责；新增分析能力由独立 Python 包承担，宿主通过版本化 HTTP 契约调用。首期交付本地 Web 开发模式，Tauri 进程托管和正式部署后续单独验收。

选择小范围源码扩展，是因为实际核验 `crates/core/src/addons/network.rs` 后确认 addon broker 强制公网 HTTPS，并拒绝 loopback、私网和本地域名。采用宿主路由及同源开发代理可保持这些保护；无需暴露分析数据到公网。源码固定为 `8f6f9898d30e84d7215e01d3d06cd65e02c9ab1b`，补丁和新增文件单独版本管理，升级时重新核验适用性。

代价是需要维护少量上游补丁。Wealthfolio 采用 AGPL-3.0，修改后的宿主属于衍生部分，遵守上游许可；仓库根目录 MIT 不重新许可上游代码。Python 与宿主不共享数据库，也不在本阶段交换真实账户数据。
