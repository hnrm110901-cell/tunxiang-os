# 门店端架构：硬件兼容 · 稳定交付 · AI 智能体

> **定位**：屯象 OS 在**门店现场**的落地架构（L4 + L0 与边缘协同），与 `CLAUDE.md`「务实混合架构」一致并扩展 **Windows 收银**与**统一外设抽象**。  
> **目标**：兼容市面常见硬件形态；收银/KDS/移动流程**可生产级交付**；AI 智能体**可观测、可降级、不阻断交易**。  
> **修订**：2026-04-02

---

## 1. 架构总览

```
                         ┌──────────────────┐
                         │   腾讯云 API      │  报表 / 集团 / 重推理（Claude 等）
                         └────────┬─────────┘
                                  │ HTTPS / Tailscale
                         ┌────────▼─────────┐
                         │  Mac mini M4     │  本地 PG 副本 · sync-engine · 轻量 Agent
                         │  门店边缘         │  Core ML HTTP :8100
                         └────────┬─────────┘
                                  │ 局域网 Wi-Fi
    ┌─────────────────────────────┼─────────────────────────────┐
    │                             │                             │
┌───▼────┐                 ┌──────▼──────┐               ┌──────▼──────┐
│ Windows │                 │ Android 壳   │               │ iOS / 纯浏览器 │
│ 收银壳   │                 │ WebView       │               │ Safari / PWA   │
│ WebView2 │                 │ + TXBridge    │               │ 无 USB 外设    │
│ + 打印等 │                 │ + 商米 SDK    │               │ 打印→打印主机   │
└───┬────┘                 └──────┬──────┘               └──────┬──────┘
    │                             │                             │
    └─────────────────────────────┼─────────────────────────────┘
                                  ▼
              ┌───────────────────────────────────────┐
              │  同一套 React Web App（业务 UI 单栈）    │
              │  web-pos / web-kds / web-crew / …       │
              └───────────────────────────────────────┘
```

**三条铁律**

1. **业务逻辑**在 **Python（服务）+ TypeScript（前端）**；**壳层**（Kotlin / Swift / .NET 等）**只做外设桥接**，不写业务规则。  
2. **交易硬约束**（毛利底线、食安、客户体验）在**确定性服务**中执行，**不依赖 LLM**。  
3. **外设**通过统一抽象 **`window.TXBridge` 语义** 暴露给 Web；无桥环境（iOS、部分浏览器）**降级为 HTTP 调用「打印主机」**。

---

## 2. 终端与产品映射

| 终端形态 | 推荐壳/运行时 | 主要 Web 应用 | 外设策略 |
|----------|----------------|---------------|----------|
| 安卓 POS（商米 T2/V2 等） | `apps/android-pos` / `android-shell` + WebView | `web-pos` | TXBridge → 打印/秤/钱箱/扫码 |
| Windows 收银 PC | **轻壳**（WebView2 或 Electron，见 §5） | `web-pos` | 实现同名 TXBridge 能力或本地打印代理 |
| 安卓区域触摸屏 / KDS 平板 | WebView 壳或 Chrome Kiosk | `web-pos`（大屏路由）/ `web-kds` | 可选 TXBridge；打印建议走打印主机 |
| 员工 Android / iOS 手机 | Chrome / Safari PWA | `web-crew` | **不直连小票机**；`POST 打印主机/api/print` |
| TV 菜单屏 | 浏览器 | `web-tv-menu` | 无外设 |
| 前台接待大屏/PC | 浏览器 | `web-reception` | 按需 |

**打印主机（强烈建议）**：每个门店指定 **唯一** 设备（Windows 收银机或固定安卓 POS）接收局域网打印请求，避免多终端重复出票、串单。

---

## 3. 稳定交付：数据流与身份

### 3.1 写入与离线

- **目标路径**：POS / 移动 **优先写 Mac mini 本地 API** → 本地 PostgreSQL → `sync-engine` 增量上云（与 `edge/sync-engine` 设计一致）。  
- **断公网**：门店局域网内 **仍可开单、出厨打**（依赖本地服务可用）；恢复后同步，**冲突策略以产品文档为准**（默认云端为主时需可对账）。  
- **身份**：全端统一 **Gateway JWT** + **`X-Tenant-ID`**；登录成功后前端持久化 **`tx_tenant_id`**，与 POS 回填、Hub 演示账号等 **禁止多套 UUID 映射并存**（单一事实源：`tenants` + 令牌声明）。

### 3.2 外设可靠

- 打印：**超时、重试、补打**；壳与静态资源 **版本锁 + 灰度**（与 `infra` / DNS gray 环境配合）。  
- **iPad / iPhone**：遵循 `CLAUDE.md` — 外设指令经 WiFi 至打印主机，**不**要求 iOS 直连 USB 打印机。

---

## 4. AI 智能体分层（门店可感知）

| 层级 | 运行位置 | 职责 | 失败时行为 |
|------|----------|------|------------|
| **L0 硬规则** | `tx-trade` 等微服务 | 毛利/食安/体验校验 | **必须拦截违法操作** |
| **L1 边缘轻量** | Mac mini · Core ML HTTP | 出餐预测、简单风险评分等 | **跳过建议**，不挡结账 |
| **L2 云端 Agent** | `tx-agent` / `tx-brain` | 排菜建议、摘要、客服类能力 | **异步**；**决策留痕**（`AgentDecisionLog`） |
| **L3 终端呈现** | Web 内面板 / 卡片 | 展示建议 → **人工确认** 后再调 API | 无确认不改单 |

**原则**：智能体输出为 **建议或辅助操作**；改价、免单、跨约束操作 **必须经过 L0**。

---

## 5. 工程落地清单（与仓库对应）

| 模块 | 路径/说明 |
|------|-----------|
| Web POS / KDS / 服务员 | `apps/web-pos`, `web-kds`, `web-crew` |
| 安卓壳与 TXBridge | `apps/android-pos`, `android-shell`, `apps/android-shell` |
| Windows 壳 | **规划**：`apps/windows-pos-shell/`（或等价仓库目录），见 `docs/development-plan-mixed-terminals-claude-2026Q2.md` |
| 边缘 | `edge/mac-station`, `edge/sync-engine`, `edge/coreml-bridge` |
| 网关与 Agent | `services/gateway`, `services/tx-agent`, `services/tx-brain` |
| 外设抽象（前端） | 各 App 内统一封装：`TXBridge` 存在则直连，否则 **HTTP 打印主机** |

---

## 6. 与全栈文档的关系

| 文档 | 关系 |
|------|------|
| `CLAUDE.md` | 项目宪法；硬件分工、TXBridge、Mac mini 边界 |
| `README.md` | 自述中的「门店端架构」摘要链到本文 |
| `docs/development-plan-mixed-terminals-claude-2026Q2.md` | 混合终端分阶段开发计划 |
| `docs/domain-architecture-v3.md` | 域名与 Hub/OS 划分 |

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-02 | 初版：硬件兼容 + 稳定交付 + AI 分层定稿入库 |
