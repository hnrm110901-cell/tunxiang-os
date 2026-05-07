# 屯象OS a11y 基线扫描报告（2026-05-07）

> 由 `scripts/a11y/scan.mjs` 自动生成，基于 lint-ui 风格 regex 扫描器（v1）。
> 不替代完整 axe-core + 浏览器测试，但覆盖 90% 高频静态 a11y 违规。
> 重跑：`pnpm a11y:scan`。

## 总账：817 处违规跨 16 个 app

## 按 app 分布

| App | 违规数 |
|-----|-------|
| apps/web-admin | 389 |
| apps/web-crew | 170 |
| apps/web-pos | 132 |
| apps/web-hub | 44 |
| apps/web-kds | 22 |
| apps/web-reception | 17 |
| shared/design-system | 11 |
| apps/web-tv-menu | 8 |
| apps/h5-self-order | 8 |
| apps/web-forge | 6 |
| packages/tx-touch | 4 |
| apps/web-wecom-sidebar | 2 |
| apps/web-forge-admin | 2 |
| apps/web-devforge | 2 |

## 按检查项分类

| Rule | Severity | 数量 | 说明 |
|------|---------|-----|------|
| `img-no-alt` | error | 0 | <img> 缺 alt 属性（屏幕阅读器无法描述） |
| `button-no-label` | warning | 0 | icon-only <button> 疑似缺 aria-label / 无文字 children |
| `icon-button-no-label` | warning | 0 | <IconButton> / icon-only TXButton 疑似缺 aria-label |
| `div-clickable` | warning | 372 | <div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex + onKeyDown） |
| `anchor-no-href` | warning | 106 | <a> 有 onClick 但无 href（键盘不可达） |
| `input-no-label` | info | 339 | <input> 疑似缺 aria-label / 关联 label（type=submit/button 除外） |
| `empty-button` | error | 0 | <button></button> 完全空内容（屏幕阅读器无法宣读） |

## Top 30 违规（按 severity → app → rule 排序）

### 1. `div-clickable` (warning) — apps/h5-self-order/src/components/CartBar.tsx:26

```
<div className={styles.totalSection} onClick={onViewCart}>
```
→ <div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex + onKeyDown）

### 2. `div-clickable` (warning) — apps/h5-self-order/src/components/DishCard.tsx:28

```
<div
```
→ <div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex + onKeyDown）

### 3. `div-clickable` (warning) — apps/h5-self-order/src/pages/MenuBrowse.tsx:245

```
<div key={rec.dishId} className="tx-pressable" onClick={() => navigate(`/dish/${rec.dishId}`)} style={{ minWidth: 140, padding: 10, borderRadius: 'var(--tx-radius-md)', background: 'var(--tx-bg-card)'
```
→ <div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex + onKeyDown）

### 4. `div-clickable` (warning) — apps/h5-self-order/src/templates/TeaTemplate.tsx:340

```
<div
```
→ <div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex + onKeyDown）

### 5. `anchor-no-href` (warning) — apps/web-admin/src/pages/analytics/hq/StorePerformanceMatrix.tsx:310

```
<a onClick={() => {
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 6. `anchor-no-href` (warning) — apps/web-admin/src/pages/analytics/hq/StorePerformanceMatrix.tsx:395

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 7. `anchor-no-href` (warning) — apps/web-admin/src/pages/finance/AgreementUnitPage.tsx:472

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 8. `anchor-no-href` (warning) — apps/web-admin/src/pages/finance/EInvoicePage.tsx:312

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 9. `anchor-no-href` (warning) — apps/web-admin/src/pages/finance/FinanceAuditPage.tsx:432

```
<a onClick={() => setDetailRecord(record)}>查看详情</a>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 10. `anchor-no-href` (warning) — apps/web-admin/src/pages/finance/PayrollPage.tsx:387

```
<a key="view" onClick={() => handleViewDetail(record)}>详情</a>,
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 11. `anchor-no-href` (warning) — apps/web-admin/src/pages/finance/PayrollPage.tsx:400

```
<a key="paid" style={{ color: txColors.success }} onClick={() => handleMarkPaid(record)}>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 12. `anchor-no-href` (warning) — apps/web-admin/src/pages/finance/PayrollPage.tsx:553

```
extra={<a onClick={() => handleEdit(cfg)}>编辑</a>}
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 13. `anchor-no-href` (warning) — apps/web-admin/src/pages/finance/TaxManagePage.tsx:656

```
<a key="edit" onClick={() => handleEdit(r)}>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 14. `anchor-no-href` (warning) — apps/web-admin/src/pages/franchise/FranchiseContractPage.tsx:280

```
<a key="detail" onClick={() => Modal.info({
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 15. `anchor-no-href` (warning) — apps/web-admin/src/pages/franchise/FranchiseContractPage.tsx:295

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 16. `anchor-no-href` (warning) — apps/web-admin/src/pages/franchise/FranchiseContractPage.tsx:584

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 17. `anchor-no-href` (warning) — apps/web-admin/src/pages/growth/CampaignManagePage.tsx:284

```
<a key="stats" onClick={() => handleViewStats(record)}>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 18. `anchor-no-href` (warning) — apps/web-admin/src/pages/growth/CampaignManagePage.tsx:287

```
<a key="notify" onClick={() => handleOpenNotify(record)}>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 19. `anchor-no-href` (warning) — apps/web-admin/src/pages/growth/CampaignManagePage.tsx:293

```
<a key="activate" style={{ color: txColors.success }} onClick={() => handleActivate(record)}>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 20. `anchor-no-href` (warning) — apps/web-admin/src/pages/growth/CampaignManagePage.tsx:305

```
<a key="end" style={{ color: txColors.danger }} onClick={() => handleEnd(record)}>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 21. `anchor-no-href` (warning) — apps/web-admin/src/pages/growth/GroupDealPage.tsx:181

```
<a onClick={() => showDetail(record.id)}>{record.name}</a>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 22. `anchor-no-href` (warning) — apps/web-admin/src/pages/hq/agent/AgentSettingsPage.tsx:62

```
<a key="edit" onClick={() => alert('编辑权限配置')}>编辑</a>,
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 23. `anchor-no-href` (warning) — apps/web-admin/src/pages/hq/growth/CrossBrandPage.tsx:127

```
<a style={{ color: INFO_BLUE }} onClick={() => openDrawer(id)}>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 24. `anchor-no-href` (warning) — apps/web-admin/src/pages/hq/growth/GrowthDashboardPage.tsx:1129

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 25. `anchor-no-href` (warning) — apps/web-admin/src/pages/hq/growth/JourneyAttributionPage.tsx:317

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 26. `anchor-no-href` (warning) — apps/web-admin/src/pages/hq/supply/SupplierPortalPage.tsx:308

```
<a key="view" onClick={() => handleViewDetail(record)}>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 27. `anchor-no-href` (warning) — apps/web-admin/src/pages/hq/supply/SupplierPortalPage.tsx:620

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 28. `anchor-no-href` (warning) — apps/web-admin/src/pages/hq/trade/BanquetTemplatePage.tsx:862

```
<a
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 29. `anchor-no-href` (warning) — apps/web-admin/src/pages/hr/AlertAggregationPage.tsx:249

```
<a onClick={() => message.info(`跳转门店画像: ${r.store_id}`)}>查看画像</a>
```
→ <a> 有 onClick 但无 href（键盘不可达）

### 30. `anchor-no-href` (warning) — apps/web-admin/src/pages/hr/CertificationPage.tsx:350

```
<a onClick={() => openDetail(r.id)}>详情</a>
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
