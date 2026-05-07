# 屯象OS a11y 基线扫描报告（2026-05-07）

> 由 `scripts/a11y/scan.mjs` 自动生成，基于 lint-ui 风格 regex 扫描器（v1）。
> 不替代完整 axe-core + 浏览器测试，但覆盖 90% 高频静态 a11y 违规。
> 重跑：`pnpm a11y:scan`。

## 总账：498 处违规跨 16 个 app

## 按 app 分布

| App | 违规数 |
|-----|-------|
| apps/web-admin | 248 |
| apps/web-pos | 85 |
| apps/web-crew | 59 |
| apps/web-hub | 31 |
| apps/h5-self-order | 18 |
| apps/web-kds | 17 |
| apps/web-reception | 11 |
| shared/design-system | 9 |
| apps/web-tv-menu | 8 |
| apps/web-forge | 5 |
| apps/web-wecom-sidebar | 2 |
| apps/web-forge-admin | 2 |
| packages/tx-touch | 2 |
| apps/web-devforge | 1 |

## 按检查项分类

| Rule | Severity | 数量 | 说明 |
|------|---------|-----|------|
| `img-no-alt` | error | 26 | <img> 缺 alt 属性（屏幕阅读器无法描述） |
| `button-no-label` | warning | 0 | icon-only <button> 疑似缺 aria-label |
| `icon-button-no-label` | warning | 0 | <IconButton> / icon-only TXButton 疑似缺 aria-label |
| `div-clickable` | warning | 69 | <div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex） |
| `anchor-no-href` | warning | 64 | <a> 有 onClick 但无 href（键盘不可达） |
| `input-no-label` | info | 339 | <input> 疑似缺 aria-label / 关联 label（type=submit/button 除外） |
| `empty-button` | error | 0 | <button></button> 完全空内容（屏幕阅读器无法宣读） |

## Top 30 违规（按 severity → app → rule 排序）

### 1. `img-no-alt` (error) — apps/h5-self-order/src/components/DishCard.tsx:34

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 2. `img-no-alt` (error) — apps/h5-self-order/src/pages/Cart.tsx:127

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 3. `img-no-alt` (error) — apps/h5-self-order/src/pages/DishDetail.tsx:75

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 4. `img-no-alt` (error) — apps/h5-self-order/src/pages/FeedbackPage.tsx:163

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 5. `img-no-alt` (error) — apps/h5-self-order/src/pages/FeedbackPage.tsx:223

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 6. `img-no-alt` (error) — apps/h5-self-order/src/pages/OrderConfirmPage.tsx:201

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 7. `img-no-alt` (error) — apps/h5-self-order/src/templates/HotpotTemplate.tsx:256

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 8. `img-no-alt` (error) — apps/h5-self-order/src/templates/HotpotTemplate.tsx:395

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 9. `img-no-alt` (error) — apps/h5-self-order/src/templates/QuickServiceTemplate.tsx:206

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 10. `img-no-alt` (error) — apps/h5-self-order/src/templates/QuickServiceTemplate.tsx:274

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 11. `img-no-alt` (error) — apps/h5-self-order/src/templates/TeaTemplate.tsx:267

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 12. `img-no-alt` (error) — apps/h5-self-order/src/templates/TeaTemplate.tsx:361

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 13. `img-no-alt` (error) — apps/web-admin/src/components/receipt-editor/PropertyPanel.tsx:893

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 14. `img-no-alt` (error) — apps/web-admin/src/components/receipt-editor/ReceiptCanvas.tsx:560

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 15. `img-no-alt` (error) — apps/web-admin/src/pages/member/BadgeManagePage.tsx:322

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 16. `img-no-alt` (error) — apps/web-admin/src/pages/service/CustomerServiceWorkbench.tsx:482

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 17. `img-no-alt` (error) — apps/web-crew/src/pages/IssueReportPage.tsx:282

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 18. `img-no-alt` (error) — apps/web-kds/src/pages/DigitalMenuBoardPage.tsx:119

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 19. `img-no-alt` (error) — apps/web-kds/src/pages/DigitalMenuBoardPage.tsx:432

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 20. `img-no-alt` (error) — apps/web-pos/src/components/ComboSelectorSheet.tsx:202

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 21. `img-no-alt` (error) — apps/web-pos/src/components/a2ui/A2UIRenderer.tsx:369

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 22. `img-no-alt` (error) — apps/web-tv-menu/src/components/DishCard.tsx:125

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 23. `img-no-alt` (error) — apps/web-wecom-sidebar/src/components/CustomerProfile.tsx:57

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 24. `img-no-alt` (error) — shared/design-system/src/biz/DishCard/DishCard.tsx:66

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 25. `img-no-alt` (error) — shared/design-system/src/biz/DishImage/DishImage.tsx:122

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 26. `img-no-alt` (error) — shared/design-system/src/biz/SpecSheet/SpecSheet.tsx:135

```
<img
```
→ <img> 缺 alt 属性（屏幕阅读器无法描述）

### 27. `div-clickable` (warning) — apps/h5-self-order/src/components/CartBar.tsx:26

```
<div className={styles.totalSection} onClick={onViewCart}>
```
→ <div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex）

### 28. `div-clickable` (warning) — apps/h5-self-order/src/pages/MenuBrowse.tsx:245

```
<div key={rec.dishId} className="tx-pressable" onClick={() => navigate(`/dish/${rec.dishId}`)} style={{ minWidth: 140, padding: 10, borderRadius: 'var(--tx-radius-md)', background: 'var(--tx-bg-card)'
```
→ <div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex）

### 29. `anchor-no-href` (warning) — apps/web-admin/src/pages/analytics/hq/StorePerformanceMatrix.tsx:310

```
<a onClick={() => {
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 30. `anchor-no-href` (warning) — apps/web-admin/src/pages/finance/FinanceAuditPage.tsx:432

```
<a onClick={() => setDetailRecord(record)}>查看详情</a>
```
→ <a> 有 onClick 但无 href（键盘不可达）

## 修复路线图

### 30 天（M1 末）
- [ ] 全部 `error` 级修复（`img-no-alt` + `empty-button`）— 由 #254 [S2-02] 执行
- [ ] `button-no-label` / `icon-button-no-label` 全部加 aria-label

### 90 天（M2 末）
- [ ] `div-clickable` 改造为 `<button>` 或加 role + tabIndex + onKeyDown
- [ ] `anchor-no-href` 改 `<button>` 或加 href="#"

### 180 天（M3 末）
- [ ] `input-no-label` 全部关联 `<label>` 或 aria-label
- [ ] axe-core + Playwright 集成（动态 DOM 检查 color-contrast / focus-visible）
- [ ] WCAG AA 全量审计 ≥ 90 分

## 与 CI 的联动

- 本扫描已加入 `pnpm a11y:scan` 入口
- 暂未进 CI 强制（baseline 模式待补，参考 `scripts/lint-ui/baseline.json`）
- M1 末把 baseline 锁住，再渐进降数字到 0
