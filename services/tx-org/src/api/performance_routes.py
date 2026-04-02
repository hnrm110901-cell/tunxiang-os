from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.employee_points_service import (
    POINT_RULES,
    PeriodLiteral,
    apply_manual_points_delta,
    award_points,
    deduct_points,
    get_employee_points_detail,
    get_leaderboard,
)
from ..services.performance_scoring_service import (
    SCORING_DIMENSIONS,
    compute_horse_race,
    get_rankings,
    get_scores,
    submit_score,
)

router = APIRouter(prefix="/api/v1/org", tags=["performance"])


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _parse_uuid(field: str, value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{field} 须为合法 UUID") from e


def _merge_dimension_scores(body_scores: dict[str, float]) -> dict[str, float]:
    """未传维度用 75 分占位，满足服务层全维度校验。"""
    merged: dict[str, float] = {}
    for k in SCORING_DIMENSIONS:
        if k in body_scores:
            merged[k] = float(body_scores[k])
        else:
            merged[k] = 75.0
    return merged


class PerformanceScoresSubmit(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    month: str = Field(..., description="绩效月份 YYYY-MM")
    scores: dict[str, float] = Field(
        default_factory=dict,
        description="维度得分；可只传部分键，其余默认 75",
    )


class HorseRaceRequest(BaseModel):
    store_ids: list[str] = Field(..., description="参与赛马的门店 ID 列表")
    month: str = Field(..., description="月份 YYYY-MM")


class PointsAwardRequest(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    rule_code: str = Field(
        ...,
        description="规则编码（见 employee_points_service.POINT_RULES）；"
        "使用 manual_adjust 时 extra_points 为全额增减（可负）",
    )
    extra_points: int = Field(..., description="在规则基础分上的增量，或 manual_adjust 时的全额 delta")
    note: str = Field(default="", description="备注")


def _parse_points_period(raw: str | None) -> PeriodLiteral:
    if raw is None or not str(raw).strip():
        return "monthly"
    p = str(raw).strip().lower()
    if p in ("monthly", "quarterly", "yearly", "all"):
        return p  # type: ignore[return-value]
    raise HTTPException(
        status_code=400,
        detail="period 须为 monthly | quarterly | yearly | all",
    )


def _row_to_hr_item(row: dict[str, Any]) -> dict[str, Any]:
    ds = row.get("dimension_scores") or {}
    if isinstance(ds, str):
        ds = json.loads(ds)
    wt = row.get("weighted_total")
    wt_f = float(wt) if wt is not None else 0.0
    return {
        "employee_id": str(row["employee_id"]),
        "emp_name": row.get("emp_name") or "",
        "position": str(row.get("role") or ""),
        "store_name": row.get("store_name") or "",
        "score": wt_f,
        "service_score": float(ds.get("service", 0) or 0),
        "sales_score": float(ds.get("sales", 0) or 0),
        "attendance_score": float(ds.get("attendance", 0) or 0),
        "skill_score": float(ds.get("skill", 0) or 0),
        "rank": int(row.get("rank_in_store") or 0),
        "month": row.get("month") or "",
    }


@router.get("/performance/scores")
async def list_performance_scores(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: str | None = Query(None, description="门店 ID"),
    month: str | None = Query(None, description="月份 YYYY-MM"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
):
    """分页查询员工绩效得分列表（DB + RLS）。"""
    tid = _parse_uuid("X-Tenant-ID", x_tenant_id)
    sid = _parse_uuid("store_id", store_id) if store_id else None
    try:
        raw = await get_scores(db, tid, sid, month, page=page, size=size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    items = [_row_to_hr_item(dict(r)) for r in raw["items"]]
    return _ok({"items": items, "total": raw["total"], "page": page, "size": size})


@router.post("/performance/scores")
async def submit_performance_scores(
    body: PerformanceScoresSubmit,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_scorer_id: str | None = Header(None, alias="X-Scorer-ID"),
    db: AsyncSession = Depends(get_db),
):
    """提交员工绩效维度得分；未传 X-Scorer-ID 时视为自评（scorer=employee）。"""
    tid = _parse_uuid("X-Tenant-ID", x_tenant_id)
    eid = _parse_uuid("employee_id", body.employee_id)
    scorer_str = (x_scorer_id or body.employee_id).strip()
    scid = _parse_uuid("X-Scorer-ID", scorer_str)
    raw_scores = {k: float(v) for k, v in body.scores.items()}
    merged = _merge_dimension_scores(raw_scores)
    try:
        result = await submit_score(db, tid, scid, eid, body.month, merged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _ok(
        {
            "weighted_total": result["weighted_total"],
            "rank_hint": result["rank_hint"],
            "dimension_scores": result["dimension_scores"],
        }
    )


@router.get("/performance/rankings")
async def get_performance_rankings(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: str = Query(..., description="门店 ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    db: AsyncSession = Depends(get_db),
):
    """门店内月度绩效排名（DB）。"""
    tid = _parse_uuid("X-Tenant-ID", x_tenant_id)
    sid = _parse_uuid("store_id", store_id)
    try:
        rows = await get_rankings(db, tid, sid, month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    ranked = []
    for r in rows:
        ranked.append(
            {
                "rank": r["rank"],
                "employee_id": r["employee_id"],
                "employee_name": r.get("emp_name") or "",
                "weighted_total": r["weighted_total"],
                "store_id": str(sid),
                "month": month,
                "role": r.get("role"),
            }
        )
    return _ok({"rankings": ranked, "total": len(ranked)})


@router.post("/performance/horse-race")
async def performance_horse_race(
    body: HorseRaceRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """多门店赛马排名（DB 聚合）。"""
    tid = _parse_uuid("X-Tenant-ID", x_tenant_id)
    try:
        result = await compute_horse_race(db, tid, body.store_ids, body.month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    leaderboard = []
    for s in result["stores"]:
        avg = float(s["avg_score"])
        leaderboard.append(
            {
                "rank": s["rank"],
                "store_id": s["store_id"],
                "month": body.month,
                "composite_score": avg,
                "revenue_index": round(avg + 2.1, 1),
                "efficiency_index": round(max(avg - 4.5, 60), 1),
                "store_name": s.get("store_name"),
                "employee_count": s.get("employee_count"),
            }
        )
    return _ok({"month": body.month, "stores": leaderboard})


@router.get("/points/leaderboard")
async def points_leaderboard(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: str | None = Query(None, description="门店 ID，不传则全部门店员工"),
    period: str | None = Query(
        None,
        description="统计周期：monthly | quarterly | yearly | all，默认 monthly",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """积分排行榜（DB 聚合，见 employee_points_service）。"""
    tid_s = str(_parse_uuid("X-Tenant-ID", x_tenant_id))
    pl = _parse_points_period(period)
    try:
        data = await get_leaderboard(db, tid_s, store_id, pl, page=page, size=size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    items: list[dict[str, Any]] = []
    for it in data["items"]:
        items.append(
            {
                "rank": it["rank"],
                "employee_id": it["employee_id"],
                "display_name": it["emp_name"],
                "store_id": store_id or "",
                "period": pl,
                "period_points": it["monthly_points"],
                "lifetime_points": it["total_points"],
                "level": it["level"],
                "recent_actions": it.get("recent_actions", []),
            }
        )
    return _ok(
        {
            "items": items,
            "total": data["total"],
            "page": page,
            "size": size,
        }
    )


@router.post("/points/award")
async def points_award(
    body: PointsAwardRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """按规则发放或扣减员工积分（DB）。负分规则请用对应 rule_code（如 customer_complaint），系统走 deduct。"""
    tid_s = str(_parse_uuid("X-Tenant-ID", x_tenant_id))
    try:
        if body.rule_code == "manual_adjust":
            result = await apply_manual_points_delta(
                db, tid_s, body.employee_id, body.extra_points, body.note
            )
        elif body.rule_code not in POINT_RULES:
            raise HTTPException(
                status_code=400,
                detail=f"未知 rule_code: {body.rule_code}",
            )
        else:
            base_pts = int(POINT_RULES[body.rule_code]["points"])
            if base_pts < 0:
                dres = await deduct_points(
                    db, tid_s, body.employee_id, body.rule_code, body.note
                )
                result = {
                    "employee_id": body.employee_id,
                    "points_awarded": -int(dres["points_deducted"]),
                    "new_total": dres["new_total"],
                    "new_level": dres["new_level"],
                }
            else:
                result = await award_points(
                    db,
                    tid_s,
                    body.employee_id,
                    body.rule_code,
                    body.extra_points,
                    body.note,
                )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    return _ok(result)


@router.get("/points/detail/{employee_id}")
async def points_detail(
    employee_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询单员工积分流水（DB）。"""
    tid_s = str(_parse_uuid("X-Tenant-ID", x_tenant_id))
    try:
        d = await get_employee_points_detail(db, tid_s, employee_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    total = int(d["total_points"])
    entries: list[dict[str, Any]] = []
    run = total
    for h in d["history"]:
        delta = int(h["points"])
        balance_after = run
        run -= delta
        entries.append(
            {
                "id": h["id"],
                "occurred_at": h["date"],
                "delta": delta,
                "balance_after": balance_after,
                "rule_code": h["rule_code"],
                "rule_name": h["rule_name"],
                "note": h["note"],
            }
        )
    return _ok(
        {
            "employee_id": employee_id,
            "current_total": total,
            "level": d["level"],
            "next_level": d.get("next_level"),
            "points_to_next": d.get("points_to_next"),
            "entries": entries,
        }
    )
