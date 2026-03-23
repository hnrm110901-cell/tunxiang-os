"""
KDS 实时推送服务
管理 KDS 终端 WebSocket 连接，推送订单票据和状态变更
"""
from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import WebSocket

logger = structlog.get_logger()


class KDSPusher:
    """KDS 实时推送服务"""

    def __init__(self):
        # station_id -> list of WebSocket connections
        self.connections: dict[str, list[WebSocket]] = {}

    async def register(self, station_id: str, ws: WebSocket) -> None:
        """
        注册 KDS 终端 WebSocket 连接。

        Args:
            station_id: 档口/工位 ID
            ws: WebSocket 连接对象
        """
        if station_id not in self.connections:
            self.connections[station_id] = []
        self.connections[station_id].append(ws)
        logger.info(
            "kds_ws_registered",
            station_id=station_id,
            total=len(self.connections[station_id]),
        )

    async def unregister(self, station_id: str, ws: WebSocket) -> None:
        """
        注销 KDS 终端 WebSocket 连接。

        Args:
            station_id: 档口/工位 ID
            ws: WebSocket 连接对象
        """
        if station_id in self.connections:
            try:
                self.connections[station_id].remove(ws)
            except ValueError:
                pass
            if not self.connections[station_id]:
                del self.connections[station_id]
        logger.info(
            "kds_ws_unregistered",
            station_id=station_id,
            remaining=len(self.connections.get(station_id, [])),
        )

    async def _send_to_station(self, station_id: str, message: dict) -> int:
        """
        向指定档口的所有连接发送消息。

        Args:
            station_id: 档口ID
            message: 消息字典

        Returns:
            成功发送的连接数
        """
        conns = self.connections.get(station_id, [])
        sent = 0
        dead: list[WebSocket] = []

        for ws in conns:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as exc:
                logger.warning(
                    "kds_ws_send_failed",
                    station_id=station_id,
                    error=str(exc),
                )
                dead.append(ws)

        # 清理断开的连接
        for ws in dead:
            await self.unregister(station_id, ws)

        return sent

    async def push_new_ticket(self, station_id: str, ticket: dict) -> None:
        """
        订单下单 -> 推送新票据到对应档口。

        Args:
            station_id: 目标档口ID
            ticket: 票据数据，包含订单项、桌号等信息
        """
        message = {
            "type": "new_ticket",
            "station_id": station_id,
            "payload": ticket,
        }
        sent = await self._send_to_station(station_id, message)
        logger.info(
            "kds_new_ticket_pushed",
            station_id=station_id,
            ticket_id=ticket.get("ticket_id"),
            sent_count=sent,
        )

    async def push_status_change(self, ticket_id: str, new_status: str) -> None:
        """
        状态变更推送（制作中/完成/异常）。

        广播到所有档口，由前端根据 ticket_id 过滤。

        Args:
            ticket_id: 票据ID
            new_status: 新状态 ("cooking" | "done" | "error")
        """
        message = {
            "type": "status_change",
            "ticket_id": ticket_id,
            "new_status": new_status,
        }
        await self.broadcast_to_all(message)
        logger.info(
            "kds_status_change_pushed",
            ticket_id=ticket_id,
            new_status=new_status,
        )

    async def push_rush_order(self, ticket_id: str) -> None:
        """
        催菜推送（高亮+声音提示标记）。

        广播到所有档口，前端收到后高亮对应票据并播放提示音。

        Args:
            ticket_id: 被催的票据ID
        """
        message = {
            "type": "rush_order",
            "ticket_id": ticket_id,
            "alert": True,
            "sound": "rush",
        }
        await self.broadcast_to_all(message)
        logger.info("kds_rush_order_pushed", ticket_id=ticket_id)

    async def broadcast_to_all(self, message: dict) -> None:
        """
        广播到所有 KDS 终端。

        Args:
            message: 消息字典
        """
        total_sent = 0
        for station_id in list(self.connections.keys()):
            sent = await self._send_to_station(station_id, message)
            total_sent += sent
        logger.info(
            "kds_broadcast",
            message_type=message.get("type"),
            total_sent=total_sent,
        )

    def split_order_to_stations(self, order: dict) -> dict[str, list[dict]]:
        """
        按出品部门拆分订单到各档口。

        根据订单中每个菜品的 station_id / department 字段，
        将订单项拆分为多个档口的票据。

        Args:
            order: 原始订单字典，items 中每个菜品需包含 station_id 字段

        Returns:
            {station_id: [ticket_items]} 映射
        """
        station_items: dict[str, list[dict]] = {}

        for item in order.get("items", []):
            sid = item.get("station_id", item.get("department", "default"))
            if sid not in station_items:
                station_items[sid] = []
            station_items[sid].append(item)

        return station_items

    async def dispatch_new_order(self, order: dict) -> None:
        """
        接收新订单，按出品部门拆分并推送到各档口。

        Args:
            order: 订单字典
        """
        station_items = self.split_order_to_stations(order)

        for station_id, items in station_items.items():
            ticket = {
                "ticket_id": f"{order.get('order_id', '')}_{station_id}",
                "order_id": order.get("order_id"),
                "order_number": order.get("order_number"),
                "table_number": order.get("table_number"),
                "items": items,
                "created_at": order.get("created_at"),
                "remark": order.get("remark"),
            }
            await self.push_new_ticket(station_id, ticket)
