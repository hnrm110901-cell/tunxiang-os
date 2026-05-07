# V4 安卓 POS 架构对齐 Sprint（7 天）

**决策日期**：2026-05-06
**决策人**：lichun（创始人）
**触发**：sprint-0-dedup R3 勘察发现 pos 与 shell 各持半套真理，直接合并/删除任一方都把宪法债买进 V4
**原则**：MVP 前 + 稳定 + 零技术债（创始人原则，刻进每天的验收）

---

## 一、决策背景

### 1.1 第一性原理

替换徐记海鲜 23 套系统 + 替换天财商龙存量连锁餐饮商户，两个市场客户的物理需求是一致的：

| 维度 | 阈值 | 谁卡谁出局 |
|---|---|---|
| 单次按键响应 | < 50ms | 80ms 收银员开始抱怨，150ms 直接换系统 |
| 桌台/订单切换 | < 100ms | 高峰期 200 桌反复切，慢 100ms × 千次 = 整晚崩 |
| 称重→显示 | < 200ms | 客户在等 |
| 打印小票首字 | < 500ms | 客户付完款拿小票走人 |
| 断网 4h | 数据零丢失 + 持续出单 + 打印不卡 | Tier 1 已写明 |
| 高峰期内存 | < 4GB（商米 T2 仅 4GB RAM）| OOM = 收银台冻死 |

### 1.2 当前两条路线的结构性缺陷

| | shell（V3）| pos（V4 团队）|
|---|---|---|
| 收银 hot path 性能 | ❌ WebView only 在商米 T2 撑不住高峰 | ✅ Compose Native，60fps 稳定 |
| Mac mini 真相源（路线 C） | ✅ `getMacMiniUrl` 真返回 IP，React 调 mac-station | ❌ pos/TXBridge.kt:121 注释"Room DB replaces Mac mini for POS"，绕开 mac-station |
| §十三 第 1 条铁律（Kotlin 不写业务） | ✅ 0 业务代码 | ❌ 5 屏 Compose 共 2186 行业务 |
| 商米 SDK 接入 | ✅ ServiceConnection + BroadcastReceiver + 11 JS API | ⚠️ DI 风格 4 个类，TXBridge 是 stub |
| OTA v094 | ✅ 实装 | ❌ 缺 |
| 多端复用（iPad/Windows）| ✅ 一套 React 跨端 | ❌ 5 屏 Native 不可复用 |
| AI/营销/看板高频迭代 | ✅ React 改 5 分钟全店生效 | ❌ APK 重打 1-2 周 |

**结论**：两条路线各持半套真理。直接 plan A（删 shell 保 pos）= 把违路线 C 的 V4 钉死；反向 A（删 pos 保 shell）= 把 hot path 性能债钉死。

### 1.3 V4 正解 = 混合架构 + Mac mini 真相源

```
┌────────────────────────────────────────────────────────┐
│ android-pos (Compose 主进程)                            │
│                                                         │
│  Hot Path (Native Compose, 性能锁 < 50ms)              │
│  ├── OrderScreen / TableMapScreen / SettleScreen       │
│  ├── ShiftScreen / DailyCloseScreen                    │
│  └── 直调 Sunmi SDK (打印/称重/扫码/钱箱)              │
│       ↓ 数据真相源                                       │
│  Cool Path (WebViewScreen + React)                     │
│  ├── 菜品菜单 CMS (高频改价)                            │
│  ├── 营销活动 / 优惠券规则                              │
│  ├── 经营驾驶舱 / Agent 决策弹窗                        │
│  ├── 总部 SOP / 培训 / 通知                             │
│  ├── 报表 / 财务 / 食安上报                             │
│  └── 通过 TXBridge (DI 风格 + 11 JS API) 调外设        │
└────────────────────────────────────────────────────────┘
            ↓ 唯一真相源 + 唯一同步路径
┌────────────────────────────────────────────────────────┐
│ Mac mini (mac-station) — 路线 C                         │
│  ├── 本地 PG 真相源                                     │
│  ├── Room 仅作 4h 断网缓冲（带 TTL + 同步水位）         │
│  └── sync-engine ↔ 云端 PG                              │
└────────────────────────────────────────────────────────┘
```

---

## 二、Sprint 节奏（7 天 = 5 工程日 + 2 缓冲日）

### Day 1 — 边界决策 + 完成度 verify

**目标**：把 hot/cool path 边界写死，verify 现有资产够不够支撑边界。

**动作**
1. **边界决策清单**（@创始人 半天）
   - hot path 5 屏锁定：OrderScreen / TableMapScreen / SettleScreen / ShiftScreen / DailyCloseScreen
   - cool path 屏列表：菜品 CMS / 营销 / 看板 / 报表 / Agent 决策弹窗 / SOP / 食安上报 / 设置 / 跨品牌切换 / 培训
   - 灰色地带逐一定性（如：会员卡查询是 hot 还是 cool？）
2. **android-pos 5 屏完成度审计**（@android）
   - 5 屏功能覆盖度 vs 徐记海鲜真实业务流（点单/桌台/结算/换班/日结）
   - SunmiPrinter / Scanner / Scale / CashBox 4 个类是 stub 还是真实装
   - WebViewScreen 现状（是否真能加载 React）
3. **web-pos React cool path 完成度审计**（@frontend）
   - 上面 cool path 屏列表里每个屏在 web-pos 是否存在
   - 缺口列表 → D5 同步补
4. **shell 资产抢救清单**（@android）
   - TXBridge.kt 247 行 11 个 JS API + ServiceConnection + BroadcastReceiver
   - MainActivity.kt 100 行（WebView 全屏 + Bridge 注入 + 商米生命周期）
   - OTA v094 实装代码位置（git show 找）

**D1 验收**：
- [ ] 边界清单签字（创始人）
- [ ] pos 5 屏完成度报告 + 缺口列表
- [ ] React cool path 完成度报告 + 缺口列表
- [ ] shell 抢救清单（行号锚点 + git sha）

---

### Day 2 — Repository 层改造（Room 降级为缓冲，Mac mini 升级为真相源）

**目标**：解决 §八 路线 C 违反。

**动作**
1. 改造 `apps/android-pos/src/main/kotlin/com/tunxiang/pos/data/repository/*Repository.kt`（4 个：Order / Table / Dish / Sync）
   - 真相源：mac-station HTTP API
   - 缓存：Room（**仅作 4h 断网缓冲，带 `expires_at` 字段**）
   - 读：先尝试 mac-station，失败 → 读 Room 缓冲
   - 写：先写 mac-station，成功 → 同步写 Room；mac-station 不可达 → 仅写 Room + 标记 `pending_sync`
2. 改造 Room schema：每张表加 `synced_at`、`source` 字段（区分本地/远程）
3. 改造 `data/remote/ApiClient.kt`：baseUrl 从云端切到 mac-station 局域网 IP
4. 单元测试：每个 Repository 三种场景（Mac mini 在线 / Mac mini 离线但 Room 有 / 全空）
5. 离线 4h 模拟测试（断网 4h → 恢复 → 验证数据一致性）

**D2 验收**：
- [ ] 4 个 Repository 改造完成
- [ ] Room schema 加 `expires_at`/`synced_at`/`source` migration 跑过
- [ ] 单元测试全绿
- [ ] 4h 模拟测试 0 数据丢失

---

### Day 3 — SyncManager 改造（Mac mini 是同步中枢）

**目标**：把双向同步统一到 Mac mini，不再让安卓直连云端。

**动作**
1. 改造 `apps/android-pos/src/main/kotlin/com/tunxiang/pos/sync/SyncManager.kt`
   - sync target：从 `TxCoreApi`（云端）改为 `mac-station HTTP API`
   - mac-station 内部已有 sync-engine 负责向云端同步（300秒/轮）→ 安卓不直接管云端
2. 改造 `sync/SyncWorker.kt` WorkManager 任务
3. 局域网 mac-station 发现机制（mDNS / 配置注入 / 轮询）—— 与 D4 的 `getMacMiniUrl` 实装协同
4. 商米 T2 真机断网 4h 演练
   - 演练剧本：开台 → 点单 → 改菜 → 结账 → 拔网线 4h → 接网 → 验证数据已 sync

**D3 验收**：
- [ ] SyncManager target 改 mac-station
- [ ] mac-station 局域网发现机制工作
- [ ] 真机 4h 断网演练 0 数据丢失（与 D2 单元测试是不同层级）

---

### Day 4 — TXBridge 工程合并（B 方案）+ getMacMiniUrl 真实装

**目标**：解决 cool path 的 WebView 真接入。

**动作**
1. **抢救 shell 资产到 pos**（cherry-pick 风格）
   - shell/TXBridge.kt 247 行的方法体逐个对照，映射到 pos 的 DI 注入（`SunmiPrinter / Scanner / Scale / CashBox`）
   - shell 的 `ServiceConnection`（绑定 `com.sunmi.printerservice`）→ 移到 pos 的 `MainActivity.onCreate`
   - shell 的 `BroadcastReceiver` 注册/注销 → 同样移到 pos `MainActivity` 生命周期
   - 11 个 `@JavascriptInterface` 方法填实装：print / printText / openCashBox / startScale / onScaleData / scan / onScanResult / getDeviceInfo / getMacMiniUrl / reportHeartbeat / stopScale
2. **`getMacMiniUrl` 真实装**
   - 删除 stub `return ""`
   - 替换为：返回 D3 实装的 mac-station 局域网 IP
3. **OTA v094 cherry-pick**
   - 从 shell 的 v094 commit cherry-pick OTA 模块到 pos
4. **WebViewScreen 真接入**
   - cool path 屏列表里每个 URL 走 WebViewScreen 加载
   - 注入 TXBridge 到每个 WebView 实例
5. **商米 T2 真机验证**
   - 真机 print/scale/scan/cashBox 全链路过
   - WebView 加载一个 cool path 屏，从 React 调 `window.TXBridge.print()` 全过

**D4 验收**：
- [ ] TXBridge 247 行真实装迁移完成（DI 风格统一）
- [ ] `getMacMiniUrl` 返回真实 IP
- [ ] OTA v094 在 pos 实装
- [ ] 真机外设 4 件套全过
- [ ] React → WebView → TXBridge → Sunmi SDK 全链路过

---

### Day 5 — CLAUDE.md 宪法修订 + ADR

**目标**：让宪法跟代码一致，避免下一次"代码先走，宪法滞后"。

**动作**
1. **CLAUDE.md §三 "技术路线"** 重写
   - 旧："一套 React Web App，多端运行"
   - 新："**Native 收银核心 + React 辅助 surface，TXBridge 桥接**" + hot/cool path 边界图
2. **CLAUDE.md §七** 整节重写为"安卓 POS 混合壳规范（android-pos）"
   - 分 Native hot path 段（5 屏 Compose 锁定）+ WebView cool path 段（React 加载 + TXBridge）
   - shell 名字从规范文档撤掉
3. **CLAUDE.md §十三 第 1 条铁律删除并替换**
   - 旧："禁止在 Kotlin/Swift 层写业务逻辑 — 壳层只做桥接"
   - 新："**Hot path 必须 Native 写业务，cool path 必须 WebView 写业务，Native 与 WebView 之间通过 TXBridge / Mac mini PG 真相源解耦**"
4. **CLAUDE.md §十二 "iPad 可选升级包"** 微调
   - iPad 只承载 cool path（React/WebView），hot path 通过 HTTP 转发到安卓 POS
5. **新增 `docs/architecture/ADR-001-hybrid-architecture.md`**
   - 决策背景（V3 shell 的 WebView only 路线 + V4 pos 的 Native only 路线 各持半套真理）
   - 第一性原理推导（hot/cool path × 性能/灵活 双坐标）
   - 决策内容（混合架构 + Mac mini 真相源）
   - 后果/风险/回滚条件

**D5 验收**：
- [ ] CLAUDE.md §三/七/十三/十二 修订
- [ ] ADR-001 完成
- [ ] 内部 review（创始人签字）

---

### Day 6 — Tier 1 全链路真机回归

**目标**：徐记海鲜验收门槛达标证据。

**动作**（按 CLAUDE.md §二十二 W8 demo 验收门槛逐项）
1. **Tier 1 全绿** — 订单/支付/RLS/POS/存酒/发票
2. **P99 延迟 < 200ms** — 200 桌并发模拟
3. **支付成功率 > 99.9%** — 含超时/失败回滚
4. **断网恢复 4h 0 数据丢失** — 真机 4h 演练
5. **收银员现场使用** — 至少 1 名非技术员工 30 分钟无障碍操作

商米 T2 + Mac mini M4 真机 + Mac mini 与云端的 Tailscale 链路全部联调。

**D6 验收**：
- [ ] 5 项 W8 门槛达标，留证据（视频/log/截图）

---

### Day 7 — 删 shell + 收尾

**目标**：物理收敛。

**动作**
1. `git rm -r apps/android-shell`
2. CLAUDE.md §五 项目结构：删 `android-shell/` 行
3. 检查 `web-pos` 是否仍有 React 实现 hot path 5 屏对应业务——如果有，**降级 / 删除**这部分（避免双轨）
4. 检查 `ios-shell`：iPad 应只加载 cool path React，更新代码注释
5. 单一 commit 串联整个 sprint：`feat(android): V4 hybrid architecture alignment + drop V3 shell`
6. 更新 sprint-0-dedup.md：R3 状态从 SUSPENDED 改为 ✅ COMPLETED
7. DEVLOG.md + docs/progress.md 更新

**D7 验收**：
- [ ] android-shell 删除
- [ ] sprint-0-dedup R3 标记 COMPLETED
- [ ] DEVLOG / progress / CLAUDE.md 全部一致

---

## 三、ROI 与风险

### 3.1 ROI

| 方案 | 当下 | 6 个月内重构 | 总 |
|---|---|---|---|
| 不做（保持双轨）| 0 | 必须 + 客户损失 | 大债 |
| plan A 删 shell | 0.5d | 必须 1-2 周 | 中债 |
| 反向 A 删 pos | 0.5d | 必须 1-2 周（重做 hot path）| 大债 |
| **本 sprint** | **7 天** | 0 | **零债** |

### 3.2 风险表

| 风险 | 概率 | 缓解 |
|---|---|---|
| pos 5 屏完成度低于预期，D1 暴露后必须延期 | 中 | D1 是 hard gate，未通过即停 |
| Mac mini 局域网发现机制不稳 | 中 | D3 真机演练前提 + mDNS / 配置双备 |
| 商米 T2 真机问题 | 中 | D4/D6 双次真机验证 |
| 宪法修订后团队认知不一致 | 低 | D5 ADR + 创始人签字 + 沟通会 |
| 并发会话切分支污染 | 高（已实锤）| 每 commit 后 git status + 锁定分支 |

### 3.3 回滚条件

任何一条触发即整 sprint 回滚到 V4 启动前 sha：

- D2 4h 模拟失败（>0 数据丢失）
- D3 真机 4h 演练失败
- D6 任一 W8 门槛未达
- D5 ADR 创始人不签

---

## 四、命名 / 分支 / Commit 策略

- 工作分支：`feat/v4-architecture-alignment`（不在 sprint-0-dedup 上做）
- 基分支：`main`（确保起点干净）
- 每天一个或多个 atomic commit，commit message 前缀按 CLAUDE.md §二十一：
  - `refactor(android): ...` / `feat(android): ...` / `docs(architecture): ...`
- D7 收尾 commit 标 `[Tier1]` 因为涉及 W8 验收
- PR 标题：`feat(android): V4 hybrid architecture alignment + drop V3 shell`
- PR body 引用本 plan + ADR-001

---

## 五、与 sprint-0-dedup 的关系

- sprint-0-dedup 的 R3 标记 SUSPENDED → 升级到本 sprint
- sprint-0-dedup 的 R1/R6/R7/R4 不依赖 R3，**继续推进**
- 本 sprint **独立 PR**，不混入 sprint-0-dedup PR
- 本 sprint 完成后回头把 sprint-0-dedup R3 状态改 ✅ COMPLETED

---

## 六、不在本 sprint 范围

明确**不做**的事：
- ❌ 不动 ios-shell 业务实装（只更新注释）
- ❌ 不动 windows-pos-shell（路线 C 已淘汰，但本 sprint 不处理）
- ❌ 不动 web-pos 的现有 cool path React 屏（除非发现与 hot path 重叠需删）
- ❌ 不引入新业务功能
- ❌ 不动 mac-station 的 sync-engine 内部逻辑（接入 OK，内部不改）
- ❌ 不动 Tier 1 路径的业务规则（架构对齐 ≠ 业务变更）

---

## 七、一句话

> 屯象 V4 架构对齐 = **承认 hot/cool path 不该用同一种技术栈**。这一周买回的不是代码，是 6 个月后徐记海鲜不退货的概率。

---

## 附录 A · Pre-D1 资产 Audit（2026-05-07）

> 在 V4 sprint 正式启动（D1）之前对 pos / shell / web-pos 做的只读盘点，结果直接修订本 plan 的工时与步骤。

### A.1 android-pos Hot Path 完成度

| 屏 | 行数 | @Composable | 外部调用 | 业务实装 |
|---|---:|---:|---:|---|
| OrderScreen | 406 | 3 | 10 | ✅ 充实 |
| TableMapScreen | 316 | 2 | 6 | ✅ |
| SettleScreen | 462 | 4 | 6 | ✅ |
| ShiftScreen | 428 | 4 | 4 | ✅ |
| DailyCloseScreen | 434 | 3 | 5 | ✅ |
| WebViewScreen（fallback）| 140 | 1 | 0 | ⚠️ 占位，需增强 |

5 屏 Compose 业务**已充实**，但**调用方仍走 Room + 云端**（违路线 C，待 D2/D3 改造）。

### A.2 android-pos Sunmi SDK 接入（关键缺口）

| 类 | 行数 | Sunmi import | 状态 |
|---|---:|---:|---|
| **SunmiPrinter** | 309 | **0** | 🔴 注释明说 "In production, this would be IWoyouService" — **未接 SDK** |
| **SunmiCashBox** | 68 | **0** | 🔴 主路径未接 SDK，走 ESC/POS fallback |
| SunmiScanner | 132 | 2 | 🟢 真接 SDK |
| SunmiScale | 110 | 2 | 🟢 真接 SDK |

**结论**：打印 + 钱箱 = 骨架 stub，扫码 + 称重 = 真实装。D4 必须把 shell 的 IWoyouService 真接入迁过来。

### A.3 android-shell 抢救清单（V3 真货）

| 资产 | 内容 |
|---|---|
| TXBridge.kt（247 行）| ServiceConnection + BroadcastReceiver + 11 JS API + Sunmi 服务真绑 |
| MainActivity.kt（100 行）| WebView 全屏 + Bridge 注入 + Sunmi 生命周期 |
| **AIDL 文件 ⭐** | `aidl/woyou/aidlservice/jiuiv5/IWoyouService.aidl` + `ICallback.aidl`（Sunmi SDK 关键接入文件，pos 没有）|

### A.4 OTA v094 已在 main 分支 ✅

OTA v094 (commit `d54f05b4`, 2026-04-01) 实装分布在：

| 位置 | 行数 | 用途 |
|---|---:|---|
| `shared/db-migrations/versions/v094_ota_management.py` | 112 | `app_versions`（含灰度 rollout_pct + 租户专属）+ `ota_check_logs` |
| `services/tx-org/src/api/ota_routes.py` | 295 | 云端 5 端点：发布/列表/最新版/撤回/进度 |
| `edge/mac-station/src/ota_routes.py` | 151 | 边缘检查端点（1h 本地缓存）|

**OTA 后端已就绪 → 本 plan 不再需要单独 D-OTA 步骤**（节省 0.5d）。

### A.5 web-pos React Cool Path 完成度

✅ 已有：menu(4) / dish(2) / coupon(3) / dashboard(1) / report(5) / training(5) / agent(3)

🔴 **缺口（V4 sprint 内补，+2d，2026-05-07 创始人决策）**：
- `marketing` 0 文件
- `campaign` 0 文件
- `food_safety` 0 文件
- `cross-brand` 0 文件

⚠️ 单文件（薄弱）：sop / setting / decision

### A.6 双轨债 — web-pos 的 hot path 副本

`apps/web-pos` 同时存在 hot path 5 屏的 React 实装：

| Hot Path 屏 | React (web-pos) | Native (android-pos) |
|---|---:|---:|
| Cashier / Order | 2 + 10 files | ✅ |
| OpenTable / FloorMap | 2 files | ✅ TableMapScreen |
| Handover | 2 files | ✅ ShiftScreen |
| Settlement / DepositPos / Discount | 3+ files | ✅ SettleScreen |
| DailySettlement | 1 file | ✅ DailyCloseScreen |

**创始人决策（2026-05-07）：D7 直接删 web-pos hot path 副本，不冻结**——避免双轨永久回流风险。

---

## 附录 B · 工时与步骤修订（基于附录 A 的 Audit）

| 项 | 原 plan | 修订 | 净变 |
|---|---:|---:|---:|
| D-OTA（独立步骤）| +0.5d | ❌ 删除（A.4 已落 main）| **-0.5d** |
| D4 cherry-pick 范围 | 0.5d | 1d（含 AIDL 2 文件 + IWoyouService 真接入到 SunmiPrinter/SunmiCashBox）| **+0.5d** |
| **D5b**（新增）：补 4 个 cool path 缺口屏 | — | **2d** | **+2d** |
| D7 删 web-pos hot path 副本 | 已含但未细化 | 明确动作 + 验证 | 0 |
| **总计** | 7d | **9d** | **+2d** |

### 修订后节奏

```
D1   边界决策 + 完成度 verify              (1d, hard gate)
D2   Repository 改造（Room → Mac mini）    (1d)
D3   SyncManager 改造 + mac-station 发现   (1d)
D4   TXBridge AIDL cherry-pick + Sunmi
     真接入（SunmiPrinter / SunmiCashBox） (1d)  ← 含 AIDL 2 文件迁移 + IWoyouService 实绑
D5   CLAUDE.md §三/七/十二/十三 修订
     + ADR-001-hybrid-architecture         (1d)
D5b  补 4 cool path 缺口屏（marketing /
     campaign / food_safety / cross-brand）(2d)  ← 新增
D6   Tier 1 全链路真机回归（W8 验收）       (1d)
D7   删 shell + 删 web-pos hot path 副本
     + 收尾                                (1d)

总：9 工程日 + 2 缓冲日 = 11 日历日（约 1.5 周）
```

---

## 附录 C · D7 web-pos hot path 副本删除清单（细化）

D7 必须删除（基于 A.6 双轨清单）：

| 文件类 | 路径 | 删除依据 |
|---|---|---|
| Cashier / Order 类 | `apps/web-pos/src/pages/CashierPage.tsx` + `OrderPage.tsx` + `OrderHistoryPage.tsx` + `OrderActionPanel.tsx` 等 12 文件 | hot path 走 Compose Native |
| Table 类 | `OpenTablePage.tsx` + `FloorMapPage.tsx` | hot path 走 TableMapScreen |
| Handover | `HandoverPage.tsx`（2 文件）| hot path 走 ShiftScreen |
| Settlement 类 | `DepositPosPage.tsx` + `DiscountAuditPage.tsx` + 3 文件 | hot path 走 SettleScreen |
| DailySettlement | `DailySettlementPage.tsx` | hot path 走 DailyCloseScreen |

**D7 验收**：
- [ ] grep `apps/web-pos/src/pages/Cashier|Order|Settle|Handover|DailySettlement` → 0 匹配
- [ ] web-pos build 仍成功（删除后 router 同步清理）
- [ ] iPad WKWebView 加载 web-pos 仅显示 cool path（hot path 自动 redirect 到 android-pos HTTP）
