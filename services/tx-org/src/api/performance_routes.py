from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/org", tags=["performance"])


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


class PerformanceScoresSubmit(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    month: str = Field(..., description="绩效月份 YYYY-MM")
    scores: dict[str, float] = Field(
        default_factory=dict,
        description="维度得分，如 service、sales",
    )


class HorseRaceRequest(BaseModel):
    store_ids: list[str] = Field(..., description="参与赛马的门店 ID 列表")
    month: str = Field(..., description="月份 YYYY-MM")


class PointsAwardRequest(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    rule_code: str = Field(..., description="积分规则编码")
    extra_points: int = Field(..., description="本次增减积分")
    note: str = Field(default="", description="备注")


_MOCK_SCORE_ROWS: list[dict[str, Any]] = [
    {
        "employee_id": f"emp-perf-{i:02d}",
        "employee_name": f"员工{i}",
        "store_id": "store-mock-a" if i % 2 else "store-mock-b",
        "month": "2026-03",
        "service": 80 + (i % 15),
        "sales": 75 + (i % 20),
        "hygiene": 88 + (i % 10),
        "weighted_total": round(82.0 + (i % 12) * 0.5, 1),
        "rank_in_store": i,
    }
    for i in range(1, 11)
]


@router.get("/performance/scores")
async def list_performance_scores(
    store_id: str | None = Query(None, description="门店 ID"),
    month: str | None = Query(None, description="月份 YYYY-MM"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    """分页查询员工绩效得分列表（Mock）。"""
    items = list(_MOCK_SCORE_ROWS)
    if store_id:
        items = [r for r in items if r["store_id"] == store_id]
    if month:
        items = [r for r in items if r["month"] == month]
    total = len(items)
    start = (page - 1) * size
    end = start + size
    return _ok({"items": items[start:end], "total": total, "page": page, "size": size})


@router.post("/performance/scores")
async def submit_performance_scores(body: PerformanceScoresSubmit):
    """提交或试算员工绩效维度得分，返回加权总分与等级提示（Mock）。"""
    vals = list(body.scores.values()) if body.scores else [0.0]
    weighted_total = round(sum(vals) / max(len(vals), 1), 1)
    if weighted_total >= 90:
        rank_hint = "优秀"
    elif weighted_total >= 80:
        rank_hint = "良好"
    elif weighted_total >= 60:
        rank_hint = "合格"
    else:
        rank_hint = "待改进"
    return _ok({"weighted_total": weighted_total, "rank_hint": rank_hint})


@router.get("/performance/rankings")
async def get_performance_rankings(
    store_id: str | None = Query(None, description="门店 ID"),
    month: str | None = Query(None, description="月份 YYYY-MM"),
):
    """查询门店内绩效排名（Mock）。"""
    rows = sorted(_MOCK_SCORE_ROWS, key=lambda r: r["weighted_total"], reverse=True)
    if store_id:
        rows = [r for r in rows if r["store_id"] == store_id]
    if month:
        rows = [r for r in rows if r["month"] == month]
    ranked = []
    for idx, r in enumerate(rows, start=1):
        ranked.append(
            {
                "rank": idx,
                "employee_id": r["employee_id"],
                "employee_name": r["employee_name"],
                "weighted_total": r["weighted_total"],
                "store_id": r["store_id"],
                "month": r["month"],
            }
        )
    return _ok({"rankings": ranked, "total": len(ranked)})


@router.post("/performance/horse-race")
async def performance_horse_race(body: HorseRaceRequest):
    """多门店赛马排名（Mock）。"""
    stores = body.store_ids or ["store-mock-a", "store-mock-b", "store-mock-c"]
    leaderboard = []
    for idx, sid in enumerate(stores):
        score = round(72.0 + (idx * 3.7) % 20, 1)
        leaderboard.append(
            {
                "rank": idx + 1,
                "store_id": sid,
                "month": body.month,
                "composite_score": score,
                "revenue_index": round(score + 2.1, 1),
                "efficiency_index": round(max(score - 4.5, 60), 1),
            }
        )
    leaderboard.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, row in enumerate(leaderboard, start=1):
        row["rank"] = i
    return _ok({"month": body.month, "stores": leaderboard})


@router.get("/points/leaderboard")
async def points_leaderboard(
    store_id: str | None = Query(None, description="门店 ID"),
    period: str | None = Query(None, description="统计周期"),
):
    """积分排行榜（Mock）。"""
    base = "store-mock-a" if not store_id else store_id
    items = [
        {
            "rank": i,
            "employee_id": f"emp-pt-{i:02d}",
            "display_name": f"积分榜第{i}名",
            "store_id": base,
            "period": period or "2026-Q1",
            "total_points": 5000 - i * 120,
            "level": "黄金" if i <= 3 else "白银",
        }
        for i in range(1, 11)
    ]
    return _ok({"items": items, "store_id": base, "period": period or "2026-Q1"})


@router.post("/points/award")
async def points_award(body: PointsAwardRequest):
    """按规则发放或调整员工积分（Mock）。"""
    awarded = body.extra_points
    new_total = 3200 + awarded
    if new_total >= 5000:
        new_level = "钻石"
    elif new_total >= 3500:
        new_level = "黄金"
    elif new_total >= 2500:
        new_level = "白银"
    else:
        new_level = "青铜"
    return _ok(
        {
            "points_awarded": awarded,
            "new_total": new_total,
            "new_level": new_level,
        }
    )


@router.get("/points/detail/{employee_id}")
async def points_detail(employee_id: str):
    """查询单员工积分明细（Mock）。"""
    return _ok(
        {
            "employee_id": employee_id,
            "current_total": 3180,
            "level": "白银",
            "entries": [
                {
                    "id": "pt-001",
                    "occurred_at": "2026-03-28T10:00:00Z",
                    "delta": 50,
                    "balance_after": 3180,
                    "rule_code": "ATTENDANCE_FULL",
                    "note": "全勤奖励",
                },
                {
                    "id": "pt-002",
                    "occurred_at": "2026-03-20T15:30:00Z",
                    "delta": -20,
                    "balance_after": 3130,
                    "rule_code": "DEDUCTION_LATE",
                    "note": "迟到扣减",
                },
                {
                    "id": "pt-003",
                    "occurred_at": "2026-03-15T09:00:00Z",
                    "delta": 100,
                    "balance_after": 3150,
                    "rule_code": "TRAINING_COMPLETE",
                    "note": "培训完成",
                },
            ],
        }
    )
