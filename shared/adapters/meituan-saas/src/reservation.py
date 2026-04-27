"""
美团预订适配器方法
提供预订确认、取消、查询等API调用
"""

from typing import Any, Dict

import structlog

logger = structlog.get_logger()


class MeituanReservationMixin:
    """美团预订操作混入类，用于扩展 MeituanSaasAdapter"""

    async def confirm_reservation(self, external_reservation_id: str) -> Dict[str, Any]:
        """确认预订"""
        params = {
            "reservation_id": external_reservation_id,
            "status": "confirmed",
        }
        result = await self._request("POST", "/api/reservation/confirm", data=params)
        logger.info("meituan_confirm_reservation", external_id=external_reservation_id)
        return result

    async def cancel_reservation(self, external_reservation_id: str, reason: str = "") -> Dict[str, Any]:
        """取消预订"""
        params = {
            "reservation_id": external_reservation_id,
            "status": "cancelled",
            "reason": reason,
        }
        result = await self._request("POST", "/api/reservation/cancel", data=params)
        logger.info("meituan_cancel_reservation", external_id=external_reservation_id)
        return result

    async def update_reservation_status(
        self,
        external_reservation_id: str,
        status: str,
    ) -> Dict[str, Any]:
        """更新预订状态（no_show/arrived/completed）"""
        params = {
            "reservation_id": external_reservation_id,
            "status": status,
        }
        result = await self._request("POST", "/api/reservation/update-status", data=params)
        logger.info("meituan_update_reservation_status", external_id=external_reservation_id, status=status)
        return result

    async def query_reservation(self, external_reservation_id: str) -> Dict[str, Any]:
        """查询预订详情"""
        params = {"reservation_id": external_reservation_id}
        result = await self._request("GET", "/api/reservation/detail", data=params)
        return result
