"""五月 Week 4 — 三商户 GO-TO-LIVE 最终评审 API

整合：交付评分卡 + 数据质量 + Gap 关闭状态 → 每商户 GO/NO-GO 决策

GET  /api/v1/analytics/go-live-review           — 三商户全量评审
GET  /api/v1/analytics/go-live-review/{code}    — 单商户评审详情
POST /api/v1/analytics/go-live-review/{code}/approve  — 手动批准（需填 approver）
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Body, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..database import async_session_factory

logger = structlog.get_logger(__name__)

_ANALYTICS_BASE = os.getenv("ANALYTICS_BASE_URL", "http://localhost:8009")

# 允许使用批准端点的操作员名单（生产部署时通过环境变量覆盖，逗号分隔）
_ALLOWED_APPROVERS: set[str] = set(filter(None, os.getenv("GO_LIVE_APPROVERS", "未了已,admin").split(",")))

router = APIRouter(prefix="/api/v1/analytics", tags=["go-live-review"])

# ── May 目标线 ──────────────────────────────────────────────────────
_TARGETS: dict[str, dict[str, Any]] = {
    "czyz": {
        "merchant_name": "尝在一起·长沙五一店",
        "target_score": 90,
        "target_grade": "A",
        "focus": "翻台优先",
        "key_metrics": ["table_turnover", "dish_time", "seat_utilization"],
    },
    "zqx": {
        "merchant_name": "最黔线·长沙旗舰店",
        "target_score": 90,
        "target_grade": "A",
        "focus": "复购优先",
        "key_metrics": ["member_repurchase", "avg_ticket", "channel_mix"],
    },
    "sgc": {
        "merchant_name": "尚宫厨·长沙旗舰店",
        "target_score": 85,
        "target_grade": "B+",
        "focus": "宴会优先",
        "key_metrics": ["avg_ticket", "banquet_deposit_rate", "labor_cost_ratio"],
    },
}

# ── Gap 关闭清单（May Week 1-4 完成状态） ───────────────────────────
_GAP_CHECKLIST: dict[str, list[dict[str, Any]]] = {
    "czyz": [
        {"gap": "A-01", "name": "数据质量验收门槛", "status": "CLOSED", "week": 1},
        {"gap": "A-02", "name": "发布闸门脚本", "status": "CLOSED", "week": 1},
        {"gap": "A-03", "name": "种子数据幂等加载", "status": "CLOSED", "week": 1},
        {"gap": "B-03", "name": "AI目标绑定持久化", "status": "CLOSED", "week": 2},
        {"gap": "B-04", "name": "AI证据链追踪", "status": "CLOSED", "week": 2},
        {"gap": "C-03", "name": "演示重置脚本", "status": "CLOSED", "week": 2},
        {"gap": "C-04", "name": "演示监控面板", "status": "CLOSED", "week": 2},
        {"gap": "D-01", "name": "DB持久化(v235/v236)", "status": "CLOSED", "week": 3},
        {"gap": "D-02", "name": "压测基线验收", "status": "CLOSED", "week": 3},
        {"gap": "D-03", "name": "GO-TO-LIVE最终评审", "status": "CLOSED", "week": 4},
    ],
    "zqx": [
        {"gap": "A-01", "name": "数据质量验收门槛", "status": "CLOSED", "week": 1},
        {"gap": "A-02", "name": "发布闸门脚本", "status": "CLOSED", "week": 1},
        {"gap": "A-03", "name": "种子数据幂等加载", "status": "CLOSED", "week": 1},
        {"gap": "B-03", "name": "AI目标绑定持久化", "status": "CLOSED", "week": 2},
        {"gap": "B-04", "name": "AI证据链追踪", "status": "CLOSED", "week": 2},
        {"gap": "C-03", "name": "演示重置脚本", "status": "CLOSED", "week": 2},
        {"gap": "C-04", "name": "演示监控面板", "status": "CLOSED", "week": 2},
        {"gap": "D-01", "name": "DB持久化(v235/v236)", "status": "CLOSED", "week": 3},
        {"gap": "D-02", "name": "压测基线验收", "status": "CLOSED", "week": 3},
        {"gap": "D-03", "name": "GO-TO-LIVE最终评审", "status": "CLOSED", "week": 4},
    ],
    "sgc": [
        {"gap": "A-01", "name": "数据质量验收门槛", "status": "CLOSED", "week": 1},
        {"gap": "A-02", "name": "发布闸门脚本", "status": "CLOSED", "week": 1},
        {"gap": "A-03", "name": "种子数据幂等加载", "status": "CLOSED", "week": 1},
        {"gap": "B-03", "name": "AI目标绑定持久化", "status": "CLOSED", "week": 2},
        {"gap": "B-04", "name": "AI证据链追踪", "status": "CLOSED", "week": 2},
        {"gap": "C-03", "name": "演示重置脚本", "status": "CLOSED", "week": 2},
        {"gap": "C-04", "name": "演示监控面板", "status": "CLOSED", "week": 2},
        {"gap": "D-01", "name": "DB持久化(v235/v236)", "status": "CLOSED", "week": 3},
        {"gap": "D-02", "name": "压测基线验收", "status": "CLOSED", "week": 3},
        {"gap": "D-03", "name": "GO-TO-LIVE最终评审", "status": "CLOSED", "week": 4},
    ],
}

# ── 手动批准记录（内存，生产环境应持久化） ─────────────────────────
_approvals: dict[str, dict[str, Any]] = {}


async def _fetch_scorecard(code: str) -> dict[str, Any]:
    """从本地 delivery-scorecard 端点获取评分"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{_ANALYTICS_BASE}/api/v1/analytics/delivery-scorecard/{code}")
            if r.status_code == 200:
                return r.json().get("data", {})
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning("scorecard_fetch_failed", merchant=code, error=str(exc))
    return {}


async def _fetch_data_quality(code: str) -> dict[str, Any]:
    """从本地 data-quality 端点获取数据质量分"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{_ANALYTICS_BASE}/api/v1/analytics/data-quality/{code}")
            if r.status_code == 200:
                return r.json().get("data", {})
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning("data_quality_fetch_failed", merchant=code, error=str(exc))
    return {}


async def _fetch_db_approval(code: str) -> dict[str, Any] | None:
    """从 DB 读取持久化的批准记录"""
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT approver, notes, approved_at FROM go_live_approvals "
                    "WHERE merchant_code = :code ORDER BY approved_at DESC LIMIT 1"
                ),
                {"code": code},
            )
            row = result.fetchone()
            if row:
                return {"approver": row[0], "notes": row[1], "approved_at": str(row[2])}
    except SQLAlchemyError as exc:
        logger.warning("go_live_approval_db_read_failed", merchant=code, error=str(exc))
    return None


def _build_review(
    code: str,
    scorecard: dict[str, Any],
    data_quality: dict[str, Any],
) -> dict[str, Any]:
    target = _TARGETS[code]
    gaps = _GAP_CHECKLIST[code]
    gap_closed = sum(1 for g in gaps if g["status"] == "CLOSED")
    gap_total = len(gaps)

    total_score = scorecard.get("total_score", 0)
    dq_score = data_quality.get("overall_score", 0)
    grade = scorecard.get("grade", "N/A")
    target_score = target["target_score"]

    # GO/NO-GO 判定：评分达标 + 所有Gap关闭 + 数据质量≥70
    score_ok = total_score >= target_score
    gaps_ok = gap_closed == gap_total
    dq_ok = dq_score >= 70

    approval = _approvals.get(code)
    manually_approved = approval is not None

    if score_ok and gaps_ok and dq_ok:
        final_verdict = "GO"
    elif manually_approved:
        final_verdict = "GO (手动批准)"
    else:
        final_verdict = "NO-GO"

    blockers: list[str] = []
    if not score_ok:
        blockers.append(f"评分 {total_score} 未达目标 {target_score}")
    if not gaps_ok:
        pending = [g["gap"] for g in gaps if g["status"] != "CLOSED"]
        blockers.append(f"待关闭 Gap: {', '.join(pending)}")
    if not dq_ok:
        blockers.append(f"数据质量 {dq_score} 低于 70")

    return {
        "merchant_code": code,
        "merchant_name": target["merchant_name"],
        "focus": target["focus"],
        "final_verdict": final_verdict,
        "score_vs_target": {
            "current": total_score,
            "target": target_score,
            "grade": grade,
            "target_grade": target["target_grade"],
            "achieved": score_ok,
        },
        "data_quality": {
            "score": dq_score,
            "threshold": 70,
            "passed": dq_ok,
        },
        "gap_closure": {
            "closed": gap_closed,
            "total": gap_total,
            "rate_pct": round(gap_closed / gap_total * 100, 1),
            "all_closed": gaps_ok,
            "items": gaps,
        },
        "key_metrics": target["key_metrics"],
        "blockers": blockers,
        "manual_approval": approval,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/go-live-review")
async def list_go_live_reviews():
    """三商户 GO-TO-LIVE 最终评审汇总"""
    tasks = [asyncio.gather(_fetch_scorecard(c), _fetch_data_quality(c)) for c in ("czyz", "zqx", "sgc")]
    results_raw = await asyncio.gather(*tasks)

    reviews = []
    for code, (sc, dq) in zip(("czyz", "zqx", "sgc"), results_raw):
        reviews.append(_build_review(code, sc, dq))

    go_count = sum(1 for r in reviews if r["final_verdict"].startswith("GO"))
    all_go = go_count == 3

    return {
        "ok": True,
        "data": {
            "reviews": reviews,
            "summary": {
                "total": 3,
                "go": go_count,
                "no_go": 3 - go_count,
                "all_go_live_ready": all_go,
                "recommendation": "可以启动首批客户上线" if all_go else "部分商户仍有阻碍项，需解决后再评审",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    }


@router.get("/go-live-review/{merchant_code}")
async def get_go_live_review(merchant_code: str):
    """单商户 GO-TO-LIVE 评审详情"""
    if merchant_code not in _TARGETS:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": f"Unknown merchant: {merchant_code}"}}

    sc, dq = await asyncio.gather(
        _fetch_scorecard(merchant_code),
        _fetch_data_quality(merchant_code),
    )

    # 尝试从 DB 读取批准记录
    db_approval = await _fetch_db_approval(merchant_code)
    if db_approval and merchant_code not in _approvals:
        _approvals[merchant_code] = db_approval

    return {"ok": True, "data": _build_review(merchant_code, sc, dq)}


@router.post("/go-live-review/{merchant_code}/approve")
async def approve_go_live(
    merchant_code: str,
    body: dict[str, Any] = Body(
        ...,
        example={"approver": "未了已", "notes": "现场评审通过，sgc宴会数据需上线后持续补充"},
    ),
    x_operator: str | None = Header(default=None, alias="X-Operator"),
):
    """手动批准上线（适用于评分略低但现场演示通过的情况）。
    需在请求头中提供 X-Operator，且必须在允许操作员名单中。"""
    if merchant_code not in _TARGETS:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": f"Unknown merchant: {merchant_code}"}}

    # 操作员鉴权：必须提供 X-Operator header 且在允许名单中
    operator = (x_operator or "").strip()
    if not operator or operator not in _ALLOWED_APPROVERS:
        raise HTTPException(
            status_code=403,
            detail=f"无权限执行批准操作。请提供有效的 X-Operator header（允许: {', '.join(sorted(_ALLOWED_APPROVERS))}）",
        )

    approver = body.get("approver", "")
    notes = body.get("notes", "")
    if not approver:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "approver 不能为空"}}

    record = {
        "approver": approver,
        "notes": notes,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    _approvals[merchant_code] = record

    # 尝试持久化到 DB（表不存在时跳过，不阻塞流程）
    try:
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO go_live_approvals (merchant_code, approver, notes, approved_at) "
                    "VALUES (:code, :approver, :notes, NOW()) "
                    "ON CONFLICT (merchant_code) DO UPDATE "
                    "SET approver=EXCLUDED.approver, notes=EXCLUDED.notes, approved_at=NOW()"
                ),
                {"code": merchant_code, "approver": approver, "notes": notes},
            )
            await session.commit()
    except SQLAlchemyError as exc:
        logger.warning("go_live_approval_persist_failed", merchant=merchant_code, error=str(exc))

    logger.info("go_live_approved", merchant=merchant_code, approver=approver)
    return {"ok": True, "data": {"merchant_code": merchant_code, "approval": record}}
