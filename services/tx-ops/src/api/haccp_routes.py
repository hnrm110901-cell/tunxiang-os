"""HACCP 食安检查计划 API — Phase 4 食安合规数字化

端点：
  GET  /api/v1/ops/haccp/plans               — 列出检查计划
  POST /api/v1/ops/haccp/plans               — 创建计划
  PATCH /api/v1/ops/haccp/plans/{plan_id}    — 更新计划
  GET  /api/v1/ops/haccp/records             — 列出检查记录（按日期过滤）
  POST /api/v1/ops/haccp/records             — 提交检查记录（自动计算critical_failures）
  GET  /api/v1/ops/haccp/records/{record_id} — 获取单条记录
  GET  /api/v1/ops/haccp/stats               — 本月合格率/关键失控点统计
  GET  /api/v1/ops/haccp/overdue             — 逾期未完成的检查

写操作成功后旁路发射事件（asyncio.create_task）：
  - safety.haccp_check_completed（提交检查记录时）
  - safety.haccp_critical_failure（critical_failures > 0 时额外发射）

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import SafetyEventType
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/haccp", tags=["haccp"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RLS 辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SAFE_TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


def _serialize_row(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    """将 UUID / datetime / date 统一序列化为字符串。"""
    for k, v in row_dict.items():
        if isinstance(v, datetime):
            row_dict[k] = v.isoformat()
        elif isinstance(v, date):
            row_dict[k] = v.isoformat()
        elif type(v).__name__ == "UUID":
            row_dict[k] = str(v)
    return row_dict


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求 / 响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ChecklistItem(BaseModel):
    item: str = Field(..., description="检查项目名称")
    standard: str = Field(..., description="合格标准描述")
    critical: bool = Field(False, description="是否为关键控制点（CCP）")


class PlanCreateReq(BaseModel):
    store_id: str = Field(..., description="门店ID")
    plan_name: str = Field(..., max_length=100, description="计划名称")
    check_type: str = Field(
        ..., description="检查类型：temperature|hygiene|pest|supplier|equipment"
    )
    frequency: str = Field(..., description="执行频率：daily|weekly|monthly")
    responsible_role: Optional[str] = Field(None, max_length=50, description="负责岗位")
    checklist: List[ChecklistItem] = Field(default_factory=list, description="检查项清单")
    is_active: bool = Field(True, description="是否启用")


class PlanUpdateReq(BaseModel):
    plan_name: Optional[str] = Field(None, max_length=100)
    check_type: Optional[str] = None
    frequency: Optional[str] = None
    responsible_role: Optional[str] = Field(None, max_length=50)
    checklist: Optional[List[ChecklistItem]] = None
    is_active: Optional[bool] = None


class ResultItem(BaseModel):
    item: str = Field(..., description="检查项目名称")
    passed: bool = Field(..., description="是否合格")
    value: Optional[str] = Field(None, description="实测值（如温度）")
    note: Optional[str] = Field(None, description="备注")


class RecordCreateReq(BaseModel):
    store_id: str = Field(..., description="门店ID")
    plan_id: str = Field(..., description="对应检查计划ID")
    operator_id: Optional[str] = Field(None, description="执行人员ID")
    check_date: date = Field(..., description="检查日期")
    results: List[ResultItem] = Field(default_factory=list, description="各项检查结果")
    corrective_actions: Optional[str] = Field(None, description="整改措施说明")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /plans — 列出检查计划
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/plans")
async def list_plans(
    store_id: Optional[str] = Query(None),
    check_type: Optional[str] = Query(None),
    frequency: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """列出HACCP检查计划，支持门店/类型/频率/启用状态过滤。"""
    await _set_rls(db, tenant_id)
    try:
        conditions = [_SAFE_TENANT]
        params: dict = {
            "tid": tenant_id,
            "offset": (page - 1) * page_size,
            "limit": page_size,
        }

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if check_type:
            conditions.append("check_type = :check_type")
            params["check_type"] = check_type
        if frequency:
            conditions.append("frequency = :frequency")
            params["frequency"] = frequency
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active

        where = " AND ".join(conditions)

        count_sql = text(f"SELECT COUNT(*) FROM haccp_check_plans WHERE {where}")
        total = (await db.execute(count_sql, params)).scalar() or 0

        select_sql = text(f"""
            SELECT id, tenant_id, store_id, plan_name, check_type, frequency,
                   responsible_role, checklist, is_active, created_at, updated_at
            FROM haccp_check_plans
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        rows = await db.execute(select_sql, params)
        plans = [_serialize_row(dict(r._mapping)) for r in rows]

        return {"ok": True, "data": {"plans": plans, "total": total, "page": page, "page_size": page_size}}
    except SQLAlchemyError as exc:
        log.error("haccp_list_plans_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"plans": [], "total": 0, "page": page, "page_size": page_size}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /plans — 创建检查计划
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/plans", status_code=201)
async def create_plan(
    req: PlanCreateReq,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建HACCP检查计划。"""
    await _set_rls(db, tenant_id)
    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    checklist_data = [item.model_dump() for item in req.checklist]

    try:
        insert_sql = text("""
            INSERT INTO haccp_check_plans (
                id, tenant_id, store_id, plan_name, check_type, frequency,
                responsible_role, checklist, is_active, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :store_id, :plan_name, :check_type, :frequency,
                :responsible_role, :checklist::jsonb, :is_active, :now, :now
            )
        """)
        await db.execute(insert_sql, {
            "id": plan_id,
            "tenant_id": tenant_id,
            "store_id": req.store_id,
            "plan_name": req.plan_name,
            "check_type": req.check_type,
            "frequency": req.frequency,
            "responsible_role": req.responsible_role,
            "checklist": __import__("json").dumps(checklist_data, ensure_ascii=False),
            "is_active": req.is_active,
            "now": now,
        })
        await db.commit()

        log.info("haccp_plan_created", plan_id=plan_id, check_type=req.check_type,
                 tenant_id=tenant_id)
        return {"ok": True, "data": {
            "plan_id": plan_id,
            "plan_name": req.plan_name,
            "check_type": req.check_type,
            "frequency": req.frequency,
            "created_at": now.isoformat(),
        }}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("haccp_create_plan_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": False, "error": {"message": "创建检查计划失败", "detail": str(exc)}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PATCH /plans/{plan_id} — 更新检查计划
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    req: PlanUpdateReq,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新HACCP检查计划，仅修改提交的字段。"""
    await _set_rls(db, tenant_id)
    now = datetime.now(timezone.utc)

    # 动态构建 SET 子句
    set_parts: list[str] = ["updated_at = :now"]
    params: dict = {"plan_id": plan_id, "tid": tenant_id, "now": now}

    if req.plan_name is not None:
        set_parts.append("plan_name = :plan_name")
        params["plan_name"] = req.plan_name
    if req.check_type is not None:
        set_parts.append("check_type = :check_type")
        params["check_type"] = req.check_type
    if req.frequency is not None:
        set_parts.append("frequency = :frequency")
        params["frequency"] = req.frequency
    if req.responsible_role is not None:
        set_parts.append("responsible_role = :responsible_role")
        params["responsible_role"] = req.responsible_role
    if req.checklist is not None:
        set_parts.append("checklist = :checklist::jsonb")
        params["checklist"] = __import__("json").dumps(
            [item.model_dump() for item in req.checklist], ensure_ascii=False
        )
    if req.is_active is not None:
        set_parts.append("is_active = :is_active")
        params["is_active"] = req.is_active

    if len(set_parts) == 1:
        return {"ok": False, "error": {"message": "无可更新字段", "code": "NO_FIELDS"}}

    try:
        update_sql = text(f"""
            UPDATE haccp_check_plans
            SET {", ".join(set_parts)}
            WHERE id = :plan_id AND {_SAFE_TENANT}
        """)
        result = await db.execute(update_sql, params)
        if result.rowcount == 0:
            return {"ok": False, "error": {"message": "检查计划不存在", "code": "NOT_FOUND"}}
        await db.commit()

        log.info("haccp_plan_updated", plan_id=plan_id, tenant_id=tenant_id)
        return {"ok": True, "data": {"plan_id": plan_id, "updated_at": now.isoformat()}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("haccp_update_plan_db_error", plan_id=plan_id, tenant_id=tenant_id,
                  error=str(exc), exc_info=True)
        return {"ok": False, "error": {"message": "更新检查计划失败", "detail": str(exc)}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /records — 列出检查记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/records")
async def list_records(
    store_id: Optional[str] = Query(None),
    plan_id: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None, description="开始日期（含）"),
    date_to: Optional[date] = Query(None, description="结束日期（含）"),
    overall_passed: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """列出检查执行记录，支持门店/计划/日期区间/合格状态过滤。"""
    await _set_rls(db, tenant_id)
    try:
        conditions = [_SAFE_TENANT]
        params: dict = {
            "tid": tenant_id,
            "offset": (page - 1) * page_size,
            "limit": page_size,
        }

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if plan_id:
            conditions.append("plan_id = :plan_id")
            params["plan_id"] = plan_id
        if date_from:
            conditions.append("check_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("check_date <= :date_to")
            params["date_to"] = date_to
        if overall_passed is not None:
            conditions.append("overall_passed = :overall_passed")
            params["overall_passed"] = overall_passed

        where = " AND ".join(conditions)

        count_sql = text(f"SELECT COUNT(*) FROM haccp_check_records WHERE {where}")
        total = (await db.execute(count_sql, params)).scalar() or 0

        select_sql = text(f"""
            SELECT id, tenant_id, store_id, plan_id, operator_id,
                   check_date, results, overall_passed, critical_failures,
                   corrective_actions, created_at
            FROM haccp_check_records
            WHERE {where}
            ORDER BY check_date DESC, created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        rows = await db.execute(select_sql, params)
        records = [_serialize_row(dict(r._mapping)) for r in rows]

        return {"ok": True, "data": {"records": records, "total": total, "page": page, "page_size": page_size}}
    except SQLAlchemyError as exc:
        log.error("haccp_list_records_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"records": [], "total": 0, "page": page, "page_size": page_size}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /records — 提交检查记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/records", status_code=201)
async def create_record(
    req: RecordCreateReq,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """提交检查执行记录，自动计算 critical_failures，旁路发射食安事件。"""
    await _set_rls(db, tenant_id)
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # 查询计划的 checklist，获取关键控制点标记
    plan_checklist: list[dict] = []
    try:
        plan_sql = text(f"""
            SELECT checklist FROM haccp_check_plans
            WHERE id = :plan_id AND {_SAFE_TENANT}
        """)
        plan_row = await db.execute(plan_sql, {"plan_id": req.plan_id, "tid": tenant_id})
        plan_record = plan_row.mappings().first()
        if plan_record and plan_record["checklist"]:
            plan_checklist = plan_record["checklist"] if isinstance(plan_record["checklist"], list) else []
    except SQLAlchemyError as exc:
        log.warning("haccp_plan_fetch_error", plan_id=req.plan_id, error=str(exc), exc_info=True)

    # 构建 critical 查找表
    critical_items: set[str] = {
        item["item"] for item in plan_checklist if item.get("critical", False)
    }

    # 计算 critical_failures 和 overall_passed
    results_data = [r.model_dump() for r in req.results]
    critical_failures = sum(
        1 for r in req.results if not r.passed and r.item in critical_items
    )
    overall_passed = all(r.passed for r in req.results) if req.results else None

    try:
        insert_sql = text("""
            INSERT INTO haccp_check_records (
                id, tenant_id, store_id, plan_id, operator_id,
                check_date, results, overall_passed, critical_failures,
                corrective_actions, created_at
            ) VALUES (
                :id, :tenant_id, :store_id, :plan_id, :operator_id,
                :check_date, :results::jsonb, :overall_passed, :critical_failures,
                :corrective_actions, :now
            )
        """)
        await db.execute(insert_sql, {
            "id": record_id,
            "tenant_id": tenant_id,
            "store_id": req.store_id,
            "plan_id": req.plan_id,
            "operator_id": req.operator_id,
            "check_date": req.check_date,
            "results": __import__("json").dumps(results_data, ensure_ascii=False),
            "overall_passed": overall_passed,
            "critical_failures": critical_failures,
            "corrective_actions": req.corrective_actions,
            "now": now,
        })
        await db.commit()

        # 旁路发射 safety.haccp_check_completed 事件
        asyncio.create_task(emit_event(
            event_type=SafetyEventType.HACCP_CHECK_COMPLETED,
            tenant_id=tenant_id,
            stream_id=record_id,
            payload={
                "record_id": record_id,
                "plan_id": req.plan_id,
                "check_date": req.check_date.isoformat(),
                "overall_passed": overall_passed,
                "critical_failures": critical_failures,
                "total_items": len(req.results),
                "passed_items": sum(1 for r in req.results if r.passed),
            },
            store_id=req.store_id,
            source_service="tx-ops",
            metadata={"operator_id": req.operator_id or ""},
        ))

        # 若存在关键失控点，额外发射 safety.haccp_critical_failure 事件
        if critical_failures > 0:
            failed_critical_items = [
                r.item for r in req.results
                if not r.passed and r.item in critical_items
            ]
            asyncio.create_task(emit_event(
                event_type=SafetyEventType.HACCP_CRITICAL_FAILURE,
                tenant_id=tenant_id,
                stream_id=record_id,
                payload={
                    "record_id": record_id,
                    "plan_id": req.plan_id,
                    "check_date": req.check_date.isoformat(),
                    "critical_failures": critical_failures,
                    "failed_items": failed_critical_items,
                    "corrective_actions": req.corrective_actions,
                },
                store_id=req.store_id,
                source_service="tx-ops",
                metadata={"operator_id": req.operator_id or ""},
            ))

        log.info("haccp_record_created", record_id=record_id, plan_id=req.plan_id,
                 overall_passed=overall_passed, critical_failures=critical_failures,
                 tenant_id=tenant_id)
        return {"ok": True, "data": {
            "record_id": record_id,
            "plan_id": req.plan_id,
            "check_date": req.check_date.isoformat(),
            "overall_passed": overall_passed,
            "critical_failures": critical_failures,
            "created_at": now.isoformat(),
        }}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("haccp_create_record_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": False, "error": {"message": "提交检查记录失败", "detail": str(exc)}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /records/{record_id} — 获取单条记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/records/{record_id}")
async def get_record(
    record_id: str,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取单条HACCP检查记录详情，包含检查计划基本信息。"""
    await _set_rls(db, tenant_id)
    try:
        sql = text(f"""
            SELECT
                r.id, r.tenant_id, r.store_id, r.plan_id, r.operator_id,
                r.check_date, r.results, r.overall_passed, r.critical_failures,
                r.corrective_actions, r.created_at,
                p.plan_name, p.check_type, p.frequency, p.responsible_role
            FROM haccp_check_records r
            LEFT JOIN haccp_check_plans p ON r.plan_id = p.id
            WHERE r.id = :record_id AND r.{_SAFE_TENANT}
        """)
        row = await db.execute(sql, {"record_id": record_id, "tid": tenant_id})
        record = row.mappings().first()
        if not record:
            return {"ok": False, "error": {"message": "检查记录不存在", "code": "NOT_FOUND"}}

        return {"ok": True, "data": {"record": _serialize_row(dict(record))}}
    except SQLAlchemyError as exc:
        log.error("haccp_get_record_db_error", record_id=record_id, tenant_id=tenant_id,
                  error=str(exc), exc_info=True)
        return {"ok": True, "data": {"record": None}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /stats — 本月合格率/关键失控点统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/stats")
async def get_stats(
    store_id: Optional[str] = Query(None),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """统计本月 HACCP 检查数据：总次数、合格次数、合格率、关键失控点总数，按 check_type 分组。"""
    await _set_rls(db, tenant_id)
    try:
        conditions = [f"r.{_SAFE_TENANT}", "r.check_date >= DATE_TRUNC('month', CURRENT_DATE)"]
        params: dict = {"tid": tenant_id}
        if store_id:
            conditions.append("r.store_id = :store_id")
            params["store_id"] = store_id
        where = " AND ".join(conditions)

        # 按检查类型分组汇总
        type_sql = text(f"""
            SELECT
                p.check_type,
                COUNT(*) AS total_checks,
                COUNT(*) FILTER (WHERE r.overall_passed = true) AS passed_checks,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE r.overall_passed = true)
                    / NULLIF(COUNT(*), 0), 1
                ) AS pass_rate,
                SUM(r.critical_failures) AS total_critical_failures
            FROM haccp_check_records r
            LEFT JOIN haccp_check_plans p ON r.plan_id = p.id
            WHERE {where}
            GROUP BY p.check_type
            ORDER BY p.check_type
        """)
        type_rows = await db.execute(type_sql, params)
        by_type = []
        for row in type_rows:
            rd = dict(row._mapping)
            for k in ("total_checks", "passed_checks", "total_critical_failures"):
                rd[k] = int(rd.get(k) or 0)
            for k in ("pass_rate",):
                rd[k] = float(rd.get(k) or 0)
            by_type.append(rd)

        # 汇总总计
        summary_sql = text(f"""
            SELECT
                COUNT(*) AS total_checks,
                COUNT(*) FILTER (WHERE r.overall_passed = true) AS passed_checks,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE r.overall_passed = true)
                    / NULLIF(COUNT(*), 0), 1
                ) AS pass_rate,
                SUM(r.critical_failures) AS total_critical_failures
            FROM haccp_check_records r
            WHERE {where}
        """)
        summary_row = (await db.execute(summary_sql, params)).mappings().first()
        summary: dict = {}
        if summary_row:
            summary = dict(summary_row)
            for k in ("total_checks", "passed_checks", "total_critical_failures"):
                summary[k] = int(summary.get(k) or 0)
            summary["pass_rate"] = float(summary.get("pass_rate") or 0)

        return {"ok": True, "data": {"summary": summary, "by_type": by_type}}
    except SQLAlchemyError as exc:
        log.error("haccp_stats_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"summary": {}, "by_type": []}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /overdue — 逾期未完成的检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/overdue")
async def get_overdue(
    store_id: Optional[str] = Query(None),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """返回逾期未完成的检查计划列表。

    逾期判断规则（按频率）：
      - daily  — 今天未执行（最近执行日期 < 今天）
      - weekly — 最近7天内未执行
      - monthly — 最近30天内未执行
    """
    await _set_rls(db, tenant_id)
    today = date.today()
    try:
        conditions = [f"p.{_SAFE_TENANT}", "p.is_active = true"]
        params: dict = {
            "tid": tenant_id,
            "today": today,
            "daily_cutoff": today,
            "weekly_cutoff": today - timedelta(days=7),
            "monthly_cutoff": today - timedelta(days=30),
        }
        if store_id:
            conditions.append("p.store_id = :store_id")
            params["store_id"] = store_id
        where = " AND ".join(conditions)

        # 查找每个计划最近一次执行日期，筛选出逾期的
        overdue_sql = text(f"""
            SELECT
                p.id AS plan_id,
                p.store_id,
                p.plan_name,
                p.check_type,
                p.frequency,
                p.responsible_role,
                MAX(r.check_date) AS last_check_date,
                CASE
                    WHEN p.frequency = 'daily'   THEN :daily_cutoff
                    WHEN p.frequency = 'weekly'  THEN :weekly_cutoff
                    WHEN p.frequency = 'monthly' THEN :monthly_cutoff
                    ELSE :today
                END AS required_since
            FROM haccp_check_plans p
            LEFT JOIN haccp_check_records r
                ON r.plan_id = p.id
                AND r.{_SAFE_TENANT}
            WHERE {where}
            GROUP BY p.id, p.store_id, p.plan_name, p.check_type,
                     p.frequency, p.responsible_role
            HAVING MAX(r.check_date) IS NULL
                OR MAX(r.check_date) < CASE
                    WHEN p.frequency = 'daily'   THEN :daily_cutoff
                    WHEN p.frequency = 'weekly'  THEN :weekly_cutoff
                    WHEN p.frequency = 'monthly' THEN :monthly_cutoff
                    ELSE :today
                END
            ORDER BY p.frequency, p.plan_name
        """)
        rows = await db.execute(overdue_sql, params)
        overdue_plans = []
        for row in rows:
            rd = dict(row._mapping)
            for k, v in rd.items():
                if isinstance(v, (date, datetime)):
                    rd[k] = v.isoformat()
                elif type(v).__name__ == "UUID":
                    rd[k] = str(v)
            overdue_plans.append(rd)

        return {"ok": True, "data": {"overdue": overdue_plans, "total": len(overdue_plans)}}
    except SQLAlchemyError as exc:
        log.error("haccp_overdue_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"overdue": [], "total": 0}}
