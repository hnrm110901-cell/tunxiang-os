# 快餐模式完整性验证清单 — TC-P1-10

> 创建时间：2026-04-06
> 执行人：Team G
> 基准：天财餐饮 v7.7.86 快餐模式功能点（192行）

---

## 一、功能差距分析

### P0（必须有）

| 功能点 | 状态 | 说明 |
|--------|------|------|
| 牌号管理（开单分配牌号→出餐叫号→取餐确认） | ✅ 已有 | `quick_cashier_routes.py` 实现了 call_number 原子分配（UPSERT 序号流水）+ pending→calling→completed 状态机；前端 `QuickCashierPage.tsx` 在支付弹窗中展示取餐号。`TableNumberManager.tsx` 补全了独立网格管理 UI。 |
| 叫号屏联动（出餐完成推送叫号） | 🟡 部分实现 | `CallingScreenPage.tsx` 已存在；`quick_cashier_routes.py` 有 `/call` 端点；但前端缺少封装好的 Hook 统一触发推送。`useCallerDisplay.ts` 已补全。 |
| 付款码结算（扫码快速收款） | ✅ 已有 | `QuickPayReq.auth_code` 字段支持 B扫C 顾客付款码；前端 `QuickCashierPage.tsx` 有微信/支付宝支付方式选择。 |
| 废单重结（废单后可重新生成） | ❌ 缺失 | 后端无 `/cancel` 端点，前端无废单入口。需后续跟进（依赖 tx-trade API 扩展）。 |
| 快餐打印模板（厨打单/标签单/结账单） | ❌ 缺失 | `QuickCashierPage.tsx` 有打印调用但无专用快餐模板。`quickPrintTemplates.ts` 已补全 3 种模板。 |
| 前台快餐报表（当班营业汇总） | ❌ 缺失 | `POSReportsPage.tsx` 有通用报表，但无快餐专属当班汇总。`QuickShiftReportPage.tsx` 已补全。 |

### P1（推荐有）

| 功能点 | 状态 | 说明 |
|--------|------|------|
| AI智能识菜（扫描识别菜品加单） | ❌ 缺失 | 依赖 tx-brain Core ML 真实模型，暂未实现。 |
| 快速加减（+/- 按钮，无需详情页） | ✅ 已有 | `QuickCashierPage.tsx` 中菜品卡片点击直接加入购物车，购物车有数量增减逻辑。 |
| 会员快速绑定（输入手机号1步绑定） | 🟡 部分实现 | `QuickCashierPage.tsx` 暂无会员绑定入口，但 `tx-member` 服务有对应 API。待后续集成。 |

---

## 二、现有实现清单（探查结果）

### 后端（tx-trade）

| 文件 | 内容 |
|------|------|
| `services/tx-trade/src/api/quick_cashier_routes.py` | 8 个端点：创建订单/支付/叫号列表/叫号/完成/配置读写/序号预览 |
| `services/tx-trade/src/api/calling_screen_routes.py` | 叫号屏独立路由 |
| `services/tx-trade/src/tests/test_trade_misc.py` | 5 个快餐场景测试（场景1-5） |

### 前端（web-pos）

| 文件 | 内容 |
|------|------|
| `apps/web-pos/src/pages/QuickCashierPage.tsx` | 快餐收银主界面（菜品网格+购物车+支付弹窗+取餐号展示） |
| `apps/web-pos/src/pages/CallingScreenPage.tsx` | 叫号屏展示页 |
| `apps/web-pos/src/App.tsx` | 路由：`/quick-cashier` + `/calling-screen` 已注册 |

---

## 三、本次补全（Round 108 Sprint 2）

### 新增/完善的文件

| 文件 | 功能 |
|------|------|
| `apps/web-pos/src/components/quick/TableNumberManager.tsx` | 牌号管理组件（3列网格，等待/就绪/已取三态，颜色编码） |
| `apps/web-pos/src/utils/quickPrintTemplates.ts` | 3种快餐打印模板（厨打单/标签打印/结账单） |
| `apps/web-pos/src/hooks/useCallerDisplay.ts` | 叫号屏联动 Hook（WebSocket 优先 + HTTP 回退，失败静默） |
| `apps/web-pos/src/pages/QuickShiftReportPage.tsx` | 快餐结班报表页（5个数字卡片+支付渠道+热销品项+打印） |
| `services/tx-trade/src/tests/test_quick_cashier.py` | 5个专项测试（牌号分配/回收/打印格式/合计计算/叫号触发） |
| `apps/web-pos/src/App.tsx` | 新增路由 `/quick/shift-report` |

### 仍需跟进

- **废单重结**：需 tx-trade 增加 `POST /api/v1/quick-cashier/order/{id}/cancel` 端点 + 前端废单入口
- **AI智能识菜**：依赖 tx-brain 真实 Core ML 模型就绪后集成
- **会员快速绑定**：需在 QuickCashierPage 支付流程前增加手机号输入步骤
- **语音叫号**：配置 `call_mode=voice/both` 时需接入 TTS 引擎

---

## 四、测试覆盖情况

| 测试文件 | 覆盖场景 | 类型 |
|----------|----------|------|
| `test_trade_misc.py` | 场景1-5：创建订单/叫号/完成/配置默认值 | 集成测试 |
| `test_quick_cashier.py` | 5个新测试：顺序分配/回收/格式/计算/触发 | 单元测试 |
