# Sprint A1 TDD 工单 — POS ErrorBoundary + 3s 超时 + Toast

**Tier**：1（零容忍 — 先测后写 / DEMO 验收 / P99<200ms / 支付成功率>99.9%）
**周期**：W1-W2（共 18.5 人日中约 **6 人日**，含测试、实装、灰度、独立验证）
**Owner**：交易+前端双签
**状态**：规划中（本工单尚未开工）
**产出**：Plan Agent · 2026-04-24

---

## 1. 目标 + Tier 级别 + 验收标准

### 1.1 目标一句话

让徐记海鲜收银员在高峰期遇到前端崩溃、接口超时、网络抖动时，**不再白屏、不丢单、不需要重启 POS**，且所有异常被留痕到 `pos_crash_reports` 并可在 Sprint A1 健康度看板上实时复盘。

### 1.2 Tier 1 验收（必须全部基于餐厅场景，非技术边界值）

| # | 验收场景（必须在 `demo-xuji-seafood.sql` 数据集上可复现） |
|---|---|
| 1 | 徐记 17 号桌收银员结完第 47 单后点"结账"，4G 抖动触发 3s 超时，UI 显示"请检查网络，订单已暂存"，Toast 3s 自动消失，收银员无需重启 |
| 2 | 200 桌并发高峰，某桌 CashierPage 因会员扣费计算错误 throw，ErrorBoundary 捕获并降级到"结账失败，请扫桌重试"，**未触发浏览器刷新** |
| 3 | 店长误按点餐平板的"删单"触发越权，服务端返回 403，前端 Toast 展示"权限不足，请联系店长"，`trade_audit_logs` 留一条 `action=delete_order, result=deny` |
| 4 | 晚餐 6-9pm 连续断网 100 单全部通过离线队列暂存，联网恢复后 100 单 100% 补发成功，零重复（幂等键防重） |
| 5 | P99 结算接口延迟 < 200ms（k6 200 桌并发脚本），支付成功率 > 99.9% |
| 6 | 灰度 5% → 50% → 100% 任一档位错误率 > 0.1% 触发自动回退（flag off） |

---

## 2. 现状差距（已实地核查）

| 项 | 状态 | 差距 |
|---|---|---|
| `shared/db-migrations/versions/v260_pos_crash_reports.py` | **已存在** | schema 只含 `tenant_id / store_id / device_id / route / error_stack / user_action / created_at`。**缺失 Sprint A1 需要的 6 列**：`timeout_reason`(TEXT, enum)、`recovery_action`(TEXT)、`saga_id`(UUID FK)、`order_no`(TEXT)、`severity`(TEXT: fatal/warn/info)、`boundary_level`(TEXT: root/cashier)。**→ 需追加 v265_pos_crash_reports_ext**（v264 已被 D2 `agent_roi_fields` 占用） |
| `apps/web-pos/src/components/ErrorBoundary.tsx` | **已存在** | 已实装 `getDerivedStateFromError / componentDidCatch / reportCrashToTelemetry`。**差距**：无 3s 自动重置、无 Toast 联动、无 boundary_level 上报、无结算 saga 恢复钩子 |
| `apps/web-pos/src/components/RootFallback.tsx` | **已存在** | 顶层 fallback 文案中性化 OK。**差距**：未与 /settle /order 路由级 CashierBoundary 联动 |
| `apps/web-pos/src/components/Toast.tsx + ToastContainer.tsx` | **已存在** | **差距未核查到具体实装**，需本工单 T1.7 场景验证 5 类样式（success/error/info/warning/offline）是否齐全 |
| 3s 超时（前端） | **未实装** | `apps/web-pos/src/api/tradeApi.ts` 无 `AbortController` / `TIMEOUT_SETTLE` 分级。Flag 描述写 "8s 超时分级"，**与 A1 规划原文"3s"不一致，需本工单统一**（建议 3s UI 提示 / 8s 硬失败两级） |
| 3s 超时（后端） | **不属于本工单** | `services/tx-trade/src/services/payment_saga_service.py` `_PENDING_TIMEOUT_MINUTES = 5` 是服务端 saga 超时，归属 A2 |
| `/api/v1/telemetry/pos-crash` | **已存在于 tx-ops** | `services/tx-ops/src/api/telemetry_routes.py:89` 已实装。**与 A1 规划边界 `services/tx-trade` 冲突**，本工单**维持现状放在 tx-ops**（避免跨服务迁移增加风险），在立项卡注脚补一行说明 |
| Flag `trade.pos.settle.hardening` | **已注册** | `flags/trade/trade_flags.yaml:106-170`。已有 `trade_pos_settle_hardening_enable / trade_pos_toast_enable / trade_pos_error_boundary_enable` 三个，默认 `prod: false`，灰度槽位为空数组 |
| `trade_audit_logs` | 归属 A4（v261 已存在），本工单**只消费，不建表** | |

---

## 3. TDD 测试用例清单（至少 8 条 — 餐厅场景命名）

所有测试先写、再实装。命名遵循 `test_*_tier1.py` / `*.test.tsx`。

| # | 测试名 | 场景 | P99 阈值 | Fixture |
|---|---|---|---|---|
| 1 | `ErrorBoundary.test.tsx::test_cashier_page_crash_shows_fallback_within_3s` | 晚市第 47 单，CashierPage 因会员抵扣 throw，3s 内降级 UI 可见，非白屏 | UI 帧 < 100ms | Boom 组件 + vitest fake timers |
| 2 | `ErrorBoundary.test.tsx::test_network_jitter_auto_recover_no_restart` | 17 桌结账时 4G 抖动，AbortController 3s 超时，Toast 提示 + 自动重试 1 次，收银员不需要重启 POS | E2E < 200ms | mocked fetch + network-toggle |
| 3 | `test_pos_integration_tier1.py::test_200_tables_concurrent_checkout_p99_under_200ms` | 200 桌并发结账（高峰），P99 < 200ms，错误率 < 0.1% | P99 < 200ms | `demo-xuji-seafood.sql` + k6 |
| 4 | `test_offline_buffer.py::test_offline_4h_100_orders_zero_loss` | 断网 4 小时，离线暂存 100 单，联网后补发 100% 成功，无重复（幂等键） | 恢复 < 60s | toxiproxy drop + idempotency_key fixture |
| 5 | `test_payment_saga_tier1.py::test_settle_timeout_saga_rollback_clean` | 第 47 单支付网关 3s 无响应，saga 回滚，座位/库存/积分状态一致 | Saga < 500ms | mocked gateway timeout |
| 6 | `ErrorBoundary.test.tsx::test_cash_drawer_state_consistent_after_boundary` | ErrorBoundary 触发后，钱箱状态（localStorage.cash_drawer）与服务端 order 状态一致，不留半状态 | 同步 < 50ms | mocked TXBridge.getCashDrawerState |
| 7 | `test_rls_isolation_tier1.py::test_pos_crash_cross_tenant_403` | 传菜员误用店长 token 查 tenant_B 崩溃报告，返回 403，`trade_audit_logs` 写 deny 一条 | < 100ms | 双 tenant fixture + RBAC 装饰器 |
| 8 | `test_telemetry_routes.py::test_pos_crash_audit_log_full_coverage` | 每条 pos_crash_reports 写入都触发 trade_audit_logs 一条 `action=pos_crash_report`，包含 saga_id / order_no | < 100ms | audit_log 表 fixture |
| 9 | `featureFlags.test.ts::test_flag_rollback_on_error_rate_over_threshold` | 灰度 5% → 50% 过程中错误率 > 0.1%，feature flag 自动回退，ErrorBoundary 降级到 legacy 行为 | < 200ms | mocked flag poller |
| 10 | `Toast.test.tsx::test_toast_5_types_queue_management` | 高峰连续触发 5 种 Toast（success/error/info/warning/offline），队列最多 3 条，超出的淘汰最老 | 渲染 < 50ms | React Testing Library |

---

## 4. 文件变更清单（TDD 顺序：先测试后实现）

### 4.1 阶段 1 — 测试文件先行（预计 1.5 人日）

| 路径 | 动作 | 预估行 |
|---|---|---|
| `apps/web-pos/src/components/__tests__/ErrorBoundary.test.tsx` | **追加**用例 1/2/6 | +180 |
| `apps/web-pos/src/components/__tests__/Toast.test.tsx` | **追加**用例 10 | +80 |
| `apps/web-pos/src/api/__tests__/tradeApi.test.ts` | **追加** 3s 超时 + AbortController 测试 | +120 |
| `apps/web-pos/src/config/__tests__/featureFlags.test.ts` | **追加**用例 9 | +90 |
| `services/tx-trade/src/tests/test_pos_integration_tier1.py` | **追加**用例 3 | +150 |
| `services/tx-trade/src/tests/test_payment_saga_tier1.py` | **追加**用例 5 | +90 |
| `services/tx-trade/src/tests/test_rls_isolation_tier1.py` | **追加**用例 7 | +60 |
| `services/tx-ops/src/tests/test_telemetry_routes.py` | **追加**用例 8 | +70 |

### 4.2 阶段 2 — 迁移（预计 0.5 人日）

| 路径 | 动作 | 预估行 |
|---|---|---|
| `shared/db-migrations/versions/v265_pos_crash_reports_ext.py` | **新建** — 追加 6 列 + index | +90 |

### 4.3 阶段 3 — 实装（预计 3 人日）

| 路径 | 动作 | 预估行 |
|---|---|---|
| `apps/web-pos/src/components/ErrorBoundary.tsx` | 追加 3s 自动重置、boundary_level 上报、saga_id/order_no 联动 | +80 |
| `apps/web-pos/src/api/tradeApi.ts` | 新增 `TIMEOUT_SETTLE=3000` + AbortController + 重试 1 次 | +120 |
| `apps/web-pos/src/components/Toast.tsx` | 补齐 5 类样式 + 队列（若缺） | +60 |
| `apps/web-pos/src/App.tsx` | 包裹 CashierBoundary 到 /settle /order 路由 | +20 |
| `services/tx-ops/src/api/telemetry_routes.py` | 接收新字段 + 审计日志钩子 | +40 |

### 4.4 阶段 4 — 独立验证 + DEMO 验收（预计 1 人日）

独立新会话 review（见 §7）。

**合计**：~6 人日 / 18.5 人日 = 32% of Sprint A。

---

## 5. 迁移号锁定

| 版本 | 现状 | 本工单动作 |
|---|---|---|
| `v260_pos_crash_reports.py` | **已存在**，down_revision=v259，基础表 + RLS + 2 索引 | **不修改**（冻结应用后的迁移） |
| `v261` / `v262` / `v263` | 已被占用（menu_plan_v2 / franchise_fee / kiosk_voice_count / trade_audit_logs） | **跳过** |
| `v264_agent_roi_fields.py` | **本日 D2 已占用** | **跳过** |
| `v265_pos_crash_reports_ext.py` | **新建** | 6 列：`timeout_reason TEXT`（enum:fetch_timeout/saga_timeout/gateway_timeout/rls_deny/disk_io_error/unknown）、`recovery_action TEXT`（reset/redirect_tables/retry/abort）、`saga_id UUID`（nullable, FK payment_sagas.saga_id）、`order_no TEXT`（nullable，软关联）、`severity TEXT`（fatal/warn/info, default 'fatal'）、`boundary_level TEXT`（root/cashier/unknown）。**down_revision=v264**。所有列 nullable 默认，**向后兼容前端旧版本** |

> **注**：Sprint C3 规划的 `edge_device_registry` 原锁 v264，因本次重排应改 **v266_edge_device_registry**。需架构师在 Sprint A/C 对齐会 15 分钟内裁决。

---

## 6. Flag 注册表

| Flag | 默认 | 灰度路径 | 回退阈值 | 文件 |
|---|---|---|---|---|
| `trade.pos.settle.hardening.enable` | prod=off | pilot 5%（徐记 1 店） → pilot 50%（徐记 4 店+交个朋友 1 店） → prod 100%（徐记 8 店） | 错误率 > 0.1% / 5 分钟滑动窗口 | `flags/trade/trade_flags.yaml:106` |
| `trade.pos.errorBoundary.enable` | prod=off | 同上 | React 崩溃后 `boundary_level=unknown` 占比 > 10% | `flags/trade/trade_flags.yaml:150` |
| `trade.pos.toast.enable` | prod=off | 同上 | Toast 渲染异常率 > 0.5% | `flags/trade/trade_flags.yaml:128` |

三个 flag **联动开关**（必须一起灰度）。`targeting_rules.pilot[0].values` 在 Sprint 中由交易 Owner 分三次填入 store_id。

---

## 7. 独立验证门禁（§19）

本工单**强制触发**独立新会话 review（修改 ≥ 3 文件 + 涉及迁移 + Tier 1 + 权限逻辑 + 跨服务边界）。

| 视角 | 重点 | 新会话提示词要点 |
|---|---|---|
| 跨租户 RLS | 新 v265 6 列是否继承 v260 的 `pos_crash_reports_tenant` 策略 | `test_pos_crash_cross_tenant_403` + 手工 psql 双租户扫描 |
| Saga 超时 | 3s 前端 AbortController 触发后，服务端 payment_saga 是否正确识别为 compensating 而非 failed；钱箱状态一致性 | 关注 `_PENDING_TIMEOUT_MINUTES` 与前端 3s 的语义边界 |
| 断网恢复 | 4h 断网 100 单零丢失，idempotency_key 防重；恢复 60s 内全同步 | 用 toxiproxy 真实断网，非 mock |
| UI 跨组件 | ErrorBoundary / RootFallback / CashierBoundary 三层 fallback 不互相遮蔽 | 手工点击 5 个路由触发 Boom 组件验证 |

---

## 8. 提交策略（§21 原子化）

```bash
# 1. 测试先行
git commit -m "test(web-pos): A1 ErrorBoundary+Toast 场景用例扩充 [Tier1]"
git commit -m "test(tx-trade): A1 200 桌并发+3s 超时+越权 403 场景 [Tier1]"
git commit -m "test(tx-ops): A1 pos-crash audit_log 全覆盖场景 [Tier1]"

# 2. 迁移
git commit -m "migrate: v265_pos_crash_reports_ext 追加 6 列 [Tier1]"

# 3. 后端实装
git commit -m "feat(tx-ops): pos-crash 遥测接收新字段 timeout_reason/recovery_action [Tier1]"

# 4. 前端实装
git commit -m "feat(web-pos): ErrorBoundary 3s 自动重置+boundary_level 上报 [Tier1]"
git commit -m "feat(web-pos): tradeApi 3s 超时+AbortController+1 次重试 [Tier1]"
git commit -m "feat(web-pos): Toast 5 类样式+队列管理 [Tier1]"

# 5. 路由级包裹
git commit -m "feat(web-pos): CashierBoundary 包裹 /settle /order 路由 [Tier1]"

# 6. 灰度
git commit -m "chore(flags): trade.pos.* pilot 5% 放量徐记 17 号店 [Tier1]"
```

**回滚原则**：任一 commit 可 `git revert` 而不影响其他。迁移回滚走 `alembic downgrade v264`。

---

## 9. 预估工时

| 阶段 | 人日 |
|---|---|
| TDD 测试用例先行 | 1.5 |
| v265 迁移 | 0.5 |
| 前端+后端实装 | 3 |
| 独立验证 + DEMO 走查 | 1 |
| **合计 A1** | **6 人日** |

---

## 10. 已知风险

| # | 风险 | 缓解 | 备注 |
|---|---|---|---|
| R1 | **风险登记册 #4 "A2 POS 容器卷权限" 间接影响 A1** — 商米 T2 `/var/tunxiang` 未预配时 A2 SQLite 异常被 A1 捕获并误报为 `saga_timeout` | Edge 在 W1 完成预配；v265 迁移 `timeout_reason` 预留 `disk_io_error` 取值，不建 CHECK 约束 | 依赖 #4 |
| R2 | **前端 3s 与服务端 saga 5min 语义冲突** — abort 后服务端仍在 paying，可能双扣费 | tradeApi.txFetchTrade 每次携带 `idempotency_key`，与 A3 对齐 | **A3 offline_order_mapping 的 order_id 格式依赖本工单决策**，建议锁 UUID v7 + `device_id:ms_epoch:counter` |
| R3 | 遥测端点跨服务（tx-ops 而非规划原文 tx-trade） | 本工单不迁移；A4 trade_audit_logs 双写时同步到 tx-ops | |
| R4 | 迁移号 v264 已被 D2 占用，v265 与 C3 edge_device_registry 冲突 | 本工单锁 v265；C3 改用 v266 | **架构师对齐会裁决** |
| R5 | Flag 默认值 yaml `defaultValue: true` 与 `environments.prod: false` — prod 读取优先级未验证 | 验收前手工在 prod `GET /api/v1/flags?domain=trade` 确认返回 false | |
| R6 | 200 桌并发 P99<200ms 基线未建立，首次跑可能红 | W1 先跑 baseline，再做优化 | H1 k6 脚本可复用 |

---

## 11. DoD（Definition of Done）

- [ ] 10 条 TDD 用例全部 main 绿
- [ ] v265_pos_crash_reports_ext 可 upgrade + downgrade 双向回滚验证
- [ ] 3 个 flag pilot=徐记 17 号店 1 天稳定运行，错误率 < 0.1%
- [ ] 独立验证新会话 review 无 P0/P1 发现
- [ ] `demo-xuji-seafood.sql` 数据集上手工跑通 6 条验收场景
- [ ] `docs/progress.md` 更新 A1 完成记录 + 已知风险

---

## 12. 实装时必读的 5 个文件

- `apps/web-pos/src/components/ErrorBoundary.tsx`
- `apps/web-pos/src/api/tradeApi.ts`
- `shared/db-migrations/versions/v260_pos_crash_reports.py`
- `services/tx-ops/src/api/telemetry_routes.py`
- `flags/trade/trade_flags.yaml`
