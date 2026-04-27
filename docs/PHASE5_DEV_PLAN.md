# PHASE5_DEV_PLAN.md — FCT Agent 2.0 重构开发计划

> 本文档是屯象OS FCT Agent 从 1.0 → 2.0 的 **Phase 5–7** 开发计划。
> Phase 5 目标：Ontology 事件总线骨架立起 + 首个子 Agent（CashFlowAlertAgent）+ NL 查询 Agent 上线。
>
> **文档版本**：v1.0
> **生成时间**：2026-04-18
> **适用范围**：services/tx-agent、services/tx-finance、services/tx-brain、shared/events、shared/finance（新建）
> **首客**：尝在一起（真实数据回放）
> **LLM**：GLM-5.1（`zhipuai` SDK）
> **不得触碰**：`shared/ontology/` 冻结（CLAUDE.md §18）、已应用迁移（v001–v229）、未授权 Tier 1 路径

---

## §0 关键修正（读前必看）

基于 CLAUDE.md 约束对原方案做的 4 处修正：

| # | 修正项 | 原方案 | 当前方案 | 原因 |
|---|---|---|---|---|
| 1 | 总线代码位置 | `shared/ontology/bus/` | **`shared/events/bus/`** | CLAUDE.md §18 Ontology 冻结 |
| 2 | 事件 Schema 位置 | `shared/ontology/schemas/` | **`shared/events/schemas/`** | 同上 |
| 3 | 三条硬约束共享模块 | `shared/ontology/constraints.py` | **`shared/finance/constraints.py`** | 同上；且约束是"业务层"而非"实体层" |
| 4 | 首客 / LLM | 尚宫厨 / Claude Haiku | **尝在一起 / GLM-5.1** | 创始人确认 |

---

## §1 架构总览

### 1.1 当前（FCT 1.0 现状）

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          FCT 1.0 现状（已落地）                            │
├────────────────────────────────────────────────────────────────────────────┤
│  [web-admin] [miniapp] [web-wecom-sidebar]                                 │
│                    │ HTTP                                                  │
│                    ▼                                                       │
│           gateway:8000 (路由代理)                                          │
│     ┌──────────────┼─────────────────────────┐                             │
│     ▼              ▼                         ▼                             │
│  tx-finance:8007   tx-agent:8008             tx-brain:8010                 │
│   ├ invoice        ├ master.py               ├ cfo_dashboard (550行)       │
│   ├ vat            ├ orchestrator (747行)    ├ finance_auditor (550行)     │
│   ├ three_way_match├ skills/finance_audit    └ cost_truth_engine           │
│   ├ pnl (多引擎)   │   (18 actions)                                        │
│   └ voucher        └ scheduler (APScheduler)                               │
│     │                                                                      │
│     ▼                                                                      │
│  PostgreSQL (RLS) ◄── shared/events/ (PgEventStore + Redis Streams)        │
│     │                        ▲                                             │
│     │                        │ emit_event() 平行写入                        │
│     └── events 表 (v147) ────┘                                             │
│     └── mv_* 物化视图 (v148, 8 个)                                         │
│                                                                            │
│  缺口：                                                                    │
│  ❌ 事件总线无抽象层（Redis Streams 直接暴露给消费端）                     │
│  ❌ 事件 payload 无 Pydantic schema（dict 传输）                           │
│  ❌ Outbox Relay 无去重机制                                                │
│  ❌ 资金流预测仅"历史现金流表"，无"未来 N 天断流预警"                      │
│  ❌ 进项税用"假设倍率" — invoice_service.py 全电发票回填未完成            │
│  ❌ NLQuery 散落在 voice_orchestrator，无统一 Agent                        │
│  ❌ EvidenceBundle 溯源结构未形式化                                        │
└────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 目标（FCT 2.0）

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                       FCT 2.0 目标架构（Phase 5–7）                            │
├────────────────────────────────────────────────────────────────────────────────┤
│                     [企业微信 / web-admin / 小程序]                            │
│                                      │                                         │
│                                      ▼                                         │
│                         tx-agent:8008 (AgentOrchestrator)                      │
│    ┌─────────────────────────────────┼─────────────────────────────────┐       │
│    ▼                                 ▼                                 ▼       │
│  NLQueryAgent                 finance.plan_from_template           APScheduler │
│  (GLM-5.1 + reports)          ├─ EvidenceBundleAssembler           事件调度    │
│                               └─ 三条硬约束校验                                 │
│                                      │                                         │
│             ┌──────┬──────┬──────────┼──────────┬──────┬──────┐                 │
│             ▼      ▼      ▼          ▼          ▼      ▼      ▼                 │
│         CashFlow CostAnom InvoiceM TaxOptim ReconAg NLQuery AlertRule           │
│         Alert   aly       atch     izer     ent              DSL (5.5)          │
│             │      │      │          │          │      │                        │
│             └──────┴──────┴──────────┼──────────┴──────┘                        │
│                                      │                                          │
│                                      ▼                                          │
│    ┌─────────────── shared/events/bus/ (NEW) ──────────────────────┐            │
│    │   EventBus (抽象基类)                                          │            │
│    │   RedisStreamsEventBus / (未来) KafkaEventBus                  │            │
│    │   OntologySubscriber (Pydantic schema + RLS 注入)              │            │
│    │   EventRelay (PG outbox → Redis Streams，至少一次 + 去重)      │            │
│    └────────────────────────────────────────────────────────────────┘            │
│                                      ▲                                          │
│                 ┌────────────────────┴────────────────────┐                     │
│                 │                                         │                     │
│         shared/events/src/emitter.py              shared/events/src/consumer.py │
│         (改造：aggregate_id 必填)                 (改用 OntologySubscriber)     │
│                 │                                                               │
│                 ▼                                                               │
│              PostgreSQL (RLS)                                                   │
│               ├── events 表 (v147) + processed_events (NEW v265, 去重)          │
│               ├── event_outbox_cursor (NEW v265, Relay 游标)                    │
│               └── evidence_bundles (NEW v266, 溯源证据留痕)                     │
│                                                                                 │
│    ┌──────── shared/finance/ (NEW) ────────┐                                    │
│    │   constraints.py (三条硬约束)          │                                   │
│    │   metric_calculator.py (财务指标)      │                                   │
│    └────────────────────────────────────────┘                                   │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 数据流图（OrderPaid 事件 → 企微推送）

```
[收银 Order Paid]
      │
      │ emit_event(OrderEventType.PAID, aggregate_id=order_id, ...)
      ▼
┌──────────────┐       ┌─────────────────┐
│ PG events 表 │ ────→ │ Redis Streams    │  (双轨，现有)
│ (v147)       │       │ ontology.*       │
└──────┬───────┘       └────────┬─────────┘
       │                        │
       │                        │ XREADGROUP
       ▼                        ▼
┌─────────────────────────────────────────────┐
│   EventRelay (NEW, APScheduler, 每10s)      │
│   - 扫 events 表 where sequence_num > cursor│
│   - 批量 XADD + 写入 processed_events 去重  │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│   OntologySubscriber (NEW, Pydantic 校验)    │
│   - 按 aggregate_id 分区（同单有序）         │
│   - RLS 上下文注入（app.tenant_id）          │
└────┬──────────────┬─────────────────┬────────┘
     ▼              ▼                 ▼
[CashFlow]      [CostAnomaly]     [InvoiceMatch]
 Alert           Agent              Agent
     │               │                  │
     │ 聚合7天滚动  │ 对比BOM         │ 三流合一
     │ 预测现金流  │ 偏差>阈值       │ 匹配发票
     ▼               ▼                  ▼
┌──────────────────────────────────────────────┐
│   AgentOrchestrator                          │
│   - plan_from_template('finance.cashflow_*')  │
│   - synthesize() 产出 OrchestratorResult     │
│   - EvidenceBundleAssembler 装配             │
│   - 三条硬约束校验（shared/finance/constraints）│
└────────────────────────┬─────────────────────┘
                         │
                         ▼
                ┌────────────────────┐
                │ WeComSDK (已有)     │
                │ send_alert_card     │
                └─────────┬──────────┘
                          ▼
                  [老板企业微信推送]
```

### 1.4 模块依赖图

```
                 ┌────────────────────────┐
                 │  shared/events/src/     │ (现有)
                 │  - emitter (改造)       │
                 │  - pg_event_store       │
                 │  - event_types          │
                 └──────────┬──────────────┘
                            │
                            ▼
                 ┌────────────────────────┐
                 │  shared/events/bus/ (NEW)│
                 │  - event_bus.py (抽象)  │
                 │  - redis_bus.py         │
                 │  - subscriber.py        │
                 │  - relay.py             │
                 │  - evidence.py          │
                 └──────────┬──────────────┘
                            │
         ┌──────────────────┼────────────────────────┐
         ▼                  ▼                        ▼
┌────────────────┐ ┌────────────────────┐ ┌──────────────────────┐
│shared/events/  │ │ shared/finance/ NEW│ │shared/integrations/   │
│ schemas/ (NEW) │ │ - constraints.py    │ │ wecom_sdk.py (改造)   │
│ - base.py      │ │ - metric_calc.py    │ │                      │
│ - order_*.py   │ │                    │ │                      │
│ - invoice_*.py │ │                    │ │                      │
│ - finance_*.py │ │                    │ │                      │
└────────┬───────┘ └──────────┬─────────┘ └───────────┬──────────┘
         │                    │                       │
         └────────────────────┼───────────────────────┘
                              ▼
                services/tx-agent/src/agents/
                     ├ orchestrator.py (扩展 plan_from_template)
                     ├ skills/
                     │  ├ finance_audit.py (现有)
                     │  ├ cashflow_alert.py (NEW)
                     │  ├ cost_anomaly.py (NEW, Phase 5.5)
                     │  ├ invoice_match.py (NEW, Phase 6)
                     │  ├ tax_optimizer.py (NEW, Phase 6)
                     │  ├ recon_agent.py (NEW, Phase 6)
                     │  ├ nl_query.py (NEW)
                     │  └ finance_mixin.py (NEW, Evidence helpers)
                     └ plans/finance_plan_templates.py (NEW)
```

---

## §2 新增/改动文件清单

### 2.1 新建（20 个文件）

| 路径 | 用途 | 预计行数 |
|------|------|----------|
| `shared/events/bus/__init__.py` | 模块导出 | 20 |
| `shared/events/bus/event_bus.py` | `EventBus` 抽象基类 + `EventEnvelope` | 220 |
| `shared/events/bus/redis_bus.py` | `RedisStreamsEventBus` 实现 | 280 |
| `shared/events/bus/subscriber.py` | `OntologySubscriber`（订阅+校验+RLS） | 280 |
| `shared/events/bus/relay.py` | `EventRelay` PG → Redis outbox relay | 260 |
| `shared/events/bus/evidence.py` | `EvidenceBundle` + `EvidenceBundleAssembler` | 160 |
| `shared/events/schemas/__init__.py` | schema 包导出 | 20 |
| `shared/events/schemas/base.py` | `OntologyEvent` 基类 + 演进规则 | 110 |
| `shared/events/schemas/order_events.py` | 订单相关 Pydantic payload | 160 |
| `shared/events/schemas/invoice_events.py` | 发票相关 payload | 140 |
| `shared/events/schemas/finance_events.py` | 现金流/成本异常 payload | 180 |
| `shared/finance/__init__.py` | 模块导出 | 10 |
| `shared/finance/constraints.py` | 三条硬约束校验（方案丙共享） | 180 |
| `shared/finance/metric_calculator.py` | 财务指标计算（毛利/折扣/成本率） | 160 |
| `services/tx-agent/src/agents/skills/finance_mixin.py` | FinanceEvidenceMixin | 60 |
| `services/tx-agent/src/agents/skills/cashflow_alert.py` | CashFlowAlertAgent | 320 |
| `services/tx-agent/src/agents/skills/cost_anomaly.py` | CostAnomalyAgent (Phase 5.5) | 260 |
| `services/tx-agent/src/agents/skills/nl_query.py` | NLQueryAgent (GLM-5.1) | 280 |
| `services/tx-agent/src/agents/plans/__init__.py` | plans 包初始化 | 10 |
| `services/tx-agent/src/agents/plans/finance_plan_templates.py` | finance 域计划模板 | 180 |

Phase 6–7 的新增（invoice_match / tax_optimizer / recon_agent）在后续 Sprint 计划明细中展开。

### 2.2 迁移（2 个）

| 路径 | 用途 |
|------|------|
| `shared/db-migrations/versions/v265_ontology_outbox_cursor.py` | `event_outbox_cursor` + `processed_events` 表 |
| `shared/db-migrations/versions/v266_evidence_bundles.py` | `evidence_bundles` 表 |

### 2.3 改动（12 个文件）

| 路径 | 改动 | 影响范围 | Tier |
|------|------|----------|------|
| `shared/events/src/emitter.py` | **Tier 1**：新增 `aggregate_id` 参数（旧签名兼容，feature flag 灰度） | 现有 50+ emit_event 调用 | **T1** |
| `shared/events/src/pg_event_store.py` | append 后写 `event_outbox_cursor`；payload schema 校验钩子 | 主库写入路径 | T1 |
| `shared/events/src/event_types.py` | 新增 CashFlowEventType/TaxEventType/ReconciliationEventType | 新 Agent 订阅 | T2 |
| `services/tx-agent/src/agents/orchestrator.py` | 新增 `plan_from_template(name, context)`；synthesize 出参加 evidence_bundle | 所有编排调用方 | T2 |
| `services/tx-agent/src/agents/skills/finance_audit.py` | 拆出编排子 skill；委托 check_pl_anomaly 给 CashFlowAlertAgent；保留 18 actions 签名 | 现有调用方 | T2 |
| `services/tx-agent/src/agents/master.py` | 注册 6 个新子 Agent | Agent Catalog | T2 |
| `services/tx-agent/src/agents/domain_event_consumer.py` | 改用 `OntologySubscriber` | 事件消费路径 | T2 |
| `services/tx-agent/src/scheduler.py` | 新增 cashflow_daily_check 08:00 / ontology_relay_tick 10s 两个 job | Cron 表 | T2 |
| `services/tx-brain/src/services/cfo_dashboard.py` | 暴露"未来 7 天现金流预测"接口 | cfo 前端 | T2 |
| `services/tx-brain/src/agents/finance_auditor.py` | **不删**，按方案丙保留；复用 shared/finance 模块去除重复 | HTTP API 消费者 | T2 |
| `services/tx-agent/src/agents/model_router.py` | 扩展支持 `provider=zhipu + model=glm-5.1` | NLQueryAgent | T2 |
| `shared/integrations/wecom_sdk.py` | 新增 `send_alert_card(recipient, evidence_bundle_id)` 模板方法 | CashFlowAlert 推送 | T2 |

### 2.4 废弃（仅 1 条）

| 路径 | 废弃理由 | 迁移方案 |
|------|----------|----------|
| `finance_audit.agent_level=1` 的旧约束级别 | Phase 5 要求升级至 level 2（带 30min 回滚） | 按 `base.py` 已有 rollback 机制升级 |

---

## §3 接口契约（代码级定义）

### 3.1 EventEnvelope 与 EventBus 抽象基类

```python
# shared/events/bus/event_bus.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Optional
from uuid import UUID
from datetime import datetime

from shared.events.schemas.base import OntologyEvent


@dataclass(frozen=True)
class EventEnvelope:
    """统一事件信封：传输层无关。"""
    event_id: str                   # UUID
    aggregate_id: str               # 分区键（同聚合根事件有序）
    aggregate_type: str             # 'order' | 'invoice' | 'cashflow' | ...
    event_type: str                 # 点分字符串：order.paid / invoice.verified / ...
    tenant_id: UUID
    occurred_at: datetime
    schema_version: str             # '1.0' / '1.1' ...
    payload: OntologyEvent          # Pydantic 强类型
    causation_id: Optional[str] = None
    correlation_id: Optional[str] = None


class EventBus(ABC):
    """事件总线抽象。RedisStreamsEventBus 是第一实现；未来可换 Kafka。"""

    @abstractmethod
    async def publish(self, envelope: EventEnvelope, *, maxlen: int = 100_000) -> str: ...

    @abstractmethod
    async def subscribe(
        self,
        *,
        consumer_group: str,
        topics: list[str],
        handler: Callable[[EventEnvelope], Awaitable[None]],
        start_from: str = ">",        # ">" 新消息 | "0" 回放全部
    ) -> None: ...

    @abstractmethod
    async def replay(
        self,
        *,
        topic: str,
        after_event_id: Optional[str] = None,
        limit: int = 1000,
    ) -> AsyncIterator[EventEnvelope]: ...

    @abstractmethod
    async def ack(self, *, topic: str, consumer_group: str, event_id: str) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
```

### 3.2 EventStore（复用现有 events 表 + 新增辅助表）

```sql
-- v265_ontology_outbox_cursor.py
CREATE TABLE event_outbox_cursor (
    relay_name       TEXT PRIMARY KEY,
    last_event_id    UUID NOT NULL,
    last_sequence    BIGINT NOT NULL DEFAULT 0,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE processed_events (
    consumer_group   TEXT NOT NULL,
    event_id         UUID NOT NULL,
    tenant_id        UUID NOT NULL,
    processed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer_group, event_id)
);
CREATE INDEX idx_processed_tenant ON processed_events (tenant_id, processed_at DESC);

-- 启用 RLS
ALTER TABLE processed_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_processed_events ON processed_events
    USING (tenant_id::text = current_setting('app.tenant_id', TRUE));
```

```sql
-- v266_evidence_bundles.py
CREATE TABLE evidence_bundles (
    bundle_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    decision_type     TEXT NOT NULL,
    severity          TEXT NOT NULL,            -- 'info' | 'warning' | 'critical'
    recommendation    TEXT,
    voucher_ids       TEXT[] NOT NULL DEFAULT '{}',
    order_ids         TEXT[] NOT NULL DEFAULT '{}',
    invoice_ids       TEXT[] NOT NULL DEFAULT '{}',
    bank_txn_ids      TEXT[] NOT NULL DEFAULT '{}',
    event_ids         UUID[] NOT NULL DEFAULT '{}',
    reasoning_chain   JSONB NOT NULL DEFAULT '[]'::jsonb,
    mv_snapshots      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_evidence_tenant_created ON evidence_bundles (tenant_id, created_at DESC);
CREATE INDEX idx_evidence_decision_type ON evidence_bundles (decision_type);

ALTER TABLE evidence_bundles ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_evidence_bundles ON evidence_bundles
    USING (tenant_id::text = current_setting('app.tenant_id', TRUE));
```

### 3.3 EventRelay（APScheduler job）

```python
# shared/events/bus/relay.py
class EventRelay:
    """PG events → EventBus 的 outbox relay.

    运行节奏：APScheduler，每 10 秒一次。
    语义：至少一次；以 processed_events 表去重。
    """
    def __init__(self, bus: EventBus, *, batch: int = 500, relay_name: str = "ontology_relay_default"):
        self._bus = bus
        self._batch = batch
        self._name = relay_name

    async def run_once(self) -> int:
        async with _pg_pool.acquire() as conn:
            async with conn.transaction():
                cursor = await conn.fetchrow(
                    "SELECT last_sequence FROM event_outbox_cursor "
                    "WHERE relay_name=$1 FOR UPDATE SKIP LOCKED",
                    self._name,
                )
                last_seq = (cursor or {}).get("last_sequence", 0)

                rows = await conn.fetch(
                    """SELECT event_id, sequence_num, tenant_id, stream_type, stream_id,
                              event_type, occurred_at, payload, causation_id, correlation_id,
                              schema_version
                       FROM events
                       WHERE sequence_num > $1
                       ORDER BY sequence_num ASC
                       LIMIT $2""",
                    last_seq, self._batch,
                )
                if not rows:
                    return 0

                forwarded = 0
                for r in rows:
                    envelope = _row_to_envelope(r)
                    try:
                        await self._bus.publish(envelope)
                        forwarded += 1
                    except Exception as exc:
                        logger.error("relay_publish_failed",
                                     event_id=str(r["event_id"]), error=str(exc))
                        break

                if forwarded:
                    await conn.execute(
                        """UPDATE event_outbox_cursor
                           SET last_sequence=$1, last_event_id=$2, updated_at=now()
                           WHERE relay_name=$3""",
                        rows[forwarded - 1]["sequence_num"],
                        rows[forwarded - 1]["event_id"],
                        self._name,
                    )
                return forwarded
```

### 3.4 OntologyEvent 基类 + 三示例 schema

```python
# shared/events/schemas/base.py
from pydantic import BaseModel, ConfigDict
from typing import ClassVar

class OntologyEvent(BaseModel):
    """所有 ontology 事件 payload 的基类。

    演进规则 "只加不改"：
      - 新增字段必须 Optional 或带默认值
      - 不删字段（弃用字段保留 + 文档标注 deprecated）
      - 字段类型不可变更
      - 破坏性变更 → 改 schema_version 主版本 + 启用新 topic
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: ClassVar[str] = "1.0"


# shared/events/schemas/order_events.py
class OrderCreatedPayload(OntologyEvent):
    order_id: str
    store_id: str
    total_fen: int  # 总金额（分），>= 0
    table_id: str | None = None
    created_by: str


class OrderPaidPayload(OntologyEvent):
    order_id: str
    store_id: str
    total_fen: int
    paid_fen: int
    payment_method: str  # 'wechat' | 'alipay' | 'cash' | ...
    channel: str         # 'dine_in' | 'takeout' | 'delivery'


# shared/events/schemas/invoice_events.py
class InvoiceVerifiedPayload(OntologyEvent):
    invoice_no: str
    supplier_tax_id: str
    amount_fen: int
    tax_fen: int
    invoice_type: str                       # 'fully_electronic' | 'paper'
    verified_at: str                        # ISO8601
    three_way_match_id: str | None = None


# shared/events/schemas/finance_events.py
class CashFlowSnapshotPayload(OntologyEvent):
    store_id: str
    snapshot_date: str                      # YYYY-MM-DD
    cash_on_hand_fen: int
    projected_7d_inflow_fen: int
    projected_7d_outflow_fen: int
    days_until_dry: int | None              # None 表示 > 30 天
    confidence: float                       # 0.0–1.0
```

### 3.5 Orchestrator 扩展（非新建类）

```python
# services/tx-agent/src/agents/orchestrator.py (增量补丁)
class AgentOrchestrator:
    ...
    async def plan_from_template(
        self,
        template_name: str,          # 'finance.cashflow_alert' | 'finance.month_end' | ...
        context: dict,
    ) -> ExecutionPlan:
        """基于模板直出 ExecutionPlan，跳过 LLM 规划。"""
        tpl = FINANCE_PLAN_TEMPLATES[template_name]
        return tpl.build(context, tenant_id=self.tenant_id, store_id=self.store_id)

    async def synthesize(self, plan: ExecutionPlan, results: list[AgentResult]) -> OrchestratorResult:
        """(改动) 输出附带 evidence_bundle。"""
        bundle = EvidenceBundleAssembler.assemble(plan, results)
        # 原三条硬约束校验逻辑不变
        return OrchestratorResult(
            plan_id=plan.plan_id,
            ...,
            evidence_bundle=bundle,   # NEW
        )
```

### 3.6 CashFlowAlertAgent

```python
# services/tx-agent/src/agents/skills/cashflow_alert.py
from ..base import SkillAgent, AgentResult, ActionConfig
from .finance_mixin import FinanceEvidenceMixin

class CashFlowAlertAgent(SkillAgent, FinanceEvidenceMixin):
    agent_id = "cashflow_alert"
    agent_name = "资金断流预警"
    description = "滚动 7 天预测现金流；断流/风险时主动推送企微"
    priority = "P0"
    run_location = "cloud"
    agent_level = 1                      # Phase 5 仅建议；Phase 5.5 升 2
    constraint_scope = {"margin"}        # 仅涉及毛利底线相关告警
    constraint_waived_reason = None

    def get_supported_actions(self) -> list[str]:
        return [
            "compute_cashflow_snapshot",
            "evaluate_dryness_risk",
            "push_alert",
        ]

    def get_action_config(self, action):
        return {
            "push_alert": ActionConfig(risk_level="high", requires_human_confirm=False),
        }.get(action, ActionConfig(risk_level="low"))

    async def execute(self, action: str, params: dict) -> AgentResult:
        if action == "compute_cashflow_snapshot":
            return await self._compute_snapshot(params)
        if action == "evaluate_dryness_risk":
            return await self._evaluate_risk(params)
        if action == "push_alert":
            return await self._push(params)
        return AgentResult(success=False, action=action, error=f"unsupported:{action}")
```

### 3.7 EvidenceBundle 数据结构

```python
# shared/events/bus/evidence.py
from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from datetime import datetime

class EvidenceBundle(BaseModel):
    bundle_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)

    voucher_ids: list[str] = Field(default_factory=list)
    order_ids: list[str] = Field(default_factory=list)
    invoice_ids: list[str] = Field(default_factory=list)
    bank_txn_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    mv_snapshots: dict[str, str] = Field(default_factory=dict)

    reasoning_chain: list[dict] = Field(default_factory=list)
    # { "step": int, "agent": str, "action": str,
    #   "input_summary": str, "output_summary": str, "confidence": float }

    decision_type: str
    recommendation: str = ""
    severity: str = "info"    # 'info' | 'warning' | 'critical'
```

---

## §4 WBS 任务拆解

Phase 5 粒度 2–4 人日；Phase 6/7 粒度 5–8 人日。任务 ID 格式：T{Phase}.{Sprint}.{Seq}。

### 4.1 Phase 5（Month 1–2）：骨架 + CashFlowAlertAgent + NLQueryAgent

#### Sprint 1（Week 1–2）：Ontology 总线基础设施

| 任务 ID | 任务名 | 模块 | 工期 | 前置 | 验收 | 风险 | Tier |
|---|---|---|---|---|---|---|---|
| **T5.1.1** | 编写 EventBus 抽象基类 + EventEnvelope | `shared/events/bus/event_bus.py` | 2 | — | mypy --strict 零错误；pytest 单测覆盖率 ≥90% | 低 | T2 |
| **T5.1.2** | 实现 RedisStreamsEventBus（publish/subscribe/ack/replay） | `shared/events/bus/redis_bus.py` | 3 | T5.1.1 | 单测 ≥85%；publish→subscribe 本地回环 ≤20ms | 中：consumer-group 异常处理 | T2 |
| **T5.1.3** | 定义 OntologyEvent 基类 + 三示例 schema | `shared/events/schemas/` | 2 | — | Pydantic 校验 + version 演进规则单测 | 低 | T2 |
| **T5.1.4** | 迁移 v265：event_outbox_cursor + processed_events | `shared/db-migrations/versions/v265_*.py` | 1 | — | alembic upgrade/downgrade 双向可逆；RLS 单测 | 低 | T2 |
| **T5.1.5** | 实现 EventRelay + APScheduler 注册 | `shared/events/bus/relay.py` + `tx-agent/src/scheduler.py` | 3 | T5.1.2/T5.1.4 | 1000 事件 60s 内 100% 推达 Redis；幂等 | 中：Relay 停机恢复 | T2 |
| **T5.1.6** | 实现 OntologySubscriber（Pydantic 反序列化 + RLS 注入） | `shared/events/bus/subscriber.py` | 3 | T5.1.2/T5.1.3 | 异常路由 DLQ；per-aggregate_id 保序 | 中：保序↔并发权衡 | T2 |
| **T5.1.7** | **TDD 改造 emitter.py**（aggregate_id 兼容层 + feature flag） | `shared/events/src/emitter.py` | 2 | T5.1.3 | 现有单测全绿；14 微服务 grep 无破坏 | **高** | **T1** |
| **T5.1.8** | 改造 domain_event_consumer.py 用 OntologySubscriber | `tx-agent/src/agents/domain_event_consumer.py` | 2 | T5.1.6 | 现有 event-driven action 回归通过 | 中 | T2 |
| **T5.1.9** | EventBus + Relay 集成测试（Docker compose） | `tests/integration/test_ontology_bus_e2e.py` | 2 | T5.1.1–T5.1.7 | ORDER.PAID → Subscriber 全链路 ≤2s | 中 | T2 |
| **T5.1.10** | 提取 shared/finance/constraints.py + metric_calculator.py（方案丙） | `shared/finance/*.py` | 3 | — | tx-agent/tx-brain 两侧均调用新模块；删除重复代码 | 低 | T2 |

**Sprint 1 合计**：23 人日。里程碑：抽象总线层上线，所有新 Agent 只订阅抽象层，不直连 Redis。

#### Sprint 2（Week 3–4）：Orchestrator + CashFlowAlertAgent

| 任务 ID | 任务名 | 工期 | 前置 | 验收 | 风险 |
|---|---|---|---|---|---|
| T5.2.1 | EvidenceBundle + Assembler | 2 | T5.1.3 | 3 典型装配场景单测 |
| T5.2.2 | 迁移 v266：evidence_bundles | 1 | — | RLS + 索引齐全 |
| T5.2.3 | Orchestrator.plan_from_template + 计划模板注册表 | 3 | — | `finance.cashflow_alert` 模板可跑 |
| T5.2.4 | Orchestrator.synthesize 携带 EvidenceBundle | 2 | T5.2.1 | bundle_id 在 bundles 表可查 |
| T5.2.5 | CashFlowAlertAgent: compute_cashflow_snapshot | 4 | T5.2.1 | 尝在一起 30 天真实数据 MAE < 20% |
| T5.2.6 | CashFlowAlertAgent: evaluate_dryness_risk | 2 | T5.2.5 | days < 7 critical；< 14 warning |
| T5.2.7 | CashFlowAlertAgent: push_alert + WeCom 模板 | 3 | T5.2.6 | 模板含 days/证据链 URL/查原因按钮 |
| T5.2.8 | scheduler: cashflow_daily_check 08:00 cron | 1 | T5.2.7 | 每日触发；失败告警 |
| T5.2.9 | CashFlowAlertAgent 单测（覆盖率 ≥85%） | 3 | T5.2.5–7 | MAE/保序/幂等/降级 覆盖 |
| T5.2.10 | Orchestrator + CashFlow 集成测试 | 2 | T5.2.7/T5.2.4 | ORDER.PAID → 企微收到 ≤30s |

**Sprint 2 合计**：23 人日。里程碑：首次资金断流预警从尝在一起真实租户发出到企微 Bot。

#### Sprint 3（Week 5–6）：NLQueryAgent（GLM-5.1）+ 验收

| 任务 ID | 任务名 | 工期 | 前置 | 验收 |
|---|---|---|---|---|
| T5.3.0 | model_router 接入 GLM-5.1（zhipuai SDK） | 2 | — | provider=zhipu 路由单测通过 |
| T5.3.1 | NLQueryAgent v0.1：GLM-5.1 function calling 意图识别 | 3 | T5.3.0 | 10 个常问场景意图准确率 ≥85% |
| T5.3.2 | NLQueryAgent: 参数槽位抽取（时间/门店/指标） | 3 | T5.3.1 | "本月徐家井店利润"→ 正确槽位 |
| T5.3.3 | NLQueryAgent: 调用 tx-finance/tx-analytics 报表 API | 2 | T5.3.2 | 路由到 finance_pl_routes / reports_router |
| T5.3.4 | NLQueryAgent: 结果摘要化（GLM-5.1 二次总结 3 句话） | 2 | T5.3.3 | Markdown 格式适配企微 |
| T5.3.5 | 企微 sidebar 接入 NLQueryAgent | 3 | T5.3.4 | sidebar 输入问题 30s 内有答（前端用 tx-ui 技能）|
| T5.3.6 | Phase 5 验收：尝在一起真实数据回放 | 3 | T5.3.5/T5.2.10 | §9 KR 全绿 |
| T5.3.7 | 文档：docs/fct2_phase5_handbook.md + Runbook | 2 | — | 注册/回滚/告警响应 SOP |

**Sprint 3 合计**：20 人日。里程碑（= Phase 5 Exit）：
- 老板企微问"本月各店利润"30s 内拿到答案
- 资金预警在真实租户发出
- 每个决策留下完整 EvidenceBundle

**Phase 5 总工期**：Sprint 1 (23) + Sprint 2 (23) + Sprint 3 (20) = **66 人日**，含 10% buffer 约 **73 人日**；2 人全职并行 **约 7 周**（W1–W7）。

### 4.2 Phase 5.5（Week 8）：预警规则 DSL + CostAnomaly

| 任务 ID | 任务名 | 工期 |
|---|---|---|
| T5.5.1 | JSON Schema 规则 DSL 定义 + 解析器 | 3 |
| T5.5.2 | 规则评估引擎（and/or/阈值/窗口聚合） | 5 |
| T5.5.3 | web-admin 低代码配置 UI（tx-ui 技能） | 6 |
| T5.5.4 | CostAnomalyAgent：订阅 InventoryEvent + 对比 BOM | 5 |
| T5.5.5 | CostAnomaly + DSL 联动 | 3 |
| T5.5.6 | Phase 5.5 验收 | 2 |

Phase 5.5 合计 24 人日，2 周（W8–W9）。

### 4.3 Phase 6（Month 3–4）：四流真实闭环

| 任务 ID | 任务名 | 工期 |
|---|---|---|
| T6.1 | InvoiceMatchAgent 架构 + 三流合一匹配算法 | 8 |
| T6.2 | 全电发票对接（航信/百望 API 适配器） | 8 |
| T6.3 | 发票 XML 解析 + 自动入账（改造 invoice_service.py） | 6 |
| T6.4 | ReconAgent：银企直连事件消费 + 对账匹配引擎 | 8 |
| T6.5 | 银企直连 SDK（建行/招商/工行三选一 POC） | 6 |
| T6.6 | TaxOptimizerAgent：月结 cron + 申报表取数 | 6 |
| T6.7 | 改造 vat_service.py：从"假设倍率"到真实数据 | 5 |
| T6.8 | Phase 6 验收（VAT 误差 < 2%，申报 < 1h） | 3 |

Phase 6 合计 50 人日，约 10 周（含并行）。

### 4.4 Phase 7（Month 5–6）：驾驶舱 + 可复制化

| 任务 ID | 任务名 | 工期 |
|---|---|---|
| T7.1 | CFO 驾驶舱前端（嵌入"追问 AI" NLQueryAgent，tx-ui 技能） | 8 |
| T7.2 | 合并报表引擎（多主体 GroupBy 聚合） | 8 |
| T7.3 | 预算智能优化 Agent | 6 |
| T7.4 | 标准化部署包（Helm + Ansible） | 6 |
| T7.5 | Phase 7 验收（徐记 FCT ROI > 500%） | 5 |

Phase 7 合计 33 人日，约 6 周。

---

## §5 Sprint 规划

| Sprint | 周次 | 目标 | 关键任务 | Demo 标准 |
|---|---|---|---|---|
| **S1** | W1–W2 | Ontology 总线 + 方案丙共享模块 | T5.1.1–T5.1.10 | 录屏：ORDER.PAID 事件跨 Relay 到达 Subscriber，Pydantic 反序列化成功，全链路 ≤2s |
| **S2** | W3–W4 | Orchestrator 模板化 + CashFlowAlertAgent | T5.2.1–T5.2.10 | 尝在一起早 08:00 收到"某店 5 天内可能断流"企微推送，点击卡片可看 EvidenceBundle |
| **S3** | W5–W7 | NLQueryAgent（GLM-5.1）+ Phase 5 验收 | T5.3.0–T5.3.7 | 老板 sidebar 问 10 题至少 8 题 30 秒内答出 |
| **S4** | W8–W9 | Phase 5.5：DSL + CostAnomaly | T5.5.* | 老板自定义规则次日触发 |
| **S5–S8** | W10–W17 | Phase 6：四流闭环 | T6.* | 发票匹配自动率 ≥85%；银行流水自动对账 |
| **S9–S12** | W18–W24 | Phase 7：驾驶舱 + 标准化 | T7.* | 尝在一起 → 徐记一键部署 |

---

## §6 测试策略

### 6.1 单测

- 覆盖率门槛：
  - `shared/events/bus/*`: **≥90%**
  - 每个新 SkillAgent：**≥85%**
  - `Orchestrator.plan_from_template` / `synthesize`: **≥90%**
- 工具：`pytest` + `pytest-asyncio` + `pytest-cov`
- Mock：Redis 用 `fakeredis`；PG 用 `testcontainers-postgres` + `alembic upgrade head`；GLM API mock 返回 function_call JSON
- **Tier 1 TDD**：T5.1.7 emitter 改造必须测试先行，用例基于真实场景（§20）：
  ```python
  def test_emit_event_backward_compat_without_aggregate_id():
      """未提供 aggregate_id 时从 stream_id 推导，不破坏现有 50+ 调用点"""
  def test_emit_event_aggregate_id_preserves_order_partition():
      """同一 aggregate_id 的事件在 Redis Stream 上严格有序"""
  def test_emit_event_feature_flag_strict_mode_rejects_missing_aggregate_id():
      """ONTOLOGY_V2_STRICT=true 时缺失 aggregate_id 立即报错"""
  ```

### 6.2 集成测试

- `tests/integration/test_ontology_bus_e2e.py`：OrderPaid 跨全链路
- `tests/integration/test_fct2_cashflow_flow.py`：完整预警端到端
- `tests/integration/test_nlquery_intent_coverage.py`：10 个标注问题
- CI：Docker Compose 起 `postgres + redis + tx-agent + tx-finance + tx-brain`，执行 E2E

### 6.3 验收测试（尝在一起真实数据）

- **数据源**：尝在一起生产 orders/payments（签 DPA 后）
- **脱敏**：tenant_id 换 UUID；employee_id pseudo-id；手机/身份证 SHA-256；金额原值保留
- **回放脚本**：`scripts/replay_tenant_events.py`（新增）：PG events 按 occurred_at 等比例压缩到 2 小时

---

## §7 基础设施变更

### 7.1 数据库迁移

详见 §3.2。v265 + v266 须在 Sprint 1 / Sprint 2 开头完成。

### 7.2 Redis 配置

- 每个 topic `XADD ... MAXLEN ~ 100000`（约 10 万条滚动）
- 金税四期 7 年留痕由 PG events 承担，不依赖 Redis
- 新增 ENV：
  ```bash
  ONTOLOGY_BUS_URL=redis://localhost:6379/1
  ONTOLOGY_TOPIC_PREFIX=ontology
  ONTOLOGY_RELAY_INTERVAL_SEC=10
  ONTOLOGY_RELAY_BATCH=500
  ONTOLOGY_V2_STRICT=false           # Sprint 1 默认 false；Sprint 3 切 true
  ```

### 7.3 调度

不引入 Celery（屯象OS 栈无 Celery）。使用现有 `services/tx-agent/src/scheduler.py`（APScheduler），新增：

- `ontology_relay_tick` → 每 10s
- `cashflow_daily_check` → 08:00
- `invoice_match_hourly` → 每整点（Phase 6）
- `tax_optimizer_monthend` → 每月 1 号 03:00（Phase 6）

### 7.4 环境变量（全量）

```bash
# Ontology 总线
ONTOLOGY_BUS_URL=redis://localhost:6379/1
ONTOLOGY_TOPIC_PREFIX=ontology
ONTOLOGY_RELAY_INTERVAL_SEC=10
ONTOLOGY_RELAY_BATCH=500
ONTOLOGY_V2_STRICT=false

# CashFlow
CASHFLOW_DRY_DAYS_CRITICAL=7
CASHFLOW_DRY_DAYS_WARNING=14
CASHFLOW_ALERT_WECOM_AGENT_ID=<待创始人同步>
CASHFLOW_ALERT_WECOM_RECIPIENTS=<待同步>

# NLQuery (GLM-5.1)
NLQUERY_LLM_PROVIDER=zhipu
NLQUERY_LLM_MODEL=glm-5.1
NLQUERY_LLM_TIMEOUT_SEC=20
NLQUERY_MAX_INTENT_TOKENS=500
ZHIPUAI_API_KEY=<待同步>
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/

# Evidence
EVIDENCE_RETENTION_DAYS=2555   # 7 年金税四期
```

---

## §8 风险与对冲（Top 5）

| # | 风险 | 概率 | 影响 | 对冲 |
|---|---|---|---|---|
| **R1** | emitter.py 改造影响现有 50+ 调用点 | 高 | 高 | (1) `aggregate_id` 默认从 `stream_id` 推导；(2) feature flag `ONTOLOGY_V2_STRICT` 灰度；(3) TDD 先行；(4) staging 压力测 24h |
| **R2** | 尝在一起数据稀疏，资金预测 MAE 不达标 | 中 | 高 | (1) 先用 `demo-xuji-seafood.sql` 预训练；(2) MAE 不达标时降级为"账面 + 固定支出"，confidence 打 0.5 并在 UI 标注"样本不足"；(3) Phase 5.5 升级到"多店聚合 + 行业基准" |
| **R3** | GLM-5.1 function calling schema 约束能力弱导致意图识别幻觉 | 高 | 中 | (1) Sprint 3 首周做 spike 验证；(2) 失败降级为"LLM + 正则后处理"；(3) 门店名模糊匹配置信度 <0.9 反问；(4) 答案必带 EvidenceBundle 让老板可复核 |
| **R4** | Outbox Relay 停机恢复时批量重放雷击消费端 | 中 | 中 | (1) 单 tick 硬上限 500；(2) Subscriber consumer-group + XPENDING 背压；(3) Redis MAXLEN ~100k；(4) Runbook：停机 >10min 需先 pause Relay |
| **R5** | EvidenceBundle 7 年留痕存储膨胀 | 低 | 中 | (1) `evidence_bundles` 按月分区；(2) 冷数据压缩到 COS/S3；(3) mv_snapshots 存 hash 引用而非内容 |

---

## §9 验收指标

### Phase 5 KR（Exit @ W7）
- 资金预测准确率 MAE < 20%
- Agent 主动推送：每店 ≥1 条/日有效预警（非噪声）
- 老板 NL 查询满意度：10 题抽测 ≥8 题达 4/5 星
- Orchestrator 全链路 p95 ≤ 3s

### Phase 5.5 KR（Exit @ W9）
- DSL 规则命中率：老板自定义规则 72h 内 ≥1 次触发
- CostAnomaly 召回率：真实成本异常事件召回 ≥70%

### Phase 6 KR（Exit @ Month 4）
- 月度 VAT 误差 < 2%
- 申报准备时间：1 天 → < 1 小时
- 三流合一匹配自动率 ≥85%

### Phase 7 KR（Exit @ Month 6）
- 徐记 FCT ROI > 500%
- 新客部署时间 < 2 周

---

## §10 开工前 Checklist

| # | 事项 | 负责 | 截止 | 状态 |
|---|---|---|---|---|
| 1 | 尝在一起真实数据 DPA 签署 | 创始人 | Sprint 1 | ⏳ |
| 2 | 徐记海鲜 demo 种子（`demo-xuji-seafood.sql`）继续用 | 已备 | — | ✅ |
| 3 | 企微 Bot 凭证（CORP_ID / AGENT_ID / 模板审批） | 运营 | Sprint 2 中 | ⏳ 后续同步 |
| 4 | GLM-5.1 API 配额（`ZHIPUAI_API_KEY`） | 财务 | Sprint 3 开工前 | ⏳ |
| 5 | Redis 集群升级评估（是否需独立 Redis） | 基础设施 | Sprint 1 | ⏳ |
| 6 | 银企直连 POC 立项（建/招/工 三选一） | BD | W6 | ⏳ Phase 6 前 |
| 7 | 航信/百望 发票 API 合作账号 | BD | W10 | ⏳ Phase 6 前 |
| 8 | 数据脱敏规则签字 | 创始人 + 法务 | Sprint 1 | ⏳ |
| 9 | Phase 5 验收评审人（尝在一起店长/财务） | 创始人 | Sprint 3 中 | ⏳ |
| 10 | **Tier 1 emitter.py 改造 TDD 授权** | 创始人 | — | ✅ 已授权 |
| 11 | Mac mini 边缘侧 CashFlow 本地副本评估 | 产品 | Sprint 2 中 | ⏳ 默认否 |
| 12 | 双 finance_agent 方案丙确认 | 创始人 | Sprint 1 | ✅ 已确认 |

---

## 附录 A：实现偏差（相对早期构想）

- 原构想 "tx-brain/finance_auditor 完全废弃" → 按 **方案丙** 保留，通过 `shared/finance/` 提共享
- 原构想 "Celery Beat EventRelay" → 改 **APScheduler job**（屯象OS 栈无 Celery）
- 原构想 "独立 FctOrchestrator" → 改 **扩展现有 AgentOrchestrator 的 `plan_from_template`**（避免双实现）
- 原构想 "packages/ontology/" → 改 **`shared/events/bus/` + `shared/events/schemas/`**（CLAUDE.md §18 冻结）
- 原构想 "Claude Haiku" → 改 **GLM-5.1**（境内合规 + 中文财税语义优势 + 成本低）
- 原构想 "首客尚宫厨" → 改 **尝在一起**

---

**文档版本：v1.0 / 生成时间：2026-04-18**
