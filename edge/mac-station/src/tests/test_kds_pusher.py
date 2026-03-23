"""
KDS Pusher 测试
覆盖连接管理、票据推送、催菜广播、订单拆分
"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import sys
import os

# 将 mac-station/src 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kds_pusher import KDSPusher


def _make_ws_mock() -> AsyncMock:
    """创建一个模拟的 WebSocket 对象"""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


class TestKDSPusherRegistration:
    @pytest.mark.asyncio
    async def test_register_and_unregister(self):
        """注册和注销 WebSocket 连接"""
        pusher = KDSPusher()
        ws = _make_ws_mock()

        await pusher.register("station_a", ws)
        assert "station_a" in pusher.connections
        assert len(pusher.connections["station_a"]) == 1

        await pusher.unregister("station_a", ws)
        assert "station_a" not in pusher.connections

    @pytest.mark.asyncio
    async def test_register_multiple_connections(self):
        """同一档口多个连接"""
        pusher = KDSPusher()
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()

        await pusher.register("station_a", ws1)
        await pusher.register("station_a", ws2)
        assert len(pusher.connections["station_a"]) == 2

        await pusher.unregister("station_a", ws1)
        assert len(pusher.connections["station_a"]) == 1


class TestKDSPusherPush:
    @pytest.mark.asyncio
    async def test_push_new_ticket(self):
        """推送新票据到指定档口"""
        pusher = KDSPusher()
        ws = _make_ws_mock()
        await pusher.register("hot_kitchen", ws)

        ticket = {
            "ticket_id": "T001",
            "order_id": "ORD001",
            "table_number": "A5",
            "items": [{"dish_name": "宫保鸡丁", "quantity": 2}],
        }
        await pusher.push_new_ticket("hot_kitchen", ticket)

        ws.send_json.assert_called_once()
        sent_msg = ws.send_json.call_args[0][0]
        assert sent_msg["type"] == "new_ticket"
        assert sent_msg["station_id"] == "hot_kitchen"
        assert sent_msg["payload"]["ticket_id"] == "T001"

    @pytest.mark.asyncio
    async def test_push_rush_order_broadcast(self):
        """催菜推送广播到所有档口"""
        pusher = KDSPusher()
        ws_hot = _make_ws_mock()
        ws_cold = _make_ws_mock()

        await pusher.register("hot_kitchen", ws_hot)
        await pusher.register("cold_kitchen", ws_cold)

        await pusher.push_rush_order("T001")

        # 两个档口都应收到催菜消息
        ws_hot.send_json.assert_called_once()
        ws_cold.send_json.assert_called_once()

        msg = ws_hot.send_json.call_args[0][0]
        assert msg["type"] == "rush_order"
        assert msg["ticket_id"] == "T001"
        assert msg["alert"] is True
        assert msg["sound"] == "rush"


class TestKDSPusherSplit:
    def test_split_order_to_stations(self):
        """按出品部门拆分订单"""
        pusher = KDSPusher()
        order = {
            "order_id": "ORD001",
            "items": [
                {"dish_name": "宫保鸡丁", "station_id": "hot_kitchen"},
                {"dish_name": "拍黄瓜", "station_id": "cold_kitchen"},
                {"dish_name": "辣子鸡", "station_id": "hot_kitchen"},
                {"dish_name": "酸梅汤", "station_id": "drink_bar"},
            ],
        }

        result = pusher.split_order_to_stations(order)

        assert len(result) == 3
        assert len(result["hot_kitchen"]) == 2
        assert len(result["cold_kitchen"]) == 1
        assert len(result["drink_bar"]) == 1

    @pytest.mark.asyncio
    async def test_dispatch_new_order(self):
        """完整订单分发流程：拆分+推送"""
        pusher = KDSPusher()
        ws_hot = _make_ws_mock()
        ws_cold = _make_ws_mock()

        await pusher.register("hot_kitchen", ws_hot)
        await pusher.register("cold_kitchen", ws_cold)

        order = {
            "order_id": "ORD002",
            "order_number": "B002",
            "table_number": "B3",
            "items": [
                {"dish_name": "水煮鱼", "station_id": "hot_kitchen"},
                {"dish_name": "凉拌木耳", "station_id": "cold_kitchen"},
            ],
        }

        await pusher.dispatch_new_order(order)

        # 热菜档口收到 1 个 ticket
        assert ws_hot.send_json.call_count == 1
        hot_msg = ws_hot.send_json.call_args[0][0]
        assert hot_msg["type"] == "new_ticket"
        assert len(hot_msg["payload"]["items"]) == 1
        assert hot_msg["payload"]["items"][0]["dish_name"] == "水煮鱼"

        # 冷菜档口收到 1 个 ticket
        assert ws_cold.send_json.call_count == 1
        cold_msg = ws_cold.send_json.call_args[0][0]
        assert cold_msg["payload"]["items"][0]["dish_name"] == "凉拌木耳"
