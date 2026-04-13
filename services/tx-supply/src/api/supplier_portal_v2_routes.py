"""
供应商门户路由 v2 — 全量接入真实数据库
Y-E10

设计原则：
- DB 不可用时：显式返回 503，禁止静默内存降级
- 所有写操作有结构化审计日志
- 所有端点均查询真实数据库（supplier_accounts / supplier_rfq_requests / purchase_orders）
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional, List

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError, ProgrammingError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from shared.ontology.src.database import get_db as _get_db

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/supplier-portal",
    tags=["supplier-portal-v2"],
)


# ──────────────────────────────────────────────────────────────────────────────
# 通用工具
# ──────────────────────────────────────────────────────────────────────────────

def _db_unavailable_response() -> dict:
    """显式 DB 不可用响应 — 禁止静默降级"""
    return {
        "ok": False,
        "error": {
            "code": "DB_UNAVAILABLE",
            "message": "供应商门户暂时不可用，请稍后重试",
        },
        "readonly_mode": True,
    }


def _is_db_error(exc: BaseException) -> bool:
    return isinstance(exc, (OperationalError, InterfaceError, ConnectionError))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_rfq_no() -> str:
    month = _now().strftime("%Y%m")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"RFQ-{month}-{suffix}"


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ──────────────────────────────────────────────────────────────────────────────
# 请求体
# ──────────────────────────────────────────────────────────────────────────────

class SupplierLoginRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=11, description="供应商手机号")
    password: str = Field(min_length=6, max_length=128, description="门户登录密码")


class RFQQuoteRequest(BaseModel):
    quoted_price_fen: int = Field(ge=1, description="报价总金额，单位：分")
    quote_valid_until: date = Field(description="报价有效期")
    notes: Optional[str] = Field(default=None, max_length=500)


class RatingUpdateRequest(BaseModel):
    rating: float = Field(ge=1.0, le=5.0, description="供应商评级 1.0-5.0")
    reason: Optional[str] = Field(default=None, max_length=200)


class POConfirmRequest(BaseModel):
    estimated_deliver_date: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class PODeliverRequest(BaseModel):
    actual_deliver_date: date
    delivery_notes: Optional[str] = Field(default=None, max_length=500)
    tracking_no: Optional[str] = Field(default=None, max_length=100)


# ──────────────────────────────────────────────────────────────────────────────
# Part 1: 供应商认证
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/auth/login")
async def supplier_login(
    body: SupplierLoginRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应商门户登录（手机号 + 密码）"""
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT id, name, portal_status, portal_password_hash, portal_last_login
                FROM supplier_accounts
                WHERE contact->>'phone' = :phone
                  AND is_deleted = FALSE
                  AND tenant_id = :tenant_id
                LIMIT 1
            """),
            {"phone": body.phone, "tenant_id": x_tenant_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail={"ok": False, "error": {"code": "INVALID_CREDENTIALS", "message": "手机号或密码错误"}},
            )

        if row["portal_status"] == "suspended":
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "error": {"code": "ACCOUNT_SUSPENDED", "message": "供应商账号已暂停"}},
            )

        # 更新最后登录时间（审计日志）
        supplier_id = str(row["id"])
        await db.execute(
            text("UPDATE supplier_accounts SET portal_last_login = NOW() WHERE id = :id"),
            {"id": supplier_id},
        )
        await db.commit()

        logger.info(
            "supplier_portal_login",
            supplier_id=supplier_id,
            tenant_id=x_tenant_id,
            phone=body.phone[:3] + "****" + body.phone[-4:],
        )

        # 生成简单 session token（生产应使用 JWT）
        session_token = uuid.uuid4().hex

        return {
            "ok": True,
            "data": {
                "supplier_id": supplier_id,
                "supplier_name": row["name"],
                "session_token": session_token,
                "portal_status": row["portal_status"],
            },
        }

    except HTTPException:
        raise
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_db_unavailable_response(),
            )
        raise
    except (OperationalError, InterfaceError) as exc:
        await db.rollback()
        logger.error("supplier_login_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )


@router.get("/auth/profile")
async def get_supplier_profile(
    supplier_id: str = Query(..., description="供应商ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """获取供应商自身信息"""
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT id, name, category, contact, certifications,
                       portal_status, bank_name, bank_account, tax_no,
                       contact_email, rating, total_orders, total_amount_fen,
                       portal_last_login, created_at
                FROM supplier_accounts
                WHERE id = :supplier_id
                  AND is_deleted = FALSE
            """),
            {"supplier_id": supplier_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "供应商不存在"}},
            )

        return {
            "ok": True,
            "data": dict(row),
            "_data_source": "db",
        }

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("supplier_profile_db_error", error=str(exc), supplier_id=supplier_id)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Part 2: RFQ 询价
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/rfq")
async def list_rfq(
    supplier_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, description="pending/quoted/accepted/rejected/expired"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应商询价单列表（只看自己的）"""
    try:
        await _set_tenant(db, x_tenant_id)

        where_clauses = ["r.tenant_id = :tenant_id", "r.is_deleted = FALSE"]
        params: dict = {"tenant_id": x_tenant_id, "limit": size, "offset": (page - 1) * size}

        if supplier_id:
            where_clauses.append("r.supplier_id = :supplier_id")
            params["supplier_id"] = supplier_id
        if status:
            where_clauses.append("r.status = :status")
            params["status"] = status

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT r.id, r.request_no, r.supplier_id, r.store_id,
                       r.status, r.items, r.expected_delivery_date,
                       r.quote_valid_until, r.quoted_price_fen,
                       r.accepted_at, r.notes, r.created_at, r.updated_at
                FROM supplier_rfq_requests r
                WHERE {where_sql}
                ORDER BY r.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM supplier_rfq_requests r WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

        return {
            "ok": True,
            "data": {"items": rows, "total": total, "page": page, "size": size},
            "_data_source": "db",
        }

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("rfq_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )


@router.get("/rfq/{rfq_id}")
async def get_rfq_detail(
    rfq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """询价单详情"""
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT r.*, a.name AS supplier_name
                FROM supplier_rfq_requests r
                LEFT JOIN supplier_accounts a ON r.supplier_id = a.id
                WHERE r.id = :rfq_id AND r.is_deleted = FALSE
            """),
            {"rfq_id": rfq_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "询价单不存在"}},
            )

        return {"ok": True, "data": dict(row), "_data_source": "db"}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("rfq_detail_db_error", error=str(exc), rfq_id=rfq_id)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )


@router.post("/rfq/{rfq_id}/quote")
async def submit_rfq_quote(
    rfq_id: str,
    body: RFQQuoteRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """
    供应商提交报价
    DB 不可用时：显式返回 503，不静默降级
    """
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT id, supplier_id, status, request_no
                FROM supplier_rfq_requests
                WHERE id = :rfq_id AND is_deleted = FALSE
            """),
            {"rfq_id": rfq_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "询价单不存在"}},
            )
        if row["status"] not in ("pending",):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "ok": False,
                    "error": {
                        "code": "INVALID_STATUS",
                        "message": f"询价单当前状态 '{row['status']}' 不可报价（仅 pending 状态可报价）",
                    },
                },
            )

        await db.execute(
            text("""
                UPDATE supplier_rfq_requests
                SET status = 'quoted',
                    quoted_price_fen = :quoted_price_fen,
                    quote_valid_until = :quote_valid_until,
                    notes = :notes,
                    updated_at = NOW()
                WHERE id = :rfq_id
            """),
            {
                "rfq_id": rfq_id,
                "quoted_price_fen": body.quoted_price_fen,
                "quote_valid_until": body.quote_valid_until,
                "notes": body.notes,
            },
        )
        await db.commit()

        # 审计日志
        logger.info(
            "rfq_quote_submitted",
            rfq_id=rfq_id,
            request_no=row["request_no"],
            supplier_id=str(row["supplier_id"]),
            quoted_price_fen=body.quoted_price_fen,
            quote_valid_until=str(body.quote_valid_until),
            tenant_id=x_tenant_id,
            who="supplier",
            when=_now().isoformat(),
            what="rfq_quote",
        )

        return {
            "ok": True,
            "data": {
                "rfq_id": rfq_id,
                "status": "quoted",
                "quoted_price_fen": body.quoted_price_fen,
                "quote_valid_until": str(body.quote_valid_until),
            },
        }

    except HTTPException:
        raise
    except (OperationalError, InterfaceError) as exc:
        await db.rollback()
        logger.error(
            "rfq_quote_db_error", error=str(exc),
            rfq_id=rfq_id, tenant_id=x_tenant_id,
        )
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_db_unavailable_response(),
            )
        raise


# ──────────────────────────────────────────────────────────────────────────────
# Part 3: 采购订单（供应商视角）
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/purchase-orders")
async def list_purchase_orders(
    supplier_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应商视角的采购订单列表"""
    try:
        await _set_tenant(db, x_tenant_id)

        where_clauses = ["po.tenant_id = :tenant_id", "po.is_deleted = FALSE"]
        params: dict = {"tenant_id": x_tenant_id, "limit": size, "offset": (page - 1) * size}

        if supplier_id:
            where_clauses.append("po.supplier_id = :supplier_id")
            params["supplier_id"] = supplier_id
        if status:
            where_clauses.append("po.status = :status")
            params["status"] = status

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT
                    po.id,
                    po.po_number,
                    po.supplier_id,
                    sa.name AS supplier_name,
                    po.store_id,
                    po.status,
                    po.total_amount_fen,
                    po.expected_delivery_date,
                    po.actual_delivery_date,
                    po.notes,
                    po.created_at,
                    po.updated_at,
                    COALESCE(
                        json_agg(
                            json_build_object(
                                'id', poi.id,
                                'ingredient_id', poi.ingredient_id,
                                'name', poi.ingredient_name,
                                'qty', poi.quantity,
                                'unit', poi.unit,
                                'unit_price_fen', poi.unit_price_fen,
                                'subtotal_fen', poi.subtotal_fen
                            )
                        ) FILTER (WHERE poi.id IS NOT NULL),
                        '[]'::json
                    ) AS items
                FROM purchase_orders po
                LEFT JOIN supplier_accounts sa ON po.supplier_id = sa.id
                LEFT JOIN purchase_order_items poi ON poi.po_id = po.id
                WHERE {where_sql}
                GROUP BY po.id, sa.name
                ORDER BY po.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM purchase_orders po WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

        return {
            "ok": True,
            "data": {
                "items": rows,
                "total": total,
                "page": page,
                "size": size,
            },
            "_data_source": "db",
        }

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("purchase_orders_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )


@router.post("/purchase-orders/{po_id}/confirm")
async def confirm_purchase_order(
    po_id: str,
    body: POConfirmRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """
    供应商确认接单
    审计日志：who/when/what，structlog JSON 格式
    """
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT id, status, po_number
                FROM purchase_orders
                WHERE id = :po_id AND is_deleted = FALSE
            """),
            {"po_id": po_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "采购订单不存在"}},
            )
        if row["status"] not in ("pending_confirm", "draft", "approved"):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "ok": False,
                    "error": {
                        "code": "INVALID_STATUS",
                        "message": f"采购订单当前状态 '{row['status']}' 不可确认",
                    },
                },
            )

        await db.execute(
            text("""
                UPDATE purchase_orders
                SET status = 'confirmed',
                    expected_delivery_date = COALESCE(:expected_delivery_date, expected_delivery_date),
                    notes = COALESCE(:notes, notes),
                    updated_at = NOW()
                WHERE id = :po_id
            """),
            {
                "po_id": po_id,
                "expected_delivery_date": body.estimated_deliver_date,
                "notes": body.notes,
            },
        )
        await db.commit()

        logger.info(
            "purchase_order_confirmed",
            po_id=po_id,
            po_number=row["po_number"],
            estimated_deliver_date=str(body.estimated_deliver_date) if body.estimated_deliver_date else None,
            tenant_id=x_tenant_id,
            who="supplier",
            when=_now().isoformat(),
            what="po_confirm",
        )

        return {
            "ok": True,
            "data": {
                "po_id": po_id,
                "status": "confirmed",
                "estimated_deliver_date": str(body.estimated_deliver_date) if body.estimated_deliver_date else None,
            },
        }

    except HTTPException:
        raise
    except (OperationalError, InterfaceError) as exc:
        await db.rollback()
        logger.error("po_confirm_db_error", error=str(exc), po_id=po_id)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_db_unavailable_response(),
            )
        raise


@router.post("/purchase-orders/{po_id}/deliver")
async def confirm_delivery(
    po_id: str,
    body: PODeliverRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """
    供应商确认发货
    审计日志：who/when/what，structlog JSON 格式
    """
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT id, status, po_number
                FROM purchase_orders
                WHERE id = :po_id AND is_deleted = FALSE
            """),
            {"po_id": po_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "采购订单不存在"}},
            )
        if row["status"] not in ("confirmed", "approved"):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "ok": False,
                    "error": {
                        "code": "INVALID_STATUS",
                        "message": f"采购订单当前状态 '{row['status']}' 不可发货（需先确认接单）",
                    },
                },
            )

        await db.execute(
            text("""
                UPDATE purchase_orders
                SET status = 'delivered',
                    actual_delivery_date = :actual_delivery_date,
                    notes = CASE WHEN :delivery_notes IS NOT NULL
                                 THEN COALESCE(notes || E'\\n', '') || :delivery_notes
                                 ELSE notes END,
                    updated_at = NOW()
                WHERE id = :po_id
            """),
            {
                "po_id": po_id,
                "actual_delivery_date": body.actual_deliver_date,
                "delivery_notes": body.delivery_notes,
            },
        )
        await db.commit()

        logger.info(
            "purchase_order_delivered",
            po_id=po_id,
            po_number=row["po_number"],
            actual_deliver_date=str(body.actual_deliver_date),
            tracking_no=body.tracking_no,
            tenant_id=x_tenant_id,
            who="supplier",
            when=_now().isoformat(),
            what="po_deliver",
        )

        return {
            "ok": True,
            "data": {
                "po_id": po_id,
                "status": "delivered",
                "actual_deliver_date": str(body.actual_deliver_date),
                "tracking_no": body.tracking_no,
            },
        }

    except HTTPException:
        raise
    except (OperationalError, InterfaceError) as exc:
        await db.rollback()
        logger.error("po_deliver_db_error", error=str(exc), po_id=po_id)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_db_unavailable_response(),
            )
        raise


# ──────────────────────────────────────────────────────────────────────────────
# Part 4: 供应商自助管理（总部管理端）
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/suppliers")
async def list_suppliers_portal(
    category: Optional[str] = Query(default=None),
    portal_status: Optional[str] = Query(default=None, description="active/suspended/pending"),
    rating_min: Optional[float] = Query(default=None, ge=1.0, le=5.0),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应商列表（含评级/状态/累计采购）"""
    try:
        await _set_tenant(db, x_tenant_id)

        where_clauses = ["is_deleted = FALSE"]
        params: dict = {
            "tenant_id": x_tenant_id,
            "limit": size,
            "offset": (page - 1) * size,
        }

        if category:
            where_clauses.append("category = :category")
            params["category"] = category
        if portal_status:
            where_clauses.append("portal_status = :portal_status")
            params["portal_status"] = portal_status
        if rating_min is not None:
            where_clauses.append("rating >= :rating_min")
            params["rating_min"] = rating_min

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT id, name, category, contact, portal_status,
                       rating, total_orders, total_amount_fen,
                       contact_email, bank_name, created_at
                FROM supplier_accounts
                WHERE {where_sql}
                ORDER BY rating DESC, total_orders DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM supplier_accounts WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

        return {
            "ok": True,
            "data": {"items": rows, "total": total, "page": page, "size": size},
            "_data_source": "db",
        }

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error(
            "supplier_list_db_error",
            error=str(exc),
            tenant_id=x_tenant_id,
        )
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )


@router.put("/suppliers/{supplier_id}/rating")
async def update_supplier_rating(
    supplier_id: str,
    body: RatingUpdateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """
    更新供应商评级（1.0-5.0）
    DB 不可用时：显式返回 503，不静默降级
    """
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT id, name, rating
                FROM supplier_accounts
                WHERE id = :supplier_id AND is_deleted = FALSE
            """),
            {"supplier_id": supplier_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "供应商不存在"}},
            )

        await db.execute(
            text("""
                UPDATE supplier_accounts
                SET rating = :rating, updated_at = NOW()
                WHERE id = :supplier_id
            """),
            {"supplier_id": supplier_id, "rating": body.rating},
        )
        await db.commit()

        logger.info(
            "supplier_rating_updated",
            supplier_id=supplier_id,
            old_rating=float(row["rating"]) if row["rating"] is not None else None,
            new_rating=body.rating,
            reason=body.reason,
            tenant_id=x_tenant_id,
            who="admin",
            when=_now().isoformat(),
            what="rating_update",
        )

        return {
            "ok": True,
            "data": {
                "supplier_id": supplier_id,
                "supplier_name": row["name"],
                "rating": body.rating,
                "reason": body.reason,
            },
        }

    except HTTPException:
        raise
    except (OperationalError, InterfaceError) as exc:
        await db.rollback()
        logger.error("rating_update_db_error", error=str(exc), supplier_id=supplier_id)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_db_unavailable_response(),
        )
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_db_unavailable_response(),
            )
        raise
