"""智能内容工厂 — AI驱动的多渠道营销内容自动生成

基于Claude API（通过tx-brain）为不同渠道自动生成营销文案：
  - 朋友圈、企微会话、短信、海报、短视频脚本、菜品故事
  - 支持按菜品、节日、周计划批量生成
  - 渠道特征适配（长度/语气/格式）

S3W11-12 Smart Content Factory
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

TX_BRAIN_URL: str = os.getenv("TX_BRAIN_SERVICE_URL", "http://tx-brain:8010")

# ---------------------------------------------------------------------------
# 渠道要求定义
# ---------------------------------------------------------------------------

CHANNEL_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "moments": {
        "label": "朋友圈",
        "max_chars": 120,
        "tone": "简短有趣，带emoji",
        "description": "简短有趣，带emoji，120字以内",
    },
    "wecom_chat": {
        "label": "企微会话",
        "max_chars": 80,
        "tone": "亲切对话式，像朋友推荐",
        "description": "亲切对话式，像朋友推荐，80字以内",
    },
    "sms": {
        "label": "短信",
        "max_chars": 70,
        "tone": "精简直达，含优惠信息",
        "description": "精简直达，含优惠信息，70字以内",
    },
    "poster": {
        "label": "海报",
        "max_chars": 200,
        "tone": "醒目有冲击力",
        "description": "标题+副标题+行动号召",
    },
    "short_video_script": {
        "label": "短视频脚本",
        "max_chars": 300,
        "tone": "生动口语化",
        "description": "开场hook+内容+结尾号召，300字以内",
    },
    "dish_story": {
        "label": "菜品故事",
        "max_chars": 150,
        "tone": "温暖有文化底蕴",
        "description": "讲述菜品故事，150字",
    },
    "seasonal_campaign": {
        "label": "时令活动",
        "max_chars": 200,
        "tone": "应季氛围感",
        "description": "结合时令特色，营造氛围感，200字以内",
    },
    "live_preview": {
        "label": "直播预告",
        "max_chars": 150,
        "tone": "期待感与紧迫感",
        "description": "直播预告，突出亮点和时间，150字以内",
    },
}

# ---------------------------------------------------------------------------
# Claude 提示词模板
# ---------------------------------------------------------------------------

CONTENT_PROMPT_TEMPLATE = """你是{brand_name}的社交媒体运营专家。请为以下场景生成营销文案：
渠道：{channel}
场景：{context_description}
品牌调性：{tone}
要求：{channel_requirements}
- moments: 简短有趣，带emoji，120字以内
- wecom_chat: 亲切对话式，像朋友推荐，80字以内
- sms: 精简直达，含优惠信息，70字以内
- poster: 标题+副标题+行动号召
- dish_story: 讲述菜品故事，150字

请直接输出文案内容，不要加任何解释说明。"""


# ---------------------------------------------------------------------------
# ContentFactory
# ---------------------------------------------------------------------------


class ContentFactory:
    """智能内容工厂 — AI驱动的多渠道营销内容自动生成"""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    async def _get_brand_info(self, tenant_id: str, db: AsyncSession) -> dict:
        """获取品牌信息（名称、调性）"""
        await self._set_tenant(db, tenant_id)
        row = await db.execute(
            text("""
                SELECT brand_name, brand_voice, tone_keywords
                FROM brand_strategies
                WHERE tenant_id = :tid AND is_deleted = false
                ORDER BY updated_at DESC LIMIT 1
            """),
            {"tid": tenant_id},
        )
        r = row.mappings().first()
        if r:
            return {
                "brand_name": r["brand_name"] or "我们的品牌",
                "brand_voice": r["brand_voice"] or "专业温暖",
                "tone_keywords": r["tone_keywords"] if r["tone_keywords"] else "美味,品质,用心",
            }
        return {
            "brand_name": "我们的品牌",
            "brand_voice": "专业温暖",
            "tone_keywords": "美味,品质,用心",
        }

    async def _call_claude(
        self,
        prompt: str,
        model: str = "claude-haiku",
    ) -> dict:
        """通过 tx-brain 调用 Claude API 生成内容"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{TX_BRAIN_URL}/api/v1/brain/generate",
                    json={
                        "prompt": prompt,
                        "model": model,
                        "max_tokens": 500,
                        "temperature": 0.8,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "content": data.get("data", {}).get("text", ""),
                    "model": model,
                    "success": True,
                }
        except httpx.TimeoutException:
            logger.warning("claude_call_timeout", model=model)
            return {"content": "", "model": model, "success": False, "error": "timeout"}
        except httpx.HTTPStatusError as exc:
            logger.warning("claude_call_http_error", status=exc.response.status_code)
            return {"content": "", "model": model, "success": False, "error": f"http_{exc.response.status_code}"}

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    async def auto_generate(
        self,
        tenant_id: str,
        db: AsyncSession,
        context: dict,
    ) -> dict:
        """AI自动生成内容

        Args:
            context: {
                dish_ids: list[str],  # 可选
                event_name: str,       # 可选
                holiday: str,          # 可选
                season: str,           # 可选
                brand_voice: str,      # 可选（覆盖品牌默认调性）
                target_channel: str,   # 必填
                custom_prompt: str,    # 可选
            }
        Returns:
            {content: str, model: str, suggested_media: list, ai_prompt_context: dict}
        """
        brand = await self._get_brand_info(tenant_id, db)
        channel = context.get("target_channel", "moments")
        ch_req = CHANNEL_REQUIREMENTS.get(channel, CHANNEL_REQUIREMENTS["moments"])

        # 构建场景描述
        parts: list[str] = []
        if context.get("dish_ids"):
            parts.append(f"推荐菜品（ID: {', '.join(context['dish_ids'][:5])}）")
        if context.get("event_name"):
            parts.append(f"活动：{context['event_name']}")
        if context.get("holiday"):
            parts.append(f"节日：{context['holiday']}")
        if context.get("season"):
            parts.append(f"季节：{context['season']}")
        context_description = "；".join(parts) if parts else "日常品牌推广"

        tone = context.get("brand_voice") or brand["brand_voice"]

        prompt = CONTENT_PROMPT_TEMPLATE.format(
            brand_name=brand["brand_name"],
            channel=ch_req["label"],
            context_description=context_description,
            tone=tone,
            channel_requirements=ch_req["description"],
        )

        if context.get("custom_prompt"):
            prompt += f"\n\n额外要求：{context['custom_prompt']}"

        result = await self._call_claude(prompt, model="claude-haiku")

        ai_prompt_context = {
            "dish_ids": context.get("dish_ids", []),
            "event_name": context.get("event_name"),
            "holiday": context.get("holiday"),
            "season": context.get("season"),
            "brand_voice": tone,
            "target_channel": channel,
        }

        return {
            "content": result["content"],
            "model": result["model"],
            "success": result["success"],
            "suggested_media": [],
            "ai_prompt_context": ai_prompt_context,
        }

    async def generate_for_dish(
        self,
        tenant_id: str,
        dish_id: str,
        db: AsyncSession,
        channels: Optional[list[str]] = None,
    ) -> list[dict]:
        """为单个菜品生成多渠道内容"""
        if channels is None:
            channels = ["moments", "wecom_chat"]

        await self._set_tenant(db, tenant_id)

        # 读取菜品数据
        row = await db.execute(
            text("""
                SELECT name, description, price_fen, category
                FROM dishes
                WHERE id = :did AND tenant_id = :tid AND is_deleted = false
            """),
            {"did": dish_id, "tid": tenant_id},
        )
        dish = row.mappings().first()
        if not dish:
            logger.warning("dish_not_found", dish_id=dish_id, tenant_id=tenant_id)
            return []

        brand = await self._get_brand_info(tenant_id, db)
        results: list[dict] = []

        for channel in channels:
            ch_req = CHANNEL_REQUIREMENTS.get(channel, CHANNEL_REQUIREMENTS["moments"])
            prompt = CONTENT_PROMPT_TEMPLATE.format(
                brand_name=brand["brand_name"],
                channel=ch_req["label"],
                context_description=f"推荐菜品：{dish['name']}，{dish['description'] or ''}，价格：{(dish['price_fen'] or 0) / 100:.0f}元",
                tone=brand["brand_voice"],
                channel_requirements=ch_req["description"],
            )

            gen = await self._call_claude(prompt)
            results.append(
                {
                    "channel": channel,
                    "content": gen["content"],
                    "model": gen["model"],
                    "success": gen["success"],
                    "dish_id": dish_id,
                    "dish_name": dish["name"],
                }
            )

        return results

    async def generate_for_holiday(
        self,
        tenant_id: str,
        holiday_name: str,
        db: AsyncSession,
    ) -> list[dict]:
        """为节日生成全渠道内容"""
        brand = await self._get_brand_info(tenant_id, db)
        results: list[dict] = []

        for channel in ["moments", "wecom_chat", "sms", "poster"]:
            ch_req = CHANNEL_REQUIREMENTS[channel]
            prompt = CONTENT_PROMPT_TEMPLATE.format(
                brand_name=brand["brand_name"],
                channel=ch_req["label"],
                context_description=f"节日：{holiday_name}，营造节日氛围，结合品牌特色推出节日限定活动",
                tone=brand["brand_voice"],
                channel_requirements=ch_req["description"],
            )

            gen = await self._call_claude(prompt)
            results.append(
                {
                    "channel": channel,
                    "content": gen["content"],
                    "model": gen["model"],
                    "success": gen["success"],
                    "holiday": holiday_name,
                }
            )

        return results

    async def generate_weekly_plan(
        self,
        tenant_id: str,
        db: AsyncSession,
        store_id: Optional[str] = None,
    ) -> list[dict]:
        """自动生成一周内容计划（Mon-Sun，混合类型）"""
        brand = await self._get_brand_info(tenant_id, db)

        # 一周内容类型安排
        weekly_plan = [
            {"day": "周一", "content_type": "moments", "theme": "新的一周开始，元气满满的美食推荐"},
            {"day": "周二", "content_type": "wecom_chat", "theme": "老客关怀，推荐本周新菜"},
            {"day": "周三", "content_type": "dish_story", "theme": "讲述一道招牌菜背后的故事"},
            {"day": "周四", "content_type": "short_video_script", "theme": "后厨探秘，展示烹饪过程"},
            {"day": "周五", "content_type": "moments", "theme": "周末聚餐推荐，呼朋唤友"},
            {"day": "周六", "content_type": "poster", "theme": "周末特惠活动海报"},
            {"day": "周日", "content_type": "seasonal_campaign", "theme": "下周预告与会员专属福利"},
        ]

        results: list[dict] = []
        now = datetime.now(timezone.utc)
        # 计算下一个周一
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = now + timedelta(days=days_until_monday)

        for i, plan in enumerate(weekly_plan):
            ch_req = CHANNEL_REQUIREMENTS.get(plan["content_type"], CHANNEL_REQUIREMENTS["moments"])
            prompt = CONTENT_PROMPT_TEMPLATE.format(
                brand_name=brand["brand_name"],
                channel=ch_req["label"],
                context_description=f"{plan['day']}主题：{plan['theme']}",
                tone=brand["brand_voice"],
                channel_requirements=ch_req["description"],
            )

            gen = await self._call_claude(prompt)
            scheduled = next_monday + timedelta(days=i, hours=10)

            results.append(
                {
                    "day": plan["day"],
                    "content_type": plan["content_type"],
                    "theme": plan["theme"],
                    "content": gen["content"],
                    "model": gen["model"],
                    "success": gen["success"],
                    "scheduled_at": scheduled.isoformat(),
                    "store_id": store_id,
                }
            )

        return results

    # ------------------------------------------------------------------
    # 排期 & 审批
    # ------------------------------------------------------------------

    async def schedule_content(
        self,
        tenant_id: str,
        content_id: str,
        scheduled_at: str,
        db: AsyncSession,
    ) -> dict:
        """设置内容排期"""
        await self._set_tenant(db, tenant_id)
        result = await db.execute(
            text("""
                UPDATE content_calendar
                SET status = 'scheduled',
                    scheduled_at = :scheduled_at,
                    updated_at = NOW()
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
                RETURNING id, status, scheduled_at
            """),
            {"cid": content_id, "tid": tenant_id, "scheduled_at": scheduled_at},
        )
        row = result.mappings().first()
        if not row:
            return {"error": "content_not_found"}
        return {
            "id": str(row["id"]),
            "status": row["status"],
            "scheduled_at": row["scheduled_at"].isoformat() if row["scheduled_at"] else None,
        }

    async def approve_content(
        self,
        tenant_id: str,
        content_id: str,
        approved_by: str,
        db: AsyncSession,
    ) -> dict:
        """审批内容"""
        await self._set_tenant(db, tenant_id)
        result = await db.execute(
            text("""
                UPDATE content_calendar
                SET approved_by = :approved_by,
                    approved_at = NOW(),
                    updated_at = NOW()
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
                RETURNING id, approved_by, approved_at
            """),
            {"cid": content_id, "tid": tenant_id, "approved_by": approved_by},
        )
        row = result.mappings().first()
        if not row:
            return {"error": "content_not_found"}
        return {
            "id": str(row["id"]),
            "approved_by": str(row["approved_by"]),
            "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        }
