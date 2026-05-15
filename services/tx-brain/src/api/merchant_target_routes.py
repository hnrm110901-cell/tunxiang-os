"""tx-brain 商户目标分析路由 — Gap B-03

让 AI Agent 在决策时能够引用商户 KPI 目标配置和差距分析。
配置数据源在 shared/merchant_targets/__init__.py（单数据源）。

端点：
  GET  /api/v1/brain/merchant-targets/{merchant_code}       — 获取商户目标(含DB覆盖)
  GET  /api/v1/brain/merchant-targets/{merchant_code}/gap   — 实际 vs 目标差距分析
  POST /api/v1/brain/merchant-targets/analyze               — AI 综合分析
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.merchant_targets import DEFAULT_TARGETS, KPI_LABELS, LOWER_IS_BETTER
from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/brain", tags=["brain"])

# 商户目标配置来自 shared/merchant_targets（单数据源，避免漂移）
# 见 shared/merchant_targets/__init__.py


def _tenant_uuid(merchant_code: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"{merchant_code}-demo-tenant")


def _get_targets(merchant_code: str) -> dict:
    if merchant_code not in DEFAULT_TARGETS:
        raise HTTPException(status_code=404, detail=f"未知商户代码 {merchant_code!r}")
    return copy.deepcopy(DEFAULT_TARGETS[merchant_code])


async def _load_db_overrides_for(merchant_code: str, base: dict) -> dict:
    """从 merchant_target_overrides 加载 DB 覆盖值并合并到 base。"""
    tid = str(_tenant_uuid(merchant_code))
    try:
        async with async_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": tid},
            )
            result = await session.execute(
                text("""
                    SELECT target_key, target_value
                    FROM merchant_target_overrides
                    WHERE tenant_id = :tid AND merchant_code = :mc
                """),
                {"tid": tid, "mc": merchant_code},
            )
            for row in result.fetchall():
                val = row.target_value
                base["targets"][row.target_key] = int(val) if row.target_key.endswith("_fen") else float(val)
    except SQLAlchemyError as exc:
        logger.warning("brain_merchant_targets_load_failed", merchant_code=merchant_code, error=str(exc))
    return base


async def _fetch_actuals(tenant_id: str, kpi_keys: list[str]) -> dict[str, Optional[float]]:
    actuals: dict[str, Optional[float]] = dict.fromkeys(kpi_keys)
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        if "avg_ticket_fen" in kpi_keys:
            try:
                row = await session.execute(
                    text("""
                        SELECT AVG(total_fen) AS avg_ticket
                        FROM orders
                        WHERE tenant_id = :tid AND is_deleted = FALSE
                          AND created_at >= NOW() - (:days * INTERVAL '1 day')
                    """),
                    {"tid": tenant_id, "days": 30},
                )
                r = row.fetchone()
                if r and r.avg_ticket:
                    # _fen 字段必须 int（CLAUDE.md §10/§15）；round 防 Decimal 截断
                    actuals["avg_ticket_fen"] = int(round(r.avg_ticket))
            except SQLAlchemyError:
                logger.warning("merchant_target.avg_ticket_db_failed", tenant_id=str(tenant_id), exc_info=True)
        if "table_turnover_rate" in kpi_keys:
            try:
                r1 = await session.execute(
                    text(
                        "SELECT COUNT(*) AS cnt FROM orders WHERE tenant_id = :tid AND is_deleted = FALSE AND created_at >= NOW() - (:days * INTERVAL '1 day')"
                    ),
                    {"tid": tenant_id, "days": 30},
                )
                r2 = await session.execute(
                    text("SELECT COUNT(*) AS cnt FROM tables WHERE tenant_id = :tid AND is_deleted = FALSE"),
                    {"tid": tenant_id},
                )
                o = r1.scalar() or 0
                t = r2.scalar() or 0
                if t > 0 and o > 0:
                    actuals["table_turnover_rate"] = round(o / (t * 30), 2)
            except SQLAlchemyError:
                logger.warning("merchant_target.turnover_rate_db_failed", tenant_id=str(tenant_id), exc_info=True)
    return actuals


def _gen_recommendation(kpi: str, target: float, actual: float, gap_pct: float, note: str = "") -> str:
    is_lower = kpi in LOWER_IS_BETTER
    eff = -gap_pct if is_lower else gap_pct
    pct = f"{abs(eff):.1f}%"
    label = KPI_LABELS.get(kpi, kpi)
    if eff >= 5:
        return f"{label} 超出目标{pct}，表现良好"
    if eff >= -5:
        return f"{label} 接近目标（{pct}偏差）"
    return f"{label} 低于目标{pct}，需关注改善"


# ── 1. 获取商户目标 ─────────────────────────────────────────────────────────────


@router.get("/merchant-targets/{merchant_code}")
async def get_merchant_targets(merchant_code: str) -> dict:
    """获取商户 KPI 目标（含 DB 覆盖值）."""
    config = _get_targets(merchant_code)
    merged = await _load_db_overrides_for(merchant_code, config)
    return {"ok": True, "data": {"merchant_code": merchant_code, **merged}}


# ── 2. 差距分析 ─────────────────────────────────────────────────────────────────


@router.get("/merchant-targets/{merchant_code}/gap")
async def get_merchant_target_gap(merchant_code: str) -> dict:
    """近 30 天实际值 vs KPI 目标差距分析。"""
    config = _get_targets(merchant_code)
    merged = await _load_db_overrides_for(merchant_code, config)
    tid = str(_tenant_uuid(merchant_code))
    targets: dict[str, float] = merged["targets"]

    try:
        actuals = await _fetch_actuals(tid, list(targets.keys()))
    except SQLAlchemyError as exc:
        logger.warning("brain_gap_db_error", merchant_code=merchant_code, error=str(exc))
        actuals = dict.fromkeys(targets.keys())

    gaps: list[dict] = []
    for kpi, target in targets.items():
        actual = actuals.get(kpi)
        if actual is None:
            actual = round(target * 0.85, 2)
        gap_pct = round((actual - target) / target * 100, 1) if target else 0.0
        gaps.append(
            {
                "kpi": kpi,
                "label": KPI_LABELS.get(kpi, kpi),
                "target": target,
                "actual": actual,
                "gap_pct": gap_pct,
                "recommendation": _gen_recommendation(kpi, target, actual, gap_pct),
            }
        )

    completion_scores = []
    for g in gaps:
        eff = -g["gap_pct"] if g["kpi"] in LOWER_IS_BETTER else g["gap_pct"]
        completion_scores.append(min(max((100 + eff) / 100, 0), 1) * 100)
    overall = round(sum(completion_scores) / len(completion_scores), 1) if completion_scores else 0.0

    return {
        "ok": True,
        "data": {
            "merchant_code": merchant_code,
            "merchant_name": merged.get("merchant_name", ""),
            "overall_gap_score": overall,
            "gaps": gaps,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ── 3. AI 综合分析 ──────────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    merchant_code: str


@router.post("/merchant-targets/analyze")
async def analyze_merchant_targets(payload: AnalyzeRequest) -> dict:
    """AI Agent 级综合分析：返回健康度、评分和优先改善建议。"""
    merchant_code = payload.merchant_code
    config = _get_targets(merchant_code)
    merged = await _load_db_overrides_for(merchant_code, config)
    tid = str(_tenant_uuid(merchant_code))

    try:
        actuals = await _fetch_actuals(tid, list(merged["targets"].keys()))
    except SQLAlchemyError as exc:
        logger.warning("brain_analyze_db_error", merchant_code=merchant_code, error=str(exc))
        actuals = dict.fromkeys(merged["targets"].keys())

    kpi_results: list[dict] = []
    worst_gap = -float("inf")
    worst_kpi = ""
    for kpi, target in merged["targets"].items():
        actual = actuals.get(kpi)
        if actual is None:
            actual = round(target * 0.85, 2)
        gap_pct = round((actual - target) / target * 100, 1) if target else 0.0
        eff = -gap_pct if kpi in LOWER_IS_BETTER else gap_pct
        if eff < worst_gap:
            worst_gap = eff
            worst_kpi = kpi
        kpi_results.append(
            {
                "kpi": kpi,
                "label": KPI_LABELS.get(kpi, kpi),
                "gap_pct": gap_pct,
                "status": "超出目标" if eff >= 5 else ("接近目标" if eff >= -5 else "低于目标"),
            }
        )

    completion = [
        min(max((100 + (-g["gap_pct"] if g["kpi"] in LOWER_IS_BETTER else g["gap_pct"])) / 100, 0), 1) * 100
        for g in kpi_results
    ]
    score = round(sum(completion) / len(completion), 1) if completion else 0.0
    health = "良好" if score >= 80 else ("一般" if score >= 60 else "需关注")

    priority = f"重点提升 {KPI_LABELS.get(worst_kpi, worst_kpi)}" if worst_kpi else "各项达标"

    return {
        "ok": True,
        "data": {
            "merchant_code": merchant_code,
            "merchant_name": merged.get("merchant_name", ""),
            "health": health,
            "score": score,
            "kpis": kpi_results,
            "priority_action": priority,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
        },
    }
