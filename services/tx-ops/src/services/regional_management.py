"""E8 区域追踪与整改 — 整改派发、进度跟踪、复查、评分卡、跨店对标、月报、归档

整改状态机: dispatched → in_progress → submitted → reviewed → closed
评分卡分级: 绿(≥80) / 黄(60-79) / 红(<60)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  整改状态机
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RECTIFICATION_STATUSES = (
    "dispatched",
    "in_progress",
    "submitted",
    "reviewed",
    "closed",
)

RECTIFICATION_TRANSITIONS: Dict[str, tuple[str, ...]] = {
    "dispatched": ("in_progress",),
    "in_progress": ("submitted",),
    "submitted": ("reviewed",),
    "reviewed": ("closed",),
    "closed": (),
}

# 评分卡阈值
SCORE_GREEN_THRESHOLD = 80
SCORE_YELLOW_THRESHOLD = 60


def _can_transition(current: str, target: str) -> bool:
    return target in RECTIFICATION_TRANSITIONS.get(current, ())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _set_rls(db: Any, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _serialize_row(row_mapping: dict) -> dict:
    result = {}
    for key, val in row_mapping.items():
        if val is None:
            result[key] = None
        elif hasattr(val, "isoformat"):
            result[key] = val.isoformat()
        elif hasattr(val, "hex"):
            result[key] = str(val)
        else:
            result[key] = val
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 区域整改派发
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def dispatch_rectification(
    region_id: str,
    store_id: str,
    issue_id: str,
    assignee_id: str,
    deadline: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """派发一条整改任务给指定责任人，写入 DB。"""
    rectification_id = str(uuid.uuid4())
    now = _now_iso()

    record: Dict[str, Any] = {
        "rectification_id": rectification_id,
        "region_id": region_id,
        "store_id": store_id,
        "issue_id": issue_id,
        "assignee_id": assignee_id,
        "deadline": deadline,
        "status": "dispatched",
        "tenant_id": tenant_id,
        "progress_notes": [],
        "review_result": None,
        "created_at": now,
        "updated_at": now,
    }

    if db is not None:
        try:
            await _set_rls(db, tenant_id)
            await db.execute(
                text(
                    """
                    INSERT INTO regional_rectifications
                      (id, tenant_id, region_id, store_id, issue_id, assignee_id,
                       deadline, status, created_at, updated_at)
                    VALUES
                      (:id, NULLIF(current_setting('app.tenant_id', true), '')::uuid,
                       :region_id, :store_id, :issue_id, :assignee_id,
                       :deadline, 'dispatched', NOW(), NOW())
                    """
                ),
                {
                    "id": rectification_id,
                    "region_id": region_id,
                    "store_id": store_id,
                    "issue_id": issue_id,
                    "assignee_id": assignee_id,
                    "deadline": deadline,
                },
            )
        except SQLAlchemyError as exc:
            log.error("dispatch_rectification_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    log.info(
        "rectification_dispatched",
        rectification_id=rectification_id,
        region_id=region_id,
        store_id=store_id,
        tenant_id=tenant_id,
        assignee_id=assignee_id,
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 进度跟踪
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def track_rectification(
    rectification_id: str,
    tenant_id: str,
    db: Any,
    *,
    record: Optional[Dict[str, Any]] = None,
    new_status: Optional[str] = None,
    note: str = "",
) -> Dict[str, Any]:
    """更新整改进度。"""
    if new_status and new_status not in RECTIFICATION_STATUSES:
        raise ValueError(f"Invalid rectification status: {new_status}")

    if db is not None and new_status:
        try:
            await _set_rls(db, tenant_id)
            check_result = await db.execute(
                text(
                    """
                    SELECT id, status FROM regional_rectifications
                    WHERE id = :id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                    LIMIT 1
                    """
                ),
                {"id": rectification_id},
            )
            row = check_result.fetchone()
            if row:
                current = row.status
                if not _can_transition(current, new_status):
                    raise ValueError(f"Cannot transition from '{current}' to '{new_status}'")
                await db.execute(
                    text(
                        """
                        UPDATE regional_rectifications
                        SET status = :status, updated_at = NOW()
                        WHERE id = :id
                          AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        """
                    ),
                    {"status": new_status, "id": rectification_id},
                )
        except ValueError:
            raise
        except SQLAlchemyError as exc:
            log.error("track_rectification_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
    elif record is not None and new_status:
        current = record.get("status", "dispatched")
        if not _can_transition(current, new_status):
            raise ValueError(f"Cannot transition from '{current}' to '{new_status}'")
        record["status"] = new_status
        record["updated_at"] = _now_iso()
        if note:
            record.setdefault("progress_notes", []).append(
                {
                    "text": note,
                    "status": new_status,
                    "timestamp": _now_iso(),
                }
            )

    log.info("rectification_tracked", rectification_id=rectification_id, tenant_id=tenant_id, new_status=new_status)

    return {
        "rectification_id": rectification_id,
        "status": new_status or (record or {}).get("status", "unknown"),
        "note": note,
        "updated_at": _now_iso(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 复查记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def submit_review(
    rectification_id: str,
    reviewer_id: str,
    result: str,
    tenant_id: str,
    db: Any,
    *,
    record: Optional[Dict[str, Any]] = None,
    comment: str = "",
) -> Dict[str, Any]:
    """提交整改复查结果。"""
    if result not in ("pass", "fail"):
        raise ValueError(f"Review result must be 'pass' or 'fail', got '{result}'")

    now = _now_iso()
    final_status = "closed" if result == "pass" else "reviewed"

    if db is not None:
        try:
            await _set_rls(db, tenant_id)
            check_result = await db.execute(
                text(
                    """
                    SELECT id, status FROM regional_rectifications
                    WHERE id = :id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                    LIMIT 1
                    """
                ),
                {"id": rectification_id},
            )
            row = check_result.fetchone()
            if row:
                current = row.status
                if current != "submitted":
                    raise ValueError(f"Review requires status 'submitted', current is '{current}'")
                await db.execute(
                    text(
                        """
                        UPDATE regional_rectifications
                        SET status = :status, reviewer_id = :reviewer_id,
                            review_result = :review_result, review_comment = :comment,
                            reviewed_at = NOW(), updated_at = NOW()
                        WHERE id = :id
                          AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        """
                    ),
                    {
                        "status": final_status,
                        "reviewer_id": reviewer_id,
                        "review_result": result,
                        "comment": comment,
                        "id": rectification_id,
                    },
                )
        except ValueError:
            raise
        except SQLAlchemyError as exc:
            log.error("submit_review_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
    elif record is not None:
        current = record.get("status", "dispatched")
        if current != "submitted":
            raise ValueError(f"Review requires status 'submitted', current is '{current}'")
        record["status"] = final_status
        record["review_result"] = result
        record["reviewer_id"] = reviewer_id
        record["review_comment"] = comment
        record["reviewed_at"] = now
        record["updated_at"] = now

    log.info(
        "rectification_reviewed",
        rectification_id=rectification_id,
        tenant_id=tenant_id,
        reviewer_id=reviewer_id,
        result=result,
    )

    return {
        "rectification_id": rectification_id,
        "reviewer_id": reviewer_id,
        "result": result,
        "comment": comment,
        "status": final_status,
        "reviewed_at": now,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 区域门店红黄绿评分卡
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _score_to_color(score: float) -> str:
    """绿(>=80) / 黄(60-79) / 红(<60)"""
    if score >= SCORE_GREEN_THRESHOLD:
        return "green"
    if score >= SCORE_YELLOW_THRESHOLD:
        return "yellow"
    return "red"


async def get_regional_scorecard(
    region_id: str,
    tenant_id: str,
    db: Any,
    *,
    store_scores: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """获取区域门店红黄绿评分卡（从 DB 查询）。"""
    scores: List[Dict[str, Any]] = store_scores or []

    if db is not None and not store_scores:
        try:
            await _set_rls(db, tenant_id)
            rows_result = await db.execute(
                text(
                    """
                    SELECT store_id,
                           COALESCE(AVG(score), 0) AS score
                    FROM store_inspection_scores
                    WHERE region_id = :region_id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                      AND scored_at >= NOW() - INTERVAL '30 days'
                    GROUP BY store_id
                    """
                ),
                {"region_id": region_id},
            )
            scores = [{"store_id": row.store_id, "score": float(row.score)} for row in rows_result]
        except SQLAlchemyError as exc:
            log.error("regional_scorecard_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    cards: List[Dict[str, Any]] = []
    color_counts = {"green": 0, "yellow": 0, "red": 0}

    for entry in scores:
        score = entry.get("score", 0)
        color = _score_to_color(score)
        color_counts[color] += 1
        cards.append(
            {
                "store_id": entry.get("store_id", ""),
                "score": score,
                "color": color,
            }
        )

    cards.sort(key=lambda c: c["score"])

    avg_score = round(sum(e.get("score", 0) for e in scores) / len(scores), 1) if scores else 0.0

    log.info(
        "regional_scorecard_generated",
        region_id=region_id,
        tenant_id=tenant_id,
        store_count=len(scores),
        avg_score=avg_score,
    )

    return {
        "region_id": region_id,
        "tenant_id": tenant_id,
        "avg_score": avg_score,
        "color_counts": color_counts,
        "stores": cards,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 跨店对标
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def cross_store_benchmark(
    metric: str,
    region_id: str,
    tenant_id: str,
    db: Any,
    *,
    store_metrics: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """跨店同指标对标（从 DB 查询）。"""
    data: Dict[str, float] = store_metrics or {}

    if db is not None and not store_metrics:
        try:
            await _set_rls(db, tenant_id)
            rows_result = await db.execute(
                text(
                    """
                    SELECT store_id, AVG(metric_value) AS avg_val
                    FROM store_metrics_daily
                    WHERE region_id = :region_id
                      AND metric_name = :metric
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                      AND metric_date >= NOW() - INTERVAL '30 days'
                    GROUP BY store_id
                    """
                ),
                {"region_id": region_id, "metric": metric},
            )
            data = {row.store_id: float(row.avg_val) for row in rows_result}
        except SQLAlchemyError as exc:
            log.error("cross_store_benchmark_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    ranked: List[Dict[str, Any]] = [{"store_id": sid, "value": val} for sid, val in data.items()]
    ranked.sort(key=lambda x: x["value"], reverse=True)

    for idx, item in enumerate(ranked, 1):
        item["rank"] = idx

    values = list(data.values())
    total = sum(values) if values else 0.0
    avg = round(total / len(values), 2) if values else 0.0

    log.info("cross_store_benchmark", metric=metric, region_id=region_id, tenant_id=tenant_id, store_count=len(data))

    return {
        "metric": metric,
        "region_id": region_id,
        "tenant_id": tenant_id,
        "summary": {
            "avg": avg,
            "max": max(values) if values else 0.0,
            "min": min(values) if values else 0.0,
            "total_stores": len(values),
        },
        "ranking": ranked,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 区域月报
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def generate_regional_report(
    region_id: str,
    month: str,
    tenant_id: str,
    db: Any,
    *,
    rectifications: Optional[List[Dict[str, Any]]] = None,
    store_scores: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """生成区域月报（从 DB 查询整改记录和评分）。"""
    rects: List[Dict[str, Any]] = rectifications or []
    scores: List[Dict[str, Any]] = store_scores or []

    if db is not None and not rectifications:
        try:
            await _set_rls(db, tenant_id)
            rows_result = await db.execute(
                text(
                    """
                    SELECT id, status, review_result
                    FROM regional_rectifications
                    WHERE region_id = :region_id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                      AND TO_CHAR(created_at, 'YYYY-MM') = :month
                    """
                ),
                {"region_id": region_id, "month": month},
            )
            rects = [_serialize_row(dict(row._mapping)) for row in rows_result]
        except SQLAlchemyError as exc:
            log.error("regional_report_rects_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    if db is not None and not store_scores:
        try:
            await _set_rls(db, tenant_id)
            rows_result = await db.execute(
                text(
                    """
                    SELECT store_id, AVG(score) AS score
                    FROM store_inspection_scores
                    WHERE region_id = :region_id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                      AND TO_CHAR(scored_at, 'YYYY-MM') = :month
                    GROUP BY store_id
                    """
                ),
                {"region_id": region_id, "month": month},
            )
            scores = [{"store_id": row.store_id, "score": float(row.score)} for row in rows_result]
        except SQLAlchemyError as exc:
            log.error("regional_report_scores_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    total_rects = len(rects)
    closed = sum(1 for r in rects if r.get("status") == "closed")
    in_progress = sum(1 for r in rects if r.get("status") in ("dispatched", "in_progress", "submitted"))
    reviewed_fail = sum(1 for r in rects if r.get("status") == "reviewed" and r.get("review_result") == "fail")
    closure_rate = round(closed / total_rects * 100, 1) if total_rects else 0.0

    avg_score = round(sum(s.get("score", 0) for s in scores) / len(scores), 1) if scores else 0.0

    log.info(
        "regional_report_generated",
        region_id=region_id,
        month=month,
        tenant_id=tenant_id,
        total_rects=total_rects,
        closure_rate=closure_rate,
    )

    return {
        "region_id": region_id,
        "month": month,
        "tenant_id": tenant_id,
        "generated_at": _now_iso(),
        "rectification_summary": {
            "total": total_rects,
            "closed": closed,
            "in_progress": in_progress,
            "reviewed_fail": reviewed_fail,
            "closure_rate_pct": closure_rate,
        },
        "score_summary": {
            "avg_score": avg_score,
            "store_count": len(scores),
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 整改归档
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_rectification_archive(
    region_id: str,
    tenant_id: str,
    db: Any,
    *,
    rectifications: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """获取区域整改归档（从 DB 查询已关闭和进行中的整改记录）。"""
    all_rects: List[Dict[str, Any]] = rectifications or []

    if db is not None and not rectifications:
        try:
            await _set_rls(db, tenant_id)
            rows_result = await db.execute(
                text(
                    """
                    SELECT id AS rectification_id, region_id, store_id, issue_id,
                           assignee_id, deadline, status, review_result,
                           reviewer_id, review_comment, created_at, updated_at
                    FROM regional_rectifications
                    WHERE region_id = :region_id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                    ORDER BY created_at DESC
                    """
                ),
                {"region_id": region_id},
            )
            all_rects = [_serialize_row(dict(row._mapping)) for row in rows_result]
        except SQLAlchemyError as exc:
            log.error("rectification_archive_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    archived = [r for r in all_rects if r.get("status") == "closed"]
    pending = [r for r in all_rects if r.get("status") != "closed"]

    log.info(
        "rectification_archive_queried",
        region_id=region_id,
        tenant_id=tenant_id,
        archived_count=len(archived),
        pending_count=len(pending),
    )

    return {
        "region_id": region_id,
        "tenant_id": tenant_id,
        "archived": archived,
        "pending": pending,
        "summary": {
            "archived_count": len(archived),
            "pending_count": len(pending),
            "total": len(all_rects),
        },
    }
