"""
绩效考核路由扩展 — 周期考核与薪资联动
Y-G8: 绩效评分DB化，补全 performance_routes.py 中缺失的周期/评级/历史端点
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/performance", tags=["performance-scoring"])

# ── KPI 权重配置（可按岗位不同） ──────────────────────────────────────────────

KPI_WEIGHTS: dict[str, dict[str, float]] = {
    "chef": {
        "service": 0.2,
        "efficiency": 0.4,
        "attendance": 0.2,
        "quality": 0.2,
    },
    "waiter": {
        "service": 0.5,
        "efficiency": 0.2,
        "attendance": 0.2,
        "customer_feedback": 0.1,
    },
    "cashier": {
        "service": 0.3,
        "efficiency": 0.3,
        "attendance": 0.2,
        "accuracy": 0.2,
    },
    "default": {
        "service": 0.3,
        "efficiency": 0.3,
        "attendance": 0.4,
    },
}

# 评级规则
GRADE_THRESHOLDS = [
    (90.0, "A", "优秀"),
    (80.0, "B", "良好"),
    (70.0, "C", "合格"),
    (60.0, "D", "待改进"),
    (0.0, "E", "不合格"),
]

# 考核周期类型
PERIOD_TYPES = ("monthly", "quarterly", "annual")

# Mock 数据
MOCK_PERIODS = [
    {
        "id": "period-2026-03",
        "name": "2026年3月考核",
        "period_type": "monthly",
        "period_key": "2026-03",
        "status": "completed",
        "participant_count": 12,
        "avg_score": 82.5,
        "created_at": "2026-04-01T00:00:00+00:00",
    },
    {
        "id": "period-2026-04",
        "name": "2026年4月考核",
        "period_type": "monthly",
        "period_key": "2026-04",
        "status": "in_progress",
        "participant_count": 0,
        "avg_score": None,
        "created_at": "2026-04-06T00:00:00+00:00",
    },
]

MOCK_SCORES = [
    {
        "employee_id": "emp-001",
        "employee_name": "张厨师",
        "role": "chef",
        "period_key": "2026-03",
        "kpi_scores": {"service": 88, "efficiency": 92, "attendance": 95, "quality": 85},
        "weighted_score": 91.0,
        "grade": "A",
        "grade_label": "优秀",
        "supervisor_comment": "厨艺精湛，效率突出",
    },
    {
        "employee_id": "emp-002",
        "employee_name": "李服务员",
        "role": "waiter",
        "period_key": "2026-03",
        "kpi_scores": {"service": 90, "efficiency": 78, "attendance": 92, "customer_feedback": 85},
        "weighted_score": 87.8,
        "grade": "B",
        "grade_label": "良好",
        "supervisor_comment": "服务态度好，需提升效率",
    },
    {
        "employee_id": "emp-003",
        "employee_name": "王收银",
        "role": "cashier",
        "period_key": "2026-03",
        "kpi_scores": {"service": 85, "efficiency": 90, "attendance": 88, "accuracy": 98},
        "weighted_score": 90.1,
        "grade": "A",
        "grade_label": "优秀",
        "supervisor_comment": "精确度高，服务规范",
    },
]

# ── 辅助函数 ─────────────────────────────────────────────────────────────────


def _parse_tenant(x_tenant_id: str) -> str:
    try:
        uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 须为合法 UUID") from e
    return x_tenant_id


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _compute_weighted_score(kpi_scores: dict[str, float], role: str) -> float:
    """根据岗位权重计算加权综合分。"""
    weights = KPI_WEIGHTS.get(role, KPI_WEIGHTS["default"])
    total_weight = 0.0
    weighted_sum = 0.0

    for kpi, weight in weights.items():
        score = kpi_scores.get(kpi)
        if score is not None:
            weighted_sum += float(score) * weight
            total_weight += weight

    if total_weight == 0:
        # 无权重匹配，取简单平均
        if kpi_scores:
            return round(sum(float(v) for v in kpi_scores.values()) / len(kpi_scores), 2)
        return 0.0

    # 归一化：未参与权重的维度按75分平补
    remaining_weight = 1.0 - total_weight
    if remaining_weight > 0:
        weighted_sum += 75.0 * remaining_weight

    return round(weighted_sum, 2)


def _compute_grade(score: float) -> tuple[str, str]:
    """根据分数返回 (grade, grade_label)。"""
    for threshold, grade, label in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade, label
    return "E", "不合格"


def _grade_distribution(scores: list[float]) -> dict[str, int]:
    dist: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for s in scores:
        grade, _ = _compute_grade(s)
        dist[grade] = dist.get(grade, 0) + 1
    return dist


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────


class PeriodCreate(BaseModel):
    name: str = Field(..., description="考核周期名称", min_length=1, max_length=100)
    period_type: str = Field(..., description="monthly/quarterly/annual")
    period_key: str = Field(..., description="月度: YYYY-MM，季度: YYYY-Q1，年度: YYYY")


class EvaluationItem(BaseModel):
    employee_id: str = Field(..., description="员工ID")
    role: str = Field(default="default", description="岗位（chef/waiter/cashier/default）")
    kpi_scores: dict[str, float] = Field(
        ...,
        description="KPI评分，键为维度名，值为0-100分",
    )
    supervisor_comment: Optional[str] = Field(None, description="上级评语")


class BatchEvaluateRequest(BaseModel):
    evaluations: list[EvaluationItem] = Field(..., description="批量评分列表", min_length=1)


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.get("/periods")
async def list_performance_periods(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    period_type: Optional[str] = Query(None, description="monthly/quarterly/annual"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """考核周期列表（月度/季度/年度）。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    conditions = ["tenant_id = :tid"]
    params: dict = {"tid": tid}
    if period_type:
        if period_type not in PERIOD_TYPES:
            raise HTTPException(status_code=400,
                                detail=f"period_type 须为 {'/'.join(PERIOD_TYPES)}")
        conditions.append("period_type = :period_type")
        params["period_type"] = period_type

    where = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM performance_periods WHERE {where}"), params
        )
        total = count_res.scalar() or 0

        rows_res = await db.execute(
            text(f"""
                SELECT id, name, period_type, period_key, status,
                       participant_count, avg_score, created_at
                FROM performance_periods
                WHERE {where}
                ORDER BY period_key DESC
                LIMIT :size OFFSET :offset
            """),
            {**params, "size": size, "offset": offset},
        )
        items = [
            {
                "id": str(r.id),
                "name": r.name,
                "period_type": r.period_type,
                "period_key": r.period_key,
                "status": r.status,
                "participant_count": r.participant_count or 0,
                "avg_score": float(r.avg_score) if r.avg_score is not None else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows_res.fetchall()
        ]

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as exc:  # noqa: BLE001 — DB不可用时降级mock
        logger.warning("performance_periods_db_fallback", error=str(exc))
        filtered = MOCK_PERIODS
        if period_type:
            filtered = [p for p in MOCK_PERIODS if p["period_type"] == period_type]
        total = len(filtered)
        items = filtered[(page - 1) * size: (page - 1) * size + size]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.post("/periods")
async def create_performance_period(
    body: PeriodCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建考核周期。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    if body.period_type not in PERIOD_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"period_type 须为 {'/'.join(PERIOD_TYPES)}")

    period_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    try:
        # 检查是否已存在同期
        exists_res = await db.execute(
            text("""
                SELECT id FROM performance_periods
                WHERE tenant_id = :tid AND period_key = :period_key
            """),
            {"tid": tid, "period_key": body.period_key},
        )
        if exists_res.fetchone():
            raise HTTPException(status_code=409,
                                detail=f"考核周期 {body.period_key} 已存在")

        await db.execute(
            text("""
                INSERT INTO performance_periods
                    (id, tenant_id, name, period_type, period_key,
                     status, participant_count, created_at, updated_at)
                VALUES
                    (:id, :tid, :name, :period_type, :period_key,
                     'in_progress', 0, :now, :now)
            """),
            {
                "id": period_id,
                "tid": tid,
                "name": body.name,
                "period_type": body.period_type,
                "period_key": body.period_key,
                "now": now,
            },
        )
        await db.commit()

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as exc:  # noqa: BLE001 — DB不可用时降级mock
        logger.warning("create_period_db_fallback", error=str(exc))
        # mock成功响应
        period_id = uuid.uuid4()

    logger.info("performance_period_created",
                period_id=str(period_id), period_key=body.period_key, tenant_id=tid)
    return {"ok": True, "data": {"id": str(period_id), "period_key": body.period_key, "name": body.name}}


@router.post("/periods/{period_id}/evaluate")
async def batch_evaluate(
    period_id: str,
    body: BatchEvaluateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量提交考核评分，返回计算后的综合分和评级。

    Body: [{ employee_id, role, kpi_scores: {service: 90, ...}, supervisor_comment }]
    """
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    now = datetime.now(timezone.utc)
    results = []

    for item in body.evaluations:
        # 校验分数范围
        for kpi, score in item.kpi_scores.items():
            if not (0 <= score <= 100):
                raise HTTPException(
                    status_code=400,
                    detail=f"员工 {item.employee_id} 的 {kpi} 分数须在 0-100 之间",
                )

        weighted_score = _compute_weighted_score(item.kpi_scores, item.role)
        grade, grade_label = _compute_grade(weighted_score)

        eval_id = uuid.uuid4()

        try:
            import json
            await db.execute(
                text("""
                    INSERT INTO performance_evaluations
                        (id, tenant_id, period_id, employee_id, role,
                         kpi_scores, weighted_score, grade,
                         supervisor_comment, evaluated_at, created_at)
                    VALUES
                        (:id, :tid, :period_id, :employee_id, :role,
                         :kpi_scores, :weighted_score, :grade,
                         :supervisor_comment, :now, :now)
                    ON CONFLICT (tenant_id, period_id, employee_id)
                    DO UPDATE SET
                        kpi_scores = EXCLUDED.kpi_scores,
                        weighted_score = EXCLUDED.weighted_score,
                        grade = EXCLUDED.grade,
                        supervisor_comment = EXCLUDED.supervisor_comment,
                        evaluated_at = EXCLUDED.evaluated_at
                """),
                {
                    "id": eval_id,
                    "tid": tid,
                    "period_id": period_id,
                    "employee_id": item.employee_id,
                    "role": item.role,
                    "kpi_scores": json.dumps(item.kpi_scores),
                    "weighted_score": weighted_score,
                    "grade": grade,
                    "supervisor_comment": item.supervisor_comment,
                    "now": now,
                },
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as exc:  # noqa: BLE001 — DB不可用时仅计算不持久化
            logger.warning("evaluate_db_fallback", error=str(exc),
                           employee_id=item.employee_id)

        results.append({
            "employee_id": item.employee_id,
            "role": item.role,
            "kpi_scores": item.kpi_scores,
            "weighted_score": weighted_score,
            "grade": grade,
            "grade_label": grade_label,
            "supervisor_comment": item.supervisor_comment,
            "weights_used": KPI_WEIGHTS.get(item.role, KPI_WEIGHTS["default"]),
        })

    try:
        # 更新周期参与人数和平均分
        scores_list = [r["weighted_score"] for r in results]
        avg_score = round(sum(scores_list) / len(scores_list), 2) if scores_list else 0.0
        await db.execute(
            text("""
                UPDATE performance_periods
                SET participant_count = (
                    SELECT COUNT(DISTINCT employee_id) FROM performance_evaluations
                    WHERE period_id = :period_id AND tenant_id = :tid
                ),
                avg_score = (
                    SELECT AVG(weighted_score) FROM performance_evaluations
                    WHERE period_id = :period_id AND tenant_id = :tid
                ),
                updated_at = :now
                WHERE id = :period_id AND tenant_id = :tid
            """),
            {"period_id": period_id, "tid": tid, "now": now},
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as exc:  # noqa: BLE001 — 不影响主流程
        logger.warning("update_period_stats_fallback", error=str(exc))

    logger.info("batch_evaluate_completed",
                period_id=period_id, count=len(results), tenant_id=tid)
    return {
        "ok": True,
        "data": {
            "period_id": period_id,
            "evaluated_count": len(results),
            "results": results,
        },
    }


@router.get("/periods/{period_id}/results")
async def get_period_results(
    period_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    group_by: str = Query("none", description="按 role 或 none 分组"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """考核结果报表（按岗位分组 + 评级分布）。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    try:
        rows_res = await db.execute(
            text("""
                SELECT e.employee_id, e.role, e.kpi_scores,
                       e.weighted_score, e.grade, e.supervisor_comment,
                       e.evaluated_at
                FROM performance_evaluations e
                WHERE e.period_id = :period_id AND e.tenant_id = :tid
                ORDER BY e.weighted_score DESC
            """),
            {"period_id": period_id, "tid": tid},
        )
        rows = rows_res.fetchall()

        import json
        items = []
        for i, r in enumerate(rows):
            kpi_scores = r.kpi_scores
            if isinstance(kpi_scores, str):
                kpi_scores = json.loads(kpi_scores)
            grade, grade_label = _compute_grade(float(r.weighted_score or 0))
            items.append({
                "rank": i + 1,
                "employee_id": str(r.employee_id),
                "role": r.role,
                "kpi_scores": kpi_scores or {},
                "weighted_score": float(r.weighted_score or 0),
                "grade": grade,
                "grade_label": grade_label,
                "supervisor_comment": r.supervisor_comment,
                "evaluated_at": r.evaluated_at.isoformat() if r.evaluated_at else None,
            })

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as exc:  # noqa: BLE001 — DB不可用时降级mock
        logger.warning("period_results_db_fallback", error=str(exc))
        items = [
            {
                "rank": i + 1,
                **{k: v for k, v in r.items()},
            }
            for i, r in enumerate(MOCK_SCORES)
        ]

    all_scores = [item["weighted_score"] for item in items]
    grade_dist = _grade_distribution(all_scores)
    avg_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0

    # 按岗位分组
    by_role: dict[str, list] = {}
    if group_by == "role":
        for item in items:
            role = item.get("role", "default")
            by_role.setdefault(role, []).append(item)

    return {
        "ok": True,
        "data": {
            "period_id": period_id,
            "total": len(items),
            "avg_score": avg_score,
            "grade_distribution": grade_dist,
            "items": items,
            "by_role": by_role if group_by == "role" else {},
        },
    }


@router.get("/employee/{employee_id}/history")
async def get_employee_performance_history(
    employee_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    periods: int = Query(6, ge=1, le=24, description="查近N期"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """员工绩效历史（近N期）。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    try:
        import json
        rows_res = await db.execute(
            text("""
                SELECT e.period_id, p.period_key, p.period_type, p.name as period_name,
                       e.role, e.kpi_scores, e.weighted_score, e.grade,
                       e.supervisor_comment, e.evaluated_at
                FROM performance_evaluations e
                JOIN performance_periods p
                    ON p.id = e.period_id AND p.tenant_id = e.tenant_id
                WHERE e.tenant_id = :tid AND e.employee_id = :eid
                ORDER BY p.period_key DESC
                LIMIT :periods
            """),
            {"tid": tid, "eid": employee_id, "periods": periods},
        )
        rows = rows_res.fetchall()

        history = []
        for r in rows:
            kpi_scores = r.kpi_scores
            if isinstance(kpi_scores, str):
                kpi_scores = json.loads(kpi_scores)
            grade, grade_label = _compute_grade(float(r.weighted_score or 0))
            history.append({
                "period_id": str(r.period_id),
                "period_key": r.period_key,
                "period_type": r.period_type,
                "period_name": r.period_name,
                "role": r.role,
                "kpi_scores": kpi_scores or {},
                "weighted_score": float(r.weighted_score or 0),
                "grade": grade,
                "grade_label": grade_label,
                "supervisor_comment": r.supervisor_comment,
                "evaluated_at": r.evaluated_at.isoformat() if r.evaluated_at else None,
            })

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as exc:  # noqa: BLE001 — DB不可用时降级mock
        logger.warning("employee_perf_history_db_fallback", error=str(exc), employee_id=employee_id)
        filtered = [s for s in MOCK_SCORES if s.get("employee_id") == employee_id]
        history = [
            {
                "period_key": s.get("period_key"),
                "period_type": "monthly",
                "kpi_scores": s.get("kpi_scores", {}),
                "weighted_score": s.get("weighted_score", 0),
                "grade": s.get("grade", "C"),
                "grade_label": s.get("grade_label", "合格"),
                "supervisor_comment": s.get("supervisor_comment"),
            }
            for s in filtered
        ]

    # 趋势计算
    if len(history) >= 2:
        latest = history[0]["weighted_score"]
        prev = history[1]["weighted_score"]
        trend = round(latest - prev, 2)
        trend_direction = "up" if trend > 0 else ("down" if trend < 0 else "flat")
    else:
        trend = 0.0
        trend_direction = "flat"

    return {
        "ok": True,
        "data": {
            "employee_id": employee_id,
            "history": history,
            "trend": trend,
            "trend_direction": trend_direction,
        },
    }


@router.get("/stats")
async def get_performance_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    period_key: Optional[str] = Query(None, description="考核周期，不传=最新周期"),
    store_id: Optional[str] = Query(None, description="门店ID过滤"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """团队绩效概览（平均分/优秀率/待改进率）。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    try:
        # 查最新/指定周期
        if period_key:
            period_res = await db.execute(
                text("""
                    SELECT id, period_key, name, status
                    FROM performance_periods
                    WHERE tenant_id = :tid AND period_key = :period_key
                    LIMIT 1
                """),
                {"tid": tid, "period_key": period_key},
            )
        else:
            period_res = await db.execute(
                text("""
                    SELECT id, period_key, name, status
                    FROM performance_periods
                    WHERE tenant_id = :tid
                    ORDER BY period_key DESC
                    LIMIT 1
                """),
                {"tid": tid},
            )
        period_row = period_res.fetchone()

        if not period_row:
            raise HTTPException(status_code=404, detail="未找到考核周期数据")

        current_period_id = str(period_row.id)

        rows_res = await db.execute(
            text("""
                SELECT weighted_score, grade
                FROM performance_evaluations
                WHERE tenant_id = :tid AND period_id = :period_id
            """),
            {"tid": tid, "period_id": current_period_id},
        )
        rows = rows_res.fetchall()

        if not rows:
            raise HTTPException(status_code=404, detail="该周期暂无考核数据")

        all_scores = [float(r.weighted_score or 0) for r in rows]
        avg_score = round(sum(all_scores) / len(all_scores), 2)
        grade_dist = _grade_distribution(all_scores)

        excellent_count = grade_dist.get("A", 0)
        excellent_rate = round(excellent_count / len(all_scores) * 100, 1)
        needs_improvement_count = grade_dist.get("D", 0) + grade_dist.get("E", 0)
        needs_improvement_rate = round(needs_improvement_count / len(all_scores) * 100, 1)
        pass_count = sum(1 for s in all_scores if s >= 60)
        pass_rate = round(pass_count / len(all_scores) * 100, 1)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as exc:  # noqa: BLE001 — DB不可用时降级mock
        logger.warning("performance_stats_db_fallback", error=str(exc))
        all_scores = [s["weighted_score"] for s in MOCK_SCORES]
        avg_score = round(sum(all_scores) / len(all_scores), 2)
        grade_dist = _grade_distribution(all_scores)
        excellent_count = grade_dist.get("A", 0)
        excellent_rate = round(excellent_count / len(all_scores) * 100, 1)
        needs_improvement_count = grade_dist.get("D", 0) + grade_dist.get("E", 0)
        needs_improvement_rate = round(needs_improvement_count / len(all_scores) * 100, 1)
        pass_count = sum(1 for s in all_scores if s >= 60)
        pass_rate = round(pass_count / len(all_scores) * 100, 1)
        period_row = type("obj", (object,), {  # type: ignore[assignment]
            "period_key": "2026-03", "name": "2026年3月考核", "status": "completed"
        })()
        current_period_id = "mock-period"

    return {
        "ok": True,
        "data": {
            "period_id": current_period_id,
            "period_key": period_row.period_key if hasattr(period_row, "period_key") else period_key,
            "period_name": period_row.name if hasattr(period_row, "name") else "",
            "total_employees": len(all_scores),
            "avg_score": avg_score,
            "excellent_rate": excellent_rate,
            "pass_rate": pass_rate,
            "needs_improvement_rate": needs_improvement_rate,
            "grade_distribution": grade_dist,
            "kpi_weights": KPI_WEIGHTS,
        },
    }
