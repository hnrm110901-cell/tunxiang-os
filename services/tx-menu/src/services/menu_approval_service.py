"""菜单下发审批流服务

职责：
- 创建集团/品牌向门店的菜单变更下发申请
- 审批通过 / 拒绝申请
- 执行已批准的变更到目标门店（add_dish / update_price / deactivate / clone_menu）
- 查询申请列表（分页）
- 管理门店菜单自主修改权限
- 新店开业一键复制菜单（跳过审批流）

所有金额单位：分（int）。
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ─── Pydantic 数据模型 ────────────────────────────────────────────────────────


class MenuPublishRequest(BaseModel):
    id: UUID
    tenant_id: UUID
    request_no: str
    source_type: str
    target_store_ids: list[UUID]
    change_type: str
    change_payload: dict
    status: str
    approver_id: Optional[UUID]
    approver_note: Optional[str]
    approved_at: Optional[datetime]
    applied_at: Optional[datetime]
    apply_error: Optional[str]
    expires_at: Optional[datetime]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime


class ApplyResult(BaseModel):
    request_id: UUID
    success_stores: list[UUID]
    failed_stores: list[UUID]
    errors: dict[str, str]  # store_id -> error_message


class StoreMenuPermission(BaseModel):
    store_id: UUID
    can_add_dish: bool
    can_modify_price: bool
    price_range_pct: float
    can_deactivate_dish: bool
    can_add_category: bool


class StoreMenuPermissionUpdate(BaseModel):
    can_add_dish: Optional[bool] = None
    can_modify_price: Optional[bool] = None
    price_range_pct: Optional[float] = None
    can_deactivate_dish: Optional[bool] = None
    can_add_category: Optional[bool] = None


class CloneResult(BaseModel):
    source_store_id: UUID
    target_store_id: UUID
    cloned_dishes: int
    cloned_categories: int
    skipped: int


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────


def _generate_request_no() -> str:
    """生成请求编号：MR + YYYYMMDD + 4位随机大写字母"""
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase, k=4))
    return f"MR{date_str}{suffix}"


def _row_to_request(row: dict) -> MenuPublishRequest:
    return MenuPublishRequest(
        id=row["id"],
        tenant_id=row["tenant_id"],
        request_no=row["request_no"],
        source_type=row["source_type"],
        target_store_ids=row["target_store_ids"] or [],
        change_type=row["change_type"],
        change_payload=row["change_payload"] or {},
        status=row["status"],
        approver_id=row.get("approver_id"),
        approver_note=row.get("approver_note"),
        approved_at=row.get("approved_at"),
        applied_at=row.get("applied_at"),
        apply_error=row.get("apply_error"),
        expires_at=row.get("expires_at"),
        created_by=row.get("created_by"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_permission(row: dict) -> StoreMenuPermission:
    return StoreMenuPermission(
        store_id=row["store_id"],
        can_add_dish=row["can_add_dish"],
        can_modify_price=row["can_modify_price"],
        price_range_pct=float(row["price_range_pct"]),
        can_deactivate_dish=row["can_deactivate_dish"],
        can_add_category=row["can_add_category"],
    )


# ─── Service ─────────────────────────────────────────────────────────────────


class MenuApprovalService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── 申请管理 ──────────────────────────────────────────────────────────────

    async def create_publish_request(
        self,
        tenant_id: UUID,
        source_type: str,
        target_store_ids: list[UUID],
        change_type: str,
        change_payload: dict,
        created_by: UUID,
        expires_hours: int = 48,
    ) -> MenuPublishRequest:
        """创建下发申请，生成请求编号（MR+时间戳+4位随机大写字母）"""
        request_no = _generate_request_no()
        store_ids_pg = "{" + ",".join(str(sid) for sid in target_store_ids) + "}"

        result = await self._db.execute(
            text("""
                INSERT INTO menu_publish_requests (
                    tenant_id, request_no, source_type, target_store_ids,
                    change_type, change_payload, status, expires_at, created_by
                ) VALUES (
                    :tenant_id, :request_no, :source_type, :store_ids::UUID[],
                    :change_type, :change_payload::JSONB, 'pending',
                    NOW() + (:expires_hours || ' hours')::INTERVAL,
                    :created_by
                )
                RETURNING *
            """),
            {
                "tenant_id": str(tenant_id),
                "request_no": request_no,
                "source_type": source_type,
                "store_ids": store_ids_pg,
                "change_type": change_type,
                "change_payload": __import__("json").dumps(change_payload),
                "expires_hours": expires_hours,
                "created_by": str(created_by),
            },
        )
        row = result.mappings().one()
        await self._db.commit()
        log.info("menu_publish_request.created", request_no=request_no, tenant_id=str(tenant_id))
        return _row_to_request(dict(row))

    async def approve_request(
        self,
        request_id: UUID,
        approver_id: UUID,
        note: str = "",
    ) -> MenuPublishRequest:
        """审批通过，状态变为 approved"""
        result = await self._db.execute(
            text("""
                UPDATE menu_publish_requests
                SET status       = 'approved',
                    approver_id  = :approver_id,
                    approver_note = :note,
                    approved_at  = NOW(),
                    updated_at   = NOW()
                WHERE id = :id AND status = 'pending'
                RETURNING *
            """),
            {"id": str(request_id), "approver_id": str(approver_id), "note": note},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError(f"Request {request_id} not found or not in pending status")
        await self._db.commit()
        log.info("menu_publish_request.approved", request_id=str(request_id))
        return _row_to_request(dict(row))

    async def reject_request(
        self,
        request_id: UUID,
        approver_id: UUID,
        note: str,
    ) -> MenuPublishRequest:
        """拒绝申请"""
        result = await self._db.execute(
            text("""
                UPDATE menu_publish_requests
                SET status        = 'rejected',
                    approver_id   = :approver_id,
                    approver_note = :note,
                    approved_at   = NOW(),
                    updated_at    = NOW()
                WHERE id = :id AND status = 'pending'
                RETURNING *
            """),
            {"id": str(request_id), "approver_id": str(approver_id), "note": note},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError(f"Request {request_id} not found or not in pending status")
        await self._db.commit()
        log.info("menu_publish_request.rejected", request_id=str(request_id))
        return _row_to_request(dict(row))

    async def apply_approved_request(self, request_id: UUID) -> ApplyResult:
        """执行已审批的菜单变更到目标门店

        支持变更类型：
          - add_dish:      将菜品复制到目标门店的菜单
          - update_price:  更新目标门店的菜品价格（受 store_menu_permissions 约束）
          - deactivate:    在目标门店下架指定菜品
          - clone_menu:    完整复制源门店菜单到目标门店（新店开业用）
        """
        req_result = await self._db.execute(
            text("SELECT * FROM menu_publish_requests WHERE id = :id"),
            {"id": str(request_id)},
        )
        row = req_result.mappings().one_or_none()
        if row is None:
            raise ValueError(f"Request {request_id} not found")
        req = _row_to_request(dict(row))

        if req.status != "approved":
            raise ValueError(f"Request {request_id} is not in approved status (current: {req.status})")

        success_stores: list[UUID] = []
        failed_stores: list[UUID] = []
        errors: dict[str, str] = {}

        for store_id in req.target_store_ids:
            try:
                await self._apply_change_to_store(
                    store_id=store_id,
                    tenant_id=req.tenant_id,
                    change_type=req.change_type,
                    change_payload=req.change_payload,
                )
                success_stores.append(store_id)
            except (ValueError, RuntimeError, KeyError) as exc:
                failed_stores.append(store_id)
                errors[str(store_id)] = str(exc)
                log.warning(
                    "menu_apply.store_failed",
                    request_id=str(request_id),
                    store_id=str(store_id),
                    error=str(exc),
                )

        final_status = "applied" if not failed_stores else "failed"
        error_summary = "; ".join(f"{k}: {v}" for k, v in errors.items()) if errors else None

        await self._db.execute(
            text("""
                UPDATE menu_publish_requests
                SET status      = :status,
                    applied_at  = NOW(),
                    apply_error = :apply_error,
                    updated_at  = NOW()
                WHERE id = :id
            """),
            {"id": str(request_id), "status": final_status, "apply_error": error_summary},
        )
        await self._db.commit()
        log.info(
            "menu_publish_request.applied",
            request_id=str(request_id),
            status=final_status,
            success=len(success_stores),
            failed=len(failed_stores),
        )
        return ApplyResult(
            request_id=request_id,
            success_stores=success_stores,
            failed_stores=failed_stores,
            errors=errors,
        )

    async def _apply_change_to_store(
        self,
        store_id: UUID,
        tenant_id: UUID,
        change_type: str,
        change_payload: dict,
    ) -> None:
        """将单条变更应用到指定门店（内部方法）"""
        if change_type == "add_dish":
            dish_id = change_payload["dish_id"]
            await self._db.execute(
                text("""
                    INSERT INTO store_dish_overrides (tenant_id, store_id, dish_id, is_active, created_at, updated_at)
                    VALUES (:tenant_id, :store_id, :dish_id, TRUE, NOW(), NOW())
                    ON CONFLICT (tenant_id, store_id, dish_id) DO UPDATE
                        SET is_active = TRUE, updated_at = NOW()
                """),
                {"tenant_id": str(tenant_id), "store_id": str(store_id), "dish_id": str(dish_id)},
            )

        elif change_type == "update_price":
            dish_id = change_payload["dish_id"]
            new_price_fen: int = change_payload["new_price_fen"]
            # 检查门店价格修改权限
            perm = await self.get_store_permission(store_id=store_id, tenant_id=tenant_id)
            if perm.can_modify_price:
                orig_result = await self._db.execute(
                    text("""
                        SELECT price_fen FROM dishes
                        WHERE id = :dish_id AND tenant_id = :tenant_id
                    """),
                    {"dish_id": str(dish_id), "tenant_id": str(tenant_id)},
                )
                orig_row = orig_result.mappings().one_or_none()
                if orig_row is not None:
                    allowed = await self.check_price_permission(
                        store_id=store_id,
                        tenant_id=tenant_id,
                        original_price_fen=orig_row["price_fen"],
                        new_price_fen=new_price_fen,
                    )
                    if not allowed:
                        raise ValueError(
                            f"Price change for dish {dish_id} exceeds allowed range "
                            f"({perm.price_range_pct}%) for store {store_id}"
                        )
            await self._db.execute(
                text("""
                    INSERT INTO store_dish_overrides (
                        tenant_id, store_id, dish_id, override_price_fen, is_active, created_at, updated_at
                    )
                    VALUES (:tenant_id, :store_id, :dish_id, :price_fen, TRUE, NOW(), NOW())
                    ON CONFLICT (tenant_id, store_id, dish_id) DO UPDATE
                        SET override_price_fen = :price_fen, updated_at = NOW()
                """),
                {
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "dish_id": str(dish_id),
                    "price_fen": new_price_fen,
                },
            )

        elif change_type == "deactivate":
            dish_id = change_payload["dish_id"]
            await self._db.execute(
                text("""
                    INSERT INTO store_dish_overrides (tenant_id, store_id, dish_id, is_active, created_at, updated_at)
                    VALUES (:tenant_id, :store_id, :dish_id, FALSE, NOW(), NOW())
                    ON CONFLICT (tenant_id, store_id, dish_id) DO UPDATE
                        SET is_active = FALSE, updated_at = NOW()
                """),
                {"tenant_id": str(tenant_id), "store_id": str(store_id), "dish_id": str(dish_id)},
            )

        elif change_type == "clone_menu":
            source_store_id = UUID(change_payload["source_store_id"])
            await self.clone_store_menu(
                source_store_id=source_store_id,
                target_store_id=store_id,
                tenant_id=tenant_id,
            )

        else:
            raise ValueError(f"Unknown change_type: {change_type}")

    async def get_requests(
        self,
        tenant_id: UUID,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[MenuPublishRequest], int]:
        """获取申请列表（分页）"""
        offset = (page - 1) * size
        params: dict = {"tenant_id": str(tenant_id), "limit": size, "offset": offset}

        status_clause = ""
        if status:
            status_clause = "AND status = :status"
            params["status"] = status

        rows_result = await self._db.execute(
            text(f"""
                SELECT * FROM menu_publish_requests
                WHERE tenant_id = :tenant_id {status_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = rows_result.mappings().all()

        count_result = await self._db.execute(
            text(f"""
                SELECT COUNT(*) AS total FROM menu_publish_requests
                WHERE tenant_id = :tenant_id {status_clause}
            """),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

        return [_row_to_request(dict(r)) for r in rows], int(total)

    async def get_request_by_id(self, request_id: UUID, tenant_id: UUID) -> Optional[MenuPublishRequest]:
        """按 ID 查询单条申请"""
        result = await self._db.execute(
            text("SELECT * FROM menu_publish_requests WHERE id = :id AND tenant_id = :tenant_id"),
            {"id": str(request_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().one_or_none()
        return _row_to_request(dict(row)) if row else None

    # ── 门店权限管理 ──────────────────────────────────────────────────────────

    async def get_store_permission(self, store_id: UUID, tenant_id: UUID) -> StoreMenuPermission:
        """获取门店菜单权限，不存在则返回默认值（除 can_deactivate_dish 外全部禁止）"""
        result = await self._db.execute(
            text("""
                SELECT * FROM store_menu_permissions
                WHERE store_id = :store_id AND tenant_id = :tenant_id
            """),
            {"store_id": str(store_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return StoreMenuPermission(
                store_id=store_id,
                can_add_dish=False,
                can_modify_price=False,
                price_range_pct=10.0,
                can_deactivate_dish=True,
                can_add_category=False,
            )
        return _row_to_permission(dict(row))

    async def update_store_permission(
        self,
        store_id: UUID,
        tenant_id: UUID,
        permission: StoreMenuPermissionUpdate,
    ) -> StoreMenuPermission:
        """更新门店菜单权限（不存在则创建）"""
        updates: dict = {}
        if permission.can_add_dish is not None:
            updates["can_add_dish"] = permission.can_add_dish
        if permission.can_modify_price is not None:
            updates["can_modify_price"] = permission.can_modify_price
        if permission.price_range_pct is not None:
            updates["price_range_pct"] = permission.price_range_pct
        if permission.can_deactivate_dish is not None:
            updates["can_deactivate_dish"] = permission.can_deactivate_dish
        if permission.can_add_category is not None:
            updates["can_add_category"] = permission.can_add_category

        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        if set_clauses:
            set_clauses += ", updated_at = NOW()"
        else:
            set_clauses = "updated_at = NOW()"

        params = {**updates, "store_id": str(store_id), "tenant_id": str(tenant_id)}

        result = await self._db.execute(
            text(f"""
                INSERT INTO store_menu_permissions (tenant_id, store_id)
                VALUES (:tenant_id, :store_id)
                ON CONFLICT (tenant_id, store_id) DO UPDATE
                    SET {set_clauses}
                RETURNING *
            """),
            params,
        )
        row = result.mappings().one()
        await self._db.commit()
        log.info("store_menu_permission.updated", store_id=str(store_id), tenant_id=str(tenant_id))
        return _row_to_permission(dict(row))

    async def check_price_permission(
        self,
        store_id: UUID,
        tenant_id: UUID,
        original_price_fen: int,
        new_price_fen: int,
    ) -> bool:
        """校验门店修改价格是否在允许范围内"""
        perm = await self.get_store_permission(store_id=store_id, tenant_id=tenant_id)
        if not perm.can_modify_price:
            return False
        if original_price_fen == 0:
            return True
        change_pct = abs(new_price_fen - original_price_fen) / original_price_fen * 100
        return change_pct <= perm.price_range_pct

    # ── 新店开业克隆菜单 ──────────────────────────────────────────────────────

    async def clone_store_menu(
        self,
        source_store_id: UUID,
        target_store_id: UUID,
        tenant_id: UUID,
    ) -> CloneResult:
        """新店开业一键复制菜单（跳过审批流，直接执行，使用事务保证全成功或全回滚）"""
        async with self._db.begin_nested():
            # 复制菜品分类
            cat_result = await self._db.execute(
                text("""
                    INSERT INTO menu_categories (tenant_id, store_id, name, sort_order, created_at, updated_at)
                    SELECT :target_tenant_id, :target_store_id, name, sort_order, NOW(), NOW()
                    FROM menu_categories
                    WHERE store_id = :source_store_id AND tenant_id = :tenant_id
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """),
                {
                    "target_tenant_id": str(tenant_id),
                    "target_store_id": str(target_store_id),
                    "source_store_id": str(source_store_id),
                    "tenant_id": str(tenant_id),
                },
            )
            cloned_categories = len(cat_result.fetchall())

            # 复制门店菜品覆盖配置（包含门店特有价格/激活状态）
            dish_result = await self._db.execute(
                text("""
                    INSERT INTO store_dish_overrides (
                        tenant_id, store_id, dish_id, override_price_fen,
                        is_active, created_at, updated_at
                    )
                    SELECT :target_tenant_id, :target_store_id, dish_id, override_price_fen,
                           is_active, NOW(), NOW()
                    FROM store_dish_overrides
                    WHERE store_id = :source_store_id AND tenant_id = :tenant_id
                    ON CONFLICT (tenant_id, store_id, dish_id) DO NOTHING
                    RETURNING id
                """),
                {
                    "target_tenant_id": str(tenant_id),
                    "target_store_id": str(target_store_id),
                    "source_store_id": str(source_store_id),
                    "tenant_id": str(tenant_id),
                },
            )
            cloned_dishes = len(dish_result.fetchall())

            # 统计跳过条数（已存在的）
            total_result = await self._db.execute(
                text("""
                    SELECT COUNT(*) AS total FROM store_dish_overrides
                    WHERE store_id = :source_store_id AND tenant_id = :tenant_id
                """),
                {"source_store_id": str(source_store_id), "tenant_id": str(tenant_id)},
            )
            total_source = int(total_result.scalar_one())
            skipped = total_source - cloned_dishes

        await self._db.commit()
        log.info(
            "clone_store_menu.done",
            source=str(source_store_id),
            target=str(target_store_id),
            cloned_dishes=cloned_dishes,
            cloned_categories=cloned_categories,
            skipped=skipped,
        )
        return CloneResult(
            source_store_id=source_store_id,
            target_store_id=target_store_id,
            cloned_dishes=cloned_dishes,
            cloned_categories=cloned_categories,
            skipped=skipped,
        )
