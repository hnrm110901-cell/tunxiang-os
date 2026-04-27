"""DRI工单中心 API 路由（Human Hub Sprint 1）

端点列表：
  GET    /api/v1/dri-workorders                                    工单列表（多维筛选+分页）
  POST   /api/v1/dri-workorders                                    创建工单
  GET    /api/v1/dri-workorders/statistics                         工单统计看板
  GET    /api/v1/dri-workorders/my-orders                          我的工单
  GET    /api/v1/dri-workorders/{order_id}                         工单详情
  PUT    /api/v1/dri-workorders/{order_id}                         更新工单字段（非状态）
  PUT    /api/v1/dri-workorders/{order_id}/transition              工单状态流转
  POST   /api/v1/dri-workorders/{order_id}/actions                 追加行动项
  PUT    /api/v1/dri-workorders/{order_id}/actions/{idx}/complete  完成行动项
  DELETE /api/v1/dri-workorders/{order_id}                         软删除工单（仅draft）

数据源：dri_work_orders + stores + employees

状态机：
  draft → assigned → in_progress → completed → closed
                                 → cancelled
  assigned → draft (退回)
  in_progress → assigned (退回)

统一响应格式: {"ok": bool, "data": {}, "error": null}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/dri-workorders", tags=["dri-workorders"])


# ── 状态机 ──────────────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["assigned"],
    "assigned": ["in_progress", "draft"],  # draft = 退回
    "in_progress": ["completed", "cancelled", "assigned"],  # assigned = 退回
    "completed": ["closed"],
    "closed": [],
    "cancelled": [],
}

VALID_STATUSES = {"draft", "assigned", "in_progress", "completed", "closed", "cancelled"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_ORDER_TYPES = {"recruit", "fill_gap", "training", "retention", "reform", "new_store"}
VALID_SOURCES = {"manual", "ai_alert", "system"}


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _generate_order_no(db: AsyncSession) -> str:
    """生成工单编号：DRI-YYYYMMDD-0001"""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"DRI-{today_str}-"

    result = await db.execute(
        text("""
            SELECT MAX(order_no) AS max_no
            FROM dri_work_orders
            WHERE order_no LIKE :prefix || '%'
              AND is_deleted = FALSE
        """),
        {"prefix": prefix},
    )
    row = result.fetchone()
    max_no = row._mapping["max_no"] if row else None

    if max_no:
        seq = int(max_no.split("-")[-1]) + 1
    else:
        seq = 1

    return f"{prefix}{seq:04d}"


def _parse_jsonb(val: Any) -> Any:
    """安全解析 JSONB 字段"""
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def _serialize_dates(d: dict, keys: tuple[str, ...]) -> None:
    """将指定日期字段转为字符串"""
    for key in keys:
        if d.get(key):
            d[key] = str(d[key])


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateWorkOrderReq(BaseModel):
    order_type: str = Field(..., description="工单类型: recruit/fill_gap/training/retention/reform/new_store")
    store_id: str = Field(..., description="门店ID")
    title: str = Field(..., description="工单标题")
    description: Optional[str] = Field(None, description="描述")
    severity: str = Field(default="medium", description="严重度: critical/high/medium/low")
    dri_user_id: Optional[str] = Field(None, description="DRI责任人ID")
    collaborators: Optional[List[dict]] = Field(None, description="协作者列表(JSONB)")
    actions: Optional[List[dict]] = Field(None, description="行动项列表(JSONB)")
    due_date: Optional[date] = Field(None, description="截止日期")
    source: Optional[str] = Field(default="manual", description="来源: manual/ai_alert/system")
    source_ref_id: Optional[str] = Field(None, description="来源关联ID")


class UpdateWorkOrderReq(BaseModel):
    title: Optional[str] = Field(None, description="工单标题")
    description: Optional[str] = Field(None, description="描述")
    severity: Optional[str] = Field(None, description="严重度")
    dri_user_id: Optional[str] = Field(None, description="DRI责任人ID")
    collaborators: Optional[List[dict]] = Field(None, description="协作者列表")
    actions: Optional[List[dict]] = Field(None, description="行动项列表")
    due_date: Optional[date] = Field(None, description="截止日期")


class TransitionReq(BaseModel):
    target_status: str = Field(..., description="目标状态")
    reason: Optional[str] = Field(None, description="流转原因/备注（取消时必填）")
    resolution: Optional[str] = Field(None, description="解决说明（完成时必填）")


class AddActionReq(BaseModel):
    action: str = Field(..., description="行动项内容")
    assigned_to: Optional[str] = Field(None, description="指派人ID")
    due_date: Optional[date] = Field(None, description="行动项截止日期")


class CompleteActionReq(BaseModel):
    result: Optional[str] = Field(None, description="完成结果说明")


# ── 端点 ──────────────────────────────────────────────────────────────────────


# ---- 1. 工单列表 ----


@router.get("")
async def list_work_orders(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店筛选"),
    order_type: Optional[str] = Query(None, description="工单类型"),
    severity: Optional[str] = Query(None, description="严重度"),
    status: Optional[str] = Query(None, description="状态（支持逗号分隔多值，如 draft,assigned）"),
    dri_user_id: Optional[str] = Query(None, description="DRI责任人"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """工单列表（多维筛选+分页），按严重度降序+截止日期升序排列"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["wo.is_deleted = FALSE"]
    params: dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

    if store_id:
        conditions.append("wo.store_id = :store_id")
        params["store_id"] = store_id
    if order_type:
        conditions.append("wo.order_type = :order_type")
        params["order_type"] = order_type
    if severity:
        conditions.append("wo.severity = :severity")
        params["severity"] = severity
    if status:
        # 支持逗号分隔多值筛选
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if len(status_list) == 1:
            conditions.append("wo.status = :status_val")
            params["status_val"] = status_list[0]
        elif len(status_list) > 1:
            placeholders = []
            for i, sv in enumerate(status_list):
                key = f"status_{i}"
                placeholders.append(f":{key}")
                params[key] = sv
            conditions.append(f"wo.status IN ({', '.join(placeholders)})")
    if dri_user_id:
        conditions.append("wo.dri_user_id = :dri_user_id")
        params["dri_user_id"] = dri_user_id

    where_clause = " AND ".join(conditions)

    count_sql = f"SELECT COUNT(*) FROM dri_work_orders wo WHERE {where_clause}"
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    list_sql = f"""
        SELECT
            wo.id::text AS order_id,
            wo.order_no,
            wo.order_type,
            wo.store_id::text,
            wo.title,
            wo.description,
            wo.severity,
            wo.status,
            wo.dri_user_id::text,
            wo.collaborators,
            wo.actions,
            wo.due_date,
            wo.completed_at,
            wo.resolution,
            wo.source,
            wo.source_ref_id::text,
            wo.created_at,
            wo.updated_at,
            s.name AS store_name,
            e.emp_name AS dri_user_name
        FROM dri_work_orders wo
        LEFT JOIN stores s ON s.id = wo.store_id AND s.is_deleted = FALSE
        LEFT JOIN employees e ON e.id = wo.dri_user_id AND e.is_deleted = FALSE
        WHERE {where_clause}
        ORDER BY
            CASE wo.severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
            END,
            wo.due_date ASC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    items = []
    for r in result.fetchall():
        d = dict(r._mapping)
        d["collaborators"] = _parse_jsonb(d.get("collaborators"))
        d["actions"] = _parse_jsonb(d.get("actions"))
        _serialize_dates(d, ("due_date", "completed_at", "created_at", "updated_at"))
        items.append(d)

    log.info("list_dri_work_orders", tenant_id=tenant_id, total=total, page=page)
    return _ok({"items": items, "total": total, "page": page, "size": size})


# ---- 2. 创建工单 ----


@router.post("")
async def create_work_order(
    request: Request,
    req: CreateWorkOrderReq,
    db: AsyncSession = Depends(get_db),
):
    """创建工单，自动生成 DRI-YYYYMMDD-序号 编号"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if req.severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"severity 须为 {sorted(VALID_SEVERITIES)} 之一",
        )
    if req.order_type not in VALID_ORDER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"order_type 须为 {sorted(VALID_ORDER_TYPES)} 之一",
        )
    if req.source and req.source not in VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"source 须为 {sorted(VALID_SOURCES)} 之一",
        )

    now = datetime.now(timezone.utc)
    order_id = str(uuid4())
    order_no = await _generate_order_no(db)

    result = await db.execute(
        text("""
            INSERT INTO dri_work_orders (
                id, tenant_id, order_no, order_type, store_id, title,
                description, severity, status, dri_user_id, collaborators,
                actions, due_date, source, source_ref_id,
                is_deleted, created_at, updated_at
            ) VALUES (
                :id, :tid, :order_no, :order_type, :store_id, :title,
                :description, :severity, 'draft', :dri_user_id, :collaborators,
                :actions, :due_date, :source, :source_ref_id,
                FALSE, :now, :now
            )
            RETURNING id::text AS order_id, order_no
        """),
        {
            "id": order_id,
            "tid": tenant_id,
            "order_no": order_no,
            "order_type": req.order_type,
            "store_id": req.store_id,
            "title": req.title,
            "description": req.description,
            "severity": req.severity,
            "dri_user_id": req.dri_user_id,
            "collaborators": json.dumps(req.collaborators) if req.collaborators else None,
            "actions": json.dumps(req.actions) if req.actions else None,
            "due_date": req.due_date,
            "source": req.source or "manual",
            "source_ref_id": req.source_ref_id,
            "now": now,
        },
    )
    row = result.fetchone()
    await db.commit()

    log.info(
        "create_dri_work_order",
        tenant_id=tenant_id,
        order_id=order_id,
        order_no=order_no,
        order_type=req.order_type,
        store_id=req.store_id,
    )
    return _ok(
        {
            "order_id": row._mapping["order_id"],
            "order_no": row._mapping["order_no"],
            "status": "draft",
            "created_at": now.isoformat(),
        }
    )


# ---- 7. 工单统计看板 ----
# 注意：statistics 和 my-orders 路由必须在 {order_id} 之前注册


@router.get("/statistics")
async def get_work_order_statistics(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店筛选"),
    date_from: Optional[date] = Query(None, description="起始日期"),
    date_to: Optional[date] = Query(None, description="截止日期"),
    db: AsyncSession = Depends(get_db),
):
    """工单统计看板：按状态/类型/严重度分布 + 逾期数 + 平均解决天数"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 构建公共过滤条件
    extra_filters = ""
    params: dict[str, Any] = {}
    if store_id:
        extra_filters += " AND wo.store_id = :store_id"
        params["store_id"] = store_id
    if date_from:
        extra_filters += " AND wo.created_at >= :date_from"
        params["date_from"] = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    if date_to:
        extra_filters += " AND wo.created_at <= :date_to"
        params["date_to"] = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)

    # 按状态统计
    status_sql = text(f"""
        SELECT
            COUNT(*) FILTER (WHERE wo.status = 'draft') AS draft,
            COUNT(*) FILTER (WHERE wo.status = 'assigned') AS assigned,
            COUNT(*) FILTER (WHERE wo.status = 'in_progress') AS in_progress,
            COUNT(*) FILTER (WHERE wo.status = 'completed') AS completed,
            COUNT(*) FILTER (WHERE wo.status = 'closed') AS closed,
            COUNT(*) FILTER (WHERE wo.status = 'cancelled') AS cancelled
        FROM dri_work_orders wo
        WHERE wo.is_deleted = FALSE {extra_filters}
    """)
    status_result = await db.execute(status_sql, params)
    status_row = dict(status_result.fetchone()._mapping)
    by_status = {k: int(v or 0) for k, v in status_row.items()}

    # 按工单类型统计
    type_sql = text(f"""
        SELECT wo.order_type, COUNT(*) AS count
        FROM dri_work_orders wo
        WHERE wo.is_deleted = FALSE {extra_filters}
        GROUP BY wo.order_type
    """)
    type_result = await db.execute(type_sql, params)
    by_type_raw = {r._mapping["order_type"]: int(r._mapping["count"]) for r in type_result.fetchall()}
    by_type = {t: by_type_raw.get(t, 0) for t in VALID_ORDER_TYPES}

    # 按严重度统计
    sev_sql = text(f"""
        SELECT wo.severity, COUNT(*) AS count
        FROM dri_work_orders wo
        WHERE wo.is_deleted = FALSE {extra_filters}
        GROUP BY wo.severity
    """)
    sev_result = await db.execute(sev_sql, params)
    by_sev_raw = {r._mapping["severity"]: int(r._mapping["count"]) for r in sev_result.fetchall()}
    by_severity = {s: by_sev_raw.get(s, 0) for s in VALID_SEVERITIES}

    # 逾期数量
    overdue_sql = text(f"""
        SELECT COUNT(*) AS overdue_count
        FROM dri_work_orders wo
        WHERE wo.is_deleted = FALSE
          AND wo.due_date < CURRENT_DATE
          AND wo.status NOT IN ('completed', 'closed', 'cancelled')
          {extra_filters}
    """)
    overdue_result = await db.execute(overdue_sql, params)
    overdue_count = int(overdue_result.scalar() or 0)

    # 平均解决天数
    avg_sql = text(f"""
        SELECT COALESCE(
            AVG(EXTRACT(EPOCH FROM (wo.completed_at - wo.created_at)) / 86400),
            0
        ) AS avg_days
        FROM dri_work_orders wo
        WHERE wo.is_deleted = FALSE
          AND wo.status = 'completed'
          AND wo.completed_at IS NOT NULL
          {extra_filters}
    """)
    avg_result = await db.execute(avg_sql, params)
    avg_resolution_days = round(float(avg_result.scalar() or 0), 2)

    log.info("dri_workorder_statistics", tenant_id=tenant_id)
    return _ok(
        {
            "by_status": by_status,
            "by_type": by_type,
            "by_severity": by_severity,
            "overdue_count": overdue_count,
            "avg_resolution_days": avg_resolution_days,
        }
    )


# ---- 8. 我的工单 ----


@router.get("/my-orders")
async def list_my_work_orders(
    request: Request,
    user_id: Optional[str] = Query(None, description="用户ID（不传则从请求上下文取）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """我的工单：包括我是DRI责任人的 + 我在协作者列表中的"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 优先用参数，否则从 request.state 取
    uid = user_id or getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(status_code=400, detail="user_id 参数必填")

    params: dict[str, Any] = {
        "uid": uid,
        "check": json.dumps([{"user_id": uid}]),
        "limit": size,
        "offset": (page - 1) * size,
    }

    where_clause = """
        wo.is_deleted = FALSE
        AND (
            wo.dri_user_id = :uid
            OR wo.collaborators @> :check::jsonb
        )
    """

    count_sql = f"SELECT COUNT(*) FROM dri_work_orders wo WHERE {where_clause}"
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    list_sql = f"""
        SELECT
            wo.id::text AS order_id,
            wo.order_no,
            wo.order_type,
            wo.store_id::text,
            wo.title,
            wo.severity,
            wo.status,
            wo.dri_user_id::text,
            wo.collaborators,
            wo.due_date,
            wo.created_at,
            wo.updated_at,
            s.name AS store_name,
            e.emp_name AS dri_user_name,
            CASE WHEN wo.dri_user_id = :uid THEN 'dri' ELSE 'collaborator' END AS my_role
        FROM dri_work_orders wo
        LEFT JOIN stores s ON s.id = wo.store_id AND s.is_deleted = FALSE
        LEFT JOIN employees e ON e.id = wo.dri_user_id AND e.is_deleted = FALSE
        WHERE {where_clause}
        ORDER BY
            CASE wo.severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
            END,
            wo.due_date ASC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    items = []
    for r in result.fetchall():
        d = dict(r._mapping)
        d["collaborators"] = _parse_jsonb(d.get("collaborators"))
        _serialize_dates(d, ("due_date", "created_at", "updated_at"))
        items.append(d)

    log.info("list_my_work_orders", tenant_id=tenant_id, user_id=uid, total=total)
    return _ok({"items": items, "total": total, "page": page, "size": size})


# ---- 3. 工单详情 ----


@router.get("/{order_id}")
async def get_work_order_detail(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """工单详情（含门店名称、DRI人名、完整行动项历史）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            wo.id::text AS order_id,
            wo.order_no,
            wo.order_type,
            wo.store_id::text,
            wo.title,
            wo.description,
            wo.severity,
            wo.status,
            wo.dri_user_id::text,
            wo.collaborators,
            wo.actions,
            wo.due_date,
            wo.completed_at,
            wo.resolution,
            wo.source,
            wo.source_ref_id::text,
            wo.created_at,
            wo.updated_at,
            s.name AS store_name,
            e.emp_name AS dri_user_name
        FROM dri_work_orders wo
        LEFT JOIN stores s ON s.id = wo.store_id AND s.is_deleted = FALSE
        LEFT JOIN employees e ON e.id = wo.dri_user_id AND e.is_deleted = FALSE
        WHERE wo.id = :order_id AND wo.is_deleted = FALSE
    """)

    result = await db.execute(sql, {"order_id": order_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="工单不存在")

    data = dict(row._mapping)
    data["collaborators"] = _parse_jsonb(data.get("collaborators"))
    data["actions"] = _parse_jsonb(data.get("actions"))
    _serialize_dates(data, ("due_date", "completed_at", "created_at", "updated_at"))

    log.info("get_dri_work_order", tenant_id=tenant_id, order_id=order_id)
    return _ok(data)


# ---- 4. 更新工单 ----


@router.put("/{order_id}")
async def update_work_order(
    request: Request,
    order_id: str,
    req: UpdateWorkOrderReq,
    db: AsyncSession = Depends(get_db),
):
    """更新工单字段（不含状态，状态请用 transition 端点）。closed/cancelled 状态不可更新。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 先查当前状态，校验是否可编辑
    check = await db.execute(
        text("""
            SELECT status FROM dri_work_orders
            WHERE id = :order_id AND is_deleted = FALSE
        """),
        {"order_id": order_id},
    )
    check_row = check.fetchone()
    if not check_row:
        raise HTTPException(status_code=404, detail="工单不存在")

    current_status = check_row._mapping["status"]
    if current_status in ("closed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"工单状态为 '{current_status}'，不可编辑",
        )

    now = datetime.now(timezone.utc)
    set_clauses = ["updated_at = :now"]
    params: dict[str, Any] = {"order_id": order_id, "now": now}

    if req.title is not None:
        set_clauses.append("title = :title")
        params["title"] = req.title
    if req.description is not None:
        set_clauses.append("description = :description")
        params["description"] = req.description
    if req.severity is not None:
        if req.severity not in VALID_SEVERITIES:
            raise HTTPException(
                status_code=400,
                detail=f"severity 须为 {sorted(VALID_SEVERITIES)} 之一",
            )
        set_clauses.append("severity = :severity")
        params["severity"] = req.severity
    if req.dri_user_id is not None:
        set_clauses.append("dri_user_id = :dri_user_id")
        params["dri_user_id"] = req.dri_user_id
    if req.collaborators is not None:
        set_clauses.append("collaborators = :collaborators")
        params["collaborators"] = json.dumps(req.collaborators)
    if req.actions is not None:
        set_clauses.append("actions = :actions")
        params["actions"] = json.dumps(req.actions)
    if req.due_date is not None:
        set_clauses.append("due_date = :due_date")
        params["due_date"] = req.due_date

    if len(set_clauses) == 1:
        raise HTTPException(status_code=400, detail="至少提供一个更新字段")

    set_sql = ", ".join(set_clauses)
    result = await db.execute(
        text(f"""
            UPDATE dri_work_orders
            SET {set_sql}
            WHERE id = :order_id AND is_deleted = FALSE
            RETURNING id::text AS order_id
        """),
        params,
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="工单不存在")

    log.info("update_dri_work_order", tenant_id=tenant_id, order_id=order_id)
    return _ok({"order_id": order_id, "updated_at": now.isoformat()})


# ---- 5. 状态流转 ----


@router.put("/{order_id}/transition")
async def transition_work_order(
    request: Request,
    order_id: str,
    req: TransitionReq,
    db: AsyncSession = Depends(get_db),
):
    """工单状态流转（严格状态机校验）

    状态机:
      draft → assigned → in_progress → completed → closed
                                      → cancelled
      assigned → draft (退回)
      in_progress → assigned (退回)

    约束:
      - completed 时必须填写 resolution
      - cancelled 时必须填写 reason
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    target = req.target_status
    if target not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"target_status 须为 {sorted(VALID_STATUSES)} 之一",
        )

    # 查询当前状态
    current = await db.execute(
        text("""
            SELECT status FROM dri_work_orders
            WHERE id = :order_id AND is_deleted = FALSE
        """),
        {"order_id": order_id},
    )
    current_row = current.fetchone()
    if not current_row:
        raise HTTPException(status_code=404, detail="工单不存在")

    current_status = current_row._mapping["status"]

    # 验证状态转换
    allowed = VALID_TRANSITIONS.get(current_status, [])
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"状态 '{current_status}' 不可转换为 '{target}'，允许: {allowed}",
        )

    # 完成时必须填写 resolution
    if target == "completed" and not req.resolution:
        raise HTTPException(status_code=400, detail="完成工单时必须填写 resolution")

    # 取消时必须填写 reason
    if target == "cancelled" and not req.reason:
        raise HTTPException(status_code=400, detail="取消工单时必须填写 reason")

    now = datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "order_id": order_id,
        "target": target,
        "now": now,
    }

    extra_sets = ""
    if target == "completed":
        extra_sets = ", completed_at = :now, resolution = :resolution"
        params["resolution"] = req.resolution
    elif target == "cancelled":
        extra_sets = ", resolution = :resolution"
        params["resolution"] = req.reason  # 存到 resolution 字段作为取消原因
    elif req.resolution:
        extra_sets = ", resolution = :resolution"
        params["resolution"] = req.resolution

    result = await db.execute(
        text(f"""
            UPDATE dri_work_orders
            SET status = :target, updated_at = :now {extra_sets}
            WHERE id = :order_id AND is_deleted = FALSE
            RETURNING id::text AS order_id, status
        """),
        params,
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="工单不存在")

    log.info(
        "transition_dri_work_order",
        tenant_id=tenant_id,
        order_id=order_id,
        from_status=current_status,
        to_status=target,
        reason=req.reason,
    )
    return _ok(
        {
            "order_id": order_id,
            "from_status": current_status,
            "to_status": target,
            "updated_at": now.isoformat(),
        }
    )


# ---- 9. 添加行动项 ----


@router.post("/{order_id}/actions")
async def add_action_item(
    request: Request,
    order_id: str,
    req: AddActionReq,
    db: AsyncSession = Depends(get_db),
):
    """追加行动项到工单 actions JSONB 数组"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    new_action = {
        "action": req.action,
        "assigned_to": req.assigned_to,
        "due_date": str(req.due_date) if req.due_date else None,
        "status": "pending",
        "result": None,
        "completed_at": None,
        "added_at": now.isoformat(),
    }

    result = await db.execute(
        text("""
            UPDATE dri_work_orders
            SET actions = COALESCE(actions, '[]'::jsonb) || :new_action::jsonb,
                updated_at = :now
            WHERE id = :order_id AND is_deleted = FALSE
            RETURNING id::text AS order_id, actions
        """),
        {
            "order_id": order_id,
            "new_action": json.dumps(new_action),
            "now": now,
        },
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="工单不存在")

    updated_actions = _parse_jsonb(row._mapping["actions"])

    log.info(
        "add_dri_work_order_action",
        tenant_id=tenant_id,
        order_id=order_id,
        action=req.action,
    )
    return _ok(
        {
            "order_id": order_id,
            "actions": updated_actions,
            "added_action": new_action,
        }
    )


# ---- 10. 完成行动项 ----


@router.put("/{order_id}/actions/{action_index}/complete")
async def complete_action_item(
    request: Request,
    order_id: str,
    action_index: int,
    req: CompleteActionReq,
    db: AsyncSession = Depends(get_db),
):
    """完成指定行动项（通过 jsonb_set 更新 JSONB 数组中指定索引的元素）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    # 先查询当前 actions 长度以验证 index
    check = await db.execute(
        text("""
            SELECT jsonb_array_length(COALESCE(actions, '[]'::jsonb)) AS len
            FROM dri_work_orders
            WHERE id = :order_id AND is_deleted = FALSE
        """),
        {"order_id": order_id},
    )
    check_row = check.fetchone()
    if not check_row:
        raise HTTPException(status_code=404, detail="工单不存在")

    actions_len = check_row._mapping["len"]
    if action_index < 0 or action_index >= actions_len:
        raise HTTPException(
            status_code=400,
            detail=f"action_index {action_index} 越界，当前共 {actions_len} 个行动项",
        )

    # 使用嵌套 jsonb_set 更新 status / result / completed_at
    result = await db.execute(
        text("""
            UPDATE dri_work_orders
            SET actions = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            actions,
                            :path_status,
                            :val_status
                        ),
                        :path_result,
                        :val_result
                    ),
                    :path_completed,
                    :val_completed
                ),
                updated_at = :now
            WHERE id = :order_id AND is_deleted = FALSE
            RETURNING id::text AS order_id, actions
        """),
        {
            "order_id": order_id,
            "path_status": f"{{{action_index},status}}",
            "val_status": json.dumps("done"),
            "path_result": f"{{{action_index},result}}",
            "val_result": json.dumps(req.result),
            "path_completed": f"{{{action_index},completed_at}}",
            "val_completed": json.dumps(now.isoformat()),
            "now": now,
        },
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="工单不存在")

    updated_actions = _parse_jsonb(row._mapping["actions"])

    log.info(
        "complete_dri_work_order_action",
        tenant_id=tenant_id,
        order_id=order_id,
        action_index=action_index,
    )
    return _ok(
        {
            "order_id": order_id,
            "action_index": action_index,
            "status": "done",
            "result": req.result,
            "completed_at": now.isoformat(),
            "actions": updated_actions,
        }
    )


# ---- 6. 软删除 ----


@router.delete("/{order_id}")
async def delete_work_order(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """软删除工单（仅 draft 状态允许删除）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 先查状态，仅 draft 可删
    check = await db.execute(
        text("""
            SELECT status FROM dri_work_orders
            WHERE id = :order_id AND is_deleted = FALSE
        """),
        {"order_id": order_id},
    )
    check_row = check.fetchone()
    if not check_row:
        raise HTTPException(status_code=404, detail="工单不存在")

    current_status = check_row._mapping["status"]
    if current_status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"仅 draft 状态可删除，当前状态为 '{current_status}'",
        )

    now = datetime.now(timezone.utc)
    result = await db.execute(
        text("""
            UPDATE dri_work_orders
            SET is_deleted = TRUE, updated_at = :now
            WHERE id = :order_id AND is_deleted = FALSE AND status = 'draft'
            RETURNING id::text AS order_id
        """),
        {"order_id": order_id, "now": now},
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="工单不存在或不可删除")

    log.info("delete_dri_work_order", tenant_id=tenant_id, order_id=order_id)
    return _ok({"order_id": order_id, "deleted": True})
