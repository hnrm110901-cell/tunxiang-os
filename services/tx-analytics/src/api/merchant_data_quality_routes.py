"""商户数据质量验收 API 路由

用途：上线前验证各商户数据完整性，对应差距 A-01/A-02 闭环。

端点：
  GET /api/v1/analytics/data-quality/{merchant_code}  — 单商户完整质量报告
  GET /api/v1/analytics/data-quality                  — 三商户汇总概览

评分维度（加权，总分100）：
  门店数据完整率      20%  — stores ≥1行，store_name/address/seats 非空
  菜品数据完整率      20%  — dishes ≥10行，name/price/category 非空
  会员数据完整率      15%  — members ≥5行
  历史订单数据        15%  — orders 近90天 ≥20条
  KPI权重已配置       10%  — merchant_kpi_weight_configs 有记录
  桌台数据完整率      10%  — tables ≥5行
  主键一致性          10%  — orders.store_id 全部在 stores 中
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["data-quality"])

# 演示商户代码 → 租户 ID 映射（非 UUID 格式，演示环境专用）
_DEMO_TENANTS: dict[str, str] = {
    "czyz": "czyz-demo-tenant",
    "zqx": "zqx-demo-tenant",
    "sgc": "sgc-demo-tenant",
}

# 评分等级阈值
_GRADE_TABLE = [
    (95, "A+"),
    (90, "A"),
    (85, "B+"),
    (80, "B"),
    (70, "C+"),
    (60, "C"),
    (0,  "D"),
]


def _grade(score: float) -> str:
    for threshold, grade in _GRADE_TABLE:
        if score >= threshold:
            return grade
    return "D"


def _require_merchant(merchant_code: str, x_tenant_id: Optional[str]) -> str:
    """解析并返回 tenant_id。演示商户直接映射，否则使用 header。"""
    if merchant_code in _DEMO_TENANTS:
        return _DEMO_TENANTS[merchant_code]
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(
            status_code=400,
            detail=f"商户代码 {merchant_code!r} 不在演示列表中，请提供 X-Tenant-ID header",
        )
    return x_tenant_id.strip()


async def _run_quality_checks(tenant_id: str) -> list[dict]:
    """执行所有质量检查，返回检查结果列表。"""
    checks: list[dict] = []

    async with async_session_factory() as session:
        # 设置租户上下文（兼容非 UUID 演示 tenant_id）
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # ── 1. 门店数据完整率 (20%) ──────────────────────────────────────────
        try:
            row = await session.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (
                            WHERE store_name IS NOT NULL
                              AND address IS NOT NULL
                              AND seats IS NOT NULL
                        ) AS complete
                    FROM stores
                    WHERE tenant_id = :tid
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id},
            )
            r = row.fetchone()
            total, complete = (r.total or 0), (r.complete or 0)
            if total == 0:
                score = 0
                status = "❌"
                detail = "未找到门店数据"
            elif complete == total:
                score = 100
                status = "✅"
                detail = f"{total} 家门店，字段完整"
            else:
                score = int(complete / total * 100)
                status = "⚠️"
                detail = f"{total} 家门店，{complete} 家字段完整"
            checks.append({"check": "门店数据完整率", "weight": 0.20, "score": score,
                           "status": status, "detail": detail})
        except SQLAlchemyError as exc:
            logger.warning("data_quality_check_failed", check="stores", error=str(exc))
            checks.append({"check": "门店数据完整率", "weight": 0.20, "score": 0,
                           "status": "❌", "detail": f"查询失败: {exc}"})

        # ── 2. 菜品数据完整率 (20%) ──────────────────────────────────────────
        DISH_MIN = 10
        try:
            row = await session.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (
                            WHERE dish_name IS NOT NULL
                              AND price_fen IS NOT NULL
                              AND category_id IS NOT NULL
                        ) AS complete
                    FROM dishes
                    WHERE tenant_id = :tid
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id},
            )
            r = row.fetchone()
            total, complete = (r.total or 0), (r.complete or 0)
            if total == 0:
                score = 0
                status = "❌"
                detail = "未找到菜品数据"
            else:
                # 数量分 (最多 60 分)
                qty_score = min(total / DISH_MIN, 1.0) * 60
                # 完整率分 (最多 40 分)
                completeness_score = (complete / total * 40) if total > 0 else 0
                score = int(qty_score + completeness_score)
                if score >= 100:
                    status = "✅"
                elif score >= 60:
                    status = "⚠️"
                else:
                    status = "❌"
                detail = f"{total} 道菜品，{complete} 道字段完整"
            checks.append({"check": "菜品数据完整率", "weight": 0.20, "score": min(score, 100),
                           "status": status, "detail": detail})
        except SQLAlchemyError as exc:
            logger.warning("data_quality_check_failed", check="dishes", error=str(exc))
            checks.append({"check": "菜品数据完整率", "weight": 0.20, "score": 0,
                           "status": "❌", "detail": f"查询失败: {exc}"})

        # ── 3. 会员数据完整率 (15%) ──────────────────────────────────────────
        MEMBER_MIN = 5
        try:
            row = await session.execute(
                text("SELECT COUNT(*) AS total FROM members WHERE tenant_id = :tid AND is_deleted = FALSE"),
                {"tid": tenant_id},
            )
            total = row.scalar() or 0
            if total == 0:
                score = 0
                status = "❌"
                detail = "未找到会员数据"
            else:
                score = min(int(total / MEMBER_MIN * 100), 100)
                status = "✅" if total >= MEMBER_MIN else "⚠️"
                detail = f"{total} 位会员"
            checks.append({"check": "会员数据完整率", "weight": 0.15, "score": score,
                           "status": status, "detail": detail})
        except SQLAlchemyError as exc:
            logger.warning("data_quality_check_failed", check="members", error=str(exc))
            checks.append({"check": "会员数据完整率", "weight": 0.15, "score": 0,
                           "status": "❌", "detail": f"查询失败: {exc}"})

        # ── 4. 历史订单数据 (15%) ────────────────────────────────────────────
        ORDER_MIN = 20
        try:
            row = await session.execute(
                text("""
                    SELECT COUNT(*) AS total
                    FROM orders
                    WHERE tenant_id = :tid
                      AND is_deleted = FALSE
                      AND created_at >= NOW() - INTERVAL '90 days'
                """),
                {"tid": tenant_id},
            )
            total = row.scalar() or 0
            if total == 0:
                score = 0
                status = "❌"
                detail = "近90天无订单数据"
            else:
                score = min(int(total / ORDER_MIN * 100), 100)
                status = "✅" if total >= ORDER_MIN else "⚠️"
                detail = f"近90天 {total} 条订单"
            checks.append({"check": "历史订单数据", "weight": 0.15, "score": score,
                           "status": status, "detail": detail})
        except SQLAlchemyError as exc:
            logger.warning("data_quality_check_failed", check="orders", error=str(exc))
            checks.append({"check": "历史订单数据", "weight": 0.15, "score": 0,
                           "status": "❌", "detail": f"查询失败: {exc}"})

        # ── 5. KPI 权重已配置 (10%) ──────────────────────────────────────────
        try:
            row = await session.execute(
                text("""
                    SELECT COUNT(*) AS total
                    FROM merchant_kpi_weight_configs
                    WHERE tenant_id = :tid
                """),
                {"tid": tenant_id},
            )
            total = row.scalar() or 0
            if total > 0:
                score = 100
                status = "✅"
                detail = "KPI 权重配置已就绪"
            else:
                score = 0
                status = "❌"
                detail = "未找到 KPI 权重配置"
            checks.append({"check": "KPI权重已配置", "weight": 0.10, "score": score,
                           "status": status, "detail": detail})
        except SQLAlchemyError as exc:
            logger.warning("data_quality_check_failed", check="kpi_weights", error=str(exc))
            checks.append({"check": "KPI权重已配置", "weight": 0.10, "score": 0,
                           "status": "⚠️", "detail": f"表不存在或查询失败: {exc}"})

        # ── 6. 桌台数据完整率 (10%) ──────────────────────────────────────────
        TABLE_MIN = 5
        try:
            row = await session.execute(
                text("SELECT COUNT(*) AS total FROM tables WHERE tenant_id = :tid AND is_deleted = FALSE"),
                {"tid": tenant_id},
            )
            total = row.scalar() or 0
            if total == 0:
                score = 0
                status = "❌"
                detail = "未找到桌台数据"
            else:
                score = min(int(total / TABLE_MIN * 100), 100)
                status = "✅" if total >= TABLE_MIN else "⚠️"
                detail = f"{total} 张桌台"
            checks.append({"check": "桌台数据完整率", "weight": 0.10, "score": score,
                           "status": status, "detail": detail})
        except SQLAlchemyError as exc:
            logger.warning("data_quality_check_failed", check="tables", error=str(exc))
            checks.append({"check": "桌台数据完整率", "weight": 0.10, "score": 0,
                           "status": "❌", "detail": f"查询失败: {exc}"})

        # ── 7. 主键一致性 (10%) ──────────────────────────────────────────────
        try:
            row = await session.execute(
                text("""
                    SELECT COUNT(*) AS orphan_count
                    FROM orders o
                    WHERE o.tenant_id = :tid
                      AND o.is_deleted = FALSE
                      AND NOT EXISTS (
                          SELECT 1 FROM stores s
                          WHERE s.id = o.store_id
                            AND s.tenant_id = :tid
                            AND s.is_deleted = FALSE
                      )
                """),
                {"tid": tenant_id},
            )
            orphans = row.scalar() or 0
            if orphans == 0:
                score = 100
                status = "✅"
                detail = "无孤立订单，主键一致性良好"
            else:
                score = 0
                status = "❌"
                detail = f"{orphans} 条订单的 store_id 在 stores 中不存在"
            checks.append({"check": "主键一致性", "weight": 0.10, "score": score,
                           "status": status, "detail": detail})
        except SQLAlchemyError as exc:
            logger.warning("data_quality_check_failed", check="pk_consistency", error=str(exc))
            checks.append({"check": "主键一致性", "weight": 0.10, "score": 0,
                           "status": "❌", "detail": f"查询失败: {exc}"})

    return checks


def _compute_report(merchant_code: str, tenant_id: str, checks: list[dict]) -> dict:
    """根据 checks 列表计算综合评分报告。"""
    total_score = sum(c["score"] * c["weight"] for c in checks)
    total_score = round(total_score, 1)

    gap_items: list[str] = []
    for c in checks:
        if c["score"] < 100:
            gap_items.append(f"{c['check']}: {c['detail']}")

    return {
        "merchant_code": merchant_code,
        "tenant_id": tenant_id,
        "total_score": total_score,
        "grade": _grade(total_score),
        "checks": checks,
        "gap_items": gap_items,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 1. 单商户完整质量报告 ─────────────────────────────────────────────────────

@router.get("/data-quality/{merchant_code}", summary="单商户数据质量报告")
async def get_merchant_data_quality(
    merchant_code: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """返回指定商户的数据质量评分报告（A-01/A-02 差距验收）。"""
    tenant_id = _require_merchant(merchant_code, x_tenant_id)

    try:
        checks = await _run_quality_checks(tenant_id)
    except SQLAlchemyError as exc:
        logger.error("data_quality_db_error", merchant_code=merchant_code, error=str(exc))
        raise HTTPException(status_code=503, detail=f"数据库查询失败: {exc}") from exc

    report = _compute_report(merchant_code, tenant_id, checks)
    return {"ok": True, "data": report}


# ── 2. 三商户汇总概览 ─────────────────────────────────────────────────────────

@router.get("/data-quality", summary="所有演示商户数据质量汇总")
async def get_all_merchants_data_quality() -> dict:
    """返回三个演示商户（czyz/zqx/sgc）的数据质量汇总。"""
    summary: list[dict] = []

    for code, tenant_id in _DEMO_TENANTS.items():
        try:
            checks = await _run_quality_checks(tenant_id)
        except SQLAlchemyError as exc:
            logger.warning("data_quality_summary_skip", merchant_code=code, error=str(exc))
            summary.append({
                "merchant_code": code,
                "total_score": 0.0,
                "grade": "D",
                "top_gap": f"数据库查询失败: {exc}",
            })
            continue

        report = _compute_report(code, tenant_id, checks)

        # 取得分最低的 gap 项作为 top_gap
        failing = [c for c in checks if c["score"] < 100]
        failing.sort(key=lambda c: c["score"])
        top_gap = (
            f"{failing[0]['check']}: {failing[0]['detail']}"
            if failing
            else "全部检查通过"
        )

        summary.append({
            "merchant_code": code,
            "total_score": report["total_score"],
            "grade": report["grade"],
            "top_gap": top_gap,
        })

    return {"ok": True, "data": summary}
