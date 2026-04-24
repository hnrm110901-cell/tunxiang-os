"""券核销服务 (VoucherRedeemService) — 区域级券核销流程

核销时机由 table_zones.coupon_config.voucher_deduct_timing 决定：

on_order（scan_and_pay 默认）：
  顾客扫码 → 选菜 → 选券 → 计算抵扣 → 付差额 → 出品
  适用：大厅扫码点单、快餐、外带窗口

on_settle（dine_first 默认）：
  用餐 → 结账时出示券码 → 扫码核销 → 抵扣 → 付差额
  适用：包厢、卡座、正式堂食

支持的券类型：
  - platform_voucher: 美团/抖音套餐券（需调用平台API核销）
  - cash_voucher:     代金券（内部发行，直接抵扣）
  - member_points:    会员积分抵扣（调用 tx-member POST /api/v1/member/points/spend）
"""

from __future__ import annotations

import json as _json
import os
import uuid
from typing import Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ─── tx-member 服务连接配置 ─────────────────────────────────────────────────────
_TX_MEMBER_URL = os.getenv("TX_MEMBER_URL", "http://tx-member:8003")
_member_client: Optional[httpx.AsyncClient] = None

# 积分兑换比例默认值：100积分 = 1元 = 100分
DEFAULT_POINTS_TO_FEN_RATIO = 100


def _get_member_client() -> httpx.AsyncClient:
    global _member_client
    if _member_client is None:
        _member_client = httpx.AsyncClient(
            base_url=_TX_MEMBER_URL,
            timeout=httpx.Timeout(connect=3, read=10, write=5, pool=3),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _member_client


class VoucherRedeemService:
    """券核销服务

    根据区域的 coupon_config 配置，在正确的时机执行核销。
    """

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = uuid.UUID(tenant_id)
        self._tid_str = tenant_id

    async def _set_tenant(self) -> None:
        await self._db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self._tid_str},
        )

    async def check_zone_coupon_config(self, zone_id: uuid.UUID) -> dict:
        """获取区域券核销配置"""
        await self._set_tenant()
        row = await self._db.execute(
            text("""
                SELECT coupon_config, service_mode
                FROM table_zones
                WHERE id = :zid AND tenant_id = :tid
            """),
            {"zid": zone_id, "tid": self._tenant_id},
        )
        info = row.mappings().one_or_none()
        if not info:
            return {
                "allows_platform_voucher": True,
                "allows_cash_voucher": True,
                "allows_member_points": True,
                "voucher_deduct_timing": "on_settle",
            }
        config = info["coupon_config"] or {}
        # 默认值：scan_and_pay 模式默认 on_order，其他默认 on_settle
        service_mode = info["service_mode"] or "dine_first"
        default_timing = "on_order" if service_mode == "scan_and_pay" else "on_settle"
        return {
            "allows_platform_voucher": config.get("allows_platform_voucher", True),
            "allows_cash_voucher": config.get("allows_cash_voucher", True),
            "allows_member_points": config.get("allows_member_points", True),
            "voucher_deduct_timing": config.get("voucher_deduct_timing", default_timing),
        }

    async def redeem_voucher(
        self,
        order_id: uuid.UUID,
        voucher_type: str,
        voucher_code: str,
        zone_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """核销券码

        Args:
            order_id:     订单ID
            voucher_type: 券类型 platform_voucher / cash_voucher / member_points
            voucher_code: 券码
            zone_id:      区域ID（用于读取核销配置）

        Returns:
            核销结果 {redeemed, deduct_amount_fen, voucher_detail}
        """
        await self._set_tenant()

        # 检查区域是否允许该类型券核销
        if zone_id:
            config = await self.check_zone_coupon_config(zone_id)
            type_to_flag = {
                "platform_voucher": "allows_platform_voucher",
                "cash_voucher": "allows_cash_voucher",
                "member_points": "allows_member_points",
            }
            flag_key = type_to_flag.get(voucher_type)
            if flag_key and not config.get(flag_key, True):
                return {
                    "redeemed": False,
                    "deduct_amount_fen": 0,
                    "error": f"当前区域不允许使用{voucher_type}",
                }

        # 根据券类型分发核销逻辑
        if voucher_type == "platform_voucher":
            return await self._redeem_platform_voucher(order_id, voucher_code)
        elif voucher_type == "cash_voucher":
            return await self._redeem_cash_voucher(order_id, voucher_code)
        elif voucher_type == "member_points":
            return await self._redeem_member_points(order_id, voucher_code)
        else:
            return {"redeemed": False, "deduct_amount_fen": 0, "error": f"未知券类型: {voucher_type}"}

    async def _redeem_platform_voucher(
        self, order_id: uuid.UUID, voucher_code: str
    ) -> dict:
        """核销美团/抖音平台券

        TODO: 对接 tx-trade/webhook_routes.py 的平台核销接口
        当前实现：查询 platform_voucher_records 表验证券码有效性并标记已核销
        """
        result = await self._db.execute(
            text("""
                SELECT id, platform, voucher_name, amount_fen, status
                FROM platform_voucher_records
                WHERE voucher_code = :code
                  AND tenant_id = :tid
                  AND status = 'active'
                LIMIT 1
            """),
            {"code": voucher_code, "tid": self._tenant_id},
        )
        voucher = result.mappings().one_or_none()
        if not voucher:
            return {"redeemed": False, "deduct_amount_fen": 0, "error": "券码无效或已使用"}

        # 标记核销
        await self._db.execute(
            text("""
                UPDATE platform_voucher_records
                SET status = 'redeemed', redeemed_order_id = :oid, redeemed_at = NOW()
                WHERE id = :vid AND tenant_id = :tid
            """),
            {"vid": voucher["id"], "oid": order_id, "tid": self._tenant_id},
        )

        logger.info(
            "platform_voucher_redeemed",
            voucher_id=str(voucher["id"]),
            order_id=str(order_id),
            platform=voucher["platform"],
            amount_fen=voucher["amount_fen"],
        )

        return {
            "redeemed": True,
            "deduct_amount_fen": voucher["amount_fen"],
            "voucher_detail": {
                "id": str(voucher["id"]),
                "platform": voucher["platform"],
                "name": voucher["voucher_name"],
            },
        }

    async def _redeem_cash_voucher(
        self, order_id: uuid.UUID, voucher_code: str
    ) -> dict:
        """核销内部代金券

        查询 coupons 表（tx-member 发行的代金券），验证并标记核销。
        """
        result = await self._db.execute(
            text("""
                SELECT id, coupon_name, discount_value_fen, status, expires_at
                FROM coupons
                WHERE coupon_code = :code
                  AND tenant_id = :tid
                  AND status = 'active'
                  AND (expires_at IS NULL OR expires_at > NOW())
                LIMIT 1
            """),
            {"code": voucher_code, "tid": self._tenant_id},
        )
        coupon = result.mappings().one_or_none()
        if not coupon:
            return {"redeemed": False, "deduct_amount_fen": 0, "error": "代金券无效、已使用或已过期"}

        await self._db.execute(
            text("""
                UPDATE coupons
                SET status = 'used', used_order_id = :oid, used_at = NOW()
                WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": coupon["id"], "oid": order_id, "tid": self._tenant_id},
        )

        logger.info(
            "cash_voucher_redeemed",
            coupon_id=str(coupon["id"]),
            order_id=str(order_id),
            amount_fen=coupon["discount_value_fen"],
        )

        return {
            "redeemed": True,
            "deduct_amount_fen": coupon["discount_value_fen"],
            "voucher_detail": {
                "id": str(coupon["id"]),
                "name": coupon["coupon_name"],
            },
        }

    async def _redeem_member_points(
        self, order_id: uuid.UUID, points_code: str
    ) -> dict:
        """会员积分抵扣 — 调用 tx-member POST /api/v1/member/points/spend

        points_code 格式: "{card_id}:{points_amount}"
        例: "a1b2c3d4-...:500" 表示用会员卡 a1b2c3d4 扣 500 积分

        兑换比例由 tx-member 的 spend-rules 控制，默认 100积分=1元。
        本方法先查余额确认足够，再调用扣减接口。

        Args:
            order_id:     订单ID
            points_code:  格式 "{card_id}:{points_amount}"

        Returns:
            {redeemed, deduct_amount_fen, voucher_detail}
        """
        # 解析 points_code
        parts = points_code.split(":", 1)
        if len(parts) != 2:
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": "积分码格式错误，应为 card_id:points_amount",
            }

        card_id = parts[0].strip()
        try:
            points_amount = int(parts[1].strip())
        except ValueError:
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": "积分数量必须为整数",
            }

        if points_amount <= 0:
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": "积分数量必须大于0",
            }

        client = _get_member_client()
        headers = {"X-Tenant-ID": self._tid_str}

        # 1. 查询积分余额
        try:
            balance_resp = await client.get(
                f"/api/v1/member/points/cards/{card_id}/balance",
                headers=headers,
            )
            balance_resp.raise_for_status()
            balance_data = balance_resp.json()
            if not balance_data.get("ok"):
                return {
                    "redeemed": False,
                    "deduct_amount_fen": 0,
                    "error": balance_data.get("error", {}).get("message", "查询积分余额失败"),
                }
            current_points = balance_data.get("data", {}).get("points", 0)
        except httpx.ConnectError:
            logger.warning("tx_member_unreachable", card_id=card_id)
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": "会员服务暂不可用，请稍后重试",
            }
        except httpx.TimeoutException:
            logger.warning("tx_member_timeout", card_id=card_id)
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": "会员服务响应超时，请稍后重试",
            }

        if current_points < points_amount:
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": f"积分不足，当前余额 {current_points} 积分，需要 {points_amount} 积分",
            }

        # 2. 调用积分扣减
        try:
            spend_resp = await client.post(
                "/api/v1/member/points/spend",
                headers=headers,
                json={
                    "card_id": card_id,
                    "amount": points_amount,
                    "purpose": "cash_offset",
                },
            )
            spend_resp.raise_for_status()
            spend_data = spend_resp.json()
        except httpx.ConnectError:
            logger.warning("tx_member_spend_unreachable", card_id=card_id)
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": "会员服务暂不可用，积分未扣减",
            }
        except httpx.TimeoutException:
            logger.warning("tx_member_spend_timeout", card_id=card_id)
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": "会员服务响应超时，积分未扣减",
            }

        if not spend_data.get("ok"):
            error_msg = spend_data.get("error", {}).get("message", "积分扣减失败")
            return {
                "redeemed": False,
                "deduct_amount_fen": 0,
                "error": error_msg,
            }

        # 3. 计算抵扣金额（默认 100积分=1元=100分）
        deduct_amount_fen = points_amount * DEFAULT_POINTS_TO_FEN_RATIO // 100
        new_balance = spend_data.get("data", {}).get("new_balance", 0)

        # 4. 记录核销到订单元数据
        await self._db.execute(
            text("""
                UPDATE orders
                SET order_metadata = COALESCE(order_metadata, '{}'::jsonb) || :meta,
                    discount_amount_fen = discount_amount_fen + :deduct,
                    final_amount_fen = GREATEST(final_amount_fen - :deduct, 0),
                    updated_at = NOW()
                WHERE id = :oid AND tenant_id = :tid
            """),
            {
                "oid": order_id,
                "tid": self._tenant_id,
                "deduct": deduct_amount_fen,
                "meta": _json.dumps({
                    "points_redeemed": points_amount,
                    "points_card_id": card_id,
                    "points_deduct_fen": deduct_amount_fen,
                }, ensure_ascii=False),
            },
        )

        logger.info(
            "member_points_redeemed",
            card_id=card_id,
            order_id=str(order_id),
            points_spent=points_amount,
            deduct_amount_fen=deduct_amount_fen,
            new_balance=new_balance,
        )

        return {
            "redeemed": True,
            "deduct_amount_fen": deduct_amount_fen,
            "voucher_detail": {
                "type": "member_points",
                "card_id": card_id,
                "points_spent": points_amount,
                "new_balance": new_balance,
            },
        }
