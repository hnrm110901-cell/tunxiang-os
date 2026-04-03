# Phase 1 供应链数据接入层技术设计方案

**版本**: v1.0
**日期**: 2026-03-31
**作者**: 屯象OS 架构预研
**状态**: 待创始人确认后实施

---

## 一、探索结论：现有供应链能力盘点

### 已有（tx-supply/src）
| 能力 | 文件 | 状态 |
|------|------|------|
| 采购全流程状态机（请购→审批→下单→收货→验收→入库） | `services/procurement_service.py` | 服务函数完整，无 DB 持久化 |
| 收货验收单 + 退货 + 门店调拨 | `services/receiving_service.py` | 有 DB 写入（receiving_orders/receiving_items 表），完整 |
| 盘点服务（开单→录入→结单→调整） | `services/stocktake_service.py` | 内存缓存（_stocktakes dict），DB 只写 IngredientTransaction 调整记录，未建 stocktakes 表 |
| 移库/拆组/BOM拆分 | `services/warehouse_ops.py` | 服务函数完整，无 DB 持久化 |
| 供应商管理 + 五维度评分 + 比价 + 合同 + 价格情报 | `services/supplier_portal_service.py` | 内存存储，无 DB 持久化 |
| 金蝶凭证导出桥接 | `services/kingdee_bridge.py` | 依赖 inventory_transactions / erp_export_history 表，完整 |
| 中央厨房生产计划 | `models/production_plan.py` | 数据模型完整，SQL Schema 已注释，未建 Alembic 迁移 |
| 智能补货建议 | `services/smart_replenishment.py` | 完整 |
| 奥琦玮适配器 | `shared/adapters/aoqiwei/src/adapter.py` | 签名认证完整，支持采购单/供应商/库存/配送接口，无数据映射层 |
| 品智库存同步 | `shared/adapters/pinzhi/src/inventory_sync.py` | 有降级策略，无 to_supplier / to_purchase_order 映射 |

### 缺失（Phase 1 需要补充）
1. **奥琦玮/品智采购数据接入**：适配器有，但缺少 `to_purchase_order` / `to_supplier` / `to_receiving` 标准映射函数，缺同步服务
2. **WMS 数据库表**：stocktakes/warehouse_transfers/stocktake_items 等表只存在于内存或注释中，未写 Alembic 迁移
3. **供应商评分引擎**：五维度评分逻辑在内存类中，未与 DB 数据打通，未接入 AI
4. **巡店管理模块**：完全缺失

---

## 二、采购数据接入适配器设计

### 2.1 设计原则

复用现有 POS 适配层的三层架构：
```
原始 API 调用层 (adapter._request)
      ↓
字段映射层 (mapper: raw → UnifiedPurchaseOrder / UnifiedSupplier)
      ↓
同步服务层 (sync_service: UPSERT 到 DB，tenant_id 隔离)
```

参考 `shared/adapters/pinzhi/src/order_sync.py` + `tunxiang-api/modules/gateway/integrations/pos_sync_service.py` 模式。

### 2.2 奥琦玮供应链适配器补充

**文件位置**: `shared/adapters/aoqiwei/src/supply_mapper.py`（新增）

现有 `AoqiweiAdapter` 已实现：
- `query_purchase_orders(start_date, end_date, depot_code)` → 采购入库单列表
- `query_suppliers(supplier_code, page)` → 供应商列表
- `query_delivery_dispatch_out(start_date, end_date, shop_code)` → 配送出库单（即收货记录来源）

**需要新增的映射函数接口定义**：

```python
# shared/adapters/aoqiwei/src/supply_mapper.py

def aoqiwei_supplier_to_unified(raw: dict, tenant_id: str) -> UnifiedSupplier:
    """奥琦玮供应商 → 标准 UnifiedSupplier

    奥琦玮字段: supplierCode, supplierName, contactName, contactPhone,
               supplierAddress, supplierStatus, categoryList
    映射规则:
      - external_id = raw["supplierCode"]
      - source = "aoqiwei"
      - is_active = (raw["supplierStatus"] == 1)
      - categories = raw.get("categoryList", [])
    """
    ...

def aoqiwei_purchase_order_to_unified(raw: dict, tenant_id: str, store_id: str) -> UnifiedPurchaseOrder:
    """奥琦玮采购入库单 → 标准 UnifiedPurchaseOrder

    奥琦玮字段: orderNo, depotCode, supplierCode, orderDate,
               totalAmount(分), status(0待确认/1已确认/2已入库),
               goodList[{goodCode, goodName, qty, unit, price}]
    映射规则:
      - external_id = raw["orderNo"]
      - source = "aoqiwei"
      - total_amount = raw["totalAmount"]  # 已是分，不需转换
      - status: {0: "ordered", 1: "received", 2: "stocked"}
      - items = [{ingredient_id: goodCode, name: goodName, ...}]
    """
    ...

def aoqiwei_dispatch_to_receiving(raw: dict, tenant_id: str, store_id: str) -> dict:
    """奥琦玮配送出库单 → 收货记录格式（对接 receiving_service.create_receiving）

    奥琦玮字段: dispatchOrderNo, shopCode, dispatchDate,
               goodList[{goodCode, goodName, qty, unit, price}]
    """
    ...
```

### 2.3 品智采购适配器补充

品智 POS 本身不是采购系统，但其库存/食材数据需要接入。

**文件位置**: `shared/adapters/pinzhi/src/supply_sync.py`（新增）

需要补充：
```python
def pinzhi_ingredient_to_unified(raw: dict, store_id: str, tenant_id: str) -> UnifiedIngredient:
    """品智食材 → 标准 UnifiedIngredient
    品智字段: materialId, materialName, unit, categoryName, specification
    """
    ...
```

注意：品智无采购单接口，采购数据来源以奥琦玮为主，品智仅提供食材主档同步。

### 2.4 采购数据同步服务

**文件位置**: `services/tx-supply/src/services/procurement_sync_service.py`（新增）

```python
class ProcurementSyncService:
    """采购数据定时同步 — 奥琦玮 → 屯象OS DB

    同步策略：
    - 增量同步：每次拉取过去 N 天的数据（默认 1 天）
    - 全量回填：支持指定日期范围
    - UPSERT 语义：以 (tenant_id, source, external_id) 为唯一键
    - 失败重试：最多 3 次指数退避
    """

    async def sync_suppliers(self, tenant_id: str, merchant_code: str) -> SyncResult:
        """同步供应商主档"""
        ...

    async def sync_purchase_orders(
        self,
        tenant_id: str,
        merchant_code: str,
        start_date: str,
        end_date: str,
    ) -> SyncResult:
        """同步采购入库单，写入 purchase_orders 表"""
        ...

    async def sync_receiving_records(
        self,
        tenant_id: str,
        merchant_code: str,
        start_date: str,
        end_date: str,
    ) -> SyncResult:
        """同步收货记录（从奥琦玮配送出库单转换），写入 receiving_orders 表"""
        ...
```

**同步触发方式**（两种，都需要）：
1. **定时任务**：每日凌晨 2:00 自动同步前一天数据（接入 tx-supply 的 APScheduler）
2. **手动触发**：通过 API `POST /api/v1/supply/sync/procurement` 触发，支持日期范围参数

### 2.5 多系统适配模式

当客户同时有奥琦玮和品智时（如尝在一起），采用**统一入口 + 按 source 路由**：

```
POST /api/v1/supply/sync/procurement
  X-Tenant-ID: {tenant_id}
  Body: {source: "aoqiwei"|"pinzhi", start_date, end_date}
```

内部由 `AdapterRegistry`（已有 `shared/adapters/base/src/registry.py`）根据 source 选择对应适配器，保持扩展性。

---

## 三、WMS 缺失表结构设计

### 3.1 现状分析

| 已有表（有实际 DB 写入的） | 注释/内存存储（需建表） |
|---|---|
| `receiving_orders` + `receiving_items` | `stocktakes` + `stocktake_items`（内存缓存） |
| `ingredient_transactions`（调整流水） | `warehouse_transfers`（移库单，无持久化） |
| `purchase_orders`（supply_chain_ext 引用） | `supplier_profiles`（供应商，内存 dict） |
| `suppliers`（supply_chain_ext 引用） | `purchase_order_snapshots`（采购快照） |

### 3.2 需要新增的表

#### 表1: `stocktakes`（盘点单头表）

```sql
CREATE TABLE stocktakes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    store_id        UUID NOT NULL REFERENCES stores(id),
    stocktake_no    VARCHAR(30) NOT NULL UNIQUE,  -- ST20260331XXXX
    status          VARCHAR(20) NOT NULL DEFAULT 'open',  -- open/finalized/cancelled
    stocktake_type  VARCHAR(20) DEFAULT 'full',  -- full/cycle（循环盘点）/spot（抽检）
    initiated_by    UUID,  -- 发起人 employee_id
    finalized_by    UUID,  -- 结单人 employee_id
    note            TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    finalized_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_stocktakes_tenant_store ON stocktakes(tenant_id, store_id, status);

-- RLS 策略（使用 app.tenant_id，与现有表保持一致）
ALTER TABLE stocktakes ENABLE ROW LEVEL SECURITY;
CREATE POLICY stocktakes_tenant_isolation ON stocktakes
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
```

#### 表2: `stocktake_items`（盘点明细行）

```sql
CREATE TABLE stocktake_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    stocktake_id    UUID NOT NULL REFERENCES stocktakes(id) ON DELETE CASCADE,
    ingredient_id   UUID NOT NULL REFERENCES ingredients(id),
    system_qty      NUMERIC(10, 3) NOT NULL,   -- 快照时系统账面数量
    actual_qty      NUMERIC(10, 3),             -- 实盘录入数量，NULL=未盘
    variance_qty    NUMERIC(10, 3),             -- 差异 = actual - system
    unit_price_fen  INTEGER,                    -- 快照单价
    variance_cost_fen INTEGER,                 -- 差异金额
    counted_by      UUID,                       -- 录入人 employee_id
    counted_at      TIMESTAMPTZ,
    status          VARCHAR(20) DEFAULT 'pending', -- pending/counted/matched/surplus/deficit
    is_deleted      BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_stocktake_items_stocktake ON stocktake_items(stocktake_id);
CREATE INDEX idx_stocktake_items_tenant ON stocktake_items(tenant_id);

ALTER TABLE stocktake_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY stocktake_items_tenant_isolation ON stocktake_items
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
```

#### 表3: `warehouse_transfers`（移库单）

```sql
CREATE TABLE warehouse_transfers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    transfer_no      VARCHAR(30) NOT NULL UNIQUE,  -- WT20260331XXXX
    from_store_id    UUID NOT NULL REFERENCES stores(id),
    to_store_id      UUID NOT NULL REFERENCES stores(id),
    -- 注：奥琦玮 depot 概念映射为 store_type=warehouse 的 Store 记录
    transfer_type    VARCHAR(20) DEFAULT 'inter_store',  -- inter_store/depot_to_store/return
    status           VARCHAR(20) DEFAULT 'pending',
    -- pending/sender_confirmed/receiver_confirmed/completed/cancelled
    initiated_by     UUID,
    sender_confirmed_by   UUID,
    receiver_confirmed_by UUID,
    sender_confirmed_at   TIMESTAMPTZ,
    receiver_confirmed_at TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    is_deleted       BOOLEAN DEFAULT FALSE
);

CREATE TABLE warehouse_transfer_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    transfer_id     UUID NOT NULL REFERENCES warehouse_transfers(id) ON DELETE CASCADE,
    ingredient_id   UUID NOT NULL,
    ingredient_name VARCHAR(100) NOT NULL,
    quantity        NUMERIC(10, 3) NOT NULL,
    unit            VARCHAR(20) NOT NULL,
    batch_no        VARCHAR(50),
    unit_price_fen  INTEGER,
    is_deleted      BOOLEAN DEFAULT FALSE
);
```

#### 表4: `supplier_profiles`（供应商档案，与 suppliers 表关联）

> 说明：现有 `supply_chain_ext.py` 引用了 `suppliers` 表，`supplier_portal_service.py` 则在内存中维护更丰富的供应商信息（评分、合同、价格历史）。需要将后者持久化。

```sql
-- 扩展现有 suppliers 表，或新建 supplier_profiles 表
CREATE TABLE supplier_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    supplier_id     UUID NOT NULL REFERENCES suppliers(id),  -- 关联基础 suppliers 表

    -- 外部系统 ID（用于同步去重）
    external_id     VARCHAR(100),   -- 奥琦玮的 supplierCode
    source          VARCHAR(30),    -- "aoqiwei" / "manual"

    -- 资质
    certifications  JSONB DEFAULT '[]',  -- ["食品经营许可证", "ISO22000"]
    payment_terms   VARCHAR(20) DEFAULT 'net30',  -- net30/net60/cod

    -- 推荐等级
    recommendation_level VARCHAR(20) DEFAULT 'approved',  -- preferred/approved/probation/blacklist
    blacklist_reason TEXT,

    -- 当前评分（最近一次计算结果快照）
    last_score_quality    NUMERIC(4, 2),
    last_score_delivery   NUMERIC(4, 2),
    last_score_price      NUMERIC(4, 2),
    last_score_service    NUMERIC(4, 2),
    last_score_compliance NUMERIC(4, 2),
    last_total_score      NUMERIC(4, 2),
    last_scored_at        TIMESTAMPTZ,

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE,

    UNIQUE(tenant_id, supplier_id)
);

-- 价格历史（用于价格情报和稳定性评分）
CREATE TABLE supplier_price_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    supplier_id     UUID NOT NULL,
    ingredient_id   UUID NOT NULL,
    price_fen       INTEGER NOT NULL,
    effective_date  DATE NOT NULL,
    source          VARCHAR(30),  -- "purchase_order" / "manual"
    reference_id    UUID,         -- 关联的 purchase_order id
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_price_history_supplier_ingredient ON supplier_price_history(tenant_id, supplier_id, ingredient_id, effective_date DESC);
```

#### 表5: `purchase_orders`（采购单持久化）

> 说明：`procurement_service.py` 的状态机逻辑完整，但无 DB 写入。需要建表持久化。

```sql
CREATE TABLE purchase_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    store_id        UUID NOT NULL REFERENCES stores(id),
    po_no           VARCHAR(30) NOT NULL UNIQUE,  -- PO20260331XXXX

    -- 来源（区分自建 vs 外部同步）
    source          VARCHAR(30) DEFAULT 'manual',  -- "manual" / "aoqiwei" / "pinzhi"
    external_id     VARCHAR(100),  -- 外部系统单号

    requisition_id  UUID,          -- 关联请购单（内部发起时）
    supplier_id     UUID REFERENCES suppliers(id),
    supplier_name   VARCHAR(100),

    status          VARCHAR(30) NOT NULL DEFAULT 'draft',
    -- draft/pending_approval/approved/rejected/ordered/received/inspected/stocked/cancelled

    expected_delivery DATE,
    total_fen       INTEGER DEFAULT 0,  -- 总金额（分）

    -- 审批信息
    approved_by     UUID,
    approved_at     TIMESTAMPTZ,
    rejection_reason TEXT,

    notes           TEXT,
    created_by      UUID,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE
);

CREATE TABLE purchase_order_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    po_id           UUID NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    ingredient_id   UUID,
    ingredient_name VARCHAR(100) NOT NULL,
    unit            VARCHAR(20) NOT NULL,
    quantity        NUMERIC(10, 3) NOT NULL,
    unit_price_fen  INTEGER,
    subtotal_fen    INTEGER,
    received_qty    NUMERIC(10, 3),  -- 实收数量
    quality_status  VARCHAR(20) DEFAULT 'pending',  -- pending/pass/fail/partial
    is_deleted      BOOLEAN DEFAULT FALSE
);
```

### 3.3 表关系图（文字描述）

```
purchase_orders (1) → (N) purchase_order_items
purchase_orders (1) → (N) receiving_orders        -- 一个采购单可能多次收货
receiving_orders (1) → (N) receiving_items
receiving_orders (1) → (N) ingredient_transactions  -- 入库后触发库存流水

stocktakes (1) → (N) stocktake_items
stocktake_items 结单后 → ingredient_transactions (adjustment 类型)

warehouse_transfers (1) → (N) warehouse_transfer_items
warehouse_transfers 完成后 → ingredient_transactions (transfer_in/transfer_out 类型)

suppliers (1) → (1) supplier_profiles
supplier_profiles → (N) supplier_price_history
```

---

## 四、供应商绩效评分引擎设计

### 4.1 评分维度

延续现有 `supplier_portal_service.py` 的五维度框架，扩展 AI 接入：

| 维度 | 权重 | 数据来源 | 计算方式 |
|------|------|------|------|
| 质量（quality） | 30% | `receiving_items.quality_status` | 合格率 = pass件数 / 总收货件数 |
| 交付（delivery） | 25% | `purchase_orders.expected_delivery` vs `receiving_orders.created_at` | 准时率 = 按时收货次数 / 总次数 |
| 价格（price） | 20% | `supplier_price_history` | 价格稳定性 = 1 - 标准差/均值（CV系数） |
| 服务（service） | 15% | 人工评分 + 退货处理速度 | 加权平均（手动评分 + 退货响应天数） |
| 合规（compliance） | 10% | `supplier_profiles.certifications` 到期状态 | 资质有效率 = 有效资质数/总资质数 |

### 4.2 评分触发时机

```
事件驱动 + 定期批量（二选一组合）：
1. 每次收货单 finalize → 触发对应供应商实时评分更新
2. 每日凌晨批量重算最近 90 天数据 → 写入 supplier_profiles.last_*_score
```

### 4.3 AI 评分接口设计

**文件位置**: `services/tx-supply/src/services/supplier_score_service.py`（新增）

```python
class SupplierScoreService:
    """供应商绩效评分引擎

    规则评分（可离线计算）+ AI 洞察（在线 Claude API 调用）
    """

    async def calculate_scores(
        self,
        supplier_id: str,
        tenant_id: str,
        lookback_days: int = 90,
    ) -> SupplierScoreResult:
        """规则评分：基于 DB 数据计算五维度分数"""
        ...

    async def generate_ai_insight(
        self,
        supplier_id: str,
        tenant_id: str,
        score_result: SupplierScoreResult,
    ) -> str:
        """AI 洞察：调用 ModelRouter 生成供应商分析报告

        任务类型: "supplier_insight" (已在 ModelRouter 注册, Moderate 级别)
        输入: 最近评分 + 价格趋势 + 异常收货记录
        输出: 200字以内的评分解读 + 风险预警 + 优化建议
        """
        model = model_router.get_model("supplier_insight")
        # ... 调用 Claude API, 不直接调用，必须通过 model_router
        ...
```

**AI Prompt 设计要点**：
- 输入上下文：最近 90 天各维度得分、价格波动曲线（简化为描述）、质量不合格清单
- 输出结构化 JSON：`{risk_level: "low/medium/high", summary: "...", recommendations: [...]}`
- 调用频率：仅在总部月度采购报告或手动触发时调用，不实时触发（控成本）

### 4.4 评分结果存储

```sql
CREATE TABLE supplier_score_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    supplier_id     UUID NOT NULL,
    score_period    VARCHAR(10) NOT NULL,  -- "2026-03"（月度）

    score_quality    NUMERIC(4, 2),
    score_delivery   NUMERIC(4, 2),
    score_price      NUMERIC(4, 2),
    score_service    NUMERIC(4, 2),
    score_compliance NUMERIC(4, 2),
    total_score      NUMERIC(4, 2),

    -- 计算依据统计
    receiving_count  INTEGER,   -- 收货次数
    quality_pass_count INTEGER,
    on_time_count   INTEGER,
    price_cv        NUMERIC(6, 4),  -- 价格变异系数

    -- AI 洞察
    ai_insight      TEXT,       -- AI 生成的分析报告
    ai_generated_at TIMESTAMPTZ,

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE,

    UNIQUE(tenant_id, supplier_id, score_period)
);
```

---

## 五、巡店管理模块设计

### 5.1 模块定位

巡店管理 = **门店健康度定期体检**。与 tx-org（组织模块）的关系：
- 巡店任务的**分配和通知**依赖 tx-org 的员工角色（inspector/area_manager）
- 巡店发现的整改跟踪依赖 tx-org 的**审批流引擎**（`approval_workflow_engine.py` 已有）
- 独立部署在 tx-org 服务内（作为新模块），或在 tx-supply 的 `api/` 目录下增加路由

**建议**：巡店作为 `tx-org` 的新子模块（`tx-org/src/services/store_inspection_service.py`），原因：巡店的核心是人员调度和整改管理，与供应链关系弱，与组织人员关系强。

### 5.2 数据库表设计

```sql
-- 巡店模板（检查项集合）
CREATE TABLE inspection_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    name            VARCHAR(100) NOT NULL,  -- "标准月度巡店"
    template_type   VARCHAR(30) DEFAULT 'regular',  -- regular/surprise/safety/food_safety
    items           JSONB NOT NULL,
    -- [{section: "食品安全", items: [{code: "FS001", title: "冰箱温度", weight: 10, ...}]}]
    total_weight    INTEGER DEFAULT 100,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE
);

-- 巡店任务（一次巡店计划）
CREATE TABLE inspection_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    task_no         VARCHAR(30) NOT NULL UNIQUE,  -- IT20260331XXXX
    store_id        UUID NOT NULL REFERENCES stores(id),
    template_id     UUID REFERENCES inspection_templates(id),

    inspector_id    UUID NOT NULL,  -- 巡店人员 employee_id (来自 tx-org employees 表)
    area_manager_id UUID,           -- 区域经理（可选，用于收到汇报）

    task_type       VARCHAR(30) DEFAULT 'regular',
    status          VARCHAR(20) DEFAULT 'scheduled',
    -- scheduled/in_progress/completed/cancelled

    scheduled_date  DATE NOT NULL,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,

    total_score     NUMERIC(5, 2),  -- 0-100
    pass_threshold  NUMERIC(5, 2) DEFAULT 80,  -- 合格线
    result          VARCHAR(20),    -- pass/fail/partial

    summary         TEXT,           -- 巡店总结
    ai_report       TEXT,           -- AI 生成的报告（可选）

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_inspection_tasks_store ON inspection_tasks(tenant_id, store_id, scheduled_date DESC);
CREATE INDEX idx_inspection_tasks_inspector ON inspection_tasks(tenant_id, inspector_id, status);

-- 巡店明细（每个检查项的评分记录）
CREATE TABLE inspection_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    task_id         UUID NOT NULL REFERENCES inspection_tasks(id) ON DELETE CASCADE,

    item_code       VARCHAR(30) NOT NULL,   -- 与模板 items.code 对应
    section         VARCHAR(50),
    title           VARCHAR(200) NOT NULL,

    result          VARCHAR(20),  -- pass/fail/na（不适用）
    score           NUMERIC(5, 2),
    weight          INTEGER DEFAULT 1,

    notes           TEXT,
    photo_urls      JSONB DEFAULT '[]',  -- 现场照片 URL 列表

    requires_rectification BOOLEAN DEFAULT FALSE,
    is_deleted      BOOLEAN DEFAULT FALSE
);

-- 整改单（不合格项的跟踪）
CREATE TABLE inspection_rectifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    task_id         UUID NOT NULL REFERENCES inspection_tasks(id),
    item_id         UUID NOT NULL REFERENCES inspection_items(id),

    description     TEXT NOT NULL,      -- 问题描述
    severity        VARCHAR(20) DEFAULT 'medium',  -- critical/high/medium/low
    deadline        DATE,               -- 整改截止日期

    status          VARCHAR(20) DEFAULT 'open',  -- open/in_progress/resolved/verified/closed
    assignee_id     UUID,               -- 责任人 employee_id
    verifier_id     UUID,               -- 核查人

    resolution_notes TEXT,
    resolved_at     TIMESTAMPTZ,
    verified_at     TIMESTAMPTZ,

    -- 关联审批流（复用 tx-org 的 approval_workflow_engine）
    approval_flow_id UUID,

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_rectifications_task ON inspection_rectifications(task_id);
CREATE INDEX idx_rectifications_assignee ON inspection_rectifications(tenant_id, assignee_id, status);
```

### 5.3 API 接口设计

**路由前缀**: `GET/POST /api/v1/org/inspections`（放在 tx-org 服务）

```
POST   /api/v1/org/inspections/templates          # 创建巡店模板
GET    /api/v1/org/inspections/templates          # 查询模板列表

POST   /api/v1/org/inspections/tasks              # 创建巡店任务
GET    /api/v1/org/inspections/tasks              # 查询任务列表（按门店/巡店员/状态过滤）
GET    /api/v1/org/inspections/tasks/{task_id}    # 任务详情
PATCH  /api/v1/org/inspections/tasks/{task_id}/start    # 开始巡店
PATCH  /api/v1/org/inspections/tasks/{task_id}/submit   # 提交结果
PATCH  /api/v1/org/inspections/tasks/{task_id}/items/{item_id}  # 录入单项评分

GET    /api/v1/org/inspections/rectifications     # 查整改单（按状态/责任人）
PATCH  /api/v1/org/inspections/rectifications/{id}/resolve  # 提交整改结果
PATCH  /api/v1/org/inspections/rectifications/{id}/verify   # 核查确认
```

### 5.4 与 tx-org 组织模块的关系

```
tx-org 提供：
  - 员工角色：inspector（巡店员）/ area_manager（区域经理）
  - 已有审批流：inspection_rectifications.approval_flow_id 引用 approval_flows
  - 门店批量操作：store_batch.py 可用于批量创建多门店巡店任务

巡店模块使用：
  - tx-org.employees 表查询巡店员信息
  - tx-org.approval_workflow_engine 处理整改审批
  - tx-org.franchise_service 判断是否加盟店（不同巡店模板）
```

---

## 六、优先级建议：Phase 1 十二周 Sprint 计划

### Sprint 5-8（第 5-8 周）：地基 — 数据入库

**目标**：打通采购数据管道，WMS 表结构落地

| Sprint | 主要工作 | 关键产出 |
|--------|----------|----------|
| Sprint 5 | Alembic 迁移：新增 purchase_orders / purchase_order_items / stocktakes / stocktake_items | 5 张核心表上线，含 RLS 策略 |
| Sprint 5 | 奥琦玮 supply_mapper.py：to_purchase_order / to_supplier / to_receiving 三个映射函数（含 >=3 单测） | 映射函数 + 测试通过 |
| Sprint 6 | ProcurementSyncService：增量同步 + UPSERT + 定时任务接入 | 奥琦玮数据每日自动入库 |
| Sprint 6 | stocktake_service.py 重构：内存缓存 → DB 持久化（迁移到 stocktakes/stocktake_items 表） | 盘点数据持久化 |
| Sprint 7 | warehouse_transfers 表 + warehouse_ops.py 重构（无持久化 → DB 写入） | 移库单可持久化 |
| Sprint 7 | supplier_profiles + supplier_price_history 表 + supplier_portal_service.py DB化 | 供应商档案持久化 |
| Sprint 8 | purchase_orders 状态机与 DB 打通 + API 路由完善 | 采购全流程可跑通 |
| Sprint 8 | 集成测试：奥琦玮 → 采购单 → 收货 → 库存流水 全链路测试 | E2E 冒烟测试通过 |

**约束**：
- 所有新表必须带 `tenant_id` + RLS 策略（使用 `app.tenant_id`，不得为 NULL 绕过，参见 RLS 安全漏洞备忘）
- 新增映射函数必须附带 >=3 单测（参见 CLAUDE.md 审计修复期约束）
- 异常处理不得使用 `except Exception`

### Sprint 9-12（第 9-12 周）：上层 — 智能与运营

**目标**：供应商评分引擎上线，巡店模块 MVP

| Sprint | 主要工作 | 关键产出 |
|--------|----------|----------|
| Sprint 9 | supplier_score_service.py：规则评分计算（5维度 × DB数据） | 月度评分可计算 |
| Sprint 9 | supplier_score_history 表 + 评分写入 | 评分历史可查 |
| Sprint 10 | AI 洞察接入：ModelRouter("supplier_insight") + Claude Sonnet | 月报 AI 摘要可用 |
| Sprint 10 | 巡店模块：inspection_templates + inspection_tasks + inspection_items 表 + Alembic | 数据库上线 |
| Sprint 11 | 巡店 Service + API：创建任务 / 录入结果 / 提交 / 查询 | 巡店 MVP 可用 |
| Sprint 11 | 整改单：inspection_rectifications + 与 approval_workflow_engine 集成 | 整改可审批跟踪 |
| Sprint 12 | 供应链数据联动：收货异常 → 自动触发供应商评分重算 | 事件驱动评分 |
| Sprint 12 | Phase 1 验收：奥琦玮数据同步稳定性测试 + 巡店模块功能验收 | 交付报告 |

### 关键路径风险

| 风险 | 概率 | 缓解方案 |
|------|------|------|
| 奥琦玮 API 字段与文档不符 | 高（已知历史问题） | Sprint 5 先跑 Mock 数据，预留 1 周用于字段校正 |
| 品智无独立采购接口 | 已确认 | 仅同步食材主档，采购数据走奥琦玮 |
| 盘点服务从内存迁 DB 有数据丢失风险 | 中 | Sprint 6 新功能上线前，保留内存逻辑作降级开关 |
| RLS 安全漏洞未修复（MEMORY 备忘） | CRITICAL | 新表 RLS 必须用 `app.tenant_id`，不得复用旧表的错误写法 |

---

## 七、架构决策记录（ADR）

### ADR-001：巡店模块放在 tx-org 而非 tx-supply
**决策**：巡店管理作为 tx-org 服务的新模块
**理由**：巡店核心逻辑是人员调度 + 整改审批（已有 approval_workflow_engine），与供应链数据耦合少
**反对意见**：有人认为巡店发现的食材卫生问题应与供应链联动
**折中**：整改单可选关联 ingredient_id，待需求明确后再加

### ADR-002：供应商评分 AI 仅用于报告，不实时触发
**决策**：AI 洞察仅在月度报告或手动触发时调用，不在每次收货后实时触发
**理由**：Claude API 调用成本控制，单人开发阶段优先保证功能完整性
**条件**：若后续商户需要实时预警，可改为事件驱动（收货异常评分 < 60 分时触发）

### ADR-003：purchase_orders 与奥琦玮 depotin 的映射关系
**决策**：奥琦玮的"采购入库单"（depotin）映射为 purchase_orders（status=stocked）
**理由**：奥琦玮只提供已入库的结果数据，无请购/审批中间状态
**影响**：外部同步进来的订单直接跳过 draft/approved 阶段，source="aoqiwei" 标记区分

### ADR-004：Ontology 层本次不变更
**决策**：本次 Phase 1 只做数据接入层和新增业务表，不修改 Ontology L1 层的六大核心实体
**理由**：Ontology 变更需创始人确认，且现有 Ingredient / Store / Supplier 实体已能支撑供应链场景
**例外**：supplier_profiles 作为 suppliers 的扩展表，不修改 suppliers 实体本身

---

## 八、文件变更清单（仅设计，不包含实现代码）

### 需要新增的文件
```
shared/adapters/aoqiwei/src/supply_mapper.py       # 采购数据字段映射
shared/adapters/aoqiwei/tests/test_supply_mapper.py
shared/adapters/pinzhi/src/supply_sync.py          # 品智食材主档映射

services/tx-supply/src/services/procurement_sync_service.py  # 采购同步服务
services/tx-supply/src/services/supplier_score_service.py    # 供应商评分引擎
services/tx-supply/src/tests/test_procurement_sync.py
services/tx-supply/src/tests/test_supplier_score.py

services/tx-org/src/services/store_inspection_service.py     # 巡店服务
services/tx-org/src/api/inspection_routes.py                 # 巡店 API 路由
services/tx-org/src/tests/test_inspection.py

shared/db-migrations/versions/XXXX_add_purchase_orders.py
shared/db-migrations/versions/XXXX_add_stocktakes.py
shared/db-migrations/versions/XXXX_add_warehouse_transfers.py
shared/db-migrations/versions/XXXX_add_supplier_profiles.py
shared/db-migrations/versions/XXXX_add_supplier_score_history.py
shared/db-migrations/versions/XXXX_add_inspection_tables.py
```

### 需要修改的文件
```
services/tx-supply/src/services/stocktake_service.py         # 内存 → DB 持久化
services/tx-supply/src/services/warehouse_ops.py             # 无持久化 → DB 写入
services/tx-supply/src/services/supplier_portal_service.py   # 内存 dict → DB 读写
services/tx-supply/src/services/procurement_service.py       # 增加 DB 写入（UPSERT）
shared/adapters/base/src/types/supplier.py                   # 补充 UnifiedReceivingRecord 类型
services/tunxiang-api/src/shared/core/model_router.py        # 注册 supplier_scoring 任务类型
```

---

*本文档为技术预研设计方案。实施前需创始人确认优先级，特别是 Alembic 迁移的执行顺序和 RLS 安全漏洞修复的协同安排。*
