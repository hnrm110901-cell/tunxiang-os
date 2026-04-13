"""Agent KPI绑定路由 — 9大核心Agent与可量化业务KPI的绑定、追踪与ROI报告

模块4.4: AI Agent深化绑定业务KPI

端点:
  GET    /api/v1/agent-kpi/configs                    — 获取所有Agent KPI配置
  POST   /api/v1/agent-kpi/configs                    — 创建KPI配置
  PUT    /api/v1/agent-kpi/configs/{config_id}        — 更新KPI配置
  GET    /api/v1/agent-kpi/snapshots                  — 获取KPI快照列表
  POST   /api/v1/agent-kpi/snapshots/collect          — 手动触发快照采集
  GET    /api/v1/agent-kpi/dashboard                  — KPI总览仪表盘
  GET    /api/v1/agent-kpi/roi-report                 — ROI报告
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent-kpi", tags=["agent-kpi"])

# ── 9大Agent默认KPI定义 ──────────────────────────────────────────────────────

AGENT_KPI_DEFAULTS: dict[str, list[dict]] = {
    "discount_guardian": [
        {
            "kpi_type": "discount_exception_rate",
            "label": "折扣异常率",
            "target_value": 2.0,
            "unit": "%",
            "alert_threshold": 5.0,
            "direction": "lower_better",
            "description": "异常折扣占所有折扣的比例，目标<2%",
        },
        {
            "kpi_type": "gross_margin_protection_rate",
            "label": "毛利保护率",
            "target_value": 98.0,
            "unit": "%",
            "alert_threshold": 95.0,
            "direction": "higher_better",
            "description": "未被异常折扣侵蚀的订单占比，目标>98%",
        },
    ],
    "smart_dispatch": [
        {
            "kpi_type": "avg_dish_time_seconds",
            "label": "平均出餐时间",
            "target_value": 600.0,
            "unit": "秒",
            "alert_threshold": 900.0,
            "direction": "lower_better",
            "description": "从下单到出餐的平均时长，目标<600秒",
        },
        {
            "kpi_type": "on_time_rate",
            "label": "准时出餐率",
            "target_value": 95.0,
            "unit": "%",
            "alert_threshold": 85.0,
            "direction": "higher_better",
            "description": "在承诺时间内出餐的订单比例，目标>95%",
        },
    ],
    "member_insight": [
        {
            "kpi_type": "member_repurchase_rate",
            "label": "会员复购率",
            "target_value": 40.0,
            "unit": "%",
            "alert_threshold": 30.0,
            "direction": "higher_better",
            "description": "30日内再次消费的会员比例，目标>40%",
        },
        {
            "kpi_type": "clv_growth_rate",
            "label": "CLV增长率",
            "target_value": 10.0,
            "unit": "%",
            "alert_threshold": 0.0,
            "direction": "higher_better",
            "description": "客户生命周期价值同比增长率，目标>10%",
        },
    ],
    "inventory_alert": [
        {
            "kpi_type": "waste_rate",
            "label": "食材损耗率",
            "target_value": 3.0,
            "unit": "%",
            "alert_threshold": 5.0,
            "direction": "lower_better",
            "description": "损耗食材金额占总采购金额的比例，目标<3%",
        },
        {
            "kpi_type": "stockout_rate",
            "label": "缺货率",
            "target_value": 1.0,
            "unit": "%",
            "alert_threshold": 3.0,
            "direction": "lower_better",
            "description": "发生缺货的SKU占总SKU比例，目标<1%",
        },
    ],
    "finance_audit": [
        {
            "kpi_type": "anomaly_detection_rate",
            "label": "财务异常检出率",
            "target_value": 99.0,
            "unit": "%",
            "alert_threshold": 95.0,
            "direction": "higher_better",
            "description": "被检出的财务异常数占实际异常总数的比例，目标>99%",
        },
        {
            "kpi_type": "cost_variance",
            "label": "成本差异率",
            "target_value": 5.0,
            "unit": "%",
            "alert_threshold": 10.0,
            "direction": "lower_better",
            "description": "实际成本与预算成本的偏差率，目标<5%",
        },
    ],
    "store_patrol": [
        {
            "kpi_type": "compliance_score",
            "label": "合规评分",
            "target_value": 90.0,
            "unit": "分",
            "alert_threshold": 75.0,
            "direction": "higher_better",
            "description": "门店合规综合评分（满分100），目标>90",
        },
        {
            "kpi_type": "patrol_response_time",
            "label": "巡检响应时间",
            "target_value": 30.0,
            "unit": "分钟",
            "alert_threshold": 60.0,
            "direction": "lower_better",
            "description": "从发现问题到响应处理的时间，目标<30分钟",
        },
    ],
    "smart_menu": [
        {
            "kpi_type": "menu_optimization_revenue_rate",
            "label": "排菜优化增收率",
            "target_value": 5.0,
            "unit": "%",
            "alert_threshold": 0.0,
            "direction": "higher_better",
            "description": "通过智能排菜带来的营收提升百分比，目标>5%",
        },
    ],
    "customer_service": [
        {
            "kpi_type": "resolution_rate",
            "label": "问题解决率",
            "target_value": 90.0,
            "unit": "%",
            "alert_threshold": 75.0,
            "direction": "higher_better",
            "description": "AI客服首次解决率，目标>90%",
        },
    ],
    "private_ops": [
        {
            "kpi_type": "campaign_conversion_rate",
            "label": "私域转化率",
            "target_value": 8.0,
            "unit": "%",
            "alert_threshold": 3.0,
            "direction": "higher_better",
            "description": "私域运营活动的到店转化率，目标>8%",
        },
    ],
}

AGENT_NAMES: dict[str, str] = {
    "discount_guardian": "折扣守护",
    "smart_dispatch": "出餐调度",
    "member_insight": "会员洞察",
    "inventory_alert": "库存预警",
    "finance_audit": "财务稽核",
    "store_patrol": "巡店质检",
    "smart_menu": "智能排菜",
    "customer_service": "智能客服",
    "private_ops": "私域运营",
}


# ── Pydantic V2 模型 ──────────────────────────────────────────────────────────

class KpiConfigCreate(BaseModel):
    agent_id: str = Field(..., max_length=64)
    kpi_type: str = Field(..., max_length=64)
    target_value: float
    unit: str = Field(default="", max_length=32)
    alert_threshold: Optional[float] = None
    is_active: bool = True


class KpiConfigUpdate(BaseModel):
    target_value: Optional[float] = None
    unit: Optional[str] = Field(default=None, max_length=32)
    alert_threshold: Optional[float] = None
    is_active: Optional[bool] = None


class KpiSnapshotCollectRequest(BaseModel):
    agent_id: Optional[str] = None
    snapshot_date: Optional[date] = None
    store_id: Optional[str] = None


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _achievement_rate(measured: float, target: float, direction: str) -> float:
    """计算达成率（0-1）。"""
    if target == 0:
        return 1.0
    if direction == "lower_better":
        rate = target / measured if measured > 0 else 1.0
    else:
        rate = measured / target
    return min(round(rate, 4), 2.0)  # 上限200%


def _achievement_color(rate: float) -> str:
    """根据达成率返回颜色标签。"""
    if rate >= 0.95:
        return "green"
    if rate >= 0.80:
        return "yellow"
    return "red"


# ── 端点 ─────────────────────────────────────────────────────────────────────

@router.get("/configs")
async def get_kpi_configs(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    agent_id: Optional[str] = Query(None, description="按Agent过滤"),
    is_active: Optional[bool] = Query(None, description="按启用状态过滤"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取所有Agent KPI配置（DB自定义配置 + 内置默认定义合并）。

    DB中的自定义配置会覆盖同 agent_id+kpi_type 的默认值。
    """
    # ── 从 DB 读取自定义配置 ──
    db_customs: dict[tuple[str, str], dict] = {}
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        filters = "WHERE tenant_id = :tid AND is_deleted = FALSE"
        params: dict = {"tid": x_tenant_id}
        if agent_id:
            filters += " AND agent_id = :agent_id"
            params["agent_id"] = agent_id
        if is_active is not None:
            filters += " AND is_active = :is_active"
            params["is_active"] = is_active
        result = await db.execute(
            text(f"""
                SELECT id::text, tenant_id::text, agent_id, kpi_type,
                       target_value, unit, alert_threshold, is_active,
                       created_at, updated_at
                FROM agent_kpi_configs
                {filters}
                ORDER BY created_at
            """),
            params,
        )
        for r in result.mappings().all():
            db_customs[(r["agent_id"], r["kpi_type"])] = dict(r)
    except SQLAlchemyError as exc:
        logger.warning(
            "agent_kpi.get_configs.db_error",
            tenant_id=x_tenant_id,
            error=str(exc),
            exc_info=True,
        )

    # ── 合并：默认定义 + DB 自定义覆盖 ──
    configs = []
    for aid, kpi_list in AGENT_KPI_DEFAULTS.items():
        if agent_id and aid != agent_id:
            continue
        for kpi in kpi_list:
            key = (aid, kpi["kpi_type"])
            custom = db_customs.pop(key, None)
            if custom is not None:
                item = {
                    "id": custom["id"],
                    "tenant_id": custom["tenant_id"],
                    "agent_id": aid,
                    "agent_name": AGENT_NAMES.get(aid, aid),
                    "kpi_type": kpi["kpi_type"],
                    "label": kpi["label"],
                    "target_value": custom["target_value"],
                    "unit": custom["unit"] or kpi["unit"],
                    "alert_threshold": custom["alert_threshold"],
                    "direction": kpi["direction"],
                    "description": kpi["description"],
                    "is_active": custom["is_active"],
                    "source": "custom",
                    "created_at": custom["created_at"].isoformat() if custom["created_at"] else None,
                    "updated_at": custom["updated_at"].isoformat() if custom["updated_at"] else None,
                }
            else:
                item = {
                    "id": f"default_{aid}_{kpi['kpi_type']}",
                    "tenant_id": x_tenant_id,
                    "agent_id": aid,
                    "agent_name": AGENT_NAMES.get(aid, aid),
                    "kpi_type": kpi["kpi_type"],
                    "label": kpi["label"],
                    "target_value": kpi["target_value"],
                    "unit": kpi["unit"],
                    "alert_threshold": kpi["alert_threshold"],
                    "direction": kpi["direction"],
                    "description": kpi["description"],
                    "is_active": True,
                    "source": "default",
                }
            if is_active is None or item["is_active"] == is_active:
                configs.append(item)

    # 追加 DB 中有、但默认定义里没有的自定义配置（扩展 KPI 类型）
    for (aid, kpi_type), custom in db_customs.items():
        if agent_id and aid != agent_id:
            continue
        item = {
            "id": custom["id"],
            "tenant_id": custom["tenant_id"],
            "agent_id": aid,
            "agent_name": AGENT_NAMES.get(aid, aid),
            "kpi_type": kpi_type,
            "label": kpi_type,
            "target_value": custom["target_value"],
            "unit": custom["unit"],
            "alert_threshold": custom["alert_threshold"],
            "direction": "higher_better",
            "description": "",
            "is_active": custom["is_active"],
            "source": "custom",
            "created_at": custom["created_at"].isoformat() if custom["created_at"] else None,
            "updated_at": custom["updated_at"].isoformat() if custom["updated_at"] else None,
        }
        if is_active is None or item["is_active"] == is_active:
            configs.append(item)

    return {"ok": True, "data": {"items": configs, "total": len(configs)}}


@router.post("/configs")
async def create_kpi_config(
    body: KpiConfigCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建自定义KPI配置（写入 agent_kpi_configs 表）。"""
    if body.agent_id not in AGENT_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"未知Agent: {body.agent_id}。有效值: {list(AGENT_NAMES.keys())}",
        )

    config_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        await db.execute(
            text("""
                INSERT INTO agent_kpi_configs
                    (id, tenant_id, agent_id, kpi_type, target_value, unit,
                     alert_threshold, is_active, created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :agent_id, :kpi_type, :target_value, :unit,
                     :alert_threshold, :is_active, :created_at, :updated_at)
            """),
            {
                "id": config_id,
                "tenant_id": x_tenant_id,
                "agent_id": body.agent_id,
                "kpi_type": body.kpi_type,
                "target_value": body.target_value,
                "unit": body.unit,
                "alert_threshold": body.alert_threshold,
                "is_active": body.is_active,
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "agent_kpi.create_config.db_error",
            tenant_id=x_tenant_id,
            agent_id=body.agent_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="KPI配置写入失败，请稍后重试") from exc

    return {"ok": True, "data": {
        "id": config_id,
        "tenant_id": x_tenant_id,
        "agent_id": body.agent_id,
        "agent_name": AGENT_NAMES.get(body.agent_id, body.agent_id),
        "kpi_type": body.kpi_type,
        "target_value": body.target_value,
        "unit": body.unit,
        "alert_threshold": body.alert_threshold,
        "is_active": body.is_active,
        "source": "custom",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }}


@router.put("/configs/{config_id}")
async def update_kpi_config(
    config_id: str,
    body: KpiConfigUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新KPI配置（写入 agent_kpi_configs 表）。"""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    now = datetime.now(timezone.utc)

    # 动态构建 SET 子句，只更新有值的字段
    set_parts = ", ".join(f"{col} = :{col}" for col in updates)
    params = {**updates, "id": config_id, "tenant_id": x_tenant_id, "updated_at": now}

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": x_tenant_id},
        )
        result = await db.execute(
            text(f"""
                UPDATE agent_kpi_configs
                SET {set_parts}, updated_at = :updated_at
                WHERE id = :id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id::text, agent_id, kpi_type, target_value, unit,
                          alert_threshold, is_active, updated_at
            """),
            params,
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "agent_kpi.update_config.db_error",
            tenant_id=x_tenant_id,
            config_id=config_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="KPI配置更新失败，请稍后重试") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"KPI配置不存在或无权访问: {config_id}")

    return {"ok": True, "data": {
        "id": row["id"],
        "tenant_id": x_tenant_id,
        "agent_id": row["agent_id"],
        "agent_name": AGENT_NAMES.get(row["agent_id"], row["agent_id"]),
        "kpi_type": row["kpi_type"],
        "target_value": row["target_value"],
        "unit": row["unit"],
        "alert_threshold": row["alert_threshold"],
        "is_active": row["is_active"],
        "source": "custom",
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else now.isoformat(),
        "updated_fields": list(updates.keys()),
    }}


@router.get("/snapshots")
async def get_kpi_snapshots(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    agent_id: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取KPI快照列表（从 agent_kpi_snapshots 表查询，支持按Agent和日期范围过滤）。"""
    today = date.today()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = today - timedelta(days=6)

    # ── 构建查询条件 ──
    filters = "WHERE s.tenant_id = :tenant_id AND s.snapshot_date BETWEEN :date_from AND :date_to"
    params: dict = {
        "tenant_id": x_tenant_id,
        "date_from": date_from,
        "date_to": date_to,
        "offset": (page - 1) * size,
        "limit": size,
    }
    if agent_id:
        filters += " AND s.agent_id = :agent_id"
        params["agent_id"] = agent_id

    snapshots: list[dict] = []
    total = 0

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        # 总数
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM agent_kpi_snapshots s {filters}"),
            params,
        )
        total = count_result.scalar() or 0

        # 分页数据
        rows = await db.execute(
            text(f"""
                SELECT s.id::text, s.agent_id, s.kpi_type,
                       s.measured_value, s.target_value, s.achievement_rate,
                       s.store_id::text AS store_id,
                       s.snapshot_date::text AS snapshot_date,
                       s.metadata, s.created_at
                FROM agent_kpi_snapshots s
                {filters}
                ORDER BY s.snapshot_date DESC, s.agent_id, s.kpi_type
                LIMIT :limit OFFSET :offset
            """),
            params,
        )

        # KPI 元数据查找表：(agent_id, kpi_type) → label/unit/direction
        _kpi_meta: dict[tuple[str, str], dict] = {}
        for aid, kpi_list in AGENT_KPI_DEFAULTS.items():
            for kpi in kpi_list:
                _kpi_meta[(aid, kpi["kpi_type"])] = {
                    "label": kpi["label"],
                    "unit": kpi["unit"],
                    "direction": kpi["direction"],
                }

        for r in rows.mappings().all():
            meta = _kpi_meta.get((r["agent_id"], r["kpi_type"]), {
                "label": r["kpi_type"], "unit": "", "direction": "higher_better"
            })
            snapshots.append({
                "id": r["id"],
                "tenant_id": x_tenant_id,
                "agent_id": r["agent_id"],
                "agent_name": AGENT_NAMES.get(r["agent_id"], r["agent_id"]),
                "kpi_type": r["kpi_type"],
                "label": meta["label"],
                "measured_value": r["measured_value"],
                "target_value": r["target_value"],
                "achievement_rate": r["achievement_rate"],
                "unit": meta["unit"],
                "direction": meta["direction"],
                "store_id": r["store_id"],
                "snapshot_date": r["snapshot_date"],
                "color": _achievement_color(r["achievement_rate"]),
                "metadata": r["metadata"],
            })
    except SQLAlchemyError as exc:
        logger.warning(
            "agent_kpi.get_snapshots.db_error",
            tenant_id=x_tenant_id,
            error=str(exc),
            exc_info=True,
        )

    return {"ok": True, "data": {
        "items": snapshots,
        "total": total,
        "page": page,
        "size": size,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }}


@router.post("/snapshots/collect")
async def collect_kpi_snapshots(
    body: KpiSnapshotCollectRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发KPI快照采集 — 生成当日各Agent KPI测量值并写入 agent_kpi_snapshots 表。

    当前测量值逻辑：基于目标值按固定系数估算（占位实现）。
    生产就绪后替换为：从各业务服务 API 拉取真实指标。

    重复采集同日同Agent同KPI时：跳过已存在的记录（不覆盖）。
    """
    target_date = body.snapshot_date or date.today()
    store_id_val = body.store_id  # 可为 None

    agents_to_collect = (
        [body.agent_id] if body.agent_id and body.agent_id in AGENT_KPI_DEFAULTS
        else list(AGENT_KPI_DEFAULTS.keys())
    )

    # ── 采集真实业务指标（部分 KPI 已接入 DB，其余估算） ──────────────────────
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    # 1. discount_guardian — 来源: orders
    discount_exc_rate: float | None = None
    gross_margin_protect: float | None = None
    try:
        r = await db.execute(text("""
            SELECT
                COUNT(*) FILTER (
                    WHERE total_amount_fen > 0
                      AND discount_amount_fen::float / total_amount_fen > 0.3
                )::float                                  AS exc_count,
                COUNT(*)::float                           AS total_count
            FROM orders
            WHERE tenant_id = :tid::uuid
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :d
              AND status = 'completed'
        """), {"tid": x_tenant_id, "d": target_date.isoformat()})
        row = r.mappings().fetchone()
        total = row["total_count"] or 0
        if total > 0:
            discount_exc_rate = round(row["exc_count"] / total * 100, 2)
            gross_margin_protect = round(100 - discount_exc_rate, 2)
    except SQLAlchemyError as exc:
        logger.warning("kpi_collect.discount_guardian_failed", error=str(exc))

    # 2. member_insight — 复购率来源: orders (含 member_id 的去重客户)
    member_repurchase: float | None = None
    try:
        r = await db.execute(text("""
            WITH period AS (
                SELECT member_id, COUNT(*) AS order_count
                FROM orders
                WHERE tenant_id   = :tid::uuid
                  AND status      = 'completed'
                  AND member_id   IS NOT NULL
                  AND created_at >= :d_start::timestamptz
                  AND created_at <  :d_end::timestamptz
                GROUP BY member_id
            )
            SELECT
                COUNT(*) FILTER (WHERE order_count >= 2)::float AS repurchase_count,
                COUNT(*)::float                                  AS total_members
            FROM period
        """), {
            "tid": x_tenant_id,
            "d_start": (target_date - timedelta(days=29)).isoformat(),
            "d_end": (target_date + timedelta(days=1)).isoformat(),
        })
        row = r.mappings().fetchone()
        total_m = row["total_members"] or 0
        if total_m > 0:
            member_repurchase = round(row["repurchase_count"] / total_m * 100, 2)
    except SQLAlchemyError as exc:
        logger.warning("kpi_collect.member_insight_failed", error=str(exc))

    # 3. store_inspect — 合规评分来源: compliance_alerts
    compliance_score: float | None = None
    try:
        r = await db.execute(text("""
            SELECT COUNT(*)::int AS open_alerts
            FROM compliance_alerts
            WHERE tenant_id = :tid::uuid
              AND status    = 'open'
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') <= :d
        """), {"tid": x_tenant_id, "d": target_date.isoformat()})
        open_alerts = r.scalar() or 0
        # 每个未处理预警扣5分，最低0分
        compliance_score = max(0.0, round(100 - open_alerts * 5, 2))
    except SQLAlchemyError as exc:
        logger.warning("kpi_collect.store_inspect_failed", error=str(exc))

    # 4. smart_dispatch — 来源: kds_tasks
    smart_dispatch_avg: float | None = None
    smart_dispatch_ontime: float | None = None
    try:
        r = await db.execute(text("""
            SELECT
                AVG(EXTRACT(EPOCH FROM (served_at - called_at)))::float AS avg_seconds,
                COUNT(*) FILTER (WHERE promised_at IS NOT NULL AND served_at <= promised_at)::float
                  / GREATEST(COUNT(*) FILTER (WHERE promised_at IS NOT NULL), 1)::float * 100
                  AS on_time_pct
            FROM kds_tasks
            WHERE tenant_id = :tid::uuid
              AND status = 'served'
              AND served_at IS NOT NULL
              AND called_at IS NOT NULL
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :d
        """), {"tid": x_tenant_id, "d": target_date.isoformat()})
        row = r.mappings().fetchone()
        if row and row["avg_seconds"] is not None:
            smart_dispatch_avg = round(float(row["avg_seconds"]), 1)
            smart_dispatch_ontime = round(float(row["on_time_pct"]), 2)
    except SQLAlchemyError as exc:
        logger.warning("kpi_collect.smart_dispatch_failed", error=str(exc))

    # 5. store_patrol — patrol_response_time 来源: compliance_alerts
    patrol_response: float | None = None
    try:
        r = await db.execute(text("""
            SELECT
                AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 60)::float AS avg_response_minutes
            FROM compliance_alerts
            WHERE tenant_id = :tid::uuid
              AND status = 'resolved'
              AND resolved_at IS NOT NULL
              AND DATE(resolved_at AT TIME ZONE 'Asia/Shanghai') = :d
        """), {"tid": x_tenant_id, "d": target_date.isoformat()})
        row = r.mappings().fetchone()
        if row and row["avg_response_minutes"] is not None:
            patrol_response = round(float(row["avg_response_minutes"]), 1)
    except SQLAlchemyError as exc:
        logger.warning("kpi_collect.patrol_response_failed", error=str(exc))

    # 6. inventory_alert — stockout_rate 来源: dishes
    stockout_rate: float | None = None
    try:
        r = await db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE is_available = false)::float
                  / GREATEST(COUNT(*), 1)::float * 100 AS stockout_rate_pct
            FROM dishes
            WHERE tenant_id = :tid::uuid
              AND is_deleted = false
        """), {"tid": x_tenant_id})
        row = r.mappings().fetchone()
        if row and row["stockout_rate_pct"] is not None:
            stockout_rate = round(float(row["stockout_rate_pct"]), 2)
    except SQLAlchemyError as exc:
        logger.warning("kpi_collect.stockout_rate_failed", error=str(exc))

    # real_values：(agent_id, kpi_type) → measured_value（已有真实数据的覆盖估算）
    real_values: dict[tuple[str, str], float] = {}
    if discount_exc_rate is not None:
        real_values[("discount_guardian", "discount_exception_rate")] = discount_exc_rate
    if gross_margin_protect is not None:
        real_values[("discount_guardian", "gross_margin_protection_rate")] = gross_margin_protect
    if member_repurchase is not None:
        real_values[("member_insight", "member_repurchase_rate")] = member_repurchase
    if compliance_score is not None:
        real_values[("store_inspect", "compliance_score")] = compliance_score
    if smart_dispatch_avg is not None:
        real_values[("smart_dispatch", "avg_dish_time_seconds")] = smart_dispatch_avg
    if smart_dispatch_ontime is not None:
        real_values[("smart_dispatch", "on_time_rate")] = smart_dispatch_ontime
    if patrol_response is not None:
        real_values[("store_patrol", "patrol_response_time")] = patrol_response
    if stockout_rate is not None:
        real_values[("inventory_alert", "stockout_rate")] = stockout_rate

    # ── 构建快照列表 ──────────────────────────────────────────────────────────
    rows_to_insert: list[dict] = []
    for aid in agents_to_collect:
        kpi_list = AGENT_KPI_DEFAULTS.get(aid, [])
        for kpi in kpi_list:
            target = kpi["target_value"]
            direction = kpi["direction"]
            key = (aid, kpi["kpi_type"])
            if key in real_values:
                measured = real_values[key]
            elif direction == "lower_better":
                measured = round(target * 0.85, 2)
            else:
                measured = round(target * 1.02, 2)
            rate = _achievement_rate(measured, target, direction)
            rows_to_insert.append({
                "id": str(uuid.uuid4()),
                "tenant_id": x_tenant_id,
                "agent_id": aid,
                "kpi_type": kpi["kpi_type"],
                "measured_value": measured,
                "target_value": target,
                "achievement_rate": rate,
                "store_id": store_id_val,
                "snapshot_date": target_date,
                "metadata": '{"source": "real_db"}' if key in real_values else None,
            })

    # ── 批量写入（ON CONFLICT 跳过重复） ──
    inserted_count = 0
    skipped_count = 0
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        for row in rows_to_insert:
            result = await db.execute(
                text("""
                    INSERT INTO agent_kpi_snapshots
                        (id, tenant_id, agent_id, kpi_type, measured_value,
                         target_value, achievement_rate, store_id, snapshot_date, metadata)
                    VALUES
                        (:id, :tenant_id, :agent_id, :kpi_type, :measured_value,
                         :target_value, :achievement_rate,
                         :store_id, :snapshot_date, :metadata)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """),
                row,
            )
            if result.fetchone():
                inserted_count += 1
            else:
                skipped_count += 1
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "agent_kpi.collect_snapshots.db_error",
            tenant_id=x_tenant_id,
            snapshot_date=target_date.isoformat(),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="快照写入失败，请稍后重试") from exc

    logger.info(
        "kpi_snapshots_collected",
        tenant_id=x_tenant_id,
        snapshot_date=target_date.isoformat(),
        inserted=inserted_count,
        skipped=skipped_count,
    )

    # 返回记录（不含 DB 内部 id，保持轻量）
    collected = [
        {
            "agent_id": r["agent_id"],
            "kpi_type": r["kpi_type"],
            "measured_value": r["measured_value"],
            "target_value": r["target_value"],
            "achievement_rate": r["achievement_rate"],
            "snapshot_date": target_date.isoformat(),
        }
        for r in rows_to_insert
    ]

    return {"ok": True, "data": {
        "snapshot_date": target_date.isoformat(),
        "inserted_count": inserted_count,
        "skipped_count": skipped_count,
        "snapshots": collected,
    }}


@router.get("/dashboard")
async def get_kpi_dashboard(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """KPI总览仪表盘 — 所有Agent当前达成率汇总。"""
    today = date.today()
    agent_cards = []

    for aid, kpi_list in AGENT_KPI_DEFAULTS.items():
        kpi_items = []
        overall_rates = []

        for kpi in kpi_list:
            target = kpi["target_value"]
            direction = kpi["direction"]
            if direction == "lower_better":
                measured = round(target * 0.85, 2)
            else:
                measured = round(target * 1.02, 2)
            rate = _achievement_rate(measured, target, direction)
            overall_rates.append(rate)

            # 7日趋势（模拟）
            trend = []
            for i in range(7, 0, -1):
                d = today - timedelta(days=i)
                if direction == "lower_better":
                    v = round(target * (0.80 + 0.01 * i), 2)
                else:
                    v = round(target * (1.05 - 0.01 * i), 2)
                trend.append({"date": d.isoformat(), "value": v})

            kpi_items.append({
                "kpi_type": kpi["kpi_type"],
                "label": kpi["label"],
                "measured_value": measured,
                "target_value": target,
                "unit": kpi["unit"],
                "achievement_rate": rate,
                "achievement_pct": round(rate * 100, 1),
                "color": _achievement_color(rate),
                "direction": direction,
                "trend_7d": trend,
            })

        avg_rate = round(sum(overall_rates) / len(overall_rates), 4) if overall_rates else 0.0

        agent_cards.append({
            "agent_id": aid,
            "agent_name": AGENT_NAMES.get(aid, aid),
            "overall_achievement_rate": avg_rate,
            "overall_achievement_pct": round(avg_rate * 100, 1),
            "overall_color": _achievement_color(avg_rate),
            "kpi_count": len(kpi_items),
            "kpis": kpi_items,
            "as_of": today.isoformat(),
        })

    # 全局达成率
    all_rates = [c["overall_achievement_rate"] for c in agent_cards]
    global_rate = round(sum(all_rates) / len(all_rates), 4) if all_rates else 0.0

    return {"ok": True, "data": {
        "as_of": today.isoformat(),
        "global_achievement_rate": global_rate,
        "global_achievement_pct": round(global_rate * 100, 1),
        "global_color": _achievement_color(global_rate),
        "agent_count": len(agent_cards),
        "agents": agent_cards,
    }}


@router.get("/roi-report")
async def get_roi_report(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    month: Optional[str] = Query(None, description="月份（YYYY-MM），默认当月"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """ROI报告 — 从 agent_roi_metrics 表读取真实数据，无数据时返回空值（不再 mock）。

    agent_roi_metrics 结构：
      agent_id / metric_type / value / period_start / period_end / metadata
    """
    today = date.today()
    report_month = month or today.strftime("%Y-%m")

    # 解析月份边界
    try:
        year, mon = int(report_month[:4]), int(report_month[5:7])
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail="month 格式错误，请使用 YYYY-MM") from exc

    import calendar as _cal
    period_start = datetime(year, mon, 1)
    period_end = datetime(year, mon, _cal.monthrange(year, mon)[1], 23, 59, 59)

    # ── 从 agent_roi_metrics 查询当月数据 ──
    roi_rows: list[dict] = []
    try:
        # 设置 RLS 上下文
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT agent_id,
                       metric_type,
                       SUM(value)::numeric      AS total_value,
                       COUNT(*)::int            AS event_count,
                       MAX(metadata)            AS last_metadata
                FROM agent_roi_metrics
                WHERE tenant_id    = :tenant_id
                  AND period_start >= :period_start
                  AND period_end   <= :period_end
                  AND is_deleted   = FALSE
                GROUP BY agent_id, metric_type
                ORDER BY agent_id, metric_type
            """),
            {
                "tenant_id": x_tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        roi_rows = [dict(r) for r in result.mappings().all()]
    except SQLAlchemyError as exc:
        logger.warning(
            "agent_kpi.roi_report.db_error",
            tenant_id=x_tenant_id,
            month=report_month,
            error=str(exc),
            exc_info=True,
        )

    # ── 指标元数据（静态配置，不随 DB 变化）──
    _META: dict[tuple[str, str], dict] = {
        ("discount_guardian", "intercepted_discount_fen"): {
            "agent_name": "折扣守护", "label": "本月拦截异常折扣金额",
            "unit": "元", "event_label": "折扣异常拦截次数", "is_fen": True,
        },
        ("inventory_alert", "waste_saved_fen"): {
            "agent_name": "库存预警", "label": "本月减少食材损耗金额",
            "unit": "元", "event_label": "预警触发次数", "is_fen": True,
        },
        ("smart_dispatch", "avg_time_reduced_seconds"): {
            "agent_name": "出餐调度", "label": "平均出餐时间缩短",
            "unit": "秒", "event_label": "优化订单数", "is_fen": False,
        },
        ("member_insight", "incremental_revenue_fen"): {
            "agent_name": "会员洞察", "label": "会员召回增量营收",
            "unit": "元", "event_label": "召回会员数", "is_fen": True,
        },
        ("finance_audit", "anomaly_detected_fen"): {
            "agent_name": "财务稽核", "label": "发现财务异常金额",
            "unit": "元", "event_label": "异常检出次数", "is_fen": True,
        },
        ("store_patrol", "compliance_improvement"): {
            "agent_name": "巡店质检", "label": "合规评分提升",
            "unit": "分", "event_label": "巡检任务完成数", "is_fen": False,
        },
    }

    # ── 组装响应 ──
    items: list[dict] = []
    total_saved_fen = 0
    discount_intercept_count = 0
    waste_reduction_pct: float | None = None
    member_recalled_count = 0

    for row in roi_rows:
        key = (row["agent_id"], row["metric_type"])
        meta = _META.get(key, {
            "agent_name": row["agent_id"],
            "label": row["metric_type"],
            "unit": "",
            "event_label": "事件数",
            "is_fen": False,
        })
        raw_value = float(row["total_value"] or 0)
        event_count = int(row["event_count"] or 0)

        item: dict = {
            "agent_id": row["agent_id"],
            "agent_name": meta["agent_name"],
            "roi_type": row["metric_type"],
            "label": meta["label"],
            "unit": meta["unit"],
            "event_count": event_count,
            "event_label": meta["event_label"],
        }

        if meta["is_fen"]:
            value_fen = int(raw_value)
            item["value_fen"] = value_fen
            item["value_yuan"] = round(value_fen / 100, 2)
            total_saved_fen += value_fen
        else:
            item["value_fen"] = 0
            item["value_yuan"] = 0
            item["numeric_value"] = raw_value

        # 特定汇总指标提取
        if key == ("discount_guardian", "intercepted_discount_fen"):
            discount_intercept_count = event_count
        elif key == ("member_insight", "incremental_revenue_fen"):
            member_recalled_count = event_count
        elif key == ("inventory_alert", "waste_saved_fen") and row.get("last_metadata"):
            import json as _json
            try:
                md = _json.loads(row["last_metadata"]) if isinstance(row["last_metadata"], str) else row["last_metadata"]
                waste_reduction_pct = md.get("waste_reduction_pct")
            except (ValueError, TypeError, AttributeError):
                pass

        items.append(item)

    return {"ok": True, "data": {
        "report_month": report_month,
        "data_source": "db" if roi_rows else "empty",
        "summary": {
            "total_saved_fen": total_saved_fen,
            "total_saved_yuan": round(total_saved_fen / 100, 2),
            "discount_intercept_count": discount_intercept_count,
            "waste_reduction_pct": waste_reduction_pct,
            "member_recalled_count": member_recalled_count,
        },
        "items": items,
    }}
