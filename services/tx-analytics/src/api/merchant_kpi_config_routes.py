"""商户 KPI 权重配置 API — 三商户差异化经营指标权重

背景：三商户（尝在一起/最黔线/尚宫厨）经营重点不同，KPI 权重应有所区别：
  - 尝在一起（czyz）：火锅快轻餐，重翻台率/出餐速度/客流量
  - 最黔线（zqx）：正餐，重客单价/会员复购/菜品毛利
  - 尚宫厨（sgc）：宴会/包厢高端正餐，重包厢占用率/客单/宴会定金

端点：
  GET  /api/v1/analytics/merchant-kpi/configs        — 获取当前商户 KPI 权重配置
  PUT  /api/v1/analytics/merchant-kpi/configs        — 更新商户 KPI 权重配置
  GET  /api/v1/analytics/merchant-kpi/score/{store_id} — 根据权重计算门店经营综合评分
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/analytics/merchant-kpi", tags=["merchant-kpi-config"])


# ─── 默认权重配置（三商户预置） ────────────────────────────────────────────────

DEFAULT_MERCHANT_KPI_WEIGHTS: dict[str, dict[str, float]] = {
    # 尝在一起 — 火锅快轻餐：翻台优先
    "czyz": {
        "revenue_growth": 0.20,
        "table_turnover": 0.20,  # 翻台率（高权重）
        "avg_ticket": 0.10,
        "margin_rate": 0.20,
        "member_repurchase": 0.10,
        "dish_time": 0.15,  # 出餐速度（高权重）
        "daily_settlement": 0.05,
    },
    # 最黔线 — 正餐：客单/会员优先
    "zqx": {
        "revenue_growth": 0.20,
        "table_turnover": 0.10,
        "avg_ticket": 0.20,  # 客单价（高权重）
        "margin_rate": 0.20,
        "member_repurchase": 0.20,  # 复购率（高权重）
        "dish_time": 0.05,
        "daily_settlement": 0.05,
    },
    # 尚宫厨 — 高端正餐/宴会：客单/包厢/宴会优先
    "sgc": {
        "revenue_growth": 0.15,
        "table_turnover": 0.05,
        "avg_ticket": 0.25,  # 客单价（最高权重）
        "margin_rate": 0.20,
        "member_repurchase": 0.15,
        "dish_time": 0.05,
        "banquet_deposit_rate": 0.15,  # 宴会定金比率（高权重）
        "daily_settlement": 0.00,
    },
    # 默认（其他商户）
    "default": {
        "revenue_growth": 0.20,
        "table_turnover": 0.15,
        "avg_ticket": 0.15,
        "margin_rate": 0.25,
        "member_repurchase": 0.15,
        "dish_time": 0.05,
        "daily_settlement": 0.05,
    },
}

KPI_DESCRIPTIONS: dict[str, str] = {
    "revenue_growth": "营收增长率（环比）",
    "table_turnover": "翻台率（高峰段）",
    "avg_ticket": "客单价",
    "margin_rate": "综合毛利率",
    "member_repurchase": "会员月度复购率",
    "dish_time": "出餐及时率",
    "daily_settlement": "日结合规率",
    "banquet_deposit_rate": "宴会定金回收率",
}


# ─── 依赖 ─────────────────────────────────────────────────────────────────────


async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _get_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class KpiWeightItem(BaseModel):
    kpi_key: str = Field(..., description="KPI 标识符，如 revenue_growth / margin_rate")
    weight: float = Field(..., ge=0.0, le=1.0, description="权重值 0.0-1.0，所有 KPI 权重之和应为 1.0")
    description: str | None = Field(None)


class MerchantKpiWeightUpdate(BaseModel):
    merchant_code: str = Field(..., description="商户代码：czyz / zqx / sgc 或自定义")
    weights: dict[str, float] = Field(..., description="KPI权重字典，值域 0.0-1.0，合计应为 1.0")
    notes: str | None = Field(None, max_length=200)


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.get("/configs", summary="获取商户 KPI 权重配置")
async def get_merchant_kpi_configs(
    merchant_code: str | None = None,
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    返回商户 KPI 权重配置。
    - merchant_code 为 None 时返回所有商户配置
    - 优先读取 DB 自定义配置（merchant_kpi_weight_configs 表），无则返回内置默认值
    """
    # 尝试读取 DB 自定义配置
    db_configs: dict[str, dict[str, Any]] = {}
    try:
        r = await db.execute(
            text("""
            SELECT merchant_code, weights, notes, updated_at
            FROM merchant_kpi_weight_configs
            WHERE tenant_id = :tid::uuid
              AND (:mc IS NULL OR merchant_code = :mc)
        """),
            {"tid": tenant_id, "mc": merchant_code},
        )
        for row in r.mappings().all():
            db_configs[row["merchant_code"]] = {
                "weights": row["weights"],
                "notes": row["notes"],
                "source": "custom",
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
    except SQLAlchemyError:
        # 表不存在时降级到内置配置
        pass

    # 合并内置默认值
    result = []
    codes = [merchant_code] if merchant_code else list(DEFAULT_MERCHANT_KPI_WEIGHTS.keys())
    for code in codes:
        if code in db_configs:
            entry = db_configs[code]
        elif code in DEFAULT_MERCHANT_KPI_WEIGHTS:
            entry = {
                "weights": DEFAULT_MERCHANT_KPI_WEIGHTS[code],
                "notes": None,
                "source": "default",
                "updated_at": None,
            }
        else:
            continue

        # 注入 KPI 描述
        weights_with_desc = [
            {
                "kpi_key": k,
                "weight": v,
                "description": KPI_DESCRIPTIONS.get(k, k),
            }
            for k, v in entry["weights"].items()
        ]
        result.append(
            {
                "merchant_code": code,
                "weights": weights_with_desc,
                "weight_sum": round(sum(entry["weights"].values()), 4),
                "notes": entry["notes"],
                "source": entry["source"],
                "updated_at": entry["updated_at"],
            }
        )

    return {"ok": True, "data": result}


@router.put("/configs", summary="更新商户 KPI 权重配置")
async def update_merchant_kpi_config(
    body: MerchantKpiWeightUpdate,
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    更新（或创建）指定商户的 KPI 权重配置。
    权重之和应为 1.0，否则返回 400。
    写入 merchant_kpi_weight_configs 表（幂等 UPSERT）。
    """
    import json

    from fastapi import HTTPException

    weight_sum = round(sum(body.weights.values()), 4)
    if abs(weight_sum - 1.0) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"KPI 权重之和须为 1.0，当前为 {weight_sum:.4f}",
        )

    now = datetime.now(timezone.utc)
    try:
        await db.execute(
            text("""
            INSERT INTO merchant_kpi_weight_configs
                (tenant_id, merchant_code, weights, notes, updated_at)
            VALUES
                (:tid::uuid, :mc, :weights::jsonb, :notes, :now)
            ON CONFLICT (tenant_id, merchant_code)
            DO UPDATE SET
                weights    = EXCLUDED.weights,
                notes      = EXCLUDED.notes,
                updated_at = EXCLUDED.updated_at
        """),
            {
                "tid": tenant_id,
                "mc": body.merchant_code,
                "weights": json.dumps(body.weights),
                "notes": body.notes,
                "now": now,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("merchant_kpi.update_failed", error=str(exc), merchant_code=body.merchant_code)
        raise HTTPException(status_code=500, detail="保存失败，请重试") from exc

    logger.info(
        "merchant_kpi.updated",
        merchant_code=body.merchant_code,
        tenant_id=tenant_id,
        weight_sum=weight_sum,
    )
    return {
        "ok": True,
        "data": {
            "merchant_code": body.merchant_code,
            "weights": body.weights,
            "weight_sum": weight_sum,
            "updated_at": now.isoformat(),
        },
    }


@router.get("/score/{store_id}", summary="根据商户 KPI 权重计算门店综合经营评分")
async def get_store_kpi_score(
    store_id: str,
    merchant_code: str | None = None,
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    根据商户 KPI 权重配置计算门店本月综合经营评分（0-100分）。
    merchant_code 不传则使用 default 权重。
    """
    from datetime import timezone as tz

    now_utc = datetime.now(tz.utc)
    year, month = now_utc.year, now_utc.month

    # 读取权重
    code = merchant_code or "default"
    weights = DEFAULT_MERCHANT_KPI_WEIGHTS.get(code, DEFAULT_MERCHANT_KPI_WEIGHTS["default"])
    try:
        r = await db.execute(
            text("""
            SELECT weights FROM merchant_kpi_weight_configs
            WHERE tenant_id = :tid::uuid AND merchant_code = :mc
        """),
            {"tid": tenant_id, "mc": code},
        )
        row = r.mappings().fetchone()
        if row:
            weights = row["weights"]
    except SQLAlchemyError:
        pass

    # 采集各项原始指标（简化版：直接查本月数据）
    from .monthly_brief_routes import _month_compliance_score, _month_member_metrics, _month_metrics

    this_m = await _month_metrics(db, tenant_id, year, month)
    member = await _month_member_metrics(db, tenant_id, year, month)
    compliance = await _month_compliance_score(db, tenant_id, year, month)

    # 原始分（0-100）
    raw_scores: dict[str, float] = {
        "revenue_growth": min(100, max(0, 75 + this_m.get("revenue_fen", 0) / 1_000_000)),  # 简化
        "table_turnover": 70.0,  # 需接翻台率数据，暂估
        "avg_ticket": min(100, this_m.get("avg_ticket_yuan", 0) / 2),
        "margin_rate": min(100, this_m.get("margin_rate", 0) * 1.5),
        "member_repurchase": min(100, member.get("repurchase_rate", 0) * 2.5),
        "dish_time": 75.0,  # 需接出餐时间数据，暂估
        "daily_settlement": min(
            100, (compliance.get("settled_days", 0) / max(1, this_m.get("business_days", 1))) * 100
        ),
        "banquet_deposit_rate": 70.0,  # 需接宴会数据，暂估
    }

    # 加权综合分
    weighted_score = 0.0
    score_detail: list[dict[str, Any]] = []
    for kpi_key, w in weights.items():
        raw = raw_scores.get(kpi_key, 70.0)
        contribution = raw * w
        weighted_score += contribution
        score_detail.append(
            {
                "kpi_key": kpi_key,
                "description": KPI_DESCRIPTIONS.get(kpi_key, kpi_key),
                "weight": w,
                "raw_score": round(raw, 1),
                "contribution": round(contribution, 2),
            }
        )

    final_score = round(weighted_score, 1)
    grade = "A" if final_score >= 85 else ("B" if final_score >= 70 else ("C" if final_score >= 55 else "D"))

    logger.info(
        "merchant_kpi.score_calculated",
        store_id=store_id,
        merchant_code=code,
        final_score=final_score,
        grade=grade,
    )

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "merchant_code": code,
            "period": f"{year}-{month:02d}",
            "final_score": final_score,
            "grade": grade,
            "score_detail": score_detail,
            "generated_at": now_utc.isoformat(),
        },
    }
