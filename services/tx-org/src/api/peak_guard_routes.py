"""高峰保障指挥 API 路由

端点列表：
  GET    /api/v1/peak-guard                              高峰记录列表（分页+筛选）
  POST   /api/v1/peak-guard                              创建高峰保障记录
  GET    /api/v1/peak-guard/dashboard                    高峰保障总览
  GET    /api/v1/peak-guard/upcoming                     即将到来的高峰（未来7天）
  GET    /api/v1/peak-guard/alerts                       覆盖度预警（coverage < 60）
  GET    /api/v1/peak-guard/{record_id}                  高峰记录详情
  PUT    /api/v1/peak-guard/{record_id}                  更新记录
  POST   /api/v1/peak-guard/{record_id}/actions          追加保障行动
  PUT    /api/v1/peak-guard/{record_id}/evaluate         事后评估
  DELETE /api/v1/peak-guard/{record_id}                  软删除

数据源：peak_guard_records

统一响应格式: {"ok": bool, "data": {}, "error": null}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional
from uuid import uuid4

import json
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/peak-guard", tags=["peak-guard"])

# ── 常量 ──────────────────────────────────────────────────────────────────

VALID_PEAK_TYPES = {"lunch", "dinner", "weekend", "holiday", "event"}

PEAK_TYPE_LABELS = {
    "lunch": "午高峰",
    "dinner": "晚高峰",
    "weekend": "周末",
    "holiday": "节假日",
    "event": "活动",
}


# ── helpers ───────────────────────────────────────────────────────────────

def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将 SQLAlchemy Row/Mapping 转为可序列化 dict（处理 date/datetime/Decimal）"""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif not isinstance(v, (str, int, float, bool, dict, list, type(None))):
            d[k] = str(v)
    return d


def _calc_coverage_score(risk_positions: list[dict]) -> float:
    """根据 risk_positions 计算人力覆盖度 (0-100)"""
    if not risk_positions:
        return 0.0
    scores: list[float] = []
    for pos in risk_positions:
        required = pos.get("required", 0)
        actual = pos.get("actual", 0)
        if required > 0:
            scores.append(min(actual / required * 100, 100.0))
        else:
            scores.append(100.0)
    return round(sum(scores) / len(scores), 2) if scores else 0.0


def _enrich_risk_positions(positions: list[dict]) -> list[dict]:
    """为每个岗位计算 gap = actual - required"""
    for pos in positions:
        pos["gap"] = pos.get("actual", 0) - pos.get("required", 0)
    return positions


# ── request models ────────────────────────────────────────────────────────

class PeakGuardCreateReq(BaseModel):
    store_id: str = Field(..., min_length=1)
    guard_date: date
    peak_type: str = Field(..., pattern="^(lunch|dinner|weekend|holiday|event)$")
    expected_traffic: int = Field(default=0, ge=0)
    risk_positions: Optional[List[dict]] = None
    notes: Optional[str] = None


class PeakGuardUpdateReq(BaseModel):
    expected_traffic: Optional[int] = Field(default=None, ge=0)
    coverage_score: Optional[float] = Field(default=None, ge=0, le=100)
    risk_positions: Optional[List[dict]] = None
    notes: Optional[str] = None


class ActionReq(BaseModel):
    action: str = Field(..., min_length=1)
    executor: str = Field(..., min_length=1)
    result: Optional[str] = None


class EvaluateReq(BaseModel):
    result_score: float = Field(..., ge=0, le=100)


# ── GET /api/v1/peak-guard — 高峰记录列表 ─────────────────────────────────

@router.get("")
async def list_peak_guard(
    request: Request,
    store_id: Optional[str] = Query(None),
    peak_type: Optional[str] = Query(None),
    guard_date: Optional[date] = Query(None),
    coverage_below: Optional[float] = Query(None, description="筛选覆盖度低于此阈值的记录"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if peak_type:
        if peak_type not in VALID_PEAK_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid peak_type: {peak_type}")
        conditions.append("peak_type = :peak_type")
        params["peak_type"] = peak_type
    if guard_date:
        conditions.append("guard_date = :guard_date")
        params["guard_date"] = guard_date
    if coverage_below is not None:
        conditions.append("coverage_score < :coverage_below")
        params["coverage_below"] = coverage_below

    where = " AND ".join(conditions)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    total_row = (await db.execute(
        text(f"SELECT COUNT(*) AS cnt FROM peak_guard_records WHERE {where}"),
        params,
    )).mappings().first()
    total = total_row["cnt"] if total_row else 0

    rows = (await db.execute(
        text(f"""
            SELECT id::text, tenant_id::text, store_id::text, guard_date,
                   peak_type, expected_traffic, coverage_score,
                   risk_positions, actions_taken, result_score,
                   notes, created_at, updated_at
            FROM peak_guard_records
            WHERE {where}
            ORDER BY guard_date DESC, created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )).mappings().all()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        d["peak_type_label"] = PEAK_TYPE_LABELS.get(d.get("peak_type", ""), "")
        items.append(d)

    return _ok({"items": items, "total": total, "page": page, "size": size})


# ── POST /api/v1/peak-guard — 创建高峰保障记录 ───────────────────────────

@router.post("")
async def create_peak_guard(
    request: Request,
    body: PeakGuardCreateReq,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    record_id = str(uuid4())
    now = datetime.now(timezone.utc)

    risk_positions = _enrich_risk_positions(body.risk_positions or [])
    coverage_score = _calc_coverage_score(risk_positions)

    await db.execute(
        text("""
            INSERT INTO peak_guard_records
                (id, tenant_id, store_id, guard_date, peak_type, expected_traffic,
                 coverage_score, risk_positions, actions_taken, notes,
                 is_deleted, created_at, updated_at)
            VALUES
                (:id, :tid, :store_id, :guard_date, :peak_type, :expected_traffic,
                 :coverage_score, :risk_positions::jsonb, '[]'::jsonb, :notes,
                 FALSE, :now, :now)
        """),
        {
            "id": record_id,
            "tid": tenant_id,
            "store_id": body.store_id,
            "guard_date": body.guard_date,
            "peak_type": body.peak_type,
            "expected_traffic": body.expected_traffic,
            "coverage_score": coverage_score,
            "risk_positions": json.dumps(risk_positions),
            "notes": body.notes,
            "now": now,
        },
    )
    await db.commit()

    log.info("peak_guard.created", record_id=record_id, store_id=body.store_id,
             peak_type=body.peak_type, coverage_score=coverage_score)

    return _ok({
        "id": record_id,
        "coverage_score": coverage_score,
        "risk_positions": risk_positions,
        "peak_type_label": PEAK_TYPE_LABELS.get(body.peak_type, ""),
    })


# ── GET /api/v1/peak-guard/dashboard — 高峰保障总览 ──────────────────────

@router.get("/dashboard")
async def peak_guard_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    row = (await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE guard_date = CURRENT_DATE) AS today_count,
                COUNT(*) FILTER (WHERE guard_date BETWEEN date_trunc('week', CURRENT_DATE) AND date_trunc('week', CURRENT_DATE) + INTERVAL '6 days') AS week_count,
                COALESCE(AVG(coverage_score), 0) AS avg_coverage,
                COALESCE(AVG(result_score) FILTER (WHERE result_score IS NOT NULL), 0) AS avg_result_score
            FROM peak_guard_records
            WHERE tenant_id = :tid AND is_deleted = FALSE
        """),
        {"tid": tenant_id},
    )).mappings().first()

    # 覆盖不足门店
    low_stores = (await db.execute(
        text("""
            SELECT DISTINCT store_id::text, MIN(coverage_score) AS min_coverage
            FROM peak_guard_records
            WHERE tenant_id = :tid AND is_deleted = FALSE
              AND coverage_score < 60
              AND guard_date >= CURRENT_DATE
            GROUP BY store_id
            ORDER BY min_coverage ASC
            LIMIT 20
        """),
        {"tid": tenant_id},
    )).mappings().all()

    # 按 peak_type 分布
    by_type = (await db.execute(
        text("""
            SELECT peak_type, COUNT(*) AS cnt,
                   COALESCE(AVG(coverage_score), 0) AS avg_coverage
            FROM peak_guard_records
            WHERE tenant_id = :tid AND is_deleted = FALSE
              AND guard_date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY peak_type
            ORDER BY cnt DESC
        """),
        {"tid": tenant_id},
    )).mappings().all()

    dashboard = _row_to_dict(row) if row else {}
    dashboard["low_coverage_stores"] = [_row_to_dict(s) for s in low_stores]
    dashboard["by_peak_type"] = [
        {**_row_to_dict(t), "peak_type_label": PEAK_TYPE_LABELS.get(t["peak_type"], "")}
        for t in by_type
    ]

    return _ok(dashboard)


# ── GET /api/v1/peak-guard/upcoming — 即将到来的高峰 ─────────────────────

@router.get("/upcoming")
async def upcoming_peaks(
    request: Request,
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = [
        "tenant_id = :tid",
        "is_deleted = FALSE",
        "guard_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7",
    ]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id

    where = " AND ".join(conditions)

    rows = (await db.execute(
        text(f"""
            SELECT id::text, store_id::text, guard_date, peak_type,
                   expected_traffic, coverage_score, risk_positions, notes
            FROM peak_guard_records
            WHERE {where}
            ORDER BY guard_date ASC, peak_type ASC
        """),
        params,
    )).mappings().all()

    items = [
        {**_row_to_dict(r), "peak_type_label": PEAK_TYPE_LABELS.get(r["peak_type"], "")}
        for r in rows
    ]

    return _ok({"items": items, "total": len(items)})


# ── GET /api/v1/peak-guard/alerts — 覆盖度预警 ──────────────────────────

@router.get("/alerts")
async def peak_guard_alerts(
    request: Request,
    threshold: float = Query(60.0, description="覆盖度预警阈值，默认60"),
    store_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = [
        "tenant_id = :tid",
        "is_deleted = FALSE",
        "coverage_score < :threshold",
        "guard_date >= CURRENT_DATE",
    ]
    params: dict[str, Any] = {"tid": tenant_id, "threshold": threshold}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id

    where = " AND ".join(conditions)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    total_row = (await db.execute(
        text(f"SELECT COUNT(*) AS cnt FROM peak_guard_records WHERE {where}"),
        params,
    )).mappings().first()
    total = total_row["cnt"] if total_row else 0

    rows = (await db.execute(
        text(f"""
            SELECT id::text, store_id::text, guard_date, peak_type,
                   expected_traffic, coverage_score, risk_positions, notes
            FROM peak_guard_records
            WHERE {where}
            ORDER BY coverage_score ASC, guard_date ASC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )).mappings().all()

    items = [
        {**_row_to_dict(r), "peak_type_label": PEAK_TYPE_LABELS.get(r["peak_type"], "")}
        for r in rows
    ]

    return _ok({"items": items, "total": total, "page": page, "size": size})


# ── GET /api/v1/peak-guard/{record_id} — 高峰记录详情 ────────────────────

@router.get("/{record_id}")
async def get_peak_guard(
    request: Request,
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    row = (await db.execute(
        text("""
            SELECT id::text, tenant_id::text, store_id::text, guard_date,
                   peak_type, expected_traffic, coverage_score,
                   risk_positions, actions_taken, result_score,
                   notes, created_at, updated_at
            FROM peak_guard_records
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id},
    )).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Peak guard record not found")

    d = _row_to_dict(row)
    d["peak_type_label"] = PEAK_TYPE_LABELS.get(d.get("peak_type", ""), "")
    if d.get("result_score") is not None and d.get("coverage_score") is not None:
        d["effectiveness"] = round(d["result_score"] - d["coverage_score"], 2)

    return _ok(d)


# ── PUT /api/v1/peak-guard/{record_id} — 更新记录 ───────────────────────

@router.put("/{record_id}")
async def update_peak_guard(
    request: Request,
    record_id: str,
    body: PeakGuardUpdateReq,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 验证记录存在
    existing = (await db.execute(
        text("""
            SELECT id FROM peak_guard_records
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id},
    )).mappings().first()

    if not existing:
        raise HTTPException(status_code=404, detail="Peak guard record not found")

    sets: list[str] = ["updated_at = :now"]
    params: dict[str, Any] = {"rid": record_id, "tid": tenant_id, "now": datetime.now(timezone.utc)}

    if body.expected_traffic is not None:
        sets.append("expected_traffic = :expected_traffic")
        params["expected_traffic"] = body.expected_traffic

    if body.notes is not None:
        sets.append("notes = :notes")
        params["notes"] = body.notes

    if body.risk_positions is not None:
        enriched = _enrich_risk_positions(body.risk_positions)
        sets.append("risk_positions = :risk_positions::jsonb")
        params["risk_positions"] = json.dumps(enriched)
        # 重算 coverage_score
        new_coverage = _calc_coverage_score(enriched)
        sets.append("coverage_score = :coverage_score")
        params["coverage_score"] = new_coverage

    if body.coverage_score is not None and body.risk_positions is None:
        sets.append("coverage_score = :coverage_score")
        params["coverage_score"] = body.coverage_score

    await db.execute(
        text(f"""
            UPDATE peak_guard_records
            SET {', '.join(sets)}
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        params,
    )
    await db.commit()

    log.info("peak_guard.updated", record_id=record_id)
    return _ok({"id": record_id, "updated": True})


# ── POST /api/v1/peak-guard/{record_id}/actions — 追加保障行动 ──────────

@router.post("/{record_id}/actions")
async def add_action(
    request: Request,
    record_id: str,
    body: ActionReq,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    existing = (await db.execute(
        text("""
            SELECT id FROM peak_guard_records
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id},
    )).mappings().first()

    if not existing:
        raise HTTPException(status_code=404, detail="Peak guard record not found")

    action_entry = {
        "action": body.action,
        "executor": body.executor,
        "result": body.result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    await db.execute(
        text("""
            UPDATE peak_guard_records
            SET actions_taken = actions_taken || :new_action::jsonb,
                updated_at = :now
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {
            "rid": record_id,
            "tid": tenant_id,
            "new_action": json.dumps([action_entry]),
            "now": datetime.now(timezone.utc),
        },
    )
    await db.commit()

    log.info("peak_guard.action_added", record_id=record_id, action=body.action)
    return _ok({"id": record_id, "action_added": action_entry})


# ── PUT /api/v1/peak-guard/{record_id}/evaluate — 事后评估 ──────────────

@router.put("/{record_id}/evaluate")
async def evaluate_peak_guard(
    request: Request,
    record_id: str,
    body: EvaluateReq,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    row = (await db.execute(
        text("""
            SELECT coverage_score
            FROM peak_guard_records
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id},
    )).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Peak guard record not found")

    coverage = float(row["coverage_score"]) if row["coverage_score"] else 0.0
    effectiveness = round(body.result_score - coverage, 2)

    await db.execute(
        text("""
            UPDATE peak_guard_records
            SET result_score = :result_score,
                updated_at = :now
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {
            "rid": record_id,
            "tid": tenant_id,
            "result_score": body.result_score,
            "now": datetime.now(timezone.utc),
        },
    )
    await db.commit()

    log.info("peak_guard.evaluated", record_id=record_id,
             result_score=body.result_score, effectiveness=effectiveness)

    return _ok({
        "id": record_id,
        "result_score": body.result_score,
        "coverage_score": coverage,
        "effectiveness": effectiveness,
    })


# ── DELETE /api/v1/peak-guard/{record_id} — 软删除 ──────────────────────

@router.delete("/{record_id}")
async def delete_peak_guard(
    request: Request,
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            UPDATE peak_guard_records
            SET is_deleted = TRUE, updated_at = :now
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id, "now": datetime.now(timezone.utc)},
    )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Peak guard record not found")

    await db.commit()
    log.info("peak_guard.deleted", record_id=record_id)
    return _ok({"id": record_id, "deleted": True})
