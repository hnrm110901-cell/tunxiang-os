# 屯象OS Feature Flags 体系

## 命名规范

格式：`{domain}.{agent_or_module}.{feature}.{action}`

### 域（domain）清单

| 域 | 前缀 | 说明 |
|---|---|---|
| 增长中枢 | `growth` | 旅程模板、沉默召回、触达频控 |
| Agent体系 | `agent` | 各 Skill Agent 开关、自治级别 |
| 交易履约 | `trade` | 外卖接单、折扣引擎、语音下单 |
| 人力组织 | `org` | 排班、贡献度、离职预警 |
| 会员CDP | `member` | 洞察页面、CLV引擎、GDPR |
| 边缘计算 | `edge` | 增量同步、CoreML推理、离线模式 |

### 动作（action）后缀约定

| 后缀 | 含义 | 风险等级 |
|---|---|---|
| `.enable` | 功能开关（只读或展示类） | 低 |
| `.auto_execute` | 自动执行（无人工干预） | 高 |
| `.auto_publish` | 自动发布 | 高 |

---

## 评估维度

所有 Flag 支持以下维度进行定向开启（targeting_rules）：

| 维度 | 类型 | 说明 |
|---|---|---|
| `tenant_id` | string | 租户级别控制 |
| `brand_id` | string | 品牌级别控制 |
| `region_id` | string | 区域级别控制 |
| `store_id` | string | 门店级别控制 |
| `role_code` | string | 角色级别控制（L1/L2/L3） |
| `app_version` | string | App版本控制 |
| `edge_node_group` | string | 边缘节点分组控制 |

### targeting_rules 格式

```yaml
targeting_rules:
  pilot:          # 环境名
    - dimension: brand_id
      values: [brand_001, brand_002]
  prod:
    - dimension: store_id
      values: [store_vip_001]
    - dimension: role_code
      values: [L3]
      operator: any  # any（默认）或 all
```

---

## 环境说明

| 环境 | 用途 |
|---|---|
| `dev` | 本地开发，大部分Flag开启 |
| `test` | CI测试，同dev |
| `uat` | 用户验收测试 |
| `pilot` | 灰度环境，定向开启 |
| `prod` | 生产，默认最保守 |

---

## 使用方式

### Python SDK

```python
from shared.feature_flags import is_enabled, FlagContext
from shared.feature_flags.flag_names import GrowthFlags, AgentFlags

# 简单判断（无上下文）
if is_enabled(GrowthFlags.JOURNEY_V2):
    run_v2_logic()

# 带上下文（多维度定向）
ctx = FlagContext(
    tenant_id="t_001",
    brand_id="brand_001",
    store_id="store_123",
    role_code="L3",
)
if is_enabled(AgentFlags.L3_AUTONOMY, ctx):
    allow_autonomous_action()
```

### 环境变量覆盖

格式：`FEATURE_{FLAG_NAME_UPPERCASE_WITH_UNDERSCORE}=true`

```bash
# 覆盖单个Flag（优先级最高）
export FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE=true
export FEATURE_AGENT_L3_AUTONOMY_ENABLE=false
```

### FastAPI 中间件

```python
from shared.feature_flags.middleware import FeatureFlagMiddleware

app.add_middleware(FeatureFlagMiddleware)

# 在路由中使用
@app.get("/some-endpoint")
async def handler(request: Request):
    ctx = request.state.flag_context
    if is_enabled(GrowthFlags.JOURNEY_V2, ctx):
        ...
```

---

## 各域 Flag 文件清单

| 文件 | 说明 |
|---|---|
| `growth/growth_hub_flags.yaml` | 增长中枢（8个Flag） |
| `agents/agent_flags.yaml` | Agent体系（10个Flag） |
| `trade/trade_flags.yaml` | 交易履约（8个Flag，含 Sprint A1 三件套） |
| `org/hr_flags.yaml` | 人力组织（5个Flag） |
| `member/member_flags.yaml` | 会员CDP（4个Flag） |
| `edge/edge_flags.yaml` | 边缘计算（4个Flag） |

---

## 高风险 Flag 管控规则

以下 Flag 为高风险，生产启用必须经过审批流：

- `growth.agent.suggestion.auto_publish` — Agent建议自动发布，仅允许L3门店
- `agent.hr.shift_suggest.auto_execute` — 排班自动执行，L2自治
- `agent.l3_autonomy.enable` — L3全自治，最高风险
- `edge.offline.full_mode.enable` — 完全离线模式，需确认数据同步策略

变更流程：
1. 提交审批单（Approval Service）
2. 指定 targeting_rules 范围（不允许全量prod开启）
3. 观察24小时后方可扩大范围

---

## Sprint A1 POS 收银硬化三件套（2026-04-18）

| Flag | 作用 | 关闭回滚行为 |
|---|---|---|
| `trade.pos.settle.hardening.enable` | `txFetchTrade` 超时分级（SETTLE 8s / QUERY 3s）+ 离线自动入队 + 5 类错误码 | 回退到无超时分级、直接 throw 的旧行为 |
| `trade.pos.toast.enable` | `<ToastContainer>` 统一提示替代 alert() | 降级到 window.alert |
| `trade.pos.errorBoundary.enable` | 顶层 + `/settle/:id` `/order/:id` 路由级 ErrorBoundary | 崩溃白屏（但仍可通过其他链路采集崩溃） |

**灰度路径**：pilot (5%) → pilot (50%) → prod (100%)，回滚阈值错误率 > 0.1%
**前端读取**：`apps/web-pos` 启动时 `initFeatureFlags()` 调 `GET /api/v1/flags?domain=trade` 覆盖本地 DEFAULTS；端点未就绪时静默回退到 yaml defaultValue。
