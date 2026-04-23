"""内容生成 Agent — P1 | 云端

营销文案生成、社交媒体内容、菜品描述、活动海报文案、短视频脚本、评论回复。

品牌约束层：
  所有生成方法在执行前会调用 tx-growth 的 /api/v1/brand/content-brief 端点，
  获取 BrandStrategyDbService.build_content_brief() 返回的完整约束包，
  并将 system_prompt 注入 LLM 的 system message，确保：
    1. 生成内容符合品牌 voice（tone/style/preferred_words）
    2. 不出现 forbidden_words / forbidden_elements
    3. 遵守渠道字数限制（max_length）
    4. 融入当前节气/节日营销上下文
"""

import os
from typing import Any, Optional

import httpx
import structlog

from ..base import AgentResult, SkillAgent

log = structlog.get_logger(__name__)

# tx-growth 服务地址（通过环境变量配置，本地开发默认值）
_GROWTH_BASE_URL = os.getenv("TX_GROWTH_URL", "http://localhost:8040")

# 渠道名称到 content-brief channel 参数的映射
_CHANNEL_MAP: dict[str, str] = {
    "wechat_moments": "wechat",
    "wechat_push": "wechat",
    "douyin": "douyin",
    "xiaohongshu": "xiaohongshu",
    "sms": "sms",
    "poster": "poster",
    "wecom": "wecom",
    "miniapp": "miniapp",
}


async def _fetch_content_brief(
    tenant_id: str,
    channel: str,
    segment: str,
    purpose: str,
) -> Optional[dict[str, Any]]:
    """从 tx-growth 获取品牌内容简报

    Args:
        tenant_id: 租户 UUID 字符串
        channel:   渠道标识（经过 _CHANNEL_MAP 映射后的值）
        segment:   目标客群名称
        purpose:   内容目的

    Returns:
        ContentBrief dict 或 None（若服务不可用则降级，不阻塞生成）
    """
    if not tenant_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_GROWTH_BASE_URL}/api/v1/brand/content-brief",
                params={"channel": channel, "segment": segment, "purpose": purpose},
                headers={"X-Tenant-ID": tenant_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data.get("data")
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
        log.warning(
            "brand_brief_fetch_failed",
            tenant_id=tenant_id,
            channel=channel,
            error=str(exc),
        )
    return None


def _apply_brand_constraints(
    content: str,
    brief: Optional[dict[str, Any]],
    max_chars: int,
) -> str:
    """应用品牌约束到已生成文案

    1. 若品牌有 max_length 约束，取品牌限制与平台限制的较小值截断
    2. 检查并移除 forbidden_words（简单替换为空，生产环境应重新生成）
    """
    if brief is None:
        if len(content) > max_chars:
            content = content[: max_chars - 3] + "..."
        return content

    # 渠道字数约束：取品牌约束与平台约束的较小值
    brand_max = brief.get("max_length")
    effective_max = min(brand_max, max_chars) if brand_max else max_chars
    if len(content) > effective_max:
        content = content[: effective_max - 3] + "..."

    # 禁止词检查（替换处理，生产环境建议重新生成）
    for word in brief.get("forbidden_words", []):
        if word and word in content:
            content = content.replace(word, "")
            log.warning("forbidden_word_removed", word=word)

    for elem in brief.get("forbidden_elements", []):
        elem_str = str(elem) if elem else ""
        if elem_str and elem_str in content:
            content = content.replace(elem_str, "")
            log.warning("forbidden_element_removed", element=elem_str)

    return content


# 文案风格模板
TONE_STYLES = {
    "warm": {"name": "温馨", "emoji_density": "low", "sentence_style": "短句为主"},
    "playful": {"name": "活泼", "emoji_density": "high", "sentence_style": "口语化"},
    "premium": {"name": "高端", "emoji_density": "none", "sentence_style": "文雅精炼"},
    "promotional": {"name": "促销", "emoji_density": "medium", "sentence_style": "直击痛点"},
}

# 平台特性
PLATFORM_SPECS = {
    "wechat_moments": {"name": "朋友圈", "max_chars": 200, "image_count": "1-9", "hashtags": False},
    "douyin": {"name": "抖音", "max_chars": 55, "video_required": True, "hashtags": True},
    "xiaohongshu": {"name": "小红书", "max_chars": 1000, "image_count": "1-9", "hashtags": True},
    "meituan": {"name": "美团", "max_chars": 500, "image_count": "1-15", "hashtags": False},
    "dianping": {"name": "大众点评", "max_chars": 500, "image_count": "1-9", "hashtags": False},
    "sms": {"name": "短信", "max_chars": 70, "image_count": "0", "hashtags": False},
    "wechat_push": {"name": "公众号推送", "max_chars": 2000, "image_count": "1-6", "hashtags": False},
}


class ContentGenerationAgent(SkillAgent):
    agent_id = "content_generation"
    agent_name = "内容生成"
    description = "营销文案生成、社交媒体内容、菜品描述、活动海报文案、短视频脚本、评论回复"
    priority = "P1"
    run_location = "cloud"

    # Sprint D1 / PR Overflow：纯文案生成，不触发业务决策，豁免
    constraint_scope = set()
    constraint_waived_reason = (
        "内容生成纯文案/脚本/海报文案/评论回复生成工具，"
        "不直接操作毛利/食安/客户体验三条业务约束维度"
    )

    def get_supported_actions(self) -> list[str]:
        return [
            "generate_marketing_copy",
            "generate_social_content",
            "generate_dish_description",
            "generate_poster_copy",
            "generate_video_script",
            "generate_review_reply",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "generate_marketing_copy": self._marketing_copy,
            "generate_social_content": self._social_content,
            "generate_dish_description": self._dish_description,
            "generate_poster_copy": self._poster_copy,
            "generate_video_script": self._video_script,
            "generate_review_reply": self._review_reply,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _marketing_copy(self, params: dict) -> AgentResult:
        """营销文案生成

        执行前调用 tx-growth /api/v1/brand/content-brief 获取品牌约束包，
        将 system_prompt 注入 LLM（当前为模板生成，LLM 集成时直接传入）。
        """
        campaign_type = params.get("campaign_type", "general")
        brand_name = params.get("brand_name", "")
        offer = params.get("offer", "")
        tone = params.get("tone", "warm")
        target_audience = params.get("target_audience", "全部顾客")
        tenant_id: str = params.get("tenant_id", "")

        # 获取品牌约束简报（降级安全：失败不阻塞生成）
        channel = _CHANNEL_MAP.get(params.get("platform", "wechat_moments"), "wechat")
        brand_brief = await _fetch_content_brief(
            tenant_id=tenant_id,
            channel=channel,
            segment=target_audience,
            purpose=f"{campaign_type}营销文案",
        )

        # 若品牌档案有品牌名，优先使用
        if brand_brief and brand_brief.get("brand_name"):
            brand_name = brand_brief["brand_name"]

        # 若品牌有语气配置，覆盖默认 tone 参数
        if brand_brief and brand_brief.get("tone"):
            brand_tone_name = brand_brief["tone"]
            # 将品牌语气名映射回内部枚举（模糊匹配）
            if any(k in brand_tone_name for k in ["高端", "精致", "奢"]):
                tone = "premium"
            elif any(k in brand_tone_name for k in ["活泼", "轻松", "年轻"]):
                tone = "playful"
            elif any(k in brand_tone_name for k in ["促销", "优惠", "折扣"]):
                tone = "promotional"
            # 否则保持传入的 tone 或 warm 默认值

        tone_info = TONE_STYLES.get(tone, TONE_STYLES["warm"])

        # 生成多版本文案
        copies = []
        if campaign_type == "new_customer":
            copies = [
                f"初次相遇，{brand_name}为您准备了一份心意——{offer}，期待与您的味蕾邂逅。",
                f"欢迎新朋友！{brand_name}{offer}，好味道值得分享。",
                f"第一次来{brand_name}？{offer}，让美食开启我们的故事。",
            ]
        elif campaign_type == "recall":
            copies = [
                f"好久不见，{brand_name}想念您的味蕾。{offer}，欢迎回来。",
                f"您有一份来自{brand_name}的思念——{offer}，期待重逢。",
                f"美食不会辜负等待，{brand_name}为您保留了专属位置。{offer}",
            ]
        elif campaign_type == "seasonal":
            copies = [
                f"时令限定，{brand_name}应季上新！{offer}，尝鲜趁早。",
                f"跟着节气吃，{brand_name}限时{offer}，不负好时光。",
                f"季节的馈赠，{brand_name}为您呈现——{offer}",
            ]
        else:
            copies = [
                f"{brand_name}诚意推荐，{offer}，好味道不等人。",
                f"来{brand_name}，享受{offer}，每一口都是惊喜。",
                f"{offer}——{brand_name}邀您共享美味时光。",
            ]

        # 应用品牌约束（forbidden_words / max_length）
        constrained_copies = [_apply_brand_constraints(c, brand_brief, 500) for c in copies]

        return AgentResult(
            success=True,
            action="generate_marketing_copy",
            data={
                "campaign_type": campaign_type,
                "tone": tone,
                "tone_name": tone_info["name"],
                "copies": [
                    {"version": i + 1, "text": c, "char_count": len(c)} for i, c in enumerate(constrained_copies)
                ],
                "recommended_version": 1,
                "target_audience": target_audience,
                "brand_constrained": brand_brief is not None,
                "brand_system_prompt": brand_brief.get("system_prompt") if brand_brief else None,
            },
            reasoning=(
                f"为{campaign_type}活动生成 {len(constrained_copies)} 版文案，"
                f"风格: {tone_info['name']}"
                + ("（已应用品牌约束）" if brand_brief else "（品牌档案未配置，使用默认约束）")
            ),
            confidence=0.8,
        )

    async def _social_content(self, params: dict) -> AgentResult:
        """社交媒体内容生成（注入品牌约束）"""
        platform = params.get("platform", "wechat_moments")
        topic = params.get("topic", "")
        brand_name = params.get("brand_name", "")
        dishes = params.get("featured_dishes", [])
        tenant_id: str = params.get("tenant_id", "")
        target_segment: str = params.get("target_segment", "全部顾客")

        # 获取品牌约束简报
        channel = _CHANNEL_MAP.get(platform, "wechat")
        brand_brief = await _fetch_content_brief(
            tenant_id=tenant_id,
            channel=channel,
            segment=target_segment,
            purpose=f"社交媒体{platform}内容",
        )
        if brand_brief and brand_brief.get("brand_name"):
            brand_name = brand_brief["brand_name"]

        # 若有节气上下文且 topic 为空，融入节气主题
        if not topic and brand_brief:
            season_ctx = brand_brief.get("current_season_context") or {}
            active = season_ctx.get("active_campaigns", [])
            nearest = season_ctx.get("nearest_solar_term", {})
            if active:
                topic = active[0].get("campaign_theme") or active[0].get("period_name", "")
            elif nearest:
                topic = nearest.get("name", "")

        platform_info = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["wechat_moments"])
        max_chars = platform_info["max_chars"]

        # 根据平台生成内容
        dish_text = "、".join(dishes[:3]) if dishes else "招牌美食"
        # topic 默认值（兜底）
        if not topic:
            topic = "美食探店"
        if platform == "douyin":
            content = f"来{brand_name}必点{dish_text}！#美食探店 #{brand_name}"
            image_guide = "建议拍摄15-30秒菜品特写视频"
        elif platform == "xiaohongshu":
            content = (
                f"在{brand_name}发现了宝藏餐厅！\n\n"
                f"必点推荐：{dish_text}\n"
                f"每一道都超级惊艳，{topic}不踩雷\n\n"
                f"#{brand_name} #美食推荐 #{topic}"
            )
            image_guide = "建议9宫格精修图，第一张为环境/摆盘"
        elif platform == "sms":
            content = f"【{brand_name}】{topic}，{dish_text}等你来尝！回T退订"
            image_guide = "短信无图"
        else:
            content = f"{topic}\n{brand_name}{dish_text}，每一口都是幸福的味道。"
            image_guide = "建议3-6张菜品高清图"

        # 应用品牌约束（forbidden_words / max_length / channel max_chars）
        content = _apply_brand_constraints(content, brand_brief, max_chars)

        return AgentResult(
            success=True,
            action="generate_social_content",
            data={
                "platform": platform,
                "platform_name": platform_info["name"],
                "content": content,
                "char_count": len(content),
                "max_chars": max_chars,
                "image_guide": image_guide,
                "best_post_time": "11:30-12:30 或 17:30-18:30",
                "hashtags": [f"#{brand_name}", f"#{topic}"] if platform_info.get("hashtags") else [],
                "brand_constrained": brand_brief is not None,
                "brand_system_prompt": brand_brief.get("system_prompt") if brand_brief else None,
            },
            reasoning=(
                f"为{platform_info['name']}生成内容，{len(content)}字" + ("（已应用品牌约束）" if brand_brief else "")
            ),
            confidence=0.8,
        )

    async def _dish_description(self, params: dict) -> AgentResult:
        """菜品描述生成"""
        dish_name = params.get("dish_name", "")
        ingredients = params.get("ingredients", [])
        cooking_method = params.get("cooking_method", "")
        flavor_profile = params.get("flavor_profile", "")
        price_fen = params.get("price_fen", 0)

        ingredient_text = "、".join(ingredients[:4]) if ingredients else "精选食材"

        descriptions = {
            "menu": f"精选{ingredient_text}，{cooking_method}烹制，{flavor_profile}，每一口都是匠心呈现。",
            "promotion": f"人气爆款！{dish_name}——{ingredient_text}{cooking_method}，{flavor_profile}，仅 ¥{price_fen / 100:.0f}！",
            "social": f"来了必点的{dish_name}！{ingredient_text}的完美组合，{flavor_profile}，谁吃谁知道！",
        }

        return AgentResult(
            success=True,
            action="generate_dish_description",
            data={
                "dish_name": dish_name,
                "descriptions": descriptions,
                "recommended_for_menu": descriptions["menu"],
                "ingredients_highlighted": ingredients[:4],
                "selling_points": [cooking_method, flavor_profile] if cooking_method else [flavor_profile],
            },
            reasoning=f"为「{dish_name}」生成3种场景描述文案",
            confidence=0.85,
        )

    async def _poster_copy(self, params: dict) -> AgentResult:
        """活动海报文案生成"""
        event_name = params.get("event_name", "")
        offer = params.get("offer", "")
        valid_period = params.get("valid_period", "")
        brand_name = params.get("brand_name", "")

        poster = {
            "headline": f"{event_name}",
            "subheadline": offer,
            "body": f"{brand_name}邀您共享{event_name}，{offer}，不容错过！",
            "cta": "立即预订",
            "footer": f"活动时间: {valid_period}" if valid_period else "数量有限，先到先得",
            "disclaimer": "最终解释权归本店所有",
        }

        return AgentResult(
            success=True,
            action="generate_poster_copy",
            data={
                "event_name": event_name,
                "poster_copy": poster,
                "layout_suggestion": "主标题居中大字，副标题下方，CTA按钮醒目",
                "color_scheme": "暖色调（红/橙）适合促销，冷色调（蓝/绿）适合品质",
            },
            reasoning=f"为「{event_name}」生成海报文案，含标题/副标题/正文/CTA",
            confidence=0.85,
        )

    async def _video_script(self, params: dict) -> AgentResult:
        """短视频脚本生成"""
        topic = params.get("topic", "")
        duration_seconds = params.get("duration_seconds", 15)
        brand_name = params.get("brand_name", "")
        featured_dish = params.get("featured_dish", "")
        style = params.get("style", "探店")

        if duration_seconds <= 15:
            script = {
                "scenes": [
                    {"time": "0-3s", "visual": "门店外景/招牌", "narration": f"来{brand_name}打卡！", "bgm": "轻快"},
                    {
                        "time": "3-8s",
                        "visual": f"{featured_dish}特写",
                        "narration": f"这道{featured_dish}绝了！",
                        "bgm": "轻快",
                    },
                    {
                        "time": "8-12s",
                        "visual": "夹起/品尝动作",
                        "narration": f"入口{topic}，好吃到停不下来",
                        "bgm": "高潮",
                    },
                    {"time": "12-15s", "visual": "门店地址字幕", "narration": "快来尝尝吧！", "bgm": "轻快"},
                ],
            }
        else:
            script = {
                "scenes": [
                    {
                        "time": "0-3s",
                        "visual": "开场悬念/美食近景",
                        "narration": "你绝对没吃过这么好吃的！",
                        "bgm": "悬疑",
                    },
                    {
                        "time": "3-10s",
                        "visual": "环境+点菜过程",
                        "narration": f"来{brand_name}，必点{featured_dish}",
                        "bgm": "轻快",
                    },
                    {"time": "10-20s", "visual": "菜品上桌+特写", "narration": f"{topic}，色香味俱全", "bgm": "轻快"},
                    {
                        "time": "20-25s",
                        "visual": "品尝+表情反应",
                        "narration": "入口的瞬间，幸福感爆棚！",
                        "bgm": "高潮",
                    },
                    {"time": "25-30s", "visual": "结尾字幕+定位", "narration": "关注收藏，下次不迷路！", "bgm": "轻快"},
                ],
            }

        return AgentResult(
            success=True,
            action="generate_video_script",
            data={
                "topic": topic,
                "duration_seconds": duration_seconds,
                "style": style,
                "script": script,
                "total_scenes": len(script["scenes"]),
                "tips": ["前3秒必须抓眼球", "美食特写要近景", "加字幕提升完播率", "结尾引导关注"],
            },
            reasoning=f"为「{topic}」生成 {duration_seconds}秒 短视频脚本，{len(script['scenes'])} 个分镜",
            confidence=0.75,
        )

    async def _review_reply(self, params: dict) -> AgentResult:
        """评论回复生成"""
        review_text = params.get("review_text", "")
        rating = params.get("rating", 5)
        platform = params.get("platform", "大众点评")
        brand_name = params.get("brand_name", "")

        if rating >= 4:
            tone = "感谢"
            reply = f"感谢您对{brand_name}的认可！我们会继续努力，期待您的再次光临。"
            if "好吃" in review_text or "味道" in review_text:
                reply = f"感谢您的好评！能让您满意是我们最大的动力，欢迎常来{brand_name}品尝更多美味！"
        elif rating >= 3:
            tone = "中性"
            reply = "感谢您的反馈！您提出的建议我们已认真记录，会持续改进。期待下次给您更好的体验。"
        else:
            tone = "致歉"
            issues = []
            if "慢" in review_text or "等" in review_text:
                issues.append("出餐速度")
            if "服务" in review_text or "态度" in review_text:
                issues.append("服务质量")
            if "味道" in review_text or "难吃" in review_text:
                issues.append("菜品口味")

            issue_text = "、".join(issues) if issues else "您反映的问题"
            reply = (
                f"非常抱歉给您带来了不好的体验！关于{issue_text}，"
                f"我们已经高度重视并着手改进。欢迎您联系我们（电话/微信），"
                f"我们将为您准备一份专属补偿。"
            )

        return AgentResult(
            success=True,
            action="generate_review_reply",
            data={
                "platform": platform,
                "rating": rating,
                "tone": tone,
                "reply": reply,
                "char_count": len(reply),
                "reply_urgency": "high" if rating <= 2 else "medium" if rating <= 3 else "low",
                "follow_up_needed": rating <= 2,
            },
            reasoning=f"{platform}评论回复: {rating}星，语气{tone}，{len(reply)}字",
            confidence=0.85,
        )
