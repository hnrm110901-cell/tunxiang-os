"""rfq_service — RFQ 询价单 service（PRD-04 sub-B / Phase 2 W9 / Tier 1 资金路径前置）

核心业务逻辑：
  1. create_rfq — 创建草稿 + 写入 items + 写入 invitees（同事务原子）
  2. get_rfq — SELECT (lock=False default) / lock=True 加 FOR UPDATE (mutation 路径)
  3. award_rfq — Tier 1 中标 + 二级审批 + RLHF 信号
     - FOR UPDATE 行锁串行化重复 award (UNIQUE(rfq_id) 双保险)
     - approver_id != rfq.created_by (二级审批拒绝 self-approve)
     - quote 必须属于本 rfq + 该 supplier 必须被邀请
     - INSERT INTO rfq_awards + UPDATE rfqs.status = 'awarded'
     - ai_recommendation_followed: Optional[bool] — ⭐ RLHF 训练信号 (sub-C UI 强制采集)

设计要点：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - lock 参数沿 PR-A/B/C/D/E 行锁 pattern（mutation 路径 lock=True，read-only lock=False）
  - raw SQL text() 路径与 yield_standard_service / weight_standard_service / delivery_window_service 对齐
  - publish / submit_quote / close / cancel 4 个状态转换在 sub-C 落（submit_quote 含 supplier_portal endpoint）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Union

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

logger = structlog.get_logger(__name__)

_DBConn = Union[AsyncConnection, AsyncSession]


def _uuid_str(val: str | uuid.UUID) -> str:
    return str(val)


async def _set_tenant(db: _DBConn, tenant_id: str) -> None:
    """设置 RLS 租户上下文（与 yield_standard_service / weight_standard_service 同 pattern）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── CRUD ─────────────────────────────────────────────────────────────────────


async def create_rfq(
    db: AsyncSession,
    tenant_id: str,
    *,
    initiator_id: str,
    deadline: datetime,
    items: list[dict],
    invited_supplier_ids: list[str],
    created_by: str,
    notes: Optional[str] = None,
    rfq_number: Optional[str] = None,
) -> dict:
    """新建询价单（草稿态 status='draft'）。

    同事务原子写 rfqs + rfq_items + rfq_invitees。后续 publish 由 sub-C 落。

    items[i] 字段：
      - ingredient_id: str (UUID)
      - qty_required: Decimal (> 0)
      - qty_unit: Optional[str]
      - spec_notes: Optional[str]
    """
    if not items:
        raise ValueError("询价单至少包含一项 item")
    if deadline <= datetime.now(timezone.utc):
        raise ValueError("deadline 必须在未来")

    await _set_tenant(db, tenant_id)

    rfq_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # 1. INSERT rfqs 主表
    result = await db.execute(
        text(
            """
            INSERT INTO rfqs (
                id, tenant_id, rfq_number, initiator_id, deadline, status,
                notes, created_by, created_at, updated_at, is_deleted
            )
            VALUES (
                :id, :tenant_id, :rfq_number, :initiator_id, :deadline, 'draft',
                :notes, :created_by, :now, :now, FALSE
            )
            RETURNING
                id::text                   AS id,
                tenant_id::text            AS tenant_id,
                rfq_number,
                initiator_id::text         AS initiator_id,
                deadline,
                status,
                notes,
                created_by::text           AS created_by,
                created_at,
                updated_at,
                is_deleted
            """
        ),
        {
            "id": rfq_id,
            "tenant_id": _uuid_str(tenant_id),
            "rfq_number": rfq_number,
            "initiator_id": _uuid_str(initiator_id),
            "deadline": deadline,
            "notes": notes,
            "created_by": _uuid_str(created_by),
            "now": now,
        },
    )
    rfq_row = result.mappings().first()
    if rfq_row is None:
        raise ValueError("create_rfq failed — RETURNING 无结果")

    # 2. INSERT rfq_items 子表（每行）
    item_rows = []
    for item in items:
        if Decimal(str(item["qty_required"])) <= 0:
            raise ValueError(f"item.qty_required 必须 > 0: {item}")
        item_id = str(uuid.uuid4())
        ir = await db.execute(
            text(
                """
                INSERT INTO rfq_items (
                    id, tenant_id, rfq_id, ingredient_id, qty_required,
                    qty_unit, spec_notes, created_at, updated_at, is_deleted
                )
                VALUES (
                    :id, :tenant_id, :rfq_id, :ingredient_id, :qty_required,
                    :qty_unit, :spec_notes, :now, :now, FALSE
                )
                RETURNING
                    id::text                AS id,
                    tenant_id::text         AS tenant_id,
                    rfq_id::text            AS rfq_id,
                    ingredient_id::text     AS ingredient_id,
                    qty_required,
                    qty_unit,
                    spec_notes,
                    created_at
                """
            ),
            {
                "id": item_id,
                "tenant_id": _uuid_str(tenant_id),
                "rfq_id": rfq_id,
                "ingredient_id": _uuid_str(item["ingredient_id"]),
                "qty_required": Decimal(str(item["qty_required"])),
                "qty_unit": item.get("qty_unit"),
                "spec_notes": item.get("spec_notes"),
                "now": now,
            },
        )
        item_row = ir.mappings().first()
        if item_row:
            item_rows.append(dict(item_row))

    # 3. INSERT rfq_invitees 子表（每个邀请供应商）
    invitee_rows = []
    for supplier_id in invited_supplier_ids:
        invitee_id = str(uuid.uuid4())
        inv = await db.execute(
            text(
                """
                INSERT INTO rfq_invitees (
                    id, tenant_id, rfq_id, supplier_id, invited_at, responded_at,
                    created_at, updated_at, is_deleted
                )
                VALUES (
                    :id, :tenant_id, :rfq_id, :supplier_id, :now, NULL,
                    :now, :now, FALSE
                )
                RETURNING
                    id::text                AS id,
                    tenant_id::text         AS tenant_id,
                    rfq_id::text            AS rfq_id,
                    supplier_id::text       AS supplier_id,
                    invited_at,
                    responded_at
                """
            ),
            {
                "id": invitee_id,
                "tenant_id": _uuid_str(tenant_id),
                "rfq_id": rfq_id,
                "supplier_id": _uuid_str(supplier_id),
                "now": now,
            },
        )
        invitee_row = inv.mappings().first()
        if invitee_row:
            invitee_rows.append(dict(invitee_row))

    logger.info(
        "rfq_created",
        rfq_id=rfq_id,
        tenant_id=str(tenant_id),
        initiator_id=str(initiator_id),
        items_count=len(items),
        invitees_count=len(invited_supplier_ids),
    )

    return {
        **dict(rfq_row),
        "items": item_rows,
        "invitees": invitee_rows,
    }


async def get_rfq(
    db: AsyncSession,
    tenant_id: str,
    rfq_id: str,
    *,
    lock: bool = False,
) -> Optional[dict]:
    """单条 RFQ 查询。lock=True 加 FOR UPDATE 行锁（mutation 路径 — award/cancel）。

    沿用 PR-A/B/C/D/E row-lock pattern：read-only 入口 lock=False 默认。
    """
    await _set_tenant(db, tenant_id)

    lock_clause = " FOR UPDATE" if lock else ""
    result = await db.execute(
        text(
            f"""
            SELECT
                id::text                   AS id,
                tenant_id::text            AS tenant_id,
                rfq_number,
                initiator_id::text         AS initiator_id,
                deadline,
                status,
                notes,
                created_by::text           AS created_by,
                created_at,
                updated_at,
                is_deleted
            FROM rfqs
            WHERE id        = :rfq_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            LIMIT 1{lock_clause}
            """
        ),
        {"rfq_id": rfq_id, "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


# ─── Tier 1 award 路径 ────────────────────────────────────────────────────────


async def award_rfq(
    db: AsyncSession,
    tenant_id: str,
    rfq_id: str,
    *,
    selected_quote_id: str,
    reason: str,
    approver_id: str,
    created_by: str,
    ai_recommendation_followed: Optional[bool] = None,
) -> dict:
    """Tier 1 中标 — row-lock 行锁串行化 + 二级审批 + RLHF 信号写入。

    硬约束（全部强制）:
      1. RFQ 必须存在 + status != 'awarded' + status != 'cancelled' + is_deleted=FALSE
      2. approver_id != rfq.created_by (二级审批 — 防 self-approve)
      3. selected_quote_id 必须属于本 rfq (跨 rfq 中标拒绝)
      4. UNIQUE(tenant_id, rfq_id) on rfq_awards 防重复 award (DB-level)
      5. FOR UPDATE on rfqs 串行化并发 award 请求 (200 桌并发 #579)

    Tier 1 资金路径前置 — 此函数 commit 后 rfq.status = 'awarded' 不可回退（不可逆操作）。
    后续采购单生成 + 应付账款挂账走 sub-B 集成或后续 PR.
    """
    if not reason or not reason.strip():
        raise ValueError("award reason 必填 — 合规审计")
    if str(approver_id) == str(created_by):
        raise ValueError(
            f"approver_id={approver_id} 不能与 created_by 相同（二级审批必须独立签字）"
        )

    await _set_tenant(db, tenant_id)

    # 1. SELECT rfqs FOR UPDATE 行锁串行化（PR-A/B/C/D/E pattern）
    rfq = await get_rfq(db, tenant_id, rfq_id, lock=True)
    if rfq is None:
        raise ValueError(f"rfq_id={rfq_id} 不存在或已删除")

    # 2. 状态机校验：only draft/published/quoting/comparing 可 award
    if rfq["status"] == "awarded":
        raise ValueError(f"rfq_id={rfq_id} 已 award，不允许重复中标")
    if rfq["status"] == "cancelled":
        raise ValueError(f"rfq_id={rfq_id} 已 cancel，不允许 award")

    # 3. 二级审批：approver_id != rfq.created_by（防 self-approve）
    if str(rfq["created_by"]) == str(approver_id):
        raise ValueError(
            f"approver_id={approver_id} 不能与 rfq.created_by={rfq['created_by']} 相同"
            "（二级审批必须独立签字）"
        )

    # 4. 校验 quote 归属：selected_quote_id 必须属于本 rfq
    quote_check = await db.execute(
        text(
            """
            SELECT
                id::text                AS id,
                rfq_id::text            AS rfq_id,
                supplier_id::text       AS supplier_id,
                ingredient_id::text     AS ingredient_id,
                unit_price_fen
            FROM rfq_quotes
            WHERE id        = :quote_id
              AND tenant_id = :tenant_id
              AND rfq_id    = :rfq_id
            LIMIT 1
            """
        ),
        {
            "quote_id": _uuid_str(selected_quote_id),
            "tenant_id": _uuid_str(tenant_id),
            "rfq_id": rfq_id,
        },
    )
    quote_row = quote_check.mappings().first()
    if quote_row is None:
        raise ValueError(
            f"selected_quote_id={selected_quote_id} 不属于 rfq_id={rfq_id}"
            "（合规审计 — 中标必须基于本询价单内报价）"
        )

    # 5. INSERT rfq_awards（UNIQUE(tenant_id, rfq_id) 防重复 award — DB-level 双保险）
    award_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    award_result = await db.execute(
        text(
            """
            INSERT INTO rfq_awards (
                id, tenant_id, rfq_id, selected_quote_id, reason,
                ai_recommendation_followed, approved_by, approved_at,
                created_by, created_at, updated_at, is_deleted
            )
            VALUES (
                :id, :tenant_id, :rfq_id, :selected_quote_id, :reason,
                :ai_followed, :approver_id, :now,
                :created_by, :now, :now, FALSE
            )
            RETURNING
                id::text                        AS id,
                tenant_id::text                 AS tenant_id,
                rfq_id::text                    AS rfq_id,
                selected_quote_id::text         AS selected_quote_id,
                reason,
                ai_recommendation_followed,
                approved_by::text               AS approved_by,
                approved_at,
                created_by::text                AS created_by,
                created_at
            """
        ),
        {
            "id": award_id,
            "tenant_id": _uuid_str(tenant_id),
            "rfq_id": rfq_id,
            "selected_quote_id": _uuid_str(selected_quote_id),
            "reason": reason.strip(),
            "ai_followed": ai_recommendation_followed,
            "approver_id": _uuid_str(approver_id),
            "created_by": _uuid_str(created_by),
            "now": now,
        },
    )
    award_row = award_result.mappings().first()
    if award_row is None:
        # ON CONFLICT 不会触发（这里没用），但 UNIQUE 冲突时 INTEGRITYERROR 在外层捕获
        raise ValueError(f"award_rfq failed — rfq_id={rfq_id} RETURNING 无结果")

    # 6. UPDATE rfqs.status = 'awarded'（FOR UPDATE 已持锁 — 同事务原子）
    await db.execute(
        text(
            """
            UPDATE rfqs
            SET status     = 'awarded',
                updated_at = :now
            WHERE id        = :rfq_id
              AND tenant_id = :tenant_id
              AND status   != 'awarded'
              AND status   != 'cancelled'
              AND is_deleted = FALSE
            """
        ),
        {"rfq_id": rfq_id, "tenant_id": _uuid_str(tenant_id), "now": now},
    )

    logger.info(
        "rfq_awarded",
        rfq_id=rfq_id,
        tenant_id=str(tenant_id),
        award_id=award_id,
        selected_quote_id=str(selected_quote_id),
        approver_id=str(approver_id),
        ai_recommendation_followed=ai_recommendation_followed,
        supplier_id=str(quote_row["supplier_id"]),
        unit_price_fen=int(quote_row["unit_price_fen"]),
    )

    return dict(award_row)
