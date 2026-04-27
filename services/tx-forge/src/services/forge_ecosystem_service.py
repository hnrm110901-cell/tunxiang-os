"""生态健康仪表盘 — 8大飞轮指标 (v3.0)"""

from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

log = structlog.get_logger(__name__)

# 飞轮指标权重（加总 = 1.0）
_METRIC_WEIGHTS = {
    "isv_active_rate": 0.15,
    "product_quality_score": 0.15,
    "install_density": 0.10,
    "outcome_conversion_rate": 0.15,
    "token_efficiency": 0.15,
    "developer_nps": 0.10,
    "tthw_minutes": 0.10,
    "ecosystem_gmv_fen": 0.10,
}


class ForgeEcosystemService:
    """生态健康仪表盘 — 8大飞轮指标"""

    # ── 计算指标 ─────────────────────────────────────────────
    async def compute_metrics(
        self, db: AsyncSession, *, metric_date: date | None = None
    ) -> dict:
        if metric_date is None:
            metric_date = date.today()

        # 1. ISV活跃率: 30天内有活动的开发者 / 总开发者
        isv_row = await db.execute(
            text("""
                SELECT
                    count(*) AS total_devs,
                    count(*) FILTER (WHERE updated_at >= :d::date - INTERVAL '30 days') AS active_devs
                FROM forge_developers
                WHERE is_deleted = false
            """),
            {"d": str(metric_date)},
        )
        isv = isv_row.mappings().one()
        total_devs = isv["total_devs"] or 0
        isv_active_rate = round(isv["active_devs"] / total_devs * 100, 1) if total_devs > 0 else 0.0

        # 2. 产品质量分: AVG(rating) * (1 - uninstall_rate)
        quality_row = await db.execute(
            text("""
                SELECT
                    COALESCE(AVG(a.rating), 0) AS avg_rating,
                    COALESCE(SUM(a.install_count), 0) AS total_installs,
                    COALESCE(
                        (SELECT count(*) FROM forge_installations
                         WHERE status = 'uninstalled' AND is_deleted = false), 0
                    ) AS uninstalled_count
                FROM forge_apps a
                WHERE a.is_deleted = false AND a.status = 'published'
            """),
        )
        q = quality_row.mappings().one()
        avg_rating = float(q["avg_rating"])
        total_installs = int(q["total_installs"])
        uninstalled = int(q["uninstalled_count"])
        uninstall_rate = uninstalled / total_installs if total_installs > 0 else 0.0
        product_quality_score = round(avg_rating * (1 - uninstall_rate), 2)

        # 3. 安装密度: active_installs / active_stores
        density_row = await db.execute(
            text("""
                SELECT
                    (SELECT count(*) FROM forge_installations
                     WHERE status = 'active' AND is_deleted = false) AS active_installs,
                    GREATEST(
                        (SELECT count(*) FROM forge_installations
                         WHERE status = 'active' AND is_deleted = false), 1
                    ) AS active_stores
            """),
        )
        d = density_row.mappings().one()
        install_density = round(int(d["active_installs"]) / int(d["active_stores"]), 2)

        # 4. 效果转化率: outcome_events / agent_decisions
        outcome_row = await db.execute(
            text("""
                SELECT
                    (SELECT count(*) FROM forge_outcome_events
                     WHERE is_deleted = false
                       AND created_at >= :d::date - INTERVAL '30 days') AS outcome_events,
                    GREATEST(
                        (SELECT count(*) FROM agent_decision_logs
                         WHERE created_at >= :d::date - INTERVAL '30 days'), 1
                    ) AS agent_decisions
            """),
            {"d": str(metric_date)},
        )
        o = outcome_row.mappings().one()
        outcome_conversion_rate = round(
            int(o["outcome_events"]) / int(o["agent_decisions"]) * 100, 1
        )

        # 5. Token效率: outcomes / (total_tokens / 1000)
        token_row = await db.execute(
            text("""
                SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens
                FROM forge_token_meters
                WHERE is_deleted = false
                  AND period_type = 'daily'
                  AND period_key >= to_char(:d::date - INTERVAL '30 days', 'YYYY-MM-DD')
            """),
            {"d": str(metric_date)},
        )
        total_tokens_k = int(token_row.scalar() or 0) / 1000.0
        outcome_events = int(o["outcome_events"])
        token_efficiency = round(outcome_events / total_tokens_k, 2) if total_tokens_k > 0 else 0.0

        # 6. 开发者NPS — 占位（调研系统未实现）
        developer_nps = 50

        # 7. TTHW（首次价值感知时间）— 占位（追踪系统未实现）
        tthw_minutes = 47

        # 8. 生态GMV: SUM(revenue_total_fen)
        gmv_row = await db.execute(
            text("""
                SELECT COALESCE(SUM(revenue_total_fen), 0) AS ecosystem_gmv_fen
                FROM forge_apps
                WHERE is_deleted = false AND status = 'published'
            """),
        )
        ecosystem_gmv_fen = int(gmv_row.scalar() or 0)

        # 计算综合分数（各指标归一化后加权）
        # 归一化: 各指标映射到 0-100 区间
        normalized = {
            "isv_active_rate": min(isv_active_rate, 100),
            "product_quality_score": min(product_quality_score * 20, 100),  # rating 0-5 → 0-100
            "install_density": min(install_density * 10, 100),  # 10+ 满分
            "outcome_conversion_rate": min(outcome_conversion_rate, 100),
            "token_efficiency": min(token_efficiency * 10, 100),  # 10+ 满分
            "developer_nps": min(max(developer_nps, 0), 100),
            "tthw_minutes": max(100 - tthw_minutes, 0),  # 越低越好
            "ecosystem_gmv_fen": min(ecosystem_gmv_fen / 100000, 100),  # 10万分满分
        }
        composite_score = round(
            sum(normalized[k] * _METRIC_WEIGHTS[k] for k in _METRIC_WEIGHTS), 1
        )

        metrics = {
            "metric_date": str(metric_date),
            "isv_active_rate": isv_active_rate,
            "product_quality_score": product_quality_score,
            "install_density": install_density,
            "outcome_conversion_rate": outcome_conversion_rate,
            "token_efficiency": token_efficiency,
            "developer_nps": developer_nps,
            "tthw_minutes": tthw_minutes,
            "ecosystem_gmv_fen": ecosystem_gmv_fen,
            "composite_score": composite_score,
        }

        # UPSERT
        await db.execute(
            text("""
                INSERT INTO forge_ecosystem_metrics
                    (id, tenant_id, metric_date,
                     isv_active_rate, product_quality_score, install_density,
                     outcome_conversion_rate, token_efficiency,
                     developer_nps, tthw_minutes, ecosystem_gmv_fen,
                     composite_score)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid, :metric_date,
                     :isv_active_rate, :product_quality_score, :install_density,
                     :outcome_conversion_rate, :token_efficiency,
                     :developer_nps, :tthw_minutes, :ecosystem_gmv_fen,
                     :composite_score)
                ON CONFLICT (tenant_id, metric_date)
                DO UPDATE SET
                     isv_active_rate = EXCLUDED.isv_active_rate,
                     product_quality_score = EXCLUDED.product_quality_score,
                     install_density = EXCLUDED.install_density,
                     outcome_conversion_rate = EXCLUDED.outcome_conversion_rate,
                     token_efficiency = EXCLUDED.token_efficiency,
                     developer_nps = EXCLUDED.developer_nps,
                     tthw_minutes = EXCLUDED.tthw_minutes,
                     ecosystem_gmv_fen = EXCLUDED.ecosystem_gmv_fen,
                     composite_score = EXCLUDED.composite_score,
                     updated_at = NOW()
            """),
            metrics,
        )

        log.info("ecosystem.metrics_computed", date=str(metric_date), composite=composite_score)
        return metrics

    # ── 历史指标查询 ─────────────────────────────────────────
    async def get_metrics(self, db: AsyncSession, *, days: int = 30) -> list[dict]:
        rows = await db.execute(
            text("""
                SELECT metric_date, isv_active_rate, product_quality_score,
                       install_density, outcome_conversion_rate, token_efficiency,
                       developer_nps, tthw_minutes, ecosystem_gmv_fen,
                       composite_score, created_at
                FROM forge_ecosystem_metrics
                WHERE is_deleted = false
                ORDER BY metric_date DESC
                LIMIT :days
            """),
            {"days": days},
        )
        return [dict(r) for r in rows.mappings().all()]

    # ── 最新指标 ─────────────────────────────────────────────
    async def get_latest(self, db: AsyncSession) -> dict:
        result = await db.execute(
            text("""
                SELECT metric_date, isv_active_rate, product_quality_score,
                       install_density, outcome_conversion_rate, token_efficiency,
                       developer_nps, tthw_minutes, ecosystem_gmv_fen,
                       composite_score, created_at
                FROM forge_ecosystem_metrics
                WHERE is_deleted = false
                ORDER BY metric_date DESC
                LIMIT 1
            """),
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="暂无生态指标数据，请先执行 compute_metrics")
        return dict(row)

    # ── 飞轮趋势对比 ─────────────────────────────────────────
    async def get_flywheel_status(self, db: AsyncSession) -> dict:
        # 最新
        latest_row = await db.execute(
            text("""
                SELECT metric_date, isv_active_rate, product_quality_score,
                       install_density, outcome_conversion_rate, token_efficiency,
                       developer_nps, tthw_minutes, ecosystem_gmv_fen,
                       composite_score
                FROM forge_ecosystem_metrics
                WHERE is_deleted = false
                ORDER BY metric_date DESC
                LIMIT 1
            """),
        )
        current = latest_row.mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="暂无生态指标数据")
        current = dict(current)

        # 30天前
        prev_row = await db.execute(
            text("""
                SELECT metric_date, isv_active_rate, product_quality_score,
                       install_density, outcome_conversion_rate, token_efficiency,
                       developer_nps, tthw_minutes, ecosystem_gmv_fen,
                       composite_score
                FROM forge_ecosystem_metrics
                WHERE is_deleted = false
                  AND metric_date <= (:d::date - INTERVAL '30 days')
                ORDER BY metric_date DESC
                LIMIT 1
            """),
            {"d": str(current["metric_date"])},
        )
        previous = prev_row.mappings().first()
        previous = dict(previous) if previous else None

        # 计算趋势
        trend_metrics = [
            "isv_active_rate", "product_quality_score", "install_density",
            "outcome_conversion_rate", "token_efficiency", "developer_nps",
            "tthw_minutes", "ecosystem_gmv_fen", "composite_score",
        ]
        trends: dict = {}
        if previous:
            for m in trend_metrics:
                cur_val = float(current.get(m, 0))
                prev_val = float(previous.get(m, 0))
                delta = cur_val - prev_val
                pct = round(delta / prev_val * 100, 1) if prev_val != 0 else 0.0
                direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
                # tthw_minutes 越低越好，方向反转
                if m == "tthw_minutes":
                    direction = "up" if delta < 0 else ("down" if delta > 0 else "flat")
                trends[m] = {"delta": round(delta, 2), "pct": pct, "direction": direction}
        else:
            for m in trend_metrics:
                trends[m] = {"delta": 0, "pct": 0, "direction": "flat"}

        return {
            "current": current,
            "previous": previous,
            "trends": trends,
        }
