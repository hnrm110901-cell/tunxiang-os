"""
折扣守护Agent增强 — 会员折扣频率检测 + 客位连续折扣预警
P3-01: 差异化护城河，AI领先能力

新增 Actions：
  member_frequency_check   — 同一会员N天内折扣频率超阈值预警
  table_pattern_analyze    — 同一桌台连续折扣异常模式检测
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()

router = APIRouter(
    prefix="/api/v1/agent/discount-guard",
    tags=["discount-guard-enhanced"],
)


# 内存决策日志（服务重启清零；生产环境替换为 DB 持久化）
_DECISION_LOGS: list[dict] = []


# ─── DB 依赖 ─────────────────────────────────────────────────────────────────


def _make_get_db(tenant_id: str):
    async def _get_db():
        async for session in get_db_with_tenant(tenant_id):
            yield session

    return _get_db


# ─── 请求体模型 ──────────────────────────────────────────────────────────────


class MemberFrequencyCheckRequest(BaseModel):
    member_id: str
    order_id: str
    discount_type: str
    discount_amount_fen: int


class TablePatternAnalyzeRequest(BaseModel):
    table_id: str
    order_id: str
    employee_id: str
    discount_amount_fen: int


# ─── 决策日志模型 ────────────────────────────────────────────────────────────


class DiscountGuardDecision(BaseModel):
    agent_id: str = "discount_guard_v2"
    decision_type: str  # "member_frequency_check" / "table_pattern_analyze"
    input_context: dict
    reasoning: str
    output_action: dict
    constraints_check: dict  # 三条硬约束：毛利底线 / 食安 / 客户体验
    confidence: float
    created_at: datetime


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _calc_risk_level(count: int, threshold: int) -> str:
    """根据折扣次数与阈值计算风险等级。

    比例倍数 = count / threshold
      < 1.0  → low
      1-2x   → medium（已达阈值但不超过2倍）
      > 2x   → high
    """
    if count < threshold:
        return "low"
    ratio = count / threshold
    if ratio <= 2.0:
        return "medium"
    return "high"


def _make_recommendation(risk_level: str, count: int, total_saved_fen: int) -> str:
    """根据风险等级给出操作建议。"""
    saved_yuan = total_saved_fen / 100
    if risk_level == "low":
        return "正常放行"
    if risk_level == "medium":
        return f"需主管审批（已享受{count}次折扣，累计减免¥{saved_yuan:.0f}）"
    return f"建议拒绝（高频异常：{count}次折扣，累计减免¥{saved_yuan:.0f}，严重超出品牌阈值）"


def _record_decision(decision: DiscountGuardDecision) -> None:
    """将 Agent 决策追加到内存日志（决策留痕，CLAUDE.md 强制规范）。"""
    _DECISION_LOGS.append(decision.model_dump(mode="json"))
    logger.info(
        "discount_guard_decision_logged",
        agent_id=decision.agent_id,
        decision_type=decision.decision_type,
        confidence=decision.confidence,
    )


def _build_constraints_check(
    discount_amount_fen: int,
    is_suspicious: bool,
) -> dict:
    """构建三条硬约束校验结果。"""
    return {
        "profit_floor": {
            "passed": not is_suspicious,
            "note": "折扣频率异常会侵蚀毛利底线" if is_suspicious else "未触发毛利底线约束",
        },
        "food_safety": {
            "passed": True,
            "note": "折扣行为与食安无直接关联",
        },
        "customer_experience": {
            "passed": True,
            "note": "频率检测不影响当前用餐体验",
        },
    }


# ─── DB 查询函数 ──────────────────────────────────────────────────────────────


async def _query_high_freq_members(
    db: AsyncSession,
    store_id: Optional[str],
    days: int,
    threshold: int,
) -> list[dict]:
    """查询高频折扣会员：同一会员在 days 天内折扣次数 >= threshold。

    从 customers + orders 表联合查询，统计折扣次数和累计折扣金额。
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    store_filter = "AND o.store_id = :store_id" if store_id else ""

    sql = text(f"""
        SELECT
            c.id::text                         AS member_id,
            c.full_name                        AS name,
            COUNT(o.id)                        AS discount_count,
            COALESCE(SUM(o.discount_amount_fen), 0) AS total_saved_fen,
            MAX(o.created_at)::date::text      AS latest_discount
        FROM customers c
        JOIN orders o ON o.customer_id = c.id
            AND o.tenant_id = c.tenant_id
        WHERE o.discount_amount_fen > 0
          AND o.created_at >= :since
          AND o.status NOT IN ('cancelled', 'refunded')
          {store_filter}
        GROUP BY c.id, c.full_name
        HAVING COUNT(o.id) >= :threshold
        ORDER BY COUNT(o.id) DESC
        LIMIT 200
    """)

    params: dict = {"since": since, "threshold": threshold}
    if store_id:
        params["store_id"] = store_id

    try:
        result = await db.execute(sql, params)
        rows = result.mappings().all()
    except SQLAlchemyError as exc:
        logger.error("discount_guard.member_freq_query_failed", error=str(exc))
        return []

    members = []
    for row in rows:
        count = int(row["discount_count"])
        total_fen = int(row["total_saved_fen"])
        level = _calc_risk_level(count, threshold)
        members.append(
            {
                "member_id": row["member_id"],
                "name": row["name"] or "未知",
                "discount_count": count,
                "total_saved_fen": total_fen,
                "risk_level": level,
                "latest_discount": row["latest_discount"],
                "note": f"{days}天内{count}次折扣，累计减免¥{total_fen / 100:.0f}",
            }
        )
    return members


async def _query_member_history(
    db: AsyncSession,
    member_id: str,
    days: int,
) -> dict:
    """查询单个会员近 days 天的折扣历史（次数 + 累计金额）。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    sql = text("""
        SELECT
            COUNT(o.id)                             AS discount_count,
            COALESCE(SUM(o.discount_amount_fen), 0) AS total_saved_fen
        FROM orders o
        WHERE o.customer_id = :member_id::uuid
          AND o.discount_amount_fen > 0
          AND o.created_at >= :since
          AND o.status NOT IN ('cancelled', 'refunded')
    """)
    try:
        result = await db.execute(sql, {"member_id": member_id, "since": since})
        row = result.mappings().one_or_none()
        if row:
            return {
                "discount_count": int(row["discount_count"]),
                "total_saved_fen": int(row["total_saved_fen"]),
            }
    except (SQLAlchemyError, ValueError) as exc:
        logger.warning("discount_guard.member_history_query_failed", member_id=member_id, error=str(exc))
    return {"discount_count": 0, "total_saved_fen": 0}


async def _query_suspicious_tables(
    db: AsyncSession,
    store_id: Optional[str],
    days: int,
    min_consecutive: int,
) -> list[dict]:
    """查询连续折扣异常桌台。

    逻辑：
    - 从 dining_sessions + orders 联合查询
    - 统计每张桌台在 days 内折扣订单出现的不同日期数（作为连续天数近似值）
    - 统计关联的 waiter_id（员工）及各自操作次数
    - 连续折扣日期数 >= min_consecutive 的桌台纳入预警
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    store_filter = "AND ds.store_id = :store_id" if store_id else ""

    sql = text(f"""
        SELECT
            ds.table_id::text                          AS table_id,
            COUNT(DISTINCT o.created_at::date)         AS consecutive_discount_days,
            COUNT(o.id)                                AS discount_count,
            AVG(CASE WHEN o.discount_amount_fen > 0
                     THEN o.discount_amount_fen::float / NULLIF(o.total_amount_fen, 0)
                     ELSE 0 END)                       AS avg_discount_rate,
            json_agg(DISTINCT o.waiter_id)
                FILTER (WHERE o.waiter_id IS NOT NULL) AS waiter_ids
        FROM dining_sessions ds
        JOIN orders o ON o.tenant_id = ds.tenant_id
            AND o.table_number = (
                SELECT t.table_no FROM tables t WHERE t.id = ds.table_id LIMIT 1
            )
        WHERE ds.opened_at >= :since
          AND o.discount_amount_fen > 0
          AND o.status NOT IN ('cancelled', 'refunded')
          {store_filter}
        GROUP BY ds.table_id
        HAVING COUNT(DISTINCT o.created_at::date) >= :min_consecutive
        ORDER BY COUNT(DISTINCT o.created_at::date) DESC
        LIMIT 100
    """)

    params: dict = {"since": since, "min_consecutive": min_consecutive}
    if store_id:
        params["store_id"] = store_id

    try:
        result = await db.execute(sql, params)
        rows = result.mappings().all()
    except SQLAlchemyError as exc:
        logger.error("discount_guard.table_pattern_query_failed", error=str(exc))
        return []

    tables = []
    for row in rows:
        consecutive_days = int(row["consecutive_discount_days"])
        discount_count = int(row["discount_count"])
        avg_rate = float(row["avg_discount_rate"] or 0)
        # 异常评分：综合连续天数和折扣率
        anomaly_score = min(0.99, (consecutive_days / max(days, 1)) * 0.6 + avg_rate * 0.4)

        waiter_ids = row["waiter_ids"] or []
        related_employees = [{"id": str(wid), "name": "", "count": discount_count} for wid in waiter_ids if wid]

        tables.append(
            {
                "table_id": row["table_id"],
                "table_name": f"桌台-{row['table_id'][:8]}",
                "consecutive_discount_days": consecutive_days,
                "discount_count": discount_count,
                "related_employees": related_employees,
                "anomaly_score": round(anomaly_score, 2),
                "note": f"该桌台{consecutive_days}天内出现{discount_count}次折扣，异常评分{anomaly_score:.2f}",
            }
        )
    return tables


async def _query_table_history(
    db: AsyncSession,
    table_id: str,
    days: int,
) -> Optional[dict]:
    """查询单个桌台近 days 天的折扣历史。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    sql = text("""
        SELECT
            COUNT(DISTINCT o.created_at::date)         AS consecutive_discount_days,
            COUNT(o.id)                                AS discount_count,
            AVG(CASE WHEN o.discount_amount_fen > 0
                     THEN o.discount_amount_fen::float / NULLIF(o.total_amount_fen, 0)
                     ELSE 0 END)                       AS avg_discount_rate,
            json_agg(DISTINCT o.waiter_id)
                FILTER (WHERE o.waiter_id IS NOT NULL) AS waiter_ids
        FROM dining_sessions ds
        JOIN orders o ON o.tenant_id = ds.tenant_id
            AND o.table_number = (
                SELECT t.table_no FROM tables t WHERE t.id = ds.table_id LIMIT 1
            )
        WHERE ds.table_id = :table_id::uuid
          AND ds.opened_at >= :since
          AND o.discount_amount_fen > 0
          AND o.status NOT IN ('cancelled', 'refunded')
    """)
    try:
        result = await db.execute(sql, {"table_id": table_id, "since": since})
        row = result.mappings().one_or_none()
        if row and int(row["discount_count"]) > 0:
            consecutive_days = int(row["consecutive_discount_days"])
            avg_rate = float(row["avg_discount_rate"] or 0)
            anomaly_score = min(0.99, (consecutive_days / max(days, 1)) * 0.6 + avg_rate * 0.4)
            waiter_ids = row["waiter_ids"] or []
            return {
                "table_id": table_id,
                "table_name": f"桌台-{table_id[:8]}",
                "consecutive_discount_days": consecutive_days,
                "discount_count": int(row["discount_count"]),
                "related_employees": [
                    {"id": str(wid), "name": "", "count": int(row["discount_count"])} for wid in waiter_ids if wid
                ],
                "anomaly_score": round(anomaly_score, 2),
            }
    except (SQLAlchemyError, ValueError) as exc:
        logger.warning("discount_guard.table_history_query_failed", table_id=table_id, error=str(exc))
    return None


# ─── Action 1: 会员折扣频率检测 ──────────────────────────────────────────────


@router.get("/member-frequency")
async def get_high_frequency_members(
    tenant_id: str = Query(..., description="租户ID"),
    store_id: Optional[str] = Query(None, description="门店ID（空=全品牌）"),
    days: int = Query(30, ge=1, le=180, description="统计窗口（天）"),
    threshold: int = Query(3, ge=1, le=20, description="频率阈值（次）"),
) -> dict:
    """查询高频折扣会员列表。

    同一会员在 `days` 天内折扣次数 ≥ threshold 即纳入预警。
    风险等级：
      low    — count < threshold（在正常范围内，仍返回以便参考）
      medium — count 在 threshold 到 2× threshold 之间
      high   — count > 2× threshold
    """
    _LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}

    async for db in get_db_with_tenant(tenant_id):
        suspicious = await _query_high_freq_members(db, store_id, days, threshold)

    suspicious.sort(key=lambda x: _LEVEL_ORDER.get(x["risk_level"], 9))

    total_amount_fen = sum(m["total_saved_fen"] for m in suspicious)

    logger.info(
        "member_frequency_scan",
        tenant_id=tenant_id,
        store_id=store_id,
        days=days,
        threshold=threshold,
        suspicious_count=len(suspicious),
    )

    return {
        "ok": True,
        "data": {
            "high_frequency_members": suspicious,
            "risk_levels": {"low": "< threshold", "medium": "threshold-2×", "high": "> 2×"},
            "summary": {
                "total_suspicious": len(suspicious),
                "total_amount_saved_fen": total_amount_fen,
                "window_days": days,
                "threshold": threshold,
                "store_id": store_id or "all",
                "as_of": date.today().isoformat(),
            },
        },
    }


@router.post("/member-frequency/check")
async def check_member_frequency_realtime(
    body: MemberFrequencyCheckRequest,
    tenant_id: str = Query(..., description="租户ID"),
    days: int = Query(30, ge=1, le=180, description="回溯窗口（天）"),
    threshold: int = Query(3, ge=1, le=20, description="频率阈值（次）"),
) -> dict:
    """实时检查单笔折扣是否触发频率预警。

    查询该会员近 `days` 天折扣历史，叠加本次，判断是否超阈值。
    用于 POS 下单时实时拦截/提醒。
    """
    async for db in get_db_with_tenant(tenant_id):
        history = await _query_member_history(db, body.member_id, days)

    history_count: int = history["discount_count"]
    history_saved_fen: int = history["total_saved_fen"]

    # 本次叠加
    new_count = history_count + 1
    new_total_fen = history_saved_fen + body.discount_amount_fen

    risk_level = _calc_risk_level(new_count, threshold)
    is_suspicious = new_count >= threshold
    recommendation = _make_recommendation(risk_level, new_count, new_total_fen)

    reason = (
        f"该会员{days}天内已享受{history_count}次折扣，"
        f"累计减免¥{history_saved_fen / 100:.0f}，"
        f"本次为第{new_count}次，{'超出品牌阈值' if is_suspicious else '仍在正常范围内'}"
    )

    # 决策留痕
    decision = DiscountGuardDecision(
        decision_type="member_frequency_check",
        input_context={
            "member_id": body.member_id,
            "order_id": body.order_id,
            "discount_type": body.discount_type,
            "discount_amount_fen": body.discount_amount_fen,
            "tenant_id": tenant_id,
            "days_window": days,
            "threshold": threshold,
        },
        reasoning=reason,
        output_action={
            "is_suspicious": is_suspicious,
            "risk_level": risk_level,
            "recommendation": recommendation,
        },
        constraints_check=_build_constraints_check(body.discount_amount_fen, is_suspicious),
        confidence=0.92 if history_count > 0 else 0.75,
        created_at=datetime.now(timezone.utc),
    )
    _record_decision(decision)

    logger.info(
        "member_frequency_realtime_check",
        member_id=body.member_id,
        order_id=body.order_id,
        history_count=history_count,
        new_count=new_count,
        risk_level=risk_level,
        is_suspicious=is_suspicious,
    )

    return {
        "ok": True,
        "data": {
            "member_id": body.member_id,
            "order_id": body.order_id,
            "is_suspicious": is_suspicious,
            "frequency_in_window": new_count,
            "history_count": history_count,
            "total_saved_fen": new_total_fen,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "reason": reason,
            "window_days": days,
            "threshold": threshold,
            "decision_id": str(uuid.uuid4()),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ─── Action 2: 客位连续折扣预警 ──────────────────────────────────────────────


@router.get("/table-pattern")
async def get_suspicious_table_patterns(
    tenant_id: str = Query(..., description="租户ID"),
    store_id: Optional[str] = Query(None, description="门店ID（空=全品牌）"),
    days: int = Query(7, ge=1, le=30, description="统计窗口（天）"),
    min_consecutive: int = Query(2, ge=2, le=14, description="最小连续天数"),
) -> dict:
    """查询连续折扣异常的桌台列表。

    同一桌台在 `days` 内连续出现折扣且天数 ≥ min_consecutive，
    可能是内部员工为熟人/关系户长期优惠。
    """
    async for db in get_db_with_tenant(tenant_id):
        suspicious = await _query_suspicious_tables(db, store_id, days, min_consecutive)

    suspicious.sort(key=lambda x: x["anomaly_score"], reverse=True)

    total_tables = len(suspicious)
    avg_discount = sum(t["discount_count"] for t in suspicious) / total_tables if total_tables > 0 else 0
    suspicious_rate = round(total_tables / max(total_tables, 1) * 100, 1) if total_tables > 0 else 0.0

    logger.info(
        "table_pattern_scan",
        tenant_id=tenant_id,
        store_id=store_id,
        days=days,
        min_consecutive=min_consecutive,
        suspicious_count=len(suspicious),
    )

    return {
        "ok": True,
        "data": {
            "suspicious_tables": suspicious,
            "pattern_analysis": {
                "avg_discount_per_table": round(avg_discount, 1),
                "suspicious_rate": suspicious_rate,
                "window_days": days,
                "min_consecutive": min_consecutive,
                "store_id": store_id or "all",
                "as_of": date.today().isoformat(),
            },
        },
    }


@router.post("/table-pattern/analyze")
async def analyze_table_pattern_realtime(
    body: TablePatternAnalyzeRequest,
    tenant_id: str = Query(..., description="租户ID"),
    days: int = Query(7, ge=1, le=30, description="统计窗口（天）"),
) -> dict:
    """实时分析本次折扣是否延续了该桌台的异常模式。

    结合历史数据，判断：
    - 是否已有连续折扣记录
    - 是否总是同一员工操作
    - 综合给出 alert_level: none / warning / critical
    """
    async for db in get_db_with_tenant(tenant_id):
        existing_table = await _query_table_history(db, body.table_id, days)

    if existing_table is None:
        # 首次出现：无历史记录，低风险
        is_pattern_match = False
        consecutive_days = 0
        related_employees: list[dict] = []
        alert_level = "none"
        alert_message = "该桌台无历史异常折扣记录，本次折扣正常记录。"
        anomaly_score = 0.0
        confidence = 0.85
    else:
        consecutive_days = existing_table["consecutive_discount_days"]
        raw_employees = existing_table["related_employees"]

        # 将 related_employees 转换为统一格式
        related_employees = [
            {
                "employee_id": e["id"],
                "employee_name": e.get("name", ""),
                "discount_count": e["count"],
            }
            for e in raw_employees
        ]

        # 判断当前员工是否是惯常操作者
        is_same_employee = any(e["id"] == body.employee_id for e in raw_employees)
        anomaly_score = existing_table["anomaly_score"]

        # 模式匹配：连续天数 ≥ 3 且是同一员工 → critical；连续天数 ≥ 2 → warning
        table_name = existing_table.get("table_name", body.table_id)
        if consecutive_days >= 3 and is_same_employee:
            is_pattern_match = True
            alert_level = "critical"
            alert_message = (
                f"高度异常！{table_name}已连续{consecutive_days}天出现折扣，"
                f"且本次仍由同一员工操作，强烈建议上报管理层审查。"
            )
        elif consecutive_days >= 2:
            is_pattern_match = True
            alert_level = "warning"
            alert_message = (
                f"注意：{table_name}近期已连续{consecutive_days}天出现折扣，本次折扣已延续该模式，请主管确认是否合规。"
            )
        else:
            is_pattern_match = False
            alert_level = "none"
            alert_message = "连续折扣天数未达预警阈值，正常放行。"

        confidence = min(0.99, 0.70 + anomaly_score * 0.3)

    # 决策留痕
    decision = DiscountGuardDecision(
        decision_type="table_pattern_analyze",
        input_context={
            "table_id": body.table_id,
            "order_id": body.order_id,
            "employee_id": body.employee_id,
            "discount_amount_fen": body.discount_amount_fen,
            "tenant_id": tenant_id,
        },
        reasoning=(
            f"桌台{body.table_id}历史连续折扣天数={consecutive_days}，"
            f"员工{body.employee_id}是否为惯常操作者="
            f"{any(e.get('employee_id') == body.employee_id for e in related_employees)}，"
            f"异常评分={anomaly_score:.2f}"
        ),
        output_action={
            "is_pattern_match": is_pattern_match,
            "alert_level": alert_level,
            "alert_message": alert_message,
        },
        constraints_check=_build_constraints_check(body.discount_amount_fen, is_pattern_match),
        confidence=confidence,
        created_at=datetime.now(timezone.utc),
    )
    _record_decision(decision)

    logger.info(
        "table_pattern_realtime_analyze",
        table_id=body.table_id,
        order_id=body.order_id,
        employee_id=body.employee_id,
        consecutive_days=consecutive_days,
        alert_level=alert_level,
        is_pattern_match=is_pattern_match,
    )

    return {
        "ok": True,
        "data": {
            "table_id": body.table_id,
            "order_id": body.order_id,
            "is_pattern_match": is_pattern_match,
            "consecutive_discount_days": consecutive_days,
            "anomaly_score": anomaly_score,
            "related_employees": related_employees,
            "alert_level": alert_level,
            "alert_message": alert_message,
            "decision_id": str(uuid.uuid4()),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ─── 汇总统计 ────────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_discount_guard_summary(
    tenant_id: str = Query(..., description="租户ID"),
    store_id: Optional[str] = Query(None, description="门店ID（空=全品牌）"),
) -> dict:
    """折扣守护汇总统计：今日/本周/本月检查与拦截情况。

    实时会话数据来自内存决策日志；周期统计从 DB 聚合。
    TOP3 高风险员工和桌台来自 DB 查询（7天窗口）。
    """
    # 从决策日志中统计真实数据
    member_checks = [d for d in _DECISION_LOGS if d["decision_type"] == "member_frequency_check"]
    table_analyzes = [d for d in _DECISION_LOGS if d["decision_type"] == "table_pattern_analyze"]

    total_checks = len(member_checks) + len(table_analyzes)
    member_alerts = sum(1 for d in member_checks if d["output_action"].get("is_suspicious"))
    table_alerts = sum(1 for d in table_analyzes if d["output_action"].get("is_pattern_match"))
    total_alerts = member_alerts + table_alerts

    # 节省金额估算（拦截的异常折扣金额）
    intercepted_fen = sum(
        d["input_context"].get("discount_amount_fen", 0)
        for d in member_checks
        if d["output_action"].get("is_suspicious")
    )

    # TOP3 高风险桌台（从 DB 查 7 天）
    async for db in get_db_with_tenant(tenant_id):
        top_tables_raw = await _query_suspicious_tables(db, store_id, 7, 2)

    top3_tables = sorted(top_tables_raw, key=lambda x: x["anomaly_score"], reverse=True)[:3]

    # TOP3 高风险员工（从桌台异常模式中提取）
    employee_counter: dict[str, dict] = {}
    for table in top_tables_raw:
        for emp in table["related_employees"]:
            eid = emp["id"]
            if eid not in employee_counter:
                employee_counter[eid] = {
                    "employee_id": eid,
                    "name": emp.get("name", ""),
                    "suspicious_operations": 0,
                }
            employee_counter[eid]["suspicious_operations"] += emp["count"]

    top3_employees = sorted(
        employee_counter.values(),
        key=lambda x: x["suspicious_operations"],
        reverse=True,
    )[:3]

    today_str = date.today().isoformat()
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    month_start = date.today().replace(day=1).isoformat()

    # DB 周期聚合
    period_stats: dict = {}
    try:
        async for db in get_db_with_tenant(tenant_id):
            store_filter = "AND store_id = :store_id::uuid" if store_id else ""
            for period_key, period_start_str in [
                ("today", today_str),
                ("this_week", week_start),
                ("this_month", month_start),
            ]:
                sql = text(f"""
                    SELECT
                        COUNT(id)                                  AS checks,
                        COUNT(id) FILTER (WHERE discount_amount_fen > 0) AS alerts,
                        COALESCE(SUM(discount_amount_fen), 0)      AS intercepted_fen
                    FROM orders
                    WHERE created_at >= :period_start
                      AND status NOT IN ('cancelled', 'refunded')
                      AND discount_amount_fen > 0
                      {store_filter}
                """)
                params: dict = {"period_start": period_start_str}
                if store_id:
                    params["store_id"] = store_id
                result = await db.execute(sql, params)
                row = result.mappings().one_or_none()
                period_stats[period_key] = {
                    "checks": int(row["checks"]) if row else 0,
                    "alerts": int(row["alerts"]) if row else 0,
                    "intercepted_fen": int(row["intercepted_fen"]) if row else 0,
                }
    except SQLAlchemyError as exc:
        logger.warning("discount_guard.summary_period_query_failed", error=str(exc))
        period_stats = {
            "today": {"checks": 0, "alerts": 0, "intercepted_fen": 0},
            "this_week": {"checks": 0, "alerts": 0, "intercepted_fen": 0},
            "this_month": {"checks": 0, "alerts": 0, "intercepted_fen": 0},
        }

    return {
        "ok": True,
        "data": {
            "realtime_session": {
                "total_checks": total_checks,
                "total_alerts": total_alerts,
                "member_alerts": member_alerts,
                "table_alerts": table_alerts,
                "intercepted_amount_fen": intercepted_fen,
            },
            "today": {
                "period": today_str,
                **period_stats.get("today", {}),
            },
            "this_week": {
                "period_start": week_start,
                **period_stats.get("this_week", {}),
            },
            "this_month": {
                "period_start": month_start,
                **period_stats.get("this_month", {}),
            },
            "top3_risky_employees": top3_employees,
            "top3_risky_tables": [
                {
                    "table_id": t["table_id"],
                    "table_name": t["table_name"],
                    "anomaly_score": t["anomaly_score"],
                    "consecutive_days": t["consecutive_discount_days"],
                }
                for t in top3_tables
            ],
            "store_id": store_id or "all",
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    }


# ─── 决策日志查询（运营审计用）──────────────────────────────────────────────


@router.get("/decisions")
async def list_decision_logs(
    tenant_id: str = Query(..., description="租户ID"),
    decision_type: Optional[str] = Query(None, description="过滤类型：member_frequency_check / table_pattern_analyze"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
) -> dict:
    """查询 Agent 决策日志（调试与合规审计）。"""
    logs = _DECISION_LOGS.copy()
    if decision_type:
        logs = [d for d in logs if d["decision_type"] == decision_type]

    # 最新的在前
    logs = list(reversed(logs[-limit:]))

    return {
        "ok": True,
        "data": {
            "items": logs,
            "total": len(logs),
            "filter_type": decision_type or "all",
        },
    }
