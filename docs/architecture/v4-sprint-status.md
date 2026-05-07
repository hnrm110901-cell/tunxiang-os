# V4 Sprint 进度报告（2026-05-07）

| 字段 | 值 |
|---|---|
| 文档类型 | Sprint progress report |
| 日期 | 2026-05-07 |
| 范围 | V4 架构对齐 sprint：feat/v4-architecture-alignment 分支全部 9 commits |
| PR | #240（draft）https://github.com/hnrm110901-cell/tunxiang-os/pull/240 |
| 状态 | sandbox 部分完成（D1/D2/D3/D5/D5b ✅）；D4/D6/D7 等真机 + 远端依赖项 |

---

## 一、Sprint 起源

V4 sprint 由 sprint-0-dedup PR #239 R3 升级而来。sprint-0-dedup R3 原计划是合并 `apps/android-shell` 入 `apps/android-pos`，但深入勘察发现 pos 当前实装存在**双重 CLAUDE.md 宪法违反**：

- `pos/TXBridge.kt:121` 注释 "Room DB replaces Mac mini for POS" → 违反 §八 路线 C
- pos 5 屏 Compose 共 2186 行业务 → 违反 §十三 第 1 条铁律 "禁止 Kotlin 写业务逻辑"

shell 路线相反：getMacMiniUrl 真返回 IP（符合路线 C），但 WebView only 在商米 T2 收银 hot path 物理性能边界以内不够稳。

按"MVP 前 + 稳定 + 零技术债"原则，R3 不能在 sprint-0-dedup 范围内闭环，升级为独立 V4 架构对齐 sprint，目标：

- 修订 CLAUDE.md §三/七/十二/十三 hot/cool 混合架构宪法
- 修复 §八 路线 C 违反（Mac mini PG 真相源化）
- 修复 §十三 第 1 条铁律（Kotlin 允许在 hot path 写业务）
- D7 收尾时删除 android-shell + 删除 web-pos hot path React 副本

---

## 二、9 Commits 时间线

| # | sha | 类型 | Tier | 一句话 |
|---|---|---|---|---|
| 1 | `e1482a92` | docs | — | D1 audit + boundary draft（314 LOC）|
| 2 | `63dcf7de` | docs | — | D1 boundary signed off（G1-G20 全同意）|
| 3 | `456a402d` | feat | T2 | D2 stage 1：5 Entity sync 字段 + Migration v1→v2 + ApiClient inject |
| 4 | `9c8464ad` | fix | T2 | D2 review hotfix：B1 source 默认值 + B2/W1 注释 |
| 5 | `e0fc5635` | feat | T2 | D3 stage 1：runtime baseUrl + SyncSource 常量 + Resolver 单例 |
| 6 | `a328e40c` | fix | T2 | D3 review hotfix：B1 SyncManager + B2/W1/W2/W5 |
| 7 | `7683cbcc` | docs | — | D5：CLAUDE.md §三/七/十二/十三 + ADR-0002 hybrid-architecture |
| 8 | `e5e19a4c` | fix | — | D5 review hotfix：B1-B4 + W1-W7 + N3 |
| 9 | `afb191cf` | feat | T3 | D5b：4 cool path 缺口屏 + TXBridge.ts +3 方法 |

---

## 三、每个 Day 输出

### Day 1（hard gate）— ✅ 完成

**输出**：
- `docs/architecture/v4-pre-d1-audit.md`（176 行）— android-pos 5 屏完成度 + Sunmi 4 类（2 stub + 2 real）+ android-shell 抢救清单 + OTA v094 已落 main + web-pos cool path 4 缺口 + 双轨债清单
- `docs/architecture/v4-d1-hot-cool-path-boundary.md`（138 行 → sign-off 后）— Hot path 5 屏锁定 / Cool path 9 类锁定 / 20 灰色地带创始人逐项决策（13 hot + 7 cool）

**关键成果**：边界决策成文档化 + 创始人 sign-off。D1 是 hard gate，未通过则整 sprint 不启动。

### Day 2（schema + ApiClient inject）— ✅ 完成 + review hotfix

**stage 1 改动**（`456a402d`）：
- 5 Room Entity 加 `expires_at: Long?` / `source: String` / `synced_at: Long?` 三字段
- 新建 `Migrations.kt`（MIGRATION_1_2：5 表 × 3 列 = 15 ALTER）
- `TunxiangDatabase` version 1 → 2
- `TunxiangPOSApp.onCreate` 加 mac-station baseUrl 解析逻辑（SharedPreferences 优先 + BuildConfig fallback）
- 删 `fallbackToDestructiveMigration()` 替为 `addMigrations()`

**Review 揪出**：2 BLOCKER + 4 WARNING
- **B1**: `source = "remote"` 默认值会让断网期间本地创建订单被错标为 remote → 直接威胁 W8 demo 断网 4h 验收
- **B2**: `resolveApiBaseUrl()` 一次性读 + URL 固化进 ApiClient 实例，D4 mDNS 写 prefs 后不会动态生效

**Hotfix（`9c8464ad`）**：
- 3 写入表（LocalOrder/LocalOrderItem/LocalPayment）`source` 默认值改 `"local-pending"`，2 只读表保持 `"remote"`
- Migration SQL 拆按表设默认值
- B2/W1（Migration 失败应急）/W4（事务原子性）加注释（真正修复留 D3）

### Day 3（runtime baseUrl + SyncSource）— ✅ 完成 + review hotfix

**stage 1 改动**（`e0fc5635`）：
- 新建 `data/local/SyncSource.kt`：const object（REMOTE / LOCAL_PENDING / LOCAL_SYNCED + ALL）
- `ApiClient` 加 `setBaseUrl()` + `@Volatile/@Synchronized` + buildRetrofit 私有工厂
- `txCoreApi` val → property getter
- 新建 `data/remote/ApiBaseUrlResolver.kt`：单例监听 SharedPreferences → 通知 ApiClient
- TunxiangPOSApp 用新 Resolver

**Review 揪出**：2 BLOCKER + 5 WARNING
- **B1**: SyncManager + 4 Repositories 在构造时固化 `txCoreApi` proxy，setBaseUrl 后这些消费者继续用旧 proxy → mDNS 切换完全失效
- **B2**: `attachReactivePropagation` 与 `resolveInitialUrl` 之间存在 race window，fast mDNS 写入会丢失

**Hotfix（`a328e40c`）**：
- SyncManager 接收 `ApiClient` 引用（不再固化 TxCoreApi），用 getter 按需读
- attachReactivePropagation 末尾 race-fix：再读 prefs 校对
- W1 修：用 `RetrofitState data class @Volatile` 单字段原子化（替代 3 字段独立 @Volatile）
- W2 修：runCatching 加 Log.e
- W5 修：`SyncSource.ALL` wrap 为 `unmodifiableSet`
- 4 Repository 加 stage-2 必修 TODO 注释（真正 lockstep 改造留 D3 stage 2）

### Day 5（CLAUDE.md 宪法 + ADR）— ✅ 完成 + review hotfix

**改动**（`7683cbcc`）：
- §三 重写：title "Web App + 多壳层" → "Native Hot Path + WebView Cool Path 混合架构" + 边界图 + 决策原则
- §七 整节重写："android-shell" → "android-pos 混合壳"（hot path 直调 SDK / cool path TXBridge / shell 抢救清单）
- §十二 微调：iPad 仅承担 cool path + Hot Path Jump 模式
- §十三 第 1 条替换：旧"禁止 Kotlin 写业务" → 新"Hot/Cool Path 边界铁律"
- 新建 `docs/adr/0002-hybrid-architecture.md`（163 行）— 第一性原理推导 + Palantir Ontology 思想 + 回滚条件

**Review 揪出**：4 BLOCKER + 7 WARNING + 3 NIT
- **B1**: §十 Kotlin 编码规范节仍写"不写业务逻辑"，与 §七 V4 修订矛盾
- **B2**: §三 技术栈表 Kotlin 行未更新（仍是"加载 React App"）
- **B3**: §十二 helper 函数命名 `isAndroidPOSWebView` 与现有 `TXBridge.ts` 的 `isAndroidPOS` 不一致 + TXBridge.ts 缺 V4 新 3 方法
- **B4**: ADR `.omc/plans/v4-architecture-alignment.md` 链接在 V4 worktree 不存在（实际 live 在 sprint-0-dedup 分支）

**Hotfix（`e5e19a4c`）**：
- B1: §十 Kotlin/Swift 节改 hot/cool 二元
- B2: §三 表格行重写
- B3: §十二 helper 名对齐 `TXBridge.ts` 现有命名 + 加 D5b 必修 TODO（D5b 已闭环此 TODO）
- B4: 加 footnote 说明 `.omc/plans/*` 链接 PR #239 merge 后生效
- W1-W7 全部修（§五 / §七 / §九 / §二十二 + ADR §3.2 / §4.2 / §五）
- N1-N3 全部处理

### Day 5b（4 cool path 缺口屏 + TXBridge.ts +3）— ✅ 完成

**改动**（`afb191cf`）：
- 新建 `pages/MarketingPage.tsx`（113 LOC）：营销活动列表 + 状态过滤
- 新建 `pages/CampaignPage.tsx`（167 LOC）：单活动详情/创建 form
- 新建 `pages/FoodSafetyPage.tsx`（213 LOC）：食材溯源/关键温度/上报记录 3 tab
- 新建 `pages/CrossBrandPage.tsx`（162 LOC）：品牌列表 + 门店切换
- App.tsx 加 5 routes（`/marketing` / `/campaigns/:id` / `/campaigns` / `/food-safety` / `/cross-brand`）
- `bridge/TXBridge.ts` NativeTXBridge interface +3 方法（printText / stopScale / reportHeartbeat）→ 闭环 D5 review B3 D5b TODO

**性质**：UI 骨架（mock 数据 + 占位 UI），无业务逻辑接入。后续 sprint 接 backend API。

---

## 四、累积 LOC

| 类别 | 净 +/- |
|---|---|
| Kotlin（Android）| +393 / -54 |
| TypeScript（React + TXBridge）| +674 / -1 |
| Markdown（docs + ADR）| +1234 / -98 |
| **合计** | **+1756 / -153 ≈ 净 +1603 行** |

D1/D5/D5 hotfix 是 docs；D2/D3 + hotfix 是 Kotlin；D5b 是 TypeScript。

---

## 五、Review 闭环统计

3 轮独立 review（CLAUDE.md §十九 触发）：

| Review | BLOCKER | WARNING | NIT | hotfix commit |
|---|---:|---:|---:|---|
| D2 review | 2 | 4 | — | `9c8464ad` |
| D3 review | 2 | 5 | — | `a328e40c` |
| D5 review | 4 | 7 | 3 | `e5e19a4c` |
| **合计** | **8** | **16** | **3** | **3 hotfix commit** |

**所有 BLOCKER 均有 fix commit 或显式 deferred 说明**；W2/W3/W4/N1/N2 在 commit message 中明确 deferred 给后续 D（D3 stage 2 / D6）。

零静默忽略。**D3 review B1 Repository 部分为有意 deferred**（4 Repository + 5 Screen lockstep 改造留 D3 stage 2），SyncManager 已闭环；此 deferred 在本文档 §八 与 4 Repository 顶部 TODO 注释双向 tracked。

---

## 六、当前状态全景

### V4 Sprint 完成度

| Day | 状态 | sandbox 完成 | 真机/远端依赖 |
|---|---|---|---|
| D1 | ✅ | docs only | — |
| D2 stage 1 | ✅ + review | schema + Migration | D6 真机回归 |
| D3 stage 1 | ✅ + review | runtime baseUrl + SyncSource | D6 真机回归 |
| D5 | ✅ + review | CLAUDE.md + ADR | — |
| D5b | ✅ | 4 React 屏**骨架（mock 数据，无业务 API 接入）** + TXBridge.ts +3 方法 | npm build verify + 后续 sprint 接 backend API |
| D4 | ⏸ | — | 真机：cherry-pick TXBridge AIDL + Sunmi 真接入 |
| D6 | 🔴 阻塞 | — | PR #228 + audit p0 链 ship 到 main |
| D7 | ⏸ | — | D6 通过后才能删 shell + 删 web-pos hot path 副本 |

### Repository 4 个 + Screen 5 个的 stage 2 改造（D3 review B1 部分修留作）

留 stage 2 与 Screen 端 lockstep 改造，避免 sandbox 改 Repository 但 Screen 端没改导致 mismatch：

- `OrderRepository.kt` / `DishRepository.kt` / `TableRepository.kt` / `SyncRepository.kt` 4 文件接收 `apiClient: ApiClient` 而非 `api: TxCoreApi`
- `OrderScreen.kt` / `SettleScreen.kt` / `DailyCloseScreen.kt` / `ShiftScreen.kt` / `TableMapScreen.kt` 5 文件 `remember {}` 块构造同步改造

每个 Repository 顶部已加 `// ⚠️ V4 sprint D3 stage 2 (REVIEW B1, 2026-05-07)` 注释作为防漏改 guard。

---

## 七、远端依赖 / 阻塞

### Origin/main 漂移（V4 worktree 需 rebase）

V4 worktree 起点是 `0fee73b7`（2026-05-06），但 origin/main 在会话期间已推进 4 commits：

```
4a373343  fix: PR #239 R6 pinzhi 重命名漏改 7 处 + #241 narrative 漏 round  ← R6 的后续 hotfix
e9dc62ff  chore(dedup): sprint-0 R1-R7 (5 done + 1 SUSPENDED + 1 cancelled)  ← PR #239 merge ★
cefe66c9  docs(devlog): 2026-05-06 续² PR #237 merge + 4 PR/Issue review + #241
0fe462d4  fix: _fen 字段全用 int 对齐 §10/§15 金额规范
```

**关键事实**：sprint-0-dedup PR #239 已 merge 到 main（含 V4 sprint plan v2 + R3 升级文档）→ V4 worktree 需要 rebase main 以解锁 ADR-0002 中 `.omc/plans/*` footnote 标记的"待 PR #239 merge 后生效"的链接。

**Rebase 冲突预判（2026-05-07 全量 review 修订）**：

- ✅ 无冲突域：android-pos / web-pos / docs/adr / docs/architecture（V4 改） vs shared/adapters/pinzhi → pinzhi_pos（main 改）
- ⚠️ **CLAUDE.md §五 项目结构（mac-mini 行）有 1 处已知 3-way conflict**：
  - main：sprint-0-dedup R2 已删 `edge/mac-mini/` 注释行 + 加 mac-station 两行注释（pinzhi/print_queue/order_offline_buffer 详情）
  - V4：起点 0fee73b7 在 R2 之前，CLAUDE.md `:172` 仍保留旧 `mac-mini/` 注释行
- 解决：rebase 时手工选 main 版本（删 `mac-mini/` + 加 mac-station 两行），保留 V4 自己对 §三/七/十二/十三 的修订
- 实质改动隔离：V4 §三/七/十二/十三 与 main R2 §五 在不同 section，3-way merge 工具能自动识别，仅需人工确认 §五 段

### PR #228（D6 阻塞依赖）

`rebase/pr-201-clean`（"#201 clean rebase"）当前 `MERGEABLE / CLEAN` 但 base 是 `rebase/pr-195-clean`（rebase chain 第 2 层）。整条 audit p0 链共 14 个 PR 在 in-flight。D6 真机回归 hard 依赖 PR #228 + 链根 PR #227 ship 到 main，预计 2-5 天。

---

## 八、待启动 D 的输入清单（D6 启动前必修）

D6 真机回归之前必须完成：

0. **Build 编译验证（最优先，2026-05-07 全量 review W4）**：sandbox 9 commits 期间无 gradle / kotlinc / npm 验证，必须在 D6 一开始跑：
   - `cd apps/android-pos && ./gradlew assembleDebug`（验证 D2/D3 Kotlin：5 Entity + Migration + ApiClient + ApiBaseUrlResolver + SyncSource + SyncManager 改造无语法错或 import 遗漏）
   - `cd apps/web-pos && pnpm build`（验证 D5b TypeScript：4 cool path 屏 + TXBridge.ts +3 方法 编译过 + 路由解析正确）
   - 在真机 flash APK 之前确认编译可过；任一失败立即 hotfix 不进真机阶段
1. **V4 worktree rebase main**（解锁 ADR 内部链接 + 与最新 main 对齐 + §九 已知 1 处 §五 conflict 手动解决）
2. **PR #228 + audit p0 链 ship 到 main**（边缘 nonce store 防重放在 staging 必须工作）
3. **D4 完成**：cherry-pick shell 的 TXBridge.kt 247 行 + AIDL 文件 + IWoyouService 真接入到 SunmiPrinter / SunmiCashBox（替换 stub）
4. **D3 stage 2 完成**：4 Repository + 5 Screen lockstep 改造为接收 ApiClient（B1 完整修）。代码层面 deferred 清单（防止漏改）：
   - `apps/android-pos/src/main/kotlin/com/tunxiang/pos/data/repository/OrderRepository.kt:22` — TODO 注释
   - `apps/android-pos/src/main/kotlin/com/tunxiang/pos/data/repository/DishRepository.kt` 顶部 — TODO 注释
   - `apps/android-pos/src/main/kotlin/com/tunxiang/pos/data/repository/TableRepository.kt` 顶部 — TODO 注释
   - `apps/android-pos/src/main/kotlin/com/tunxiang/pos/data/repository/SyncRepository.kt` 顶部 — TODO 注释
   - 5 Screen 同步改造：`apps/android-pos/src/main/kotlin/com/tunxiang/pos/ui/screens/{Order,Settle,DailyClose,Shift,TableMap}Screen.kt` 的 `remember {}` 块构造，传 `app.apiClient` 而非 `app.apiClient.txCoreApi`

D7（删 shell + 删 web-pos hot path 副本）依赖 D6 真机通过。

---

## 九、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| V4 worktree 与 main 漂移过大导致 rebase 冲突 | 中 | 中 | 立即 rebase（已知无文件物理冲突）|
| PR #228 ship 节奏慢拖延 D6 | 中 | 高 | 已计入 V4 sprint 9d 节奏，仍有 7 周窗口至 W8 demo |
| D3 stage 2（Repository + Screen lockstep）漏改 | 中 | 高 | Repository 顶部 TODO 注释已加 + ApiClient 错误固化会在第一次 mDNS 切换时显式失败（不是静默 bug）|
| D4 商米 SDK 真接入 AIDL 集成失败 | 低 | 高 | shell 已有 247 行真实装作 reference，cherry-pick 风险可控 |
| W8 demo 5 项门槛任一不达标 | 中 | 致命 | ADR §五 已定义阶段化回滚路径（D6 阴性 → D7 之前回滚）|

---

## 十、PR #240 ship 路径

V4 sprint PR #240 当前 draft 状态。ship 路径：

1. ⏸ Rebase onto origin/main（合 PR #239 + R6 hotfix）
2. ⏸ D4 商米 T2 真机：cherry-pick AIDL + 真接入
3. ⏸ D3 stage 2：Repository + Screen lockstep（依赖 D4 真机环境）
4. ⏸ PR #228 + audit p0 链 ship 到 main
5. ⏸ D6 真机回归通过（5 项 W8 门槛全过）
6. ⏸ D7 删 shell + 删 web-pos hot path 副本
7. ⏸ Convert PR draft → ready for review
8. ⏸ Merge

---

## 十一、一句话

> V4 sprint sandbox 部分（D1/D2/D3/D5/D5b）已 ship 到 PR #240，9 commits 累计 +1603 行净。3 轮独立 review 揪出 8 BLOCKER + 16 WARNING + 3 NIT，全部修复或显式 deferred。**剩 D4/D6/D7 必须在真机 + 远端 PR 链就绪后启动**——sandbox 内的 V4 sprint 工作结束。
