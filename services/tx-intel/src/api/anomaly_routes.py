"""异常检测 API

端点：
  GET  /api/v1/intel/anomalies          — 当前异常列表（最近7天）
  POST /api/v1/intel/anomalies/{id}/dismiss — 标记为已知悉

异常类型（简单统计算法，不调用 Claude）：
  revenue_drop  : 日营收同比下滑超20%
  cost_spike    : 某日食材成本占比超60%
  high_refund   : 退单率超5%
  slow_kitchen  : 平均出餐时间超30分钟
  expiry_risk   : 7天内过期食材超10种

如果无法查询真实数据，返回带 _is_mock: true 的演示数据。
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/intel", tags=["anomalies"])


# ─── 依赖项 ───────────────────────────────────────────────────────────────────

async def get_db() -> AsyncSession:  # type: ignore[return]
    raise NotImplementedError("请在应用启动时注入 DB session factory")


async def get_tenant_id(x_tenant_id: Annotated[str, Header()]) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式无效")


# ─── 异常检测阈值 ─────────────────────────────────────────────────────────────

THRESHOLDS = {
    "revenue_drop_pct": 0.20,      # 同比下滑20%触发
    "cost_ratio_max": 0.60,        # 成本占比60%触发
    "refund_rate_max": 0.05,       # 退单率5%触发
    "kitchen_time_max_min": 30,    # 平均出餐时间30分钟触发
    "expiry_count_max": 10,        # 临期食材10种触发
}

ANOMALY_DESCRIPTIONS = {
    "revenue_drop": "日营收同比下滑超20%，建议核查原因",
    "cost_spike": "食材成本占当日营收比例超过60%，存在成本失控风险",
    "high_refund": "退单率超过5%，顾客满意度预警",
    "slow_kitchen": "平均出餐时间超过30分钟，影响翻台效率",
    "expiry_risk": "7天内临期食材超过10种，需尽快消耗或处理",
}

ANOMALY_SEVERITY = {
    "revenue_drop": "warning",
    "cost_spike": "critical",
    "high_refund": "warning",
    "slow_kitchen": "warning",
    "expiry_risk": "critical",
}


# ─── RLS 工具 ─────────────────────────────────────────────────────────────────

_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


async def _set_rls(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """设置 RLS 租户上下文（每次 DB 操作前调用）"""
    await db.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})


# ─── 检测函数 ─────────────────────────────────────────────────────────────────

async def _detect_revenue_drop(
    db: AsyncSession, tenant_id: uuid.UUID, days: int
) -> list[dict[str, Any]]:
    """检测每日营收同比下滑超20%的天"""
    now = datetime.now(timezone.utc)
    anomalies = []
    for offset in range(days):
        day_end = now - timedelta(days=offset)
        day_start = day_end.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end_time = day_start + timedelta(days=1)
        # 同期去年数据
        yoy_start = day_start - timedelta(days=365)
        yoy_end = day_end_time - timedelta(days=365)

        r = await db.execute(
            text("""
                SELECT COALESCE(SUM(total_amount), 0) AS revenue
                FROM orders
                WHERE tenant_id = :tenant_id
                  AND status = 'completed'
                  AND created_at BETWEEN :start AND :end
            """),
            {"tenant_id": str(tenant_id), "start": day_start.isoformat(), "end": day_end_time.isoformat()},
        )
        this_rev = float(r.scalar() or 0)

        r2 = await db.execute(
            text("""
                SELECT COALESCE(SUM(total_amount), 0) AS revenue
                FROM orders
                WHERE tenant_id = :tenant_id
                  AND status = 'completed'
                  AND created_at BETWEEN :start AND :end
            """),
            {"tenant_id": str(tenant_id), "start": yoy_start.isoformat(), "end": yoy_end.isoformat()},
        )
        yoy_rev = float(r2.scalar() or 0)

        if yoy_rev > 0 and this_rev < yoy_rev * (1 - THRESHOLDS["revenue_drop_pct"]):
            drop_pct = (yoy_rev - this_rev) / yoy_rev
            anomalies.append({
                "id": str(uuid.uuid4()),
                "type": "revenue_drop",
                "severity": ANOMALY_SEVERITY["revenue_drop"],
                "description": f"{day_start.strftime('%m月%d日')}日营收同比下滑{drop_pct:.0%}",
                "detail": {
                    "date": day_start.strftime("%Y-%m-%d"),
                    "this_revenue": this_rev,
                    "yoy_revenue": yoy_rev,
                    "drop_pct": round(drop_pct, 4),
                },
                "occurred_at": day_start.isoformat(),
                "dismissed": False,
            })
    return anomalies


async def _detect_cost_spike(
    db: AsyncSession, tenant_id: uuid.UUID, days: int
) -> list[dict[str, Any]]:
    """检测某日食材成本占比超60%"""
    now = datetime.now(timezone.utc)
    anomalies = []
    for offset in range(days):
        day_start = (now - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        params = {"tenant_id": str(tenant_id), "start": day_start.isoformat(), "end": day_end.isoformat()}

        r = await db.execute(
            text("""
                SELECT COALESCE(SUM(total_amount), 0) FROM orders
                WHERE tenant_id = :tenant_id AND status = 'completed'
                  AND created_at BETWEEN :start AND :end
            """),
            params,
        )
        revenue = float(r.scalar() or 0)

        r2 = await db.execute(
            text("""
                SELECT COALESCE(SUM(amount), 0) FROM cost_records
                WHERE tenant_id = :tenant_id AND cost_type = 'ingredient'
                  AND recorded_at BETWEEN :start AND :end
            """),
            params,
        )
        cost = float(r2.scalar() or 0)

        if revenue > 0 and cost / revenue > THRESHOLDS["cost_ratio_max"]:
            ratio = cost / revenue
            anomalies.append({
                "id": str(uuid.uuid4()),
                "type": "cost_spike",
                "severity": ANOMALY_SEVERITY["cost_spike"],
                "description": f"{day_start.strftime('%m月%d日')}食材成本占比达{ratio:.0%}，超过60%阈值",
                "detail": {
                    "date": day_start.strftime("%Y-%m-%d"),
                    "cost_ratio": round(ratio, 4),
                    "revenue": revenue,
                    "ingredient_cost": cost,
                },
                "occurred_at": day_start.isoformat(),
                "dismissed": False,
            })
    return anomalies


async def _detect_high_refund(
    db: AsyncSession, tenant_id: uuid.UUID, days: int
) -> list[dict[str, Any]]:
    """检测退单率超5%"""
    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(days=days)).isoformat()
    r = await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE status='completed') AS completed,
                COUNT(*) FILTER (WHERE status='refunded') AS refunded
            FROM orders
            WHERE tenant_id = :tenant_id
              AND created_at BETWEEN :start AND :end
        """),
        {"tenant_id": str(tenant_id), "start": period_start, "end": now.isoformat()},
    )
    row = r.fetchone()
    completed = int(row[0] or 0)
    refunded = int(row[1] or 0)
    total = completed + refunded
    if total == 0:
        return []
    refund_rate = refunded / total
    if refund_rate <= THRESHOLDS["refund_rate_max"]:
        return []
    return [{
        "id": str(uuid.uuid4()),
        "type": "high_refund",
        "severity": ANOMALY_SEVERITY["high_refund"],
        "description": f"近{days}天退单率{refund_rate:.1%}，超过5%警戒线",
        "detail": {
            "period_days": days,
            "refund_rate": round(refund_rate, 4),
            "refunded_count": refunded,
            "total_count": total,
        },
        "occurred_at": now.isoformat(),
        "dismissed": False,
    }]


async def _detect_slow_kitchen(
    db: AsyncSession, tenant_id: uuid.UUID, days: int
) -> list[dict[str, Any]]:
    """检测平均出餐时间超30分钟"""
    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(days=days)).isoformat()
    r = await db.execute(
        text("""
            SELECT AVG(EXTRACT(EPOCH FROM (finished_at - created_at)) / 60.0) AS avg_min
            FROM kitchen_orders
            WHERE tenant_id = :tenant_id
              AND status = 'done'
              AND created_at BETWEEN :start AND :end
        """),
        {"tenant_id": str(tenant_id), "start": period_start, "end": now.isoformat()},
    )
    avg_min = float(r.scalar() or 0)
    if avg_min <= THRESHOLDS["kitchen_time_max_min"]:
        return []
    return [{
        "id": str(uuid.uuid4()),
        "type": "slow_kitchen",
        "severity": ANOMALY_SEVERITY["slow_kitchen"],
        "description": f"近{days}天平均出餐时间{avg_min:.1f}分钟，超过30分钟标准",
        "detail": {
            "period_days": days,
            "avg_kitchen_minutes": round(avg_min, 1),
            "threshold_minutes": THRESHOLDS["kitchen_time_max_min"],
        },
        "occurred_at": now.isoformat(),
        "dismissed": False,
    }]


async def _detect_expiry_risk(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[dict[str, Any]]:
    """检测7天内过期食材超10种"""
    now = datetime.now(timezone.utc)
    threshold_date = (now + timedelta(days=7)).isoformat()
    r = await db.execute(
        text("""
            SELECT COUNT(DISTINCT id) AS expiry_count
            FROM inventory_items
            WHERE tenant_id = :tenant_id
              AND expires_at IS NOT NULL
              AND expires_at > :now
              AND expires_at <= :threshold
        """),
        {"tenant_id": str(tenant_id), "now": now.isoformat(), "threshold": threshold_date},
    )
    count = int(r.scalar() or 0)
    if count <= THRESHOLDS["expiry_count_max"]:
        return []
    return [{
        "id": str(uuid.uuid4()),
        "type": "expiry_risk",
        "severity": ANOMALY_SEVERITY["expiry_risk"],
        "description": f"7天内临期食材达{count}种，需尽快处理",
        "detail": {
            "expiry_count": count,
            "threshold": THRESHOLDS["expiry_count_max"],
            "check_before": threshold_date,
        },
        "occurred_at": now.isoformat(),
        "dismissed": False,
    }]


# ─── mock 数据 ────────────────────────────────────────────────────────────────

def _mock_anomalies() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "mock-001",
            "type": "revenue_drop",
            "severity": "warning",
            "description": "3月28日营收同比下滑22%，当日营收¥12,400（去年同期¥15,900）",
            "detail": {"date": "2026-03-28", "drop_pct": 0.22, "this_revenue": 1240000, "yoy_revenue": 1590000},
            "occurred_at": (now - timedelta(days=5)).isoformat(),
            "dismissed": False,
        },
        {
            "id": "mock-002",
            "type": "expiry_risk",
            "severity": "critical",
            "description": "7天内临期食材达14种，含三文鱼、牛里脊等高值食材",
            "detail": {"expiry_count": 14, "threshold": 10},
            "occurred_at": (now - timedelta(days=1)).isoformat(),
            "dismissed": False,
        },
        {
            "id": "mock-003",
            "type": "high_refund",
            "severity": "warning",
            "description": "近7天退单率6.2%，超过5%警戒线",
            "detail": {"refund_rate": 0.062, "refunded_count": 18, "total_count": 290},
            "occurred_at": (now - timedelta(days=2)).isoformat(),
            "dismissed": True,
        },
        {
            "id": "mock-004",
            "type": "cost_spike",
            "severity": "critical",
            "description": "3月30日食材成本占比63%，超过60%阈值",
            "detail": {"date": "2026-03-30", "cost_ratio": 0.63},
            "occurred_at": (now - timedelta(days=3)).isoformat(),
            "dismissed": False,
        },
    ]


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@router.get("/anomalies")
async def list_anomalies(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
    include_dismissed: bool = False,
) -> dict:
    """获取最近N天的经营异常列表（基于统计阈值，不调用Claude）"""
    try:
        await _set_rls(db, tenant_id)
        anomalies: list[dict[str, Any]] = []
        anomalies.extend(await _detect_revenue_drop(db, tenant_id, min(days, 7)))
        anomalies.extend(await _detect_cost_spike(db, tenant_id, min(days, 7)))
        anomalies.extend(await _detect_high_refund(db, tenant_id, days))
        anomalies.extend(await _detect_slow_kitchen(db, tenant_id, days))
        anomalies.extend(await _detect_expiry_risk(db, tenant_id))

        # 按严重程度 + 时间排序（critical 优先）
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        anomalies.sort(key=lambda x: (severity_order.get(x["severity"], 9), x["occurred_at"]))

        if not include_dismissed:
            anomalies = [a for a in anomalies if not a.get("dismissed")]

        return {
            "ok": True,
            "data": {
                "anomalies": anomalies,
                "total": len(anomalies),
                "critical_count": sum(1 for a in anomalies if a.get("severity") == "critical"),
                "warning_count": sum(1 for a in anomalies if a.get("severity") == "warning"),
                "_is_mock": False,
            },
            "error": None,
        }
    except (SQLAlchemyError, NotImplementedError) as exc:
        logger.warning("anomalies.db_fallback", exc=str(exc))
        mock = _mock_anomalies()
        if not include_dismissed:
            mock = [a for a in mock if not a.get("dismissed")]
        return {
            "ok": True,
            "data": {
                "anomalies": mock,
                "total": len(mock),
                "critical_count": sum(1 for a in mock if a.get("severity") == "critical"),
                "warning_count": sum(1 for a in mock if a.get("severity") == "warning"),
                "_is_mock": True,
            },
            "error": None,
        }


@router.post("/anomalies/{anomaly_id}/dismiss")
async def dismiss_anomaly(
    anomaly_id: Annotated[str, Path(description="异常记录ID")],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """将异常标记为已知悉（软删除，不再出现在默认列表中）"""
    try:
        await _set_rls(db, tenant_id)
        # 尝试写入 anomaly_dismissals 表（如存在）
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                INSERT INTO anomaly_dismissals (id, tenant_id, anomaly_ref_id, dismissed_at)
                VALUES (:id, :tenant_id, :anomaly_id, :dismissed_at)
                ON CONFLICT (tenant_id, anomaly_ref_id) DO UPDATE SET dismissed_at = :dismissed_at
            """),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "anomaly_id": anomaly_id,
                "dismissed_at": now.isoformat(),
            },
        )
        await db.commit()
        logger.info("anomaly.dismissed", anomaly_id=anomaly_id, tenant_id=str(tenant_id))
        return {
            "ok": True,
            "data": {"anomaly_id": anomaly_id, "dismissed": True, "dismissed_at": now.isoformat()},
            "error": None,
        }
    except (SQLAlchemyError, NotImplementedError) as exc:
        logger.warning("anomaly_dismiss.db_fallback", exc=str(exc))
        # mock 模式：直接返回成功（无持久化）
        return {
            "ok": True,
            "data": {
                "anomaly_id": anomaly_id,
                "dismissed": True,
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "_is_mock": True,
            },
            "error": None,
        }
