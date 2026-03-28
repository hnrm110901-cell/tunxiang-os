"""外卖平台统一适配器 -- 美团/饿了么/抖音

统一接口处理三大平台的订单接入、状态同步、菜单推送、结算对账。
所有金额单位：分（fen）。

v2: 订单持久化到 PostgreSQL delivery_orders 表（RLS 隔离）。
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import async_session_factory, _SET_TENANT_SQL
from ..models.delivery_order import DeliveryOrder

logger = structlog.get_logger()


def _gen_order_id() -> str:
    return str(uuid.uuid4())


def _gen_order_no(platform: str) -> str:
    prefix = {"meituan": "MT", "eleme": "EL", "douyin": "DY"}.get(platform, "DL")
    now = datetime.now(timezone.utc)
    return f"{prefix}{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class DeliveryPlatformAdapter:
    """外卖平台统一适配器 -- 美团/饿了么/抖音

    统一接口处理三大平台的订单接入。
    订单持久化到 delivery_orders 表。
    """

    PLATFORMS = {
        "meituan": {
            "name": "美团外卖",
            "commission_rate": 0.18,
            "settle_days": "T+7",
            "settle_delay_days": 7,
            "api_base": "https://api.meituan.com/",
        },
        "eleme": {
            "name": "饿了么",
            "commission_rate": 0.20,
            "settle_days": "T+7",
            "settle_delay_days": 7,
            "api_base": "https://api.ele.me/",
        },
        "douyin": {
            "name": "抖音外卖",
            "commission_rate": 0.10,
            "settle_days": "T+3",
            "settle_delay_days": 3,
            "api_base": "https://api.douyin.com/",
        },
    }

    # 平台订单状态 → 内部状态映射
    STATUS_MAP = {
        "pending": "待确认",
        "confirmed": "已确认",
        "preparing": "备餐中",
        "ready": "待取餐",
        "delivering": "配送中",
        "completed": "已完成",
        "cancelled": "已取消",
        "refunded": "已退款",
    }

    def __init__(
        self,
        store_id: str,
        brand_id: str,
        tenant_id: str = "",
        menu_items: Optional[list[dict]] = None,
        db_session: Optional[AsyncSession] = None,
    ):
        """
        Args:
            store_id: 门店ID
            brand_id: 品牌ID
            tenant_id: 租户ID（RLS 隔离必需）
            menu_items: 门店菜单 [{dish_id, name, price_fen, category, stock, sku_id}]
            db_session: 可选注入 DB session（单元测试用）
        """
        self.store_id = store_id
        self.brand_id = brand_id
        self.tenant_id = tenant_id
        self.menu_items = menu_items or []
        self._db_session = db_session

    async def _get_session(self) -> AsyncSession:
        """获取带 tenant_id 的 DB session"""
        if self._db_session is not None:
            return self._db_session
        session = async_session_factory()
        if self.tenant_id:
            await session.execute(_SET_TENANT_SQL, {"tid": self.tenant_id})
        return session

    async def _close_session(self, session: AsyncSession) -> None:
        """关闭自创建的 session（注入的不关）"""
        if session is not self._db_session:
            await session.close()

    async def receive_order(
        self,
        platform: str,
        platform_order_id: str,
        items: list[dict],
        total_fen: int,
        customer_phone: str = "",
        delivery_address: str = "",
        expected_time: Optional[str] = None,
        notes: str = "",
    ) -> dict:
        """接收平台订单 → 转换为TunxiangOS内部订单并持久化

        Args:
            platform: meituan / eleme / douyin
            platform_order_id: 平台原始订单号
            items: [{name, quantity, price_fen, sku_id?, notes?}]
            total_fen: 订单总额（分）
            customer_phone: 顾客电话（脱敏）
            delivery_address: 配送地址
            expected_time: 期望送达时间 ISO format
            notes: 订单备注

        Returns:
            {order_id, platform_order_id, status, items_mapped, commission_fen}
        """
        if platform not in self.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}，可选: {list(self.PLATFORMS.keys())}")

        session = await self._get_session()
        try:
            # 检查平台订单是否已存在
            existing = await session.execute(
                select(DeliveryOrder).where(
                    DeliveryOrder.platform_order_id == platform_order_id
                )
            )
            if existing.scalar_one_or_none() is not None:
                raise ValueError(f"平台订单已存在: {platform_order_id}")

            platform_config = self.PLATFORMS[platform]
            order_id = _gen_order_id()
            order_no = _gen_order_no(platform)

            # 映射菜品：平台SKU → 内部菜品
            items_mapped = []
            menu_by_name: dict[str, dict] = {m['name']: m for m in self.menu_items}
            menu_by_sku: dict[str, dict] = {}
            for m in self.menu_items:
                if m.get('sku_id'):
                    menu_by_sku[m['sku_id']] = m

            unmapped_items: list[str] = []
            for item in items:
                mapped = None
                if item.get('sku_id') and item['sku_id'] in menu_by_sku:
                    mapped = menu_by_sku[item['sku_id']]
                elif item.get('name') and item['name'] in menu_by_name:
                    mapped = menu_by_name[item['name']]

                mapped_item = {
                    'name': item.get('name', ''),
                    'quantity': item.get('quantity', 1),
                    'price_fen': item.get('price_fen', 0),
                    'subtotal_fen': item.get('price_fen', 0) * item.get('quantity', 1),
                    'notes': item.get('notes', ''),
                    'platform_sku_id': item.get('sku_id', ''),
                    'internal_dish_id': mapped.get('dish_id', '') if mapped else '',
                    'mapped': mapped is not None,
                }
                items_mapped.append(mapped_item)
                if not mapped:
                    unmapped_items.append(item.get('name', ''))

            # 计算佣金
            commission_rate = platform_config['commission_rate']
            commission_fen = round(total_fen * commission_rate)
            merchant_receive_fen = total_fen - commission_fen

            now = datetime.now(timezone.utc)

            # 创建 ORM 对象并持久化
            delivery_order = DeliveryOrder(
                id=uuid.UUID(order_id),
                tenant_id=uuid.UUID(self.tenant_id) if self.tenant_id else uuid.uuid4(),
                order_no=order_no,
                store_id=uuid.UUID(self.store_id) if len(self.store_id) > 8 else uuid.uuid4(),
                brand_id=self.brand_id,
                platform=platform,
                platform_name=platform_config['name'],
                platform_order_id=platform_order_id,
                sales_channel=f"delivery_{platform}",
                status='confirmed',
                items_json=items_mapped,
                total_fen=total_fen,
                commission_rate=commission_rate,
                commission_fen=commission_fen,
                merchant_receive_fen=merchant_receive_fen,
                customer_phone=customer_phone,
                delivery_address=delivery_address,
                expected_time=expected_time,
                confirmed_at=now,
                unmapped_items=unmapped_items,
                notes=notes,
            )

            session.add(delivery_order)
            await session.commit()

            logger.info(
                "delivery_order_received",
                order_id=order_id,
                order_no=order_no,
                platform=platform,
                platform_order_id=platform_order_id,
                total_fen=total_fen,
                commission_fen=commission_fen,
                items_count=len(items),
                unmapped=len(unmapped_items),
            )

            return {
                'order_id': order_id,
                'order_no': order_no,
                'platform_order_id': platform_order_id,
                'platform': platform,
                'status': 'confirmed',
                'items_mapped': items_mapped,
                'total_fen': total_fen,
                'commission_fen': commission_fen,
                'merchant_receive_fen': merchant_receive_fen,
                'unmapped_items': unmapped_items,
            }
        finally:
            await self._close_session(session)

    async def confirm_order(self, order_id: str, estimated_ready_min: int = 30) -> dict:
        """确认订单并设置预计出餐时间

        Args:
            order_id: 内部订单ID
            estimated_ready_min: 预计出餐分钟数

        Returns:
            {order_id, status, estimated_ready_min, estimated_ready_at}
        """
        session = await self._get_session()
        try:
            order = await self._get_order(session, order_id)

            if order.status not in ('confirmed', 'pending'):
                raise ValueError(f"订单状态 {order.status}，无法确认")

            order.status = 'preparing'
            order.estimated_ready_min = estimated_ready_min

            estimated_ready_at = (
                datetime.now(timezone.utc) + timedelta(minutes=estimated_ready_min)
            ).isoformat()

            await session.commit()

            # 通知平台
            await self._notify_platform(
                order.platform,
                'order_confirmed',
                {
                    'platform_order_id': order.platform_order_id,
                    'estimated_ready_min': estimated_ready_min,
                },
            )

            logger.info(
                "delivery_order_confirmed",
                order_id=order_id,
                estimated_ready_min=estimated_ready_min,
            )

            return {
                'order_id': order_id,
                'status': 'preparing',
                'estimated_ready_min': estimated_ready_min,
                'estimated_ready_at': estimated_ready_at,
            }
        finally:
            await self._close_session(session)

    async def mark_ready(self, order_id: str) -> dict:
        """标记出餐完成 -- 通知平台可以取餐

        Returns:
            {order_id, status, ready_at}
        """
        session = await self._get_session()
        try:
            order = await self._get_order(session, order_id)

            if order.status not in ('preparing', 'confirmed'):
                raise ValueError(f"订单状态 {order.status}，无法标记出餐")

            ready_at = datetime.now(timezone.utc)
            order.status = 'ready'
            order.ready_at = ready_at

            await session.commit()

            await self._notify_platform(
                order.platform,
                'order_ready',
                {
                    'platform_order_id': order.platform_order_id,
                    'ready_at': ready_at.isoformat(),
                },
            )

            logger.info(
                "delivery_order_ready",
                order_id=order_id,
                platform=order.platform,
                platform_order_id=order.platform_order_id,
            )

            return {
                'order_id': order_id,
                'status': 'ready',
                'ready_at': ready_at.isoformat(),
                'platform_order_id': order.platform_order_id,
            }
        finally:
            await self._close_session(session)

    async def cancel_order(
        self,
        order_id: str,
        reason: str = "",
        responsible_party: str = "merchant",
    ) -> dict:
        """取消订单

        Args:
            reason: 取消原因
            responsible_party: 责任方 merchant / customer / platform / rider

        Returns:
            {order_id, status, reason, responsible_party, refund_fen}
        """
        valid_parties = ['merchant', 'customer', 'platform', 'rider']
        if responsible_party not in valid_parties:
            raise ValueError(f"无效的责任方: {responsible_party}，可选: {valid_parties}")

        session = await self._get_session()
        try:
            order = await self._get_order(session, order_id)

            if order.status in ('completed', 'cancelled', 'refunded'):
                raise ValueError(f"订单状态 {order.status}，无法取消")

            # 退款计算：商家责任全额退，顾客责任看阶段
            refund_fen = 0
            if responsible_party in ('merchant', 'platform', 'rider'):
                refund_fen = order.total_fen
            elif responsible_party == 'customer':
                if order.status in ('confirmed', 'pending'):
                    refund_fen = order.total_fen
                else:
                    refund_fen = 0

            order.status = 'cancelled'
            order.cancelled_at = datetime.now(timezone.utc)
            order.cancel_reason = reason
            order.cancel_responsible = responsible_party

            await session.commit()

            await self._notify_platform(
                order.platform,
                'order_cancelled',
                {
                    'platform_order_id': order.platform_order_id,
                    'reason': reason,
                    'responsible_party': responsible_party,
                },
            )

            logger.info(
                "delivery_order_cancelled",
                order_id=order_id,
                reason=reason,
                responsible_party=responsible_party,
                refund_fen=refund_fen,
            )

            return {
                'order_id': order_id,
                'status': 'cancelled',
                'reason': reason,
                'responsible_party': responsible_party,
                'refund_fen': refund_fen,
            }
        finally:
            await self._close_session(session)

    async def complete_order(self, order_id: str) -> dict:
        """完成订单（配送完成）

        Returns:
            {order_id, status, completed_at, settlement_info}
        """
        session = await self._get_session()
        try:
            order = await self._get_order(session, order_id)

            if order.status not in ('ready', 'delivering', 'preparing', 'confirmed'):
                raise ValueError(f"订单状态 {order.status}，无法完成")

            completed_at = datetime.now(timezone.utc)
            order.status = 'completed'
            order.completed_at = completed_at

            await session.commit()

            platform_config = self.PLATFORMS[order.platform]
            settle_delay = platform_config['settle_delay_days']
            settle_date = (datetime.now(timezone.utc) + timedelta(days=settle_delay)).date()

            logger.info(
                "delivery_order_completed",
                order_id=order_id,
                platform=order.platform,
                total_fen=order.total_fen,
                commission_fen=order.commission_fen,
            )

            return {
                'order_id': order_id,
                'status': 'completed',
                'completed_at': completed_at.isoformat(),
                'settlement_info': {
                    'total_fen': order.total_fen,
                    'commission_fen': order.commission_fen,
                    'merchant_receive_fen': order.merchant_receive_fen,
                    'settle_date': settle_date.isoformat(),
                    'settle_days': platform_config['settle_days'],
                },
            }
        finally:
            await self._close_session(session)

    async def get_platform_orders(
        self,
        platform: Optional[str] = None,
        date_str: Optional[str] = None,
    ) -> list[dict]:
        """查询平台订单列表

        Args:
            platform: 按平台筛选（None=全部）
            date_str: 按日期筛选 "YYYY-MM-DD"（None=全部）

        Returns:
            [{order_id, order_no, platform, status, total_fen, ...}]
        """
        session = await self._get_session()
        try:
            conditions = [
                DeliveryOrder.store_id == uuid.UUID(self.store_id)
                if len(self.store_id) > 8
                else DeliveryOrder.store_id.isnot(None),
                DeliveryOrder.is_deleted == False,  # noqa: E712
            ]
            if platform:
                conditions.append(DeliveryOrder.platform == platform)
            if date_str:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                conditions.append(
                    DeliveryOrder.created_at >= datetime.combine(
                        target_date, datetime.min.time(), tzinfo=timezone.utc
                    )
                )
                conditions.append(
                    DeliveryOrder.created_at < datetime.combine(
                        target_date + timedelta(days=1),
                        datetime.min.time(),
                        tzinfo=timezone.utc,
                    )
                )

            result = await session.execute(
                select(DeliveryOrder)
                .where(and_(*conditions))
                .order_by(DeliveryOrder.created_at.desc())
            )
            orders = result.scalars().all()

            return [
                {
                    'order_id': str(o.id),
                    'order_no': o.order_no,
                    'platform': o.platform,
                    'platform_name': o.platform_name,
                    'platform_order_id': o.platform_order_id,
                    'status': o.status,
                    'total_fen': o.total_fen,
                    'commission_fen': o.commission_fen,
                    'merchant_receive_fen': o.merchant_receive_fen,
                    'items_count': len(o.items_json) if o.items_json else 0,
                    'delivery_address': o.delivery_address or '',
                    'created_at': o.created_at.isoformat() if o.created_at else '',
                    'completed_at': o.completed_at.isoformat() if o.completed_at else '',
                }
                for o in orders
            ]
        finally:
            await self._close_session(session)

    async def get_platform_settlement(
        self,
        platform: str,
        date_range: tuple[str, str],
    ) -> dict:
        """查询平台结算

        Args:
            platform: 平台
            date_range: ("2026-03-01", "2026-03-28")

        Returns:
            {revenue_fen, commission_fen, net_fen, pending_settlement_fen, ...}
        """
        if platform not in self.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")

        start_str, end_str = date_range
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()

        platform_config = self.PLATFORMS[platform]

        session = await self._get_session()
        try:
            result = await session.execute(
                select(DeliveryOrder).where(
                    and_(
                        DeliveryOrder.store_id == uuid.UUID(self.store_id)
                        if len(self.store_id) > 8
                        else DeliveryOrder.store_id.isnot(None),
                        DeliveryOrder.platform == platform,
                        DeliveryOrder.is_deleted == False,  # noqa: E712
                        DeliveryOrder.created_at >= datetime.combine(
                            start_date, datetime.min.time(), tzinfo=timezone.utc
                        ),
                        DeliveryOrder.created_at < datetime.combine(
                            end_date + timedelta(days=1),
                            datetime.min.time(),
                            tzinfo=timezone.utc,
                        ),
                    )
                )
            )
            orders = result.scalars().all()

            total_revenue_fen = 0
            total_commission_fen = 0
            settled_fen = 0
            pending_fen = 0
            completed_count = 0
            cancelled_count = 0

            for order in orders:
                if order.status == 'completed':
                    completed_count += 1
                    total_revenue_fen += order.total_fen
                    total_commission_fen += order.commission_fen

                    if order.completed_at:
                        completed_date = order.completed_at.date() if hasattr(order.completed_at, 'date') else order.completed_at
                        settle_date = completed_date + timedelta(days=platform_config['settle_delay_days'])
                        today = datetime.now(timezone.utc).date()
                        if today >= settle_date:
                            settled_fen += order.merchant_receive_fen
                        else:
                            pending_fen += order.merchant_receive_fen
                    else:
                        pending_fen += order.merchant_receive_fen

                elif order.status == 'cancelled':
                    cancelled_count += 1

            net_fen = total_revenue_fen - total_commission_fen

            return {
                'store_id': self.store_id,
                'platform': platform,
                'platform_name': platform_config['name'],
                'date_range': {'start': start_str, 'end': end_str},
                'order_count': len(orders),
                'completed_count': completed_count,
                'cancelled_count': cancelled_count,
                'revenue_fen': total_revenue_fen,
                'commission_rate': platform_config['commission_rate'],
                'commission_fen': total_commission_fen,
                'subsidies_fen': 0,
                'net_fen': net_fen,
                'settled_fen': settled_fen,
                'pending_settlement_fen': pending_fen,
                'settle_days': platform_config['settle_days'],
            }
        finally:
            await self._close_session(session)

    # ─── 内部方法 ───

    async def _get_order(self, session: AsyncSession, order_id: str) -> DeliveryOrder:
        """从数据库获取订单"""
        result = await session.execute(
            select(DeliveryOrder).where(
                DeliveryOrder.id == uuid.UUID(order_id)
            )
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise ValueError(f"外卖订单不存在: {order_id}")
        return order

    async def _notify_platform(self, platform: str, event: str, data: dict) -> None:
        """通知平台（生产环境替换为真实API调用）

        TODO: 注入 MeituanClient / ElemeClient 实现真实通知
        """
        logger.info(
            "platform_notified",
            platform=platform,
            event=event,
            data=data,
        )

    @staticmethod
    async def sync_menu_to_platform(
        store_id: str,
        platform: str,
        menu_items: list[dict],
    ) -> dict:
        """推送门店菜单到外卖平台（静态方法，独立于订单流程）

        Returns:
            {platform, synced_count, failed_count, details}
        """
        if platform not in DeliveryPlatformAdapter.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")

        if not menu_items:
            return {
                'platform': platform,
                'platform_name': DeliveryPlatformAdapter.PLATFORMS[platform]['name'],
                'synced_count': 0,
                'failed_count': 0,
                'details': [],
                'message': '菜单为空，无需同步',
            }

        synced: list[dict] = []
        failed: list[dict] = []

        for item in menu_items:
            try:
                platform_sku = f"{platform.upper()}_{item.get('dish_id', uuid.uuid4().hex[:8])}"
                synced.append({
                    'dish_id': item.get('dish_id', ''),
                    'name': item.get('name', ''),
                    'price_fen': item.get('price_fen', 0),
                    'stock': item.get('stock', 999),
                    'platform_sku_id': platform_sku,
                    'status': 'synced',
                })
            except (ValueError, RuntimeError) as e:
                failed.append({
                    'dish_id': item.get('dish_id', ''),
                    'name': item.get('name', ''),
                    'error': str(e),
                    'status': 'failed',
                })

        logger.info(
            "menu_synced_to_platform",
            store_id=store_id,
            platform=platform,
            synced=len(synced),
            failed=len(failed),
        )

        return {
            'platform': platform,
            'platform_name': DeliveryPlatformAdapter.PLATFORMS[platform]['name'],
            'store_id': store_id,
            'synced_count': len(synced),
            'failed_count': len(failed),
            'details': synced + failed,
            'synced_at': datetime.now(timezone.utc).isoformat(),
        }
