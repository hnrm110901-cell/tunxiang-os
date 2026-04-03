"""宴席定金在线支付 + 电子确认单服务

依赖表：banquet_deposits、banquet_confirmations（v043 迁移创建）
微信支付为 mock 实现，真实配置见各 TODO 注释。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import random
import string
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── Pydantic 模型 ──────────────────────────────────────────────────────────


class BanquetDeposit(BaseModel):
    id: UUID
    banquet_id: UUID
    total_deposit_fen: int
    paid_fen: int
    status: str
    due_date: Optional[date]
    paid_at: Optional[datetime]


class WechatPayResult(BaseModel):
    deposit_id: UUID
    payment_no: str
    jsapi_params: dict  # {timeStamp, nonceStr, package, signType, paySign}
    qr_code_url: Optional[str]  # 备用：Native支付二维码


class BanquetConfirmation(BaseModel):
    id: UUID
    banquet_id: UUID
    confirmation_no: str
    menu_items_json: list[dict]
    total_fen: int
    guest_count: Optional[int]
    status: str
    confirmed_at: Optional[datetime]
    expires_at: Optional[datetime]


class MenuItem(BaseModel):
    dish_id: UUID
    dish_name: str
    quantity: int
    unit_price_fen: int
    subtotal_fen: int


class ConfirmationSummary(BaseModel):
    confirmation_no: str
    banquet_id: UUID
    items: list[MenuItem]
    total_fen: int
    guest_count: Optional[int]
    confirmed_by_name: str
    confirmed_by_phone: str
    special_requirements: str
    status: str
    confirmed_at: Optional[datetime]


# ─── 工具函数 ───────────────────────────────────────────────────────────────


def _gen_payment_no() -> str:
    """生成唯一支付流水号：PAY + 时间戳毫秒 + 6位随机大写"""
    ts = int(time.time() * 1000)
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PAY{ts}{suffix}"


def _gen_confirmation_no() -> str:
    """生成确认单号：BC + YYYYMMDD + 4位随机大写字母"""
    today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase, k=4))
    return f"BC{today}{suffix}"


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _row_to_deposit(row: dict) -> BanquetDeposit:
    return BanquetDeposit(
        id=row["id"],
        banquet_id=row["banquet_id"],
        total_deposit_fen=row["total_deposit_fen"],
        paid_fen=row["paid_fen"],
        status=row["status"],
        due_date=row.get("due_date"),
        paid_at=row.get("paid_at"),
    )


def _row_to_confirmation(row: dict) -> BanquetConfirmation:
    return BanquetConfirmation(
        id=row["id"],
        banquet_id=row["banquet_id"],
        confirmation_no=row["confirmation_no"],
        menu_items_json=row["menu_items_json"] or [],
        total_fen=row["total_fen"],
        guest_count=row.get("guest_count"),
        status=row["status"],
        confirmed_at=row.get("confirmed_at"),
        expires_at=row.get("expires_at"),
    )


# ─── Mock / 占位 微信 JSAPI ─────────────────────────────────────────────────


def _build_wechat_jsapi_order_result(
    payment_no: str,
    amount_fen: int,
    openid: str,
    notify_url: str,
    *,
    existing_prepay_id: Optional[str] = None,
) -> dict:
    """生成（或复用）小程序调起支付参数。

    - 无 ``existing_prepay_id`` 时生成 ``mock_prepay_{payment_no}``，模拟统一下单。
    - 有 ``existing_prepay_id`` 时用于 **幂等重试**：前端重复调起仍用同一 prepay，仅刷新 nonce/时间戳。

    ``amount_fen`` / ``openid`` / ``notify_url`` 供真实微信 v3 JSAPI 对接时使用。

    TODO: 调用 https://api.mch.weixin.qq.com/v3/pay/transactions/jsapi
    """
    app_id = os.getenv("WECHAT_APP_ID", "wx_mock_appid")
    logger.debug(
        "banquet_wechat_jsapi_build",
        payment_no=payment_no,
        amount_fen=amount_fen,
        has_openid=bool(openid),
        has_notify=bool(notify_url),
        reuse_prepay=bool(existing_prepay_id),
    )

    prepay_id = existing_prepay_id or f"mock_prepay_{payment_no}"

    timestamp = str(int(time.time()))
    nonce_str = "".join(random.choices(string.ascii_letters + string.digits, k=32))
    package = f"prepay_id={prepay_id}"

    mock_sign = hmac.new(
        b"mock_key",
        f"{app_id}{timestamp}{nonce_str}{package}".encode(),
        hashlib.sha256,
    ).hexdigest()

    return {
        "prepay_id": prepay_id,
        "jsapi_params": {
            "timeStamp": timestamp,
            "nonceStr": nonce_str,
            "package": package,
            "signType": "RSA",
            "paySign": mock_sign,
        },
    }


# ─── Service ────────────────────────────────────────────────────────────────


class BanquetPaymentService:
    """宴席定金支付 + 电子确认单服务"""

    def __init__(self, tenant_id: str, db: AsyncSession) -> None:
        self._tenant_id = tenant_id
        self._db = db

    # ── 定金相关 ────────────────────────────────────────────────────────────

    async def create_deposit(
        self,
        banquet_id: UUID,
        tenant_id: UUID,
        total_deposit_fen: int,
        due_date: Optional[date] = None,
    ) -> BanquetDeposit:
        """创建定金记录（初始状态 pending）"""
        if total_deposit_fen <= 0:
            raise ValueError("total_deposit_fen 必须大于 0")

        result = await self._db.execute(
            text("""
                INSERT INTO banquet_deposits
                    (tenant_id, banquet_id, total_deposit_fen, due_date)
                VALUES
                    (:tenant_id, :banquet_id, :total_deposit_fen, :due_date)
                RETURNING
                    id, banquet_id, total_deposit_fen, paid_fen,
                    status, due_date, paid_at
            """),
            {
                "tenant_id": str(tenant_id),
                "banquet_id": str(banquet_id),
                "total_deposit_fen": total_deposit_fen,
                "due_date": due_date,
            },
        )
        await self._db.commit()
        row = result.mappings().one()
        logger.info(
            "banquet_deposit.created",
            deposit_id=str(row["id"]),
            banquet_id=str(banquet_id),
        )
        return _row_to_deposit(dict(row))

    async def initiate_wechat_pay(
        self,
        deposit_id: UUID,
        tenant_id: UUID,
        openid: str,
        notify_url: str,
    ) -> WechatPayResult:
        """发起微信小程序支付（JSAPI模式）

        生成唯一 payment_no，调用微信统一下单（当前为 mock），
        返回前端调起支付所需参数。
        """
        # 1. 查询定金记录
        result = await self._db.execute(
            text("""
                SELECT id, total_deposit_fen, status, payment_no, wechat_prepay_id
                FROM banquet_deposits
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": str(deposit_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise ValueError(f"定金记录不存在：{deposit_id}")
        if row["status"] == "paid":
            raise ValueError("该定金已支付")
        if row["status"] not in ("pending",):
            raise ValueError(f"定金状态不允许发起支付：{row['status']}")

        # 2. 支付流水号（幂等：已有则复用）
        payment_no: str = row["payment_no"] or _gen_payment_no()

        # 3. 已存在 prepay：仅刷新 JSAPI 参数，不写库（支付通道重试幂等）
        existing_prepay = row.get("wechat_prepay_id")
        if existing_prepay and payment_no:
            wechat_result = _build_wechat_jsapi_order_result(
                payment_no=payment_no,
                amount_fen=row["total_deposit_fen"],
                openid=openid,
                notify_url=notify_url,
                existing_prepay_id=str(existing_prepay),
            )
            logger.info(
                "banquet_deposit.wechat_pay_idempotent",
                deposit_id=str(deposit_id),
                payment_no=payment_no,
            )
            return WechatPayResult(
                deposit_id=deposit_id,
                payment_no=payment_no,
                jsapi_params=wechat_result["jsapi_params"],
                qr_code_url=None,
            )

        # 4. 首次下单：生成 prepay 并落库
        wechat_result = _build_wechat_jsapi_order_result(
            payment_no=payment_no,
            amount_fen=row["total_deposit_fen"],
            openid=openid,
            notify_url=notify_url,
        )

        await self._db.execute(
            text("""
                UPDATE banquet_deposits
                SET payment_no       = :payment_no,
                    wechat_prepay_id = :prepay_id,
                    updated_at       = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "payment_no": payment_no,
                "prepay_id": wechat_result["prepay_id"],
                "id": str(deposit_id),
                "tenant_id": str(tenant_id),
            },
        )
        await self._db.commit()

        logger.info(
            "banquet_deposit.wechat_pay_initiated",
            deposit_id=str(deposit_id),
            payment_no=payment_no,
        )
        return WechatPayResult(
            deposit_id=deposit_id,
            payment_no=payment_no,
            jsapi_params=wechat_result["jsapi_params"],
            qr_code_url=None,
        )

    async def handle_payment_callback(
        self,
        payment_no: str,
        wechat_transaction_id: str,
        paid_fen: int,
        paid_at: datetime,
    ) -> BanquetDeposit:
        """处理微信支付回调，更新定金状态为 paid（**幂等**：已 paid 且金额一致则直接返回）。"""
        cur = await self._db.execute(
            text("""
                SELECT id, banquet_id, total_deposit_fen, paid_fen,
                       status, due_date, paid_at
                FROM banquet_deposits
                WHERE payment_no = :payment_no
                LIMIT 1
            """),
            {"payment_no": payment_no},
        )
        existing = cur.mappings().first()
        if existing is None:
            raise ValueError(f"支付回调匹配失败，payment_no={payment_no}")

        if existing["status"] == "paid":
            if int(existing["paid_fen"]) != int(paid_fen):
                raise ValueError(
                    f"重复回调金额不一致: payment_no={payment_no}, "
                    f"已有 paid_fen={existing['paid_fen']}, 回调 paid_fen={paid_fen}"
                )
            logger.info(
                "banquet_deposit.callback_idempotent",
                payment_no=payment_no,
                wechat_transaction_id=wechat_transaction_id,
            )
            return _row_to_deposit(dict(existing))

        if existing["status"] != "pending":
            raise ValueError(
                f"支付回调状态非法: payment_no={payment_no}, status={existing['status']}"
            )

        result = await self._db.execute(
            text("""
                UPDATE banquet_deposits
                SET status     = 'paid',
                    paid_fen   = :paid_fen,
                    paid_at    = :paid_at,
                    updated_at = NOW()
                WHERE payment_no = :payment_no
                  AND status     = 'pending'
                RETURNING
                    id, banquet_id, total_deposit_fen, paid_fen,
                    status, due_date, paid_at
            """),
            {
                "payment_no": payment_no,
                "paid_fen": paid_fen,
                "paid_at": paid_at,
            },
        )
        row = result.mappings().first()
        if row is None:
            raise ValueError(f"支付回调并发冲突，payment_no={payment_no}")
        await self._db.commit()
        logger.info(
            "banquet_deposit.paid",
            payment_no=payment_no,
            wechat_transaction_id=wechat_transaction_id,
            paid_fen=paid_fen,
        )
        return _row_to_deposit(dict(row))

    async def get_deposit(
        self,
        banquet_id: UUID,
        tenant_id: UUID,
    ) -> Optional[BanquetDeposit]:
        """获取定金记录（取最新一条）"""
        result = await self._db.execute(
            text("""
                SELECT id, banquet_id, total_deposit_fen, paid_fen,
                       status, due_date, paid_at
                FROM banquet_deposits
                WHERE banquet_id = :banquet_id
                  AND tenant_id  = :tenant_id
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"banquet_id": str(banquet_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().first()
        return _row_to_deposit(dict(row)) if row else None

    # ── 电子确认单相关 ───────────────────────────────────────────────────────

    async def create_confirmation(
        self,
        banquet_id: UUID,
        tenant_id: UUID,
        menu_items: list[dict],
        guest_count: int,
        confirmed_by_name: str,
        confirmed_by_phone: str,
        special_requirements: str = "",
    ) -> BanquetConfirmation:
        """创建电子确认单

        生成确认单号 BC+YYYYMMDD+4位随机大写字母，
        过期时间 = 创建时间 + 7天。
        """
        import json

        if not menu_items:
            raise ValueError("menu_items 不能为空")

        total_fen = sum(int(item.get("subtotal_fen", 0)) for item in menu_items)
        confirmation_no = _gen_confirmation_no()
        expires_at = _now_utc() + timedelta(days=7)

        result = await self._db.execute(
            text("""
                INSERT INTO banquet_confirmations (
                    tenant_id, banquet_id, confirmation_no,
                    menu_items_json, total_fen, guest_count,
                    special_requirements, confirmed_by_name,
                    confirmed_by_phone, expires_at
                ) VALUES (
                    :tenant_id, :banquet_id, :confirmation_no,
                    :menu_items_json::jsonb, :total_fen, :guest_count,
                    :special_requirements, :confirmed_by_name,
                    :confirmed_by_phone, :expires_at
                )
                RETURNING
                    id, banquet_id, confirmation_no, menu_items_json,
                    total_fen, guest_count, status, confirmed_at, expires_at
            """),
            {
                "tenant_id": str(tenant_id),
                "banquet_id": str(banquet_id),
                "confirmation_no": confirmation_no,
                "menu_items_json": json.dumps(menu_items, ensure_ascii=False),
                "total_fen": total_fen,
                "guest_count": guest_count,
                "special_requirements": special_requirements,
                "confirmed_by_name": confirmed_by_name,
                "confirmed_by_phone": confirmed_by_phone,
                "expires_at": expires_at,
            },
        )
        await self._db.commit()
        row = result.mappings().one()
        logger.info(
            "banquet_confirmation.created",
            confirmation_no=confirmation_no,
            banquet_id=str(banquet_id),
        )
        return _row_to_confirmation(dict(row))

    async def confirm_with_signature(
        self,
        confirmation_id: UUID,
        tenant_id: UUID,
        signature_data: Optional[str] = None,
    ) -> BanquetConfirmation:
        """顾客确认签字，状态更新为 confirmed"""
        result = await self._db.execute(
            text("""
                UPDATE banquet_confirmations
                SET status         = 'confirmed',
                    confirmed_at   = NOW(),
                    signature_data = :signature_data
                WHERE id        = :id
                  AND tenant_id = :tenant_id
                  AND status    IN ('draft', 'sent')
                RETURNING
                    id, banquet_id, confirmation_no, menu_items_json,
                    total_fen, guest_count, status, confirmed_at, expires_at
            """),
            {
                "id": str(confirmation_id),
                "tenant_id": str(tenant_id),
                "signature_data": signature_data,
            },
        )
        row = result.mappings().first()
        if row is None:
            raise ValueError(f"确认单不存在或状态不允许确认：{confirmation_id}")
        await self._db.commit()
        logger.info(
            "banquet_confirmation.signed",
            confirmation_id=str(confirmation_id),
        )
        return _row_to_confirmation(dict(row))

    async def get_confirmation(
        self,
        banquet_id: UUID,
        tenant_id: UUID,
    ) -> Optional[BanquetConfirmation]:
        """获取确认单（取最新一条）"""
        result = await self._db.execute(
            text("""
                SELECT id, banquet_id, confirmation_no, menu_items_json,
                       total_fen, guest_count, status, confirmed_at, expires_at
                FROM banquet_confirmations
                WHERE banquet_id = :banquet_id
                  AND tenant_id  = :tenant_id
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"banquet_id": str(banquet_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().first()
        return _row_to_confirmation(dict(row)) if row else None

    async def generate_confirmation_summary(
        self,
        confirmation_id: UUID,
        tenant_id: UUID,
    ) -> ConfirmationSummary:
        """生成确认单摘要（用于前端展示/PDF导出）"""
        result = await self._db.execute(
            text("""
                SELECT id, banquet_id, confirmation_no, menu_items_json,
                       total_fen, guest_count, special_requirements,
                       confirmed_by_name, confirmed_by_phone,
                       status, confirmed_at
                FROM banquet_confirmations
                WHERE id        = :id
                  AND tenant_id = :tenant_id
            """),
            {"id": str(confirmation_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise ValueError(f"确认单不存在：{confirmation_id}")

        raw_items: list[dict] = row["menu_items_json"] or []
        items: list[MenuItem] = []
        for item in raw_items:
            try:
                items.append(
                    MenuItem(
                        dish_id=UUID(str(item.get("dish_id", uuid.uuid4()))),
                        dish_name=str(item.get("dish_name", "")),
                        quantity=int(item.get("quantity", 1)),
                        unit_price_fen=int(item.get("unit_price_fen", 0)),
                        subtotal_fen=int(item.get("subtotal_fen", 0)),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("menu_item.parse_error", item=item, error=str(exc))

        return ConfirmationSummary(
            confirmation_no=row["confirmation_no"],
            banquet_id=row["banquet_id"],
            items=items,
            total_fen=row["total_fen"],
            guest_count=row.get("guest_count"),
            confirmed_by_name=row["confirmed_by_name"] or "",
            confirmed_by_phone=row["confirmed_by_phone"] or "",
            special_requirements=row["special_requirements"] or "",
            status=row["status"],
            confirmed_at=row.get("confirmed_at"),
        )
