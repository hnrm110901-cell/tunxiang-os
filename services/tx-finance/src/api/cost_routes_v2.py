"""成本管理 API 路由 v2

端点：
  POST /api/v1/finance/costs                  — 录入成本记录（手工录入房租/水电等）
  GET  /api/v1/finance/costs                  — 查询成本明细（?store_id=&date=）
  GET  /api/v1/finance/costs/summary          — 成本结构汇总（饼图数据）
  POST /api/v1/finance/configs                — 设置财务配置（成本比例/月租/水电）
  GET  /api/v1/finance/configs/{store_id}     — 查询门店财务配置
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["finance-costs-v2"])

# 合法的 cost_type 枚举
_VALID_COST_TYPES = frozenset(
    {
        "purchase",
        "wastage",
        "live_seafood_death",
        "labor",
        "rent",
        "utilities",
        "other",
    }
)

# 合法的 config_type 枚举
_VALID_CONFIG_TYPES = frozenset(
    {
        "labor_cost_pct",
        "rent_monthly_fen",
        "utilities_daily_fen",
        "target_food_cost_pct",
        "other_daily_opex_fen",
    }
)


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class CreateCostItemRequest(BaseModel):
    store_id: str = Field(..., description="门店ID（UUID）")
    cost_date: str = Field(..., description="成本日期 YYYY-MM-DD")
    cost_type: str = Field(..., description="成本类型：purchase/wastage/live_seafood_death/labor/rent/utilities/other")
    description: Optional[str] = Field(None, max_length=200, description="描述")
    amount_fen: int = Field(..., ge=0, description="金额（分）")
    quantity: Optional[float] = Field(None, ge=0, description="数量")
    unit: Optional[str] = Field(None, max_length=20, description="单位（kg/g/个/份）")
    unit_cost_fen: Optional[int] = Field(None, ge=0, description="单位成本（分）")
    reference_id: Optional[str] = Field(None, description="关联记录ID（UUID，可选）")

    @field_validator("cost_type")
    @classmethod
    def validate_cost_type(cls, v: str) -> str:
        if v not in _VALID_COST_TYPES:
            raise ValueError(f"cost_type 必须为以下之一: {', '.join(sorted(_VALID_COST_TYPES))}")
        return v


class SetFinanceConfigRequest(BaseModel):
    store_id: Optional[str] = Field(None, description="门店ID（NULL=集团级配置）")
    config_type: str = Field(
        ...,
        description="配置类型：labor_cost_pct/rent_monthly_fen/utilities_daily_fen/target_food_cost_pct/other_daily_opex_fen",
    )
    value_fen: Optional[int] = Field(None, ge=0, description="金额类配置（分）")
    value_pct: Optional[float] = Field(None, ge=0, le=100, description="百分比类配置（如 30.0 表示 30%）")
    effective_from: Optional[str] = Field(None, description="生效起始日期 YYYY-MM-DD")
    effective_until: Optional[str] = Field(None, description="失效日期 YYYY-MM-DD")

    @field_validator("config_type")
    @classmethod
    def validate_config_type(cls, v: str) -> str:
        if v not in _VALID_CONFIG_TYPES:
            raise ValueError(f"config_type 必须为以下之一: {', '.join(sorted(_VALID_CONFIG_TYPES))}")
        return v


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _parse_date_param(d: str) -> date:
    if d == "today":
        return date.today()
    try:
        return date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {d}，请使用 YYYY-MM-DD") from exc


# ─── POST /costs — 录入成本记录 ───────────────────────────────────────────────


@router.post("/costs", summary="录入成本记录")
async def create_cost_item(
    body: CreateCostItemRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    手工录入成本记录。

    适用场景：
    - 月末录入当月房租（cost_type=rent）
    - 录入水电账单（cost_type=utilities）
    - 录入食材损耗（cost_type=wastage）
    - 录入活鲜死亡损耗（cost_type=live_seafood_death）

    注：人工成本（labor）通常由系统自动从排班计算，手工录入仅作补充。
    """
    sid = _parse_uuid(body.store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    cost_date = _parse_date_param(body.cost_date)

    ref_id: Optional[str] = None
    if body.reference_id:
        try:
            ref_id = str(uuid.UUID(body.reference_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"reference_id 格式错误: {body.reference_id}") from exc

    result = await db.execute(
        text("""
            INSERT INTO cost_items
            (tenant_id, store_id, cost_date, cost_type, reference_id,
             description, amount_fen, quantity, unit, unit_cost_fen)
            VALUES
            (:tenant_id::UUID, :store_id::UUID, :cost_date, :cost_type,
             :reference_id::UUID,
             :description, :amount_fen, :quantity, :unit, :unit_cost_fen)
            RETURNING id
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "cost_date": cost_date.isoformat(),
            "cost_type": body.cost_type,
            "reference_id": ref_id,
            "description": body.description,
            "amount_fen": body.amount_fen,
            "quantity": body.quantity,
            "unit": body.unit,
            "unit_cost_fen": body.unit_cost_fen,
        },
    )
    new_id = result.scalar_one()
    await db.commit()

    logger.info(
        "cost_item.created",
        tenant_id=str(tid),
        store_id=str(sid),
        cost_type=body.cost_type,
        amount_fen=body.amount_fen,
    )

    return {
        "ok": True,
        "data": {
            "id": str(new_id),
            "store_id": body.store_id,
            "cost_date": str(cost_date),
            "cost_type": body.cost_type,
            "amount_fen": body.amount_fen,
        },
    }


# ─── GET /costs — 查询成本明细 ────────────────────────────────────────────────


@router.get("/costs", summary="查询成本明细")
async def get_cost_items(
    store_id: str = Query(..., description="门店ID"),
    cost_date: str = Query("today", alias="date", description="成本日期 YYYY-MM-DD 或 today"),
    cost_type: Optional[str] = Query(None, description="成本类型过滤（可选）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    查询指定门店指定日期的成本明细列表。

    支持按 cost_type 过滤，分页返回。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(cost_date)

    if cost_type and cost_type not in _VALID_COST_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"cost_type 必须为以下之一: {', '.join(sorted(_VALID_COST_TYPES))}",
        )

    type_filter = "AND cost_type = :cost_type" if cost_type else ""
    offset = (page - 1) * size

    # 查询总数
    count_result = await db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM cost_items
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND cost_date = :cost_date
              AND is_deleted = FALSE
              {type_filter}
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "cost_date": biz_date.isoformat(),
            **({"cost_type": cost_type} if cost_type else {}),
        },
    )
    total = count_result.scalar()

    # 查询明细
    items_result = await db.execute(
        text(f"""
            SELECT id, cost_date, cost_type, description,
                   amount_fen, quantity, unit, unit_cost_fen,
                   reference_id, created_at
            FROM cost_items
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND cost_date = :cost_date
              AND is_deleted = FALSE
              {type_filter}
            ORDER BY created_at DESC
            LIMIT :size OFFSET :offset
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "cost_date": biz_date.isoformat(),
            "size": size,
            "offset": offset,
            **({"cost_type": cost_type} if cost_type else {}),
        },
    )
    rows = items_result.fetchall()

    items = [
        {
            "id": str(r[0]),
            "cost_date": str(r[1]),
            "cost_type": r[2],
            "description": r[3],
            "amount_fen": r[4],
            "quantity": float(r[5]) if r[5] is not None else None,
            "unit": r[6],
            "unit_cost_fen": r[7],
            "reference_id": str(r[8]) if r[8] else None,
            "created_at": str(r[9]),
        }
        for r in rows
    ]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


# ─── GET /costs/summary — 成本结构汇总 ───────────────────────────────────────


@router.get("/costs/summary", summary="成本结构汇总（饼图数据）")
async def get_cost_summary(
    store_id: str = Query(..., description="门店ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    成本结构汇总，用于饼图展示各类成本占比。

    返回各 cost_type 的合计金额和占比，附总成本额。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    start = _parse_date_param(start_date)
    end = _parse_date_param(end_date)

    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")
    if (end - start).days > 366:
        raise HTTPException(status_code=400, detail="查询区间不能超过 366 天")

    result = await db.execute(
        text("""
            SELECT
                cost_type,
                SUM(amount_fen) AS total_fen
            FROM cost_items
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND cost_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
            GROUP BY cost_type
            ORDER BY total_fen DESC
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    rows = result.fetchall()

    total_fen = sum(int(r[1]) for r in rows)
    breakdown = [
        {
            "cost_type": r[0],
            "amount_fen": int(r[1]),
            "ratio": round(int(r[1]) / total_fen, 4) if total_fen > 0 else 0.0,
        }
        for r in rows
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "start_date": str(start),
            "end_date": str(end),
            "total_cost_fen": total_fen,
            "breakdown": breakdown,
        },
    }


# ─── POST /configs — 设置财务配置 ─────────────────────────────────────────────


@router.post("/configs", summary="设置财务配置")
async def set_finance_config(
    body: SetFinanceConfigRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    设置门店财务配置（成本比例/月租/水电等）。

    配置类型说明：
    - labor_cost_pct:       人工成本目标比率（value_pct，如 25.0 = 25%）
    - rent_monthly_fen:     月租金（value_fen，分）
    - utilities_daily_fen:  日水电预算（value_fen，分）
    - target_food_cost_pct: 食材成本目标比率（value_pct，如 30.0 = 30%）
    - other_daily_opex_fen: 日其他运营费（value_fen，分）

    store_id 为 NULL 时设置集团级通用配置，门店级配置优先级更高。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    sid_str: Optional[str] = None
    if body.store_id:
        sid = _parse_uuid(body.store_id, "store_id")
        sid_str = str(sid)

    # 验证金额/比率二选一填写
    is_pct_type = body.config_type in ("labor_cost_pct", "target_food_cost_pct")
    if is_pct_type and body.value_pct is None and body.value_fen is None:
        raise HTTPException(status_code=400, detail=f"{body.config_type} 必须提供 value_pct")
    if not is_pct_type and body.value_fen is None and body.value_pct is None:
        raise HTTPException(status_code=400, detail=f"{body.config_type} 必须提供 value_fen")

    effective_from: Optional[str] = None
    effective_until: Optional[str] = None
    if body.effective_from:
        effective_from = _parse_date_param(body.effective_from).isoformat()
    if body.effective_until:
        effective_until = _parse_date_param(body.effective_until).isoformat()

    result = await db.execute(
        text("""
            INSERT INTO finance_configs
            (tenant_id, store_id, config_type, value_fen, value_pct,
             effective_from, effective_until)
            VALUES
            (:tenant_id::UUID,
             :store_id::UUID,
             :config_type, :value_fen, :value_pct,
             :effective_from::DATE, :effective_until::DATE)
            RETURNING id
        """),
        {
            "tenant_id": str(tid),
            "store_id": sid_str,
            "config_type": body.config_type,
            "value_fen": body.value_fen,
            "value_pct": body.value_pct,
            "effective_from": effective_from,
            "effective_until": effective_until,
        },
    )
    new_id = result.scalar_one()
    await db.commit()

    logger.info(
        "finance_config.created",
        tenant_id=str(tid),
        store_id=sid_str,
        config_type=body.config_type,
    )

    return {
        "ok": True,
        "data": {
            "id": str(new_id),
            "store_id": body.store_id,
            "config_type": body.config_type,
            "value_fen": body.value_fen,
            "value_pct": body.value_pct,
        },
    }


# ─── GET /configs/{store_id} — 查询财务配置 ──────────────────────────────────


@router.get("/configs/{store_id}", summary="查询门店财务配置")
async def get_finance_configs(
    store_id: str,
    as_of_date: str = Query("today", alias="date", description="查询生效日期，默认今天"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    查询指定门店的所有财务配置（按配置类型分组，返回当前生效版本）。

    包含门店专属配置和集团级通用配置（门店级优先）。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    cfg_date = _parse_date_param(as_of_date)

    result = await db.execute(
        text("""
            SELECT DISTINCT ON (config_type)
                id, config_type, value_fen, value_pct,
                effective_from, effective_until, store_id
            FROM finance_configs
            WHERE tenant_id = :tenant_id::UUID
              AND (store_id = :store_id::UUID OR store_id IS NULL)
              AND (effective_from IS NULL OR effective_from <= :cfg_date)
              AND (effective_until IS NULL OR effective_until >= :cfg_date)
              AND is_deleted = FALSE
            ORDER BY
                config_type,
                CASE WHEN store_id IS NOT NULL THEN 0 ELSE 1 END,
                effective_from DESC NULLS LAST
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "cfg_date": cfg_date.isoformat(),
        },
    )
    rows = result.fetchall()

    configs = [
        {
            "id": str(r[0]),
            "config_type": r[1],
            "value_fen": r[2],
            "value_pct": float(r[3]) if r[3] is not None else None,
            "effective_from": str(r[4]) if r[4] else None,
            "effective_until": str(r[5]) if r[5] else None,
            "scope": "store" if r[6] is not None else "tenant",
        }
        for r in rows
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "as_of_date": str(cfg_date),
            "configs": configs,
        },
    }
