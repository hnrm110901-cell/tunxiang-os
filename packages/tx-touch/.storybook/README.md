# tx-touch Storybook

屯象OS Store 终端组件库视觉回归 + 设计审查。

## 启动

```bash
# 在仓库根目录或 packages/tx-touch 下：
pnpm install                    # 首次拉 storybook 依赖（约 200MB，CI 缓存）
pnpm --filter @tx/touch storybook
# → http://localhost:6006
```

## 视口预设（宪法 §2.2-2.4 终端区隔）

| 视口 | 用途 |
|------|------|
| 商米 T2 (POS 竖屏) — 800×1280 | 默认；安卓 POS 收银员视角 |
| 商米 T2 (POS 横屏) — 1280×800 | 横屏布局对照 |
| iPad Pro 11 — 1194×834 | 高端店升级包 |
| 商米 D2 (KDS) — 1280×800 | 后厨出餐屏 |
| 员工手机 (Crew PWA) — 414×896 | 服务员 PWA |

## 已覆盖组件

5 / 9（占位 follow-up：TXAgentAlert / TXScrollList / TXSelector / TXPaymentPanel）

- ✅ TXButton — 8 stories（variant×size×state）
- ✅ TXCard — 5 stories
- ✅ TXDishCard — 4 stories
- ✅ TXKDSTicket — 4 stories（含超时/VIP/紧急）
- ✅ TXNumpad — 3 stories（现金/桌号/折扣率）

## 视觉回归（M2-W1+）

CI 闸门待集成：`pnpm build-storybook` + chromatic / playwright snapshot。
Storybook static 构建产物：`packages/tx-touch/storybook-static/`。

## 设计审查清单（每次 PR 经过）

- [ ] 触控目标 ≥ 48px（关键操作 ≥ 72px）
- [ ] 字号 ≥ 16px（KDS: 订单 32 / 区域 28 / 菜品 20 / 徽标 16）
- [ ] 主色锁定 `var(--tx-primary)` (#FF6B35)
- [ ] :focus-visible 可见
- [ ] :active 缩放反馈（无 hover-only）
- [ ] a11y addon 无 violations（color-contrast / target-size）
