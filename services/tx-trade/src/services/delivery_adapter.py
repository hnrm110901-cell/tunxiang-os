"""外卖平台统一适配器 -- 美团/饿了么/抖音

统一接口处理三大平台的订单接入、状态同步、菜单推送、结算对账。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 内存存储（生产环境替换为数据库） ───

_delivery_orders: dict[str, dict] = {}       # order_id → order_data
_platform_menus: dict[str, dict] = {}         # store_id:platform → menu_sync_result
_platform_order_index: dict[str, str] = {}    # platform_order_id → order_id


def _gen_order_id() -> str:
    return str(uuid.uuid4())


def _gen_order_no(platform: str) -> str:
    prefix = {"meituan": "MT", "eleme": "EL", "douyin": "DY"}.get(platform, "DL")
    now = datetime.now(timezone.utc)
    return f"{prefix}{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class DeliveryPlatformAdapter:
    """外卖平台统一适配器 -- 美团/饿了么/抖音

    统一接口处理三大平台的订单接入。
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

    def __init__(self, store_id: str, brand_id: str, menu_items: Optional[list[dict]] = None):
        """
        Args:
            store_id: 门店ID
            brand_id: 品牌ID
            menu_items: 门店菜单 [{dish_id, name, price_fen, category, stock, sku_id}]
        """
        self.store_id = store_id
        self.brand_id = brand_id
        self.menu_items = menu_items or []

    def receive_order(
        self,
        platform: str,
        platform_order_id: str,
        items: list[dict],
        total_fen: int,
        customer_phone: str = "",
        delivery_address: str = "",
        expected_time: Optional[str] = None,
    ) -> dict:
        """接收平台订单 → 转换为TunxiangOS内部订单

        Args:
            platform: meituan / eleme / douyin
            platform_order_id: 平台原始订单号
            items: [{name, quantity, price_fen, sku_id?, notes?}]
            total_fen: 订单总额（分）
            customer_phone: 顾客电话（脱敏）
            delivery_address: 配送地址
            expected_time: 期望送达时间 ISO format

        Returns:
            {order_id, platform_order_id, status, items_mapped, commission_fen}
        """
        if platform not in self.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}，可选: {list(self.PLATFORMS.keys())}")

        if platform_order_id in _platform_order_index:
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

        unmapped_items = []
        for item in items:
            # 优先按sku匹配，其次按名称
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

        # 创建内部订单
        order_data = {
            'order_id': order_id,
            'order_no': order_no,
            'store_id': self.store_id,
            'brand_id': self.brand_id,
            'platform': platform,
            'platform_name': platform_config['name'],
            'platform_order_id': platform_order_id,
            'sales_channel': f"delivery_{platform}",
            'status': 'confirmed',
            'items': items_mapped,
            'total_fen': total_fen,
            'commission_rate': commission_rate,
            'commission_fen': commission_fen,
            'merchant_receive_fen': merchant_receive_fen,
            'customer_phone': customer_phone,
            'delivery_address': delivery_address,
            'expected_time': expected_time,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'confirmed_at': datetime.now(timezone.utc).isoformat(),
            'estimated_ready_min': None,
            'ready_at': None,
            'completed_at': None,
            'cancelled_at': None,
            'cancel_reason': None,
            'cancel_responsible': None,
            'unmapped_items': unmapped_items,
        }

        _delivery_orders[order_id] = order_data
        _platform_order_index[platform_order_id] = order_id

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

    def confirm_order(self, order_id: str, estimated_ready_min: int = 30) -> dict:
        """确认订单并设置预计出餐时间

        Args:
            order_id: 内部订单ID
            estimated_ready_min: 预计出餐分钟数

        Returns:
            {order_id, status, estimated_ready_min, estimated_ready_at}
        """
        order = self._get_order(order_id)

        if order['status'] not in ('confirmed', 'pending'):
            raise ValueError(f"订单状态 {order['status']}，无法确认")

        order['status'] = 'preparing'
        order['estimated_ready_min'] = estimated_ready_min

        estimated_ready_at = (
            datetime.now(timezone.utc) + timedelta(minutes=estimated_ready_min)
        ).isoformat()

        # 模拟通知平台
        self._notify_platform(
            order['platform'],
            'order_confirmed',
            {
                'platform_order_id': order['platform_order_id'],
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

    def mark_ready(self, order_id: str) -> dict:
        """标记出餐完成 — 通知平台可以取餐

        Returns:
            {order_id, status, ready_at}
        """
        order = self._get_order(order_id)

        if order['status'] not in ('preparing', 'confirmed'):
            raise ValueError(f"订单状态 {order['status']}，无法标记出餐")

        ready_at = datetime.now(timezone.utc).isoformat()
        order['status'] = 'ready'
        order['ready_at'] = ready_at

        # 通知平台出餐完成
        self._notify_platform(
            order['platform'],
            'order_ready',
            {
                'platform_order_id': order['platform_order_id'],
                'ready_at': ready_at,
            },
        )

        logger.info(
            "delivery_order_ready",
            order_id=order_id,
            platform=order['platform'],
            platform_order_id=order['platform_order_id'],
        )

        return {
            'order_id': order_id,
            'status': 'ready',
            'ready_at': ready_at,
            'platform_order_id': order['platform_order_id'],
        }

    def cancel_order(
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

        order = self._get_order(order_id)

        if order['status'] in ('completed', 'cancelled', 'refunded'):
            raise ValueError(f"订单状态 {order['status']}，无法取消")

        order['status'] = 'cancelled'
        order['cancelled_at'] = datetime.now(timezone.utc).isoformat()
        order['cancel_reason'] = reason
        order['cancel_responsible'] = responsible_party

        # 退款计算：商家责任全额退，顾客责任看阶段
        refund_fen = 0
        if responsible_party in ('merchant', 'platform', 'rider'):
            refund_fen = order['total_fen']
        elif responsible_party == 'customer':
            if order['status'] in ('confirmed', 'pending'):
                refund_fen = order['total_fen']  # 未开始制作，全退
            else:
                refund_fen = 0  # 已开始制作，不退

        # 通知平台
        self._notify_platform(
            order['platform'],
            'order_cancelled',
            {
                'platform_order_id': order['platform_order_id'],
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

    def complete_order(self, order_id: str) -> dict:
        """完成订单（配送完成）

        Returns:
            {order_id, status, completed_at, settlement_info}
        """
        order = self._get_order(order_id)

        if order['status'] not in ('ready', 'delivering', 'preparing', 'confirmed'):
            raise ValueError(f"订单状态 {order['status']}，无法完成")

        completed_at = datetime.now(timezone.utc).isoformat()
        order['status'] = 'completed'
        order['completed_at'] = completed_at

        # 计算结算时间
        platform_config = self.PLATFORMS[order['platform']]
        settle_delay = platform_config['settle_delay_days']
        settle_date = (datetime.now(timezone.utc) + timedelta(days=settle_delay)).date()

        logger.info(
            "delivery_order_completed",
            order_id=order_id,
            platform=order['platform'],
            total_fen=order['total_fen'],
            commission_fen=order['commission_fen'],
        )

        return {
            'order_id': order_id,
            'status': 'completed',
            'completed_at': completed_at,
            'settlement_info': {
                'total_fen': order['total_fen'],
                'commission_fen': order['commission_fen'],
                'merchant_receive_fen': order['merchant_receive_fen'],
                'settle_date': settle_date.isoformat(),
                'settle_days': platform_config['settle_days'],
            },
        }

    def sync_menu_to_platform(self, platform: str) -> dict:
        """推送门店菜单到外卖平台

        将TunxiangOS菜品 → 平台菜品（名称/价格/库存/图片）

        Returns:
            {platform, synced_count, failed_count, details}
        """
        if platform not in self.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")

        if not self.menu_items:
            return {
                'platform': platform,
                'platform_name': self.PLATFORMS[platform]['name'],
                'synced_count': 0,
                'failed_count': 0,
                'details': [],
                'message': '菜单为空，无需同步',
            }

        synced = []
        failed = []

        for item in self.menu_items:
            # 模拟推送到平台API
            try:
                platform_sku = self._push_menu_item_to_platform(platform, item)
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

        key = f"{self.store_id}:{platform}"
        result = {
            'platform': platform,
            'platform_name': self.PLATFORMS[platform]['name'],
            'store_id': self.store_id,
            'synced_count': len(synced),
            'failed_count': len(failed),
            'details': synced + failed,
            'synced_at': datetime.now(timezone.utc).isoformat(),
        }
        _platform_menus[key] = result

        logger.info(
            "menu_synced_to_platform",
            store_id=self.store_id,
            platform=platform,
            synced=len(synced),
            failed=len(failed),
        )

        return result

    def get_platform_orders(
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
        results = []
        target_date = None
        if date_str:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        for order_id, order in _delivery_orders.items():
            if order.get('store_id') != self.store_id:
                continue
            if platform and order.get('platform') != platform:
                continue
            if target_date:
                created = order.get('created_at', '')
                if created:
                    order_date = datetime.fromisoformat(created).date()
                    if order_date != target_date:
                        continue

            results.append({
                'order_id': order['order_id'],
                'order_no': order['order_no'],
                'platform': order['platform'],
                'platform_name': order.get('platform_name', ''),
                'platform_order_id': order['platform_order_id'],
                'status': order['status'],
                'total_fen': order['total_fen'],
                'commission_fen': order['commission_fen'],
                'merchant_receive_fen': order['merchant_receive_fen'],
                'items_count': len(order.get('items', [])),
                'delivery_address': order.get('delivery_address', ''),
                'created_at': order.get('created_at', ''),
                'completed_at': order.get('completed_at', ''),
            })

        return sorted(results, key=lambda x: x.get('created_at', ''), reverse=True)

    def get_platform_settlement(
        self,
        platform: str,
        date_range: tuple[str, str],
    ) -> dict:
        """查询平台结算

        Args:
            platform: 平台
            date_range: ("2026-03-01", "2026-03-27")

        Returns:
            {revenue_fen, commission_fen, subsidies_fen, net_fen, pending_settlement_fen, orders}
        """
        if platform not in self.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")

        start_str, end_str = date_range
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()

        platform_config = self.PLATFORMS[platform]

        total_revenue_fen = 0
        total_commission_fen = 0
        total_subsidies_fen = 0
        settled_fen = 0
        pending_fen = 0
        order_count = 0
        completed_count = 0
        cancelled_count = 0

        for order_id, order in _delivery_orders.items():
            if order.get('store_id') != self.store_id:
                continue
            if order.get('platform') != platform:
                continue

            created = order.get('created_at', '')
            if not created:
                continue
            order_date = datetime.fromisoformat(created).date()
            if order_date < start_date or order_date > end_date:
                continue

            order_count += 1

            if order['status'] == 'completed':
                completed_count += 1
                total_revenue_fen += order['total_fen']
                total_commission_fen += order['commission_fen']

                # 判断是否已结算
                completed_at = order.get('completed_at', '')
                if completed_at:
                    completed_date = datetime.fromisoformat(completed_at).date()
                    settle_date = completed_date + timedelta(days=platform_config['settle_delay_days'])
                    today = datetime.now(timezone.utc).date()
                    if today >= settle_date:
                        settled_fen += order['merchant_receive_fen']
                    else:
                        pending_fen += order['merchant_receive_fen']
                else:
                    pending_fen += order['merchant_receive_fen']

            elif order['status'] == 'cancelled':
                cancelled_count += 1

        net_fen = total_revenue_fen - total_commission_fen + total_subsidies_fen

        return {
            'store_id': self.store_id,
            'platform': platform,
            'platform_name': platform_config['name'],
            'date_range': {'start': start_str, 'end': end_str},
            'order_count': order_count,
            'completed_count': completed_count,
            'cancelled_count': cancelled_count,
            'revenue_fen': total_revenue_fen,
            'commission_rate': platform_config['commission_rate'],
            'commission_fen': total_commission_fen,
            'subsidies_fen': total_subsidies_fen,
            'net_fen': net_fen,
            'settled_fen': settled_fen,
            'pending_settlement_fen': pending_fen,
            'settle_days': platform_config['settle_days'],
        }

    def reconcile_platform(self, platform: str, date_str: str) -> dict:
        """平台订单对账 — 内部订单 vs 平台订单

        Returns:
            {matched, internal_only, platform_only, amount_mismatch, details}
        """
        if platform not in self.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")

        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        # 获取内部订单
        internal_orders = []
        for order_id, order in _delivery_orders.items():
            if order.get('store_id') != self.store_id:
                continue
            if order.get('platform') != platform:
                continue
            created = order.get('created_at', '')
            if created:
                order_date = datetime.fromisoformat(created).date()
                if order_date == target_date:
                    internal_orders.append(order)

        # 模拟从平台拉取的订单（实际调用平台API）
        # 这里用内部订单模拟，实际会有差异
        platform_orders = {
            o['platform_order_id']: {
                'platform_order_id': o['platform_order_id'],
                'total_fen': o['total_fen'],
                'status': o['status'],
            }
            for o in internal_orders
        }

        matched = 0
        internal_only = 0
        platform_only = 0
        amount_mismatch = 0
        details: list[dict] = []

        internal_pids = set()
        for order in internal_orders:
            pid = order['platform_order_id']
            internal_pids.add(pid)

            if pid in platform_orders:
                po = platform_orders[pid]
                if po['total_fen'] == order['total_fen']:
                    matched += 1
                    details.append({
                        'platform_order_id': pid,
                        'match_status': 'matched',
                        'internal_amount_fen': order['total_fen'],
                        'platform_amount_fen': po['total_fen'],
                    })
                else:
                    amount_mismatch += 1
                    details.append({
                        'platform_order_id': pid,
                        'match_status': 'amount_mismatch',
                        'internal_amount_fen': order['total_fen'],
                        'platform_amount_fen': po['total_fen'],
                        'diff_fen': order['total_fen'] - po['total_fen'],
                    })
            else:
                internal_only += 1
                details.append({
                    'platform_order_id': pid,
                    'match_status': 'internal_only',
                    'internal_amount_fen': order['total_fen'],
                })

        for pid in platform_orders:
            if pid not in internal_pids:
                platform_only += 1
                details.append({
                    'platform_order_id': pid,
                    'match_status': 'platform_only',
                    'platform_amount_fen': platform_orders[pid]['total_fen'],
                })

        return {
            'store_id': self.store_id,
            'platform': platform,
            'date': date_str,
            'total_internal': len(internal_orders),
            'total_platform': len(platform_orders),
            'matched': matched,
            'internal_only': internal_only,
            'platform_only': platform_only,
            'amount_mismatch': amount_mismatch,
            'details': details,
            'reconciled_at': datetime.now(timezone.utc).isoformat(),
        }

    # ─── 内部方法 ───

    def _get_order(self, order_id: str) -> dict:
        if order_id not in _delivery_orders:
            raise ValueError(f"外卖订单不存在: {order_id}")
        return _delivery_orders[order_id]

    def _notify_platform(self, platform: str, event: str, data: dict) -> None:
        """模拟通知平台（生产环境替换为真实API调用）"""
        logger.info(
            "platform_notified",
            platform=platform,
            event=event,
            data=data,
        )

    def _push_menu_item_to_platform(self, platform: str, item: dict) -> str:
        """模拟推送菜品到平台（返回平台SKU ID）"""
        platform_sku = f"{platform.upper()}_{item.get('dish_id', uuid.uuid4().hex[:8])}"
        logger.info(
            "menu_item_pushed",
            platform=platform,
            name=item.get('name', ''),
            price_fen=item.get('price_fen', 0),
            platform_sku=platform_sku,
        )
        return platform_sku

    @staticmethod
    def clear_all_data():
        """清除所有内存数据（测试用）"""
        _delivery_orders.clear()
        _platform_menus.clear()
        _platform_order_index.clear()
