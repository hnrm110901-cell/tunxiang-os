"""全渠道订单统一查询（Y-A12 骨架）

合并：
  - ``orders``：堂食 / 小程序 / 已落库的 omni 单等
  - ``delivery_orders``：仅 **未** 关联 ``orders.id`` 的外卖行（避免与 omni 落库重复）
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_STATUS_TOKENS = 15
_STATUS_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_CHANNEL_KEY_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")


def _parse_status_filter(raw: Optional[str]) -> Optional[list[str]]:
    """逗号分隔状态列表，小写化；用于参数化 SQL IN，禁止注入。"""
    if raw is None or not str(raw).strip():
        return None
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw).split(","):
        p = part.strip().lower()
        if not p:
            continue
        if len(out) >= _MAX_STATUS_TOKENS:
            raise ValueError(f"status 最多 {_MAX_STATUS_TOKENS} 项")
        if not _STATUS_TOKEN_RE.match(p):
            raise ValueError(f"非法 status: {part.strip()!r}")
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out or None


def _parse_channel_key_filter(raw: Optional[str]) -> Optional[str]:
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip()
    if not _CHANNEL_KEY_RE.match(s):
        raise ValueError("channel_key 仅允许字母数字与 ._-，长度 1–80")
    return s


def _validate_uuid_str(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} 须为合法 UUID") from exc


async def list_unified_orders(
    db: AsyncSession,
    tenant_id: str,
    *,
    date_from: date,
    date_to: date,
    store_id: Optional[str] = None,
    source: str = "hq_all",
    status: Optional[str] = None,
    channel_key: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """分页返回统一订单行。

    source:
      - ``hq_all``：orders 全量 + 未关联的 delivery_orders
      - ``internal_only``：仅 orders
      - ``delivery_unlinked``：仅未关联 internal_order_id 的 delivery_orders

    status:
      逗号分隔，如 ``pending,confirmed``；与各子查询 ``orders.status`` / ``delivery_orders.status`` 匹配。

    channel_key:
      对合并结果中的 ``channel_key`` 列 **精确** 匹配（内部单为
      ``COALESCE(sales_channel_id, order_type, 'unknown')``，未关联外卖为
      ``COALESCE(sales_channel, platform, 'delivery')``）。
    """
    if date_from > date_to:
        raise ValueError("date_from 不能晚于 date_to")
    if source not in ("hq_all", "internal_only", "delivery_unlinked"):
        raise ValueError(
            "source 须为 hq_all | internal_only | delivery_unlinked",
        )
    statuses = _parse_status_filter(status)
    channel_key_val = _parse_channel_key_filter(channel_key)

    tid = _validate_uuid_str(tenant_id, "tenant_id")
    sid: Optional[uuid.UUID] = None
    if store_id is not None and store_id.strip():
        sid = _validate_uuid_str(store_id, "store_id")

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tid)},
    )

    store_clause_o = "AND o.store_id = :sid" if sid is not None else ""
    store_clause_d = "AND d.store_id = :sid" if sid is not None else ""

    status_clause_o = ""
    status_clause_d = ""
    if statuses:
        ph = ",".join(f":st{i}" for i in range(len(statuses)))
        status_clause_o = f" AND o.status IN ({ph})"
        status_clause_d = f" AND d.status IN ({ph})"

    orders_sql = f"""
        SELECT
            'internal' AS order_source,
            o.id::text AS ref_id,
            o.order_no,
            o.store_id::text AS store_id,
            COALESCE(o.sales_channel_id, o.order_type, 'unknown') AS channel_key,
            o.order_type AS platform,
            o.status,
            COALESCE(o.final_amount_fen, o.total_amount_fen, 0) AS amount_fen,
            o.order_time AS sort_ts,
            o.customer_id::text AS customer_id
        FROM orders o
        WHERE o.tenant_id = CAST(:tid AS uuid)
          AND o.is_deleted = false
          {store_clause_o}
          AND (o.order_time AT TIME ZONE 'UTC')::date >= CAST(:d0 AS date)
          AND (o.order_time AT TIME ZONE 'UTC')::date <= CAST(:d1 AS date)
          {status_clause_o}
    """

    delivery_sql = f"""
        SELECT
            'delivery_unlinked' AS order_source,
            d.id::text AS ref_id,
            d.order_no,
            d.store_id::text AS store_id,
            COALESCE(d.sales_channel, d.platform, 'delivery') AS channel_key,
            d.platform,
            d.status,
            d.total_fen AS amount_fen,
            d.created_at AS sort_ts,
            NULL::text AS customer_id
        FROM delivery_orders d
        WHERE d.tenant_id = CAST(:tid AS uuid)
          AND d.is_deleted = false
          AND d.internal_order_id IS NULL
          {store_clause_d}
          AND (d.created_at AT TIME ZONE 'UTC')::date >= CAST(:d0 AS date)
          AND (d.created_at AT TIME ZONE 'UTC')::date <= CAST(:d1 AS date)
          {status_clause_d}
    """

    params: dict[str, Any] = {
        "tid": str(tid),
        "d0": date_from.isoformat(),
        "d1": date_to.isoformat(),
    }
    if sid is not None:
        params["sid"] = str(sid)
    if statuses:
        for i, st in enumerate(statuses):
            params[f"st{i}"] = st

    if source == "internal_only":
        union_sql = f"SELECT * FROM ({orders_sql}) x"
    elif source == "delivery_unlinked":
        union_sql = f"SELECT * FROM ({delivery_sql}) x"
    else:
        union_sql = f"""
            SELECT * FROM (
                {orders_sql}
                UNION ALL
                {delivery_sql}
            ) x
        """

    if channel_key_val is not None:
        params["channel_key_exact"] = channel_key_val
        union_sql = f"""
            SELECT * FROM ({union_sql}) z
            WHERE z.channel_key = :channel_key_exact
        """

    count_sql = f"SELECT COUNT(*) FROM ({union_sql}) c"
    count_row = await db.execute(text(count_sql), params)
    total = int(count_row.scalar() or 0)

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset
    list_sql = f"""
        SELECT * FROM ({union_sql}) y
        ORDER BY sort_ts DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    rows = result.mappings().fetchall()
    items = []
    for r in rows:
        ts = r["sort_ts"]
        items.append(
            {
                "order_source": r["order_source"],
                "ref_id": r["ref_id"],
                "order_no": r["order_no"],
                "store_id": r["store_id"],
                "channel_key": r["channel_key"],
                "platform": r["platform"] or None,
                "status": r["status"],
                "amount_fen": int(r["amount_fen"] or 0),
                "sort_ts": ts.isoformat() if ts is not None else None,
                "customer_id": r["customer_id"],
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "source": source,
        "filters": {
            "status": statuses,
            "channel_key": channel_key_val,
        },
    }
