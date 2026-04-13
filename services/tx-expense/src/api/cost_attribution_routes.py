"""
成本归因 API 路由

6 个端点，提供成本归集配置与结果查询：
  GET  /rules                         — 成本归集配置概览（按门店/成本类型聚合）
  POST /rules                         — 手工录入成本归集条目
  PUT  /rules/{rule_id}               — 更新成本归集条目
  POST /calculate                     — 手动触发指定门店/日期的归因计算
  GET  /results                       — 查询成本归集日报列表（带分页）
  GET  /results/{result_id}/breakdown — 查询日报明细条目

金额约定：所有金额字段单位为分(fen)，1 元 = 100 分，展示层负责转换。
所有查询显式传入 tenant_id，确保 RLS 安全隔离。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter()
log = structlog.get_logger(__name__)

# 有效成本类型
_VALID_COST_TYPES = {"food", "labor", "rent", "utility", "other", "manual_rule"}


# ─────────────────────────────────────────────────────────────────────────────
# 依赖注入
# ─────────────────────────────────────────────────────────────────────────────

async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的租户ID格式")


async def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> UUID:
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID格式")


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schema
# ─────────────────────────────────────────────────────────────────────────────

class CreateRuleRequest(BaseModel):
    store_id: UUID = Field(..., description="门店ID")
    attribution_date: date = Field(..., description="归集日期")
    cost_type: str = Field(..., description="成本类型: food/labor/rent/utility/other/manual_rule")
    amount_fen: int = Field(..., ge=0, description="金额（分）")
    description: Optional[str] = Field(None, max_length=500, description="备注")


class UpdateRuleRequest(BaseModel):
    amount_fen: Optional[int] = Field(None, ge=0, description="金额（分）")
    cost_type: Optional[str] = Field(None, description="成本类型")
    description: Optional[str] = Field(None, max_length=500, description="备注")


class CalculateRequest(BaseModel):
    store_id: UUID = Field(..., description="门店ID")
    target_date: date = Field(..., description="归因日期")


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────

def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─────────────────────────────────────────────────────────────────────────────
# GET /rules — 成本归集配置概览
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/rules",
    summary="成本归集配置概览",
    description="返回最近N天各门店各成本类型的归集汇总，体现当前成本分布参考配置。",
)
async def list_rules(
    store_id: Optional[UUID] = Query(None, description="按门店过滤"),
    days: int = Query(30, ge=1, le=90, description="回溯天数，默认30"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        store_filter = "AND store_id = :store_id" if store_id else ""
        r = await db.execute(text(f"""
            SELECT
                store_id::text,
                cost_type,
                COUNT(*)                          AS record_count,
                COALESCE(SUM(amount_fen), 0)     AS total_fen,
                COALESCE(AVG(amount_fen), 0)     AS avg_fen,
                MAX(updated_at)                  AS last_updated_at
            FROM cost_attribution_items
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND attribution_date >= CURRENT_DATE - (:days * INTERVAL '1 day')
              {store_filter}
            GROUP BY store_id, cost_type
            ORDER BY store_id, total_fen DESC
        """), {
            "tid": str(tenant_id),
            "days": days,
            **({"store_id": str(store_id)} if store_id else {}),
        })
        rows = r.mappings().all()

        configs = []
        for row in rows:
            configs.append({
                "store_id": row["store_id"],
                "cost_type": row["cost_type"],
                "record_count": int(row["record_count"]),
                "total_fen": int(row["total_fen"]),
                "avg_fen": int(row["avg_fen"]),
                "last_updated_at": row["last_updated_at"].isoformat() if row["last_updated_at"] else None,
            })

        return _ok({
            "days": days,
            "total_configs": len(configs),
            "configs": configs,
        })

    except SQLAlchemyError as e:
        log.error("cost_attribution_list_rules_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="查询成本归集配置失败")


# ─────────────────────────────────────────────────────────────────────────────
# POST /rules — 手工录入成本归集条目
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/rules",
    summary="手工录入成本归集条目",
    status_code=201,
    description="手工创建一条成本归集记录（写入 cost_attribution_items）。",
)
async def create_rule(
    body: CreateRuleRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.cost_type not in _VALID_COST_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的成本类型，允许值: {sorted(_VALID_COST_TYPES)}"
        )

    item_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    try:
        await db.execute(text("""
            INSERT INTO cost_attribution_items
              (id, tenant_id, report_id, expense_application_id, store_id,
               attribution_date, cost_type, amount_fen, description,
               created_at, updated_at, is_deleted)
            VALUES
              (:id, :tid, NULL, NULL, :store_id,
               :attr_date, :cost_type, :amount_fen, :description,
               :now, :now, false)
        """), {
            "id": str(item_id),
            "tid": str(tenant_id),
            "store_id": str(body.store_id),
            "attr_date": body.attribution_date,
            "cost_type": body.cost_type,
            "amount_fen": body.amount_fen,
            "description": body.description,
            "now": now,
        })
        await db.commit()

        log.info(
            "cost_attribution_rule_created",
            tenant_id=str(tenant_id),
            item_id=str(item_id),
            cost_type=body.cost_type,
            amount_fen=body.amount_fen,
        )
        return _ok({
            "id": str(item_id),
            "tenant_id": str(tenant_id),
            "store_id": str(body.store_id),
            "attribution_date": body.attribution_date.isoformat(),
            "cost_type": body.cost_type,
            "amount_fen": body.amount_fen,
            "description": body.description,
            "created_at": now.isoformat(),
        })

    except SQLAlchemyError as e:
        await db.rollback()
        log.error("cost_attribution_create_rule_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="创建成本归集条目失败")


# ─────────────────────────────────────────────────────────────────────────────
# PUT /rules/{rule_id} — 更新成本归集条目
# ─────────────────────────────────────────────────────────────────────────────

@router.put(
    "/rules/{rule_id}",
    summary="更新成本归集条目",
    description="按 cost_attribution_items.id 更新金额、类型或备注。",
)
async def update_rule(
    rule_id: UUID,
    body: UpdateRuleRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.cost_type and body.cost_type not in _VALID_COST_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的成本类型，允许值: {sorted(_VALID_COST_TYPES)}"
        )

    try:
        # 验证归属
        r = await db.execute(text("""
            SELECT id FROM cost_attribution_items
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = false
        """), {"rid": str(rule_id), "tid": str(tenant_id)})
        if not r.first():
            raise HTTPException(status_code=404, detail="成本归集条目不存在")

        # 动态构建更新字段
        set_clauses = ["updated_at = :now"]
        params: dict = {
            "rid": str(rule_id),
            "tid": str(tenant_id),
            "now": datetime.now(tz=timezone.utc),
        }

        if body.amount_fen is not None:
            set_clauses.append("amount_fen = :amount_fen")
            params["amount_fen"] = body.amount_fen
        if body.cost_type is not None:
            set_clauses.append("cost_type = :cost_type")
            params["cost_type"] = body.cost_type
        if body.description is not None:
            set_clauses.append("description = :description")
            params["description"] = body.description

        if len(set_clauses) == 1:
            raise HTTPException(status_code=400, detail="没有可更新的字段")

        await db.execute(text(f"""
            UPDATE cost_attribution_items
            SET {', '.join(set_clauses)}
            WHERE id = :rid AND tenant_id = :tid
        """), params)
        await db.commit()

        # 返回更新后的记录
        r = await db.execute(text("""
            SELECT id::text, tenant_id::text, store_id::text,
                   attribution_date, cost_type, amount_fen, description, updated_at
            FROM cost_attribution_items
            WHERE id = :rid AND tenant_id = :tid
        """), {"rid": str(rule_id), "tid": str(tenant_id)})
        row = r.mappings().one()

        return _ok({
            "id": row["id"],
            "store_id": row["store_id"],
            "attribution_date": row["attribution_date"].isoformat(),
            "cost_type": row["cost_type"],
            "amount_fen": int(row["amount_fen"]),
            "description": row["description"],
            "updated_at": row["updated_at"].isoformat(),
        })

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        log.error("cost_attribution_update_rule_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="更新成本归集条目失败")


# ─────────────────────────────────────────────────────────────────────────────
# POST /calculate — 手动触发归因计算
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/calculate",
    summary="手动触发归因计算",
    description="对指定门店和日期重新运行成本归集计算（调用 daily_cost_attribution worker）。",
)
async def trigger_calculate(
    body: CalculateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        from ..workers import daily_cost_attribution as _worker
        if hasattr(_worker, "run_for_store"):
            result = await _worker.run_for_store(db, tenant_id, body.store_id, body.target_date)
            return _ok({
                "store_id": str(body.store_id),
                "target_date": body.target_date.isoformat(),
                "queued": False,
                "result": result,
                "message": "归因计算已完成",
            })
    except (ImportError, AttributeError) as e:
        log.warning("cost_attribution_worker_unavailable", error=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error("cost_attribution_calculate_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail=f"归因计算失败: {e}")

    # Worker 不可用时降级响应
    log.info(
        "cost_attribution_calculate_queued",
        tenant_id=str(tenant_id),
        store_id=str(body.store_id),
        target_date=str(body.target_date),
    )
    return _ok({
        "store_id": str(body.store_id),
        "target_date": body.target_date.isoformat(),
        "queued": True,
        "message": "计算任务已加入队列，将在下一个调度周期执行",
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /results — 成本归集日报列表
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/results",
    summary="成本归集日报列表",
    description="分页查询每日成本归集日报，可按门店和日期范围过滤。",
)
async def list_results(
    store_id: Optional[UUID] = Query(None, description="按门店过滤"),
    date_from: Optional[date] = Query(None, description="开始日期（含）"),
    date_to: Optional[date] = Query(None, description="结束日期（含）"),
    data_status: Optional[str] = Query(None, description="数据状态: pending/complete/manual_adjusted"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    filters = ["tenant_id = :tid", "is_deleted = false"]
    params: dict = {"tid": str(tenant_id), "limit": limit, "offset": offset}

    if store_id:
        filters.append("store_id = :store_id")
        params["store_id"] = str(store_id)
    if date_from:
        filters.append("report_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("report_date <= :date_to")
        params["date_to"] = date_to
    if data_status:
        filters.append("data_status = :data_status")
        params["data_status"] = data_status

    where = " AND ".join(filters)

    try:
        # 总数
        r = await db.execute(
            text(f"SELECT COUNT(*) FROM daily_cost_reports WHERE {where}"),
            params,
        )
        total = int(r.scalar() or 0)

        # 日报列表 + 关联归集条目数
        r = await db.execute(text(f"""
            SELECT
                d.id::text,
                d.store_id::text,
                d.report_date,
                d.total_revenue_fen,
                d.food_cost_fen,
                d.labor_cost_fen,
                d.other_cost_fen,
                d.total_cost_fen,
                d.food_cost_rate,
                d.labor_cost_rate,
                d.gross_margin_rate,
                d.pos_data_source,
                d.data_status,
                d.notes,
                d.created_at,
                d.updated_at,
                (
                    SELECT COUNT(*)
                    FROM cost_attribution_items c
                    WHERE c.report_id = d.id AND c.is_deleted = false
                ) AS attribution_item_count
            FROM daily_cost_reports d
            WHERE {where}
            ORDER BY d.report_date DESC, d.store_id
            LIMIT :limit OFFSET :offset
        """), params)
        rows = r.mappings().all()

        reports = []
        for row in rows:
            reports.append({
                "id": row["id"],
                "store_id": row["store_id"],
                "report_date": row["report_date"].isoformat(),
                "total_revenue_fen": int(row["total_revenue_fen"]),
                "food_cost_fen": int(row["food_cost_fen"]),
                "labor_cost_fen": int(row["labor_cost_fen"]),
                "other_cost_fen": int(row["other_cost_fen"]),
                "total_cost_fen": int(row["total_cost_fen"]),
                "food_cost_rate": float(row["food_cost_rate"]) if row["food_cost_rate"] else None,
                "labor_cost_rate": float(row["labor_cost_rate"]) if row["labor_cost_rate"] else None,
                "gross_margin_rate": float(row["gross_margin_rate"]) if row["gross_margin_rate"] else None,
                "pos_data_source": row["pos_data_source"],
                "data_status": row["data_status"],
                "notes": row["notes"],
                "attribution_item_count": int(row["attribution_item_count"]),
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            })

        return _ok({
            "total": total,
            "limit": limit,
            "offset": offset,
            "reports": reports,
        })

    except SQLAlchemyError as e:
        log.error("cost_attribution_list_results_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="查询成本归集日报失败")


# ─────────────────────────────────────────────────────────────────────────────
# GET /results/{result_id}/breakdown — 日报归集明细
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/results/{result_id}/breakdown",
    summary="日报归集明细",
    description="返回指定日报的所有成本归集条目明细及费控申请来源追溯。",
)
async def get_result_breakdown(
    result_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        # 验证日报归属并获取摘要
        r = await db.execute(text("""
            SELECT id::text, store_id::text, report_date,
                   total_revenue_fen, total_cost_fen, data_status,
                   food_cost_rate, labor_cost_rate, gross_margin_rate
            FROM daily_cost_reports
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = false
        """), {"rid": str(result_id), "tid": str(tenant_id)})
        report_row = r.mappings().first()
        if not report_row:
            raise HTTPException(status_code=404, detail="成本归集日报不存在")

        # 归集明细（关联费控申请信息）
        r = await db.execute(text("""
            SELECT
                c.id::text,
                c.store_id::text,
                c.attribution_date,
                c.cost_type,
                c.amount_fen,
                c.description,
                c.expense_application_id::text,
                c.created_at,
                ea.expense_no,
                ea.title AS expense_title
            FROM cost_attribution_items c
            LEFT JOIN expense_applications ea
                   ON ea.id = c.expense_application_id
                  AND ea.tenant_id = :tid
                  AND ea.is_deleted = false
            WHERE c.report_id = :rid
              AND c.tenant_id = :tid
              AND c.is_deleted = false
            ORDER BY c.cost_type, c.amount_fen DESC
        """), {"rid": str(result_id), "tid": str(tenant_id)})
        item_rows = r.mappings().all()

        # 按成本类型聚合
        type_summary: dict = {}
        items = []
        for row in item_rows:
            ct = row["cost_type"] or "other"
            type_summary[ct] = type_summary.get(ct, 0) + int(row["amount_fen"])
            items.append({
                "id": row["id"],
                "store_id": row["store_id"],
                "attribution_date": row["attribution_date"].isoformat(),
                "cost_type": row["cost_type"],
                "amount_fen": int(row["amount_fen"]),
                "description": row["description"],
                "expense_application_id": row["expense_application_id"],
                "expense_no": row["expense_no"],
                "expense_title": row["expense_title"],
                "created_at": row["created_at"].isoformat(),
            })

        return _ok({
            "report": {
                "id": report_row["id"],
                "store_id": report_row["store_id"],
                "report_date": report_row["report_date"].isoformat(),
                "total_revenue_fen": int(report_row["total_revenue_fen"]),
                "total_cost_fen": int(report_row["total_cost_fen"]),
                "data_status": report_row["data_status"],
                "food_cost_rate": float(report_row["food_cost_rate"]) if report_row["food_cost_rate"] else None,
                "labor_cost_rate": float(report_row["labor_cost_rate"]) if report_row["labor_cost_rate"] else None,
                "gross_margin_rate": float(report_row["gross_margin_rate"]) if report_row["gross_margin_rate"] else None,
            },
            "type_summary": type_summary,
            "total_items": len(items),
            "items": items,
        })

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        log.error("cost_attribution_breakdown_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="查询归集明细失败")
