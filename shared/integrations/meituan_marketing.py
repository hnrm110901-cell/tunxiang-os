"""美团/饿了么商家营销适配器

覆盖外卖平台营销核心能力：
  - 创建/管理优惠券（美团商家券）
  - 满减/折扣活动管理
  - 广告花费数据回流
  - 订单归因（广告带来 vs 自然流量）

环境变量：
  MEITUAN_APP_ID       — 美团开放平台 AppID
  MEITUAN_APP_SECRET   — 美团开放平台 AppSecret
  MEITUAN_MERCHANT_ID  — 美团商家 ID
  ELEME_APP_KEY        — 饿了么 AppKey（可选，共享同一适配器）
  ELEME_APP_SECRET     — 饿了么 AppSecret

未配置时进入 Mock 模式，返回模拟数据。
所有金额使用分（整数），不使用浮点。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_MEITUAN_BASE_URL = "https://waimaiopen.meituan.com/api/v1"
_ELEME_BASE_URL = "https://open-api.shop.ele.me/api/v1"


# ─────────────────────────────────────────────────────────────────────────────
# 美团商家营销适配器
# ─────────────────────────────────────────────────────────────────────────────


class MeituanMarketingAdapter:
    """美团/饿了么商家营销适配器

    用于连锁餐饮品牌在外卖平台侧的营销动作管理和数据回流。
    """

    def __init__(self) -> None:
        self._app_id = os.getenv("MEITUAN_APP_ID", "")
        self._app_secret = os.getenv("MEITUAN_APP_SECRET", "")
        self._merchant_id = os.getenv("MEITUAN_MERCHANT_ID", "")
        self._is_mock = not (self._app_id and self._app_secret and self._merchant_id)

        if self._is_mock:
            logger.info("meituan_mock_mode", reason="MEITUAN_APP_ID/APP_SECRET/MERCHANT_ID not fully set")

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    # ─── 优惠券管理 ──────────────────────────────────────────────────────────

    async def create_coupon(
        self,
        tenant_id: str,
        store_id: str,
        coupon_config: dict[str, Any],
    ) -> dict[str, Any]:
        """创建美团商家优惠券

        Args:
            tenant_id: 租户 ID
            store_id: 门店 ID
            coupon_config: 优惠券配置
                - name: str 券名称
                - discount_fen: int 优惠金额（分）
                - min_order_fen: int 最低消费（分）
                - total_count: int 发行总量
                - per_limit: int 每人限领数量
                - start_time: str ISO 格式开始时间
                - end_time: str ISO 格式结束时间

        Returns:
            {coupon_id, status, platform, store_id}
        """
        op_id = f"mt_cpn_{uuid.uuid4().hex[:10]}"

        if self._is_mock:
            mock_coupon_id = f"MOCK_CPT_{uuid.uuid4().hex[:8].upper()}"
            logger.info(
                "meituan_create_coupon_mock",
                op_id=op_id,
                store_id=store_id,
                discount_fen=coupon_config.get("discount_fen"),
                min_order_fen=coupon_config.get("min_order_fen"),
            )
            return {
                "op_id": op_id,
                "coupon_id": mock_coupon_id,
                "status": "mock",
                "platform": "meituan",
                "store_id": store_id,
            }

        try:
            params = {
                "ePoiId": store_id,
                "actName": coupon_config["name"],
                "discountAmount": coupon_config["discount_fen"],
                "minOrderAmount": coupon_config["min_order_fen"],
                "totalCount": coupon_config.get("total_count", 100),
                "perLimit": coupon_config.get("per_limit", 1),
                "startTime": coupon_config["start_time"],
                "endTime": coupon_config["end_time"],
            }
            result = await self._call_api("POST", "/coupon/create", params)
            logger.info("meituan_coupon_created", op_id=op_id, coupon_id=result.get("couponId"))
            return {
                "op_id": op_id,
                "coupon_id": result.get("couponId"),
                "status": "created",
                "platform": "meituan",
                "store_id": store_id,
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("meituan_create_coupon_failed", op_id=op_id, error=str(exc))
            return {"op_id": op_id, "status": "failed", "error": str(exc)}

    async def get_promotion_list(
        self,
        tenant_id: str,
        store_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """获取门店当前促销活动列表（满减/折扣/优惠券）"""
        if self._is_mock:
            return {
                "store_id": store_id,
                "total": 2,
                "items": [
                    {
                        "promotion_id": "MOCK_PROMO_001",
                        "type": "full_reduction",
                        "name": "满50减10",
                        "threshold_fen": 5000,
                        "discount_fen": 1000,
                        "status": "active",
                        "platform": "meituan",
                    },
                    {
                        "promotion_id": "MOCK_PROMO_002",
                        "type": "new_customer",
                        "name": "新客立减5元",
                        "threshold_fen": 0,
                        "discount_fen": 500,
                        "status": "active",
                        "platform": "meituan",
                    },
                ],
                "status": "mock",
            }

        try:
            result = await self._call_api(
                "GET", "/promotion/list", {"ePoiId": store_id, "page": page, "pageSize": page_size}
            )
            return {
                "store_id": store_id,
                "total": result.get("total", 0),
                "items": result.get("data", []),
                "platform": "meituan",
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("meituan_get_promotions_failed", store_id=store_id, error=str(exc))
            return {"store_id": store_id, "total": 0, "items": [], "error": str(exc)}

    async def update_store_promotion(
        self,
        tenant_id: str,
        store_id: str,
        promotion_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """更新门店满减/折扣活动配置

        config 字段：
          - threshold_fen: int 满减门槛（分）
          - discount_fen: int 优惠金额（分）
          - is_active: bool 是否启用
        """
        op_id = f"mt_promo_{uuid.uuid4().hex[:8]}"

        if self._is_mock:
            logger.info(
                "meituan_update_promotion_mock",
                op_id=op_id,
                store_id=store_id,
                promotion_id=promotion_id,
                config=config,
            )
            return {"op_id": op_id, "promotion_id": promotion_id, "status": "mock"}

        try:
            params = {"ePoiId": store_id, "actId": promotion_id, **config}
            await self._call_api("POST", "/promotion/update", params)
            logger.info("meituan_promotion_updated", op_id=op_id, promotion_id=promotion_id)
            return {"op_id": op_id, "promotion_id": promotion_id, "status": "updated"}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("meituan_update_promotion_failed", op_id=op_id, error=str(exc))
            return {"op_id": op_id, "status": "failed", "error": str(exc)}

    # ─── 广告数据回流 ─────────────────────────────────────────────────────────

    async def get_ad_spend_data(
        self,
        tenant_id: str,
        store_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """获取门店广告花费数据（信息流广告/搜索广告）

        Args:
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"

        Returns:
            {
                total_spend_fen: int,
                impression_count: int,
                click_count: int,
                order_count: int,
                ctr: float,
                roi: float,
                daily_breakdown: list
            }
        """
        if self._is_mock:
            return {
                "store_id": store_id,
                "period": f"{start_date} ~ {end_date}",
                "total_spend_fen": 158000,
                "impression_count": 45000,
                "click_count": 1350,
                "order_count": 89,
                "ctr": 0.03,
                "cvr": 0.066,
                "roi": 4.2,
                "revenue_from_ad_fen": 663600,
                "daily_breakdown": [],
                "platform": "meituan",
                "status": "mock",
            }

        try:
            result = await self._call_api(
                "GET",
                "/ad/report",
                {"ePoiId": store_id, "startDate": start_date, "endDate": end_date},
            )
            return {
                "store_id": store_id,
                "period": f"{start_date} ~ {end_date}",
                "total_spend_fen": result.get("totalSpend", 0),
                "impression_count": result.get("impression", 0),
                "click_count": result.get("click", 0),
                "order_count": result.get("orderCount", 0),
                "roi": result.get("roi", 0.0),
                "platform": "meituan",
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("meituan_ad_spend_failed", store_id=store_id, error=str(exc))
            return {"store_id": store_id, "error": str(exc)}

    async def get_order_attribution(
        self,
        tenant_id: str,
        store_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """获取订单归因数据（广告带来 vs 自然流量 vs 活动引流）"""
        if self._is_mock:
            total = 312
            return {
                "store_id": store_id,
                "period": f"{start_date} ~ {end_date}",
                "total_orders": total,
                "attribution_breakdown": {
                    "paid_ad": {"count": 89, "pct": 28.5, "revenue_fen": 663600},
                    "coupon": {"count": 67, "pct": 21.5, "revenue_fen": 401800},
                    "natural": {"count": 156, "pct": 50.0, "revenue_fen": 1140000},
                },
                "platform": "meituan",
                "status": "mock",
            }

        try:
            result = await self._call_api(
                "GET",
                "/order/attribution",
                {"ePoiId": store_id, "startDate": start_date, "endDate": end_date},
            )
            return {"store_id": store_id, "platform": "meituan", **result}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("meituan_order_attribution_failed", store_id=store_id, error=str(exc))
            return {"store_id": store_id, "error": str(exc)}

    # ─── 内部：API 调用 + 签名 ────────────────────────────────────────────────

    async def _call_api(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """调用美团开放平台 API（带 HMAC-SHA256 签名）"""
        timestamp = int(time.time())
        nonce = uuid.uuid4().hex[:16]

        # 构造待签名字符串
        sign_params = {
            "app_id": self._app_id,
            "timestamp": str(timestamp),
            "nonce": nonce,
            **{str(k): str(v) for k, v in params.items()},
        }
        sorted_str = "&".join(f"{k}={v}" for k, v in sorted(sign_params.items()))
        signature = hmac.new(
            self._app_secret.encode("utf-8"),
            sorted_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        request_params = {**sign_params, "sign": signature}
        url = f"{_MEITUAN_BASE_URL}{path}"

        import aiohttp

        async with aiohttp.ClientSession() as session:
            if method == "GET":
                req = session.get(url, params=request_params, timeout=aiohttp.ClientTimeout(total=15))
            else:
                req = session.post(url, json=request_params, timeout=aiohttp.ClientTimeout(total=15))

            async with req as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    raise ValueError(f"Meituan API error {data.get('code')}: {data.get('msg')}")
                return data.get("data", {})
