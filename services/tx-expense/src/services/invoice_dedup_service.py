"""
集团级跨品牌发票去重服务
核心逻辑：同一张发票（由 invoice_code + invoice_number 唯一标识）在不同品牌/租户各报销一次即为可疑重复。

关键设计决策：
  - group_key = SHA-256(invoice_code + ":" + invoice_number)，不含金额
    （同一张发票不管金额是否相同都是同一张，含金额会导致漏检）
  - invoice_dedup_groups / group_invoice_cross_ref 不加 RLS，必须通过 SERVICE_DB_URL（超级账号）连接
  - 本服务通过 db 参数接收连接，调用方负责传入正确的超级账号 session
  - is_suspicious 仅在 first_tenant_id != 当前 tenant_id 时置 True（真正跨品牌）
  - 同一租户内重复上传（如同一门店误传两次）不标 is_suspicious，但会记录到 cross_ref

金额约定：所有金额字段为分(fen)。
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _compute_group_key(invoice_code: str, invoice_number: str) -> str:
    """
    集团去重组 key：SHA-256(invoice_code + ":" + invoice_number)
    注意：不含金额，与 invoice_verification_service.compute_dedup_hash() 的含金额版本区分。
    invoice_dedup_groups 用此 key，invoices.dedup_hash 仍用含金额版本。
    """
    content = f"{invoice_code}:{invoice_number}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# 集团级发票去重服务
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceDedupService:
    """
    集团级跨品牌发票去重服务。

    调用时序（由 invoice_verification_service.process_invoice_upload 在最后一步调用）：
      1. OCR 提取 invoice_code / invoice_number
      2. 若字段存在，调用 check_group_dedup()
      3. 返回结果中注入 group_dedup 字段
      4. 若 is_duplicate=True，在 invoices 表 notes 中追加 [集团去重警告]

    重要：本服务的 db 参数必须是通过 SERVICE_DB_URL（超级账号）创建的 session，
    因为 invoice_dedup_groups 不加 RLS。
    """

    async def check_group_dedup(
        self,
        db: AsyncSession,
        invoice_code: str,
        invoice_number: str,
        tenant_id: UUID,
        invoice_id: UUID,
        expense_application_id: Optional[UUID] = None,
    ) -> dict:
        """
        在发票上传时调用（invoice_verification_service.process_invoice_upload 末尾）。

        逻辑：
          1. 计算 group_key = SHA-256(invoice_code + ":" + invoice_number)
          2. 查找 invoice_dedup_groups WHERE group_id = group_key
          3. 不存在 → 创建组记录，插入 cross_ref，返回 is_duplicate=False
          4. 存在 →
             - total_usage_count += 1
             - 若 first_tenant_id != tenant_id：is_suspicious=True（跨品牌重复）
             - 插入 cross_ref（ON CONFLICT DO NOTHING，幂等）
             - 返回 is_duplicate=True 及详情

        返回结构：
        {
            "is_duplicate": bool,
            "group_id": str,
            "usage_count": int,
            "is_cross_brand": bool,              # True=不同品牌，False=同品牌内重复
            "first_tenant_id": str | None,       # 仅 is_duplicate=True 时有值
            "first_invoice_id": str | None,
            "first_reported_at": str | None,     # ISO 8601
            "message": str,
        }
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            invoice_id=str(invoice_id),
            invoice_code=invoice_code,
            invoice_number=invoice_number,
        )

        group_key = _compute_group_key(invoice_code, invoice_number)
        now = _now_utc()

        # ── Step 1：查询是否存在 ─────────────────────────────────────────────
        try:
            select_stmt = text("""
                SELECT group_id, first_tenant_id, first_invoice_id,
                       first_reported_at, total_usage_count, is_suspicious
                FROM invoice_dedup_groups
                WHERE group_id = :group_key
                FOR UPDATE
            """)
            result = await db.execute(select_stmt, {"group_key": group_key})
            row = result.mappings().one_or_none()
        except SQLAlchemyError as exc:
            logger.error(
                "invoice_dedup_select_error",
                error=str(exc),
                group_key=group_key,
                exc_info=True,
            )
            return {
                "is_duplicate": False,
                "group_id": group_key,
                "usage_count": 1,
                "is_cross_brand": False,
                "first_tenant_id": None,
                "first_invoice_id": None,
                "first_reported_at": None,
                "message": f"去重检查数据库错误，跳过：{exc}",
            }

        if row is None:
            # ── Step 2：首次使用，创建组记录 ─────────────────────────────────
            try:
                await db.execute(
                    text("""
                        INSERT INTO invoice_dedup_groups (
                            group_id, first_tenant_id, first_invoice_id,
                            first_reported_at, total_usage_count, is_suspicious,
                            created_at, updated_at
                        ) VALUES (
                            :group_key, :tenant_id, :invoice_id,
                            :first_reported_at, 1, FALSE,
                            :now, :now
                        )
                        ON CONFLICT (group_id) DO NOTHING
                    """),
                    {
                        "group_key": group_key,
                        "tenant_id": str(tenant_id),
                        "invoice_id": str(invoice_id),
                        "first_reported_at": now,
                        "now": now,
                    },
                )
            except SQLAlchemyError as exc:
                logger.error(
                    "invoice_dedup_insert_group_error",
                    error=str(exc),
                    group_key=group_key,
                    exc_info=True,
                )

            # 插入 cross_ref
            await self._upsert_cross_ref(
                db, group_key, tenant_id, invoice_id, expense_application_id, now
            )

            log.info(
                "invoice_dedup_new_group",
                group_key=group_key,
            )
            return {
                "is_duplicate": False,
                "group_id": group_key,
                "usage_count": 1,
                "is_cross_brand": False,
                "first_tenant_id": str(tenant_id),
                "first_invoice_id": str(invoice_id),
                "first_reported_at": now.isoformat(),
                "message": "发票首次使用，已注册集团去重组",
            }

        # ── Step 3：已存在，更新计数 + 判断跨品牌 ─────────────────────────────
        first_tenant_id = row["first_tenant_id"]
        first_invoice_id = row["first_invoice_id"]
        first_reported_at = row["first_reported_at"]
        new_usage_count = int(row["total_usage_count"]) + 1
        is_cross_brand = str(first_tenant_id) != str(tenant_id)

        try:
            await db.execute(
                text("""
                    UPDATE invoice_dedup_groups SET
                        total_usage_count = :new_count,
                        is_suspicious = is_suspicious OR :is_cross_brand,
                        updated_at = :now
                    WHERE group_id = :group_key
                """),
                {
                    "new_count": new_usage_count,
                    "is_cross_brand": is_cross_brand,
                    "now": now,
                    "group_key": group_key,
                },
            )
        except SQLAlchemyError as exc:
            logger.error(
                "invoice_dedup_update_group_error",
                error=str(exc),
                group_key=group_key,
                exc_info=True,
            )

        # 插入 cross_ref（幂等）
        await self._upsert_cross_ref(
            db, group_key, tenant_id, invoice_id, expense_application_id, now
        )

        if is_cross_brand:
            log.warning(
                "invoice_dedup_cross_brand_duplicate",
                group_key=group_key,
                first_tenant_id=str(first_tenant_id),
                usage_count=new_usage_count,
            )
            message = (
                f"[跨品牌重复] 发票已被租户 {first_tenant_id} 于 "
                f"{first_reported_at.isoformat() if hasattr(first_reported_at, 'isoformat') else first_reported_at} "
                f"报销，使用次数 {new_usage_count}"
            )
        else:
            log.warning(
                "invoice_dedup_same_brand_duplicate",
                group_key=group_key,
                usage_count=new_usage_count,
            )
            message = (
                f"[同品牌重复] 发票在同一集团内已报销 {new_usage_count - 1} 次，"
                f"首次时间 "
                f"{first_reported_at.isoformat() if hasattr(first_reported_at, 'isoformat') else first_reported_at}"
            )

        return {
            "is_duplicate": True,
            "group_id": group_key,
            "usage_count": new_usage_count,
            "is_cross_brand": is_cross_brand,
            "first_tenant_id": str(first_tenant_id),
            "first_invoice_id": str(first_invoice_id),
            "first_reported_at": (
                first_reported_at.isoformat()
                if hasattr(first_reported_at, "isoformat")
                else str(first_reported_at)
            ),
            "message": message,
        }

    async def _upsert_cross_ref(
        self,
        db: AsyncSession,
        group_key: str,
        tenant_id: UUID,
        invoice_id: UUID,
        expense_application_id: Optional[UUID],
        now: datetime,
    ) -> None:
        """幂等插入 group_invoice_cross_ref（ON CONFLICT DO NOTHING）。"""
        try:
            await db.execute(
                text("""
                    INSERT INTO group_invoice_cross_ref (
                        group_id, tenant_id, invoice_id,
                        expense_application_id, reported_at
                    ) VALUES (
                        :group_key, :tenant_id, :invoice_id,
                        :expense_application_id, :now
                    )
                    ON CONFLICT (group_id, tenant_id, invoice_id) DO NOTHING
                """),
                {
                    "group_key": group_key,
                    "tenant_id": str(tenant_id),
                    "invoice_id": str(invoice_id),
                    "expense_application_id": str(expense_application_id) if expense_application_id else None,
                    "now": now,
                },
            )
        except SQLAlchemyError as exc:
            logger.error(
                "invoice_dedup_upsert_cross_ref_error",
                error=str(exc),
                group_key=group_key,
                tenant_id=str(tenant_id),
                exc_info=True,
            )

    async def get_suspicious_invoices(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """
        查询本租户涉及的可疑跨品牌重复发票（分页）。

        返回：
        {
            "items": [
                {
                    "group_id": str,
                    "invoice_id": str,
                    "first_tenant_id": str,
                    "first_reported_at": str,
                    "total_usage_count": int,
                    "is_cross_brand": bool,
                    "reported_at": str,          # 本租户上报时间
                    "resolved_at": str | None,
                    "resolve_note": str | None,
                }
            ],
            "total": int,
            "page": int,
            "page_size": int,
        }
        """
        where_clauses = [
            "cr.tenant_id = :tenant_id",
            "dg.is_suspicious = TRUE",
        ]
        params: dict = {"tenant_id": str(tenant_id)}

        if start_date:
            where_clauses.append("cr.reported_at >= :start_date")
            params["start_date"] = start_date
        if end_date:
            where_clauses.append("cr.reported_at <= :end_date")
            params["end_date"] = end_date

        where_sql = " AND ".join(where_clauses)

        count_sql = f"""
            SELECT COUNT(*) AS total
            FROM group_invoice_cross_ref cr
            JOIN invoice_dedup_groups dg ON dg.group_id = cr.group_id
            WHERE {where_sql}
        """
        try:
            count_result = await db.execute(text(count_sql), params)
            total = int(count_result.scalar_one())
        except SQLAlchemyError as exc:
            logger.error(
                "invoice_dedup_get_suspicious_count_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

        offset = (page - 1) * page_size
        items_sql = f"""
            SELECT
                cr.group_id,
                cr.invoice_id,
                cr.expense_application_id,
                cr.reported_at,
                dg.first_tenant_id,
                dg.first_invoice_id,
                dg.first_reported_at,
                dg.total_usage_count,
                dg.resolved_at,
                dg.resolve_note
            FROM group_invoice_cross_ref cr
            JOIN invoice_dedup_groups dg ON dg.group_id = cr.group_id
            WHERE {where_sql}
            ORDER BY cr.reported_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = page_size
        params["offset"] = offset

        try:
            items_result = await db.execute(text(items_sql), params)
            rows = items_result.mappings().all()
        except SQLAlchemyError as exc:
            logger.error(
                "invoice_dedup_get_suspicious_items_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )
            return {"items": [], "total": total, "page": page, "page_size": page_size}

        items = []
        for row in rows:
            first_reported = row["first_reported_at"]
            reported = row["reported_at"]
            resolved = row["resolved_at"]
            items.append({
                "group_id": row["group_id"],
                "invoice_id": str(row["invoice_id"]),
                "expense_application_id": str(row["expense_application_id"]) if row["expense_application_id"] else None,
                "first_tenant_id": str(row["first_tenant_id"]),
                "first_invoice_id": str(row["first_invoice_id"]),
                "first_reported_at": first_reported.isoformat() if hasattr(first_reported, "isoformat") else str(first_reported),
                "total_usage_count": int(row["total_usage_count"]),
                "is_cross_brand": str(row["first_tenant_id"]) != str(tenant_id),
                "reported_at": reported.isoformat() if hasattr(reported, "isoformat") else str(reported),
                "resolved_at": resolved.isoformat() if resolved and hasattr(resolved, "isoformat") else (str(resolved) if resolved else None),
                "resolve_note": row["resolve_note"],
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_dedup_stats(self, db: AsyncSession, tenant_id: UUID) -> dict:
        """
        统计本租户发票去重数据。

        返回：
        {
            "total_checked": int,           # 参与去重检查的发票数
            "duplicate_found": int,          # 发现重复次数（含同品牌+跨品牌）
            "cross_brand_duplicate": int,    # 跨品牌重复次数（严重）
            "resolved_count": int,           # 已处理的可疑记录数
            "unresolved_count": int,         # 待处理的可疑记录数
        }
        """
        sql = """
            SELECT
                COUNT(cr.id) AS total_checked,
                COUNT(cr.id) FILTER (WHERE dg.total_usage_count > 1) AS duplicate_found,
                COUNT(cr.id) FILTER (WHERE dg.is_suspicious = TRUE
                                     AND cr.tenant_id != dg.first_tenant_id) AS cross_brand_duplicate,
                COUNT(dg.group_id) FILTER (WHERE dg.is_suspicious = TRUE
                                            AND dg.resolved_at IS NOT NULL
                                            AND cr.tenant_id = :tenant_id) AS resolved_count,
                COUNT(dg.group_id) FILTER (WHERE dg.is_suspicious = TRUE
                                            AND dg.resolved_at IS NULL
                                            AND cr.tenant_id = :tenant_id) AS unresolved_count
            FROM group_invoice_cross_ref cr
            JOIN invoice_dedup_groups dg ON dg.group_id = cr.group_id
            WHERE cr.tenant_id = :tenant_id
        """
        try:
            result = await db.execute(text(sql), {"tenant_id": str(tenant_id)})
            row = result.mappings().one_or_none()
        except SQLAlchemyError as exc:
            logger.error(
                "invoice_dedup_get_stats_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )
            return {
                "total_checked": 0,
                "duplicate_found": 0,
                "cross_brand_duplicate": 0,
                "resolved_count": 0,
                "unresolved_count": 0,
            }

        if row is None:
            return {
                "total_checked": 0,
                "duplicate_found": 0,
                "cross_brand_duplicate": 0,
                "resolved_count": 0,
                "unresolved_count": 0,
            }

        return {
            "total_checked": int(row["total_checked"] or 0),
            "duplicate_found": int(row["duplicate_found"] or 0),
            "cross_brand_duplicate": int(row["cross_brand_duplicate"] or 0),
            "resolved_count": int(row["resolved_count"] or 0),
            "unresolved_count": int(row["unresolved_count"] or 0),
        }

    async def mark_resolved(
        self,
        db: AsyncSession,
        group_id: str,
        resolved_by: UUID,
        note: str,
    ) -> None:
        """
        标记去重组为已处理（人工确认合规或驳回）。

        Raises:
            LookupError: group_id 不存在时抛出（路由层转 404）
            ValueError: 已经处理过时抛出（路由层转 400）
        """
        check_sql = text("""
            SELECT group_id, resolved_at
            FROM invoice_dedup_groups
            WHERE group_id = :group_id
        """)
        try:
            check_result = await db.execute(check_sql, {"group_id": group_id})
            row = check_result.mappings().one_or_none()
        except SQLAlchemyError as exc:
            logger.error(
                "invoice_dedup_mark_resolved_check_error",
                error=str(exc),
                group_id=group_id,
                exc_info=True,
            )
            raise

        if row is None:
            raise LookupError(f"invoice_dedup_groups 中不存在 group_id: {group_id}")

        if row["resolved_at"] is not None:
            raise ValueError(
                f"去重组 {group_id} 已于 {row['resolved_at']} 处理，请勿重复提交"
            )

        now = _now_utc()
        try:
            await db.execute(
                text("""
                    UPDATE invoice_dedup_groups SET
                        resolved_at = :resolved_at,
                        resolved_by = :resolved_by,
                        resolve_note = :note,
                        updated_at = :now
                    WHERE group_id = :group_id
                """),
                {
                    "resolved_at": now,
                    "resolved_by": str(resolved_by),
                    "note": note,
                    "now": now,
                    "group_id": group_id,
                },
            )
            await db.flush()
        except SQLAlchemyError as exc:
            logger.error(
                "invoice_dedup_mark_resolved_update_error",
                error=str(exc),
                group_id=group_id,
                exc_info=True,
            )
            raise

        logger.info(
            "invoice_dedup_resolved",
            group_id=group_id,
            resolved_by=str(resolved_by),
        )


# 单例（路由层通过依赖注入使用）
invoice_dedup_service = InvoiceDedupService()
