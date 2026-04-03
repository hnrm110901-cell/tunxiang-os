"""E8 区域追踪与整改 — 整改派发、进度跟踪、复查、评分卡、跨店对标、月报、归档

整改状态机: dispatched → in_progress → submitted → reviewed → closed
评分卡分级: 绿(≥80) / 黄(60-79) / 红(<60)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  整改状态机
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RECTIFICATION_STATUSES = (
    "dispatched", "in_progress", "submitted", "reviewed", "closed",
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
    """派发一条整改任务给指定责任人。

    Args:
        region_id: 区域 ID
        store_id: 门店 ID
        issue_id: 关联问题 ID
        assignee_id: 责任人 ID
        deadline: 整改截止日期 (YYYY-MM-DD)
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        整改单字典，含 rectification_id 和初始状态 dispatched
    """
    rectification_id = f"rect_{region_id}_{uuid.uuid4().hex[:8]}"
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
    """更新整改进度。

    Args:
        rectification_id: 整改单 ID
        tenant_id: 租户 ID
        db: 数据库会话
        record: 已加载整改记录（测试注入用）
        new_status: 目标状态
        note: 进度备注

    Returns:
        更新后的整改记录
    """
    if new_status and new_status not in RECTIFICATION_STATUSES:
        raise ValueError(f"Invalid rectification status: {new_status}")

    if record is not None and new_status:
        current = record.get("status", "dispatched")
        if not _can_transition(current, new_status):
            raise ValueError(
                f"Cannot transition from '{current}' to '{new_status}'"
            )
        record["status"] = new_status
        record["updated_at"] = _now_iso()
        if note:
            record.setdefault("progress_notes", []).append({
                "text": note,
                "status": new_status,
                "timestamp": _now_iso(),
            })

    log.info(
        "rectification_tracked",
        rectification_id=rectification_id,
        tenant_id=tenant_id,
        new_status=new_status,
    )

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
    """提交整改复查结果。

    Args:
        rectification_id: 整改单 ID
        reviewer_id: 复查人 ID
        result: 复查结果 (pass / fail)
        tenant_id: 租户 ID
        db: 数据库会话
        record: 已加载整改记录（测试注入用）
        comment: 复查意见

    Returns:
        复查结果字典
    """
    if result not in ("pass", "fail"):
        raise ValueError(f"Review result must be 'pass' or 'fail', got '{result}'")

    now = _now_iso()

    if record is not None:
        current = record.get("status", "dispatched")
        # 复查只能在 submitted 状态进行
        if current != "submitted":
            raise ValueError(
                f"Review requires status 'submitted', current is '{current}'"
            )
        record["status"] = "reviewed"
        record["review_result"] = result
        record["reviewer_id"] = reviewer_id
        record["review_comment"] = comment
        record["reviewed_at"] = now
        record["updated_at"] = now

        # 如果通过，自动关闭
        if result == "pass":
            record["status"] = "closed"
            record["closed_at"] = now

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
        "status": "closed" if result == "pass" else "reviewed",
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
    """获取区域门店红黄绿评分卡。

    Args:
        region_id: 区域 ID
        tenant_id: 租户 ID
        db: 数据库会话
        store_scores: [{store_id, score}] 各门店分数（测试注入用）

    Returns:
        评分卡字典，包含各门店颜色及汇总
    """
    scores = store_scores or []
    cards: List[Dict[str, Any]] = []
    color_counts = {"green": 0, "yellow": 0, "red": 0}

    for entry in scores:
        score = entry.get("score", 0)
        color = _score_to_color(score)
        color_counts[color] += 1
        cards.append({
            "store_id": entry.get("store_id", ""),
            "score": score,
            "color": color,
        })

    # 按分数升序，最差排前面
    cards.sort(key=lambda c: c["score"])

    avg_score = round(
        sum(e.get("score", 0) for e in scores) / len(scores), 1
    ) if scores else 0.0

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
    """跨店同指标对标。

    Args:
        metric: 对标指标名称 (如 food_safety_score / hygiene_score)
        region_id: 区域 ID
        tenant_id: 租户 ID
        db: 数据库会话
        store_metrics: {store_id: value} 各门店指标值（测试注入用）

    Returns:
        对标结果，含排名和统计
    """
    data = store_metrics or {}

    ranked: List[Dict[str, Any]] = [
        {"store_id": sid, "value": val} for sid, val in data.items()
    ]
    ranked.sort(key=lambda x: x["value"], reverse=True)

    # 添加排名
    for idx, item in enumerate(ranked, 1):
        item["rank"] = idx

    values = list(data.values())
    total = sum(values) if values else 0.0
    avg = round(total / len(values), 2) if values else 0.0

    log.info(
        "cross_store_benchmark",
        metric=metric,
        region_id=region_id,
        tenant_id=tenant_id,
        store_count=len(data),
    )

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
    """生成区域月报。

    Args:
        region_id: 区域 ID
        month: 月份 (YYYY-MM)
        tenant_id: 租户 ID
        db: 数据库会话
        rectifications: 整改记录列表（测试注入用）
        store_scores: 门店分数列表（测试注入用）

    Returns:
        月报字典，含整改统计和评分汇总
    """
    rects = rectifications or []
    scores = store_scores or []

    # 整改统计
    total_rects = len(rects)
    closed = sum(1 for r in rects if r.get("status") == "closed")
    in_progress = sum(1 for r in rects if r.get("status") in ("dispatched", "in_progress", "submitted"))
    reviewed_fail = sum(1 for r in rects if r.get("status") == "reviewed" and r.get("review_result") == "fail")

    closure_rate = round(closed / total_rects * 100, 1) if total_rects else 0.0

    # 评分汇总
    avg_score = round(
        sum(s.get("score", 0) for s in scores) / len(scores), 1
    ) if scores else 0.0

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
    """获取区域整改归档（已关闭的整改记录）。

    Args:
        region_id: 区域 ID
        tenant_id: 租户 ID
        db: 数据库会话
        rectifications: 全部整改记录（测试注入用）

    Returns:
        归档字典，含已关闭整改列表及统计
    """
    all_rects = rectifications or []
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
