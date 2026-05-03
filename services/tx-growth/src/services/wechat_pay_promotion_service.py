"""微信支付营销活动业务逻辑

管理微信支付营销活动（摇一摇优惠）、商家名片、投放计划。

职责：
- 管理营销活动的创建、配置、状态查询
- 在支付回调中旁路触发摇一摇优惠
- 调用 WechatPayPromotionService SDK 完成微信 API 通信
- WP-2: 投放计划管理（列表/详情/状态变更）+ 效果追踪
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from shared.integrations.wechat_pay_promotion import (
    WechatPayPromotionService,
    get_wechat_pay_promotion_service,
)

logger = structlog.get_logger(__name__)


class PromotionService:
    """微信支付营销活动业务逻辑"""

    def __init__(self) -> None:
        self._sdk = get_wechat_pay_promotion_service()
        # Phase 1: 使用内存缓存存储营销活动配置
        # TODO(v2): 迁移至 DB 表 v386_wechat_promotion_activities
        self._activities: dict[str, dict] = {}
        self._cards: dict[str, dict] = {}
        self._plans: dict[str, dict] = {}

    # ─── Internal helpers ───

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _filter_by_tenant(
        self, items: dict[str, dict], tenant_id: str | None = None
    ) -> list[dict]:
        results = list(items.values())
        if tenant_id:
            results = [r for r in results if r.get("tenant_id") == tenant_id]
        results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return results

    # ─── 摇一摇优惠 ───

    async def create_shake_coupon_activity(
        self,
        tenant_id: str,
        store_id: str,
        activity_name: str,
        begin_time: str,
        end_time: str,
        award_amount_fen: int,
        total_count: int,
        operator_id: str | None = None,
        **kwargs: Any,
    ) -> dict:
        """创建摇一摇优惠活动。

        调用微信支付营销 API 创建活动，并在本地缓存活动信息。

        Returns:
            dict: { activity_id, activity_name, status, create_time }
        """
        activity_id: str | None = None
        try:
            result = await self._sdk.create_shake_coupon_activity(
                activity_name=activity_name,
                begin_time=begin_time,
                end_time=end_time,
                award_amount_fen=award_amount_fen,
                total_count=total_count,
                **kwargs,
            )
            activity_id = result.get("activity_id", "")
            now = self._now()
            self._activities[activity_id] = {
                "id": activity_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "activity_name": activity_name,
                "activity_type": "shake_coupon",
                "begin_time": begin_time,
                "end_time": end_time,
                "award_amount_fen": award_amount_fen,
                "total_count": total_count,
                "operator_id": operator_id,
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "wechat_result": result,
            }
            logger.info(
                "promotion.shake_activity_created",
                activity_id=activity_id,
                activity_name=activity_name,
                store_id=store_id,
                tenant_id=tenant_id,
            )
            return {"id": activity_id, "activity_name": activity_name, "status": "active", "create_time": now}
        except ValueError as exc:
            logger.error(
                "promotion.shake_activity_create_failed",
                activity_name=activity_name,
                store_id=store_id,
                error=str(exc),
                exc_info=True,
            )
            raise

    # ─── 商家名片 ───

    async def create_merchant_card(
        self,
        tenant_id: str,
        store_id: str,
        card_name: str,
        card_type: str,
        operator_id: str | None = None,
        **kwargs: Any,
    ) -> dict:
        """配置商家名片。

        Returns:
            dict: { card_id, card_name, status, create_time }
        """
        card_id: str | None = None
        try:
            result = await self._sdk.create_merchant_card(
                card_name=card_name,
                card_type=card_type,
                **kwargs,
            )
            card_id = result.get("card_id", "")
            now = self._now()
            self._cards[card_id] = {
                "id": card_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "card_name": card_name,
                "card_type": card_type,
                "activity_type": "merchant_card",
                "operator_id": operator_id,
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "wechat_result": result,
            }
            logger.info(
                "promotion.merchant_card_created",
                card_id=card_id,
                card_name=card_name,
                store_id=store_id,
                tenant_id=tenant_id,
            )
            return {"id": card_id, "card_name": card_name, "status": "active", "create_time": now}
        except ValueError as exc:
            logger.error(
                "promotion.merchant_card_create_failed",
                card_name=card_name,
                error=str(exc),
                exc_info=True,
            )
            raise

    # ─── 投放计划 ───

    async def create_promotion_plan(
        self,
        tenant_id: str,
        store_id: str,
        plan_name: str,
        plan_type: str,
        begin_time: str,
        end_time: str,
        operator_id: str | None = None,
        **kwargs: Any,
    ) -> dict:
        """创建投放计划。

        Returns:
            dict: { plan_id, plan_name, status, create_time }
        """
        plan_id: str | None = None
        try:
            result = await self._sdk.create_promotion_plan(
                plan_name=plan_name,
                plan_type=plan_type,
                begin_time=begin_time,
                end_time=end_time,
                **kwargs,
            )
            plan_id = result.get("plan_id", "")
            now = self._now()
            self._plans[plan_id] = {
                "id": plan_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "plan_name": plan_name,
                "plan_type": plan_type,
                "activity_type": "promotion_plan",
                "begin_time": begin_time,
                "end_time": end_time,
                "operator_id": operator_id,
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "wechat_result": result,
            }
            logger.info(
                "promotion.promotion_plan_created",
                plan_id=plan_id,
                plan_name=plan_name,
                store_id=store_id,
                tenant_id=tenant_id,
            )
            return {"id": plan_id, "plan_name": plan_name, "status": "active", "create_time": now}
        except ValueError as exc:
            logger.error(
                "promotion.promotion_plan_create_failed",
                plan_name=plan_name,
                error=str(exc),
                exc_info=True,
            )
            raise

    # ─── 旁路触发摇优惠 ───

    async def trigger_shake_coupon(self, openid: str, store_id: str, amount_fen: int) -> dict:
        """旁路触发摇一摇优惠。

        在支付回调中异步调用，不阻塞主流程。
        失败仅记录日志，不向调用方抛出异常。

        Args:
            openid: 用户 OpenID
            store_id: 门店 ID
            amount_fen: 支付金额（分）

        Returns:
            dict: 触发结果
        """
        try:
            result = await self._sdk.trigger_shake_coupon(
                openid=openid,
                store_id=store_id,
                amount_fen=amount_fen,
            )
            logger.info(
                "promotion.shake_coupon_triggered",
                openid=openid,
                store_id=store_id,
                amount_fen=amount_fen,
                triggered=result.get("triggered", False),
            )
            return result
        except ValueError as exc:
            logger.error(
                "promotion.shake_coupon_trigger_failed",
                openid=openid,
                store_id=store_id,
                amount_fen=amount_fen,
                error=str(exc),
                exc_info=True,
            )
            return {
                "triggered": False,
                "openid": openid,
                "store_id": store_id,
                "amount_fen": amount_fen,
                "error": str(exc),
            }

    # ─── WP-2: 投放计划管理 ───

    def list_activities(
        self,
        tenant_id: str | None = None,
        activity_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """查询活动列表。

        Args:
            tenant_id: 按租户过滤
            activity_type: 按类型过滤 (shake_coupon/merchant_card/promotion_plan)
            status: 按状态过滤 (active/paused/ended/cancelled)
            limit: 最大返回条数

        Returns:
            list[dict]: 活动列表（按创建时间倒序）
        """
        all_items: dict[str, dict] = {}
        for items in (self._activities, self._cards, self._plans):
            all_items.update(items)

        results = list(all_items.values())
        if tenant_id:
            results = [r for r in results if r.get("tenant_id") == tenant_id]
        if activity_type:
            results = [r for r in results if r.get("activity_type") == activity_type]
        if status:
            results = [r for r in results if r.get("status") == status]
        results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return results[:limit]

    def get_activity(self, activity_id: str) -> dict | None:
        """获取活动详情。"""
        for items in (self._activities, self._cards, self._plans):
            if activity_id in items:
                return items[activity_id]
        return None

    def update_activity_status(
        self, activity_id: str, status: str, operator_id: str | None = None
    ) -> dict | None:
        """更新活动状态。

        Args:
            activity_id: 活动/名片/计划 ID
            status: 新状态 (active/paused/ended/cancelled)
            operator_id: 操作人

        Returns:
            updated record or None if not found
        """
        record = self.get_activity(activity_id)
        if not record:
            return None
        record["status"] = status
        record["updated_at"] = self._now()
        if operator_id:
            record["operator_id"] = operator_id
        logger.info(
            "promotion.activity_status_updated",
            activity_id=activity_id,
            status=status,
            operator_id=operator_id,
        )
        return record


# ─── 全局单例 ───

_instance: PromotionService | None = None


def get_promotion_service() -> PromotionService:
    """获取 PromotionService 全局单例"""
    global _instance
    if _instance is None:
        _instance = PromotionService()
    return _instance
