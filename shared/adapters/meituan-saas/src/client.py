"""美团外卖开放平台 API 客户端

基于 httpx.AsyncClient 连接池，支持：
- MD5 签名计算
- OAuth2 token 自动刷新
- 订单确认/取消/查询、菜品上传、结算对账
"""
import hashlib
import os
import time
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

# ─── 环境变量 ───

MEITUAN_APP_ID = os.getenv("MEITUAN_APP_ID", "")
MEITUAN_APP_SECRET = os.getenv("MEITUAN_APP_SECRET", "")
MEITUAN_STORE_ID = os.getenv("MEITUAN_STORE_ID", "")
MEITUAN_BASE_URL = os.getenv(
    "MEITUAN_BASE_URL", "https://waimaiopen.meituan.com/api/v2"
)


class MeituanAuthError(Exception):
    """OAuth2 认证失败"""


class MeituanAPIError(Exception):
    """美团 API 业务错误"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"美团API错误 [{code}]: {message}")


class MeituanClient:
    """美团外卖开放平台 HTTP 客户端（全局连接池）

    Args:
        app_id: 应用ID，默认读取环境变量 MEITUAN_APP_ID
        app_secret: 应用密钥，默认读取环境变量 MEITUAN_APP_SECRET
        store_id: 门店ID，默认读取环境变量 MEITUAN_STORE_ID
        base_url: API 基础URL
        timeout: 请求超时（秒）
        max_retries: 最大重试次数
    """

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        store_id: str = "",
        base_url: str = "",
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.app_id = app_id or MEITUAN_APP_ID
        self.app_secret = app_secret or MEITUAN_APP_SECRET
        self.store_id = store_id or MEITUAN_STORE_ID
        self.base_url = (base_url or MEITUAN_BASE_URL).rstrip("/")
        self.max_retries = max_retries

        if not self.app_id or not self.app_secret:
            raise ValueError("MEITUAN_APP_ID 和 MEITUAN_APP_SECRET 不能为空")

        self._http = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )

        # OAuth2 token 缓存
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

        logger.info(
            "meituan_client_init",
            app_id=self.app_id,
            store_id=self.store_id,
            base_url=self.base_url,
        )

    # ─── 签名 ───

    @staticmethod
    def compute_sign(url: str, params: dict[str, Any], app_secret: str) -> str:
        """MD5 签名：MD5(url + sorted_params_kv + app_secret)

        美团外卖开放平台签名规则：
        1. 拼接请求URL路径
        2. 将所有参数按key字典序排列，拼接 key=value
        3. 末尾追加 app_secret
        4. 整体 MD5
        """
        sorted_pairs = sorted(params.items(), key=lambda kv: kv[0])
        param_str = "".join(f"{k}={v}" for k, v in sorted_pairs)
        raw = url + param_str + app_secret
        return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()

    @staticmethod
    def verify_callback_sign(
        params: dict[str, Any], sign: str, app_secret: str
    ) -> bool:
        """验证美团回调签名：MD5(sorted_params_kv + app_secret)

        回调验签与请求签名略有不同，不含URL。
        """
        filtered = {k: v for k, v in params.items() if k != "sign"}
        sorted_pairs = sorted(filtered.items(), key=lambda kv: kv[0])
        param_str = "".join(f"{k}={v}" for k, v in sorted_pairs)
        raw = param_str + app_secret
        expected = hashlib.md5(raw.encode("utf-8")).hexdigest().lower()
        return expected == sign.lower()

    # ─── OAuth2 Token ───

    async def _ensure_token(self) -> str:
        """确保 access_token 有效，过期则自动刷新"""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        return await self._refresh_token()

    async def _refresh_token(self) -> str:
        """通过 OAuth2 获取/刷新 access_token"""
        url = f"{self.base_url}/token"
        params = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
            "grant_type": "client_credentials",
        }
        try:
            resp = await self._http.post(url, data=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise MeituanAuthError(
                f"Token 请求 HTTP 失败: {exc.response.status_code}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise MeituanAuthError(f"Token 请求超时: {exc}") from exc

        if data.get("error"):
            raise MeituanAuthError(
                f"Token 错误: {data.get('error_description', data.get('error'))}"
            )

        self._access_token = data["access_token"]
        # 美团 token 有效期通常 7200 秒
        self._token_expires_at = time.time() + int(data.get("expires_in", 7200))

        logger.info(
            "meituan_token_refreshed",
            expires_in=data.get("expires_in"),
        )
        return self._access_token

    # ─── 底层请求 ───

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """发送签名请求到美团 API，带重试

        Args:
            method: GET / POST
            path: API 路径，如 /order/confirm
            params: 业务参数（不含签名和token字段）

        Returns:
            API 响应 JSON

        Raises:
            MeituanAPIError: 业务错误
            MeituanAuthError: 认证失败
        """
        url = f"{self.base_url}{path}"
        token = await self._ensure_token()

        request_params: dict[str, Any] = {
            "app_id": self.app_id,
            "access_token": token,
            "timestamp": str(int(time.time())),
            **(params or {}),
        }
        request_params["sign"] = self.compute_sign(url, request_params, self.app_secret)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if method.upper() == "GET":
                    resp = await self._http.get(url, params=request_params)
                else:
                    resp = await self._http.post(url, data=request_params)

                resp.raise_for_status()
                result = resp.json()

                # 美团 API 正常返回 code=0 或 "ok"
                code = result.get("code")
                if code not in (0, "ok", "OK"):
                    raise MeituanAPIError(
                        code=int(code) if isinstance(code, (int, str)) and str(code).lstrip("-").isdigit() else -1,
                        message=result.get("msg", result.get("message", "未知错误")),
                    )

                logger.info(
                    "meituan_api_ok",
                    path=path,
                    attempt=attempt,
                )
                return result.get("data", result)

            except MeituanAPIError:
                raise
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.warning(
                    "meituan_api_http_error",
                    path=path,
                    status=exc.response.status_code,
                    attempt=attempt,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "meituan_api_network_error",
                    path=path,
                    error=str(exc),
                    attempt=attempt,
                )

        raise MeituanAPIError(
            code=-1,
            message=f"请求 {path} 失败（{self.max_retries}次重试后）: {last_exc}",
        )

    # ─── 订单接口 ───

    async def confirm_order(self, order_id: str) -> dict[str, Any]:
        """确认接单

        Args:
            order_id: 美团订单ID

        Returns:
            确认结果
        """
        return await self._request("POST", "/order/confirm", {"order_id": order_id})

    async def cancel_order(
        self, order_id: str, reason_code: int, reason: str
    ) -> dict[str, Any]:
        """取消订单

        Args:
            order_id: 美团订单ID
            reason_code: 取消原因代码
            reason: 取消原因文本
        """
        return await self._request(
            "POST",
            "/order/cancel",
            {
                "order_id": order_id,
                "reason_code": str(reason_code),
                "reason": reason,
            },
        )

    async def query_order(self, order_id: str) -> dict[str, Any]:
        """查询订单详情

        Args:
            order_id: 美团订单ID

        Returns:
            订单详情 dict
        """
        return await self._request("GET", "/order/detail", {"order_id": order_id})

    # ─── 菜品接口 ───

    async def upload_food(self, food_data: dict[str, Any]) -> dict[str, Any]:
        """上传菜品到美团

        Args:
            food_data: 菜品信息，包含 app_food_code, name, price, description 等

        Returns:
            上传结果
        """
        payload = {
            "app_poi_code": self.store_id,
            **food_data,
        }
        return await self._request("POST", "/food/upload", payload)

    # ─── 门店接口 ───

    async def query_store_info(self) -> dict[str, Any]:
        """查询门店信息"""
        return await self._request(
            "GET", "/store/info", {"app_poi_code": self.store_id}
        )

    # ─── 结算对账 ───

    async def query_settlement(self, date_str: str) -> dict[str, Any]:
        """查询指定日期结算数据

        Args:
            date_str: 日期 "YYYY-MM-DD"

        Returns:
            结算数据
        """
        return await self._request(
            "GET",
            "/settlement/queryByDate",
            {
                "app_poi_code": self.store_id,
                "date": date_str,
            },
        )

    # ─── 生命周期 ───

    async def close(self) -> None:
        """关闭 HTTP 连接池"""
        await self._http.aclose()
        logger.info("meituan_client_closed")
