"""
POS 实时推送器 — 通过 WebSocket 向收银终端推送折扣守护预警和运营通知

连接 URL: ws://mac-mini-ip:8000/ws/pos/{store_id}/{terminal_id}

设计说明：
- 单例模式，进程内共享连接注册表
- 按 store_id 分组管理 terminal_id → WebSocket 的映射
- 广播：push_discount_alert / push_operation_alert → 推送到门店所有在线终端
- 精准推送：push_to_terminal → 指定 terminal_id
- 死连接自动清理：发送失败时从注册表移除
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = structlog.get_logger()


# ─── 数据模型 ───


@dataclass
class DiscountAlert:
    """折扣守护预警数据结构"""
    alert_id: str          # uuid
    store_id: str
    order_id: str
    employee_id: str
    employee_name: str
    discount_rate: float   # 0.0-1.0，实际折扣率
    threshold: float       # 允许的最大折扣率
    amount_fen: int        # 折扣金额（分）
    risk_level: str        # "medium" | "high" | "critical"
    message: str           # 中文说明
    timestamp: str         # ISO 8601


@dataclass
class OperationAlert:
    """运营通知数据结构"""
    alert_id: str
    store_id: str
    alert_type: str   # "stock_low" | "expiry_warning" | "shift_reminder" | "sales_milestone"
    title: str
    body: str
    severity: str     # "info" | "warning" | "critical"
    timestamp: str    # ISO 8601


# ─── 推送器 ───


class POSPusher:
    """POS 实时推送服务

    管理 POS 收银终端的 WebSocket 连接，按 store_id 分组。
    支持广播（门店所有终端）和精准推送（指定 terminal_id）。
    """

    def __init__(self) -> None:
        # store_id -> { terminal_id -> WebSocket }
        self._connections: dict[str, dict[str, WebSocket]] = {}

    async def connect(self, store_id: str, terminal_id: str, websocket: WebSocket) -> None:
        """注册 POS 终端 WebSocket 连接。

        Args:
            store_id: 门店 ID
            terminal_id: 终端 ID（如 "pos-1"、"pos-main"）
            websocket: 已 accept 的 WebSocket 连接对象
        """
        if store_id not in self._connections:
            self._connections[store_id] = {}

        # 若同一终端重复连接，先关闭旧连接
        old_ws = self._connections[store_id].get(terminal_id)
        if old_ws is not None and old_ws is not websocket:
            try:
                await old_ws.close()
            except (RuntimeError, OSError):
                pass

        self._connections[store_id][terminal_id] = websocket
        logger.info(
            "pos_ws_connected",
            store_id=store_id,
            terminal_id=terminal_id,
            terminals_online=len(self._connections[store_id]),
        )

    def disconnect(self, store_id: str, terminal_id: str) -> None:
        """注销 POS 终端 WebSocket 连接（同步，由 endpoint finally 块调用）。

        Args:
            store_id: 门店 ID
            terminal_id: 终端 ID
        """
        store_map = self._connections.get(store_id)
        if store_map is None:
            return
        store_map.pop(terminal_id, None)
        if not store_map:
            del self._connections[store_id]
        logger.info(
            "pos_ws_disconnected",
            store_id=store_id,
            terminal_id=terminal_id,
            terminals_remaining=len(self._connections.get(store_id, {})),
        )

    async def push_discount_alert(self, store_id: str, alert: DiscountAlert) -> int:
        """向该门店所有在线 POS 终端广播折扣守护预警。

        Args:
            store_id: 门店 ID
            alert: 折扣预警数据

        Returns:
            成功送达的终端数
        """
        message = {
            "type": "discount_alert",
            "data": {
                "alert_id": alert.alert_id,
                "store_id": alert.store_id,
                "order_id": alert.order_id,
                "employee_id": alert.employee_id,
                "employee_name": alert.employee_name,
                "discount_rate": alert.discount_rate,
                "threshold": alert.threshold,
                "amount_fen": alert.amount_fen,
                "risk_level": alert.risk_level,
                "message": alert.message,
                "timestamp": alert.timestamp,
            },
        }
        sent = await self._broadcast_to_store(store_id, message)
        logger.info(
            "pos_discount_alert_pushed",
            store_id=store_id,
            alert_id=alert.alert_id,
            order_id=alert.order_id,
            risk_level=alert.risk_level,
            sent_count=sent,
        )
        return sent

    async def push_operation_alert(self, store_id: str, alert: OperationAlert) -> int:
        """向该门店所有在线 POS 终端广播运营通知。

        Args:
            store_id: 门店 ID
            alert: 运营通知数据

        Returns:
            成功送达的终端数
        """
        message = {
            "type": "operation_alert",
            "data": {
                "alert_id": alert.alert_id,
                "store_id": alert.store_id,
                "alert_type": alert.alert_type,
                "title": alert.title,
                "body": alert.body,
                "severity": alert.severity,
                "timestamp": alert.timestamp,
            },
        }
        sent = await self._broadcast_to_store(store_id, message)
        logger.info(
            "pos_operation_alert_pushed",
            store_id=store_id,
            alert_id=alert.alert_id,
            alert_type=alert.alert_type,
            severity=alert.severity,
            sent_count=sent,
        )
        return sent

    async def push_to_terminal(
        self, store_id: str, terminal_id: str, message: dict
    ) -> bool:
        """精准推送到指定终端。

        Args:
            store_id: 门店 ID
            terminal_id: 终端 ID
            message: 消息字典（需含 "type" 字段）

        Returns:
            True = 发送成功；False = 终端不在线或发送失败
        """
        store_map = self._connections.get(store_id)
        if not store_map:
            logger.warning(
                "pos_push_to_terminal_no_store",
                store_id=store_id,
                terminal_id=terminal_id,
            )
            return False

        ws = store_map.get(terminal_id)
        if ws is None:
            logger.warning(
                "pos_push_to_terminal_not_found",
                store_id=store_id,
                terminal_id=terminal_id,
            )
            return False

        try:
            if ws.client_state != WebSocketState.CONNECTED:
                self.disconnect(store_id, terminal_id)
                return False
            await ws.send_json(message)
            logger.debug(
                "pos_push_to_terminal_ok",
                store_id=store_id,
                terminal_id=terminal_id,
                msg_type=message.get("type"),
            )
            return True
        except (RuntimeError, OSError, ConnectionError) as exc:
            logger.warning(
                "pos_push_to_terminal_failed",
                store_id=store_id,
                terminal_id=terminal_id,
                error=str(exc),
            )
            self.disconnect(store_id, terminal_id)
            return False

    def get_connected_terminals(self, store_id: str) -> list[str]:
        """查询门店当前在线的终端 ID 列表。

        Args:
            store_id: 门店 ID

        Returns:
            在线 terminal_id 列表
        """
        return list(self._connections.get(store_id, {}).keys())

    # ─── 内部方法 ───

    async def _broadcast_to_store(self, store_id: str, message: dict) -> int:
        """向门店所有在线终端广播消息，自动清理死连接。

        Args:
            store_id: 门店 ID
            message: 消息字典

        Returns:
            成功送达的终端数
        """
        store_map = self._connections.get(store_id, {})
        if not store_map:
            logger.debug("pos_broadcast_no_terminals", store_id=store_id)
            return 0

        sent = 0
        dead: list[str] = []

        for terminal_id, ws in list(store_map.items()):
            try:
                if ws.client_state != WebSocketState.CONNECTED:
                    dead.append(terminal_id)
                    continue
                await ws.send_json(message)
                sent += 1
            except (RuntimeError, OSError, ConnectionError) as exc:
                logger.warning(
                    "pos_broadcast_send_failed",
                    store_id=store_id,
                    terminal_id=terminal_id,
                    error=str(exc),
                )
                dead.append(terminal_id)

        # 清理断开的连接（同步即可，避免 race condition）
        for terminal_id in dead:
            self.disconnect(store_id, terminal_id)

        return sent


# ─── 单例 ───

pos_pusher = POSPusher()
