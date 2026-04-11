"""AI营销内容中枢 — Claude API 驱动的餐饮营销 AIGC 工厂

核心职责：
  1. 接收活动类型 + 门店上下文 + 会员画像 → 生成全渠道营销内容包
  2. 支持品牌调性配置（不同品牌有不同的语言风格）
  3. 内容缓存（避免重复调用 Claude API）
  4. 批量生成（A/B 测试变体）

支持的内容类型：
  - wechat_oa_template: 微信公众号模板消息文案
  - wechat_moments: 朋友圈文案 + hashtags
  - sms: 短信文案（≤70字）
  - wecom_chat: 企微一对一话术
  - miniapp_banner: 小程序横幅标题/副标题
  - douyin_caption: 抖音视频配文
  - xiaohongshu: 小红书笔记标题+正文
  - xiaohongshu_note: 小红书种草笔记（结构化：标题/正文/标签/表情/封面建议）
  - store_announcement: 门店公告/LED 屏文案

输出格式：CampaignContentPackage，包含所有渠道的内容变体
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─── Channel max character constraints ───────────────────────────────────────

CHANNEL_MAX_CHARS: dict[str, int] = {
    "sms":               70,
    "wechat_oa_template": 200,
    "wechat_moments":    500,
    "wecom_chat":        300,
    "miniapp_banner":    50,
    "douyin_caption":    150,
    "xiaohongshu":       1000,
    "xiaohongshu_note":  1500,
    "store_announcement": 100,
}

# ─── Valid campaign types ─────────────────────────────────────────────────────

VALID_CAMPAIGN_TYPES = {
    "new_dish_launch",
    "member_win_back",
    "holiday_promo",
    "daily_special",
    "review_response",
    "birthday_care",
    "churn_recovery",
}

# ─── Pydantic Models ──────────────────────────────────────────────────────────


class BrandVoiceConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    brand_name: str
    tone: str  # e.g. "亲切温暖", "高端优雅", "活泼年轻"
    taboo_words: list[str] = []
    signature: str = ""  # 落款/品牌标语
    emoji_style: str = "moderate"  # none/light/moderate/heavy


class CampaignContentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    campaign_type: str
    brand_voice: BrandVoiceConfig
    store_context: dict[str, Any]
    member_segment: dict[str, Any] | None = None
    offer_detail: dict[str, Any] | None = None
    target_channels: list[str]
    ab_variants: int = 1


class ChannelContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    channel: str
    subject: str = ""
    body: str
    cta: str = ""
    hashtags: list[str] = []
    char_count: int = 0
    variant_id: str = "A"


class CampaignContentPackage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request_id: str
    campaign_type: str
    generated_at: datetime
    contents: list[ChannelContent]
    reasoning: str
    tokens_used: int = 0
    cached: bool = False


# ─── ContentHub ───────────────────────────────────────────────────────────────


class ContentHub:
    """Claude API 驱动的营销内容工厂。

    所有模型调用必须通过 ModelRouter，不直接调用 Anthropic client。
    """

    MAX_CACHE_AGE_HOURS = 24

    def __init__(self, model_router: Any) -> None:
        self._model_router = model_router

    async def generate_campaign_content(
        self,
        request: CampaignContentRequest,
        tenant_id: str,
        db: AsyncSession,
    ) -> CampaignContentPackage:
        """生成全渠道营销内容包。

        优先返回缓存结果；缓存未命中时调用 Claude API，并将结果写入缓存。

        Args:
            request:   活动内容生成请求
            tenant_id: 租户 UUID
            db:        AsyncSession

        Returns:
            CampaignContentPackage 内容包

        Raises:
            ValueError: 非法的 campaign_type 或 target_channels 为空
        """
        if request.campaign_type not in VALID_CAMPAIGN_TYPES:
            raise ValueError(
                f"非法活动类型: {request.campaign_type!r}. "
                f"支持: {sorted(VALID_CAMPAIGN_TYPES)}"
            )
        if not request.target_channels:
            raise ValueError("target_channels 不能为空")

        cache_key = self._make_cache_key(request)

        # 尝试命中缓存
        cached_pkg = await self._get_cached_content(cache_key, tenant_id, db)
        if cached_pkg is not None:
            logger.info(
                "content_hub_cache_hit",
                cache_key=cache_key,
                tenant_id=tenant_id,
                campaign_type=request.campaign_type,
            )
            return cached_pkg

        # 调用 Claude API（通过 ModelRouter）
        prompt = self._build_generation_prompt(request)
        system_prompt = (
            "你是屯象OS的AI营销文案专家，专注中国连锁餐饮行业。"
            "你的输出必须是合法JSON，不带任何markdown代码块标记。"
            "字符数约束严格执行，尤其短信≤70字。"
        )

        logger.info(
            "content_hub_calling_model_router",
            tenant_id=tenant_id,
            campaign_type=request.campaign_type,
            channels=request.target_channels,
            ab_variants=request.ab_variants,
        )

        raw_text = await self._model_router.complete(
            tenant_id=tenant_id,
            task_type="standard_analysis",
            messages=[{"role": "user", "content": prompt}],
            system=system_prompt,
            max_tokens=2000,
            db=db,
        )

        # 粗略估算 token 数（ModelRouter 已在内部做精确追踪）
        tokens_used = max(len(prompt) // 3, 100)

        pkg = self._parse_claude_response(
            raw=raw_text,
            request=request,
            request_id=str(uuid.uuid4()),
            tokens_used=tokens_used,
        )

        await self._save_to_cache(cache_key, pkg, tenant_id, db)
        return pkg

    async def generate_review_response(
        self,
        review_text: str,
        rating: int,
        brand_voice: BrandVoiceConfig,
        tenant_id: str,
    ) -> str:
        """生成评论回复文案。

        Args:
            review_text: 顾客评论原文
            rating:      评分（1-5星）
            brand_voice: 品牌调性配置
            tenant_id:   租户 UUID

        Returns:
            回复文案字符串

        Raises:
            ValueError: rating 不在 1-5 范围内
        """
        if not (1 <= rating <= 5):
            raise ValueError(f"评分必须在 1-5 之间，收到: {rating}")

        tone_guidance = "表达诚恳歉意并承诺改进" if rating <= 3 else "感谢好评并邀请再次光临"

        taboo_str = ""
        if brand_voice.taboo_words:
            taboo_str = f"\n禁用词（绝对不能出现）：{', '.join(brand_voice.taboo_words)}"

        prompt = (
            f"你是{brand_voice.brand_name}的客服专员，风格：{brand_voice.tone}。\n"
            f"顾客评分：{rating}星\n"
            f"顾客评论：{review_text}\n"
            f"要求：{tone_guidance}，回复100字以内，语气自然真诚。"
            f"{taboo_str}"
            f"\n{'落款：' + brand_voice.signature if brand_voice.signature else ''}"
            f"\n直接输出回复正文，不要任何格式标记。"
        )

        logger.info(
            "content_hub_review_response",
            tenant_id=tenant_id,
            brand_name=brand_voice.brand_name,
            rating=rating,
        )

        response = await self._model_router.complete(
            tenant_id=tenant_id,
            task_type="standard_analysis",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        return response.strip()

    async def generate_dish_story(
        self,
        dish_name: str,
        dish_ingredients: list[str],
        brand_voice: BrandVoiceConfig,
        tenant_id: str,
    ) -> str:
        """生成菜品故事文案（用于菜单/小程序菜品详情页）。

        Args:
            dish_name:        菜品名称
            dish_ingredients: 主要食材列表
            brand_voice:      品牌调性配置
            tenant_id:        租户 UUID

        Returns:
            菜品故事文案字符串（≤150字）

        Raises:
            ValueError: dish_name 为空
        """
        if not dish_name.strip():
            raise ValueError("dish_name 不能为空")

        ingredients_str = "、".join(dish_ingredients) if dish_ingredients else "精选食材"
        taboo_str = ""
        if brand_voice.taboo_words:
            taboo_str = f"\n禁用词：{', '.join(brand_voice.taboo_words)}"

        prompt = (
            f"为餐厅菜品【{dish_name}】写一段故事文案。\n"
            f"品牌：{brand_voice.brand_name}，风格：{brand_voice.tone}\n"
            f"主要食材：{ingredients_str}\n"
            f"要求：100-150字，突出食材品质和口感特色，引发食欲。"
            f"{taboo_str}"
            f"\n直接输出文案正文，不要任何格式标记。"
        )

        logger.info(
            "content_hub_dish_story",
            tenant_id=tenant_id,
            dish_name=dish_name,
            brand_name=brand_voice.brand_name,
        )

        response = await self._model_router.complete(
            tenant_id=tenant_id,
            task_type="standard_analysis",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        return response.strip()

    async def generate_xiaohongshu_note(
        self,
        tenant_id: str,
        store_name: str,
        dish_name: str,
        brand_voice: dict,
        campaign_type: str = "store_visit",
        city: str = "长沙",
        target_audience: str = "年轻女性用户",
    ) -> dict:
        """生成小红书种草笔记

        生成结构化笔记内容：标题/正文/标签/表情建议/封面构图建议

        Args:
            tenant_id:       租户 UUID
            store_name:      餐厅名称
            dish_name:       主推菜品名称
            brand_voice:     品牌调性配置字典（至少含 tone 键）
            campaign_type:   活动类型（默认 store_visit）
            city:            门店所在城市（默认长沙）
            target_audience: 目标受众描述

        Returns:
            结构化笔记字典，包含 title/body/hashtags/emojis/cover_concept/cta

        Raises:
            ValueError: store_name 或 dish_name 为空
        """
        if not store_name.strip():
            raise ValueError("store_name 不能为空")
        if not dish_name.strip():
            raise ValueError("dish_name 不能为空")

        cache_key = hashlib.sha256(
            f"xiaohongshu_note:{store_name}:{dish_name}:{campaign_type}".encode()
        ).hexdigest()

        # 无 ModelRouter 时返回 mock 响应
        if self._model_router is None:
            logger.info(
                "content_hub_xhs_note_mock",
                tenant_id=tenant_id,
                store_name=store_name,
                dish_name=dish_name,
            )
            return {
                "title": f"探店{store_name} | {dish_name}真的绝了",
                "body": f"最近发现了{city}宝藏餐厅 {store_name}，{dish_name}让我念念不忘...",
                "hashtags": [f"#{store_name}", f"#{dish_name}", "#美食探店", f"#{city}美食", "#种草"],
                "emojis": ["😋", "🍜", "✨", "❤️"],
                "cover_concept": f"{dish_name}特写，暖光氛围，背景虚化",
                "cta": "你最想尝哪道菜？评论区见～",
                "cached": False,
                "mock": True,
            }

        prompt = f"""你是一位擅长小红书内容创作的营销文案专家。
为以下餐厅生成一篇小红书种草笔记：

品牌信息：
- 餐厅名：{store_name}
- 城市：{city}
- 品牌调性：{brand_voice.get('tone', '亲切温暖')}
- 主推内容：{dish_name}
- 活动类型：{campaign_type}
- 目标受众：{target_audience}

请以 JSON 格式输出，包含以下字段：
{{
  "title": "标题（≤20字，有吸引力）",
  "body": "正文（100-300字，小红书风格，第一人称，口语化，有具体细节和情绪）",
  "hashtags": ["#tag1", "#tag2", ...（5-8个）],
  "emojis": ["😋", "🍜", ...（3-5个，建议插入正文的表情）],
  "cover_concept": "封面图构图建议（一句话）",
  "cta": "引导语（如"评论区告诉我你最想尝哪道菜～"）"
}}

注意：标题和正文必须自然真实，避免广告感，像真实用户分享。"""

        logger.info(
            "content_hub_xhs_note_calling_model_router",
            tenant_id=tenant_id,
            store_name=store_name,
            dish_name=dish_name,
            campaign_type=campaign_type,
        )

        raw_text = await self._model_router.complete(
            tenant_id=tenant_id,
            task_type="standard_analysis",
            messages=[{"role": "user", "content": prompt}],
            system=(
                "你是屯象OS的AI营销文案专家，专注中国连锁餐饮行业。"
                "你的输出必须是合法JSON。"
            ),
            max_tokens=800,
        )

        # 去除可能的 markdown 代码块标记
        raw_stripped = raw_text.strip()
        if raw_stripped.startswith("```"):
            lines = raw_stripped.split("\n")
            raw_stripped = "\n".join(lines[1:-1]) if len(lines) > 2 else raw_stripped

        try:
            note_data: dict = json.loads(raw_stripped)
        except json.JSONDecodeError as exc:
            logger.warning(
                "content_hub_xhs_note_parse_failed",
                tenant_id=tenant_id,
                error=str(exc),
                raw_preview=raw_stripped[:200],
            )
            note_data = {
                "title": f"探店{store_name} | {dish_name}真的绝了",
                "body": raw_stripped[:300],
                "hashtags": [f"#{store_name}", f"#{dish_name}", "#美食探店", f"#{city}美食", "#种草"],
                "emojis": ["😋", "🍜", "✨", "❤️"],
                "cover_concept": f"{dish_name}特写，暖光氛围，背景虚化",
                "cta": "你最想尝哪道菜？评论区见～",
            }

        result: dict = {
            "title": note_data.get("title", ""),
            "body": note_data.get("body", ""),
            "hashtags": note_data.get("hashtags", []),
            "emojis": note_data.get("emojis", []),
            "cover_concept": note_data.get("cover_concept", ""),
            "cta": note_data.get("cta", ""),
            "cached": False,
            "mock": False,
        }

        # 写入缓存（best-effort，失败不阻断）
        await self._save_xhs_note_to_cache(cache_key, result, tenant_id, campaign_type, db=None)

        return result

    async def _save_xhs_note_to_cache(
        self,
        cache_key: str,
        note: dict,
        tenant_id: str,
        campaign_type: str,
        *,
        db: AsyncSession | None = None,
    ) -> None:
        """将小红书笔记结果写入 ai_content_cache 表（best-effort）。

        复用 ai_content_cache，campaign_type 存为 "xiaohongshu_note:{campaign_type}"。
        写入失败仅记录警告，不阻断主流程。
        """
        if self._model_router is None:
            return

        ctype = f"xiaohongshu_note:{campaign_type}"
        pkg_json = json.dumps(note, ensure_ascii=False, default=str)
        await self._upsert_content_cache(
            cache_key=cache_key,
            campaign_type=ctype,
            pkg_json=pkg_json,
            tokens_used=0,
            tenant_id=tenant_id,
            db=db,
            log_event="content_hub_xhs_note_cache",
        )

    async def _get_cached_content(
        self,
        cache_key: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> CampaignContentPackage | None:
        """从 ai_content_cache 表查找未过期的缓存。

        Returns:
            CampaignContentPackage 或 None（未命中/已过期）
        """
        try:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            row = await db.execute(
                text(
                    """
                    SELECT package_json, tokens_used
                    FROM ai_content_cache
                    WHERE tenant_id = :tid
                      AND cache_key  = :key
                      AND expires_at > NOW()
                      AND NOT is_deleted
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id, "key": cache_key},
            )
            result = row.mappings().first()
        except Exception as exc:  # noqa: BLE001 — 缓存查询失败不阻断主流程
            logger.warning(
                "content_hub_cache_read_failed",
                cache_key=cache_key,
                tenant_id=tenant_id,
                error=str(exc),
                exc_info=True,
            )
            return None

        if result is None:
            return None

        try:
            pkg_data: dict[str, Any] = result["package_json"]
            pkg = CampaignContentPackage(**pkg_data)
            pkg.cached = True
            return pkg
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "content_hub_cache_parse_failed",
                cache_key=cache_key,
                error=str(exc),
            )
            return None

    async def _save_to_cache(
        self,
        cache_key: str,
        package: CampaignContentPackage,
        tenant_id: str,
        db: AsyncSession,
    ) -> None:
        """将生成结果写入 ai_content_cache 表（best-effort）。"""
        await self._upsert_content_cache(
            cache_key=cache_key,
            campaign_type=package.campaign_type,
            pkg_json=json.dumps(package.model_dump(), ensure_ascii=False, default=str),
            tokens_used=package.tokens_used,
            tenant_id=tenant_id,
            db=db,
            log_event="content_hub_cache",
        )

    async def _upsert_content_cache(
        self,
        *,
        cache_key: str,
        campaign_type: str,
        pkg_json: str,
        tokens_used: int,
        tenant_id: str,
        db: AsyncSession | None,
        log_event: str,
    ) -> None:
        """Shared helper: upsert a row in ai_content_cache (best-effort).

        If *db* is None, acquires a short-lived session internally.
        Write failures are logged and swallowed so callers are never blocked.
        """
        own_session = db is None
        db_gen = None
        if own_session:
            try:
                from ..database import get_session  # lazy import

                db_gen = get_session()
                db = await db_gen.__anext__()
            except (ImportError, OSError, RuntimeError) as exc:
                logger.warning(
                    f"{log_event}_no_session",
                    cache_key=cache_key,
                    error=str(exc),
                )
                return

        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.MAX_CACHE_AGE_HOURS)
        try:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO ai_content_cache
                        (tenant_id, cache_key, campaign_type, package_json, tokens_used, expires_at)
                    VALUES
                        (:tid, :key, :ctype, :pkg_json, :tokens, :expires)
                    ON CONFLICT (tenant_id, cache_key)
                    WHERE NOT is_deleted
                    DO UPDATE SET
                        package_json = EXCLUDED.package_json,
                        tokens_used  = EXCLUDED.tokens_used,
                        expires_at   = EXCLUDED.expires_at
                    """
                ),
                {
                    "tid":      tenant_id,
                    "key":      cache_key,
                    "ctype":    campaign_type,
                    "pkg_json": pkg_json,
                    "tokens":   tokens_used,
                    "expires":  expires_at,
                },
            )
            await db.commit()
            logger.info(
                f"{log_event}_saved",
                cache_key=cache_key,
                tenant_id=tenant_id,
                expires_at=expires_at.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 — 缓存写入失败不阻断主流程
            logger.warning(
                f"{log_event}_write_failed",
                cache_key=cache_key,
                tenant_id=tenant_id,
                error=str(exc),
                exc_info=True,
            )
        finally:
            if own_session and db_gen is not None:
                try:
                    await db_gen.aclose()
                except (OSError, RuntimeError):
                    pass

    def _build_generation_prompt(self, request: CampaignContentRequest) -> str:
        """构建发给 Claude 的生成提示词。

        生成一个包含所有目标渠道、所有 A/B 变体的结构化中文提示词。
        """
        bv = request.brand_voice
        sc = request.store_context

        variant_labels = [chr(ord("A") + i) for i in range(max(1, request.ab_variants))]

        channel_constraints = []
        for ch in request.target_channels:
            max_chars = CHANNEL_MAX_CHARS.get(ch)
            if max_chars:
                channel_constraints.append(f"  - {ch}: 最多{max_chars}字")
            else:
                channel_constraints.append(f"  - {ch}: 适当长度")

        member_info = ""
        if request.member_segment:
            seg = request.member_segment
            parts = []
            if seg.get("rfm_tier"):
                parts.append(f"RFM层级:{seg['rfm_tier']}")
            if seg.get("age_group"):
                parts.append(f"年龄段:{seg['age_group']}")
            if seg.get("favorite_dishes"):
                parts.append(f"爱好菜品:{','.join(seg['favorite_dishes'][:3])}")
            if seg.get("days_inactive"):
                parts.append(f"沉默天数:{seg['days_inactive']}天")
            member_info = f"\n会员画像: {'; '.join(parts)}"

        offer_info = ""
        if request.offer_detail:
            od = request.offer_detail
            parts = []
            if od.get("coupon_value_fen") is not None:
                yuan = od["coupon_value_fen"] / 100
                parts.append(f"优惠金额:{yuan:.0f}元")
            if od.get("validity_days"):
                parts.append(f"有效期:{od['validity_days']}天")
            if od.get("conditions"):
                parts.append(f"使用条件:{od['conditions']}")
            offer_info = f"\n优惠信息: {'; '.join(parts)}"

        taboo_str = ""
        if bv.taboo_words:
            taboo_str = f"\n禁用词（绝对不能出现）: {', '.join(bv.taboo_words)}"

        signature_str = f"\n落款/标语: {bv.signature}" if bv.signature else ""

        emoji_guidance = {
            "none":     "不使用任何表情符号",
            "light":    "少量使用表情符号（1-2个）",
            "moderate": "适量使用表情符号（3-5个）",
            "heavy":    "大量使用表情符号营造活跃氛围",
        }.get(bv.emoji_style, "适量使用表情符号")

        prompt = f"""你是中国连锁餐饮行业顶级营销文案专家。请为以下活动生成全渠道营销内容。

## 品牌信息
品牌名称: {bv.brand_name}
品牌调性: {bv.tone}
表情风格: {emoji_guidance}{taboo_str}{signature_str}

## 门店信息
门店名称: {sc.get('store_name', bv.brand_name)}
所在城市: {sc.get('city', '未知')}
招牌菜品: {', '.join(sc.get('specialty_dishes', [])) or '特色美食'}
当前促销: {sc.get('current_promotions', '无')}

## 活动类型
{request.campaign_type}{member_info}{offer_info}

## 生成要求
1. 为以下 {len(request.target_channels)} 个渠道生成内容，共 {len(variant_labels)} 个变体（{'/'.join(variant_labels)}）
2. 每个渠道的字数约束（严格遵守，尤其短信≤70字）：
{chr(10).join(channel_constraints)}
3. 内容必须符合品牌调性，真实自然，不夸张不违规
4. 短信内容必须≤70个中文字符（含标点），超出会发送失败

## 目标渠道
{', '.join(request.target_channels)}

## 变体列表
{', '.join(variant_labels)}

## 输出格式（严格JSON，不带markdown代码块）
{{
  "reasoning": "简要说明内容策略和创作思路（100字以内）",
  "contents": [
    {{
      "channel": "渠道名",
      "variant_id": "A",
      "subject": "标题或主题（无标题渠道留空字符串）",
      "body": "正文内容",
      "cta": "行动号召（无则留空字符串）",
      "hashtags": ["话题标签（仅适用微博/小红书/抖音，其他渠道返回空数组）"]
    }}
  ]
}}

注意：contents 数组中包含所有渠道 × 所有变体的组合，共 {len(request.target_channels) * len(variant_labels)} 条记录。"""

        return prompt

    def _parse_claude_response(
        self,
        raw: str,
        request: CampaignContentRequest,
        request_id: str,
        tokens_used: int,
    ) -> CampaignContentPackage:
        """解析 Claude 返回的 JSON 文本，构建 CampaignContentPackage。

        若 JSON 解析失败，构造一个包含原始文本的降级包，不抛出异常。
        """
        raw_stripped = raw.strip()
        # 去除可能的 markdown 代码块标记
        if raw_stripped.startswith("```"):
            lines = raw_stripped.split("\n")
            raw_stripped = "\n".join(lines[1:-1]) if len(lines) > 2 else raw_stripped

        reasoning = ""
        contents: list[ChannelContent] = []

        try:
            data: dict[str, Any] = json.loads(raw_stripped)
            reasoning = data.get("reasoning", "")
            raw_contents: list[dict[str, Any]] = data.get("contents", [])

            for item in raw_contents:
                channel = item.get("channel", "unknown")
                body = item.get("body", "")
                char_count = len(body)

                # 强制截断超长 SMS
                max_chars = CHANNEL_MAX_CHARS.get(channel)
                if max_chars and char_count > max_chars:
                    body = body[:max_chars]
                    char_count = max_chars
                    logger.warning(
                        "content_hub_truncated",
                        channel=channel,
                        original_len=len(item.get("body", "")),
                        max_chars=max_chars,
                    )

                contents.append(
                    ChannelContent(
                        channel=channel,
                        subject=item.get("subject", ""),
                        body=body,
                        cta=item.get("cta", ""),
                        hashtags=item.get("hashtags", []),
                        char_count=char_count,
                        variant_id=item.get("variant_id", "A"),
                    )
                )

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "content_hub_parse_failed",
                request_id=request_id,
                error=str(exc),
                raw_preview=raw_stripped[:200],
            )
            # 降级：将原始文本放入第一个目标渠道
            fallback_channel = request.target_channels[0] if request.target_channels else "unknown"
            contents = [
                ChannelContent(
                    channel=fallback_channel,
                    body=raw_stripped[:500],
                    char_count=len(raw_stripped[:500]),
                    variant_id="A",
                )
            ]
            reasoning = "解析失败，返回原始文本"

        return CampaignContentPackage(
            request_id=request_id,
            campaign_type=request.campaign_type,
            generated_at=datetime.now(timezone.utc),
            contents=contents,
            reasoning=reasoning,
            tokens_used=tokens_used,
            cached=False,
        )

    @staticmethod
    def _make_cache_key(request: CampaignContentRequest) -> str:
        """基于请求内容的 SHA256 摘要生成缓存 key。"""
        payload = json.dumps(
            {
                "campaign_type":  request.campaign_type,
                "brand_name":     request.brand_voice.brand_name,
                "tone":           request.brand_voice.tone,
                "store_context":  request.store_context,
                "member_segment": request.member_segment,
                "offer_detail":   request.offer_detail,
                "channels":       sorted(request.target_channels),
                "ab_variants":    request.ab_variants,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
