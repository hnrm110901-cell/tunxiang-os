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
- **复用现有代码**：363K 行 Python + 93K 行 TypeScript 全部保留。
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
L4  多形态前端层    安卓POS / 安卓KDS / 员工PWA / iPad(可选) / 小程序 / 总部Web
L3  Agent OS 层     Master Agent 编排 + 9个 Skill Agent（边缘+云端双层推理）
L2  业务中台层      8大产品域 × 8模块 = 64个二级模块
L1  Ontology 层     6大实体 + 4层治理 + 3条硬约束 + PostgreSQL RLS
L0  设备适配层      安卓POS外设接口 + Mac mini智能后台 + 旧系统Adapter（可插拔）
```

---

## 五、项目结构

```
tunxiang-os/
  apps/                         # 10 个前端应用（React 18 + TypeScript + Vite）
    web-pos/                    # React — POS 收银（20+ 路由，安卓/iPad 共用）
    web-admin/                  # React — 总部管理后台（多域子页面）
    web-kds/                    # React — 后厨出餐屏（6 路由）
    web-crew/                   # React — 服务员 PWA（6 Tab + 全屏流）
    web-reception/              # React — 前台接待系统（预订/排队）
    web-tv-menu/                # React — TV 菜单屏显示
    web-hub/                    # React — 品牌 Hub 门户
    web-forge/                  # React — Forge 开发者市场
    h5-self-order/              # React — H5 自助点餐（多渠道）
    miniapp-customer/           # 微信小程序 — 顾客端（8 主包 + 7 分包）
  services/                     # 16 个微服务（FastAPI + SQLAlchemy 2.0 + asyncpg）
    gateway/           :8000    # API Gateway + 域路由代理 + 租户管理
    tx-trade/          :8001    # 交易履约（76 API 模块）
    tx-menu/           :8002    # 菜品菜单（15 API 模块）
    tx-member/         :8003    # 会员 CDP（25 API 模块）
    tx-growth/         :8004    # 增长营销（11 API 模块）
    tx-ops/            :8005    # 运营流程（10 API 模块，日清日结 E1-E8）
    tx-supply/         :8006    # 供应链（23 API 模块）
    tx-finance/        :8007    # 财务结算（16 API 模块）
    tx-agent/          :8008    # Agent OS（Master + 9 Skill Agent + 73 Actions）
    tx-analytics/      :8009    # 经营分析（15 API 模块）
    tx-brain/          :8010    # AI 智能决策中枢（Claude API）
    tx-intel/          :8011    # 商业智能
    tx-org/            :8012    # 组织人事（28 API 模块）
    mcp-server/                 # MCP Protocol Server（对接 Claude Code）
  edge/                         # Mac mini M4 边缘智能后台
    mac-station/                # FastAPI — 门店本地 API + PostgreSQL 副本
    coreml-bridge/              # Swift — Core ML HTTP 桥接（port 8100）
    sync-engine/                # Python — 本地PG ↔ 云端PG 增量同步（300秒/轮）
  shared/
    ontology/                   # Ontology 实体定义（Pydantic models）
    db-migrations/              # Alembic 迁移（148 个版本，v001-v148）
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
  infra/
    docker/                     # Docker Compose（dev/prod/staging/gray）
    nginx/                      # Nginx 反代 + SSL + WebSocket
    tailscale/                  # Tailscale 网络配置
    dns/                        # DNS 配置脚本
  docs/                         # 47 份详细设计文档
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
