# CLAUDE.md — 屯象OS 项目宪法 V3.0（务实混合架构）

> 本文件是 Claude Code 的开发行为准则。所有代码生成、架构决策、重构操作必须遵守本文件。

---

## 一、项目身份

**屯象OS** 是 AI-Native 连锁餐饮经营操作系统。定位"连锁餐饮行业的 Palantir"。
用一套智能系统**替换**连锁餐饮企业现有所有业务系统，而非在现有系统上加 AI 层。

- 公司：屯象科技（湖南省长沙市）
- 创始人：未了已
- 首批客户：尝在一起（品智POS）、最黔线、尚宫厨
- 标杆案例设计：基于徐记海鲜 23 套系统替换方案

---

## 二、硬件战略：务实混合架构（路线C）

### 核心原则
**安卓做"碰硬件的脏活"，Mac mini 做"需要算力的智能活"。**
交易链路走安卓成熟生态零阻力，Agent 智能走 Mac mini 保留技术壁垒。

### 门店硬件标准配置
| 设备 | 型号 | 角色 | 连接外设 |
|------|------|------|----------|
| 安卓 POS 主机 | 商米 T2/V2 | 收银 + 外设控制 + 业务UI | 打印机/秤/钱箱/扫码枪（USB） |
| Mac mini M4 | 16GB/256GB+ | 门店智能后台 | **无**（不连任何外设） |
| 安卓平板 | 商米 D2 或同级 | 后厨 KDS | 无 |
| 员工手机 | 员工自有安卓/iOS | 服务员点餐 | 无 |
| iPad（可选升级） | iPad Air/Pro | 高端店 POS/KDS | **无**（外设指令通过WiFi发到安卓POS执行） |

### 职责边界（铁律）
```
安卓 POS 主机：收银 + 打印 + 称重 + 钱箱 + 扫码 + 税控 + 银联刷卡
Mac mini M4：  本地数据库 + 边缘AI推理 + 数据同步 + Agent运行
iPad（可选）： 纯显示和触控，不连任何外设
```

### 为什么这样分
- 安卓 POS 碰外设：中国餐饮外设生态100%围绕安卓构建，厂商SDK成熟，零驱动开发
- Mac mini 不碰外设：规避 macOS 外设驱动难题，专注边缘AI和数据中枢
- iPad 可选升级：高端客户（如徐记海鲜）可选 iPad 提升品牌调性，技术上零差异

---

## 三、技术路线：Web App + 多壳层

### 决策原则
- **一套 React Web App，多端运行**。安卓用 WebView，iPad 用 WKWebView，总部用浏览器。
- **复用现有代码**：530K 行 Python + 232K 行 TypeScript 全部保留。
- **Swift 最小化**：仅用于 Core ML 桥接（必须）+ iPad 壳层（可选）。
- **Kotlin 最小化**：仅用于安卓 POS 壳层的 JS Bridge 外设调用。

### 技术栈总览
| 层 | 技术 | 说明 |
|----|------|------|
| 前端 Web App | React 18 + TypeScript + Tailwind + Zustand | 一套代码，所有终端共用 |
| 安卓 POS 壳层 | Kotlin + WebView + JS Bridge | 加载 React App，桥接商米外设 SDK |
| iPad 壳层（可选） | Swift + WKWebView | 高端店升级包。不写业务逻辑 |
| Mac mini 本地 | Python FastAPI + PostgreSQL 16 | 门店本地 API + 本地 DB 副本 + sync engine |
| Core ML 桥接 | Swift HTTP Server (port 8100) | 封装 M4 Neural Engine，暴露 /predict/* 给 Python |
| 云端后台 | Python FastAPI + PostgreSQL 16 | 腾讯云。RLS 多租户隔离 |
| 总部 Web | React + TypeScript | 浏览器直接访问 |
| 小程序 | 微信 + 抖音 | 顾客点餐、大厨到家 |
| AI 引擎 | Claude API (云端) + Core ML (边缘) | 双层推理 |
| 消息 | Redis Streams + PG LISTEN/NOTIFY | 轻量级 |
| 网络 | Tailscale | Mac mini 安全连接云端 |

---

## 四、五层架构

```
L4  多形态前端层    安卓POS / Windows POS / 安卓KDS / 员工PWA / iPad(可选) / 小程序 / 总部Web / 企业微信
L3  Agent OS 层     Master Agent 编排 + 9个 Skill Agent（边缘+云端双层推理）
L2  业务中台层      14 个微服务 × 9 大产品域 = 360+ 路由模块
L1  Ontology 层     6大实体 + 4层治理 + 3条硬约束 + PostgreSQL RLS
L0  设备适配层      安卓POS外设接口 + Mac mini智能后台 + 旧系统Adapter（可插拔）
```

---

## 五、项目结构

```
tunxiang-os/
  apps/                         # 16 个前端应用（React 18 + TypeScript + Vite）
    web-pos/                    # React — POS 收银（20+ 路由，安卓/Windows/iPad 共用）
    web-admin/                  # React — 总部管理后台（多域子页面）
    web-kds/                    # React — 后厨出餐屏（6 路由）
    web-crew/                   # React — 服务员 PWA（6 Tab + 全屏流）
    web-reception/              # React — 前台接待系统（预订/排队）
    web-tv-menu/                # React — TV 菜单屏显示
    web-hub/                    # React — 品牌 Hub 门户
    web-forge/                  # React — Forge 开发者市场
    web-wecom-sidebar/          # React — 企业微信侧边栏
    h5-self-order/              # React — H5 自助点餐（多渠道）
    miniapp-customer/           # 微信小程序 — 顾客端 v1（8 主包 + 7 分包）
    miniapp-customer-v2/        # 微信小程序 — 顾客端 v2
    android-pos/                # Kotlin — 安卓 POS 壳层（WebView + TXBridge + 商米SDK）
    android-shell/              # Kotlin — 安卓壳层新版
    ios-shell/                  # Swift — iOS 壳层（WKWebView）
    windows-pos-shell/          # Electron — Windows POS 壳层（WebView2）
  services/                     # 14 个业务微服务 + 2 个支撑服务（FastAPI + SQLAlchemy 2.0 + asyncpg）
    gateway/           :8000    # API Gateway + 域路由代理 + 租户管理
    tx-trade/          :8001    # 交易履约（90 路由文件：收银/桌台/KDS/预订/宴席/外卖）
    tx-menu/           :8002    # 菜品菜单（20 路由文件：菜品/发布/定价/套餐/做法）
    tx-member/         :8003    # 会员 CDP（33 路由文件：会员/营销/优惠券/礼品卡）
    tx-growth/         :8004    # 增长营销（18 路由文件：客户增长/复购驱动）
    tx-ops/            :8005    # 运营流程（15 路由文件：日清日结 E1-E8）
    tx-supply/         :8006    # 供应链（35 路由文件：库存/BOM/采购/食安/活鲜）
    tx-finance/        :8007    # 财务结算（20 路由文件：成本/P&L/预算/发票/月报）
    tx-agent/          :8008    # Agent OS（Master + 9 Skill Agent + 73 Actions）
    tx-analytics/      :8009    # 经营分析（28 路由文件：驾驶舱/健康度/叙事/报表）
    tx-brain/          :8010    # AI 智能决策中枢（Claude API）
    tx-intel/          :8011    # 商业智能（12 路由文件）
    tx-org/            :8012    # 组织人事（45 路由文件：员工/排班/角色/绩效/薪资）
    tx-civic/          :8014    # 城市监管平台（9 路由文件：食安追溯/明厨亮灶/环保/消防/证照/上报/合规评分）
    mcp-server/                 # MCP Protocol Server（对接 Claude Code）
    tunxiang-api/               # 遗留 API 兼容层
  edge/                         # Mac mini M4 边缘智能后台
    mac-station/                # FastAPI — 门店本地 API + PostgreSQL 副本
    coreml-bridge/              # Swift — Core ML HTTP 桥接（port 8100）
    sync-engine/                # Python — 本地PG ↔ 云端PG 增量同步（300秒/轮）
    mac-mini/                   # Python — Mac mini 工具集（离线缓冲/打印队列）
  shared/
    ontology/                   # Ontology 实体定义（Pydantic models）
    db-migrations/              # Alembic 迁移（229 个版本，v001-v229）
      # v147: 统一事件存储表（events + projector_checkpoints）
      # v148: 8个物化视图（mv_discount_health/mv_channel_margin/mv_inventory_bom
      #        mv_member_clv/mv_store_pnl/mv_daily_settlement/mv_safety_compliance/mv_energy_efficiency）
    adapters/                   # 10 个旧系统 Adapter（品智/奥琦玮/天财/美团/饿了么/抖音等）
    events/                     # 统一事件总线（Event Sourcing + CQRS，v147/v148）
      src/
        pg_event_store.py       #   PostgreSQL append-only 事件存储写入器
        emitter.py              #   平行事件发射器（Redis Stream + PG 双写）
        projector.py            #   投影器基类（事件流 → 物化视图）
        event_types.py          #   10大域事件类型（订单/折扣/支付/会员/库存/渠道/宴会/结算/食安/能耗）
    hardware/                   # 硬件接口（商米SDK/电子秤/打印机/钱箱/扫码枪）
    vector_store/               # 向量存储（嵌入/相似度搜索）
    security/                   # 安全模块（加密/认证）
    feature_flags/              # 特性开关系统
    skill_registry/             # Agent Skill 注册表
    api-types/                  # 跨服务 API 类型定义（TypeScript）
  infra/
    docker/                     # Docker Compose（dev/prod/staging/gray/demo）
    helm/                       # Kubernetes Helm Chart（11 个）
    nginx/                      # Nginx 反代 + SSL + WebSocket
    tailscale/                  # Tailscale 网络配置
    jumpserver/                 # 堡垒机配置
    dns/                        # DNS 配置脚本
  gitops/                       # GitOps 部署配置（dev/test/uat/pilot/prod）
  flags/                        # 特性开关（trade/member/org/growth/agents/edge）
  scripts/                      # 自动化脚本（34+ 个）
  docs/                         # 67 份详细设计文档
  DEVLOG.md                     # 每日开发进度日志（日更）
```

---

## 六、Ontology 规范（L1）

### 六大核心实体
1. **Customer** — Golden ID, 全渠道画像, RFM 分层, 生命周期
2. **Dish** — BOM 配方, 各渠道价格, 毛利模型, 四象限分类
3. **Store** — 桌台拓扑, 档口配置, 人效模型, 经营指标
4. **Order** — 全渠道统一, 折扣明细, 核销记录, 出餐状态
5. **Ingredient** — 库存量, 效期, 采购价, 批次, 供应商
6. **Employee** — 角色, 技能, 排班, 业绩提成, 效率指标

### 四层治理
```
集团 → 品牌 → 业态(大店Pro/小店Lite/宴席/外卖) → 门店
```
PostgreSQL RLS 实现租户隔离。品牌并构时新建品牌节点即可。

### 三条不可违反的硬约束
**所有 Agent 决策必须通过这三条校验，无例外：**
1. **毛利底线** — 任何折扣/赠送不可使单笔毛利低于设定阈值
2. **食安合规** — 临期/过期食材不可用于出品
3. **客户体验** — 出餐时间不可超过门店设定上限

### 底层基类
```sql
-- 所有实体表必须包含
tenant_id    UUID NOT NULL,     -- RLS 租户隔离
created_at   TIMESTAMPTZ DEFAULT NOW(),
updated_at   TIMESTAMPTZ DEFAULT NOW(),
is_deleted   BOOLEAN DEFAULT FALSE
```

---

## 七、安卓 POS 壳层规范（android-shell）

### 架构
商米 WebView 加载 React Web App，外设调用通过 JS Bridge 桥接。

### JS Bridge 接口定义
React Web App 通过 `window.TXBridge.*` 调用安卓原生能力：

```kotlin
// android-shell 暴露给 Web 的接口
interface TXBridge {
    // 打印
    fun print(content: String)          // ESC/POS 打印（小票/厨房单）
    fun openCashBox()                   // 弹出钱箱

    // 称重
    fun startScale()                    // 开始监听电子秤
    fun onScaleData(callback: String)   // 称重数据回调

    // 扫码
    fun scan()                          // 启动扫码
    fun onScanResult(callback: String)  // 扫码结果回调

    // 设备信息
    fun getDeviceInfo(): String         // 返回设备型号/序列号

    // 与 Mac mini 通信
    fun getMacMiniUrl(): String         // 返回局域网内 Mac mini 地址
}
```

### React Web App 调用示例
```typescript
// 在 React 中调用打印
const printReceipt = (orderData: OrderData) => {
  if (window.TXBridge) {
    // 安卓 POS 环境：通过 JS Bridge 调用商米打印 SDK
    window.TXBridge.print(formatReceipt(orderData));
  } else {
    // 浏览器/iPad 环境：通过 HTTP 发送到安卓 POS 执行
    fetch(`${posHostUrl}/api/print`, { method: 'POST', body: JSON.stringify(orderData) });
  }
};
```

### 关键规则
- **所有外设调用只在 android-shell 层处理**
- **React Web App 通过 TXBridge 接口抽象外设**，不直接依赖任何外设 SDK
- **iPad 环境没有 TXBridge**，外设指令通过 HTTP 发送到安卓 POS 主机执行
- 锁定商米 T2/V2 两款主力机型，减少适配成本

---

## 八、Mac mini 边缘服务规范（edge/）

### 职责：只做智能，不碰外设
Mac mini 运行三个核心服务：
1. `mac-station` — 门店本地 API + 本地 PostgreSQL 副本
2. `coreml-bridge` — Core ML 推理 HTTP 服务
3. `sync-engine` — 本地PG ↔ 云端PG 增量同步

### 离线优先
- 安卓 POS 的收银数据先写入 Mac mini 本地 PG
- 断网时 Mac mini 继续提供本地 API 服务
- 边缘 Agent（出餐预测/折扣检测）通过 Core ML 本地运行
- sync-engine 每 300 秒增量同步，冲突解决策略：云端为主

### Core ML 桥接接口
```
coreml-bridge (Swift HTTP Server, port 8100)
  POST /predict/dish-time       → 出餐时间预测
  POST /predict/discount-risk   → 折扣异常检测评分
  POST /predict/traffic         → 客流量预测
  POST /transcribe              → 语音指令识别 (Whisper)
  GET  /health                  → 服务健康检查
```
Python 服务通过 `http://localhost:8100/predict/*` 调用。

### Mac mini 部署
- macOS 通过 launchd 管理所有服务（开机自启、崩溃重启）
- Tailscale 自动连接云端
- 首次部署：制作标准化配置脚本，远程 SSH 完成初始化
- 配备小型 UPS（~200元）保障断电安全关机

---

## 九、Agent 开发规范

### 架构
- Master Agent（H2 编排中心）统一调度
- Skill Agent（每个业务 Agent）专域执行
- 双层推理：边缘 Core ML（实时轻量）+ 云端 Claude API（复杂推理）

### 九大核心 Agent
| # | Agent | 优先级 | 运行位置 |
|---|-------|--------|----------|
| 1 | 折扣守护 | P0 | 边缘 + 云端 |
| 2 | 智能排菜 | P0 | 云端 |
| 3 | 出餐调度 | P1 | 边缘 |
| 4 | 会员洞察 | P1 | 云端 |
| 5 | 库存预警 | P1 | 边缘 + 云端 |
| 6 | 财务稽核 | P1 | 云端 |
| 7 | 巡店质检 | P2 | 云端 |
| 8 | 智能客服 | P2 | 云端 |
| 9 | 私域运营 | P2 | 云端 |

### 决策留痕（强制）
```python
class AgentDecisionLog(BaseModel):
    agent_id: str
    decision_type: str
    input_context: dict         # 输入上下文
    reasoning: str              # 推理过程
    output_action: dict         # 输出动作
    constraints_check: dict     # 三条硬约束校验结果
    confidence: float           # 置信度
    created_at: datetime
```

### Agent 与安卓 POS 交互
Agent 决策结果通过 Mac mini 本地 API → WebSocket → 安卓 POS WebView 推送到前端 UI。
例：折扣守护 Agent 检测到异常折扣 → Mac mini 推送预警到安卓 POS → React App 弹出提醒。

---

## 十、编码规范

### Python（服务端 + Mac mini 边缘）
- FastAPI + Pydantic V2 + async/await
- Repository 模式：Service → Repository → DB
- 禁止 broad except（必须指定具体异常类型）
- 所有函数有 type hints
- 日志用 structlog，JSON 格式

### TypeScript（前端 Web App）
- React 18 + TypeScript strict mode
- 状态管理：Zustand
- 样式：Tailwind CSS
- 外设调用统一通过 `window.TXBridge` 抽象层，不直接依赖平台 API
- API 调用：自定义 hook `useTxAPI()`

### Kotlin（安卓 POS 壳层）
- 仅做 WebView 壳层 + JS Bridge + 商米 SDK 调用
- **不写业务逻辑**
- JS Bridge 接口保持最小化，每个新接口必须有对应的 TypeScript 类型定义

### Swift（Core ML 桥接 + iPad 壳层）
- Core ML 桥接：Vapor/Hummingbird HTTP server，监听 localhost:8100
- iPad 壳层：WKWebView 加载 React App，桥接 camera/notification
- **不写业务逻辑**

### API 设计
- RESTful，统一响应：`{ "ok": bool, "data": {}, "error": {} }`
- 所有接口包含 `X-Tenant-ID` header
- 分页：`?page=1&size=20`，返回 `{ items: [], total: int }`
- 版本：`/api/v1/`

### 数据库
- 所有表包含 `tenant_id`
- RLS Policy 强制租户隔离
- Alembic 管理迁移
- 命名：snake_case，表名复数

### 测试
- pytest + pytest-asyncio
- P0 服务覆盖率 ≥ 80%
- 安卓 JS Bridge 必须有端到端测试
- Core ML 桥接模块必须有端到端测试

---

## 十一、门店网络拓扑

```
                    ┌──────────────┐
                    │   腾讯云      │
                    │ FastAPI + PG  │
                    └──────┬───────┘
                           │ Tailscale
                    ┌──────┴───────┐
                    │  Mac mini M4  │
                    │ 本地PG + AI   │
                    │ port 8000(API)│
                    │ port 8100(ML) │
                    └──────┬───────┘
                           │ WiFi (局域网)
            ┌──────────────┼──────────────┐
            │              │              │
     ┌──────┴──────┐ ┌────┴─────┐ ┌─────┴──────┐
     │ 安卓POS主机  │ │安卓平板   │ │员工手机     │
     │ 收银+外设    │ │KDS出餐屏  │ │PWA服务员端  │
     │ WebView     │ │Chrome    │ │浏览器      │
     └──────┬──────┘ └──────────┘ └────────────┘
            │ USB
     ┌──────┴──────────────────────┐
     │ 打印机 / 电子秤 / 钱箱 / 扫码枪 │
     └─────────────────────────────┘
```

**关键：所有外设只连安卓POS主机，Mac mini 不连任何外设。**

---

## 十二、iPad 可选升级包规范

### 适用场景
高端连锁品牌（如徐记海鲜）希望用 iPad 提升门店品质感。

### 技术实现
- iPad 运行同一套 React Web App（通过 WKWebView 或 Safari）
- iPad 不连接任何外设
- 打印/称重等指令通过 WiFi HTTP 发送到安卓 POS 主机执行
- 如果安卓 POS 主机断开，iPad 降级为"仅查看"模式

### iPad 环境判断
```typescript
const isIPad = () => !window.TXBridge && /iPad/.test(navigator.userAgent);
const isAndroidPOS = () => !!window.TXBridge;
const isBrowser = () => !window.TXBridge && !isIPad();

// 外设调用统一入口
const printReceipt = async (data: OrderData) => {
  if (isAndroidPOS()) {
    window.TXBridge.print(formatReceipt(data));
  } else {
    // iPad/浏览器：通过 HTTP 发送到安卓 POS
    await fetch(`${getPosMachineUrl()}/api/print`, {
      method: 'POST', body: JSON.stringify(data)
    });
  }
};
```

---

## 十三、禁止事项

1. **禁止在 Kotlin/Swift 层写业务逻辑** — 壳层只做桥接
2. **禁止 Mac mini 连接任何外设** — 外设全部由安卓 POS 处理
3. **禁止 iPad 直连外设** — 外设指令通过 HTTP 转发到安卓 POS
4. **禁止 broad except** — 必须指定具体异常类型
5. **禁止硬编码密钥** — 环境变量注入
6. **禁止跳过 RLS** — 所有 DB 操作必须带 tenant_id
7. **禁止 Agent 突破三条硬约束** — 毛利底线 + 食安合规 + 客户体验
8. **禁止同步阻塞业务** — sync-engine 异步运行
9. **禁止不记录 Agent 决策** — 每个决策必须有留痕
10. **禁止 React Web App 直接调用外设 SDK** — 必须通过 TXBridge 抽象层

---

## 十四、审计修复期特别约束（2026-03 至 2026-06）

> 基于 v6 代码审计结果，以下约束在修复期间强制执行。详见 `docs/security-audit-report.md` 和 `docs/development-plan-v6-remediation.md`。

### 异常处理
- 新代码禁止使用 `except Exception`（最外层兜底除外，且必须加 `exc_info=True`）
- 修改 `except Exception` 时，必须替换为具体异常类型
- 新增 POS 适配器代码必须附带 >=3 个测试用例

### 安全
- 禁止在 `config/merchants/` 目录下提交任何文件
- 数据库新表必须包含 `tenant_id` + RLS 策略（使用 `app.tenant_id`，禁止 NULL 绕过）
- 所有模型调用必须通过 `ModelRouter`，不直接调用 API

### 提交前检查
- `git-secrets` 扫描通过（`scripts/setup-git-secrets.sh` 配置）
- 涉及模块的 pytest 通过
- 无新增 broad except（用 ruff 规则检查）

---

## 十五、统一事件总线规范（Event Sourcing + CQRS，v147起）

> 2026-04-04 升级。方案来源：tunxiangos upgrade proposal.docx

### 核心原则
一切业务动作 = 不可变事件。七条因果链 = 同一事件流的七个视图。

### 事件写入（Phase 1 — 并行写入）
所有业务写入路径在原有逻辑后，用 `asyncio.create_task(emit_event(...))` 旁路写入事件：

```python
from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OrderEventType

# 在业务代码写入路径（完成原有逻辑后）：
asyncio.create_task(emit_event(
    event_type=OrderEventType.PAID,
    tenant_id=tenant_id,
    stream_id=str(order_id),        # 聚合根ID
    payload={"total_fen": 8800},    # 金额全部用分（整数）
    store_id=store_id,
    source_service="tx-trade",
    metadata={"operator_id": "..."},
    causation_id=None,              # 因果链追踪
))
```

### 事件类型强制规则
- 使用 `shared.events.src.event_types` 中已定义的枚举，不硬编码字符串
- 新事件类型必须先在 `event_types.py` 中注册，再使用
- payload 中所有金额字段单位为**分（整数）**，不使用浮点

### 物化视图（Phase 2 — 投影器）
- 8个物化视图（`mv_*`）由投影器从事件流异步生成
- Agent 和报表**只读物化视图**，不跨服务查询
- 视图损坏时：`await projector.rebuild()` 从��件流完整重建

### 哪些业务域��要接入 emit_event
| 域 | 关键事件 | 服务 | 状态 |
|---|---|---|---|
| 订单 | ORDER.PAID | tx-trade/cashier_engine.py | ✅ Phase 1 接入 |
| 折扣 | DISCOUNT.APPLIED | tx-trade/cashier_engine.py | ✅ Phase 1 接入 |
| 支付 | PAYMENT.CONFIRMED | tx-trade/cashier_engine.py | ✅ Phase 1 接入 |
| 会员储值 | MEMBER.RECHARGED/CONSUMED | tx-member/stored_value_routes.py | ✅ Phase 1 接入 |
| 日结 | SETTLEMENT.DAILY_CLOSED | tx-ops/daily_settlement_routes.py | ✅ Phase 1 接入 |
| 库存 | INVENTORY.RECEIVED/CONSUMED/WASTED/ADJUSTED | tx-supply/inventory.py + deduction_routes.py | ✅ Phase 1 接入 |
| 渠道 | CHANNEL.ORDER_SYNCED | tx-trade/webhook_routes.py（美团/饿了么/抖音） | ✅ Phase 1 接入 |
| 食安 | SAFETY.SAMPLE_LOGGED/TEMPERATURE_RECORDED/INSPECTION_DONE/VIOLATION_FOUND | tx-ops/food_safety_routes.py | ✅ Phase 4 接入 |
| 能耗 | ENERGY.READING_CAPTURED/ANOMALY_DETECTED/BENCHMARK_SET | tx-ops/energy_routes.py | ✅ Phase 4 接入 |

### 迁移阶段时间线
- **v147 (Phase 1)**：events 表 + projector_checkpoints（并行写入，不影响现有服务）
- **v148 (Phase 2)**：8个物化视图（投影器消费事件后填充）
- **Phase 3**：Agent 和报表切换为读物化视图（不再跨服务查询）
- **Phase 4**：食安/能耗/舆情新模块直接基于事件总线建设

---

## 十六、每日开发日志规范

每次开发结束后，在 `DEVLOG.md` 顶部追加当日记录，格式如下：

```markdown
## YYYY-MM-DD

### 今日完成
- [服务/模块] 具体内容

### 数据变化
- 迁移版本：vXXX → vXXX
- 新增 API 模块：N 个（服务名/功能）
- 新增测试：N 个

### 遗留问题
- 描述待解决的问题

### 明日计划
- 计划内容
```

**规则**：
- 每个开发会话结束后必须更新 DEVLOG.md
- 同步更新 README.md 中的"十大致命差距修复进度"状态（🔴→🟡→✅）
- 重大架构变更必须同步更新本文件（CLAUDE.md）对应节

---

## 十七、业务路径分级（Tier 制）

> 解决核心问题：Claude 生成的代码必须在徐记海鲜收银台上真实可用，而不只是技术上能跑通。

### Tier 1：零容忍（影响资金安全或收银员日常操作）

**修改这些路径时，必须先写测试、后写实现（TDD），且在 DEMO 环境验收通过后才算完成。**

| 路径 | 服务 | 核心文件 |
|------|------|---------|
| 订单状态机 | tx-trade | cashier_engine.py / order_service.py |
| 支付补偿 Saga | tx-trade | payment_saga_service.py |
| RLS 多租户隔离 | 全局 | 所有 *_rls.sql |
| POS 数据写入与结算 | tx-trade | adapters/pinjin / aiqiwei / meituan |
| 存酒 / 押金 / 协议挂账 | tx-trade / tx-finance | wine_storage_service.py |
| 全电发票 / 金税四期 | tx-finance | invoice_service.py |
| CRDT 冲突解析 | edge/sync-engine | — |
| 三条硬约束校验 | tx-agent | 毛利底线 / 食安合规 / 客户体验 |

**Tier 1 验收标准：**
- P99 延迟 < 200ms
- 支付成功率 > 99.9%
- 断网 4 小时重连后无数据丢失
- 测试用例基于真实餐厅场景（非技术边界值）

### Tier 2：高标准（影响门店运营效率，不涉及资金）

KDS 推送与出餐确认、备用金日结核销、督导巡店任务调度、积分获取与兑换、台位图状态同步。

要求：集成测试覆盖主流程，DEMO 环境手动验证。

### Tier 3：常规标准（辅助展示或低频操作）

报表生成、发票申请界面 UI、排队叫号展示、城市合规上报、IM 通知推送。

要求：功能测试通过即可。

**铁律：质量资源集中在 Tier 1，不用 Tier 3 的标准开发 Tier 1 的代码。**

---

## 十八、Claude 会话防漂移规范

> 上下文压缩是有损操作。以下规范防止关键约束在压缩后消失，导致代码与真实业务脱节。

### 会话开始前（必须在对话开头声明）

```
## 本次会话目标
[一句话，具体到功能点，例如：修复存酒押金在多次续存后余额计算错误]

## 不得触碰的边界
- [ ] 存酒押金计算逻辑（只修 Bug，不重构）
- [ ] shared/ontology/ 下任何文件（需创始人确认）
- [ ] 已应用的迁移文件（v001–vXXX，禁止修改）
- [ ] RLS 策略文件（涉及安全，单独 PR）

## 本次涉及范围
- 服务：[服务名]
- 迁移版本：vXXX → vXXX（如有）
- Tier 级别：[ ] Tier 1  [ ] Tier 2  [ ] Tier 3
```

### 会话结束后（必须更新 progress.md）

文件路径：`docs/progress.md`

```markdown
## YYYY-MM-DD HH:MM

### 完成状态
- [x] 已完成：[具体功能]
- [ ] 未完成：[原因]

### 关键决策
- [决策]：[为什么选这个方案，而不是其他]

### 下一步
- [下一个具体任务]

### 已知风险
- [任何可能影响 Tier 1 路径的改动，或预期之外的副作用]
```

**压缩发生后，Claude 从 progress.md 重建上下文，而不是依赖对话历史。**

### Ontology 层冻结规则

`shared/ontology/` 下的所有文件，Claude **不得自动修改**。
如确需变更，停止操作，向创始人描述变更理由，由创始人确认后再进行。

---

## 十九、独立验证规则

> 编写代码的 Agent 不能自行宣布任务完成。满足以下任一条件时，必须开启新会话从验证视角重检。

**触发条件：**

| 条件 | 验证重点 |
|------|---------|
| 修改了 3 个以上文件 | 各文件改动是否自洽，有无意外副作用 |
| 涉及数据库迁移 | 迁移是否可回滚，RLS 策略是否正确 |
| 修改了 Tier 1 路径 | 业务逻辑是否符合餐厅实际操作流程 |
| 新增微服务 | 与现有 15 个服务的边界是否清晰 |
| 修改了权限 / 认证逻辑 | 跨租户隔离是否仍然有效 |

**验证视角提示词模板（新会话开头使用）：**

```
你是屯象OS的代码审查者，不是开发者。刚完成的修改是：[描述]，涉及文件：[列表]。

请从徐记海鲜收银员的视角评估：
1. 这个改动在 200 桌并发高峰期会出什么问题？
2. 如果网络中断 4 小时，会导致什么数据问题？
3. 有没有意外修改 Tier 1 路径的行为？
4. RLS 策略在所有查询路径上是否仍然有效？

只指出风险，不重复描述代码内容。
```

---

## 二十、Tier 1 测试标准

### 原则：测试先于实现（TDD），用例基于真实餐厅场景

```python
# 文件命名：test_[service]_tier1.py
# 用例描述必须是餐厅场景，而不是技术边界值

class TestOrderStateMachineTier1:
    def test_200_tables_concurrent_checkout_p99(self):
        """200 桌并发结账，P99 < 200ms"""

    def test_payment_timeout_saga_full_rollback(self):
        """支付超时后，座位状态/库存/积分全部回滚，无半状态"""

    def test_offline_4h_crdt_no_data_loss(self):
        """断网 4 小时重连后，订单数据无丢失、无冲突"""

    def test_wine_storage_multi_topup_balance_correct(self):
        """存酒 3 次续存后，押金余额计算与手工账核对一致"""

    def test_rls_cross_tenant_isolation(self):
        """tenant_A 的查询不能返回 tenant_B 的任何数据"""

    def test_invoice_golden_tax_phase4_compliant(self):
        """全电发票申请符合金税四期格式，不被退票"""
```

### Tier 1 提交前检查清单

- [ ] 所有 Tier 1 用例通过（DEV 环境）
- [ ] 在 DEMO 环境（`demo-xuji-seafood.sql`）手动跑通主流程
- [ ] P99 延迟已记录
- [ ] progress.md 已更新，注明已知风险

---

## 二十一、Git 提交规范（防漂移版）

### 原子化提交：一个逻辑改动 = 一个 commit

```bash
# 正确：每个 commit 可独立回滚，可独立灰度
git commit -m "fix(tx-trade): 存酒押金多次续存余额计算错误 [Tier1]"
git commit -m "test(tx-trade): 添加 wine_storage 多次续存场景测试 [Tier1]"
git commit -m "migrate: v245_fix_wine_deposit_calculation"

# 错误：混入多个改动，无法定向回滚
git commit -m "修复了一些 bug，顺便优化了存酒和 KDS"
```

### Commit Message 格式

```
[type]([service]): [描述] [Tier级别]

type: fix | feat | test | migrate | refactor | security
```

### 灰度上线路径（Tier 1 改动强制执行）

```
DEV 环境功能验证
  → DEMO 环境（徐记海鲜数据）场景验证
    → 灰度 5% → 50% → 100%
      回滚阈值：错误率 > 0.1%
```

---

## 二十二、Week 8 DEMO 验收门槛

> 徐记海鲜评估屯象OS能否替换现有 23 个系统的实质标准。

| 指标 | 门槛 | 说明 |
|------|------|------|
| Tier 1 全绿 | 100% 测试通过 | 订单/支付/RLS/POS/存酒/发票 |
| P99 延迟 | < 200ms | 200 桌并发场景 |
| 支付成功率 | > 99.9% | 含超时/失败回滚 |
| 断网恢复 | 4 小时内无数据丢失 | CRDT 验证 |
| 收银员操作 | 无需技术培训即可使用 | 现场用户测试 |

**这 5 个数字是屯象OS的真实交付标准，不是代码跑通。**
