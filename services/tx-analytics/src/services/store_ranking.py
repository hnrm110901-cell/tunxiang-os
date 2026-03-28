"""门店排行 — 多维度排名与跨店对比

支持指标：revenue / margin / turnover / satisfaction
支持正序/倒序排列。
金额单位：分(fen)。
"""
import structlog
from typing import Optional

log = structlog.get_logger()

# 支持的排行指标
VALID_METRICS = {"revenue", "margin", "turnover", "satisfaction"}

# 支持的日期范围
VALID_DATE_RANGES = {"today", "week", "month", "quarter"}


# ─── 纯函数：计算与均值的偏差百分比 ───

def calc_vs_avg_pct(value: float, avg: float) -> Optional[float]:
    """计算与均值偏差百分比"""
    if avg <= 0:
        return None
    return round((value - avg) / avg * 100, 1)


def determine_trend(values: list[float]) -> str:
    """根据最近数据点判断趋势

    Args:
        values: 时间序列值（从旧到新）

    Returns:
        up / down / flat
    """
    if len(values) < 2:
        return "flat"
    recent = values[-1]
    prev = values[-2]
    if recent > prev * 1.02:
        return "up"
    if recent < prev * 0.98:
        return "down"
    return "flat"


# ─── 门店排行 ───

async def get_store_ranking(
    metric: str,
    date_range: str,
    tenant_id: str,
    db,
    ascending: bool = False,
) -> list[dict]:
    """门店排行榜

    Args:
        metric: revenue / margin / turnover / satisfaction
        date_range: today / week / month / quarter
        tenant_id: 租户ID
        db: 数据库连接
        ascending: True=正序(低到高), False=倒序(高到低, 默认)

    Returns:
        [{rank, store_id, store_name, value, vs_avg_pct, trend}]

    Raises:
        ValueError: metric 或 date_range 不合法
    """
    if metric not in VALID_METRICS:
        raise ValueError(f"invalid metric: {metric}, must be one of {VALID_METRICS}")
    if date_range not in VALID_DATE_RANGES:
        raise ValueError(f"invalid date_range: {date_range}, must be one of {VALID_DATE_RANGES}")

    log.info(
        "get_store_ranking",
        metric=metric,
        date_range=date_range,
        tenant_id=tenant_id,
        ascending=ascending,
    )

    raw = await _query_ranking_data(db, metric, date_range, tenant_id)

    if not raw:
        return []

    # 计算均值
    values = [item["value"] for item in raw]
    avg = sum(values) / len(values) if values else 0

    # 排序
    raw.sort(key=lambda x: x["value"], reverse=not ascending)

    # 组装结果
    results = []
    for idx, item in enumerate(raw):
        results.append({
            "rank": idx + 1,
            "store_id": item["store_id"],
            "store_name": item["store_name"],
            "value": item["value"],
            "vs_avg_pct": calc_vs_avg_pct(item["value"], avg),
            "trend": item.get("trend", "flat"),
        })

    return results


# ─── 多店多指标对比 ───

async def get_store_comparison(
    store_ids: list[str],
    metrics: list[str],
    date_range: str,
    tenant_id: str,
    db,
) -> dict:
    """多店多指标对比

    Args:
        store_ids: 要对比的门店ID列表
        metrics: 要对比的指标列表
        date_range: 日期范围
        tenant_id: 租户ID
        db: 数据库连接

    Returns:
        {
            stores: [{store_id, store_name}],
            metrics: {
                "revenue": [{store_id, value, rank}],
                "margin": [{store_id, value, rank}],
                ...
            }
        }
    """
    for m in metrics:
        if m not in VALID_METRICS:
            raise ValueError(f"invalid metric: {m}")
    if date_range not in VALID_DATE_RANGES:
        raise ValueError(f"invalid date_range: {date_range}")

    log.info(
        "get_store_comparison",
        store_ids=store_ids,
        metrics=metrics,
        date_range=date_range,
        tenant_id=tenant_id,
    )

    # 查询门店基本信息
    stores_info = await _query_stores_info(db, store_ids, tenant_id)

    # 每个指标分别查询排行
    metric_data = {}
    for m in metrics:
        raw = await _query_ranking_data(db, m, date_range, tenant_id)
        # 过滤出目标门店
        filtered = [item for item in raw if item["store_id"] in store_ids]
        filtered.sort(key=lambda x: x["value"], reverse=True)
        metric_data[m] = [
            {"store_id": item["store_id"], "value": item["value"], "rank": idx + 1}
            for idx, item in enumerate(filtered)
        ]

    return {
        "stores": stores_info,
        "date_range": date_range,
        "metrics": metric_data,
    }


# ─── 数据库查询（桩函数） ───

async def _query_ranking_data(
    db, metric: str, date_range: str, tenant_id: str
) -> list[dict]:
    """查询排行原始数据"""
    if db is None:
        # Mock 数据
        mock = [
            {"store_id": "store-001", "store_name": "芙蓉路店", "value": 856000, "trend": "up"},
            {"store_id": "store-002", "store_name": "五一广场店", "value": 1023000, "trend": "up"},
            {"store_id": "store-003", "store_name": "万达店", "value": 678000, "trend": "down"},
            {"store_id": "store-004", "store_name": "梅溪湖店", "value": 920000, "trend": "flat"},
        ]
        return mock

    # 根据不同 metric 构造不同 SQL
    metric_sql = {
        "revenue": "COALESCE(SUM(o.total_fen), 0)",
        "margin": "COALESCE(AVG(o.margin_pct), 0)",
        "turnover": "COALESCE(COUNT(DISTINCT o.table_id)::float / NULLIF(s.total_tables, 0), 0)",
        "satisfaction": "COALESCE(AVG(o.satisfaction_score), 0)",
    }

    query = f"""
        SELECT s.store_id, s.store_name,
               {metric_sql[metric]} AS value
        FROM stores s
        LEFT JOIN orders o ON o.store_id = s.store_id
            AND o.tenant_id = :tenant_id
            AND o.is_deleted = FALSE
        WHERE s.tenant_id = :tenant_id
          AND s.is_deleted = FALSE
        GROUP BY s.store_id, s.store_name
    """
    row = await db.execute(query, {"tenant_id": tenant_id})
    results = []
    for r in row.mappings().all():
        results.append({
            "store_id": r["store_id"],
            "store_name": r["store_name"],
            "value": float(r["value"]),
            "trend": "flat",
        })
    return results


async def _query_stores_info(
    db, store_ids: list[str], tenant_id: str
) -> list[dict]:
    """查询门店基本信息"""
    if db is None:
        name_map = {
            "store-001": "芙蓉路店",
            "store-002": "五一广场店",
            "store-003": "万达店",
            "store-004": "梅溪湖店",
        }
        return [
            {"store_id": sid, "store_name": name_map.get(sid, sid)}
            for sid in store_ids
        ]

    row = await db.execute(
        """
        SELECT store_id, store_name
        FROM stores
        WHERE tenant_id = :tenant_id
          AND store_id = ANY(:store_ids)
          AND is_deleted = FALSE
        """,
        {"tenant_id": tenant_id, "store_ids": store_ids},
    )
    return [dict(r) for r in row.mappings().all()]
