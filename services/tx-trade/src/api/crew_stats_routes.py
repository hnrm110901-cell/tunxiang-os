"""服务员绩效统计 API 路由

W6 服务员绩效实时看板后端接口
"""
import random
from datetime import date, timedelta
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/crew/stats", tags=["crew-stats"])

# ---------- Mock 数据 ----------

_MOCK_OPERATORS = [
    {"operator_id": "op-001", "operator_name": "张三",  "revenue": 428000, "turns": 3, "upsell": 2},
    {"operator_id": "op-002", "operator_name": "李四",  "revenue": 682000, "turns": 5, "upsell": 4},
    {"operator_id": "op-003", "operator_name": "王五",  "revenue": 392000, "turns": 3, "upsell": 1},
    {"operator_id": "op-004", "operator_name": "赵六",  "revenue": 210000, "turns": 2, "upsell": 0},
    {"operator_id": "op-005", "operator_name": "孙七",  "revenue": 156000, "turns": 1, "upsell": 0},
]


def _badge(rank: int) -> Optional[str]:
    return {1: "gold", 2: "silver", 3: "bronze"}.get(rank)


def _build_mock_stats(operator_id: str) -> dict:
    """根据 operator_id 构建 Mock 绩效数据，不存在时返回第一条。"""
    op = next((o for o in _MOCK_OPERATORS if o["operator_id"] == operator_id), _MOCK_OPERATORS[0])

    # 计算排名（按营收）
    sorted_ops = sorted(_MOCK_OPERATORS, key=lambda x: x["revenue"], reverse=True)
    rank = next((i + 1 for i, o in enumerate(sorted_ops) if o["operator_id"] == op["operator_id"]), 1)

    total = op["revenue"]
    upsell_count = op["upsell"]
    table_count = op["turns"] + 1
    upsell_rate = round(upsell_count / table_count * 100, 1) if table_count else 0.0

    return {
        "operator_id": op["operator_id"],
        "operator_name": op["operator_name"],
        "table_count": table_count,
        "table_turns": op["turns"],
        "revenue_contributed": total,
        "avg_check": round(total / max(op["turns"], 1)),
        "upsell_count": upsell_count,
        "upsell_rate": upsell_rate,
        "bell_response_avg_sec": random.randint(30, 90),
        "complaint_count": 0,
        "rush_handled": random.randint(0, 5),
        "rank": rank,
        "total_staff": len(_MOCK_OPERATORS),
    }


def _build_leaderboard(
    metric: Literal["revenue", "turns", "upsell", "response"],
) -> list[dict]:
    """按指定维度构建排行榜 Mock 数据。"""
    key_map = {
        "revenue": "revenue",
        "turns": "turns",
        "upsell": "upsell",
    }

    if metric == "response":
        # 响应时间越短排名越高
        ops_with_val = [
            {**o, "_val": random.randint(25, 120)} for o in _MOCK_OPERATORS
        ]
        sorted_ops = sorted(ops_with_val, key=lambda x: x["_val"])
    else:
        k = key_map.get(metric, "revenue")
        ops_with_val = [{**o, "_val": o[k]} for o in _MOCK_OPERATORS]
        sorted_ops = sorted(ops_with_val, key=lambda x: x["_val"], reverse=True)

    result = []
    for i, op in enumerate(sorted_ops):
        rank = i + 1
        result.append({
            "rank": rank,
            "operator_id": op["operator_id"],
            "operator_name": op["operator_name"],
            "value": op["_val"],
            "badge": _badge(rank),
        })
    return result


def _build_trend(operator_id: str, days: int) -> list[dict]:
    """构建近 N 天每日绩效趋势 Mock 数据。"""
    op = next((o for o in _MOCK_OPERATORS if o["operator_id"] == operator_id), _MOCK_OPERATORS[0])
    base_turns = op["turns"]
    today = date.today()
    trend = []
    for d in range(days - 1, -1, -1):
        day = today - timedelta(days=d)
        turns = max(0, base_turns + random.randint(-2, 3))
        revenue = turns * random.randint(80000, 160000)
        trend.append({
            "date": day.isoformat(),
            "table_turns": turns,
            "revenue_contributed": revenue,
            "upsell_count": random.randint(0, turns),
        })
    return trend


# ---------- 路由 ----------

@router.get("/me")
async def get_my_stats(
    store_id: str = Query(..., description="门店 ID"),
    period: Literal["shift", "today", "week", "month"] = Query("today"),
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """获取当前服务员的绩效数据。

    使用 X-Operator-ID header 标识当前操作员。
    当前实现使用 Mock 数据兜底，生产环境需接入真实 DB 查询。
    """
    log = logger.bind(operator_id=x_operator_id, store_id=store_id, period=period)
    try:
        stats = _build_mock_stats(x_operator_id)
        log.info("crew_stats_me_ok", rank=stats["rank"])
        return {"ok": True, "data": stats}
    except KeyError as e:
        log.warning("crew_stats_me_key_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"无效参数: {e}")
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("crew_stats_me_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/leaderboard")
async def get_leaderboard(
    store_id: str = Query(..., description="门店 ID"),
    period: Literal["shift", "today", "week", "month"] = Query("today"),
    metric: Literal["revenue", "turns", "upsell", "response"] = Query("revenue"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """获取排行榜数据，按指定维度排序。

    metric:
    - revenue: 贡献营收
    - turns: 翻台次数
    - upsell: 加菜次数
    - response: 服务铃响应速度（越快越好）
    """
    log = logger.bind(store_id=store_id, period=period, metric=metric)
    try:
        board = _build_leaderboard(metric)
        log.info("crew_stats_leaderboard_ok", count=len(board))
        return {"ok": True, "data": {"items": board, "total": len(board)}}
    except ValueError as e:
        log.warning("crew_stats_leaderboard_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("crew_stats_leaderboard_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/trend")
async def get_trend(
    operator_id: str = Query(..., description="操作员 ID"),
    store_id: str = Query(..., description="门店 ID"),
    days: Literal[7, 30] = Query(7, description="近N天"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """获取指定服务员近 N 天每日绩效趋势数据。"""
    log = logger.bind(operator_id=operator_id, store_id=store_id, days=days)
    try:
        trend = _build_trend(operator_id, days)
        log.info("crew_stats_trend_ok", data_points=len(trend))
        return {"ok": True, "data": {"items": trend, "operator_id": operator_id}}
    except ValueError as e:
        log.warning("crew_stats_trend_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("crew_stats_trend_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
