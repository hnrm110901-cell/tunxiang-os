"""会员洞察 API — AI 画像推送（开台时服务员实时洞察）

路由：
  POST /api/v1/members/{member_id}/insights/generate  生成洞察
  GET  /api/v1/members/{member_id}/insights/latest    获取最近一次洞察缓存

当前实现：使用 Mock 数据基于会员字段拼装洞察，已标注 TODO 接入 Claude API。
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/members", tags=["member-insight"])

# ─── 内存缓存（生产应换为 Redis，key = member_id） ──────────
_insight_cache: dict[str, dict] = {}


# ─── Pydantic 模型 ──────────────────────────────────────────

class InsightGenerateRequest(BaseModel):
    order_id: str
    store_id: str


class AlertItem(BaseModel):
    type: str                # "allergy" | "preference" | "vip"
    severity: str            # "danger" | "warning" | "info"
    icon: str
    title: str
    body: str


class SuggestionItem(BaseModel):
    type: str                # "upsell" | "celebration" | "retention"
    icon: str
    title: str
    body: str


class MemberProfile(BaseModel):
    visit_count: int
    last_visit: str
    avg_spend_fen: int
    favorite_dishes: list[str]
    avoided_items: list[str]
    preferences: list[str]


class InsightResponse(BaseModel):
    member_id: str
    generated_at: str
    profile: MemberProfile
    alerts: list[AlertItem]
    suggestions: list[SuggestionItem]
    service_tips: str


# ─── 内部逻辑：Mock 数据生成器 ─────────────────────────────

def _build_mock_insight(member_id: str, order_id: str, store_id: str) -> dict:
    """
    基于会员 ID 构造确定性 Mock 洞察数据。
    字段基于 MemberInfo 可获得的现有字段（visit_count / preferences / last_visit）。

    TODO: 接入 Claude API（claude-3-5-sonnet / claude-opus-4）进行真实 AI 推理
    ─────────────────────────────────────────────────────────────────────────────
    接入步骤（审计修复期结束后，按 tx-brain 服务的 ModelRouter 封装调用）：

    1. 从 DB 拉取会员完整历史（orders / complaints / preferences / allergies）
    2. 构造 system prompt：
           "你是屯象OS的会员洞察引擎。分析以下会员历史数据，生成服务员开台前的服务洞察..."
    3. 调用 ModelRouter.chat(model="claude-opus-4", messages=[...], response_format=InsightResponse)
    4. 将结果写入 Redis 缓存（TTL = 12h）
    5. 决策留痕：写入 AgentDecisionLog（agent_id="member-insight", decision_type="insight_generate"）
    ─────────────────────────────────────────────────────────────────────────────
    """
    # 使用 member_id 哈希值制造稳定的 Mock 差异（避免所有会员返回完全相同内容）
    seed = sum(ord(c) for c in member_id)
    is_vip = seed % 3 == 0
    has_allergy = seed % 2 == 0
    has_birthday = seed % 5 == 0
    has_upsell = seed % 3 != 2
    visit_count = 20 + (seed % 40)
    avg_spend_fen = 28000 + (seed % 3) * 10000

    alerts: list[dict] = []
    if has_allergy:
        alerts.append({
            "type": "allergy",
            "severity": "danger",
            "icon": "⚠️",
            "title": "花生过敏",
            "body": "该会员对花生严重过敏，请通知后厨所有菜品避免花生成分",
        })
    if visit_count > 30:
        alerts.append({
            "type": "preference",
            "severity": "info",
            "icon": "💡",
            "title": "上次反馈鱼偏咸",
            "body": "2026-03-20 用餐后备注：鱼类菜品偏咸，建议今日特别嘱咐减盐",
        })

    suggestions: list[dict] = []
    if has_birthday:
        suggestions.append({
            "type": "celebration",
            "icon": "🎂",
            "title": "本月生日",
            "body": "会员本月生日，可赠送甜品并拍照留存，有助于提升复访率",
        })
    if has_upsell:
        suggestions.append({
            "type": "upsell",
            "icon": "🍷",
            "title": "历史偏好高端酒水",
            "body": f"该会员历史 {2 + seed % 4} 次点了茅台，今日可主动推荐酒水",
        })
    if is_vip:
        suggestions.append({
            "type": "retention",
            "icon": "👑",
            "title": "贵宾留存激活",
            "body": "该会员积分即将到期，今日消费可顺带告知积分兑换权益",
        })

    level_label = "贵宾级" if visit_count > 40 else "常客"
    service_tips = (
        f"{level_label}会员，{visit_count} 次到店。"
        + ("上次带商务客户，建议今日主动询问商务需求并推荐包厢。" if is_vip else "")
        + ("注意过敏信息，务必同步后厨。" if has_allergy else "")
    )

    return {
        "member_id": member_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "visit_count": visit_count,
            "last_visit": "2026-03-25",
            "avg_spend_fen": avg_spend_fen,
            "favorite_dishes": ["红烧肉", "清蒸鲈鱼"] if seed % 2 == 0 else ["剁椒鱼头", "老鸭汤"],
            "avoided_items": ["香菜", "花椒"] if has_allergy else [],
            "preferences": ["微辣", "少盐"] if seed % 3 != 0 else ["不辣", "原味"],
        },
        "alerts": alerts,
        "suggestions": suggestions,
        "service_tips": service_tips,
        "_meta": {
            "order_id": order_id,
            "store_id": store_id,
            "source": "mock",  # TODO: 接入 Claude API 后改为 "claude-api"
        },
    }


# ─── 路由 ────────────────────────────────────────────────────

@router.post("/{member_id}/insights/generate", response_model=InsightResponse)
async def generate_member_insight(
    member_id: str,
    req: InsightGenerateRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """
    生成会员 AI 洞察（开台时调用）。

    - 当前：Mock 数据（基于会员字段确定性拼装）
    - TODO: 从 DB 拉取真实会员历史 → 调用 Claude API → 写缓存
    - 决策留痕 TODO: 写入 AgentDecisionLog（需要 DB session）
    """
    logger.info(
        "member_insight_generate_requested",
        member_id=member_id,
        order_id=req.order_id,
        store_id=req.store_id,
        tenant_id=x_tenant_id,
    )

    try:
        insight = _build_mock_insight(member_id, req.order_id, req.store_id)
        # 写入内存缓存（生产环境 TODO: 改为 Redis，TTL=12h）
        _insight_cache[member_id] = insight
        logger.info("member_insight_generated", member_id=member_id, source="mock")
        return insight
    except (ValueError, KeyError) as exc:
        logger.error("member_insight_generate_failed", member_id=member_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="洞察生成失败，请重试") from exc


@router.get("/{member_id}/insights/latest", response_model=InsightResponse)
async def get_latest_insight(
    member_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """
    获取最近一次生成的洞察缓存（避免重复调用 AI）。

    - 如果缓存不存在，返回 404，前端应退回调用 generate 接口
    - TODO: 改为 Redis GET，支持 TTL 过期自动失效
    """
    cached = _insight_cache.get(member_id)
    if not cached:
        logger.info("member_insight_cache_miss", member_id=member_id)
        raise HTTPException(status_code=404, detail="暂无洞察缓存，请先调用 generate 接口")

    logger.info("member_insight_cache_hit", member_id=member_id)
    return cached
