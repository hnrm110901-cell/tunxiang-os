"""收钱吧(Shouqianba/Upay) HTTP 客户端

官方API文档: https://doc.shouqianba.com/
基础URL: https://vsi-api.shouqianba.com
认证方式: MD5(body_json + terminal_key) 签名
所有金额单位: 分(fen)
"""

import asyncio
import hashlib
import json
import os
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()

# 收钱吧业务响应码
SQB_RESULT_SUCCESS = "SUCCESS"
SQB_RESULT_FAIL = "FAIL"
SQB_RESULT_IN_PROGRESS = "IN_PROGRESS"  # 支付处理中，需轮询


class ShouqianbaError(Exception):
    """收钱吧 API 调用异常"""

    def __init__(self, message: str, result_code: str = "", error_code: str = ""):
        super().__init__(message)
        self.result_code = result_code
        self.error_code = error_code


class ShouqianbaClient:
    """收钱吧聚合支付 HTTP 客户端

    支持 pay(B扫C)、precreate(C扫B)、query、refund、cancel 五个核心接口。
    使用 httpx.AsyncClient 全局连接池，MD5 签名认证。
    """

    PAY_TIMEOUT = 30.0  # 支付类接口超时(秒)
    DEFAULT_TIMEOUT = 10.0  # 普通接口超时(秒)
    POLL_INTERVAL = 2.0  # 轮询间隔(秒)
    MAX_POLL_ATTEMPTS = 15  # 最大轮询次数(30秒内)

    def __init__(
        self,
        terminal_sn: Optional[str] = None,
        terminal_key: Optional[str] = None,
        vendor_sn: Optional[str] = None,
        vendor_key: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.terminal_sn = terminal_sn or os.environ["SHOUQIANBA_TERMINAL_SN"]
        self.terminal_key = terminal_key or os.environ["SHOUQIANBA_TERMINAL_KEY"]
        self.vendor_sn = vendor_sn or os.environ.get("SHOUQIANBA_VENDOR_SN", "")
        self.vendor_key = vendor_key or os.environ.get("SHOUQIANBA_VENDOR_KEY", "")
        self._base_url = os.environ.get(
            "SHOUQIANBA_BASE_URL", "https://vsi-api.shouqianba.com"
        )
        self._external_client = http_client is not None
        self._client = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self.DEFAULT_TIMEOUT),
            headers={"Content-Type": "application/json"},
        )

    async def close(self) -> None:
        """关闭连接池（仅关闭内部创建的 client）"""
        if not self._external_client:
            await self._client.aclose()

    # ─── 核心接口 ───────────────────────────

    async def pay(
        self,
        client_sn: str,
        total_amount: int,
        dynamic_id: str,
        subject: str,
    ) -> dict:
        """B扫C — 商家扫顾客付款码

        Args:
            client_sn: 商户系统订单号(唯一)
            total_amount: 金额(分)
            dynamic_id: 顾客付款码内容
            subject: 订单标题

        Returns:
            收钱吧完整 biz_response 字典
        """
        if not client_sn:
            raise ValueError("client_sn 不能为空")
        if total_amount <= 0:
            raise ValueError(f"total_amount 必须大于0，当前值: {total_amount}")
        if not dynamic_id:
            raise ValueError("dynamic_id（付款码）不能为空")

        body = {
            "terminal_sn": self.terminal_sn,
            "client_sn": client_sn,
            "total_amount": str(total_amount),
            "dynamic_id": dynamic_id,
            "subject": subject or "收钱吧支付",
        }
        logger.info(
            "sqb_pay_request",
            client_sn=client_sn,
            total_amount=total_amount,
            subject=subject,
        )
        resp = await self._signed_request(
            "/upay/v2/pay", body, timeout=self.PAY_TIMEOUT
        )
        biz = self._extract_biz_response(resp, "pay")

        # 支付可能处于处理中，需要轮询
        if biz.get("order_status") in ("CREATED", "PAID", "PAY_CANCELED", "REFUNDED", "PARTIAL_REFUNDED"):
            return biz

        # IN_PROGRESS 或无明确状态时轮询
        sn = biz.get("sn")
        if sn:
            return await self._poll_order(sn, client_sn)

        return biz

    async def precreate(
        self,
        client_sn: str,
        total_amount: int,
        subject: str,
    ) -> dict:
        """C扫B — 顾客扫商家码，生成预支付二维码

        Args:
            client_sn: 商户系统订单号(唯一)
            total_amount: 金额(分)
            subject: 订单标题

        Returns:
            收钱吧完整 biz_response 字典，包含 qr_code 字段
        """
        if not client_sn:
            raise ValueError("client_sn 不能为空")
        if total_amount <= 0:
            raise ValueError(f"total_amount 必须大于0，当前值: {total_amount}")

        body = {
            "terminal_sn": self.terminal_sn,
            "client_sn": client_sn,
            "total_amount": str(total_amount),
            "subject": subject or "收钱吧支付",
        }
        logger.info(
            "sqb_precreate_request",
            client_sn=client_sn,
            total_amount=total_amount,
            subject=subject,
        )
        resp = await self._signed_request(
            "/upay/v2/precreate", body, timeout=self.PAY_TIMEOUT
        )
        return self._extract_biz_response(resp, "precreate")

    async def query(self, sn: str) -> dict:
        """查询订单状态

        Args:
            sn: 收钱吧订单号

        Returns:
            收钱吧完整 biz_response 字典
        """
        if not sn:
            raise ValueError("sn（订单号）不能为空")
        body = {
            "terminal_sn": self.terminal_sn,
            "sn": sn,
        }
        logger.info("sqb_query_request", sn=sn)
        resp = await self._signed_request("/upay/v2/query", body)
        return self._extract_biz_response(resp, "query")

    async def refund(
        self,
        sn: str,
        refund_request_no: str,
        refund_amount: int,
    ) -> dict:
        """退款

        Args:
            sn: 收钱吧原订单号
            refund_request_no: 退款请求号(唯一)
            refund_amount: 退款金额(分)

        Returns:
            收钱吧完整 biz_response 字典
        """
        if not sn:
            raise ValueError("sn（原订单号）不能为空")
        if not refund_request_no:
            raise ValueError("refund_request_no 不能为空")
        if refund_amount <= 0:
            raise ValueError(f"refund_amount 必须大于0，当前值: {refund_amount}")

        body = {
            "terminal_sn": self.terminal_sn,
            "sn": sn,
            "refund_request_no": refund_request_no,
            "refund_amount": str(refund_amount),
        }
        logger.info(
            "sqb_refund_request",
            sn=sn,
            refund_request_no=refund_request_no,
            refund_amount=refund_amount,
        )
        resp = await self._signed_request(
            "/upay/v2/refund", body, timeout=self.PAY_TIMEOUT
        )
        return self._extract_biz_response(resp, "refund")

    async def cancel(self, sn: str) -> dict:
        """撤单 — 未完成的支付可撤销

        Args:
            sn: 收钱吧订单号

        Returns:
            收钱吧完整 biz_response 字典
        """
        if not sn:
            raise ValueError("sn（订单号）不能为空")
        body = {
            "terminal_sn": self.terminal_sn,
            "sn": sn,
        }
        logger.info("sqb_cancel_request", sn=sn)
        resp = await self._signed_request(
            "/upay/v2/cancel", body, timeout=self.PAY_TIMEOUT
        )
        return self._extract_biz_response(resp, "cancel")

    # ─── 内部方法 ───────────────────────────

    def _sign(self, body_json: str) -> str:
        """MD5(body_json + terminal_key) 签名"""
        raw = body_json + self.terminal_key
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    async def _signed_request(
        self,
        path: str,
        body: dict,
        timeout: Optional[float] = None,
    ) -> dict:
        """发送带签名的 POST 请求

        Raises:
            ShouqianbaError: API 返回非成功状态
            httpx.HTTPStatusError: HTTP 状态码异常
            httpx.TimeoutException: 请求超时
        """
        body_json = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        sign = self._sign(body_json)

        headers = {
            "Authorization": f"{self.terminal_sn} {sign}",
            "Content-Type": "application/json",
        }

        request_timeout = timeout or self.DEFAULT_TIMEOUT

        try:
            response = await self._client.post(
                path,
                content=body_json,
                headers=headers,
                timeout=request_timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            logger.error("sqb_request_timeout", path=path, timeout=request_timeout)
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "sqb_http_error",
                path=path,
                status_code=exc.response.status_code,
                body=exc.response.text[:500],
            )
            raise

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "sqb_invalid_json_response",
                path=path,
                status_code=response.status_code,
                body_preview=response.text[:200],
            )
            raise ShouqianbaError(
                f"收钱吧返回非法JSON: {response.text[:100]}",
                result_code="INVALID_RESPONSE",
            ) from exc

        logger.debug(
            "sqb_response",
            path=path,
            result_code=data.get("result_code"),
        )
        return data

    def _extract_biz_response(self, resp: dict, operation: str) -> dict:
        """提取并校验业务响应

        Raises:
            ShouqianbaError: 业务失败
        """
        result_code = resp.get("result_code", "")
        error_code = resp.get("error_code", "")
        error_message = resp.get("error_message", "")

        if result_code == "200":
            biz = resp.get("biz_response", {})
            biz_result = biz.get("result_code", "")
            if biz_result == SQB_RESULT_SUCCESS:
                logger.info(
                    f"sqb_{operation}_success",
                    sn=biz.get("sn"),
                    order_status=biz.get("order_status"),
                )
                return biz
            if biz_result == SQB_RESULT_FAIL:
                logger.warning(
                    f"sqb_{operation}_biz_fail",
                    error_code=biz.get("error_code"),
                    error_message=biz.get("error_message"),
                )
                raise ShouqianbaError(
                    f"收钱吧{operation}业务失败: {biz.get('error_message', '')}",
                    result_code=biz_result,
                    error_code=biz.get("error_code", ""),
                )
            # IN_PROGRESS 等状态，返回 biz 让调用方处理
            return biz

        # 通信层失败
        logger.error(
            f"sqb_{operation}_error",
            result_code=result_code,
            error_code=error_code,
            error_message=error_message,
        )
        raise ShouqianbaError(
            f"收钱吧{operation}通信失败: {error_message}",
            result_code=result_code,
            error_code=error_code,
        )

    async def _poll_order(self, sn: str, client_sn: str) -> dict:
        """轮询订单状态直到终态

        B扫C 支付可能返回处理中，需要持续查询直到成功/失败。

        Raises:
            ShouqianbaError: 轮询超时或支付失败
        """
        for attempt in range(1, self.MAX_POLL_ATTEMPTS + 1):
            await asyncio.sleep(self.POLL_INTERVAL)
            logger.info(
                "sqb_poll_order",
                sn=sn,
                client_sn=client_sn,
                attempt=attempt,
            )
            try:
                biz = await self.query(sn)
            except ShouqianbaError:
                # 查询失败继续重试
                continue

            order_status = biz.get("order_status", "")
            if order_status == "PAID":
                return biz
            if order_status in ("PAY_CANCELED", "REFUNDED", "CANCEL"):
                raise ShouqianbaError(
                    f"支付已取消/退款: status={order_status}",
                    result_code="FAIL",
                    error_code=order_status,
                )

        # 轮询超时，尝试撤单
        logger.error(
            "sqb_poll_timeout",
            sn=sn,
            client_sn=client_sn,
            max_attempts=self.MAX_POLL_ATTEMPTS,
        )
        try:
            await self.cancel(sn)
        except ShouqianbaError:
            logger.error("sqb_cancel_after_timeout_failed", sn=sn)

        raise ShouqianbaError(
            f"支付轮询超时(>{self.MAX_POLL_ATTEMPTS * self.POLL_INTERVAL}秒)，已尝试撤单",
            result_code="TIMEOUT",
            error_code="POLL_TIMEOUT",
        )
