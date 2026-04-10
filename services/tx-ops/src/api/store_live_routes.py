"""营业中控台 API 路由（Mock 数据版）

端点:
  GET /api/v1/ops/store/live-dashboard  门店实时运营数据

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/store", tags=["ops-store-live"])
log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MOCK_STORE_LIVE: Dict[str, Any] = {
    "overview": {
        "total_stores": 12,
        "open_stores": 10,
        "closed_stores": 2,
        "alert_stores": 3,
    },
    "real_time_metrics": {
        "total_revenue_fen": 15680000,
        "total_orders": 487,
        "avg_ticket_fen": 32200,
        "table_turnover_rate": 2.8,
        "current_diners": 186,
        "waiting_count": 23,
    },
    "stores": [
        {
            "store_id": "store-001",
            "store_name": "尝在一起(芙蓉广场店)",
            "status": "open",
            "open_since": "2026-04-10T10:00:00+08:00",
            "revenue_fen": 2860000,
            "orders": 89,
            "avg_ticket_fen": 32130,
            "current_diners": 42,
            "total_seats": 80,
            "seat_utilization": 0.525,
            "table_turnover_rate": 3.1,
            "waiting_count": 8,
            "avg_wait_minutes": 12,
            "kds_avg_seconds": 420,
            "kds_timeout_count": 2,
            "staff_on_duty": 8,
            "alerts": [
                {"type": "kds_timeout", "message": "3号厨房出餐超时(>15分钟)", "time": "2026-04-10T12:35:00+08:00", "severity": "high"},
            ],
            "hourly_revenue_fen": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 180000, 680000, 920000, 480000, 320000, 280000],
        },
        {
            "store_id": "store-002",
            "store_name": "尝在一起(五一广场店)",
            "status": "open",
            "open_since": "2026-04-10T09:30:00+08:00",
            "revenue_fen": 3210000,
            "orders": 102,
            "avg_ticket_fen": 31470,
            "current_diners": 56,
            "total_seats": 100,
            "seat_utilization": 0.56,
            "table_turnover_rate": 3.4,
            "waiting_count": 12,
            "avg_wait_minutes": 15,
            "kds_avg_seconds": 380,
            "kds_timeout_count": 0,
            "staff_on_duty": 10,
            "alerts": [],
            "hourly_revenue_fen": [0, 0, 0, 0, 0, 0, 0, 0, 0, 210000, 520000, 780000, 860000, 420000, 220000, 198000],
        },
        {
            "store_id": "store-003",
            "store_name": "最黔线(河西店)",
            "status": "open",
            "open_since": "2026-04-10T10:30:00+08:00",
            "revenue_fen": 1950000,
            "orders": 65,
            "avg_ticket_fen": 30000,
            "current_diners": 28,
            "total_seats": 60,
            "seat_utilization": 0.467,
            "table_turnover_rate": 2.6,
            "waiting_count": 3,
            "avg_wait_minutes": 8,
            "kds_avg_seconds": 350,
            "kds_timeout_count": 0,
            "staff_on_duty": 6,
            "alerts": [],
            "hourly_revenue_fen": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 120000, 480000, 620000, 380000, 210000, 140000],
        },
        {
            "store_id": "store-004",
            "store_name": "尚宫厨(万达店)",
            "status": "open",
            "open_since": "2026-04-10T11:00:00+08:00",
            "revenue_fen": 2480000,
            "orders": 58,
            "avg_ticket_fen": 42760,
            "current_diners": 34,
            "total_seats": 70,
            "seat_utilization": 0.486,
            "table_turnover_rate": 2.2,
            "waiting_count": 0,
            "avg_wait_minutes": 0,
            "kds_avg_seconds": 510,
            "kds_timeout_count": 3,
            "staff_on_duty": 7,
            "alerts": [
                {"type": "equipment", "message": "POS打印机卡纸告警", "time": "2026-04-10T13:20:00+08:00", "severity": "medium"},
                {"type": "kds_timeout", "message": "出餐平均时间偏高(8.5min)", "time": "2026-04-10T12:50:00+08:00", "severity": "medium"},
            ],
            "hourly_revenue_fen": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 580000, 780000, 520000, 360000, 240000],
        },
        {
            "store_id": "store-005",
            "store_name": "最黔线(岳麓店)",
            "status": "open",
            "open_since": "2026-04-10T10:00:00+08:00",
            "revenue_fen": 1680000,
            "orders": 53,
            "avg_ticket_fen": 31700,
            "current_diners": 18,
            "total_seats": 50,
            "seat_utilization": 0.36,
            "table_turnover_rate": 2.4,
            "waiting_count": 0,
            "avg_wait_minutes": 0,
            "kds_avg_seconds": 310,
            "kds_timeout_count": 0,
            "staff_on_duty": 5,
            "alerts": [],
            "hourly_revenue_fen": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100000, 380000, 520000, 340000, 200000, 140000],
        },
        {
            "store_id": "store-006",
            "store_name": "尝在一起(梅溪湖店)",
            "status": "closed",
            "open_since": None,
            "revenue_fen": 0,
            "orders": 0,
            "avg_ticket_fen": 0,
            "current_diners": 0,
            "total_seats": 60,
            "seat_utilization": 0,
            "table_turnover_rate": 0,
            "waiting_count": 0,
            "avg_wait_minutes": 0,
            "kds_avg_seconds": 0,
            "kds_timeout_count": 0,
            "staff_on_duty": 0,
            "alerts": [
                {"type": "store_closed", "message": "门店今日未营业（装修中）", "time": "2026-04-10T08:00:00+08:00", "severity": "low"},
            ],
            "hourly_revenue_fen": [],
        },
    ],
    "channel_breakdown": {
        "dine_in": {"orders": 312, "revenue_fen": 10240000},
        "takeaway_meituan": {"orders": 86, "revenue_fen": 2580000},
        "takeaway_ele": {"orders": 52, "revenue_fen": 1560000},
        "takeaway_douyin": {"orders": 37, "revenue_fen": 1300000},
    },
    "snapshot_time": "2026-04-10T15:30:00+08:00",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/live-dashboard")
async def get_live_dashboard(
    store_id: Optional[str] = Query(None, description="指定门店ID（不传返回全部）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """门店实时运营数据中控台。"""
    log.info("store_live_dashboard_requested", tenant_id=x_tenant_id, store_id=store_id)

    if store_id:
        for s in _MOCK_STORE_LIVE["stores"]:
            if s["store_id"] == store_id:
                return {"ok": True, "data": {"stores": [s], "snapshot_time": _MOCK_STORE_LIVE["snapshot_time"]}}
        return {"ok": True, "data": {"stores": [], "snapshot_time": _MOCK_STORE_LIVE["snapshot_time"]}}

    return {"ok": True, "data": _MOCK_STORE_LIVE}
