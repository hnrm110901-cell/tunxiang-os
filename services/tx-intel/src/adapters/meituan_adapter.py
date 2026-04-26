"""美团平台适配器 — 采集门店信息、点评、菜单数据

采集规范：
  - 全部使用 httpx 异步请求
  - 每次请求间隔 ≥ 0.5 秒（rate limiting）
  - 失败自动重试最多 3 次，指数退避
  - 返回标准化 Pydantic V2 模型
  - 适配器失败只记录日志，不抛出到上层
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# 请求间隔（秒）
_RATE_LIMIT_SECS = 0.5
# 最大重试次数
_MAX_RETRIES = 3
# 重试基础等待（秒）
_RETRY_BASE_WAIT = 1.0


# ─── 标准化返回模型 ───


class MeituanStoreInfo(BaseModel):
    """美团门店基本信息"""

    platform_store_id: str
    name: str
    address: str
    city: str
    district: str
    cuisine_type: str
    price_tier: str  # 'economy' | 'mid_range' | 'mid_premium' | 'premium' | 'luxury'
    avg_rating: Decimal
    review_count: int
    price_per_person_fen: int  # 人均消费（分）
    is_open: bool
    business_hours: dict[str, Any]
    fetched_at: datetime


class MeituanReview(BaseModel):
    """美团单条点评"""

    review_id: str
    content: str
    rating: Decimal  # 1.0 ~ 5.0
    author_level: str  # 'regular' | 'vip' | 'kol'
    review_date: date
    reply: str | None = None
    tags: list[str] = Field(default_factory=list)


class MeituanDish(BaseModel):
    """美团菜单菜品"""

    dish_id: str
    name: str
    category: str
    price_fen: int
    monthly_sales: int
    is_active: bool
    is_recommended: bool
    image_url: str | None = None


# ─── HTTP 工具 ───


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """带重试和 rate limiting 的 HTTP 请求。失败时抛出最后一次异常。"""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            if attempt > 1:
                wait = _RETRY_BASE_WAIT * (2 ** (attempt - 2))
                logger.info(
                    "meituan_adapter.retry",
                    attempt=attempt,
                    wait_secs=wait,
                    url=url,
                )
                await asyncio.sleep(wait)
            else:
                await asyncio.sleep(_RATE_LIMIT_SECS)

            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            logger.warning(
                "meituan_adapter.http_error",
                status_code=exc.response.status_code,
                url=url,
                attempt=attempt,
            )
            if exc.response.status_code in (400, 401, 403, 404):
                # 非临时错误，不再重试
                raise
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning(
                "meituan_adapter.request_error",
                error=str(exc),
                url=url,
                attempt=attempt,
            )

    raise last_exc  # type: ignore[misc]


# ─── 适配器主体 ───


class MeituanAdapter:
    """美团平台适配器（异步）"""

    # 实际部署时从配置注入；此处为占位符，不硬编码真实密钥
    _BASE_URL = "https://api-open.meituan.com/v1"

    def __init__(self, app_key: str, app_secret: str) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                headers={
                    "X-App-Key": self._app_key,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── 签名工具（占位符，实际按美团开放平台规范实现）──

    def _build_signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """构建签名请求参数（占位符实现，正式接入时替换）"""
        import hashlib
        import hmac
        import time

        timestamp = str(int(time.time()))
        signed: dict[str, Any] = {**params, "app_key": self._app_key, "timestamp": timestamp}
        sorted_str = "&".join(f"{k}={v}" for k, v in sorted(signed.items()))
        sig = hmac.new(
            self._app_secret.encode(),
            sorted_str.encode(),
            hashlib.sha256,
        ).hexdigest()
        signed["sign"] = sig
        return signed

    # ── 公开接口 ──

    async def fetch_store_info(self, platform_store_id: str) -> MeituanStoreInfo:
        """采集门店基本信息"""
        log = logger.bind(adapter="meituan", action="fetch_store_info", store_id=platform_store_id)
        import time

        t0 = time.monotonic()

        client = await self._get_client()
        params = self._build_signed_params({"store_id": platform_store_id})
        raw = await _request_with_retry(client, "GET", f"{self._BASE_URL}/shop/getShopDetail", params=params)

        data: dict[str, Any] = raw.get("data", {})
        info = MeituanStoreInfo(
            platform_store_id=platform_store_id,
            name=data.get("shopName", ""),
            address=data.get("address", ""),
            city=data.get("cityName", ""),
            district=data.get("districtName", ""),
            cuisine_type=data.get("category", ""),
            price_tier=_map_price_tier(data.get("avgPrice", 0)),
            avg_rating=Decimal(str(data.get("avgStar", "0"))),
            review_count=data.get("reviewCount", 0),
            price_per_person_fen=int(data.get("avgPrice", 0) * 100),
            is_open=data.get("isOpen", False),
            business_hours=data.get("businessHours", {}),
            fetched_at=datetime.now(tz=timezone.utc),
        )

        elapsed = time.monotonic() - t0
        log.info("meituan_adapter.fetch_store_info.done", elapsed_ms=round(elapsed * 1000))
        return info

    async def fetch_recent_reviews(
        self,
        platform_store_id: str,
        days: int = 7,
    ) -> list[MeituanReview]:
        """采集最近 N 天的点评列表"""
        log = logger.bind(adapter="meituan", action="fetch_recent_reviews", store_id=platform_store_id, days=days)
        import time

        t0 = time.monotonic()

        client = await self._get_client()
        cutoff = date.today() - timedelta(days=days)
        reviews: list[MeituanReview] = []
        page = 1

        while True:
            params = self._build_signed_params(
                {
                    "store_id": platform_store_id,
                    "page": page,
                    "page_size": 50,
                }
            )
            raw = await _request_with_retry(client, "GET", f"{self._BASE_URL}/review/list", params=params)
            items: list[dict] = raw.get("data", {}).get("reviews", [])
            if not items:
                break

            for item in items:
                review_date_str: str = item.get("reviewTime", "")
                try:
                    review_date = date.fromisoformat(review_date_str[:10])
                except ValueError:
                    review_date = date.today()

                if review_date < cutoff:
                    # 超出时间窗口，后续页不再需要
                    log.debug("meituan_adapter.reviews.cutoff_reached", page=page)
                    break

                reviews.append(
                    MeituanReview(
                        review_id=str(item.get("reviewId", "")),
                        content=item.get("comment", ""),
                        rating=Decimal(str(item.get("star", "0"))),
                        author_level=_map_author_level(item.get("userLevel", 0)),
                        review_date=review_date,
                        reply=item.get("reply") or None,
                        tags=item.get("tags", []),
                    )
                )
            else:
                page += 1
                continue
            break  # cutoff_reached 时退出外层循环

        elapsed = time.monotonic() - t0
        log.info(
            "meituan_adapter.fetch_recent_reviews.done",
            review_count=len(reviews),
            elapsed_ms=round(elapsed * 1000),
        )
        return reviews

    async def fetch_competitor_menu(self, platform_store_id: str) -> list[MeituanDish]:
        """采集竞对菜单快照"""
        log = logger.bind(adapter="meituan", action="fetch_competitor_menu", store_id=platform_store_id)
        import time

        t0 = time.monotonic()

        client = await self._get_client()
        params = self._build_signed_params({"store_id": platform_store_id})
        raw = await _request_with_retry(client, "GET", f"{self._BASE_URL}/food/list", params=params)

        dishes: list[MeituanDish] = []
        for item in raw.get("data", {}).get("foodList", []):
            dishes.append(
                MeituanDish(
                    dish_id=str(item.get("spuId", "")),
                    name=item.get("name", ""),
                    category=item.get("category", ""),
                    price_fen=int(item.get("price", 0) * 100),
                    monthly_sales=item.get("monthlySales", 0),
                    is_active=item.get("status", 1) == 1,
                    is_recommended=item.get("isRecommend", False),
                    image_url=item.get("imageUrl") or None,
                )
            )

        elapsed = time.monotonic() - t0
        log.info(
            "meituan_adapter.fetch_competitor_menu.done",
            dish_count=len(dishes),
            elapsed_ms=round(elapsed * 1000),
        )
        return dishes


# ─── 内部辅助函数 ───


def _map_price_tier(avg_price_yuan: float) -> str:
    """将美团人均消费（元）映射到内部价格档位"""
    if avg_price_yuan < 30:
        return "economy"
    if avg_price_yuan < 60:
        return "mid_range"
    if avg_price_yuan < 120:
        return "mid_premium"
    if avg_price_yuan < 300:
        return "premium"
    return "luxury"


def _map_author_level(user_level: int) -> str:
    """将美团用户等级映射到内部作者分级"""
    if user_level >= 10:
        return "kol"
    if user_level >= 5:
        return "vip"
    return "regular"
