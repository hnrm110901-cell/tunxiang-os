"""
图片识菜路由 — POST /api/v1/vision/recognize-dish

识别流程（双方案）：
  方案A（Core ML Bridge 可用）：转发到 http://localhost:8100/vision/recognize
  方案B（fallback）：调用 Claude Vision API，结合门店菜单做匹配
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/vision", tags=["vision"])

COREML_BRIDGE_URL = "http://localhost:8100/vision/recognize"
COREML_TIMEOUT_SECONDS = 5.0


class RecognizeDishRequest(BaseModel):
    image_base64: str
    store_id: str


class DishMatch(BaseModel):
    dish_id: str
    dish_name: str
    price: float
    confidence: int
    thumbnail_url: str = ""


class RecognizeDishResponse(BaseModel):
    ok: bool
    data: dict[str, Any]


async def _fetch_menu_items(store_id: str) -> list[dict[str, Any]]:
    """从数据库查询门店可用菜品列表"""
    from sqlalchemy import text

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, name, price FROM dishes "
                "WHERE store_id = :store_id AND is_available = true AND is_deleted = false "
                "LIMIT 100"
            ),
            {"store_id": store_id},
        )
        rows = result.fetchall()
        return [{"id": str(r[0]), "name": r[1], "price": float(r[2])} for r in rows]


async def _recognize_via_coreml(image_base64: str, store_id: str) -> list[DishMatch] | None:
    """
    方案A：转发到 Core ML Bridge (port 8100)。
    如果 Bridge 不可用或超时，返回 None，上层 fallback 到方案B。
    """
    try:
        async with httpx.AsyncClient(timeout=COREML_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                COREML_BRIDGE_URL,
                json={"image_base64": image_base64, "store_id": store_id},
            )
            resp.raise_for_status()
            body = resp.json()
            matches_raw = body.get("matches") or body.get("data", {}).get("matches", [])
            return [DishMatch(**m) for m in matches_raw]
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.info("coreml_bridge_unavailable", store_id=store_id)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning("coreml_bridge_error", status=exc.response.status_code, store_id=store_id)
        return None


async def _recognize_via_claude(image_base64: str, store_id: str, tenant_id: str) -> list[DishMatch]:
    """
    方案B：使用 Claude Vision API 识别图片，从门店菜单中匹配。
    通过 ModelRouter 调用（统一成本追踪 + 熔断保护）。
    """
    try:
        from tx_agent.src.services.model_router import ModelRouter  # type: ignore[import]
    except ImportError:
        logger.warning("model_router_unavailable_vision_fallback", store_id=store_id)
        return []

    menu_items = await _fetch_menu_items(store_id)
    if not menu_items:
        # 无菜单数据时，仅做通用识别，无法匹配 dish_id
        logger.warning("no_menu_items_found", store_id=store_id)
        return []

    menu_text = "\n".join(f"- id={item['id']}, name={item['name']}, price={item['price']}" for item in menu_items)

    prompt = (
        "这是一道餐厅菜品的图片。请从以下菜单中找出最匹配的菜品名称（返回JSON）：\n"
        f"{menu_text}\n\n"
        "返回格式（仅 JSON，无额外说明）：\n"
        '{"matches": [{"dish_id": "...", "dish_name": "...", "confidence": 85}, ...]}\n'
        "confidence 为整数 0-100，最多返回 3 个最匹配结果，按置信度降序排列。"
    )

    raw_text = await ModelRouter().complete(
        tenant_id=tenant_id,
        task_type="standard_analysis",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=512,
    )
    raw_text = raw_text.strip()
    # 提取 JSON 部分（防止模型在 JSON 外加说明）
    start = raw_text.find("{")
    end = raw_text.rfind("}") + 1
    parsed = json.loads(raw_text[start:end])

    # 构建菜品价格 map，用于补充 price 字段
    price_map = {item["id"]: item["price"] for item in menu_items}

    results: list[DishMatch] = []
    for m in parsed.get("matches", []):
        dish_id = str(m.get("dish_id", ""))
        results.append(
            DishMatch(
                dish_id=dish_id,
                dish_name=str(m.get("dish_name", "")),
                price=price_map.get(dish_id, 0.0),
                confidence=int(m.get("confidence", 0)),
                thumbnail_url="",
            )
        )
    return results


@router.post("/recognize-dish", response_model=RecognizeDishResponse)
async def recognize_dish(
    body: RecognizeDishRequest,
    x_tenant_id: str | None = Header(default=None),
) -> RecognizeDishResponse:
    """
    图片识菜接口。

    方案A：优先转发到 Core ML Bridge (localhost:8100)。
    方案B：Bridge 不可用时 fallback 到 Claude Vision API。
    返回：{ok: true, data: {matches: [...]}}
    """
    logger.info(
        "recognize_dish_request",
        store_id=body.store_id,
        tenant_id=x_tenant_id,
        image_size=len(body.image_base64),
    )

    matches: list[DishMatch] | None = None

    # 方案A
    matches = await _recognize_via_coreml(body.image_base64, body.store_id)

    # 方案B fallback
    if matches is None:
        try:
            matches = await _recognize_via_claude(body.image_base64, body.store_id, x_tenant_id or "default")
        except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError) as exc:  # MLPS3-P0: 异常收窄
            logger.error("claude_vision_error", error=str(exc), store_id=body.store_id, exc_info=True)
            matches = []

    logger.info("recognize_dish_result", store_id=body.store_id, match_count=len(matches))

    return RecognizeDishResponse(
        ok=True,
        data={"matches": [m.model_dump() for m in matches]},
    )
