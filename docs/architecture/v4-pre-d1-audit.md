# V4 架构对齐 Sprint · Pre-D1 资产 Audit

| 字段 | 值 |
|---|---|
| 文档类型 | Architecture audit report |
| 日期 | 2026-05-07 |
| 作者 | Claude Code（基于只读盘点） |
| Sprint plan 来源 | `.omc/plans/v4-architecture-alignment.md`（sprint-0-dedup PR #239 含）|
| 阶段 | V4 sprint D1 输出（hard gate）|
| 状态 | 报告完成 / 待创始人对照 [`v4-d1-hot-cool-path-boundary.md`](v4-d1-hot-cool-path-boundary.md) sign-off |

---

## 一、目的

在 V4 sprint 正式启动 D2 之前，对 `apps/android-pos`、`apps/android-shell`、`apps/web-pos` 做只读盘点，回答 4 个问题：

1. android-pos 的 5 个 Compose hot path 屏完成度如何？
2. android-pos 的 4 个 Sunmi SDK 桥接类是真实装还是 stub？
3. android-shell 有哪些资产是 V4 sprint D4 必须 cherry-pick 的？
4. web-pos 的 cool path 完成度 + 是否存在 hot path 双轨？

---

## 二、android-pos Hot Path 完成度

| 屏 | 行数 | @Composable | 外部调用 (Repo/api/db) | 业务实装 |
|---|---:|---:|---:|---|
| OrderScreen | 406 | 3 | 10 | ✅ 充实 |
| TableMapScreen | 316 | 2 | 6 | ✅ |
| SettleScreen | 462 | 4 | 6 | ✅ |
| ShiftScreen | 428 | 4 | 4 | ✅ |
| DailyCloseScreen | 434 | 3 | 5 | ✅ |
| WebViewScreen（fallback）| 140 | 1 | 0 | ⚠️ 占位，需增强 |

**结论**：5 屏 Compose 业务**已充实**（共 ~2046 行，每屏 3-4 个 @Composable）。但调用方仍走 Room + 云端（违反 CLAUDE.md §八 路线 C），待 D2/D3 改造为 Mac mini PG 真相源。

WebViewScreen 仅 140 行 / 1 个 @Composable / 0 外部调用 — 是占位级 fallback，**需在 D4 增强为真正能加载 cool path React URL + 注入 TXBridge 的容器**。

---

## 三、android-pos Sunmi SDK 接入（关键缺口）

| 类 | 行数 | `import com.sunmi.*` | TODO/stub 标记 | 实装状态 |
|---|---:|---:|---:|---|
| **SunmiPrinter** | 309 | **0** | 0 | 🔴 注释自承 `// In production, this would be IWoyouService`，**未接 SDK** |
| **SunmiCashBox** | 68 | **0** | 0 | 🔴 主路径未接 SDK，`open()` 走 ESC/POS fallback `sendRawBytes(OPEN_COMMAND)` |
| SunmiScanner | 132 | 2 | 0 | 🟢 真接 SDK |
| SunmiScale | 110 | 2 | 0 | 🟢 真接 SDK |

**关键证据**

`apps/android-pos/src/main/kotlin/com/tunxiang/pos/bridge/SunmiPrinter.kt`：

```kotlin
companion object {
    private const val SUNMI_SERVICE_PACKAGE = "woyou.aidlservice.jiuiv5"
    private const val SUNMI_SERVICE_CLASS = "woyou.aidlservice.jiuiv5.IWoyouService"
}

// In production, this would be woyou.aidlservice.jiuiv5.IWoyouService
private var printerService: Any? = null
```

`apps/android-pos/src/main/kotlin/com/tunxiang/pos/bridge/SunmiCashBox.kt:open()`：

```kotlin
// Via Sunmi printer SDK:
// IWoyouService.sendRAWData(OPEN_COMMAND, null)
// ...
Log.i(TAG, "Cash drawer opened")
sendRawBytes(OPEN_COMMAND)   // fallback path, not main
```

**结论**：打印 + 钱箱 = 骨架 stub，扫码 + 称重 = 真实装。**D4 必须把 shell 的 IWoyouService 真接入（含 AIDL 文件）迁过来**——否则徐记演练时打印失败 / 钱箱不弹。

---

## 四、android-shell 抢救清单（V3 真货，V4 sprint D4 cherry-pick 来源）

| 资产 | 路径 | 行数 | 内容摘要 |
|---|---|---:|---|
| TXBridge.kt | `apps/android-shell/app/src/main/java/com/tunxiang/pos/TXBridge.kt` | 247 | ServiceConnection（绑 com.sunmi.printerservice）+ BroadcastReceiver（监听硬件事件）+ 11 个 @JavascriptInterface（print / printText / openCashBox / startScale / onScaleData / scan / onScanResult / getDeviceInfo / getMacMiniUrl / reportHeartbeat / stopScale）+ Sunmi 服务真绑 |
| MainActivity.kt | `apps/android-shell/app/src/main/java/com/tunxiang/pos/MainActivity.kt` | 100 | WebView 全屏 immersive + Bridge 注入 + Sunmi 服务生命周期（onCreate bind / onDestroy unbind）+ 处理返回键 |
| **AIDL 文件 ⭐** | `apps/android-shell/app/src/main/aidl/woyou/aidlservice/jiuiv5/IWoyouService.aidl` | 13 | Sunmi 打印服务 AIDL 接口（**pos 没有此文件，是接入 SDK 的关键**）|
| **AIDL 文件 ⭐** | `apps/android-shell/app/src/main/aidl/woyou/aidlservice/jiuiv5/ICallback.aidl` | 9 | Sunmi 服务回调 AIDL |
| AndroidManifest.xml | — | — | 商米 Service 声明 + 必要权限 |
| themes.xml | — | — | 全屏 immersive 主题 |

**Cherry-pick 操作**：D4 把这 6 个文件迁到 `apps/android-pos/`，并把 SunmiPrinter / SunmiCashBox 改造为真调 `IWoyouService.sendRAWData(...)`。

---

## 五、OTA v094 已在 main 分支 ✅

OTA v094（commit `d54f05b4`，2026-04-01）实装分布在 3 个位置（558 行总计）：

| 位置 | 行数 | 用途 |
|---|---:|---|
| `shared/db-migrations/versions/v094_ota_management.py` | 112 | `app_versions`（含灰度 rollout_pct + 租户专属 + 全局版本）+ `ota_check_logs` |
| `services/tx-org/src/api/ota_routes.py` | 295 | 云端 5 端点：发布 / 列表 / 最新版查询 / 撤回 / 升级进度统计 |
| `edge/mac-station/src/ota_routes.py` | 151 | 边缘检查端点（1h 本地缓存，云端不可达时使用旧缓存）|

**结论**：OTA 后端已就绪。本 sprint 不再需要单独 D-OTA 步骤。pos 客户端只需在 D4 cherry-pick TXBridge 的 OTA 检查调用代码（来自 shell 的 reportHeartbeat / OTA URL 触发）。

---

## 六、web-pos React Cool Path 完成度

✅ **已有屏类**：

| 类 | 文件数 |
|---|---:|
| menu / dish | 4 + 2 |
| coupon | 3 |
| dashboard | 1 |
| report | 5 |
| training | 5 |
| agent / decision | 3 + 1 |

🔴 **缺口（V4 sprint D5b 内补，+2d）**：

| 类 | 文件数 |
|---|---:|
| marketing | **0** |
| campaign | **0** |
| food_safety | **0** |
| cross-brand | **0** |

⚠️ **薄弱（单文件，需评估扩展性）**：

| 类 | 文件数 |
|---|---:|
| sop | 1 |
| setting | 1 |

---

## 七、双轨债 — web-pos 的 hot path 副本

`apps/web-pos` 同时存在 hot path 5 屏的 React 实装（违反 V4 sprint hot/cool 边界，**D7 直接删**）：

| Hot Path 屏 | React (web-pos) 副本 | Native (android-pos) 真身 |
|---|---:|---|
| Cashier / Order | 2 + 10 文件（CashierPage / OrderPage / OrderHistoryPage / OrderActionPanel ...）| ✅ OrderScreen |
| Table | 2 文件（OpenTablePage / FloorMapPage）| ✅ TableMapScreen |
| Handover | 2 文件（HandoverPage 等）| ✅ ShiftScreen |
| Settlement | 3+ 文件（DepositPosPage / DiscountAuditPage 等）| ✅ SettleScreen |
| DailySettlement | 1 文件（DailySettlementPage）| ✅ DailyCloseScreen |

**D7 删除清单**（具体路径见 V4 sprint plan 附录 C）。

---

## 八、Audit 结论与对 V4 Sprint Plan 的修订（已 land 到 plan v2）

| 修订项 | 影响 |
|---|---|
| OTA v094 后端已落 main | -0.5d（取消 D-OTA 步骤）|
| D4 范围扩大到 AIDL 文件 + Sunmi SDK 真接入 | +0.5d |
| 新增 D5b（补 4 个 cool path 缺口屏）| +2d |
| **总工时** | **7d → 9d** |

V4 sprint plan v2 已落 sprint-0-dedup PR #239（commit `380c610f`，附录 A/B/C）。

---

## 九、后续依赖

D2 启动条件：
- [ ] 创始人对 [`v4-d1-hot-cool-path-boundary.md`](v4-d1-hot-cool-path-boundary.md) sign-off（含 20 个灰色地带定性）
- [ ] PR #228（rebase/pr-201-clean）状态确认（V4 sprint D6 真机回归 hard 依赖该 PR ship）

D6 启动条件：
- [ ] PR #228 + 整个 audit p0 链（PR #195 / #196 / #199 / #200 / #207 / #208 / #210 等 14 PR）必要项 ship 到 main
- [ ] 商米 T2 真机 + Mac mini M4 真机环境就绪
