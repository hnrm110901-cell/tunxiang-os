# 屯象OS — 混合终端架构梳理与 Claude 开发计划（2026 Q2）

> **场景假设**  
> - 门店收银：**Windows**（键鼠 + 可能直连打印机/钱箱）  
> - 区域触摸屏：**Android**（大屏点菜/展示）  
> - 移动终端：**Android + iOS**（服务员点餐、移动查询）  
>
> **文档用途**：供 `CLAUDE.md` 约束下的 Claude Code **分阶段落地**；与现有「Web App + 安卓 TXBridge + Mac mini 边缘」主线对齐，并显式补齐 **Windows 外设与多终端协同** 缺口。

---

## 一、目标架构（混合硬件版）

### 1.1 分层（不变更 L0–L4 叙事，仅补充终端映射）

```
L4 终端层（本计划范围）
├── Windows 收银    → Web POS（浏览器或轻壳）+ Windows 外设适配层（新增）
├── Android 区域屏  → Web POS / 自助点餐 H5 或专用路由 + TXBridge（可选）
├── Android 移动    → web-crew PWA / 浏览器 + 无 TXBridge（外设走主机）
├── iOS 移动        → Safari / WKWebView 壳 + 外设 HTTP → Windows 或 Android 收银主机
└── KDS / TV        → 现有 web-kds / web-tv-menu（多为 Android 平板/TV 浏览器）

L3 Agent OS         → 云端 + Mac mini 边缘（不变）

L2 业务中台         → Gateway + 各 tx-* 微服务（不变）

L1 Ontology + RLS   → PostgreSQL（不变）

L0 设备适配（扩展）
├── Android：TXBridge（Kotlin）— 现有规范
├── Windows：TXBridgeWin 或「打印代理服务」（新增）— 仅桥接，禁止写业务逻辑
└── iOS：无直连外设，统一 HTTP 到「打印主机」
```

### 1.2 关键架构决策（本场景下必须写清）

| 决策 | 建议 | 说明 |
|------|------|------|
| **业务 UI** | 仍以 **React Web** 为主 | 与现 `apps/web-pos`、`web-crew` 等一致，降低多端重复开发 |
| **打印/钱箱权威设备** | **指定单类「打印主机」**（建议 Windows 收银或固定安卓 POS） | 避免多终端重复出票、串单；其它终端只发「打印意图」 |
| **外设 API 抽象** | 统一 **`window.TXBridge` 语义**；Windows/iOS 用 **适配实现** | TypeScript 侧单一调用面；实现可 per-platform |
| **离线/弱网** | 交易写 **Mac mini 本地 API** → 同步引擎上云（与 CLAUDE 一致） | 移动终端需能解析 `getMacMiniUrl()` 或固定门店局域网入口 |
| **身份** | Gateway JWT + `X-Tenant-ID`；登录回写 `tx_tenant_id` | 多终端会话一致，禁止多映射表 |

### 1.3 与现有仓库映射

| 能力 | 仓库/路径 | 混合终端下的角色 |
|------|-----------|------------------|
| 总部/经营 OS | `apps/web-admin` | 不变 |
| 收银 Web | `apps/web-pos` | Windows / Android 共用；需 **响应式 + 打印抽象扩展** |
| 服务员 | `apps/web-crew` | Android / iOS 浏览器为主 |
| KDS | `apps/web-kds` | 区域后厨屏，常 Android |
| 接待 | `apps/web-reception` | 可选独立大屏或 PC |
| 顾客端 | `miniapp-customer` / H5 | 不变 |
| 安卓壳 | `apps/android-shell`、`apps/android-pos` | 区域屏/移动安卓可选 |
| **Windows 壳** | **待建** `apps/windows-pos-shell/` 或 `edge/print-proxy/` | **本计划 P0/P1** |
| 网关 | `services/gateway` | 统一入口、租户、限流 |
| 边缘 | `edge/mac-station`、`edge/sync-engine` | 离线写、同步 |
| 外设语义 | `CLAUDE.md` §七 TXBridge | 扩展为跨平台接口说明 + TS 类型 |

---

## 二、产品明细（按终端）

### 2.1 Windows 收银台

| 产品能力 | 现状 | 目标 |
|----------|------|------|
| 点餐/结账/桌台 | web-pos 已有 | 全功能 + 键盘快捷键 |
| 小票/厨房单 | 依赖 TXBridge 或 HTTP | **Windows 本地打印驱动/SDK 桥接** 或 **本机打印代理** |
| 钱箱/扫码枪 | 同左 | USB 设备走 Windows 服务 |
| 离线 | 文档指向 Mac mini | Windows 浏览器 **优先连门店 Mac mini URL**；断公网仍可收银 |

### 2.2 Android 区域触摸屏

| 产品能力 | 现状 | 目标 |
|----------|------|------|
| 点菜/加购 | web-pos 或 h5-self-order | 大屏布局、少键盘 |
| 打印 | TXBridge 或仅下单不打印 | 默认 **不下发厨房单** 或 **统一到打印主机** |
| 登录 | 店员账号 | 强会话超时、防误触 |

### 2.3 Android / iOS 移动终端

| 产品能力 | 现状 | 目标 |
|----------|------|------|
| 移动点餐 | web-crew | 触控优化、弱网重试 |
| 打印 | 无桥 | **仅** `fetch(打印主机/api/print)` 与 CLAUDE iPad 条款一致 |
| 推送 | 可选 Web Push / 企微 | 非 P0 |

### 2.4 横切

- **单桌并发**：服务端订单锁/版本号；前端冲突提示。  
- **设备基线表**：文档化「Windows 版本、浏览器版本、安卓机型、iOS 最低版本」。  
- **Hub 运维**：后续可扩展「终端心跳、App 版本」（与 `hub_api` 演进一致）。

---

## 三、Claude 开发计划（分阶段）

> **执行原则**（摘自项目宪法，开发中强制自检）  
> - 业务逻辑在 **Python / TypeScript**；Kotlin/Swift **仅桥接**  
> - 全 API 带租户；新表 **tenant_id + RLS**  
> - 禁止无 root cause 的 broad except；P0 路径补测试  
> - 每个可发布阶段更新 `DEVLOG.md`

### Phase 0 — 规格冻结（3–5 人日，以文档与接口为主）

**产出**

- [ ] 本文档评审定稿；补充 **「打印主机」** 网络拓扑一页图（谁监听 `/api/print`）  
- [ ] `docs/device-matrix-mixed-terminals.md`（新建）：浏览器/WebView 版本、分辨率、外设型号列表示例  
- [ ] TypeScript：`TXBridge` 接口扩展为 **可选能力探测**（`supportsPrint`、`supportsCashBox`），缺省走 HTTP 打印主机  

**验收**

- 架构师/产品签字：**唯一打印主机策略**、**移动终端不直连 USB 打印机**

---

### Phase 1 — 身份与多终端一致（P0，约 1 周）

**范围**：`services/gateway`、`apps/web-admin`、`apps/web-pos`、`apps/web-crew`

**任务**

- [ ] 登录响应统一携带 `tenant_id`（及可选 `store_id` 默认）；前端 **登录成功写入 `localStorage.tx_tenant_id`**（web-admin / web-pos / web-crew 对齐）  
- [ ] 对齐 **POS 同步租户 UUID** 与 **JWT 租户**（消除硬编码双表，单一事实源）  
- [ ] web-pos：检测 **Windows vs Android vs iOS**（User-Agent + 可选 query `?shell=windows`），打印路径分支 **TXBridge / HTTP / 未配置提示**  

**测试**

- [ ] 三端 User-Agent 下 smoke：带 `X-Tenant-ID` 的同一订单查询一致  

**验收**

- 同一账号在 Windows 与手机看到 **同一租户** 数据；无默认错租户 UUID  

---

### Phase 2 — Windows 外设最小闭环（P0，约 2–3 周）

**范围**：新建 **`apps/windows-pos-shell/`**（建议技术栈：**.NET 8 + WebView2** 或 **Electron + 本地 Node 打印模块** — 选型在 Phase 0 末尾定）

**任务**

- [ ] 壳加载 **web-pos 同源 URL**（可配置）  
- [ ] 注入 **`window.TXBridge`**：`print(raw: string)`、`openCashBox()` **映射到 Windows 打印队列 / 钱箱指令**（具体驱动按商米/芯烨等选型二选一，先做 **RAW/ESC-POS 串口或驱动名**）  
- [ ] 可选：本机 **HTTP `:8765/print`** 供 iOS 同一局域网调用（与 CLAUDE「HTTP 转发到 POS 主机」一致，Windows 即主机）  
- [ ] 文档：`docs/windows-pos-shell.md` — 安装、证书、防火墙端口  

**测试**

- [ ] Windows 上连续 100 次打印压测（失败重试策略）  
- [ ] iOS Safari 调用 Windows 打印代理 **端到端 1 条用例**（可手工 + 自动化 stub）  

**验收**

- Windows 收银在无安卓设备情况下 **可独立完成结账+小票+开钱箱**（在选定打印机型号上）  

---

### Phase 3 — Android 区域屏与 web-pos 大屏模式（P1，约 1–2 周）

**范围**：`apps/web-pos`、`apps/android-shell`（可选）

**任务**

- [ ] web-pos **布局断点**：`≥1280` 大屏简化导航、大按钮、可选「仅点菜模式」路由 `/pos/tablet`  
- [ ] 区域屏 **默认角色**：无退款/无整单折扣（由 `menu_config` 或角色 JWT claim 控制）  
- [ ] 若用壳：复用 TXBridge；若纯 Chrome：仅 HTTP 打印到 Phase 2 主机  

**验收**

- 10 寸以上安卓设备 **无横向滚动关键路径**；误触率可接受（可用内测问卷）  

---

### Phase 4 — web-crew 移动双端打磨（P1，约 1 周）

**范围**：`apps/web-crew`

**任务**

- [ ] iOS Safari：**安全区、固定视口、防止橡皮筋滚动**  
- [ ] 打印/取 Mac mini URL：**与 web-pos 共用工具函数**（抽到 `shared` 或 monorepo package）  
- [ ] 离线提示：无法连接 Mac mini / 网关时的 **明确文案与重试**  

**验收**

- iPhone + Android 各 2 款真机 **核心下单流** 通过  

---

### Phase 5 — 可观测与发布（P1，持续）

**范围**：`services/gateway`、各前端构建流水线

**任务**

- [ ] 关键路径 **trace_id**：下单、支付、打印 串联  
- [ ] 前端 **Source Map** 与版本号 **写入 `window.__TX_BUILD__`**，Hub 可后续采集  
- [ ] 生产构建 **关闭静默 mock** 或 **显式「演示数据」横幅**（web-admin 已部分存在，收口规则）  

**验收**

- 一次完整客诉可从日志 **5 分钟内定位** 到租户/门店/设备类型  

---

### Phase 6 — Flutter（若战略确定为 Flutter 多端）（P2，另立里程碑）

> 若产品最终改为 **Flutter 统一壳**：本计划 Phase 2–4 **替换为**「Flutter 单仓 + Platform Channel 外设」；**后端与 Mac mini 不变**。建议在 Phase 0 结束做 **Go/No-Go**，避免与 Web 双线并行过久。

---

## 四、风险与依赖

| 风险 | 缓解 |
|------|------|
| Windows 打印驱动碎片化 | 先做 **2 款打印机认证清单**，其余「兼容模式」不承诺 |
| 局域网 IP 变化 | 打印主机 **mDNS 名称** 或 Mac mini 下发 **门店设备表** |
| iOS 混合内容/证书 | 全 HTTPS 或内网证书安装 SOP |
| 与现有商米安卓 POS 客户并存 | **设备矩阵分 SKU**：安卓标准店 / Windows 店 / 混合店 |

---

## 五、Claude 会话使用方式（建议）

1. 新开任务时 **附本文路径** + 当前 Phase 编号。  
2. 每次合并前：**pytest / 前端 lint / 相关 e2e**。  
3. **DEVLOG** 按日追加：完成项、迁移版本、新增 API、新增测试数。  
4. 单 PR **只做一个 Phase 子项**，避免 Windows 壳与租户重构混编。

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-02 | 初版：混合终端假设 + 架构/产品/分阶段计划 |
