"""语音点菜 API — 5 个端点

端点:
  POST /api/v1/voice/transcribe     — 语音转文字
  POST /api/v1/voice/parse-intent   — 解析点菜意图
  POST /api/v1/voice/match-dishes   — 菜品模糊匹配
  POST /api/v1/voice/confirm-order  — 确认下单
  GET  /api/v1/voice/stats/{store_id} — 语音点餐统计
"""

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/voice", tags=["voice-order"])


# ── Request Models ──────────────────────────────────────
class TranscribeRequest(BaseModel):
    audio_base64: str = Field(..., description="Base64 编码的音频数据")
    format: str = Field("wav", description="音频格式: wav/mp3/pcm")


class ParseIntentRequest(BaseModel):
    text: str = Field(..., description="语音识别后的文本")
    store_id: str = Field("", description="门店ID")


class MatchDishesRequest(BaseModel):
    dish: str = Field(..., description="菜品查询文本")
    store_id: str = Field("", description="门店ID")
    top_n: int = Field(3, description="返回Top N结果")
    menu_items: list[dict] = Field(default_factory=list, description="可选: 直接传入菜单")


class ConfirmOrderRequest(BaseModel):
    matched_items: list[dict] = Field(..., description="匹配后的菜品列表")
    table_id: str = Field(..., description="桌台ID")


# ── Endpoints ───────────────────────────────────────────
@router.post("/transcribe")
async def voice_transcribe(
    req: TranscribeRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
):
    """语音转文字"""
    import base64

    from ..agents.skills.voice_order import VoiceOrderAgent

    try:
        audio_data = base64.b64decode(req.audio_base64)
    except ValueError:
        return {"ok": False, "error": {"message": "无效的 Base64 音频数据"}}

    agent = VoiceOrderAgent(tenant_id=x_tenant_id)
    result = await agent.run("transcribe", {"audio_data": audio_data})
    return {
        "ok": result.success,
        "data": result.data,
        "error": {"message": result.error} if result.error else None,
    }


@router.post("/parse-intent")
async def voice_parse_intent(
    req: ParseIntentRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
):
    """解析点菜意图"""
    from ..agents.skills.voice_order import VoiceOrderAgent

    agent = VoiceOrderAgent(tenant_id=x_tenant_id, store_id=req.store_id)
    result = await agent.run("parse_order_intent", {"text": req.text})
    return {
        "ok": result.success,
        "data": result.data,
        "error": {"message": result.error} if result.error else None,
    }


@router.post("/match-dishes")
async def voice_match_dishes(
    req: MatchDishesRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
):
    """菜品模糊匹配"""
    from ..agents.skills.voice_order import VoiceOrderAgent

    agent = VoiceOrderAgent(tenant_id=x_tenant_id, store_id=req.store_id)
    result = await agent.run("match_dishes", {
        "dish": req.dish,
        "menu_items": req.menu_items,
        "top_n": req.top_n,
    })
    return {
        "ok": result.success,
        "data": result.data,
        "error": {"message": result.error} if result.error else None,
    }


@router.post("/confirm-order")
async def voice_confirm_order(
    req: ConfirmOrderRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
):
    """确认语音点餐下单"""
    from ..agents.skills.voice_order import VoiceOrderAgent

    agent = VoiceOrderAgent(tenant_id=x_tenant_id)
    result = await agent.run("confirm_and_order", {
        "matched_items": req.matched_items,
        "table_id": req.table_id,
    })
    return {
        "ok": result.success,
        "data": result.data,
        "error": {"message": result.error} if result.error else None,
    }


@router.get("/stats/{store_id}")
async def voice_order_stats(
    store_id: str,
    period: str = "today",
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
):
    """语音点餐统计"""
    from ..agents.skills.voice_order import VoiceOrderAgent

    agent = VoiceOrderAgent(tenant_id=x_tenant_id, store_id=store_id)
    result = await agent.run("get_stats", {
        "store_id": store_id,
        "period": period,
    })
    return {
        "ok": result.success,
        "data": result.data,
        "error": {"message": result.error} if result.error else None,
    }
