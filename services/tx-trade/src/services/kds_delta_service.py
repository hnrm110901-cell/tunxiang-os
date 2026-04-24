"""kds_delta_service — Sprint C3 KDS 订单 delta 查询

职责：
  - get_orders_delta — 查询 cursor 之后 status ∈ (pending/confirmed/preparing/ready)
    的订单；按 updated_at 升序；limit<=500。
  - parse_cursor     — 接受 ISO8601 / datetime / None 三种格式。
  - 返回 next_cursor（下一轮拉取起点）与 server_time（防时钟漂移）。

设计约束（CLAUDE.md §17 Tier1）：
  - 所有查询显式带 tenant_id 过滤（service 层拦截）+ RLS 兜底（app.tenant_id）
  - 依赖 orders (tenant_id, store_id, updated_at) 索引达到 P99<100ms
  - 敏感字段（customer_phone / total_amount_fen）在 device_kind=kds 视角下剔除
  - 不返回 completed/cancelled/served —— KDS 只关心在制任务
  - 不返回删除 (is_deleted=true) 订单

与 A3 契约共享：
  - device_id / device_kind 命名协议
  - sync_attempts / last_sync_at 命名范式（本 service 不直接写这两字段，
    由 device_registry_service 写入）

金额/时间：
  - cursor 使用 UTC TIMESTAMPTZ
  - 所有 updated_at 一律 UTC
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


# ─── 常量 ─────────────────────────────────────────────────────────────────────

# KDS 视角的订单状态白名单（不含 completed/served/cancelled）
KDS_VISIBLE_STATUSES = ("pending", "confirmed", "preparing", "ready")

# KDS 视角暴露字段（device_kind=kds 时过滤后返回）
KDS_SAFE_FIELDS = (
    "tenant_id",
    "id",
    "order_no",
    "store_id",
    "status",
    "table_number",
    "updated_at",
    "order_metadata",
    "items_count",
)

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


# ─── 工具 ─────────────────────────────────────────────────────────────────────


def parse_cursor(
    cursor: Union[str, datetime, None],
) -> Optional[datetime]:
    """将外部传入的 cursor 解析为 UTC datetime。

    Accepts:
        - None / "" → None（首次拉取，无 cursor）
        - datetime → 直接返回（保证 UTC，naive 会补 UTC tz）
        - "2026-04-24T18:00:00Z" / "2026-04-24T18:00:00+00:00" ISO8601

    Raises:
        ValueError: 非法格式。
    """
    if cursor is None:
        return None
    if isinstance(cursor, datetime):
        if cursor.tzinfo is None:
            return cursor.replace(tzinfo=timezone.utc)
        return cursor
    if isinstance(cursor, str):
        s = cursor.strip()
        if not s:
            return None
        try:
            # Python datetime.fromisoformat 3.11+ 支持 Z 后缀；兼容处理
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except ValueError as exc:
            raise ValueError(f"invalid cursor format: {cursor!r}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    raise ValueError(f"unsupported cursor type: {type(cursor).__name__}")


# ─── Service ──────────────────────────────────────────────────────────────────


class KDSDeltaService:
    """KDS delta 查询服务。

    使用方式：
        svc = KDSDeltaService(db, tenant_id=X)
        result = await svc.get_orders_delta(
            store_id=..., cursor=..., device_kind="kds", limit=100
        )
        → {"orders": [...], "next_cursor": datetime, "server_time": datetime}
    """

    def __init__(self, db: Any, tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self._db = db
        self._tenant_id = str(tenant_id)

    async def _bind_rls(self) -> None:
        """设置 app.tenant_id（RLS 策略依赖此 GUC）。"""
        await self._db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self._tenant_id},
        )

    async def get_orders_delta(
        self,
        *,
        store_id: str,
        cursor: Union[str, datetime, None] = None,
        device_kind: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """查询 cursor 之后的 KDS 可见订单。

        Args:
            store_id:    门店 UUID 字符串
            cursor:      ISO8601 / datetime / None（首次）
            device_kind: None → 返回全部字段；"kds" → 剔除敏感字段
            limit:       单次返回上限 [1, 500]，默认 100

        Returns:
            {
              "orders": [订单 dict...],
              "next_cursor": datetime | None,
              "server_time": datetime
            }

        Raises:
            ValueError: cursor 非法 / limit 越界 / store_id 空
            SQLAlchemyError: 数据库异常（向上抛，由路由层包成 500）
        """
        if not store_id:
            raise ValueError("store_id is required")
        if limit <= 0 or limit > MAX_LIMIT:
            raise ValueError(f"limit out of range [1, {MAX_LIMIT}]: {limit}")

        parsed_cursor = parse_cursor(cursor)

        await self._bind_rls()

        # 使用元组做 IN 查询（status 白名单硬编码防注入）
        try:
            result = await self._db.execute(
                text(
                    """
                    SELECT
                        tenant_id, id, order_no, store_id, status,
                        table_number, updated_at, order_metadata,
                        customer_phone, total_amount_fen,
                        items_count
                    FROM orders
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND (:cursor::timestamptz IS NULL OR updated_at > :cursor::timestamptz)
                      AND status IN ('pending','confirmed','preparing','ready')
                      AND (is_deleted IS NULL OR is_deleted = false)
                    ORDER BY updated_at ASC
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "store_id": str(store_id),
                    "cursor": parsed_cursor,
                    "limit": int(limit),
                },
            )
            rows = result.mappings().all()
        except SQLAlchemyError as exc:
            logger.error(
                "kds_delta_query_failed",
                tenant_id=self._tenant_id,
                store_id=str(store_id),
                error=str(exc),
            )
            raise

        orders = [dict(r) for r in rows]

        # device_kind=kds 视角剔除敏感字段
        if device_kind == "kds":
            orders = [self._project_kds_safe(o) for o in orders]

        next_cursor = orders[-1]["updated_at"] if orders else parsed_cursor
        server_time = datetime.now(timezone.utc)

        logger.info(
            "kds_delta_query_ok",
            tenant_id=self._tenant_id,
            store_id=str(store_id),
            count=len(orders),
            device_kind=device_kind,
        )

        return {
            "orders": orders,
            "next_cursor": next_cursor,
            "server_time": server_time,
        }

    @staticmethod
    def _project_kds_safe(order: dict) -> dict:
        """对订单字典仅保留 KDS_SAFE_FIELDS。"""
        return {k: v for k, v in order.items() if k in KDS_SAFE_FIELDS}
