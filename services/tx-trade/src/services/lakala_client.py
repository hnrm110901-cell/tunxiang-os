"""拉卡拉聚合支付 HTTP 客户端

官方API文档: 聚合支付系统接口文档v2.8（交易相关）
SIT地址:  https://test.wsmsd.cn/sit/jhzf
生产地址: https://papi.yufengfintech.com

认证方式: MD5签名
  - 所有参数(除sign/signType)按key的ASCII码排序
  - 拼接为 key1=value1&key2=value2 (空值不参与)
  - 末尾追加签名密钥(无分隔符)
  - MD5(utf-8)小写

金额单位: 本服务内部统一使用 分(fen)，调用拉卡拉 API 时自动转换为 元(yuan)
"""

import asyncio
import hashlib
import json
import os
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

# 拉卡拉业务响应状态
LKL_STATUS_SUCCESS = "S"
LKL_STATUS_FAIL = "F"
LKL_STATUS_PROCESSING = "P"  # 处理中，需轮询查询


class LakalaError(Exception):
    """拉卡拉 API 调用异常"""

    def __init__(self, message: str, rsp_code: str = "", rsp_status: str = ""):
        super().__init__(message)
        self.rsp_code = rsp_code
        self.rsp_status = rsp_status


class LakalaClient:
    """拉卡拉聚合支付 HTTP 客户端

    支持以下核心接口:
      - micropay:    B扫C 条码支付（收银员扫用户付款码）
      - jsapi:       C扫B/公众号统一下单（用户扫商户码）
      - mini_jsapi:  小程序支付
      - dynamic_qr:  动态码（一单一码）
      - query:       订单查询
      - refund:      退款
      - refund_query:退款查询
      - close:       关闭/撤销订单

    所有金额参数单位为 分(fen)，内部自动转换为元传给 API。
    使用 httpx.AsyncClient 共享连接池，条码支付自动轮询至终态。
    """

    # ─── 超时配置 ────────────────────────────────────────────────────────────────
    PAY_TIMEOUT = 30.0
    QUERY_TIMEOUT = 10.0
    POLL_INTERVAL = 2.0       # 轮询间隔（秒）
    MAX_POLL_ATTEMPTS = 15    # 最多轮询次数（30秒内）

    def __init__(
        self,
        merchant_no: str,
        sign_key: str,
        base_url: str = "",
        app_code: str = "",
        term_no: str = "",
        version: str = "1.0",
    ):
        """
        Args:
            merchant_no: 商户编号（聚合系统分配，字母数字下划线）
            sign_key:    签名密钥
            base_url:    API基础URL，留空则从环境变量 LAKALA_BASE_URL 读取
                         SIT: https://test.wsmsd.cn/sit/jhzf
                         生产: https://papi.yufengfintech.com
            app_code:    应用编码（可选）
            term_no:     终端号（可选）
            version:     接口版本号，默认 "1.0"
        """
        if not merchant_no:
            raise ValueError("merchant_no 不能为空")
        if not sign_key:
            raise ValueError("sign_key 不能为空")

        self.merchant_no = merchant_no
        self.sign_key = sign_key
        self.version = version
        self.app_code = app_code
        self.term_no = term_no

        self.base_url = (
            base_url
            or os.getenv("LAKALA_BASE_URL", "https://test.wsmsd.cn/sit/jhzf")
        ).rstrip("/")

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.PAY_TIMEOUT),
            verify=True,
        )

    # ─── 公共接口 ────────────────────────────────────────────────────────────────

    async def micropay(
        self,
        out_trade_no: str,
        amount_fen: int,
        subject: str,
        auth_code: str,
        spbill_ip: str,
        body: str = "",
        scan_type: str = "",
        attach: str = "",
        notify_url: str = "",
    ) -> dict:
        """B扫C 条码支付 — 收银员扫用户付款码

        Args:
            out_trade_no: 商户订单号（接入侧唯一，8-64位字母数字下划线横线）
            amount_fen:   订单金额（分）
            subject:      商品标题（0-127字符）
            auth_code:    用户付款码（微信/支付宝条码或二维码）
            spbill_ip:    终端IP
            body:         商品描述（可选）
            scan_type:    扫码类型 "0"=扫码 "1"=支付宝刷脸 "2"=微信刷脸
            attach:       附加数据（原样返回，可选）
            notify_url:   异步通知地址（可选）

        Returns:
            拉卡拉 biz 响应字典，rspStatus=S 表示成功

        Raises:
            LakalaError: 支付失败或轮询超时
        """
        if not out_trade_no:
            raise ValueError("out_trade_no 不能为空")
        if not isinstance(amount_fen, int) or amount_fen <= 0:
            raise ValueError(f"amount_fen 必须为正整数(分)，当前值: {amount_fen}")
        if not auth_code:
            raise ValueError("auth_code（付款码）不能为空")

        params = {
            "outTradeNo": out_trade_no,
            "totalAmount": self._fen_to_yuan(amount_fen),
            "goodSubject": subject,
            "authCode": auth_code,
            "spbillCreateIp": spbill_ip,
        }
        if body:
            params["body"] = body
        if scan_type:
            params["scanType"] = scan_type
        if attach:
            params["attach"] = attach
        if notify_url:
            params["notifyUrl"] = notify_url

        logger.info(
            "lakala_micropay_request",
            out_trade_no=out_trade_no,
            amount_fen=amount_fen,
        )

        resp = await self._request("/papi/micropay", params, timeout=self.PAY_TIMEOUT)
        rsp_status = resp.get("rspStatus", "")

        if rsp_status == LKL_STATUS_SUCCESS:
            logger.info(
                "lakala_micropay_success",
                out_trade_no=out_trade_no,
                transaction_id=resp.get("transactionId", ""),
            )
            return resp

        if rsp_status == LKL_STATUS_PROCESSING:
            # 需要输入密码 or 网络异常，轮询直到终态
            logger.info(
                "lakala_micropay_processing",
                out_trade_no=out_trade_no,
            )
            return await self._poll_order(out_trade_no)

        # 失败
        raise LakalaError(
            f"拉卡拉条码支付失败: {resp.get('rspMsg', '')}",
            rsp_code=resp.get("rspCode", ""),
            rsp_status=rsp_status,
        )

    async def jsapi(
        self,
        out_trade_no: str,
        amount_fen: int,
        subject: str,
        spbill_ip: str,
        pay_channel: str = "",
        sub_openid: str = "",
        buyer_id: str = "",
        body: str = "",
        attach: str = "",
        notify_url: str = "",
    ) -> dict:
        """统一下单支付 — C扫B/公众号/H5支付

        Args:
            out_trade_no: 商户订单号
            amount_fen:   订单金额（分）
            subject:      商品标题
            spbill_ip:    终端IP
            pay_channel:  支付渠道 WX/ALI/QP（可空由平台自动识别）
            sub_openid:   用户openID（微信公众号/小程序支付必传）
            buyer_id:     买家ID（支付宝可选）
            body:         商品描述
            attach:       附加数据
            notify_url:   异步通知地址

        Returns:
            拉卡拉下单结果字典（含 payInfo/prepayId 等支付凭证）
        """
        params = {
            "outTradeNo": out_trade_no,
            "totalAmount": self._fen_to_yuan(amount_fen),
            "goodSubject": subject,
            "spbillCreateIp": spbill_ip,
        }
        if pay_channel:
            params["payChannel"] = pay_channel
        if sub_openid:
            params["subOpenid"] = sub_openid
        if buyer_id:
            params["buyerId"] = buyer_id
        if body:
            params["body"] = body
        if attach:
            params["attach"] = attach
        if notify_url:
            params["notifyUrl"] = notify_url

        logger.info(
            "lakala_jsapi_request",
            out_trade_no=out_trade_no,
            amount_fen=amount_fen,
            pay_channel=pay_channel,
        )
        resp = await self._request("/papi/jsapi", params)
        self._check_response(resp, "统一下单")
        return resp

    async def mini_jsapi(
        self,
        out_trade_no: str,
        amount_fen: int,
        subject: str,
        spbill_ip: str,
        sub_openid: str = "",
        pay_channel: str = "",
        body: str = "",
        attach: str = "",
        notify_url: str = "",
    ) -> dict:
        """小程序支付

        Args:
            out_trade_no: 商户订单号
            amount_fen:   订单金额（分）
            subject:      商品标题
            spbill_ip:    终端IP
            sub_openid:   小程序用户openID
            pay_channel:  支付渠道 WX/ALI
            body:         商品描述
            attach:       附加数据
            notify_url:   异步通知地址

        Returns:
            下单结果字典（含小程序支付凭证）
        """
        params = {
            "outTradeNo": out_trade_no,
            "totalAmount": self._fen_to_yuan(amount_fen),
            "goodSubject": subject,
            "spbillCreateIp": spbill_ip,
        }
        if sub_openid:
            params["subOpenid"] = sub_openid
        if pay_channel:
            params["payChannel"] = pay_channel
        if body:
            params["body"] = body
        if attach:
            params["attach"] = attach
        if notify_url:
            params["notifyUrl"] = notify_url

        logger.info(
            "lakala_mini_jsapi_request",
            out_trade_no=out_trade_no,
            amount_fen=amount_fen,
        )
        resp = await self._request("/papi/minijsapi", params)
        self._check_response(resp, "小程序支付")
        return resp

    async def dynamic_qr(
        self,
        out_trade_no: str,
        amount_fen: int,
        subject: str,
        spbill_ip: str,
        body: str = "",
        attach: str = "",
        notify_url: str = "",
    ) -> dict:
        """动态码（一单一码）— 生成订单专属二维码

        Args:
            out_trade_no: 商户订单号
            amount_fen:   订单金额（分）
            subject:      商品标题
            spbill_ip:    终端IP
            body:         商品描述
            attach:       附加数据
            notify_url:   异步通知地址

        Returns:
            含二维码 URL 的字典
        """
        params = {
            "outTradeNo": out_trade_no,
            "totalAmount": self._fen_to_yuan(amount_fen),
            "goodSubject": subject,
            "spbillCreateIp": spbill_ip,
        }
        if body:
            params["body"] = body
        if attach:
            params["attach"] = attach
        if notify_url:
            params["notifyUrl"] = notify_url

        logger.info("lakala_dynamic_qr_request", out_trade_no=out_trade_no, amount_fen=amount_fen)
        resp = await self._request("/papi/dynamicqrurl", params)
        self._check_response(resp, "动态码")
        return resp

    async def query(self, out_trade_no: str) -> dict:
        """订单查询"""
        params = {"outTradeNo": out_trade_no}
        logger.info("lakala_query_request", out_trade_no=out_trade_no)
        return await self._request("/papi/query", params, timeout=self.QUERY_TIMEOUT)

    async def refund(
        self,
        out_trade_no: str,
        out_refund_no: str,
        refund_amount_fen: int,
        total_amount_fen: int,
        reason: str = "",
        notify_url: str = "",
    ) -> dict:
        """退款

        Args:
            out_trade_no:      原商户订单号
            out_refund_no:     商户退款单号（接入侧唯一）
            refund_amount_fen: 退款金额（分）
            total_amount_fen:  原订单总金额（分）
            reason:            退款原因（可选）
            notify_url:        退款异步通知地址（可选）
        """
        if refund_amount_fen <= 0:
            raise ValueError(f"退款金额必须大于0，当前值: {refund_amount_fen}")

        params = {
            "outTradeNo": out_trade_no,
            "outRefundNo": out_refund_no,
            "refundAmount": self._fen_to_yuan(refund_amount_fen),
            "totalAmount": self._fen_to_yuan(total_amount_fen),
        }
        if reason:
            params["refundReason"] = reason
        if notify_url:
            params["notifyUrl"] = notify_url

        logger.info(
            "lakala_refund_request",
            out_trade_no=out_trade_no,
            out_refund_no=out_refund_no,
            refund_amount_fen=refund_amount_fen,
        )
        resp = await self._request("/papi/refund", params)
        self._check_response(resp, "退款")
        return resp

    async def refund_query(self, out_trade_no: str = "", out_refund_no: str = "") -> dict:
        """退款查询"""
        params = {}
        if out_trade_no:
            params["outTradeNo"] = out_trade_no
        if out_refund_no:
            params["outRefundNo"] = out_refund_no
        return await self._request("/papi/refundquery", params, timeout=self.QUERY_TIMEOUT)

    async def close(self, out_trade_no: str) -> dict:
        """关闭/撤销订单"""
        params = {"outTradeNo": out_trade_no}
        logger.info("lakala_close_request", out_trade_no=out_trade_no)
        resp = await self._request("/papi/close", params)
        self._check_response(resp, "关单")
        return resp

    async def aclose(self) -> None:
        """关闭 HTTP 客户端连接池"""
        await self._client.aclose()

    # ─── 内部方法 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _fen_to_yuan(fen: int) -> str:
        """分转元，保留两位小数"""
        return f"{fen / 100:.2f}"

    def _sign(self, params: dict[str, Any]) -> str:
        """MD5签名（文档 §1.3）"""
        filtered = {
            k: v for k, v in params.items()
            if k not in ("sign", "signType") and v is not None and str(v) != ""
        }
        sorted_keys = sorted(filtered.keys())
        parts = []
        for k in sorted_keys:
            v = filtered[k]
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            parts.append(f"{k}={v}")

        sign_str = "&".join(parts) + self.sign_key
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    def _build_request_json(self, biz_params: dict[str, Any]) -> str:
        """构建带签名的 requestJson"""
        params: dict[str, Any] = {
            "version": self.version,
            "merchantNo": self.merchant_no,
            "signType": "MD5",
            "inputCharset": "UTF-8",
        }
        params.update(biz_params)
        params.setdefault("merchantNo", self.merchant_no)

        if self.app_code:
            params.setdefault("appCode", self.app_code)
        if self.term_no:
            params.setdefault("termNo", self.term_no)

        params = {k: v for k, v in params.items() if v is not None and str(v) != ""}
        params["sign"] = self._sign(params)
        return json.dumps(params, ensure_ascii=False)

    async def _request(
        self,
        path: str,
        biz_params: dict[str, Any],
        timeout: Optional[float] = None,
    ) -> dict:
        """发送 multipart/form-data 请求（requestJson 字段）"""
        request_json = self._build_request_json(biz_params)
        request_timeout = timeout or self.PAY_TIMEOUT

        try:
            response = await self._client.post(
                path,
                data={"requestJson": request_json},
                timeout=request_timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            logger.error("lakala_request_timeout", path=path, timeout=request_timeout)
            raise LakalaError(f"拉卡拉请求超时: {path}", rsp_code="TIMEOUT")
        except httpx.HTTPStatusError as exc:
            logger.error(
                "lakala_http_error",
                path=path,
                status_code=exc.response.status_code,
                body=exc.response.text[:300],
            )
            raise LakalaError(
                f"拉卡拉HTTP错误: {exc.response.status_code}",
                rsp_code="HTTP_ERROR",
            )

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("lakala_invalid_json", path=path, body_preview=response.text[:200])
            raise LakalaError(
                f"拉卡拉返回非法JSON: {response.text[:100]}",
                rsp_code="INVALID_RESPONSE",
            ) from exc

        logger.debug("lakala_response", path=path, rsp_status=data.get("rspStatus"))
        return data

    def _check_response(self, resp: dict, operation: str) -> None:
        """检查业务响应状态，失败时抛出 LakalaError"""
        rsp_status = resp.get("rspStatus", "")
        if rsp_status == LKL_STATUS_FAIL:
            raise LakalaError(
                f"拉卡拉{operation}失败: {resp.get('rspMsg', '')}",
                rsp_code=resp.get("rspCode", ""),
                rsp_status=rsp_status,
            )

    async def _poll_order(self, out_trade_no: str) -> dict:
        """轮询订单状态直到终态（B扫C 处理中时使用）"""
        for attempt in range(1, self.MAX_POLL_ATTEMPTS + 1):
            await asyncio.sleep(self.POLL_INTERVAL)
            logger.info("lakala_poll_order", out_trade_no=out_trade_no, attempt=attempt)
            try:
                result = await self.query(out_trade_no)
            except (LakalaError, httpx.RequestError):
                continue

            rsp_status = result.get("rspStatus", "")
            if rsp_status == LKL_STATUS_SUCCESS:
                logger.info("lakala_poll_success", out_trade_no=out_trade_no, attempt=attempt)
                return result
            if rsp_status == LKL_STATUS_FAIL:
                raise LakalaError(
                    f"支付最终失败: {result.get('rspMsg', '')}",
                    rsp_code=result.get("rspCode", ""),
                    rsp_status=LKL_STATUS_FAIL,
                )

        logger.error("lakala_poll_timeout", out_trade_no=out_trade_no, max_attempts=self.MAX_POLL_ATTEMPTS)
        try:
            await self.close(out_trade_no)
        except LakalaError:
            logger.error("lakala_close_after_timeout_failed", out_trade_no=out_trade_no)

        raise LakalaError(
            f"支付轮询超时(>{self.MAX_POLL_ATTEMPTS * self.POLL_INTERVAL}秒)，已尝试关单",
            rsp_code="POLL_TIMEOUT",
        )
