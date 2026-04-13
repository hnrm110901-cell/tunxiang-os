"""分商户经营目标配置 API 路由 — Gap B-03

AI 分析推荐将与每个商户的 KPI 目标基准进行对比，实现目标绑定。

端点：
  GET /api/v1/analytics/merchant-targets/{merchant_code}         — 获取商户目标
  PUT /api/v1/analytics/merchant-targets/{merchant_code}         — 更新商户目标
  GET /api/v1/analytics/merchant-targets/{merchant_code}/gap     — 实际 vs 目标差距分析
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["merchant-targets"])

# ── 内置默认目标（可通过 PUT 接口在内存中覆盖） ───────────────────────────────────
_DEFAULT_TARGETS: dict[str, dict] = {
    "czyz": {
        "merchant_name": "尝在一起",
        "focus": "翻台率优先",
        "targets": {
            "table_turnover_rate": 4.5,          # 次/天
            "avg_dish_time_minutes": 18,          # 分钟
            "seat_utilization_pct": 75,           # %
            "avg_ticket_fen": 8500,               # 分
            "member_repurchase_rate_pct": 35,     # %
            "monthly_revenue_growth_pct": 8,      # %
            "gross_margin_pct": 62,               # %
        },
    },
    "zqx": {
        "merchant_name": "最黔线",
        "focus": "客单+复购优先",
        "targets": {
            "table_turnover_rate": 2.8,
            "avg_dish_time_minutes": 25,
            "seat_utilization_pct": 65,
            "avg_ticket_fen": 18000,
            "member_repurchase_rate_pct": 55,
            "monthly_revenue_growth_pct": 12,
            "gross_margin_pct": 58,
        },
    },
    "sgc": {
        "merchant_name": "尚宫厨",
        "focus": "宴席+客单优先",
        "targets": {
            "table_turnover_rate": 1.5,
            "avg_dish_time_minutes": 35,
            "seat_utilization_pct": 60,
            "avg_ticket_fen": 45000,
            "member_repurchase_rate_pct": 30,
            "monthly_revenue_growth_pct": 15,
            "gross_margin_pct": 65,
            "banquet_deposit_rate_pct": 80,
        },
    },
}

# 运行时覆盖存储（PUT 接口写入这里，同时持久化到 DB）
_overrides: dict[str, dict] = {}


def _tenant_uuid_for_merchant(merchant_code: str) -> uuid.UUID:
    """将 merchant_code 映射到确定性 UUID（演示环境）。"""
    tenant_str = f"{merchant_code}-demo-tenant"
    return uuid.uuid5(uuid.NAMESPACE_DNS, tenant_str)


async def _load_overrides_from_db() -> None:
    """从 merchant_target_overrides 表加载持久化覆盖值到内存缓存。
    可在应用启动后手动调用，不在模块导入时自动执行。
    """
    for merchant_code in _DEFAULT_TARGETS:
        tenant_uuid = _tenant_uuid_for_merchant(merchant_code)
        try:
            async with async_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tenant_uuid)},
                )
                result = await session.execute(
                    text("""
                        SELECT target_key, target_value
                        FROM merchant_target_overrides
                        WHERE tenant_id = :tid AND merchant_code = :mc
                    """),
                    {"tid": str(tenant_uuid), "mc": merchant_code},
                )
                rows = result.fetchall()
                if rows:
                    base = copy.deepcopy(_DEFAULT_TARGETS[merchant_code])
                    for row in rows:
                        # _fen 字段保持整数，其余比率/指标用 float
                        val = row.target_value
                        base["targets"][row.target_key] = (
                            int(val) if row.target_key.endswith("_fen") else float(val)
                        )
                    _overrides[merchant_code] = base
                    logger.info(
                        "merchant_targets_loaded_from_db",
                        merchant_code=merchant_code,
                        keys_loaded=len(rows),
                    )
        except SQLAlchemyError as exc:
            logger.warning(
                "merchant_targets_load_db_failed",
                merchant_code=merchant_code,
                error=str(exc),
            )

# 演示商户 → 租户 ID 映射
_DEMO_TENANTS: dict[str, str] = {
    "czyz": "czyz-demo-tenant",
    "zqx": "zqx-demo-tenant",
    "sgc": "sgc-demo-tenant",
}


def _get_targets(merchant_code: str) -> dict:
    """返回商户目标，优先使用覆盖值，否则返回内置默认值的深拷贝。"""
    if merchant_code in _overrides:
        return _overrides[merchant_code]
    if merchant_code in _DEFAULT_TARGETS:
        return copy.deepcopy(_DEFAULT_TARGETS[merchant_code])
    raise HTTPException(
        status_code=404,
        detail=f"未找到商户 {merchant_code!r} 的目标配置，支持: czyz / zqx / sgc",
    )


def _require_tenant(merchant_code: str, x_tenant_id: Optional[str]) -> str:
    """解析 tenant_id：演示商户直接映射，否则使用 header。"""
    if merchant_code in _DEMO_TENANTS:
        return _DEMO_TENANTS[merchant_code]
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(
            status_code=400,
            detail=f"商户代码 {merchant_code!r} 不在演示列表中，请提供 X-Tenant-ID header",
        )
    return x_tenant_id.strip()


# ── KPI 中文标签 ─────────────────────────────────────────────────────────────────
_KPI_LABELS: dict[str, str] = {
    "table_turnover_rate": "翻台率（次/天）",
    "avg_dish_time_minutes": "平均出餐时间（分钟）",
    "seat_utilization_pct": "座位利用率（%）",
    "avg_ticket_fen": "客单价（分）",
    "member_repurchase_rate_pct": "会员复购率（%）",
    "monthly_revenue_growth_pct": "月营收增长率（%）",
    "gross_margin_pct": "毛利率（%）",
    "banquet_deposit_rate_pct": "宴席定金率（%）",
}

# 出餐时间越短越好（反向 KPI）
_LOWER_IS_BETTER = {"avg_dish_time_minutes"}


async def _fetch_actuals(tenant_id: str, kpi_keys: list[str]) -> dict[str, Optional[float]]:
    """从数据库查询近 30 天实际 KPI 值，查询失败返回 None（调用方负责 fallback）。"""
    actuals: dict[str, Optional[float]] = {k: None for k in kpi_keys}

    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 客单价（分）和订单数
        if "avg_ticket_fen" in kpi_keys or "table_turnover_rate" in kpi_keys:
            try:
                row = await session.execute(
                    text("""
                        SELECT
                            AVG(total_fen)      AS avg_ticket,
                            COUNT(*)            AS order_count
                        FROM orders
                        WHERE tenant_id = :tid
                          AND is_deleted = FALSE
                          AND created_at >= NOW() - INTERVAL '30 days'
                    """),
                    {"tid": tenant_id},
                )
                r = row.fetchone()
                if r and r.order_count and r.order_count > 0:
                    if "avg_ticket_fen" in kpi_keys:
                        actuals["avg_ticket_fen"] = float(r.avg_ticket or 0)
            except SQLAlchemyError as exc:
                logger.warning("merchant_targets_actuals_query_failed", kpi="avg_ticket_fen",
                               tenant_id=tenant_id, error=str(exc))

        # 翻台率：近 30 天订单数 / (桌台数 × 30)
        if "table_turnover_rate" in kpi_keys:
            try:
                row_orders = await session.execute(
                    text("""
                        SELECT COUNT(*) AS cnt
                        FROM orders
                        WHERE tenant_id = :tid
                          AND is_deleted = FALSE
                          AND created_at >= NOW() - INTERVAL '30 days'
                    """),
                    {"tid": tenant_id},
                )
                row_tables = await session.execute(
                    text("""
                        SELECT COUNT(*) AS cnt
                        FROM tables
                        WHERE tenant_id = :tid
                          AND is_deleted = FALSE
                    """),
                    {"tid": tenant_id},
                )
                order_cnt = row_orders.scalar() or 0
                table_cnt = row_tables.scalar() or 0
                if table_cnt > 0 and order_cnt > 0:
                    actuals["table_turnover_rate"] = round(order_cnt / (table_cnt * 30), 2)
            except SQLAlchemyError as exc:
                logger.warning("merchant_targets_actuals_query_failed", kpi="table_turnover_rate",
                               tenant_id=tenant_id, error=str(exc))

    return actuals


def _build_gap_item(kpi: str, target: float, actual: Optional[float]) -> dict:
    """计算单个 KPI 的差距并生成 AI 建议。"""
    if actual is None:
        # 无法获取实际值时使用占位值
        actual = round(target * 0.85, 2)
        data_note = "（实际值不可用，使用占位估算）"
    else:
        data_note = ""

    is_lower_better = kpi in _LOWER_IS_BETTER
    gap_pct = round((actual - target) / target * 100, 1) if target != 0 else 0.0

    # 对于越低越好的 KPI，gap_pct 符号含义相反
    if is_lower_better:
        effective_gap = -gap_pct  # 正数 = 超出目标（差）
    else:
        effective_gap = gap_pct   # 正数 = 超出目标（好）

    if effective_gap >= 5:
        status = "✅ 超出目标"
    elif effective_gap >= -5:
        status = "🟡 接近目标"
    else:
        status = "⚠️ 低于目标"

    label = _KPI_LABELS.get(kpi, kpi)
    ai_recommendation = _generate_recommendation(kpi, target, actual, effective_gap, data_note)

    return {
        "kpi": kpi,
        "label": label,
        "target": target,
        "actual": actual,
        "gap_pct": gap_pct,
        "status": status,
        "ai_recommendation": ai_recommendation,
    }


def _generate_recommendation(kpi: str, target: float, actual: float,
                              effective_gap: float, data_note: str) -> str:
    """根据 KPI 类型和差距生成 AI 建议文本。"""
    pct_str = f"{abs(effective_gap):.1f}%"
    suffix = data_note

    recommendations: dict[str, dict] = {
        "table_turnover_rate": {
            "bad": f"翻台率低于目标{pct_str}，建议：1) 优化出餐流程缩短用餐时长；2) 加强催台提醒；3) 检查出餐时间是否超标{suffix}",
            "good": f"翻台率超出目标{pct_str}，运营良好；注意避免赶客体验，关注顾客满意度{suffix}",
        },
        "avg_dish_time_minutes": {
            "bad": f"出餐时间超出目标{pct_str}，建议：1) 检查厨房备餐流程；2) 优化热门菜品备料；3) 高峰期前置备餐{suffix}",
            "good": f"出餐时间优于目标{pct_str}，效率良好；可酌情提升菜品精细度{suffix}",
        },
        "seat_utilization_pct": {
            "bad": f"座位利用率低于目标{pct_str}，建议：1) 加强预订转化率；2) 优化等位引导；3) 分析空位高峰时段{suffix}",
            "good": f"座位利用率超出目标{pct_str}，运营高效；关注服务质量，防止翻台过度{suffix}",
        },
        "avg_ticket_fen": {
            "bad": f"客单价低于目标{pct_str}，建议：1) 强化服务员推荐高毛利菜品；2) 设计套餐组合提升连带消费；3) 检查折扣使用频率{suffix}",
            "good": f"客单价超出目标{pct_str}，表现优秀；持续跟踪顾客满意度{suffix}",
        },
        "member_repurchase_rate_pct": {
            "bad": f"会员复购率低于目标{pct_str}，建议：1) 制定会员回流激励（储值赠送/生日礼）；2) 分析流失会员特征；3) 精准触达高价值会员{suffix}",
            "good": f"会员复购率超出目标{pct_str}，会员运营效果好；可进一步提升会员等级体系{suffix}",
        },
        "monthly_revenue_growth_pct": {
            "bad": f"月营收增长率低于目标{pct_str}，建议：1) 分析近期客流趋势；2) 检查渠道营销投入；3) 提升新客获取效率{suffix}",
            "good": f"月营收增长率超出目标{pct_str}，增长势头良好；关注成本端控制{suffix}",
        },
        "gross_margin_pct": {
            "bad": f"毛利率低于目标{pct_str}，建议：1) 审查食材采购成本；2) 优化菜品结构（减少低毛利菜品比例）；3) 检查折扣管控{suffix}",
            "good": f"毛利率超出目标{pct_str}，成本管控优秀{suffix}",
        },
        "banquet_deposit_rate_pct": {
            "bad": f"宴席定金率低于目标{pct_str}，建议：1) 加强宴席顾问跟进；2) 优化定金政策（分期/优惠）；3) 提升宴席套餐吸引力{suffix}",
            "good": f"宴席定金率超出目标{pct_str}，宴席转化率高；注意及时落实接待准备{suffix}",
        },
    }

    kpi_recs = recommendations.get(kpi)
    if not kpi_recs:
        direction = "良好" if effective_gap >= 0 else f"低于目标{pct_str}"
        return f"{_KPI_LABELS.get(kpi, kpi)} {direction}{suffix}"

    return kpi_recs["good"] if effective_gap >= 0 else kpi_recs["bad"]


# ── 1. 获取商户目标 ───────────────────────────────────────────────────────────────

@router.get("/merchant-targets/{merchant_code}", summary="获取商户 KPI 目标配置")
async def get_merchant_targets(
    merchant_code: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """返回指定商户的 KPI 目标配置（包含默认值或已覆盖值）。"""
    targets = _get_targets(merchant_code)
    return {
        "ok": True,
        "data": {
            "merchant_code": merchant_code,
            **targets,
            "source": "override" if merchant_code in _overrides else "default",
        },
    }


# ── 2. 更新商户目标 ───────────────────────────────────────────────────────────────

@router.put("/merchant-targets/{merchant_code}", summary="更新商户 KPI 目标配置")
async def update_merchant_targets(
    merchant_code: str,
    payload: dict,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """覆盖指定商户的 KPI 目标配置（运行时内存存储，重启后恢复默认值）。"""
    # 验证商户代码
    if merchant_code not in _DEFAULT_TARGETS:
        raise HTTPException(
            status_code=404,
            detail=f"未知商户代码 {merchant_code!r}，支持: czyz / zqx / sgc",
        )

    # 合并更新：保留默认值，覆盖传入字段
    base = copy.deepcopy(_DEFAULT_TARGETS[merchant_code])
    if "targets" in payload and isinstance(payload["targets"], dict):
        base["targets"].update(payload["targets"])
    if "focus" in payload:
        base["focus"] = str(payload["focus"])
    if "merchant_name" in payload:
        base["merchant_name"] = str(payload["merchant_name"])

    _overrides[merchant_code] = base

    # 持久化覆盖值到 DB（UPSERT），失败时仅记录警告，不阻断内存更新
    updated_targets: dict = payload.get("targets", {}) if isinstance(payload.get("targets"), dict) else {}
    if updated_targets:
        tenant_uuid = _tenant_uuid_for_merchant(merchant_code)
        operator_id: Optional[str] = payload.get("updated_by") if isinstance(payload.get("updated_by"), str) else None
        try:
            async with async_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tenant_uuid)},
                )
                for key, value in updated_targets.items():
                    await session.execute(
                        text("""
                            INSERT INTO merchant_target_overrides
                              (tenant_id, merchant_code, target_key, target_value, updated_by)
                            VALUES (:tid, :mc, :key, :val, :by)
                            ON CONFLICT (tenant_id, merchant_code, target_key)
                            DO UPDATE SET
                              target_value = EXCLUDED.target_value,
                              updated_at   = NOW(),
                              updated_by   = EXCLUDED.updated_by
                        """),
                        {
                            "tid": str(tenant_uuid),
                            "mc": merchant_code,
                            "key": str(key),
                            "val": float(value),
                            "by": operator_id,
                        },
                    )
                await session.commit()
                logger.info(
                    "merchant_targets_persisted_to_db",
                    merchant_code=merchant_code,
                    keys=list(updated_targets.keys()),
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "merchant_targets_db_upsert_failed",
                merchant_code=merchant_code,
                error=str(exc),
            )

    logger.info("merchant_targets_updated", merchant_code=merchant_code,
                updated_keys=list(payload.get("targets", {}).keys()))

    return {
        "ok": True,
        "data": {
            "merchant_code": merchant_code,
            "message": "目标配置已更新",
            **base,
        },
    }


# ── 3. 差距分析 ───────────────────────────────────────────────────────────────────

@router.get("/merchant-targets/{merchant_code}/gap", summary="实际 vs 目标差距分析")
async def get_merchant_target_gap(
    merchant_code: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """对比近 30 天实际值与 KPI 目标，返回差距分析和 AI 建议。"""
    config = _get_targets(merchant_code)
    tenant_id = _require_tenant(merchant_code, x_tenant_id)
    targets_dict: dict[str, float] = config["targets"]
    kpi_keys = list(targets_dict.keys())

    # 尝试从 DB 获取实际值
    try:
        actuals = await _fetch_actuals(tenant_id, kpi_keys)
    except SQLAlchemyError as exc:
        logger.warning("merchant_targets_gap_db_error", merchant_code=merchant_code, error=str(exc))
        actuals = {k: None for k in kpi_keys}

    # 构建差距列表
    gaps: list[dict] = []
    for kpi, target in targets_dict.items():
        actual = actuals.get(kpi)
        gaps.append(_build_gap_item(kpi, target, actual))

    # 计算综合差距分（0-100，越高越好）
    gap_scores: list[float] = []
    for g in gaps:
        effective_gap = -g["gap_pct"] if g["kpi"] in _LOWER_IS_BETTER else g["gap_pct"]
        # 归一化到 0-100：目标完成率，最高 120 分截断到 100
        completion = min((100 + effective_gap) / 100, 1.2) * 100
        gap_scores.append(min(max(completion, 0), 100))

    overall_gap_score = round(sum(gap_scores) / len(gap_scores), 1) if gap_scores else 0.0

    # 找出差距最大的 KPI（effective_gap 最负的）
    worst = min(
        gaps,
        key=lambda g: -(g["gap_pct"]) if g["kpi"] in _LOWER_IS_BETTER else g["gap_pct"],
        default=None,
    )
    priority_action = (
        f"重点提升{_KPI_LABELS.get(worst['kpi'], worst['kpi'])}（差距最大）"
        if worst and worst["status"] == "⚠️ 低于目标"
        else "各项 KPI 运营正常，保持现有策略"
    )

    return {
        "ok": True,
        "data": {
            "merchant_code": merchant_code,
            "merchant_name": config.get("merchant_name", ""),
            "focus": config.get("focus", ""),
            "gaps": gaps,
            "overall_gap_score": overall_gap_score,
            "priority_action": priority_action,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
        },
    }
