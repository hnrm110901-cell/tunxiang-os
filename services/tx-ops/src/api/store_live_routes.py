"""营业中控台 API 路由（真实DB版）

数据源：
  stores        — 门店基本信息（id, store_name, status）
  orders        — 今日订单（status, total_amount_fen, created_at, store_id）
  dining_sessions — 当前活跃桌台会话（seated/ordering/dining/add_ordering）
  compliance_alerts — 门店告警（severity, status='open'）

端点:
  GET /api/v1/ops/store/live-dashboard  门店实时运营数据

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/store", tags=["ops-store-live"])
log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/live-dashboard")
async def get_live_dashboard(
    store_id: Optional[str] = Query(None, description="指定门店ID（不传返回全部）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """门店实时运营数据中控台。"""
    log.info("store_live_dashboard_requested", tenant_id=x_tenant_id, store_id=store_id)
    snapshot_time = datetime.now(tz=timezone.utc).isoformat()

    try:
        await _set_rls(db, x_tenant_id)

        # 1. 门店列表
        stores_q = """
            SELECT id, store_name, status
            FROM stores
            WHERE tenant_id = :tid AND is_deleted = FALSE
        """
        params: Dict[str, Any] = {"tid": x_tenant_id}
        if store_id:
            stores_q += " AND id = :sid::uuid"
            params["sid"] = store_id
        stores_q += " ORDER BY store_name"
        stores_result = await db.execute(text(stores_q), params)
        store_rows = stores_result.fetchall()

        if not store_rows:
            return {
                "ok": True,
                "data": {
                    "overview": {"total_stores": 0, "open_stores": 0, "closed_stores": 0, "alert_stores": 0},
                    "real_time_metrics": {
                        "total_revenue_fen": 0,
                        "total_orders": 0,
                        "avg_ticket_fen": 0,
                        "table_turnover_rate": 0,
                        "current_diners": 0,
                        "waiting_count": 0,
                    },
                    "stores": [],
                    "snapshot_time": snapshot_time,
                },
            }

        store_ids = [str(r.id) for r in store_rows]
        store_id_list = "'" + "','".join(store_ids) + "'"

        # 2. 今日订单汇总（按门店）
        orders_agg_result = await db.execute(
            text(f"""
                SELECT
                    store_id,
                    COUNT(*)                                            AS order_count,
                    COALESCE(SUM(total_amount_fen), 0)                  AS revenue_fen,
                    COALESCE(AVG(total_amount_fen), 0)                  AS avg_ticket_fen,
                    MIN(created_at)                                     AS first_order_at
                FROM orders
                WHERE tenant_id = :tid
                  AND store_id::text IN ({store_id_list})
                  AND status = 'paid'
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE
                GROUP BY store_id
            """),
            {"tid": x_tenant_id},
        )
        orders_by_store: Dict[str, Any] = {}
        for row in orders_agg_result.fetchall():
            orders_by_store[str(row.store_id)] = {
                "order_count": int(row.order_count),
                "revenue_fen": int(row.revenue_fen),
                "avg_ticket_fen": int(row.avg_ticket_fen),
                "first_order_at": row.first_order_at.isoformat() if row.first_order_at else None,
            }

        # 3. 活跃就餐会话（dining_sessions — seated/ordering/dining/add_ordering/billing）
        active_sessions_result = await db.execute(
            text(f"""
                SELECT
                    store_id,
                    COUNT(*)          AS active_sessions,
                    SUM(guest_count)  AS total_diners
                FROM dining_sessions
                WHERE tenant_id = :tid
                  AND store_id::text IN ({store_id_list})
                  AND status NOT IN ('paid', 'clearing', 'disabled')
                  AND is_deleted = FALSE
                GROUP BY store_id
            """),
            {"tid": x_tenant_id},
        )
        sessions_by_store: Dict[str, Any] = {}
        for row in active_sessions_result.fetchall():
            sessions_by_store[str(row.store_id)] = {
                "active_sessions": int(row.active_sessions),
                "total_diners": int(row.total_diners or 0),
            }

        # 4. 桌台总座位数（tables per store）
        tables_result = await db.execute(
            text(f"""
                SELECT store_id, COUNT(*) AS table_count, SUM(seats) AS total_seats
                FROM tables
                WHERE tenant_id = :tid
                  AND store_id::text IN ({store_id_list})
                  AND is_deleted = FALSE AND is_active = TRUE
                GROUP BY store_id
            """),
            {"tid": x_tenant_id},
        )
        tables_by_store: Dict[str, Any] = {}
        for row in tables_result.fetchall():
            tables_by_store[str(row.store_id)] = {
                "table_count": int(row.table_count),
                "total_seats": int(row.total_seats or 0),
            }

        # 5. 今日已完成桌台会话数（用于翻台率）
        closed_sessions_result = await db.execute(
            text(f"""
                SELECT store_id, COUNT(*) AS closed_count
                FROM dining_sessions
                WHERE tenant_id = :tid
                  AND store_id::text IN ({store_id_list})
                  AND status IN ('paid', 'clearing')
                  AND DATE(opened_at AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE
                  AND is_deleted = FALSE
                GROUP BY store_id
            """),
            {"tid": x_tenant_id},
        )
        closed_by_store: Dict[str, Any] = {}
        for row in closed_sessions_result.fetchall():
            closed_by_store[str(row.store_id)] = int(row.closed_count)

        # 6. 未处理告警（compliance_alerts）
        alerts_result = await db.execute(
            text(f"""
                SELECT store_id, severity, title, created_at
                FROM compliance_alerts
                WHERE tenant_id = :tid
                  AND status = 'open'
                  AND store_id::text IN ({store_id_list})
                ORDER BY created_at DESC
            """),
            {"tid": x_tenant_id},
        )
        alerts_by_store: Dict[str, List[Dict[str, Any]]] = {}
        for row in alerts_result.fetchall():
            sid = str(row.store_id) if row.store_id else None
            if sid:
                if sid not in alerts_by_store:
                    alerts_by_store[sid] = []
                alerts_by_store[sid].append(
                    {
                        "type": "compliance",
                        "message": row.title,
                        "time": row.created_at.isoformat() if row.created_at else None,
                        "severity": row.severity,
                    }
                )

        # Build per-store objects
        stores_out: List[Dict[str, Any]] = []
        total_revenue = 0
        total_orders = 0
        total_diners = 0
        alert_store_ids: set = set()

        for s in store_rows:
            sid = str(s.id)
            is_open = s.status not in ("closed", "disabled", "maintenance")
            ord_data = orders_by_store.get(sid, {})
            sess_data = sessions_by_store.get(sid, {})
            tbl_data = tables_by_store.get(sid, {})
            store_alerts = alerts_by_store.get(sid, [])

            revenue_fen = ord_data.get("revenue_fen", 0)
            order_count = ord_data.get("order_count", 0)
            avg_ticket = ord_data.get("avg_ticket_fen", 0)
            current_diners = sess_data.get("total_diners", 0)
            total_seats = tbl_data.get("total_seats", 0)
            seat_util = round(current_diners / total_seats, 3) if total_seats > 0 else 0.0

            # 翻台率 = 已完成会话 / 桌台数
            table_count = tbl_data.get("table_count", 0)
            closed_count = closed_by_store.get(sid, 0)
            turnover_rate = round(closed_count / table_count, 1) if table_count > 0 else 0.0

            total_revenue += revenue_fen
            total_orders += order_count
            total_diners += current_diners
            if store_alerts:
                alert_store_ids.add(sid)

            stores_out.append(
                {
                    "store_id": sid,
                    "store_name": s.store_name,
                    "status": "open" if is_open else "closed",
                    "open_since": ord_data.get("first_order_at"),
                    "revenue_fen": revenue_fen,
                    "orders": order_count,
                    "avg_ticket_fen": avg_ticket,
                    "current_diners": current_diners,
                    "total_seats": total_seats,
                    "seat_utilization": seat_util,
                    "table_turnover_rate": turnover_rate,
                    "waiting_count": 0,  # 排队人数需接入 waitlist 表，当前返回 0
                    "avg_wait_minutes": 0,
                    "alerts": store_alerts,
                }
            )

        open_count = sum(1 for r in store_rows if r.status not in ("closed", "disabled", "maintenance"))
        closed_count_all = len(store_rows) - open_count
        avg_ticket_all = round(total_revenue / total_orders) if total_orders > 0 else 0

        return {
            "ok": True,
            "data": {
                "overview": {
                    "total_stores": len(store_rows),
                    "open_stores": open_count,
                    "closed_stores": closed_count_all,
                    "alert_stores": len(alert_store_ids),
                },
                "real_time_metrics": {
                    "total_revenue_fen": total_revenue,
                    "total_orders": total_orders,
                    "avg_ticket_fen": avg_ticket_all,
                    "table_turnover_rate": 0,
                    "current_diners": total_diners,
                    "waiting_count": 0,
                },
                "stores": stores_out,
                "snapshot_time": snapshot_time,
            },
        }

    except SQLAlchemyError as exc:
        log.error("store_live_dashboard_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "overview": {"total_stores": 0, "open_stores": 0, "closed_stores": 0, "alert_stores": 0},
                "real_time_metrics": {
                    "total_revenue_fen": 0,
                    "total_orders": 0,
                    "avg_ticket_fen": 0,
                    "table_turnover_rate": 0,
                    "current_diners": 0,
                    "waiting_count": 0,
                },
                "stores": [],
                "snapshot_time": snapshot_time,
            },
        }
