"""cert_service — 供应商证件管理服务（PRD-01 食安合规 / Tier 1）

核心业务逻辑：
  1. is_supplier_blocked() — 收货阻断点：证件过期且 auto_block_on_expire=TRUE 时返回 True
     续证后新 expire_date 在未来 → 查询自动返回 False，无需手动解锁
  2. list_expiring()       — 即将过期预警列表（为 PR-01B alerter 预留）
  3. renew_cert()          — 续证接口：更新 expire_date + attachment_url

设计要点：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - is_supplier_blocked 只看 auto_block_on_expire=TRUE 且 expire_date < today 的活跃记录
  - 无手动 block/unblock 状态机：续证 = expire_date 移到未来 = 自动解除阻断
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _uuid_str(val: str | uuid.UUID) -> str:
    return str(val)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 租户上下文（标准模式，参考 receiving_v2_service）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


async def is_supplier_blocked(
    db: AsyncSession,
    tenant_id: str,
    supplier_id: str,
    today: date,
) -> bool:
    """检查供应商是否因证件过期被阻断收货。

    GIVEN 供应商有任意一张 auto_block_on_expire=TRUE 且 expire_date < today 的活跃证件
    THEN  返回 True（阻断收货）
    ELSE  返回 False（允许收货）

    续证后 expire_date 更新到未来日期，下次查询自动返回 False，无需手动解锁。
    """
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            """
            SELECT 1
            FROM supplier_certificates
            WHERE tenant_id     = :tenant_id
              AND supplier_id   = :supplier_id
              AND auto_block_on_expire = TRUE
              AND expire_date   < :today
              AND is_deleted    = FALSE
            LIMIT 1
            """
        ),
        {
            "tenant_id": _uuid_str(tenant_id),
            "supplier_id": _uuid_str(supplier_id),
            "today": today,
        },
    )
    row = result.first()
    return row is not None


async def is_supplier_blocked_via_po(
    db: AsyncSession,
    tenant_id: str,
    purchase_order_id: str,
    today: date,
) -> bool:
    """通过 purchase_order_id 反查 supplier_id 后判断阻断（v1 收货路径 + v2 procurement 流入口）。

    若 PO 不存在或 supplier_id 为 NULL → 食安路径 **fail-closed** 返回 True（阻断）。
    这与"未知供应商不能收货"语义一致：监管视角，匿名收货违反 PRD-01。
    """
    await _set_tenant(db, tenant_id)

    row = (
        await db.execute(
            text(
                """
                SELECT supplier_id::text AS supplier_id
                FROM purchase_orders
                WHERE id        = :po_id::uuid
                  AND tenant_id = :tenant_id::uuid
                  AND is_deleted = FALSE
                LIMIT 1
                """
            ),
            {"po_id": str(purchase_order_id), "tenant_id": _uuid_str(tenant_id)},
        )
    ).mappings().first()

    if row is None or not row.get("supplier_id"):
        # PO 不存在 / PO 无 supplier_id → fail-closed
        logger.warning(
            "cert_block_po_lookup_failed_fail_closed",
            purchase_order_id=str(purchase_order_id),
            tenant_id=str(tenant_id),
        )
        return True

    return await is_supplier_blocked(
        db,
        tenant_id=tenant_id,
        supplier_id=row["supplier_id"],
        today=today,
    )


async def list_expiring(
    db: AsyncSession,
    tenant_id: str,
    within_days: int = 30,
) -> List[dict]:
    """列出即将在 within_days 天内过期的证件列表。

    为 PR-01B Celery beat alerter 预留接口。
    """
    await _set_tenant(db, tenant_id)

    today = date.today()
    result = await db.execute(
        text(
            """
            SELECT
                id::text,
                supplier_id::text,
                cert_type,
                cert_number,
                issuer,
                expire_date,
                warning_days,
                auto_block_on_expire,
                attachment_url
            FROM supplier_certificates
            WHERE tenant_id   = :tenant_id
              AND expire_date >= :today
              AND expire_date <= :cutoff
              AND is_deleted  = FALSE
            ORDER BY expire_date ASC
            """
        ),
        {
            "tenant_id": _uuid_str(tenant_id),
            "today": today,
            "cutoff": date.fromordinal(today.toordinal() + within_days),
        },
    )
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def list_alertable(
    db: AsyncSession,
    tenant_id: str,
    *,
    today: date,
    lookahead_days: int = 30,
) -> List[dict]:
    """临期 + 过期组合查询（PR-01B sub-PR B / PRD-01）。

    返回 supplier_certificates 中：
    - expire_date BETWEEN today AND today + lookahead_days  （临期窗口）
    - 或 expire_date < today                                （已过期）

    每行返回 dict 含：cert_id, supplier_id, cert_type, cert_number,
    expire_date, days_until_expiry（signed int — 负数表示已过期 N 天）。
    """
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            """
            SELECT
                id::text           AS cert_id,
                supplier_id::text  AS supplier_id,
                cert_type,
                cert_number,
                expire_date,
                (expire_date - :today)::int AS days_until_expiry
            FROM supplier_certificates
            WHERE tenant_id   = :tenant_id
              AND is_deleted  = FALSE
              AND (
                (expire_date BETWEEN :today AND :today + (:lookahead_days || ' days')::interval)
                OR expire_date < :today
              )
            ORDER BY expire_date ASC
            """
        ),
        {
            "tenant_id": _uuid_str(tenant_id),
            "today": today,
            "lookahead_days": lookahead_days,
        },
    )
    return [dict(r) for r in result.mappings()]


async def renew_cert(
    db: AsyncSession,
    tenant_id: str,
    cert_id: str,
    new_expire_date: date,
    new_attachment_url: Optional[str] = None,
) -> dict:
    """续证接口：更新 expire_date 和 attachment_url。

    续证后 expire_date > today，is_supplier_blocked 下次查询自动返回 False。
    无需手动解锁。

    §19 P1-2 修复：拒绝过去日期续证（督导手滑穿越续证导致"假成功"，
    实际仍阻断，徐记早市进货全废）。要求 new_expire_date >= today。
    """
    if new_expire_date < date.today():
        raise ValueError(
            f"new_expire_date={new_expire_date} 不能早于今天 — 续证必须指向未来"
        )

    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        text(
            """
            UPDATE supplier_certificates
            SET
                expire_date    = :new_expire_date,
                attachment_url = COALESCE(:new_attachment_url, attachment_url),
                updated_at     = :now
            WHERE id        = :cert_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            RETURNING
                id::text,
                supplier_id::text,
                cert_type,
                cert_number,
                expire_date,
                auto_block_on_expire,
                attachment_url,
                updated_at
            """
        ),
        {
            "new_expire_date": new_expire_date,
            "new_attachment_url": new_attachment_url,
            "now": now,
            "cert_id": cert_id,
            "tenant_id": _uuid_str(tenant_id),
        },
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError(f"cert_id={cert_id} not found or not owned by tenant")

    logger.info(
        "cert_renewed",
        cert_id=cert_id,
        tenant_id=tenant_id,
        new_expire_date=str(new_expire_date),
    )
    return dict(row)
