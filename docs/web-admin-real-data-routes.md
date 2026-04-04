# web-admin（OS）路由数据来源清单

> **应用**：`apps/web-admin` · 对应部署域名示例：`os.tunxiangos.com`  
> **说明**：「**仅真数据**」指**主界面指标与列表数据以 API 为准**，源码中**无**用于填充主列表的 `MOCK_*` 常量；失败时可能为空/错误态，而非替换为编造表格。  
> **注意**：`LoginPage` 成功后的 **`tx_tenant_id`** 若未写入 `localStorage`，部分页面依赖 `X-Tenant-ID` 的接口会缺头或沿用默认值——**交付前建议在登录成功回调中写入 `json.data.user.tenant_id`**（若网关已返回）。

**分类图例**

- **A 仅真数据**：主数据链 `txFetch`/`fetch` API，无本地 `MOCK_*` 主列表。
- **B 真数据 + 降级**：先请求 API，失败或 `_is_mock` 时用 mock/演示数据。
- **C 以演示数据为主**：大量 `MOCK_*` 或默认静态表驱动 UI。

---

## A. 仅真数据（主路径无 MOCK 常量）

| 路由 path | 页面组件 | 备注 |
|-----------|----------|------|
| `/` → `/dashboard` | `DashboardPage.tsx` | `txFetch('/api/v1/dashboard/summary')`，错误显示 error 无假表 |
| `/store-health` | `StoreHealthPage.tsx` | `storeHealthApi` 拉取 |
| `/agents` | `AgentMonitorPage.tsx` | `txFetch` Agent health/chat/execute |
| `/trade` | `TradePage.tsx` | `txFetch` 交易 KPI/订单等 |
| `/catalog` | `CatalogPage.tsx` | `txFetch` `/api/v1/menu/categories`、`/dishes` |
| `/daily-plan` | `DailyPlanPage.tsx` | `txFetch` 日清 E1–E8 等（注释写明真实 API） |
| `/member/insight` | `member/MemberInsightPage.tsx` | `txFetch` brain 会员洞察 |
| `/growth/campaigns` | `growth/CampaignManagePage.tsx` | 无 `MOCK_`（以实际 fetch 为准） |
| `/org/attendance` | `org/AttendancePage.tsx` | 无 `MOCK_` |
| `/member/customer-service` | `member/CustomerServicePage.tsx` | 无 `MOCK_` |
| `/member/tiers` | `member/MemberTierPage.tsx` | 无 `MOCK_` |
| `/growth/crm-campaign` | `growth/CRMCampaignPage.tsx` | 无 `MOCK_` |
| `/supply/purchase-orders` | `supply/PurchaseOrderPage.tsx` | 依赖 `TENANT_ID`，API 为主 |
| `/hq/ops/operation-plans` | `hq/ops/OperationPlanPage.tsx` | 使用 `tx_tenant_id` 调 API |
| `/receipt-editor`, `/receipt-editor/:templateId` | `ReceiptEditorPage.tsx` | 需单独确认（未检出 `MOCK_`） |
| `/ops/approval-center`, `/approval-center` | `ops/approval/ApprovalCenterPage.tsx` | 需单独确认 |

> **壳页**（`CrmPage` / `OrgPage` / `OperationsPage` / `SupplyPage` / `SystemPage` 等）：多为模块入口，若子链指向 B/C 类页，以子页为准。

---

## B. 真数据 + API 失败降级或后端 `_is_mock`

| 路由 path | 页面组件 | 说明 |
|-----------|----------|------|
| `/analytics/dashboard` | `analytics/DashboardPage.tsx` | `MOCK_*` 为初始态；成功则替换；失败保持 mock |
| `/analytics/hq-dashboard` | `analytics/HQDashboardPage.tsx` | 同上 + `catch` 降级 |
| `/finance/pnl-report` | `finance/PnLReportPage.tsx` | API + `MOCK_*` 回退；识别 `data._is_mock` |
| `/hq/analytics/pl-report` | `hq/analytics/PLReportPage.tsx` | 加载失败回落 `MOCK_PL` |
| `/analytics`（侧栏「商业智能」若指向） | `analytics/BusinessIntelPage.tsx` | `intel` API + 演示数据降级 + `_is_mock` Tag |
| `/supply/dashboard` | `supply/SupplyDashboardPage.tsx` | `MOCK_DATA` 基底 + 部分 API 合并 |
| `/supply/expiry-alerts` | `supply/ExpiryAlertPage.tsx` | `MOCK_ALERTS` + API/AI 分支 |
| `/central-kitchen` | `CentralKitchenPage.tsx` | API + `_is_mock` Tag |
| `/supply/central-kitchen` | `supply/CentralKitchenPage.tsx` | 同左 |
| `/ops/reviews` | `ops/ReviewManagePage.tsx` | `_is_mock` 统计 |
| `/ops/patrol-inspection` | `ops/PatrolInspectionPage.tsx` | API 异常提示演示数据 |
| `/operations-dashboard` | `OperationsDashboardPage.tsx` | 调用 finance compare 等，但大量 `MOCK_*` 初始与环比基数 → **偏 B** |

---

## C. 以演示数据为主（含硬编码列表/MOCK 驱动）

| 路由 path | 页面组件 | 说明 |
|-----------|----------|------|
| `/org/performance` | `org/PerformancePage.tsx` | `MOCK_KPI_CONFIGS` / `MOCK_RECORDS` / `MOCK_REWARDS` |
| `/franchise` | `franchise/FranchisePage.tsx` | `MOCK_*` 加盟主数据 |
| `/franchise-dashboard` | `org/franchise/FranchiseDashboardPage.tsx` | `MOCK_STATS` 等 |
| `/menu/optimize` | `menu/MenuOptimizePage.tsx` | `MOCK_STORES` |
| `/finance/audit` | `finance/FinanceAuditPage.tsx` | `MOCK_STORES` + payload |
| `/org/payroll/*` | `PayrollPage.tsx`, `org/payroll/PayrollManagePage.tsx` | `MOCK_STORE_ID` + 失败回落 `MOCK_RECORDS` |
| `/approval-templates` | `ops/approval/ApprovalTemplatePage.tsx` | `MOCK_TEMPLATES` |
| `/menu-templates` | `menu/template/MenuTemplatePage.tsx` | 多组 `MOCK_*` |
| `/hq/trade/banquet-menu` | `trade/banquet-menu/BanquetMenuPage.tsx` | 需 grep；若含 MOCK 则归 C |
| `/hq/menu/live-seafood` | `menu/live-seafood/LiveSeafoodPage.tsx` | `MOCK_STORES` |
| `/hq/kds/dish-dept-mapping` | `trade/kds-mapping/DishDeptMappingPage.tsx` | `MOCK_STORES` |
| `/hq/growth/journeys` | `hq/growth/JourneyListPage.tsx` | `MOCK_JOURNEYS` |
| `/hq/growth/journey-monitor` | `hq/growth/JourneyMonitorPage.tsx` | `MOCK_JOURNEYS` / `MOCK_ENROLLMENTS` |
| `/hq/ops/review` | `hq/ops/ReviewCenterPage.tsx` | `MOCK_CASES` 等 |
| `/hq/ops/dashboard` | `hq/ops/OpsDashboardPage.tsx` | `MOCK_KPI` / 小时曲线等 |

> **大量 `/hq/growth/*`、`/hq/market-intel/*`、`/hq/ops/*` 子页**：未在本清单逐行 grep 的，默认 **先归为 C 或 B**，以文件内是否含 `MOCK_` / `_is_mock` 为准。交付前建议跑：`rg "MOCK_|_is_mock" apps/web-admin/src/pages` 更新本表。

---

## 维护命令（仓库根目录）

```bash
rg "MOCK_|_is_mock|演示数据|降级 mock" apps/web-admin/src/pages --glob "*.tsx"
```

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-02 | 初版：基于源码 grep + 抽样阅读 |
