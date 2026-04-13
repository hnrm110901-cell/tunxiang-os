"""
出餐时间预测 + 翻台时机预测 Service

架构：
  - 优先调用 mac-station (Core ML) 进行边缘推理
  - mac-station 不可用时降级到规则引擎（基于历史均值）
  - 预测结果带置信度分级：high / medium / low

出餐时间预测：
  predict_dish_time(dish_id, dept_id, store_id, tenant_id) -> DishTimePrediction
    基于：该菜品历史平均制作时长 + 当前KDS队列深度 + 时段系数
    返回：estimated_minutes(int), confidence('high'|'medium'|'low'), method('ml'|'rule')

  predict_order_completion(order_id, tenant_id, db) -> OrderCompletionPrediction
    所有未出餐菜品的最大预测时间
    返回：estimated_minutes, earliest_dish, latest_dish

翻台时机预测：
  predict_table_turn(table_no, order_id, store_id, tenant_id, db) -> TableTurnPrediction
    基于：当前就餐时长 + 历史同规模桌台就餐时长分布
    返回：
      estimated_finish_minutes: int  # 预计还需N分钟
      confidence: str
      suggestion: str | None  # 如 "预计20分钟后结束，是否提前通知候位顾客？"

  get_busy_period_forecast(store_id, date, tenant_id, db) -> list[BusyPeriod]
    今日高峰时段预测（基于历史数据）
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

COREML_URL = os.getenv("COREML_BRIDGE_URL", "http://localhost:8100")

# ─── 时段系数 ───
# 午高峰 11:30-13:00 × 1.3，晚高峰 17:30-20:00 × 1.4，其他 × 1.0
_PEAK_PERIODS = [
    (11, 30, 13, 0,  1.3),   # (start_h, start_m, end_h, end_m, factor)
    (17, 30, 20, 0,  1.4),
]

# ─── 默认兜底数据（无历史数据/ML 不可用时使用） ───
_DEFAULT_DISH_PREP_SECONDS: dict[str, float] = {
    "default": 600.0,   # 10分钟兜底
}

_DEFAULT_TABLE_DINING_MINUTES: dict[int, float] = {
    2: 45.0,
    4: 55.0,
    6: 70.0,
    8: 85.0,
    12: 100.0,
}


# ────────────────────────────────────────────
# 数据类（轻量，无ORM依赖）
# ────────────────────────────────────────────

class DishTimePrediction:
    __slots__ = ("dish_id", "estimated_minutes", "confidence", "method", "queue_depth", "raw_seconds")

    def __init__(
        self,
        dish_id: str,
        estimated_minutes: int,
        confidence: str,
        method: str,
        queue_depth: int = 0,
        raw_seconds: float = 0.0,
    ) -> None:
        self.dish_id = dish_id
        self.estimated_minutes = estimated_minutes
        self.confidence = confidence
        self.method = method
        self.queue_depth = queue_depth
        self.raw_seconds = raw_seconds

    def to_dict(self) -> dict:
        return {
            "dish_id": self.dish_id,
            "estimated_minutes": self.estimated_minutes,
            "confidence": self.confidence,
            "method": self.method,
            "queue_depth": self.queue_depth,
            "raw_seconds": self.raw_seconds,
        }


class OrderCompletionPrediction:
    __slots__ = ("order_id", "estimated_minutes", "earliest_dish", "latest_dish", "pending_count")

    def __init__(
        self,
        order_id: str,
        estimated_minutes: int,
        earliest_dish: str,
        latest_dish: str,
        pending_count: int,
    ) -> None:
        self.order_id = order_id
        self.estimated_minutes = estimated_minutes
        self.earliest_dish = earliest_dish
        self.latest_dish = latest_dish
        self.pending_count = pending_count

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "estimated_minutes": self.estimated_minutes,
            "earliest_dish": self.earliest_dish,
            "latest_dish": self.latest_dish,
            "pending_count": self.pending_count,
        }


class TableTurnPrediction:
    __slots__ = (
        "table_no", "estimated_finish_minutes", "confidence",
        "suggestion", "elapsed_minutes", "avg_dining_minutes",
    )

    def __init__(
        self,
        table_no: str,
        estimated_finish_minutes: int,
        confidence: str,
        suggestion: Optional[str],
        elapsed_minutes: int,
        avg_dining_minutes: float,
    ) -> None:
        self.table_no = table_no
        self.estimated_finish_minutes = estimated_finish_minutes
        self.confidence = confidence
        self.suggestion = suggestion
        self.elapsed_minutes = elapsed_minutes
        self.avg_dining_minutes = avg_dining_minutes

    def to_dict(self) -> dict:
        return {
            "table_no": self.table_no,
            "estimated_finish_minutes": self.estimated_finish_minutes,
            "confidence": self.confidence,
            "suggestion": self.suggestion,
            "elapsed_minutes": self.elapsed_minutes,
            "avg_dining_minutes": self.avg_dining_minutes,
        }


class BusyPeriod:
    __slots__ = ("start_time", "end_time", "expected_covers", "confidence")

    def __init__(
        self,
        start_time: str,
        end_time: str,
        expected_covers: int,
        confidence: str,
    ) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self.expected_covers = expected_covers
        self.confidence = confidence

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "expected_covers": self.expected_covers,
            "confidence": self.confidence,
        }


# ────────────────────────────────────────────
# Core ML 调用（1秒超时，快速降级）
# ────────────────────────────────────────────

async def _call_coreml_dish_time(dish_id: str, queue_depth: int) -> Optional[float]:
    """调用 coreml-bridge 预测菜品制作时间。1秒超时，失败返回None触发规则降级。"""
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.post(
                f"{COREML_URL}/predict/dish-time",
                json={"dish_id": dish_id, "queue_depth": queue_depth},
            )
            if resp.status_code == 200:
                payload = resp.json()
                val = payload.get("estimated_seconds")
                if isinstance(val, (int, float)) and val > 0:
                    return float(val)
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return None


async def _call_coreml_table_turn(
    table_no: str,
    seats: int,
    elapsed_minutes: int,
) -> Optional[float]:
    """调用 coreml-bridge 预测翻台剩余分钟数。1秒超时，失败返回None触发规则降级。"""
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.post(
                f"{COREML_URL}/predict/table-turn",
                json={
                    "table_no": table_no,
                    "seats": seats,
                    "elapsed_minutes": elapsed_minutes,
                },
            )
            if resp.status_code == 200:
                payload = resp.json()
                val = payload.get("estimated_finish_minutes")
                if isinstance(val, (int, float)) and val >= 0:
                    return float(val)
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return None


# ────────────────────────────────────────────
# 时段系数
# ────────────────────────────────────────────

def _get_peak_factor(now: Optional[datetime] = None) -> float:
    """根据当前时间返回高峰时段系数。"""
    dt = now or datetime.now(tz=timezone.utc).astimezone()
    h, m = dt.hour, dt.minute
    current_minutes = h * 60 + m
    for sh, sm, eh, em, factor in _PEAK_PERIODS:
        start = sh * 60 + sm
        end = eh * 60 + em
        if start <= current_minutes < end:
            return factor
    return 1.0


# ────────────────────────────────────────────
# 规则引擎：菜品平均制作时长（DB + 默认值降级）
# ────────────────────────────────────────────

async def _get_dish_avg_seconds(
    dish_id: str,
    dept_id: str,
    store_id: str,
    tenant_id: str,
    db: Any,
) -> tuple[float, bool]:
    """
    返回 (avg_cook_seconds, has_real_data)。
    先查过去30天 kds_tasks 历史均值（called_at → served_at 为实际制作+叫菜时长）；
    无数据时降级到默认兜底值。
    """
    if db is None:
        return _DEFAULT_DISH_PREP_SECONDS.get(dish_id, _DEFAULT_DISH_PREP_SECONDS["default"]), False

    try:
        from sqlalchemy import text as sa_text
        sql = sa_text("""
            SELECT AVG(EXTRACT(EPOCH FROM (kt.served_at - kt.called_at))) AS avg_seconds,
                   COUNT(*) AS sample_count
            FROM kds_tasks kt
            JOIN order_items oi ON oi.id = kt.order_item_id
            WHERE oi.dish_id = :dish_id::uuid
              AND kt.dept_id = :dept_id::uuid
              AND kt.tenant_id = :tenant_id::uuid
              AND kt.called_at IS NOT NULL
              AND kt.served_at IS NOT NULL
              AND kt.served_at > NOW() - INTERVAL '30 days'
              AND kt.status = 'done'
        """)
        result = await db.execute(
            sql,
            {
                "dish_id": dish_id,
                "dept_id": dept_id,
                "tenant_id": tenant_id,
            },
        )
        row = result.fetchone()
        if row and row.sample_count and row.sample_count >= 3 and row.avg_seconds:
            return float(row.avg_seconds), True
    except Exception as exc:  # noqa: BLE001 — 最外层兜底
        logger.warning("dish_avg_seconds_query_failed", dish_id=dish_id, error=str(exc), exc_info=True)

    return _DEFAULT_DISH_PREP_SECONDS.get(dish_id, _DEFAULT_DISH_PREP_SECONDS["default"]), False


async def _get_queue_depth(
    dept_id: str,
    store_id: str,
    tenant_id: str,
    db: Any,
) -> int:
    """返回当前档口 pending 任务数量。"""
    if db is None:
        return 0
    try:
        from sqlalchemy import text as sa_text
        sql = sa_text("""
            SELECT COUNT(*) AS cnt
            FROM kds_tasks
            WHERE dept_id = :dept_id
              AND store_id = :store_id
              AND tenant_id = :tenant_id
              AND status IN ('pending', 'cooking')
        """)
        result = await db.execute(
            sql,
            {"dept_id": dept_id, "store_id": store_id, "tenant_id": tenant_id},
        )
        row = result.fetchone()
        return int(row.cnt) if row else 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("queue_depth_query_failed", dept_id=dept_id, error=str(exc), exc_info=True)
        return 0


# ────────────────────────────────────────────
# 规则引擎：桌台平均就餐时长（DB + 默认值降级）
# ────────────────────────────────────────────

async def _get_avg_dining_minutes(
    seats: int,
    store_id: str,
    tenant_id: str,
    db: Any,
) -> tuple[float, bool]:
    """
    返回 (avg_dining_minutes, has_real_data)。
    查过去30天 dining_sessions 中同容量桌台的完整就餐时长均值
    （opened_at → cleared_at）。
    """
    if db is None:
        fallback = _DEFAULT_TABLE_DINING_MINUTES.get(
            seats,
            _DEFAULT_TABLE_DINING_MINUTES[4],
        )
        return fallback, False

    try:
        from sqlalchemy import text as sa_text
        sql = sa_text("""
            SELECT AVG(EXTRACT(EPOCH FROM (ds.cleared_at - ds.opened_at)) / 60) AS avg_min,
                   COUNT(*) AS sample_count
            FROM dining_sessions ds
            JOIN tables t ON t.id = ds.table_id
            WHERE ds.store_id = :store_id::uuid
              AND ds.tenant_id = :tenant_id::uuid
              AND ds.status = 'paid'
              AND t.seats = :seats
              AND ds.cleared_at IS NOT NULL
              AND ds.cleared_at > NOW() - INTERVAL '30 days'
        """)
        result = await db.execute(
            sql,
            {"store_id": store_id, "tenant_id": tenant_id, "seats": seats},
        )
        row = result.fetchone()
        if row and row.sample_count and row.sample_count >= 5 and row.avg_min:
            return float(row.avg_min), True
    except Exception as exc:  # noqa: BLE001
        logger.warning("avg_dining_minutes_query_failed", seats=seats, error=str(exc), exc_info=True)

    # 按座位数插值兜底
    keys = sorted(_DEFAULT_TABLE_DINING_MINUTES.keys())
    best = keys[0]
    for k in keys:
        if k <= seats:
            best = k
    return _DEFAULT_TABLE_DINING_MINUTES[best], False


# ────────────────────────────────────────────
# 公开接口
# ────────────────────────────────────────────

async def predict_dish_time(
    dish_id: str,
    dept_id: str,
    store_id: str,
    tenant_id: str,
    db: Any = None,
) -> DishTimePrediction:
    """
    出餐时间预测。

    优先 Core ML（1秒超时），降级到规则引擎：
      规则 = avg_cook_seconds × peak_factor + queue_depth × 30秒
    """
    queue_depth = await _get_queue_depth(dept_id, store_id, tenant_id, db)

    # 1. 尝试 Core ML
    ml_seconds = await _call_coreml_dish_time(dish_id, queue_depth)
    if ml_seconds is not None:
        estimated_minutes = max(1, round(ml_seconds / 60))
        return DishTimePrediction(
            dish_id=dish_id,
            estimated_minutes=estimated_minutes,
            confidence="high",
            method="ml",
            queue_depth=queue_depth,
            raw_seconds=ml_seconds,
        )

    # 2. 规则引擎降级
    avg_seconds, has_real_data = await _get_dish_avg_seconds(
        dish_id, dept_id, store_id, tenant_id, db
    )
    peak_factor = _get_peak_factor()
    # 队列系数：每个pending任务额外30秒等待
    queue_extra_seconds = queue_depth * 30.0
    raw_seconds = avg_seconds * peak_factor + queue_extra_seconds
    estimated_minutes = max(1, round(raw_seconds / 60))

    confidence = "high" if has_real_data else "low"
    if has_real_data and queue_depth > 5:
        confidence = "medium"

    return DishTimePrediction(
        dish_id=dish_id,
        estimated_minutes=estimated_minutes,
        confidence=confidence,
        method="rule",
        queue_depth=queue_depth,
        raw_seconds=raw_seconds,
    )


async def predict_order_completion(
    order_id: str,
    tenant_id: str,
    db: Any = None,
) -> OrderCompletionPrediction:
    """
    订单整体出餐完成预测。

    获取订单所有未出餐菜品，逐一预测，取最大值。
    无DB时使用 Mock 单菜品预测。
    """
    pending_items: list[dict] = []

    if db is not None:
        try:
            from sqlalchemy import text as sa_text
            sql = sa_text("""
                SELECT oi.dish_id, oi.dish_name, oi.dept_id, o.store_id
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE oi.order_id = :order_id
                  AND o.tenant_id = :tenant_id
                  AND oi.kds_status NOT IN ('done', 'cancelled')
            """)
            result = await db.execute(sql, {"order_id": order_id, "tenant_id": tenant_id})
            rows = result.fetchall()
            pending_items = [
                {
                    "dish_id": str(r.dish_id),
                    "dish_name": r.dish_name,
                    "dept_id": str(r.dept_id),
                    "store_id": str(r.store_id),
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("order_items_query_failed", order_id=order_id, error=str(exc), exc_info=True)

    # 无数据时 mock 2道菜
    if not pending_items:
        pending_items = [
            {"dish_id": "mock_dish_1", "dish_name": "制作中菜品", "dept_id": "dept_1", "store_id": "store_1"},
            {"dish_id": "mock_dish_2", "dish_name": "等待中菜品", "dept_id": "dept_1", "store_id": "store_1"},
        ]

    predictions: list[tuple[str, int]] = []
    for item in pending_items:
        p = await predict_dish_time(
            dish_id=item["dish_id"],
            dept_id=item["dept_id"],
            store_id=item["store_id"],
            tenant_id=tenant_id,
            db=db,
        )
        predictions.append((item["dish_name"], p.estimated_minutes))

    predictions.sort(key=lambda x: x[1])
    earliest_dish = predictions[0][0] if predictions else ""
    latest_dish = predictions[-1][0] if predictions else ""
    estimated_minutes = predictions[-1][1] if predictions else 0

    return OrderCompletionPrediction(
        order_id=order_id,
        estimated_minutes=estimated_minutes,
        earliest_dish=earliest_dish,
        latest_dish=latest_dish,
        pending_count=len(predictions),
    )


async def predict_table_turn(
    table_no: str,
    order_id: str,
    store_id: str,
    tenant_id: str,
    db: Any = None,
    seats: int = 4,
    elapsed_minutes: int = 0,
) -> TableTurnPrediction:
    """
    翻台时机预测。

    优先 Core ML，降级到规则引擎：
      remaining = avg_dining_minutes - elapsed_minutes
      confidence：
        elapsed/avg < 0.5  → low（就餐才开始，不确定性大）
        0.5 ≤ elapsed/avg < 0.85 → medium
        elapsed/avg ≥ 0.85 → high（快结束了）
    """
    # 如果有order_id，尝试从DB获取真实数据
    real_elapsed = elapsed_minutes
    real_seats = seats

    if db is not None and order_id:
        try:
            from sqlalchemy import text as sa_text
            sql = sa_text("""
                SELECT
                    EXTRACT(EPOCH FROM (NOW() - o.opened_at)) / 60 AS elapsed_min,
                    t.seats
                FROM orders o
                JOIN tables t ON t.no = o.table_no AND t.store_id = o.store_id
                WHERE o.id = :order_id
                  AND o.tenant_id = :tenant_id
                LIMIT 1
            """)
            result = await db.execute(sql, {"order_id": order_id, "tenant_id": tenant_id})
            row = result.fetchone()
            if row:
                real_elapsed = int(row.elapsed_min or elapsed_minutes)
                real_seats = int(row.seats or seats)
        except Exception as exc:  # noqa: BLE001
            logger.warning("table_elapsed_query_failed", order_id=order_id, error=str(exc), exc_info=True)

    avg_dining, has_real_data = await _get_avg_dining_minutes(
        real_seats, store_id, tenant_id, db
    )

    # 1. 尝试 Core ML
    ml_finish = await _call_coreml_table_turn(table_no, real_seats, real_elapsed)
    if ml_finish is not None:
        remaining = max(0, round(ml_finish))
        confidence = _calc_turn_confidence(real_elapsed, avg_dining, use_ml=True)
        suggestion = _gen_turn_suggestion(table_no, remaining, confidence)
        return TableTurnPrediction(
            table_no=table_no,
            estimated_finish_minutes=remaining,
            confidence=confidence,
            suggestion=suggestion,
            elapsed_minutes=real_elapsed,
            avg_dining_minutes=avg_dining,
        )

    # 2. 规则引擎
    remaining = max(0, round(avg_dining - real_elapsed))
    confidence = _calc_turn_confidence(real_elapsed, avg_dining, use_ml=False)
    if not has_real_data:
        confidence = "low"
    suggestion = _gen_turn_suggestion(table_no, remaining, confidence)

    return TableTurnPrediction(
        table_no=table_no,
        estimated_finish_minutes=remaining,
        confidence=confidence,
        suggestion=suggestion,
        elapsed_minutes=real_elapsed,
        avg_dining_minutes=avg_dining,
    )


def _calc_turn_confidence(elapsed: int, avg: float, use_ml: bool = False) -> str:
    if avg <= 0:
        return "low"
    ratio = elapsed / avg
    if use_ml:
        if ratio >= 0.7:
            return "high"
        if ratio >= 0.4:
            return "medium"
        return "low"
    else:
        if ratio >= 0.85:
            return "high"
        if ratio >= 0.5:
            return "medium"
        return "low"


def _gen_turn_suggestion(table_no: str, remaining_minutes: int, confidence: str) -> Optional[str]:
    if confidence == "low":
        return None
    if remaining_minutes <= 20:
        return f"{table_no}桌预计{remaining_minutes}分钟后结束，是否提前通知候位顾客？"
    if remaining_minutes <= 35:
        return f"{table_no}桌预计约{remaining_minutes}分钟后翻台，可提前安排候位。"
    return None


async def get_busy_period_forecast(
    store_id: str,
    date: str,
    tenant_id: str,
    db: Any = None,
) -> list[BusyPeriod]:
    """
    今日高峰时段预测。

    基于过去30天同星期几的历史客流分布，识别高峰时段。
    无数据时返回通用高峰时段模板。
    """
    if db is not None:
        try:
            from sqlalchemy import text as sa_text
            sql = sa_text("""
                SELECT
                    EXTRACT(HOUR FROM opened_at) AS hour,
                    COUNT(*) AS order_count
                FROM orders
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND opened_at > NOW() - INTERVAL '30 days'
                  AND EXTRACT(DOW FROM opened_at) = EXTRACT(DOW FROM :target_date::date)
                GROUP BY 1
                ORDER BY 2 DESC
                LIMIT 6
            """)
            result = await db.execute(
                sql,
                {"store_id": store_id, "tenant_id": tenant_id, "target_date": date},
            )
            rows = result.fetchall()
            if rows and len(rows) >= 2:
                # 找出连续高峰时段
                busy_hours = sorted([int(r.hour) for r in rows[:4]])
                periods = []
                start = busy_hours[0]
                end = busy_hours[0] + 1
                for h in busy_hours[1:]:
                    if h <= end + 1:
                        end = h + 1
                    else:
                        periods.append(BusyPeriod(
                            start_time=f"{start:02d}:00",
                            end_time=f"{end:02d}:00",
                            expected_covers=int(rows[0].order_count),
                            confidence="medium",
                        ))
                        start = h
                        end = h + 1
                periods.append(BusyPeriod(
                    start_time=f"{start:02d}:00",
                    end_time=f"{end:02d}:00",
                    expected_covers=int(rows[0].order_count),
                    confidence="medium",
                ))
                return periods
        except Exception as exc:  # noqa: BLE001
            logger.warning("busy_period_query_failed", store_id=store_id, error=str(exc), exc_info=True)

    # 通用模板兜底
    return [
        BusyPeriod(start_time="11:30", end_time="13:00", expected_covers=80, confidence="low"),
        BusyPeriod(start_time="17:30", end_time="20:00", expected_covers=120, confidence="low"),
    ]
