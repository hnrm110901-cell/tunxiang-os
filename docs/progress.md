# 屯象OS 会话进度记录（progress.md）

> CLAUDE.md §18 规范文件。每次会话开始前声明目标+边界，结束后更新状态。压缩发生后 Claude 从本文件重建上下文。

---

## 2026-04-18 17:00 Sprint C2：KDS 连接健康检测 + 只读模式自动降级

### 完成状态
- [x] **新增 Hook** — `apps/web-kds/src/hooks/useConnectionHealth.ts`（180 行）聚合 WebSocket message/close 与 `navigator.onLine` 两路信号，输出三态 `health: 'online' | 'degraded' | 'offline'` + `offlineDurationMs` + `reconnect()`。状态机：OPEN 且最近 15s 内有消息 → online；15s 未收到心跳 → degraded；30s 无心跳或 ws 关闭或 navigator.onLine=false → offline。
- [x] **Context + Provider** — `apps/web-kds/src/contexts/ConnectionContext.tsx`（54 行）App 根节点挂载 `<ConnectionProvider>`，全树共享 `{ health, offlineDurationMs, reconnect }`。未挂载时 `useConnection()` 退化返回 online（测试/孤立渲染兼容）。
- [x] **顶栏 Banner** — `apps/web-kds/src/components/OfflineBanner.tsx`（68 行）`sticky top-0` + zIndex 9999；offline=橙色 `#F97316` "离线只读 · 已断线 MM:SS"；degraded=黄色 `#F59E0B` "连接不稳定"；online=return null。点击不可关闭（强制提示）。
- [x] **useOrdersCache 联动** — 改造为 `manualReadOnly + autoReadOnly(=health≠'online')` 双层合成。手动 `setReadOnly` 仍然最高优先级（保留 C1 既有 5 条测试通过），未手动覆盖时跟随 `health` 自动切换。
- [x] **App 接入** — `App.tsx` 根包 `ConnectionProvider`，`ConnectionBannerHost` 独立层渲染顶栏 banner（读 context）。
- [x] **Tier1 guard** — `KDSBoardPage` 的 `handleStart/handleComplete` 两个写操作 handler 前置 `isReadOnly` 检查，`health !== 'online'` 时 `console.warn` + `alert` 兜底并直接 return。未引入 toast 依赖（C3 再做）。
- [x] **TDD 测试** — 新增 9 条，全部绿：
  - `useConnectionHealth.test.tsx` 5 条（正常/降级/关闭/navigator.onLine 独立/状态回调）
  - `OfflineBanner.test.tsx` 4 条（online 不渲/offline 橙色计时/degraded 黄色/不可关闭）
- [x] **baseline 无回归** — web-kds vitest 总 **20/20 绿**（11 baseline + 9 新增，含 `useOrdersCache` 5 条手动 setReadOnly 场景）。
- [x] **typecheck** — 本次改动 0 错（`useConnectionHealth.ts` / `OfflineBanner.tsx` / `ConnectionContext.tsx` / `useOrdersCache.ts` / `App.tsx` 全干净）；`KDSBoardPage.tsx` 的 3 条 TS6133 为 Sprint C1 之前就存在的未使用 import，与本次改动无关。

### 关键决策
- **Provider 不持有 WebSocket**：KDS 多个页面各自有 ws 主循环（`useKdsWebSocket` / `KDSBoardPage` 内联 ws），强行集中会扩散到无关页面。Provider 先只用 `navigator.onLine` 驱动，C3 增量同步时再把页面级 wsRef 接入 Provider 的 `useConnectionHealth({ wsRef })`。
- **manualReadOnly 保留手动优先级**：C1 既有测试 `result.current.setReadOnly(true)` 依赖手动置位后 upsert 被拦截。改成"健康驱动"但保留 manual override，C1 测试全部不需改动；同时 Provider 在线/离线自动切换仍然有效。
- **orange `#F97316` 非 tailwind class**：web-kds 未引入 Tailwind runtime（仅 inline style），banner 用 inline style 直接着色，但给 wrapper 打 `tx-kds-banner-orange` / `tx-kds-banner-yellow` 类名方便 DOM 断言与未来样式 hook。
- **未改 `useKdsWebSocket`**：按任务硬边界，只读状态，不动 WS 核心逻辑。
- **alert 兜底而非 toast**：避免新增 npm 依赖；C3 再引入统一 toast 时会替换这 2 处。

### 下一步（C3 增量同步衔接）
- Provider 内置一个"注册 wsRef"的 API，让 `KDSBoardPage` / `useKdsWebSocket` 把活跃 ws 交给 Provider，使 degraded 识别精准到 ws-level（目前 navigator.onLine 只能识别系统断网，USB 线断、路由断但 STA 仍连的场景识别不到）。
- offline 期间的写操作进 outbox（IDB），online 恢复时 replay；replay 完成后自动回写服务端并去重。
- 将 alert 兜底替换为 antd 的 `message.warning` 或轻量 toast 组件。

### 已知风险
- 旁路 handler 装饰：`useConnectionHealth` 会包装 `ws.onmessage/onclose/onopen/onerror`。如果页面本身后续重新赋值这些 handler（不经过 Hook），装饰链会丢。目前只有 `useKdsWebSocket` 会反复 assign，Hook 未对其挂载（wsRef 可选），无风险；C3 集成时需注意顺序：先设置页面 handler，再 mount `useConnectionHealth`。
- 无 Provider 退化：`useOrdersCache` 在单测环境 `useConnection()` 返回 online，所有既有 upsert 测试正常。生产环境 App 根已挂 Provider，不会走退化路径。

### 改动文件清单
```
新增：
  apps/web-kds/src/hooks/useConnectionHealth.ts                        (~180 行)
  apps/web-kds/src/components/OfflineBanner.tsx                        (~68 行)
  apps/web-kds/src/contexts/ConnectionContext.tsx                      (~54 行)
  apps/web-kds/src/hooks/__tests__/useConnectionHealth.test.tsx        (~130 行, 5 tests)
  apps/web-kds/src/components/__tests__/OfflineBanner.test.tsx         (~60 行, 4 tests)
修改：
  apps/web-kds/src/hooks/useOrdersCache.ts                             (+10/-3)
  apps/web-kds/src/App.tsx                                             (+12/-3)
  apps/web-kds/src/pages/KDSBoardPage.tsx                              (+24/-5)
```

---

## 2026-04-18 17:00 Sprint A1 P1-4：Feature Flag 远程下发通道落地

### 完成状态
- [x] **yaml 注册** — `flags/trade/trade_flags.yaml` 追加 3 条 flag：`trade.pos.settle.hardening.enable` / `trade.pos.toast.enable` / `trade.pos.errorBoundary.enable`。环境默认值：dev/test/uat/pilot = true，prod = false（灰度拉起路径 pilot→prod）。targeting_rules 按 store_id 维度预留空数组，后续灰度时追加门店 ID 到 pilot/prod。tag 打 `sprint-a1` / `tier1`。
- [x] **前端改造** — `apps/web-pos/src/config/featureFlags.ts` 重写：三层优先级（`setFlagOverride > remoteValues > DEFAULTS`）+ `fetchFlagsFromRemote({timeoutMs, baseUrl, fetchFn, domain})` + `initFeatureFlags()` 启动入口 + `subscribe(listener)` 订阅模式。`isEnabled(key)` 对未知 key 返回 false 并 log debug，与 `shared/feature_flags/flag_client.py` 行为一致。保留兼容别名 `trade.pos.settle.hardening` → `trade.pos.settle.hardening.enable`，老调用点零改动。
- [x] **main.tsx 接入** — 启动时 `initFeatureFlags().catch(noop)`，不 await、不阻塞首屏；`Root` 组件用 `subscribe` 在远程下发到达后触发重渲染（boundary 状态可热切换）。
- [x] **TDD 测试** — `apps/web-pos/src/config/__tests__/featureFlags.test.ts` 新增 6 条，全部绿：(1) DEFAULTS 命中 (2) 远程成功覆盖 (3) 404 降级+警告 (4) 5s 超时+AbortController (5) override 优先级 (6) unknown flag 返回 false + debug log。
- [x] **baseline 无回归** — web-pos vitest 总 **37/37 绿**（31 baseline + 6 新增）。
- [x] **yaml 双向校验** — (a) `python -c "yaml.safe_load(...)"` 通过 (b) `shared/feature_flags/flag_client.py` 读取验证：pilot 环境 3 flag 全开，prod 环境 3 flag 全关，与 yaml 预期一致。

### 关键决策
- **保留兼容别名**：`trade.pos.settle.hardening`（无 `.enable` 后缀）已散落在 `tradeApi.ts` 两处调用，改 key 会扩散到无关 PR；用 ALIASES 映射表一次性解决，避免碎片化。
- **未在 gateway 新建 /api/v1/flags 端点**：任务边界明确不新建后端服务；前端已就位降级逻辑——404/网络错误静默回退 DEFAULTS 并 log 警告（标注 TODO）。后端补端点后前端无需二次改动。
- **订阅模式而非 Zustand**：3 个 flag 的轻量场景，Set<Listener> + `subscribe()` 足够；引入 Zustand 会在 package.json 新增依赖（被任务禁止），且 bundle 代价不划算。
- **为什么用 `subscribe` 在 Root 重渲染**：顶层 ErrorBoundary 的开关从远程切换时需要重建组件树；局部 `isEnabled` 调用点（ToastContainer / tradeApi）每次渲染/请求都会重新读值，无需订阅即自动生效。

### 后端端点契约建议（待后端补）
```
GET /api/v1/flags?domain=trade
Header: X-Tenant-ID: <tenant_uuid>
Response: {
  "ok": true,
  "data": {
    "flags": {
      "trade.pos.settle.hardening.enable": true,
      "trade.pos.toast.enable": true,
      "trade.pos.errorBoundary.enable": false
    }
  },
  "request_id": "..."
}
```
实现建议：挂到 `services/gateway/src/api/flags_routes.py`，复用 `shared/feature_flags/flag_client.FeatureFlagClient` 的 `FlagContext`（tenant_id/brand_id/store_id/role_code 从 JWT + Header 派生）。

### 下一步
- **后端 `/api/v1/flags`** — 按上述契约落地（接入 `FeatureFlagClient` + RLS 上下文），并补 gateway 路由测试；前端上线前不需此端点（已降级）。
- **灰度拉起** — yaml 里 `pilot.store_id.values` 追加徐记海鲜首批灰度门店 ID；prod 保持全 false 直至 pilot 跑满 24h 错误率 < 0.1%。

### 已知风险
- **后端端点未就绪**：当前前端只能读 yaml DEFAULTS + setFlagOverride，无法做真正租户维度下发；上线若需按 tenant/store 关闭 flag，只能走 CLI 发版覆盖 DEFAULTS（contingency，CI/CD 可操作）。
- **旧 key 仍存在**：`tradeApi.ts` 两处用 `trade.pos.settle.hardening`（无 `.enable`）。当前用别名兼容，后续独立 PR 可一次性收敛。

---

## 2026-04-18 16:00 Sprint A1 前端：独立审查 5 阻断修复（P0-1 / P1-3 / P1-5）

### 完成状态
- [x] **P0-1 修复** — `apps/web-pos/src/api/tradeApi.ts` 新增 `txFetchOffline<T>()` + `settleOrderOffline` / `createPaymentOffline`。离线时**不 throw**，自动入本地队列（通过 `registerOfflineEnqueue` 桥接 `useOffline.enqueue`），返回 `{ok:true, data:{queued:true, offline_id}}`。幂等键 `settle:${orderId}` / `payment:${orderId}:${method}` 5 分钟 TTL 防重复入队。`SettlePage.handlePay` 离线分支改用 Toast（offline 蓝色）替代 `alert("支付失败: ...")`。
- [x] **P1-3 修复** — 超时分级：`TIMEOUT_SETTLE = 8000ms`（结算/支付/退款/打印）/ `TIMEOUT_QUERY = 3000ms`（查询）。`txFetchTrade` 支持 `timeoutMs` 覆盖；`settleOrder` / `createPayment` / `processRefund` / `cancelOrder` / `printReceipt` / `printKitchen` 显式传 TIMEOUT_SETTLE。
- [x] **P1-5 修复** — `apps/web-pos/src/main.tsx` 顶层 ErrorBoundary 传 `onReset={navigateToTables}` + 独立的 `rootFallback`（文案"遇到意外错误，点击返回可恢复"，不出现"结账"字样）。新增 `apps/web-pos/src/components/RootFallback.tsx` 导出可复用的降级 UI + 导航函数。
- [x] **审查收窄** — `apps/web-pos/src/App.tsx` 新增 `CashierBoundary` 组件，包裹 `/settle/:orderId` 与 `/order/:orderId` 路由，保留"结账失败，请扫桌重试"专属 fallback；同时 `OfflineBridge` 组件把 `useOffline.enqueue` 注册给 tradeApi。
- [x] **Tier 1 测试** — 新增 `apps/web-pos/src/api/__tests__/offlineFlow.test.ts`（9 条）；扩 `components/__tests__/ErrorBoundary.test.tsx`（+3 条，共 10）。总 **31/31 绿**（tradeApi 6 + offlineFlow 9 + Toast 6 + ErrorBoundary 10）。
- [x] **typecheck 0 新增** — baseline 68 errors → 修改后仍 68 errors，全部为预先存在的 `formatPrice` 未使用 + shared DS 模块解析问题，**我的 6 个改动文件零新增**。

### 关键决策
- **为什么 8s 而不是 5s**：审查报告证据链 `tx-trade settle_order P99 ≈ 1.8s`，8s 给两次 P99 的冗余；5s 对支付回调中异步外呼（银联/微信）留余不足，200 桌并发下 P99 99 分位仍可能误伤。分级而非统一：查询 3s 与结算 8s 区分开，避免"慢查询阻塞高峰"与"快查询长超时拖收银员"的两难。
- **为什么保留顶层 ErrorBoundary**：审查建议"收窄到路由级"改动量大，本 Sprint 范围小；选择**双层方案**：顶层用中性文案兜底异常路由，内层 `CashierBoundary` 用"结账失败"专属 UI 包裹 /settle + /order。`rootFallback` 拆到独立模块便于单独单测（避免 `main.tsx` 的 ReactDOM 副作用污染测试）。
- **幂等键设计**：Map + TTL 5min 足够覆盖断网重连抖动 + 收银员多次点击场景；跨页面刷新会丢失（acceptable — 刷新后订单状态由后端 RLS + idempotency_key header 二次兜底，本次不引入服务端 header 改动）。
- **txFetchOffline 对 5xx/NET_TIMEOUT/NET_FAILURE 都降级入队**：避免"服务器抖动"当场弹"支付失败"，对业务拒绝（4xx BUSINESS_REJECT）则直接透传不入队（否则会绕过"订单已支付"等硬保护）。

### 下一步（Sprint A2 接手）
- **P0-2（4h 断网 E2E）** — 需 Playwright + mock 网络中断 4h，跑完整 CRDT 同步验证；当前仅单元测试验证幂等键与"不 throw"，未验证真实断网 4h 的数据收敛。
- **P1-4（Flag yaml 注册）** — `flags/trade/` 目录下为 `trade.pos.settle.hardening` / `trade.pos.toast.enable` / `trade.pos.errorBoundary.enable` 注册 yaml + 灰度元数据（5%→50%→100% 阈值 + 回滚错误率 0.1%）。
- 端到端打通 `POST /api/v1/telemetry/pos-crash`（已有后端端点但前端 `reportCrashToTelemetry` 仍静默失败，需真实联调）。
- 把 `createPayment` 同步调用点（splitPay / creditPay 等页面）也迁到 `createPaymentOffline` 下一 Sprint 评估。

### 已知风险
- **P0-2 未做**：断网 4h+CRDT 场景仍是 DEMO 阻断项；A2 未上线前，不得在真实门店开启"离线继续收银"flag。
- **P1-4 未做**：当前 flag 默认全 true，生产无法灰度关闭；**上线前必须补 yaml**，否则出问题只能整体回滚部署。
- **并发入队**：`txFetchOffline` 的幂等检查非原子（先读 Map 后 await 写），极端并发（同一 key 3 个 Promise 几乎同时 await _enqueueFn）仍可能入队多次。餐厅收银场景（用户连点有数十 ms 间隔）一般命中 OK；200 桌并发压测前需再观测。已在 `offlineFlow.test.ts` 第 3 条用例里通过补串行调用来验证幂等仍生效。
- **`SettlePage.tsx` 的 `formatPrice` 未使用**：pre-existing 问题，本次不动（边界）。

---

## 2026-04-18 14:30 Sprint A1 后端：POS 崩溃遥测端点落地

### 完成状态
- [x] 已完成：`services/tx-ops/src/api/telemetry_routes.py` — `POST /api/v1/telemetry/pos-crash`，per-device 60s 限流，严格 UUID 校验，SQLAlchemyError 降级不泄露堆栈
- [x] 已完成：`shared/db-migrations/versions/v260_pos_crash_reports.py` — 建表 + RLS（`app.tenant_id`）+ 2 条索引；downgrade 完整
- [x] 已完成：`services/tx-ops/src/tests/test_telemetry_routes.py` — 6 条用例全通过（200 / 422 / 400 / 429 / RLS 契约 / 500 无泄露）
- [x] 已完成：`services/tx-ops/src/main.py` 注册 telemetry_router

### 关键决策
- **归属**：选 tx-ops 而非 tx-trade。崩溃遥测本质是运营监控与健康度聚合，与 Sprint A1 门店值班看板同域；tx-trade 只应承载资金链路（§XVII Tier 1）。
- **限流实现**：进程内 TTL 字典而非 Redis。POS 主机数量有限、单实例可覆盖，跨实例重复 <1% 可接受；未来替换 Redis 仅需改 `_rate_limit_check` 函数。
- **RLS 测试策略**：用契约测试验证"路由每次请求都调 `set_config('app.tenant_id', …, true)` 并绑定对应 tenant 参数"，真实跨租户隔离由迁移层 RLS 策略负责。避免单测里用真库。
- **500 响应**：统一 `{code: INTERNAL_ERROR, message: 上报暂时不可用}`，`SQLAlchemyError` 原文仅进 structlog，不进 HTTP body（§XIV 合规）。

### 下一步
- E2E 验证（独立会话）：实际 `alembic upgrade v260` + 真实 PG 跨租户 SELECT 验证；前端 `ErrorBoundary.reportCrashToTelemetry()` 端到端贯通。
- 消费侧：Sprint A1 运营健康度看板增加"近 24h POS 崩溃次数 / Top3 route"。
- 考虑把 `error_stack` 脱敏（若堆栈含 PII/tenant_id 泄露风险，路由层用正则清理后入库）。

### 已知风险
- 进程内限流跨实例失效；若 tx-ops 扩到 3 个 Pod，突发崩溃潮可能按 Pod 数线性放大。当前单实例，不构成 Sprint A1 阻塞。
- 本次未触及 Tier 1 路径，无需独立验证会话（§XIX）。
- 未跑 alembic upgrade（按任务要求跳过）；依赖独立会话在 DEMO 环境验证迁移可用 + 回滚。

---

## 2026-04-18 10:00 Sprint 启动（A1 + F1 + 规划文档）

### 本次会话目标
基于"场景量化五问"审计 17 项 ROI 行动建议，落地屯象OS 升级迭代主规划 V1.0，并启动首批可并行、零外部依赖的子项。

### 不得触碰的边界
- [ ] `shared/ontology/` 下任何文件（需创始人确认）
- [ ] 已应用迁移文件（v001–v262，禁止修改）
- [ ] RLS 策略文件（涉及安全，单独 PR）
- [ ] 未签字的 5 个决策点相关代码（D2 ROI 列 / E1 小红书 channel / B1 Override 签名 / B2 红冲阈值 / E4 异议阈值）
- [ ] 需供应商采购的模块（B2 金税 XML / B2 OCR / B3 湘食通 API）

### 本次涉及范围
- **启动的 Sprint**：
  - Sprint A1 ErrorBoundary + Toast + 3s 超时（apps/web-pos，T1）
  - Sprint F1 14 个非品智适配器评审报告（docs/adapters/review/，T3 纯文档）
- **未启动的 Sprint**（原因标注）：
  - Sprint B：等创始人签字 + 外部供应商采购
  - Sprint C：与 A1 同属前端，避免多 agent 同域并写冲突，A1 完成后下一会话启动
  - Sprint D：基类强化需读懂 agents/constraints.py，留下一会话 TDD
  - Sprint E：E1 canonical 需决策点 2 签字
  - Sprint G/H：后置
- **服务**：apps/web-pos（主）、docs/adapters/review/（新建）、docs/sprint-plan-2026Q2-unified.md（主源）
- **迁移版本**：本会话不涉及 DB 迁移（A1 的 v260_pos_crash_reports 留下一会话）
- **Tier 级别**：[x] Tier 1（A1 收银链路）  [ ] Tier 2  [x] Tier 3（F1 文档）

### TDD 要求
Sprint A1 属 Tier 1，严格测试先行：
1. 先写 `tests/web-pos/ErrorBoundary.spec.tsx` 失败用例
2. 再实现 `apps/web-pos/src/components/ErrorBoundary.tsx`
3. 6 条餐厅场景用例全部通过
4. 所有改动挂 feature flag `trade.pos.settle.hardening.enable`

### 完成标准（本次会话 DoD）
- [x] 规划文档 `docs/sprint-plan-2026Q2-unified.md` 冻结 V4/V6，作为管理唯一真源
- [x] Sprint A1 ErrorBoundary + Toast 组件 TDD 实现，单元测试 **18/18 绿**
- [x] Sprint A1 tradeApi.ts 3s 超时 + 错误码语义映射（NET_TIMEOUT/SERVER_5XX/BUSINESS_REJECT/OFFLINE_QUEUED/NET_FAILURE）
- [x] Sprint F1 14 份适配器评审骨架 + 评分卡模板（15 份文档，823 行）
- [x] progress.md 本次会话条目

### 实际交付清单
**Sprint A1（apps/web-pos）**：
- 新增：ErrorBoundary.tsx / Toast.tsx / ToastContainer.tsx / useToast.ts / featureFlags.ts / test-setup.ts / vitest.config.ts + 3 份 __tests__/
- 修改：api/tradeApi.ts（新增 `txFetchTrade<T>()` 返回 `{ok,data,error,request_id}`）/ main.tsx（顶层包 ErrorBoundary + ToastContainer）/ package.json
- Flags：`trade.pos.settle.hardening` / `trade.pos.toast.enable` / `trade.pos.errorBoundary.enable`
- 测试：vitest 18/18 PASS；typecheck 对本次改动 0 错误

**Sprint F1（docs/adapters/review/）**：
- 15 份文档（1 README + 14 适配器骨架）
- 扫描发现：14/14 全部未接 emit_event（违反 §XV 事件总线规范）
- P0 热点：eleme / douyin / nuonuo / erp 四个刚需先修

### 独立验证触发（CLAUDE.md §19）
修改 3+ 文件 + Tier 1 路径（SettlePage 外层 ErrorBoundary） → **必须开新会话从验证视角重检**：
- 验证提示词：`services/tx-ops` 或 `services/tx-trade` 是否真的提供 `POST /api/v1/telemetry/pos-crash` 端点（目前前端静默失败，非设计意图）
- 200 桌并发场景下 txFetchTrade 3s 超时是否误伤正常请求
- SettlePage 现在被 ErrorBoundary 包裹后，崩溃恢复是否真能回到 TablesPage（需 DEMO 环境手动测）

### 下一步（下一会话）
1. **独立验证 A1 改动**（按 §19 开新会话）
2. 启动 A1 后端子任务：`POST /api/v1/telemetry/pos-crash` + v260 pos_crash_reports 迁移
3. 启动 C1 KDS IDB 缓存（纯 apps/web-kds，与 A1 无文件冲突）
4. 启动 D1 批 1 设计：读 agents/constraints.py 设计 ConstraintContext dataclass
5. F1 Owner 填评分：Channel-A/B/Finance/Growth/Supply 五个 Squad 于 W3 Day1 填 `?/4`
6. 创始人会议：签字 5 个决策点
7. 合规 workshop：法务+HR+财务三方 W2 末启动
8. 供应商采购：诺诺全电升级 / 腾讯+阿里 OCR / 湘食通账号 / 沪食安（备选）

### 已知风险
- A1 的 3s 超时对 tx-trade P99 敏感（当前 settle_order P99 约 1.8s），灰度观察需抓取实时 P99
- vitest 对 vite 8 的 peer 警告（vite 8 vs @vitejs/plugin-react 4.7 期望 ^7），不影响测试但需跟踪
- `/api/v1/telemetry/pos-crash` 端点未建，ErrorBoundary 的 onReport 当前静默失败
- 本次启动的是 T1（A1）+ T3（F1），T2（B/D/E）和 T1 的 C/A2/A3/A4 未启动
- 未 commit。主会话不自动 commit（待用户授权）

### 下一步（下一会话）
- 独立验证视角重检 A1 改动（CLAUDE.md §19，Tier 1 触发）
- 启动 C1 KDS IDB 缓存（纯 apps/web-kds，与 A1 无文件冲突）
- 启动 D1 准备：读 agents/constraints.py 设计 ConstraintContext

### 已知风险
- A1 的 3s 超时对 tx-trade P99 敏感（当前 settle_order P99 约 1.8s），灰度观察需抓取实时 P99
- 本次会话只启动 2 个 Sprint 子项（A1/F1），不能宣称"规划 V1.0 全启动"
- 5 个决策点未签字前，Sprint B/D2/E 代码不可落地

---
