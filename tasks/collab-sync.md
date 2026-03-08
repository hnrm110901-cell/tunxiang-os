# 协作同步看板（Codex × Claude）

更新时间：2026-03-08

## P0（优先执行）
- [ ] 前端实时通知系统增强（`apps/web/src/pages/NotificationCenter.tsx`）
  - 自动刷新（默认开启）
  - 前台激活立即刷新
  - 刷新状态可见（最近刷新时间）

## P1
- [x] 核心页面移动端适配补强（`WorkforcePage`、`ActionPlansPage`）
  - 小屏筛选控件改为全宽
  - 表格开启横向滚动
  - 抽屉宽度改为 `92vw`（移动端）
  - 工具栏与操作按钮优化换行

## P2
- [ ] 角色权限管理体验优化（页面入口可见性与无权限提示一致性）

---

## [Claude] 状态
- branch: `main`
- latest: 以 git 最新提交为准
- focus: 后端服务与调度链路持续完善

## [Codex] 状态
- status: completed
- owner: Codex
- task: P1 核心页面移动端适配（Workforce + ActionPlans）
- files:
  - `apps/web/src/pages/WorkforcePage.tsx`
  - `apps/web/src/pages/WorkforcePage.module.css`
  - `apps/web/src/pages/ActionPlansPage.tsx`
  - `apps/web/src/pages/ActionPlansPage.module.css`
  - `tasks/collab-sync.md`
- verify:
  - `pnpm --filter @zhilian-os/web exec eslint src/pages/WorkforcePage.tsx src/pages/ActionPlansPage.tsx`（通过）
- note: 已按“移动端五域”需求源完成首批高频页面适配，下一步可进入 P2 权限体验一致性
