"""快递100 API 客户端

接入快递100开放平台，提供：
  1. 快递单号识别（自动识别快递公司）
  2. 物流轨迹实时查询
  3. 物流状态订阅（推送回调）

官方文档: https://api.kuaidi100.com/document/
认证方式: customer + key + sign(MD5)
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

KUAIDI100_API = "https://poll.kuaidi100.com"


class Kuaidi100Client:
    """快递100 API 客户端"""

    def __init__(self, customer: str, key: str) -> None:
        self.customer = customer
        self.key = key

    def _sign(self, param_json: str) -> str:
        """生成签名: MD5(param + key + customer)"""
        raw = param_json + self.key + self.customer
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    async def query_track(
        self,
        tracking_no: str,
        carrier_code: str = "",
    ) -> dict[str, Any]:
        """查询物流轨迹

        Args:
            tracking_no: 快递单号
            carrier_code: 快递公司编码（如 zhongtong, shunfeng）。
                          为空时先调 auto_detect 识别。

        Returns:
            {
                "status": "ok" | "error",
                "state": "0-在途 1-揽收 2-疑难 3-签收 4-退签 5-派件 6-退回 7-转投",
                "traces": [
                    {"time": "2026-04-01 14:23:00", "context": "包裹已到达长沙分拨中心"},
                    ...
                ]
            }
        """
        if not carrier_code:
            detect = await self.auto_detect(tracking_no)
            carrier_code = detect.get("carrier_code", "auto")

        param = json.dumps({
            "com": carrier_code,
            "num": tracking_no,
            "resultv2": "4",
        }, separators=(",", ":"))

        sign = self._sign(param)

        logger.info(
            "kuaidi100.query_track",
            tracking_no=tracking_no,
            carrier=carrier_code,
        )

        # TODO: 替换为 httpx 真实请求
        # async with httpx.AsyncClient() as client:
        #     resp = await client.post(
        #         f"{KUAIDI100_API}/poll/query.do",
        #         data={"customer": self.customer, "sign": sign, "param": param},
        #     )
        #     data = resp.json()

        return {
            "status": "ok",
            "state": "0",
            "carrier_code": carrier_code,
            "tracking_no": tracking_no,
            "traces": [
                {"time": "2026-04-01 08:00:00", "context": "包裹已揽收"},
                {"time": "2026-04-01 14:00:00", "context": "包裹已到达长沙分拨中心"},
                {"time": "2026-04-01 18:30:00", "context": "包裹正在派送中"},
            ],
        }

    async def auto_detect(self, tracking_no: str) -> dict[str, Any]:
        """自动识别快递公司

        Args:
            tracking_no: 快递单号

        Returns:
            {"carrier_code": str, "carrier_name": str}
        """
        logger.info("kuaidi100.auto_detect", tracking_no=tracking_no)

        # TODO: 替换为 httpx 真实请求
        # async with httpx.AsyncClient() as client:
        #     resp = await client.get(
        #         f"{KUAIDI100_API}/autonumber/autoComNum",
        #         params={"resultv2": "1", "key": self.key, "num": tracking_no},
        #     )
        #     data = resp.json()

        return {"carrier_code": "zhongtong", "carrier_name": "中通快递"}

    async def subscribe_push(
        self,
        tracking_no: str,
        carrier_code: str,
        callback_url: str,
    ) -> dict[str, Any]:
        """订阅物流推送

        快递100 会在物流状态变更时 POST 回调到 callback_url。
        """
        param = json.dumps({
            "company": carrier_code,
            "number": tracking_no,
            "callbackurl": callback_url,
            "resultv2": "4",
        }, separators=(",", ":"))

        sign = self._sign(param)

        logger.info(
            "kuaidi100.subscribe",
            tracking_no=tracking_no,
            carrier=carrier_code,
            callback=callback_url,
        )

        # TODO: 替换为真实请求
        return {"status": "ok", "subscribed": True}


class LogisticsTracker:
    """物流追踪器 — 封装快递100查询 + 状态解读"""

    STATE_MAP = {
        "0": "在途",
        "1": "揽收",
        "2": "疑难",
        "3": "已签收",
        "4": "退签",
        "5": "派件中",
        "6": "退回",
        "7": "转投",
        "10": "待清关",
        "11": "清关中",
        "12": "已清关",
        "13": "清关异常",
        "14": "拒签",
    }

    def __init__(self, customer: str, key: str) -> None:
        self.client = Kuaidi100Client(customer=customer, key=key)

    async def track(
        self,
        tracking_no: str,
        carrier_code: str = "",
    ) -> dict[str, Any]:
        """查询物流并附加状态中文描述"""
        result = await self.client.query_track(tracking_no, carrier_code)
        state_code = result.get("state", "0")
        result["state_label"] = self.STATE_MAP.get(state_code, "未知")
        return result
