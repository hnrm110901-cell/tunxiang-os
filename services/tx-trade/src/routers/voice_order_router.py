"""语音点单路由 — 服务员端 PWA 语音识别 + NLU 点单解析

POST /api/v1/voice/transcribe
    接收 base64 音频，转发至 mac-station :8000/voice/transcribe
    或 Core ML Bridge :8100/transcribe，返回识别文本。

POST /api/v1/voice/parse-order
    调用 Claude API (claude-haiku-4-5-20251001) 从语音文字中提取
    结构化点单数据；失败时返回空 items 列表（不抛错）。
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice-order"])

# ─── 配置常量（通过环境变量注入，禁止硬编码密钥）───────────────────────────────

_MAC_STATION_BASE = os.environ.get("MAC_STATION_URL", "http://localhost:8000")
_COREML_BRIDGE_BASE = os.environ.get("COREML_BRIDGE_URL", "http://localhost:8100")
_CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_HTTP_TIMEOUT = 15.0


# ─── 请求/响应 Schema ─────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    audio_base64: str = Field(..., description="Base64 编码的音频数据")
    format: str = Field(default="webm", description="音频格式，如 webm / wav / mp3")


class TranscribeResponse(BaseModel):
    text: str


class ParsedOrderItem(BaseModel):
    dishName: str
    quantity: int = Field(ge=1)
    note: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ParseOrderRequest(BaseModel):
    text: str = Field(..., description="语音识别原始文字")
    table_no: str = Field(..., description="桌台号")
    menu_context: list[str] | None = Field(default=None, description="当前菜单名称列表，可选")


class ParseOrderResponse(BaseModel):
    items: list[ParsedOrderItem]
    raw_text: str


# ─── 内部工具 ─────────────────────────────────────────────────────────────────

def _fallback_parse(text: str) -> list[ParsedOrderItem]:
    """简单正则 fallback，NLU 不可用时使用。"""
    cn_num = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

    def to_int(s: str) -> int:
        try:
            return int(s)
        except ValueError:
            return cn_num.get(s, 1)

    results: list[ParsedOrderItem] = []
    seen: set[str] = set()

    # 来/要/加 [数字] [菜品名]
    for m in re.finditer(r"[来要加]([一二两三四五六七八九十\d]+)\s*([^\s，。,！!？?]{2,8})", text):
        name = m.group(2).strip()
        if name not in seen:
            results.append(ParsedOrderItem(dishName=name, quantity=to_int(m.group(1)), confidence=0.7))
            seen.add(name)

    # [数字][个/份/杯/碗/盘/串/斤/两] [菜品名]
    for m in re.finditer(r"([一二两三四五六七八九十\d]+)\s*[个份杯碗盘串斤两]\s*([^\s，。,！!？?]{2,8})", text):
        name = m.group(2).strip()
        if name not in seen:
            results.append(ParsedOrderItem(dishName=name, quantity=to_int(m.group(1)), confidence=0.6))
            seen.add(name)

    return results


async def _call_claude_parse(text: str, menu_context: list[str] | None) -> list[ParsedOrderItem]:
    """调用 Claude API 解析自然语言点单，失败返回空列表。"""
    if not _CLAUDE_API_KEY:
        logger.warning("voice_order: ANTHROPIC_API_KEY 未配置，跳过 Claude NLU")
        return []

    menu_hint = ""
    if menu_context:
        menu_hint = f"\n当前菜单包含以下菜品（仅供参考）：{', '.join(menu_context[:50])}"

    system_prompt = (
        "你是餐厅点单助手，从语音识别文字中提取点单信息，返回JSON格式。\n"
        "JSON结构：{\"items\": [{\"dishName\": \"菜品名\", \"quantity\": 数量, "
        "\"note\": \"备注或null\", \"confidence\": 0到1的置信度}]}\n"
        "规则：\n"
        "1. dishName 只保留菜品名称，去掉数量词\n"
        "2. quantity 默认为1\n"
        "3. note 提取如\"少辣\"\"不要香菜\"等特殊要求\n"
        "4. confidence 根据识别清晰度判断\n"
        "5. 仅输出 JSON，不要其他内容"
        + menu_hint
    )

    payload = {
        "model": _CLAUDE_MODEL,
        "max_tokens": 512,
        "system": system_prompt,
        "messages": [{"role": "user", "content": text}],
    }

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()

    raw_content = body.get("content", [{}])[0].get("text", "")

    # 尝试从返回文本中提取 JSON
    json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
    if not json_match:
        return []
    data = json.loads(json_match.group())

    items: list[ParsedOrderItem] = []
    for it in data.get("items", []):
        try:
            items.append(
                ParsedOrderItem(
                    dishName=str(it.get("dishName", "")),
                    quantity=max(1, int(it.get("quantity", 1))),
                    note=it.get("note") or None,
                    confidence=min(1.0, max(0.0, float(it.get("confidence", 0.8)))),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("voice_order: 跳过无效 item %s — %s", it, exc)

    return items


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@router.post("/transcribe", response_model=dict)
async def transcribe_audio(body: TranscribeRequest, request: Request) -> dict:
    """
    将 base64 音频转发到 mac-station 或 Core ML Bridge 进行语音识别。
    优先尝试 mac-station；失败时自动降级到 coreml-bridge。
    """
    tenant_id = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
    )

    payload = {"audio_base64": body.audio_base64, "format": body.format}
    if tenant_id:
        payload["tenant_id"] = tenant_id

    errors: list[str] = []

    # 尝试 mac-station
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(f"{_MAC_STATION_BASE}/voice/transcribe", json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("text") or data.get("data", {}).get("text", "")
            return {"ok": True, "data": {"text": text}}
    except httpx.HTTPError as exc:
        errors.append(f"mac-station: {exc}")
        logger.warning("voice_order transcribe: mac-station 不可用 — %s", exc)

    # 降级：Core ML Bridge
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(f"{_COREML_BRIDGE_BASE}/transcribe", json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("text") or data.get("data", {}).get("text", "")
            return {"ok": True, "data": {"text": text}}
    except httpx.HTTPError as exc:
        errors.append(f"coreml-bridge: {exc}")
        logger.error("voice_order transcribe: 两端均不可用 — %s", errors)

    raise HTTPException(
        status_code=503,
        detail={"message": "语音识别服务暂时不可用", "errors": errors},
    )


@router.post("/parse-order", response_model=dict)
async def parse_order(body: ParseOrderRequest) -> dict:
    """
    使用 Claude API 将语音识别文字解析为结构化点单数据。
    Claude 失败时使用正则 fallback，不向前端抛错。
    """
    items: list[ParsedOrderItem] = []

    try:
        items = await _call_claude_parse(body.text, body.menu_context)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("voice_order parse-order: Claude 调用失败 — %s，使用 fallback", exc)
    except Exception:  # noqa: BLE001 — 最外层兜底，必须记录
        logger.error("voice_order parse-order: 未预期错误", exc_info=True)

    if not items:
        items = _fallback_parse(body.text)

    return {
        "ok": True,
        "data": {
            "items": [it.model_dump() for it in items],
            "raw_text": body.text,
        },
    }
