"""外卖平台 Webhook 回调接口

接收美团/饿了么/抖音外卖订单推送，验签后解析订单并持久化到数据库。
"""
import hashlib
import hmac as hmac_mod
import os
import time
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..services.delivery_adapter import DeliveryPlatformAdapter

logger = structlog.get_logger()

# 美团回调签名密钥
MEITUAN_APP_SECRET = os.environ.get("MEITUAN_APP_SECRET", "")

# 时间戳容许偏差（秒）— 美团/饿了么/抖音共用
_TIMESTAMP_TOLERANCE = 300


def _verify_meituan_callback_sign(params: dict[str, Any], sign: str) -> bool:
    """验证美团回调签名：MD5(sorted_params_kv + app_secret)

    包含时间戳防重放校验（美团推送 params 中含 timestamp 字段）。
    """
    if not MEITUAN_APP_SECRET:
        logger.error("meituan_webhook_no_secret_configured")
        return False

    # 时间戳防重放
    ts_str = str(params.get("timestamp", ""))
    if ts_str:
        try:
            ts = int(ts_str)
            if abs(int(time.time()) - ts) > _TIMESTAMP_TOLERANCE:
                logger.warning("meituan_webhook_timestamp_expired", diff=abs(int(time.time()) - ts))
                return False
        except (ValueError, TypeError):
            logger.warning("meituan_webhook_bad_timestamp", timestamp=ts_str)
            return False

    filtered = {k: v for k, v in params.items() if k != "sign"}
    sorted_pairs = sorted(filtered.items(), key=lambda kv: kv[0])
    param_str = "".join(f"{k}={v}" for k, v in sorted_pairs)
    raw = param_str + MEITUAN_APP_SECRET
    expected = hashlib.md5(raw.encode("utf-8")).hexdigest().lower()
    return hmac_mod.compare_digest(expected, sign.lower())

router = APIRouter(prefix="/api/v1/webhook", tags=["webhook"])


# ─── 请求/响应模型 ───


class MeituanOrderPushReq(BaseModel):
    """美团订单推送请求体（核心字段）

    美团推送的字段远多于此，这里仅建模必须字段，其余从 raw body 提取。
    """
    order_id: str
    app_poi_code: str = ""
    day_seq: str = ""
    status: int = 1
    order_total_price: int = 0  # 分
    detail: str = ""  # JSON string: [{app_food_code, food_name, quantity, price, ...}]
    recipient_phone: str = ""
    recipient_address: str = ""
    delivery_time: str = ""
    caution: str = ""
    sign: str = ""


class WebhookResp(BaseModel):
    """统一 Webhook 响应"""
    ok: bool
    data: dict[str, Any] = {}
    error: dict[str, Any] | None = None


# ─── 辅助函数 ───


def _get_tenant_id(request: Request) -> str:
    """从请求中提取 tenant_id

    美团 webhook 不会带 X-Tenant-ID header，需要根据 app_poi_code 映射。
    开发阶段使用 header 或 query param 传入。
    """
    tid = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
        or request.query_params.get("tenant_id", "")
    )
    if not tid:
        raise HTTPException(
            status_code=400,
            detail="无法确定 tenant_id，请配置门店-租户映射或传入 X-Tenant-ID",
        )
    return tid


def _parse_meituan_items(detail_str: str) -> list[dict[str, Any]]:
    """解析美团推送的菜品明细 JSON 字符串

    美团 detail 字段是一个 JSON 数组的字符串形式:
    [{"app_food_code": "F001", "food_name": "宫保鸡丁", "quantity": 2, "price": 2800, ...}]
    """
    import json

    if not detail_str:
        return []

    try:
        items_raw = json.loads(detail_str)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("meituan_detail_parse_failed", error=str(exc))
        return []

    items: list[dict[str, Any]] = []
    for item in items_raw:
        items.append({
            "name": item.get("food_name", ""),
            "quantity": int(item.get("quantity", 1)),
            "price_fen": int(item.get("price", 0)),
            "sku_id": item.get("app_food_code", ""),
            "notes": item.get("food_property", ""),
        })
    return items


# ─── 路由 ───


@router.post("/meituan/order", response_model=WebhookResp)
async def meituan_order_push(request: Request) -> WebhookResp:
    """接收美团外卖订单推送

    美团会将新订单以 POST 形式推送到此回调地址。
    流程：
    1. 解析 form body（美团用 application/x-www-form-urlencoded）
    2. 验签
    3. 解析订单 → 调用 delivery_adapter.receive_order()
    4. 返回 {"data": "ok"} 告知美团接收成功
    """
    # 美团推送通常是 form-encoded
    try:
        form_data = await request.form()
        body: dict[str, Any] = dict(form_data)
    except (ValueError, KeyError):
        # 也可能是 JSON
        try:
            body = await request.json()
        except (ValueError, KeyError) as exc:
            logger.error("meituan_webhook_bad_body", error=str(exc))
            raise HTTPException(status_code=400, detail="请求体解析失败") from exc

    logger.info(
        "meituan_webhook_received",
        order_id=body.get("order_id", ""),
        app_poi_code=body.get("app_poi_code", ""),
    )

    # ── 1. 验签 ──
    sign = str(body.get("sign", ""))
    if not sign:
        logger.warning("meituan_webhook_no_sign")
        raise HTTPException(status_code=403, detail="缺少签名")

    if not _verify_meituan_callback_sign(body, sign):
        logger.warning(
            "meituan_webhook_sign_invalid",
            order_id=body.get("order_id", ""),
        )
        raise HTTPException(status_code=403, detail="签名验证失败")

    # ── 2. 提取关键字段 ──
    order_id = str(body.get("order_id", ""))
    if not order_id:
        raise HTTPException(status_code=400, detail="缺少 order_id")

    total_fen = int(body.get("order_total_price", 0))
    items = _parse_meituan_items(str(body.get("detail", "")))

    # ── 3. 获取 tenant_id 并创建 DB session ──
    tenant_id = _get_tenant_id(request)

    # ── 4. 调用统一适配器接收订单 ──
    # store_id / brand_id 从门店配置中获取，开发阶段从参数传入
    store_id = str(body.get("app_poi_code", ""))
    brand_id = request.headers.get("X-Brand-ID", "default")

    adapter = DeliveryPlatformAdapter(
        store_id=store_id,
        brand_id=brand_id,
        tenant_id=tenant_id,
    )

    try:
        result = await adapter.receive_order(
            platform="meituan",
            platform_order_id=order_id,
            items=items,
            total_fen=total_fen,
            customer_phone=str(body.get("recipient_phone", "")),
            delivery_address=str(body.get("recipient_address", "")),
            expected_time=str(body.get("delivery_time", "")),
            notes=str(body.get("caution", "")),
        )
    except ValueError as exc:
        logger.warning("meituan_webhook_order_error", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(
        "meituan_webhook_order_saved",
        order_id=result["order_id"],
        order_no=result["order_no"],
        platform_order_id=order_id,
    )

    return WebhookResp(ok=True, data=result)


# ══════════════════════════════════════════════════════════
#  饿了么订单推送
# ══════════════════════════════════════════════════════════

ELEME_APP_SECRET = os.environ.get("ELEME_APP_SECRET", "")
DOUYIN_APP_SECRET = os.environ.get("DOUYIN_APP_SECRET", "")


def _verify_eleme_signature(payload: str, signature: str, timestamp: str) -> bool:
    """饿了么签名验证: SHA256(app_secret + payload + timestamp + app_secret) 大写hex"""
    if not ELEME_APP_SECRET:
        logger.error("eleme_webhook_no_secret_configured")
        return False

    try:
        ts = int(timestamp)
        if abs(int(time.time()) - ts) > _TIMESTAMP_TOLERANCE:
            logger.warning("eleme_webhook_timestamp_expired", diff=abs(int(time.time()) - ts))
            return False
    except (ValueError, TypeError):
        logger.warning("eleme_webhook_bad_timestamp", timestamp=timestamp)
        return False

    sign_str = f"{ELEME_APP_SECRET}{payload}{timestamp}{ELEME_APP_SECRET}"
    expected = hashlib.sha256(sign_str.encode("utf-8")).hexdigest().upper()
    return hmac_mod.compare_digest(expected, signature.upper())


@router.post("/eleme/order", response_model=WebhookResp)
async def eleme_order_push(request: Request) -> WebhookResp:
    """接收饿了么订单推送

    Headers:
      - X-Eleme-Signature: SHA256 签名
      - X-Eleme-Timestamp: 时间戳（秒）
    """
    signature = request.headers.get("X-Eleme-Signature", "")
    timestamp = request.headers.get("X-Eleme-Timestamp", "")
    raw_body = (await request.body()).decode("utf-8")

    if not _verify_eleme_signature(raw_body, signature, timestamp):
        logger.warning("eleme_webhook_signature_invalid")
        raise HTTPException(status_code=403, detail="签名验证失败")

    try:
        body: dict[str, Any] = await request.json()
    except ValueError as exc:
        logger.error("eleme_webhook_bad_json", error=str(exc))
        raise HTTPException(status_code=400, detail="请求体 JSON 解析失败") from exc

    event_type = body.get("type", "unknown")
    order_data = body.get("data", {})
    order_id = str(order_data.get("order_id", ""))

    logger.info(
        "eleme_webhook_received",
        event_type=event_type,
        order_id=order_id,
    )

    # 提取 tenant_id
    tenant_id = _get_tenant_id(request)
    store_id = str(order_data.get("shop_id", ""))
    brand_id = request.headers.get("X-Brand-ID", "default")

    # 金额统一为分（int）
    total_fen = int(order_data.get("total_price", order_data.get("order_amount", 0)))

    # 解析菜品
    items: list[dict[str, Any]] = []
    for item in order_data.get("food_list", order_data.get("items", [])):
        items.append({
            "name": item.get("food_name", item.get("name", "")),
            "quantity": int(item.get("quantity", item.get("count", 1))),
            "price_fen": int(item.get("price", 0)),
            "sku_id": item.get("food_id", item.get("sku_id", "")),
            "notes": item.get("remark", ""),
        })

    adapter = DeliveryPlatformAdapter(
        store_id=store_id,
        brand_id=brand_id,
        tenant_id=tenant_id,
    )

    try:
        result = await adapter.receive_order(
            platform="eleme",
            platform_order_id=order_id,
            items=items,
            total_fen=total_fen,
            customer_phone=str(order_data.get("phone", "")),
            delivery_address=str(order_data.get("address", "")),
            expected_time=str(order_data.get("delivery_time", "")),
            notes=str(order_data.get("remark", order_data.get("caution", ""))),
        )
    except ValueError as exc:
        logger.warning("eleme_webhook_order_error", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(
        "eleme_webhook_order_saved",
        order_id=result["order_id"],
        platform_order_id=order_id,
    )

    return WebhookResp(ok=True, data=result)


# ══════════════════════════════════════════════════════════
#  抖音订单推送
# ══════════════════════════════════════════════════════════


def _verify_douyin_signature(payload: str, signature: str, timestamp: str) -> bool:
    """抖音签名验证: HMAC-SHA256(key=app_secret, msg=timestamp + '\\n' + payload)"""
    if not DOUYIN_APP_SECRET:
        logger.error("douyin_webhook_no_secret_configured")
        return False

    try:
        ts = int(timestamp)
        if abs(int(time.time()) - ts) > _TIMESTAMP_TOLERANCE:
            logger.warning("douyin_webhook_timestamp_expired", diff=abs(int(time.time()) - ts))
            return False
    except (ValueError, TypeError):
        logger.warning("douyin_webhook_bad_timestamp", timestamp=timestamp)
        return False

    sign_str = f"{timestamp}\n{payload}"
    expected = hmac_mod.new(
        DOUYIN_APP_SECRET.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac_mod.compare_digest(expected, signature)


@router.post("/douyin/order", response_model=WebhookResp)
async def douyin_order_push(request: Request) -> WebhookResp:
    """接收抖音订单/团购推送

    Headers:
      - X-Douyin-Signature: HMAC-SHA256 签名
      - X-Douyin-Timestamp: 时间戳（秒）
    """
    signature = request.headers.get("X-Douyin-Signature", "")
    timestamp = request.headers.get("X-Douyin-Timestamp", "")
    raw_body = (await request.body()).decode("utf-8")

    if not _verify_douyin_signature(raw_body, signature, timestamp):
        logger.warning("douyin_webhook_signature_invalid")
        raise HTTPException(status_code=403, detail="签名验证失败")

    try:
        body: dict[str, Any] = await request.json()
    except ValueError as exc:
        logger.error("douyin_webhook_bad_json", error=str(exc))
        raise HTTPException(status_code=400, detail="请求体 JSON 解析失败") from exc

    event_type = body.get("event", body.get("type", "unknown"))
    order_data = body.get("data", {})
    order_id = str(order_data.get("order_id", ""))

    logger.info(
        "douyin_webhook_received",
        event_type=event_type,
        order_id=order_id,
    )

    tenant_id = _get_tenant_id(request)
    store_id = str(order_data.get("shop_id", ""))
    brand_id = request.headers.get("X-Brand-ID", "default")

    total_fen = int(order_data.get("pay_amount", order_data.get("total_amount", 0)))

    items: list[dict[str, Any]] = []
    for item in order_data.get("item_list", order_data.get("items", [])):
        items.append({
            "name": item.get("product_name", item.get("name", "")),
            "quantity": int(item.get("count", item.get("quantity", 1))),
            "price_fen": int(item.get("origin_amount", item.get("price", 0))),
            "sku_id": item.get("product_id", item.get("sku_id", "")),
            "notes": item.get("remark", ""),
        })

    adapter = DeliveryPlatformAdapter(
        store_id=store_id,
        brand_id=brand_id,
        tenant_id=tenant_id,
    )

    try:
        result = await adapter.receive_order(
            platform="douyin",
            platform_order_id=order_id,
            items=items,
            total_fen=total_fen,
            customer_phone=str(order_data.get("phone", "")),
            delivery_address=str(order_data.get("address", "")),
            expected_time=str(order_data.get("delivery_time", "")),
            notes=str(order_data.get("remark", "")),
        )
    except ValueError as exc:
        logger.warning("douyin_webhook_order_error", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(
        "douyin_webhook_order_saved",
        order_id=result["order_id"],
        platform_order_id=order_id,
    )

    return WebhookResp(ok=True, data=result)
