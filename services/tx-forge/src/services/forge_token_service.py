"""Forge Token 计量引擎 — LLM 成本透传

职责：
  1. record_token_usage()   — 记录 Token 消耗 + UPSERT 日/月用量
  2. get_usage()            — 查询指定周期用量
  3. get_usage_trend()      — 查询日用量趋势
  4. set_token_pricing()    — 设置 Token 单价
  5. get_token_pricing()    — 查询 Token 单价
  6. set_budget()           — 设置预算与告警阈值
  7. get_budget_alerts()    — 查询超预算告警
"""

from __future__ import annotations

from datetime import date, datetime

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import PRICING_MODELS

logger = structlog.get_logger(__name__)


class ForgeTokenService:
    """Token 计量引擎 — LLM 成本透传"""

    # ── 1. 记录 Token 用量 ──────────────────────────────────────
    async def record_token_usage(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        input_tokens: int,
        output_tokens: int,
        cost_fen: int = 0,
    ) -> dict:
        """UPSERT 日/月用量表，检查预算告警。"""
        total_tokens = input_tokens + output_tokens
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")

        # UPSERT 日粒度
        daily_result = await db.execute(
            text("""
                INSERT INTO forge_token_meters
                    (app_id, period_type, period_key,
                     input_tokens, output_tokens, total_tokens, cost_fen)
                VALUES
                    (:app_id, 'daily', :period_key,
                     :input_tokens, :output_tokens, :total_tokens, :cost_fen)
                ON CONFLICT (app_id, period_type, period_key)
                DO UPDATE SET
                    input_tokens  = forge_token_meters.input_tokens  + EXCLUDED.input_tokens,
                    output_tokens = forge_token_meters.output_tokens + EXCLUDED.output_tokens,
                    total_tokens  = forge_token_meters.total_tokens  + EXCLUDED.total_tokens,
                    cost_fen      = forge_token_meters.cost_fen      + EXCLUDED.cost_fen,
                    updated_at    = NOW()
                RETURNING app_id, period_type, period_key,
                          input_tokens, output_tokens, total_tokens,
                          cost_fen, budget_fen, alert_threshold, alert_sent
            """),
            {
                "app_id": app_id,
                "period_key": today,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost_fen": cost_fen,
            },
        )
        daily_row = dict(daily_result.mappings().one())

        # UPSERT 月粒度
        await db.execute(
            text("""
                INSERT INTO forge_token_meters
                    (app_id, period_type, period_key,
                     input_tokens, output_tokens, total_tokens, cost_fen)
                VALUES
                    (:app_id, 'monthly', :period_key,
                     :input_tokens, :output_tokens, :total_tokens, :cost_fen)
                ON CONFLICT (app_id, period_type, period_key)
                DO UPDATE SET
                    input_tokens  = forge_token_meters.input_tokens  + EXCLUDED.input_tokens,
                    output_tokens = forge_token_meters.output_tokens + EXCLUDED.output_tokens,
                    total_tokens  = forge_token_meters.total_tokens  + EXCLUDED.total_tokens,
                    cost_fen      = forge_token_meters.cost_fen      + EXCLUDED.cost_fen,
                    updated_at    = NOW()
            """),
            {
                "app_id": app_id,
                "period_key": month,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost_fen": cost_fen,
            },
        )

        # 检查预算告警
        budget_fen = daily_row.get("budget_fen") or 0
        threshold = daily_row.get("alert_threshold") or 80
        alert_sent = daily_row.get("alert_sent") or False

        usage_pct = round(
            (daily_row["cost_fen"] / budget_fen * 100), 2
        ) if budget_fen > 0 else 0.0

        if budget_fen > 0 and usage_pct >= threshold and not alert_sent:
            await db.execute(
                text("""
                    UPDATE forge_token_meters
                    SET alert_sent = true
                    WHERE app_id = :app_id
                      AND period_type = 'daily'
                      AND period_key = :period_key
                """),
                {"app_id": app_id, "period_key": today},
            )
            logger.warning(
                "token_budget_alert",
                app_id=app_id,
                usage_pct=usage_pct,
                budget_fen=budget_fen,
                cost_fen=daily_row["cost_fen"],
            )

        await db.commit()

        logger.info(
            "token_usage_recorded",
            app_id=app_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_fen=cost_fen,
        )

        return {
            "period": "daily",
            "period_key": today,
            "total_tokens": daily_row["total_tokens"],
            "cost_fen": daily_row["cost_fen"],
            "budget_fen": budget_fen,
            "usage_pct": usage_pct,
        }

    # ── 2. 查询用量 ────────────────────────────────────────────
    async def get_usage(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        period_type: str = "daily",
        period_key: str | None = None,
    ) -> dict:
        """查询指定周期的 Token 用量。"""
        if period_type not in ("daily", "monthly"):
            raise HTTPException(
                status_code=422,
                detail="period_type 必须为 daily 或 monthly",
            )

        if period_key is None:
            period_key = (
                date.today().isoformat()
                if period_type == "daily"
                else date.today().strftime("%Y-%m")
            )

        result = await db.execute(
            text("""
                SELECT app_id, period_type, period_key,
                       input_tokens, output_tokens, total_tokens,
                       cost_fen, budget_fen, alert_threshold, alert_sent,
                       updated_at
                FROM forge_token_meters
                WHERE app_id = :app_id
                  AND period_type = :period_type
                  AND period_key = :period_key
            """),
            {
                "app_id": app_id,
                "period_type": period_type,
                "period_key": period_key,
            },
        )
        row = result.mappings().first()
        if not row:
            return {
                "app_id": app_id,
                "period_type": period_type,
                "period_key": period_key,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_fen": 0,
                "budget_fen": 0,
                "usage_pct": 0.0,
            }

        row_dict = dict(row)
        budget = row_dict.get("budget_fen") or 0
        row_dict["usage_pct"] = round(
            (row_dict["cost_fen"] / budget * 100), 2
        ) if budget > 0 else 0.0
        return row_dict

    # ── 3. 日用量趋势 ──────────────────────────────────────────
    async def get_usage_trend(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        days: int = 30,
    ) -> list[dict]:
        """最近 N 天的日用量趋势。"""
        result = await db.execute(
            text("""
                SELECT period_key, input_tokens, output_tokens,
                       total_tokens, cost_fen
                FROM forge_token_meters
                WHERE app_id = :app_id
                  AND period_type = 'daily'
                  AND period_key >= (CURRENT_DATE - :days)::text
                ORDER BY period_key ASC
            """),
            {"app_id": app_id, "days": days},
        )
        return [dict(r) for r in result.mappings().all()]

    # ── 4. 设置 Token 单价 ─────────────────────────────────────
    async def set_token_pricing(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        input_price_per_1k_fen: int,
        output_price_per_1k_fen: int,
        markup_rate: float = 0.0,
    ) -> dict:
        """UPSERT Token 单价配置。"""
        result = await db.execute(
            text("""
                INSERT INTO forge_token_prices
                    (app_id, input_price_per_1k_fen, output_price_per_1k_fen,
                     markup_rate)
                VALUES
                    (:app_id, :input_price, :output_price, :markup_rate)
                ON CONFLICT (app_id)
                DO UPDATE SET
                    input_price_per_1k_fen  = EXCLUDED.input_price_per_1k_fen,
                    output_price_per_1k_fen = EXCLUDED.output_price_per_1k_fen,
                    markup_rate             = EXCLUDED.markup_rate,
                    updated_at              = NOW()
                RETURNING app_id, input_price_per_1k_fen, output_price_per_1k_fen,
                          markup_rate, updated_at
            """),
            {
                "app_id": app_id,
                "input_price": input_price_per_1k_fen,
                "output_price": output_price_per_1k_fen,
                "markup_rate": markup_rate,
            },
        )
        row = dict(result.mappings().one())
        await db.commit()

        logger.info(
            "token_pricing_set",
            app_id=app_id,
            input_price_per_1k_fen=input_price_per_1k_fen,
            output_price_per_1k_fen=output_price_per_1k_fen,
            markup_rate=markup_rate,
        )
        return row

    # ── 5. 查询 Token 单价 ─────────────────────────────────────
    async def get_token_pricing(
        self,
        db: AsyncSession,
        app_id: str,
    ) -> dict:
        """查询应用的 Token 单价配置。"""
        result = await db.execute(
            text("""
                SELECT app_id, input_price_per_1k_fen, output_price_per_1k_fen,
                       markup_rate, updated_at
                FROM forge_token_prices
                WHERE app_id = :app_id
            """),
            {"app_id": app_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Token 定价不存在: {app_id}",
            )
        return dict(row)

    # ── 6. 设置预算 ────────────────────────────────────────────
    async def set_budget(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        period_type: str,
        budget_fen: int,
        alert_threshold: int = 80,
    ) -> dict:
        """设置当前周期的预算和告警阈值。"""
        if period_type not in ("daily", "monthly"):
            raise HTTPException(
                status_code=422,
                detail="period_type 必须为 daily 或 monthly",
            )

        period_key = (
            date.today().isoformat()
            if period_type == "daily"
            else date.today().strftime("%Y-%m")
        )

        result = await db.execute(
            text("""
                INSERT INTO forge_token_meters
                    (app_id, period_type, period_key, budget_fen, alert_threshold)
                VALUES
                    (:app_id, :period_type, :period_key, :budget_fen, :alert_threshold)
                ON CONFLICT (app_id, period_type, period_key)
                DO UPDATE SET
                    budget_fen      = EXCLUDED.budget_fen,
                    alert_threshold = EXCLUDED.alert_threshold,
                    alert_sent      = false,
                    updated_at      = NOW()
                RETURNING app_id, period_type, period_key,
                          budget_fen, alert_threshold, cost_fen, total_tokens
            """),
            {
                "app_id": app_id,
                "period_type": period_type,
                "period_key": period_key,
                "budget_fen": budget_fen,
                "alert_threshold": alert_threshold,
            },
        )
        row = dict(result.mappings().one())
        await db.commit()

        logger.info(
            "token_budget_set",
            app_id=app_id,
            period_type=period_type,
            budget_fen=budget_fen,
            alert_threshold=alert_threshold,
        )
        return row

    # ── 7. 查询超预算告警 ──────────────────────────────────────
    async def get_budget_alerts(
        self,
        db: AsyncSession,
    ) -> list[dict]:
        """查询所有超预算且未发送告警的应用。"""
        result = await db.execute(
            text("""
                SELECT app_id, period_type, period_key,
                       total_tokens, cost_fen, budget_fen, alert_threshold
                FROM forge_token_meters
                WHERE budget_fen > 0
                  AND alert_sent = false
                  AND cost_fen >= budget_fen * alert_threshold / 100
                ORDER BY cost_fen DESC
            """),
        )
        rows = [dict(r) for r in result.mappings().all()]
        for row in rows:
            row["usage_pct"] = round(
                (row["cost_fen"] / row["budget_fen"] * 100), 2
            ) if row["budget_fen"] > 0 else 0.0
        return rows
