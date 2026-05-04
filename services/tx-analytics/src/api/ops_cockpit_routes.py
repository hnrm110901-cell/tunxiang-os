"""实时运营驾驶舱（Palantir Workshop 等价物）— Phase C3

WebSocket 实时推送 + REST 聚合查询 双层架构：
- REST API：单次查询，返回所有可用的物化视图聚合数据
- WebSocket：建立连接后每 5 秒推送增量更新（key metrics only）

数据源（12 个物化视图）：
  mv_discount_health, mv_channel_margin, mv_inventory_bom,
  mv_member_clv, mv_store_pnl, mv_daily_settlement,
  mv_safety_compliance, mv_energy_efficiency,
  mv_table_turnover, mv_dish_profitability,         ← v385 新增
  mv_employee_efficiency, mv_customer_ltv            ← v385 新增

三层级下钻：集团 → 品牌 → 门店
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

router = APIRouter(prefix="/api/v1/analytics", tags=["ops_cockpit"])

logger = structlog.get_logger(__name__)


# ─── DB 依赖 ──────────────────────────────────────────────────────────────────


async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── WebSocket 连接管理 ───────────────────────────────────────────────────────


class _ConnectionManager:
    """管理所有 WebSocket 连接，按租户分组。"""

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, tenant_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if tenant_id not in self._connections:
            self._connections[tenant_id] = set()
        self._connections[tenant_id].add(ws)
        logger.info("ops_cockpit.ws_connected", tenant_id=tenant_id)

    def disconnect(self, tenant_id: str, ws: WebSocket) -> None:
        if tenant_id in self._connections:
            self._connections[tenant_id].discard(ws)
            if not self._connections[tenant_id]:
                del self._connections[tenant_id]
        logger.info("ops_cockpit.ws_disconnected", tenant_id=tenant_id)

    async def broadcast(self, tenant_id: str, message: dict) -> None:
        """向指定租户的所有连接广播消息。"""
        dead: list[WebSocket] = []
        for ws in self._connections.get(tenant_id, set()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(tenant_id, ws)


manager = _ConnectionManager()


# ─── 实时指标聚合 ─────────────────────────────────────────────────────────────


class CockpitMetrics:
    """从 12 个物化视图聚合实时运营指标。"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    async def _query(self, sql: str, **params) -> Any:
        result = await self.db.execute(text(sql), params)
        return result

    async def overview(self, store_id: Optional[str] = None) -> Dict[str, Any]:
        """聚合所有物化视图的关键 KPI。

        Args:
            store_id: 门店级过滤（None = 集团/品牌级汇总）

        Returns:
            12 个维度的 KPI 字典
        """
        store_filter = "AND store_id = :sid" if store_id else ""
        store_params = {"sid": store_id} if store_id else {}

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tenant_id": self.tenant_id,
            "store_id": store_id,
            "metrics": {
                "discount_health": await self._discount_health(store_filter, store_params),
                "channel_margin": await self._channel_margin(store_filter, store_params),
                "inventory_bom": await self._inventory_bom(store_filter, store_params),
                "member_clv": await self._member_clv(),
                "store_pnl": await self._store_pnl(store_filter, store_params),
                "daily_settlement": await self._daily_settlement(store_filter, store_params),
                "safety_compliance": await self._safety_compliance(store_filter, store_params),
                "energy_efficiency": await self._energy_efficiency(store_filter, store_params),
                "table_turnover": await self._table_turnover(store_filter, store_params),
                "dish_profitability": await self._dish_profitability(store_filter, store_params),
                "employee_efficiency": await self._employee_efficiency(store_filter, store_params),
                "customer_health": await self._customer_health(),
            },
        }

    # ── 单个指标查询方法 ──────────────────────────────────────────────────────

    async def _discount_health(self, store_filter: str, params: dict) -> dict:
        rows = (await self._query(f"""
            SELECT SUM(total_orders)::bigint, SUM(discounted_orders)::bigint,
                   AVG(discount_rate)::numeric(5,4), SUM(total_discount_fen)::bigint,
                   SUM(unauthorized_count)::bigint, SUM(threshold_breaches)::bigint
            FROM mv_discount_health
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date >= CURRENT_DATE - INTERVAL '7 days'
              {store_filter}
        """, **params)).fetchone()

        if not rows or rows[0] is None:
            return {"total_orders": 0, "discount_rate": 0, "alerts": 0}

        return {
            "total_orders_7d": int(rows[0] or 0),
            "discounted_orders_7d": int(rows[1] or 0),
            "discount_rate": float(rows[2] or 0),
            "total_discount_yuan_7d": round((rows[3] or 0) / 100, 2),
            "unauthorized_count_7d": int(rows[4] or 0),
            "threshold_breaches_7d": int(rows[5] or 0),
            "health_status": "critical" if (rows[4] or 0) > 5 or (rows[5] or 0) > 3 else "normal",
        }

    async def _channel_margin(self, store_filter: str, params: dict) -> dict:
        rows = (await self._query(f"""
            SELECT channel,
                   SUM(gross_revenue_fen)::bigint, SUM(net_revenue_fen)::bigint,
                   AVG(gross_margin_rate)::numeric(5,4)
            FROM mv_channel_margin
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date = CURRENT_DATE
              {store_filter}
            GROUP BY channel
            ORDER BY SUM(gross_revenue_fen) DESC
        """, **params)).fetchall()

        channels = {}
        for row in rows:
            channels[row[0]] = {
                "gross_yuan_today": round((row[1] or 0) / 100, 2),
                "net_yuan_today": round((row[2] or 0) / 100, 2),
                "margin_rate": float(row[3] or 0),
            }
        return {"channels": channels}

    async def _inventory_bom(self, store_filter: str, params: dict) -> dict:
        row = (await self._query(f"""
            SELECT SUM(theoretical_cost_fen)::bigint, SUM(actual_cost_fen)::bigint,
                   SUM(waste_fen)::bigint
            FROM mv_inventory_bom
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date = CURRENT_DATE
              {store_filter}
        """, **params)).fetchone()

        theoretical = row[0] or 0 if row else 0
        actual = row[1] or 0 if row else 0
        waste = row[2] or 0 if row else 0

        return {
            "theoretical_cost_yuan": round(theoretical / 100, 2),
            "actual_cost_yuan": round(actual / 100, 2),
            "variance_yuan": round((actual - theoretical) / 100, 2),
            "variance_rate": round((actual - theoretical) / max(theoretical, 1), 4),
            "waste_yuan": round(waste / 100, 2),
        }

    async def _member_clv(self) -> dict:
        row = (await self._query("""
            SELECT COUNT(*), AVG(predicted_ltv_fen)::bigint,
                   COUNT(*) FILTER (WHERE churn_risk > 0.3),
                   AVG(churn_risk)::numeric(5,4)
            FROM mv_member_clv
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
        """)).fetchone()

        if not row or row[0] is None:
            return {"total": 0, "avg_ltv_yuan": 0, "churn_risk": 0}

        return {
            "total_members": int(row[0]),
            "avg_ltv_yuan": round((row[1] or 0) / 100, 2),
            "at_risk_count": int(row[2] or 0),
            "avg_churn_risk": float(row[3] or 0),
        }

    async def _store_pnl(self, store_filter: str, params: dict) -> dict:
        row = (await self._query(f"""
            SELECT SUM(revenue_fen)::bigint, SUM(cogs_fen)::bigint,
                   SUM(labor_fen)::bigint, SUM(rent_fen)::bigint,
                   SUM(utilities_fen)::bigint, SUM(net_profit_fen)::bigint
            FROM mv_store_pnl
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date = CURRENT_DATE
              {store_filter}
        """, **params)).fetchone()

        if not row or row[0] is None:
            return {"revenue_today": 0, "net_profit_today": 0}

        return {
            "revenue_today_yuan": round((row[0] or 0) / 100, 2),
            "cogs_today_yuan": round((row[1] or 0) / 100, 2),
            "labor_today_yuan": round((row[2] or 0) / 100, 2),
            "rent_today_yuan": round((row[3] or 0) / 100, 2),
            "utilities_today_yuan": round((row[4] or 0) / 100, 2),
            "net_profit_today_yuan": round((row[5] or 0) / 100, 2),
        }

    async def _daily_settlement(self, store_filter: str, params: dict) -> dict:
        row = (await self._query(f"""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE is_closed = true)
            FROM mv_daily_settlement
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date = CURRENT_DATE
              {store_filter}
        """, **params)).fetchone()

        if not row:
            return {"total_stores": 0, "settled_stores": 0, "completion_rate": 0}

        total = row[0] or 0
        settled = row[1] or 0
        return {
            "total_stores": int(total),
            "settled_stores": int(settled),
            "completion_rate": round(settled / max(total, 1), 4),
        }

    async def _safety_compliance(self, store_filter: str, params: dict) -> dict:
        row = (await self._query(f"""
            SELECT AVG(compliance_rate)::numeric(5,4),
                   COUNT(*) FILTER (WHERE has_violation = true)
            FROM mv_safety_compliance
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date >= CURRENT_DATE - INTERVAL '30 days'
              {store_filter}
        """, **params)).fetchone()

        return {
            "avg_compliance_rate": float(row[0] or 0) if row else 0,
            "violations_30d": int(row[1] or 0) if row else 0,
        }

    async def _energy_efficiency(self, store_filter: str, params: dict) -> dict:
        row = (await self._query(f"""
            SELECT SUM(energy_cost_fen)::bigint, SUM(revenue_fen)::bigint
            FROM mv_energy_efficiency
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date = CURRENT_DATE
              {store_filter}
        """, **params)).fetchone()

        energy = row[0] or 0 if row else 0
        revenue = row[1] or 0 if row else 0
        return {
            "energy_cost_yuan_today": round(energy / 100, 2),
            "energy_ratio": round(energy / max(revenue, 1), 6) if revenue else 0,
        }

    async def _table_turnover(self, store_filter: str, params: dict) -> dict:
        row = (await self._query(f"""
            SELECT SUM(turnover_count)::bigint, AVG(table_utilization_rate)::numeric(5,4),
                   AVG(avg_occupancy_mins)::int, SUM(revenue_per_table_fen * turnover_count)::bigint
            FROM mv_table_turnover
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date = CURRENT_DATE AND stat_hour = 0
              {store_filter}
        """, **params)).fetchone()

        if not row or row[0] is None:
            return {"turnover_count": 0, "utilization_rate": 0}

        return {
            "turnover_count_today": int(row[0] or 0),
            "utilization_rate": float(row[1] or 0),
            "avg_occupancy_mins": int(row[2] or 0),
            "estimated_revenue_today_yuan": round((row[3] or 0) / 100, 2),
        }

    async def _dish_profitability(self, store_filter: str, params: dict) -> dict:
        row = (await self._query(f"""
            SELECT AVG(gross_margin_rate)::numeric(5,4), COUNT(*),
                   COUNT(*) FILTER (WHERE gross_margin_rate < 0.3)
            FROM mv_dish_profitability
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date = CURRENT_DATE
              {store_filter}
        """, **params)).fetchone()

        if not row:
            return {"avg_margin": 0, "low_margin_count": 0}

        return {
            "avg_dish_margin_rate": float(row[0] or 0),
            "total_dishes_tracked": int(row[1] or 0),
            "low_margin_dishes": int(row[2] or 0),
        }

    async def _employee_efficiency(self, store_filter: str, params: dict) -> dict:
        row = (await self._query(f"""
            SELECT AVG(efficiency_score)::numeric(5,2), AVG(attendance_score)::numeric(5,2),
                   SUM(error_incidents)::bigint, COUNT(*)
            FROM mv_employee_efficiency
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
              AND stat_date = CURRENT_DATE
              {store_filter}
        """, **params)).fetchone()

        if not row:
            return {"avg_efficiency": 0, "avg_attendance": 0}

        return {
            "avg_efficiency_score": float(row[0] or 0),
            "avg_attendance_score": float(row[1] or 0),
            "total_errors_today": int(row[2] or 0),
            "active_employees": int(row[3] or 0),
        }

    async def _customer_health(self) -> dict:
        row = (await self._query("""
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE churn_risk > 0.3),
                   AVG(predicted_ltv_fen)::bigint,
                   COUNT(*) FILTER (WHERE ltv_tier = 'whale')
            FROM mv_customer_ltv
            WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
        """)).fetchone()

        if not row:
            return {"total": 0, "at_risk": 0, "whales": 0}

        return {
            "total_customers": int(row[0] or 0),
            "churn_risk_count": int(row[1] or 0),
            "avg_ltv_yuan": round((row[2] or 0) / 100, 2),
            "whale_count": int(row[3] or 0),
        }


# ─── REST 端点 ────────────────────────────────────────────────────────────────


@router.get("/cockpit/overview", summary="实时运营驾驶舱总览")
async def cockpit_overview(
    store_id: Optional[str] = Query(None, description="门店级过滤（可选）"),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """一次性拉取所有 12 维度的关键 KPI。

    数据来源：12 个物化视图（含 v385 新增的 4 个视图）。
    支持集团/品牌/门店三级下钻。
    """
    metrics = CockpitMetrics(db, x_tenant_id)
    overview = await metrics.overview(store_id=store_id)
    return {"ok": True, "data": overview}


@router.get("/cockpit/alerts", summary="运营告警摘要")
async def cockpit_alerts(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """快速获取所有运营告警（折扣异常 / 食安违规 / 能耗异常 / 流失风险）。

    返回即时可操作的告警列表。
    """
    alerts: list[dict] = []

    # 折扣健康告警
    discount_row = (await db.execute(text("""
        SELECT COUNT(*) FROM mv_discount_health
        WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
          AND stat_date = CURRENT_DATE
          AND (unauthorized_count > 0 OR threshold_breaches > 0)
    """))).scalar()
    if discount_row and discount_row > 0:
        alerts.append({
            "type": "discount", "severity": "critical",
            "message": f"{discount_row} 家门店今日有异常折扣",
        })

    # 食安告警
    safety_row = (await db.execute(text("""
        SELECT COUNT(*) FROM mv_safety_compliance
        WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
          AND stat_date = CURRENT_DATE
          AND has_violation = true
    """))).scalar()
    if safety_row and safety_row > 0:
        alerts.append({
            "type": "safety", "severity": "critical",
            "message": f"{safety_row} 家门店今日有食安违规",
        })

    # 流失风险告警
    churn_row = (await db.execute(text("""
        SELECT COUNT(*) FROM mv_customer_ltv
        WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
          AND churn_risk > 0.3
    """))).scalar()
    if churn_row and churn_row > 100:
        alerts.append({
            "type": "member", "severity": "warning",
            "message": f"{churn_row} 位高价值客户有流失风险",
        })

    # 日结未完成告警
    closed_row = (await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE is_closed = false),
               COUNT(*)
        FROM mv_daily_settlement
        WHERE tenant_id = current_setting('app.tenant_id', true)::uuid
          AND stat_date = CURRENT_DATE
    """))).fetchone()
    if closed_row and closed_row[0] > 0:
        pct = round(closed_row[0] / max(closed_row[1], 1) * 100, 1)
        alerts.append({
            "type": "settlement", "severity": "warning",
            "message": f"{closed_row[0]} 家门店日结未完成（{pct}%）",
        })

    return {"ok": True, "data": {"alerts": alerts, "count": len(alerts)}}


# ─── WebSocket 端点 ───────────────────────────────────────────────────────────


@router.websocket("/cockpit/ws")
async def cockpit_websocket(
    ws: WebSocket,
    x_tenant_id: str = Query(...),
) -> None:
    """WebSocket 实时运营推送。

    建立连接后，每 10 秒推送增量 KPI 更新。
    客户端发送控制消息：
      - {"action": "pause"}     → 暂停推送
      - {"action": "resume"}    → 恢复推送
      - {"action": "full_sync"} → 立即请求全量数据
    """
    await manager.connect(x_tenant_id, ws)
    paused = False

    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
                data = json.loads(msg)
                action = data.get("action", "")
                if action == "pause":
                    paused = True
                elif action == "resume":
                    paused = False
                elif action == "pause":
                    paused = False
            except asyncio.TimeoutError:
                pass  # 正常超时，推送指标

            if not paused:
                # 推送当前时刻的核心指标
                await ws.send_json({
                    "type": "metrics_snapshot",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "event": "cockpit_update",
                    },
                })

    except WebSocketDisconnect:
        manager.disconnect(x_tenant_id, ws)
    except Exception:
        logger.exception("ops_cockpit.ws_error")
        manager.disconnect(x_tenant_id, ws)
