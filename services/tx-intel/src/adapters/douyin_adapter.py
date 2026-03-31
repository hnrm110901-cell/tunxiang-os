"""抖音本地生活平台适配器 — 采集门店点评和热门菜品趋势

采集规范：
  - 全部使用 httpx 异步请求
  - 每次请求间隔 ≥ 0.5 秒（rate limiting）
  - 失败自动重试最多 3 次，指数退避
  - 返回标准化 Pydantic V2 模型
"""
import asyncio
import hashlib
import hmac
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

_RATE_LIMIT_SECS = 0.5
_MAX_RETRIES = 3
_RETRY_BASE_WAIT = 1.0


# ─── 标准化返回模型 ───

class DouyinReview(BaseModel):
    """抖音单条点评/评论"""
    review_id: str
    content: str
    rating: Decimal              # 1.0 ~ 5.0
    author_level: str            # 'regular' | 'vip' | 'kol'
    review_date: date
    like_count: int = 0
    tags: list[str] = Field(default_factory=list)


class DouyinTrendingDish(BaseModel):
    """抖音热门菜品趋势条目"""
    keyword: str
    category: str
    city: str
    cuisine_type: str
    trend_score: Decimal         # 0.00 ~ 100.00（平台热度指数标准化）
    trend_direction: str         # 'rising' | 'stable' | 'declining'
    mention_count: int           # 近7天提及量
    view_count: int              # 近7天相关视频播放量
    period_start: date
    period_end: date
    raw_data: dict[str, Any] = Field(default_factory=dict)


# ─── HTTP 工具 ───

async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """带重试和 rate limiting 的 HTTP 请求"""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            if attempt > 1:
                wait = _RETRY_BASE_WAIT * (2 ** (attempt - 2))
                logger.info(
                    "douyin_adapter.retry",
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
                "douyin_adapter.http_error",
                status_code=exc.response.status_code,
                url=url,
                attempt=attempt,
            )
            if exc.response.status_code in (400, 401, 403, 404):
                raise
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning(
                "douyin_adapter.request_error",
                error=str(exc),
                url=url,
                attempt=attempt,
            )

    raise last_exc  # type: ignore[misc]


# ─── 适配器主体 ───

class DouyinAdapter:
    """抖音本地生活适配器（异步）"""

    _BASE_URL = "https://openapi.life.douyin.com/v1"

    def __init__(self, client_key: str, client_secret: str) -> None:
        self._client_key = client_key
        self._client_secret = client_secret
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                headers={
                    "X-Client-Key": self._client_key,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _build_signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """构建签名请求参数（按抖音开放平台规范）"""
        timestamp = str(int(time.time()))
        signed: dict[str, Any] = {
            **params,
            "client_key": self._client_key,
            "timestamp": timestamp,
        }
        sorted_str = "&".join(f"{k}={v}" for k, v in sorted(signed.items()))
        sig = hmac.new(
            self._client_secret.encode(),
            sorted_str.encode(),
            hashlib.sha256,
        ).hexdigest()
        signed["sign"] = sig
        return signed

    async def fetch_store_reviews(
        self,
        platform_store_id: str,
        days: int = 7,
    ) -> list[DouyinReview]:
        """采集抖音门店最近 N 天点评"""
        log = logger.bind(
            adapter="douyin",
            action="fetch_store_reviews",
            store_id=platform_store_id,
            days=days,
        )
        t0 = time.monotonic()

        client = await self._get_client()
        cutoff = date.today() - timedelta(days=days)
        reviews: list[DouyinReview] = []
        cursor: str | None = None

        while True:
            params = self._build_signed_params({
                "poi_id": platform_store_id,
                "count": 50,
                **({"cursor": cursor} if cursor else {}),
            })
            raw = await _request_with_retry(
                client, "GET",
                f"{self._BASE_URL}/poi/comment/list",
                params=params,
            )
            data = raw.get("data", {})
            items: list[dict] = data.get("comments", [])
            if not items:
                break

            for item in items:
                date_str: str = item.get("createTime", "")
                try:
                    review_date = date.fromisoformat(date_str[:10])
                except ValueError:
                    review_date = date.today()

                if review_date < cutoff:
                    log.debug("douyin_adapter.reviews.cutoff_reached", cursor=cursor)
                    items = []  # 触发外层 break
                    break

                reviews.append(DouyinReview(
                    review_id=str(item.get("commentId", "")),
                    content=item.get("content", ""),
                    rating=Decimal(str(item.get("star", "0"))),
                    author_level=_map_author_level(item.get("authorLevel", "")),
                    review_date=review_date,
                    like_count=item.get("likeCount", 0),
                    tags=item.get("tags", []),
                ))

            if not items:
                break

            cursor = data.get("cursor")
            if not cursor or not data.get("hasMore", False):
                break

        elapsed = time.monotonic() - t0
        log.info(
            "douyin_adapter.fetch_store_reviews.done",
            review_count=len(reviews),
            elapsed_ms=round(elapsed * 1000),
        )
        return reviews

    async def fetch_trending_dishes(
        self,
        city: str,
        cuisine_type: str,
    ) -> list[DouyinTrendingDish]:
        """采集某城市/菜系的热门菜品趋势"""
        log = logger.bind(
            adapter="douyin",
            action="fetch_trending_dishes",
            city=city,
            cuisine_type=cuisine_type,
        )
        t0 = time.monotonic()

        client = await self._get_client()
        period_end = date.today()
        period_start = period_end - timedelta(days=7)

        params = self._build_signed_params({
            "city": city,
            "category": cuisine_type,
            "date_from": period_start.isoformat(),
            "date_to": period_end.isoformat(),
            "limit": 50,
        })
        raw = await _request_with_retry(
            client, "GET",
            f"{self._BASE_URL}/trend/dish/ranking",
            params=params,
        )

        trends: list[DouyinTrendingDish] = []
        for item in raw.get("data", {}).get("dishes", []):
            raw_score: float = item.get("heatIndex", 0)
            trends.append(DouyinTrendingDish(
                keyword=item.get("dishName", ""),
                category=item.get("category", cuisine_type),
                city=city,
                cuisine_type=cuisine_type,
                trend_score=Decimal(str(min(100.0, raw_score))),
                trend_direction=_map_trend_direction(item.get("trend", "")),
                mention_count=item.get("mentionCount", 0),
                view_count=item.get("viewCount", 0),
                period_start=period_start,
                period_end=period_end,
                raw_data=item,
            ))

        elapsed = time.monotonic() - t0
        log.info(
            "douyin_adapter.fetch_trending_dishes.done",
            trend_count=len(trends),
            city=city,
            cuisine_type=cuisine_type,
            elapsed_ms=round(elapsed * 1000),
        )
        return trends


# ─── 内部辅助函数 ───

def _map_author_level(level_str: str) -> str:
    """将抖音用户等级字符串映射到内部作者分级"""
    level_lower = level_str.lower()
    if any(k in level_lower for k in ("kol", "达人", "v+")):
        return "kol"
    if any(k in level_lower for k in ("vip", "会员", "黄金", "钻石")):
        return "vip"
    return "regular"


def _map_trend_direction(trend_str: str) -> str:
    """将抖音趋势方向标识映射到内部枚举"""
    mapping = {
        "up": "rising",
        "rise": "rising",
        "rising": "rising",
        "stable": "stable",
        "flat": "stable",
        "down": "declining",
        "fall": "declining",
        "declining": "declining",
    }
    return mapping.get(trend_str.lower(), "stable")
