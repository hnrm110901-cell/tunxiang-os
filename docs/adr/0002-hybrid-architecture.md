# ADR 0002 — V4 Hot/Cool Path 混合架构

| 字段 | 值 |
|---|---|
| 状态 | Accepted (2026-05-07) |
| 日期 | 2026-05-07 |
| 决策者 | lichun（创始人） |
| 提议者 | Claude Code（基于 V4 sprint Pre-D1 audit + 第一性原理推导） |
| 关联 PR | #239 sprint-0-dedup（含 V4 sprint plan v2）/ #240 V4 sprint draft |
| 关联文档 | [v4-pre-d1-audit.md](../architecture/v4-pre-d1-audit.md) / [v4-d1-hot-cool-path-boundary.md](../architecture/v4-d1-hot-cool-path-boundary.md) / [.omc/plans/v4-architecture-alignment.md](../../.omc/plans/v4-architecture-alignment.md) |
| 替代 | CLAUDE.md V3 §三 "一套 React Web App，多端运行" + V3 §十三 第 1 条 "禁止在 Kotlin/Swift 层写业务逻辑" |

---

## 一、背景与问题

### 1.1 触发事件

V4 sprint Pre-D1 audit（2026-05-07）发现 `apps/android-pos`（V4 候选实装）和 `apps/android-shell`（V3 实装）**各持半套真理**：

- shell：WebView only + 真实 Sunmi SDK 接入（AIDL + ServiceConnection 真绑）+ getMacMiniUrl 符合路线 C，**但**收银 hot path 在商米 T2 物理性能边界以内不够稳
- pos：5 屏 Compose Native 业务实装（~2046 LOC）+ 性能 60fps，**但** Room DB 替代 Mac mini PG（违路线 C）+ Sunmi SDK 是骨架 stub（SunmiPrinter 309 LOC 注释自承未接 SDK）

**V3 CLAUDE.md §三 + §十三 第 1 条铁律假设"一套 React 跨端"**——但这与天财商龙存量客户群体（屯象 24 个月最大迁移目标）的物理需求不符：

| 维度 | 阈值 | 谁卡谁出局 |
|---|---|---|
| 单次按键响应 | < 50ms（收银员肌肉记忆边界）| 80ms 抱怨，150ms 换系统 |
| 桌台/订单切换 | < 100ms | 高峰期 200 桌反复切，慢 100ms × 千次 = 整晚崩 |
| 称重→显示 | < 200ms | 客户在等 |
| 打印小票首字 | < 500ms | 客户付完款拿小票走人 |
| 断网 4h | 数据零丢失 + 持续出单 + 打印不卡 | Tier 1 已写明 |
| 高峰期内存 | < 4GB（商米 T2 仅 4GB RAM）| OOM = 收银台冻死 |

商米 T2 的 React WebView（老 Chromium 70-90 + 4GB RAM + RK3399）在 200 桌并发 + 大菜单 1000+ 道菜 + WebSocket 高频更新下**无法稳定满足这组阈值**。

### 1.2 替换 23 套系统的真实门槛

徐记海鲜（W8 demo 标杆）+ 天财商龙存量客户都已经在用 Native POS。他们不肯换的根本原因是**收银台不能卡**——而不是缺 AI、缺云原生、缺开放平台。

如果屯象 demo 一上去收银员说"卡"，"AI-Native"卖点也救不回来——因为 POS 的第一性是**速度和稳定**。

---

## 二、决策

### 2.1 核心决策

**采用 Hot Path + Cool Path 混合架构**，按"高频按键 + 资金安全 = Native，高频迭代 + 多端一致 = WebView" 的二元划分：

```
android-pos (Compose 主进程)
├── Hot Path  (Native Compose, 性能锁 < 50ms)
│   ├── 5 屏：OrderScreen / TableMapScreen / SettleScreen / ShiftScreen / DailyCloseScreen
│   ├── 13 项资金灰色地带（D1 sign-off G1-G8/G10/G15/G16/G18/G19）
│   └── 直调 Sunmi SDK
└── Cool Path (WebViewScreen + React)
    ├── 9 类 + 7 项灰色地带（D1 sign-off G9/G11-G14/G17/G20）
    └── 通过 TXBridge 调外设
        ↓
Mac mini (mac-station) 单一真相源
└── Room 仅作 4h 断网缓冲（带 expires_at + source 字段）
```

### 2.2 边界定性

20 项灰色地带由创始人 sign-off（D1，2026-05-07，G1-G20 全同意 Claude 建议）：

- **Hot path（13 项）**：退款 / 修改/作废订单 / 储值卡充值 / 储值卡消费 / 优惠券核销 / 礼品卡 / 押金 / 存酒 / 宴会当天结算 / 小费 / 打印补打 / 外卖单接单/推单/改单 / 全电发票申请
- **Cool path（7 项）**：宴会订单提前创建 / 桌台预订 / 排队叫号 / 会员卡查询/绑定 / 菜品 86沽清 / 设备维护 / 全电发票管理

详见 [v4-d1-hot-cool-path-boundary.md](../architecture/v4-d1-hot-cool-path-boundary.md) §四。

### 2.3 Mac mini 真相源（路线 C 强化）

- **android-pos 通过 mac-station HTTP 读写**，不直连云端
- **Room 仅作 4h 断网缓冲**：`expires_at`（TTL）+ `source`（"remote" / "local-pending" / "local-synced"）
- mac-station 内部 sync-engine 向云端 PG 同步（300 秒/轮）
- iPad 不承担 hot path；iPad 通过 HTTP 转发到安卓 POS 主机执行外设指令

---

## 三、决策依据（第一性原理推导）

### 3.1 hot/cool path 是物理需求决定的

收银员每天 8h 操作 → 按键响应 < 50ms 是肌肉记忆边界 → Native 渲染 60fps 稳定能达到，WebView 在中低端硬件上不能 → **hot path 必须 Native**。

菜单 / 营销 / AI 决策弹窗 → 高频迭代（每周改 +20 道菜，每日改价）→ APK 重打 1-2 周不能接受 → **cool path 必须 WebView**。

iPad 高端店调性 → 一套 React 跨端 → **iPad 走 cool path**。

### 3.2 Palantir 自己也是混合架构

| Palantir 产品 | 技术栈 | 为什么 |
|---|---|---|
| Foundry | Web (TypeScript + React) | 数据分析师是 cool path |
| Apollo | Native desktop + Web 混合 | 部署运维是 hot path |
| Gotham | Native + Web 混合 | 情报分析师 hot + cool 混合 |

Palantir 的 Ontology 思想 = "**按业务语义建模而非按技术栈划界**"。屯象学 Palantir 不是学"Web first"，是学**按 hot/cool path 把技术栈对齐到业务现实**。

### 3.3 Mac mini 真相源 = 数据正确性的根

V3 pos 实装把 Room 当真相源 + 直连云端：在断网 4h 演练时 Room 与云端 PG 的状态如何 reconcile？V3 没定义。Tier 1 测试 `test_offline_4h_crdt_no_data_loss` 在这个架构下无法通过。

V4 修正：mac-station PG 是**单一**真相源，Room 仅做 4h 缓冲。CRDT 冲突解析策略明确（云端为主 → mac-station 为主 → Room 仅在 mac-station 不可达时供应数据，且只读非过期数据）。

---

## 四、后果

### 4.1 正面

- **替换 23 套系统的物理门槛达标**：5 屏 Native 性能可与天财商龙打平
- **AI-Native 卖点真正落地**：cool path 的 Agent 决策弹窗 / 营销活动 OTA 即生效，比天财领先 1-2 个数量级
- **iPad 用例打开**：高端品牌（如徐记海鲜）的 iPad 调性需求技术上可行
- **数据真相源单一**：断网 4h 演练 0 数据丢失从架构层保证，不靠业务代码补漏

### 4.2 负面

- **android-pos / android-shell / web-pos 三方需要重构**：~9 工程日（V4 sprint plan v2 / 7d → 9d 含 D5b 4 缺口屏）
- **双轨债**：web-pos 现有 hot path 5 屏 React 副本必须 D7 删除（避免长期维护两套）
- **Sunmi SDK 真接入工作量**：android-pos 当前 SunmiPrinter / SunmiCashBox 是骨架 stub，D4 必须 cherry-pick shell 的 AIDL + ServiceConnection 真绑（~270 LOC）
- **CLAUDE.md V3 教条要废止**：§三 "一套 React 跨端" + §十三 第 1 条 "禁止 Kotlin 写业务" 都改

### 4.3 中性

- React 不被废弃，只是不再承担 hot path——cool path React 仍是主力
- 530K Python + 232K TypeScript 现有资产保留
- 多端复用从"一套代码"降级为"hot path 各端 native + cool path 跨端"，更工程化

---

## 五、回滚条件

如出现以下任一情况，回退到 V3 WebView only：

- W12 真机回归（D6）显示 Native 性能在商米 T2 上**没有**显著优于 WebView（< 30% P99 改善）
- Compose 维护成本经评估超过节省的迭代时间（如徐记部署 1 个月内 hot path 改 > 3 次）
- 创始人发现 hot/cool 边界在实际运营中模糊不清（业务持续要求"this should be hot but also cool"）

回滚成本：删除 android-pos 5 屏 Compose（~2046 LOC + Repository 改造），改回 web-pos React 渲染。

---

## 六、不在本 ADR 范围

- **post-W12 tx-agent 子模块合并**（sprint-0-dedup R4 立项，独立 plan：`.omc/plans/post-w12-tx-agent-merger.md`）
- **mDNS 局域网发现实装细节**（V4 sprint D4 主战场，独立技术决策）
- **CRDT 冲突解析具体算法**（CLAUDE.md §十七 Tier 1 + edge/sync-engine 实装层面）
- **iPad / Windows POS shell 命运**（windows-pos-shell 非本 sprint 范围，留待 post-W12 决策）

---

## 七、参考

- CLAUDE.md V4 修订版 §三 / §七 / §十二 / §十三（同 commit 落库）
- V4 sprint plan：`.omc/plans/v4-architecture-alignment.md`（sprint-0-dedup PR #239 含）
- D1 audit：`docs/architecture/v4-pre-d1-audit.md`
- D1 边界 sign-off：`docs/architecture/v4-d1-hot-cool-path-boundary.md`
- sprint-0-dedup R3 升级原因：`.omc/plans/sprint-0-dedup.md` §R3
