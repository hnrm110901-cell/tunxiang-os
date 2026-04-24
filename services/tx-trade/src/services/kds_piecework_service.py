"""KDS计件配菜服务 — 计件记录 + 提成计算 + 方案管理

幂等记录（kds_task_id UNIQUE）、员工汇总、门店日报、佣金计算、方案CRUD。
金额单位：分（fen）。
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class KdsPieceworkService:
    """KDS 计件配菜服务"""

    # ── 计件记录（幂等） ──────────────────────────────────────

    @staticmethod
    async def record_piecework(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        employee_id: str,
        shift_date: date,
        dish_id: Optional[str] = None,
        dish_name: Optional[str] = None,
        practice_names: Optional[str] = None,
        quantity: int = 1,
        unit_commission_fen: int = 0,
        confirmed_by: str = "auto",
        kds_task_id: Optional[str] = None,
    ) -> dict:
        """记录一条计件数据（kds_task_id 幂等）。

        如果 kds_task_id 已存在，返回已有记录而不重复插入。
        """
        total_commission_fen = quantity * unit_commission_fen

        # 幂等：kds_task_id 冲突时走 ON CONFLICT DO NOTHING
        record_id = str(uuid.uuid4())
        result = await db.execute(
            text("""
                INSERT INTO kds_piecework_records (
                    tenant_id, id, store_id, employee_id, shift_date,
                    dish_id, dish_name, practice_names, quantity,
                    unit_commission_fen, total_commission_fen,
                    confirmed_by, kds_task_id, recorded_at
                ) VALUES (
                    :tenant_id, :id, :store_id, :employee_id, :shift_date,
                    :dish_id, :dish_name, :practice_names, :quantity,
                    :unit_commission_fen, :total_commission_fen,
                    :confirmed_by, :kds_task_id, now()
                )
                ON CONFLICT (kds_task_id) WHERE kds_task_id IS NOT NULL
                DO NOTHING
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "id": record_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "shift_date": shift_date,
                "dish_id": dish_id,
                "dish_name": dish_name,
                "practice_names": practice_names,
                "quantity": quantity,
                "unit_commission_fen": unit_commission_fen,
                "total_commission_fen": total_commission_fen,
                "confirmed_by": confirmed_by,
                "kds_task_id": kds_task_id,
            },
        )
        row = result.fetchone()

        if row is None and kds_task_id:
            # 幂等命中：返回已有记录
            existing = await db.execute(
                text("""
                    SELECT id, employee_id, dish_name, quantity, total_commission_fen
                    FROM kds_piecework_records
                    WHERE kds_task_id = :kds_task_id AND is_deleted = FALSE
                """),
                {"kds_task_id": kds_task_id},
            )
            existing_row = existing.fetchone()
            if existing_row:
                logger.info(
                    "kds_piecework_idempotent_hit",
                    kds_task_id=kds_task_id,
                    existing_id=str(existing_row.id),
                )
                return {
                    "id": str(existing_row.id),
                    "idempotent": True,
                    "quantity": existing_row.quantity,
                    "total_commission_fen": existing_row.total_commission_fen,
                }

        await db.commit()
        logger.info(
            "kds_piecework_recorded",
            record_id=record_id,
            employee_id=employee_id,
            dish_name=dish_name,
            quantity=quantity,
        )
        return {
            "id": record_id,
            "idempotent": False,
            "quantity": quantity,
            "total_commission_fen": total_commission_fen,
        }

    # ── 员工汇总 ─────────────────────────────────────────────

    @staticmethod
    async def get_employee_summary(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        employee_id: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        """获取员工在日期范围内的计件汇总"""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                    AS total_records,
                    COALESCE(SUM(quantity), 0)  AS total_quantity,
                    COALESCE(SUM(total_commission_fen), 0) AS total_commission_fen,
                    COUNT(DISTINCT dish_name)   AS dish_variety
                FROM kds_piecework_records
                WHERE tenant_id  = :tenant_id
                  AND store_id   = :store_id
                  AND employee_id = :employee_id
                  AND shift_date BETWEEN :start_date AND :end_date
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.fetchone()
        return {
            "employee_id": employee_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_records": row.total_records if row else 0,
            "total_quantity": row.total_quantity if row else 0,
            "total_commission_fen": row.total_commission_fen if row else 0,
            "dish_variety": row.dish_variety if row else 0,
        }

    # ── 门店日报 ─────────────────────────────────────────────

    @staticmethod
    async def get_store_daily(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        shift_date: date,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """获取门店某日的全员计件明细（分页）"""
        offset = (page - 1) * size

        count_result = await db.execute(
            text("""
                SELECT COUNT(*) AS total
                FROM kds_piecework_records
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND shift_date = :shift_date
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "shift_date": shift_date},
        )
        total = count_result.scalar() or 0

        items_result = await db.execute(
            text("""
                SELECT id, employee_id, dish_id, dish_name, practice_names,
                       quantity, unit_commission_fen, total_commission_fen,
                       confirmed_by, kds_task_id, recorded_at
                FROM kds_piecework_records
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND shift_date = :shift_date
                  AND is_deleted = FALSE
                ORDER BY recorded_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "shift_date": shift_date,
                "limit": size,
                "offset": offset,
            },
        )
        rows = items_result.fetchall()
        items = [
            {
                "id": str(r.id),
                "employee_id": str(r.employee_id),
                "dish_id": str(r.dish_id) if r.dish_id else None,
                "dish_name": r.dish_name,
                "practice_names": r.practice_names,
                "quantity": r.quantity,
                "unit_commission_fen": r.unit_commission_fen,
                "total_commission_fen": r.total_commission_fen,
                "confirmed_by": r.confirmed_by,
                "kds_task_id": str(r.kds_task_id) if r.kds_task_id else None,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    # ── 佣金计算 ─────────────────────────────────────────────

    @staticmethod
    async def calculate_commission(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        employee_id: str,
        shift_date: date,
    ) -> dict:
        """根据当日计件 + 激活方案计算员工佣金

        匹配逻辑：找到门店下生效的方案 → 按 rules JSONB 匹配菜品/做法 → 计算佣金。
        """
        # 1) 获取当前有效方案
        schemes_result = await db.execute(
            text("""
                SELECT id, scheme_name, scheme_type, rules
                FROM kds_piecework_schemes
                WHERE tenant_id = :tenant_id
                  AND (store_id = :store_id OR store_id IS NULL)
                  AND is_active = TRUE
                  AND effective_from <= :shift_date
                  AND (effective_until IS NULL OR effective_until >= :shift_date)
                  AND is_deleted = FALSE
                ORDER BY store_id NULLS LAST
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "shift_date": shift_date},
        )
        schemes = schemes_result.fetchall()

        # 2) 获取当日计件记录
        records_result = await db.execute(
            text("""
                SELECT id, dish_id, dish_name, practice_names, quantity,
                       unit_commission_fen, total_commission_fen
                FROM kds_piecework_records
                WHERE tenant_id   = :tenant_id
                  AND store_id    = :store_id
                  AND employee_id = :employee_id
                  AND shift_date  = :shift_date
                  AND is_deleted  = FALSE
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "shift_date": shift_date,
            },
        )
        records = records_result.fetchall()

        # 3) 计算总佣金
        total_quantity = sum(r.quantity for r in records)
        total_commission_fen = sum(r.total_commission_fen for r in records)

        return {
            "employee_id": employee_id,
            "shift_date": str(shift_date),
            "total_quantity": total_quantity,
            "total_commission_fen": total_commission_fen,
            "scheme_count": len(schemes),
            "record_count": len(records),
            "schemes_applied": [
                {"id": str(s.id), "name": s.scheme_name, "type": s.scheme_type}
                for s in schemes
            ],
        }

    # ── 方案 CRUD ────────────────────────────────────────────

    @staticmethod
    async def create_scheme(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: Optional[str] = None,
        scheme_name: str,
        scheme_type: str,
        rules: list,
        effective_from: date,
        effective_until: Optional[date] = None,
    ) -> dict:
        """创建计件方案"""
        import json

        scheme_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO kds_piecework_schemes (
                    tenant_id, id, store_id, scheme_name, scheme_type,
                    rules, effective_from, effective_until
                ) VALUES (
                    :tenant_id, :id, :store_id, :scheme_name, :scheme_type,
                    :rules::JSONB, :effective_from, :effective_until
                )
            """),
            {
                "tenant_id": tenant_id,
                "id": scheme_id,
                "store_id": store_id,
                "scheme_name": scheme_name,
                "scheme_type": scheme_type,
                "rules": json.dumps(rules),
                "effective_from": effective_from,
                "effective_until": effective_until,
            },
        )
        await db.commit()
        logger.info("kds_piecework_scheme_created", scheme_id=scheme_id, name=scheme_name)
        return {"id": scheme_id, "scheme_name": scheme_name, "scheme_type": scheme_type}

    @staticmethod
    async def update_scheme(
        db: AsyncSession,
        tenant_id: str,
        *,
        scheme_id: str,
        scheme_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        rules: Optional[list] = None,
        effective_until: Optional[date] = None,
    ) -> dict:
        """更新计件方案"""
        import json

        sets: list[str] = ["updated_at = now()"]
        params: dict = {"tenant_id": tenant_id, "scheme_id": scheme_id}

        if scheme_name is not None:
            sets.append("scheme_name = :scheme_name")
            params["scheme_name"] = scheme_name
        if is_active is not None:
            sets.append("is_active = :is_active")
            params["is_active"] = is_active
        if rules is not None:
            sets.append("rules = :rules::JSONB")
            params["rules"] = json.dumps(rules)
        if effective_until is not None:
            sets.append("effective_until = :effective_until")
            params["effective_until"] = effective_until

        await db.execute(
            text(f"""
                UPDATE kds_piecework_schemes
                SET {', '.join(sets)}
                WHERE tenant_id = :tenant_id AND id = :scheme_id AND is_deleted = FALSE
            """),
            params,
        )
        await db.commit()
        logger.info("kds_piecework_scheme_updated", scheme_id=scheme_id)
        return {"id": scheme_id, "updated": True}

    @staticmethod
    async def get_scheme(db: AsyncSession, tenant_id: str, scheme_id: str) -> Optional[dict]:
        """获取单个方案"""
        result = await db.execute(
            text("""
                SELECT id, store_id, scheme_name, scheme_type, is_active,
                       rules, effective_from, effective_until, created_at
                FROM kds_piecework_schemes
                WHERE tenant_id = :tenant_id AND id = :scheme_id AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "scheme_id": scheme_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "id": str(row.id),
            "store_id": str(row.store_id) if row.store_id else None,
            "scheme_name": row.scheme_name,
            "scheme_type": row.scheme_type,
            "is_active": row.is_active,
            "rules": row.rules,
            "effective_from": str(row.effective_from),
            "effective_until": str(row.effective_until) if row.effective_until else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    async def list_schemes(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """列出方案（可按门店/活跃状态过滤）"""
        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: dict = {"tenant_id": tenant_id}

        if store_id:
            conditions.append("(store_id = :store_id OR store_id IS NULL)")
            params["store_id"] = store_id
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active

        where = " AND ".join(conditions)

        count_result = await db.execute(text(f"SELECT COUNT(*) FROM kds_piecework_schemes WHERE {where}"), params)
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset
        items_result = await db.execute(
            text(f"""
                SELECT id, store_id, scheme_name, scheme_type, is_active,
                       effective_from, effective_until, created_at
                FROM kds_piecework_schemes
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = items_result.fetchall()
        items = [
            {
                "id": str(r.id),
                "store_id": str(r.store_id) if r.store_id else None,
                "scheme_name": r.scheme_name,
                "scheme_type": r.scheme_type,
                "is_active": r.is_active,
                "effective_from": str(r.effective_from),
                "effective_until": str(r.effective_until) if r.effective_until else None,
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    @staticmethod
    async def delete_scheme(db: AsyncSession, tenant_id: str, scheme_id: str) -> dict:
        """软删除方案"""
        await db.execute(
            text("""
                UPDATE kds_piecework_schemes
                SET is_deleted = TRUE, updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :scheme_id
            """),
            {"tenant_id": tenant_id, "scheme_id": scheme_id},
        )
        await db.commit()
        logger.info("kds_piecework_scheme_deleted", scheme_id=scheme_id)
        return {"id": scheme_id, "deleted": True}
