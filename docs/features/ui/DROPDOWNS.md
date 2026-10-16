# Wheelhouse 下拉控件统一

日期：2026-09-28。用户要求修复所有原生下拉菜单的显示问题。

## 范围与行为

当前正式Wheelhouse页面19处下拉框统一使用宿主已有Radix/shadcn Select：市场页5处、DeMark序列1处、账户/Wheel/风险页13处。不修改历史原型或Wealthfolio原生业务页。

共享组件为overlay中的`features/wheelhouse/dropdown.tsx`和`dropdown.css`。所有可见触发器为button/combobox，选项为页面内portaled listbox；固定暗色背景、青色选中态、明确焦点与勾选、碰撞避让、长文本换行及滚动。手机菜单底部留80px，避免与底部导航争占空间。

FormData、required及reset由组件内部仅用于表单语义的不可见select保留；它不接收点击、不显示OS原生弹出菜单。真实空值与Radix内部占位符分开，不把占位符提交给账户/记账接口。必填未选时聚焦可见trigger并显示错误；控件无可选值时禁用。

## 验证

- 前端type-check通过，宿主Web构建通过。
- Wheelhouse前端16项测试通过；其中新增3项验证：页面内listbox与空值Latest切换、表单值/必填/reset、无占位时首项默认值。最后一次组件调整后3项专项再次通过。
- 实际浏览器选择Visible bars=200生效；数据源菜单Esc关闭后焦点回到对应trigger；市场页可见原生select计数0。
- 检查DeMark历史长序列、Saved analysis、Data knowledge菜单；390px时列表宽337px、页面宽390px，无横向溢出，长文换行、列表滚动。
- Wheel页面Stored account为同一button/combobox，无账户可选时正确禁用；没有为UI验证创建账户、交易或记账数据。其他表单路径由组件FormData/required/reset测试覆盖。
- 截图`.local/demark-verification/themed-dropdowns.png`保存了菜单。最后的整页刷新复验遇到IAB连接超时；直接HTTP页面和Python状态均可响应。此前菜单的实际交互验证已完成，不将工具超时归为控件验证通过的依据。

数据、计数和交易逻辑未改变。
