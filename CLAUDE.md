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
  apps/
    web-pos/              # React — POS 界面（安卓/iPad 共用）
    web-kds/              # React — KDS 出餐屏
    web-crew/             # React — 服务员端（PWA）
    web-admin/            # React — 总部管理后台
    android-shell/        # Kotlin — 商米 POS WebView 壳层 + JS Bridge
    ios-shell/            # Swift — iPad WKWebView 壳层（可选升级包）
    miniapp-customer/     # 微信小程序 — 顾客端
  services/
    gateway/              # FastAPI — API Gateway
    tx-trade/             # FastAPI — 域A 交易履约
    tx-menu/              # FastAPI — 域B 商品菜单
    tx-member/            # FastAPI — 域C 会员CDP
    tx-supply/            # FastAPI — 域D 供应链
    tx-finance/           # FastAPI — 域E 财务结算
    tx-org/               # FastAPI — 域F 组织运营
    tx-analytics/         # FastAPI — 域G 经营分析
    tx-agent/             # FastAPI — 域H Agent OS
  edge/
    mac-station/          # FastAPI — Mac mini 门店本地服务
    coreml-bridge/        # Swift — Core ML HTTP 桥接 (port 8100)
    sync-engine/          # Python — 本地PG ↔ 云端PG 增量同步
  shared/
    ontology/             # Ontology 实体定义（Pydantic models）
    db-migrations/        # Alembic 迁移脚本
    adapters/             # 旧系统 Adapter（品智/微生活/G10/金蝶/润典）
  infra/
    docker/               # Docker Compose
    tailscale/            # Tailscale 网络配置
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
