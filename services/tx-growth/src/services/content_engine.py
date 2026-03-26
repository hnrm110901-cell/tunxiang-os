"""内容生成引擎 — 基于品牌策略与人群特征生成内容

为不同渠道、不同人群生成品牌调性一致的营销内容，
包括企微话术、朋友圈文案、短信、菜品故事等。
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_templates: dict[str, dict] = {}
_generated_contents: dict[str, dict] = {}
_content_performance: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# 内容模板库（预置）
# ---------------------------------------------------------------------------

_BUILTIN_TEMPLATES: dict[str, dict] = {
    "wecom_chat_retention": {
        "name": "企微留存话术",
        "content_type": "wecom_chat",
        "body_template": "{customer_name}您好！上次您点的{dish_name}，好多老客都说念念不忘呢～这周我们{event_or_benefit}，专门给您留了位子，方便的话提前跟我说一声哦😊",
        "variables": ["customer_name", "dish_name", "event_or_benefit"],
    },
    "wecom_chat_new_dish": {
        "name": "企微新品推荐",
        "content_type": "wecom_chat",
        "body_template": "{customer_name}～我们新上了一道{dish_name}，{dish_story}，还没正式推就被内部试吃会一抢而空了！本周到店优先为您预留一份，要来尝尝吗？",
        "variables": ["customer_name", "dish_name", "dish_story"],
    },
    "moments_seasonal": {
        "name": "朋友圈时令推广",
        "content_type": "moments",
        "body_template": "🌿 {season_theme}\n{dish_name} | {dish_description}\n主厨说：「{chef_quote}」\n📍 {store_name}·{store_address}\n🎁 {benefit_text}",
        "variables": ["season_theme", "dish_name", "dish_description", "chef_quote", "store_name", "store_address", "benefit_text"],
    },
    "sms_reactivation": {
        "name": "短信召回",
        "content_type": "sms",
        "body_template": "【{brand_name}】{customer_name}，好久没见到您了！我们为您准备了{offer_text}，{validity_text}。退订回T",
        "variables": ["brand_name", "customer_name", "offer_text", "validity_text"],
    },
    "miniapp_banner_promo": {
        "name": "小程序横幅促销",
        "content_type": "miniapp_banner",
        "body_template": "{headline}\n{sub_headline}\n{cta_text}",
        "variables": ["headline", "sub_headline", "cta_text"],
    },
    "dish_story_template": {
        "name": "菜品故事",
        "content_type": "dish_story",
        "body_template": "📖 {dish_name}的故事\n\n{origin_story}\n\n🔥 烹饪秘诀：{cooking_secret}\n\n💡 主厨推荐搭配：{pairing_suggestion}",
        "variables": ["dish_name", "origin_story", "cooking_secret", "pairing_suggestion"],
    },
    "referral_invite_template": {
        "name": "老带新邀请",
        "content_type": "referral_invite",
        "body_template": "我在{brand_name}发现了一家宝藏店！{dish_highlight}。分享给你{offer_text}，一起来尝尝？",
        "variables": ["brand_name", "dish_highlight", "offer_text"],
    },
    "store_manager_script": {
        "name": "店长话术脚本",
        "content_type": "store_manager_script",
        "body_template": "📋 客户回访话术\n\n对象：{customer_type}\n场景：{scenario}\n\n开场白：「{opening}」\n推荐话术：「{recommendation}」\n收尾：「{closing}」\n\n⚠️ 注意事项：{notes}",
        "variables": ["customer_type", "scenario", "opening", "recommendation", "closing", "notes"],
    },
    "banquet_invite_template": {
        "name": "宴会邀请",
        "content_type": "banquet_invite",
        "body_template": "尊敬的{customer_name}：\n\n{brand_name}诚邀您参加{event_name}。\n\n📅 时间：{event_date}\n📍 地点：{venue}\n🍽️ 菜单亮点：{menu_highlight}\n\n{benefit_text}\n\n期待您的光临！",
        "variables": ["customer_name", "brand_name", "event_name", "event_date", "venue", "menu_highlight", "benefit_text"],
    },
}


# ---------------------------------------------------------------------------
# ContentEngine
# ---------------------------------------------------------------------------

class ContentEngine:
    """内容生成引擎 — 基于品牌策略与人群特征生成内容"""

    CONTENT_TYPES = [
        "wecom_chat", "moments", "miniapp_banner", "sms",
        "dish_story", "new_dish_promo", "seasonal_event",
        "referral_invite", "store_manager_script", "banquet_invite",
    ]

    def __init__(self) -> None:
        self._ensure_builtin_templates()

    def _ensure_builtin_templates(self) -> None:
        """加载内置模板"""
        for tpl_id, tpl in _BUILTIN_TEMPLATES.items():
            if tpl_id not in _templates:
                _templates[tpl_id] = {
                    "template_id": tpl_id,
                    **tpl,
                    "is_builtin": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

    def generate_content(
        self,
        content_type: str,
        brand_id: str,
        target_segment: str,
        dish_name: Optional[str] = None,
        event_name: Optional[str] = None,
        tone: Optional[str] = None,
    ) -> dict:
        """生成营销内容

        基于内容类型、品牌策略、目标人群自动生成内容。

        Args:
            content_type: 内容类型（CONTENT_TYPES 之一）
            brand_id: 品牌ID（用于获取品牌策略卡）
            target_segment: 目标分群名称
            dish_name: 菜品名称（可选）
            event_name: 活动名称（可选）
            tone: 覆盖品牌调性（可选）
        """
        if content_type not in self.CONTENT_TYPES:
            return {"error": f"不支持的内容类型: {content_type}"}

        content_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        effective_tone = tone or "温暖亲切"

        # 按内容类型 + 目标人群生成
        generated = self._generate_by_type(
            content_type, brand_id, target_segment, dish_name, event_name, effective_tone
        )

        content = {
            "content_id": content_id,
            "content_type": content_type,
            "brand_id": brand_id,
            "target_segment": target_segment,
            "tone": effective_tone,
            "title": generated["title"],
            "body": generated["body"],
            "call_to_action": generated["call_to_action"],
            "recommended_image_tags": generated["recommended_image_tags"],
            "created_at": now,
        }
        _generated_contents[content_id] = content
        return content

    def list_templates(self, content_type: Optional[str] = None) -> list[dict]:
        """列出模板"""
        templates = list(_templates.values())
        if content_type:
            templates = [t for t in templates if t.get("content_type") == content_type]
        return templates

    def create_template(
        self,
        name: str,
        content_type: str,
        body_template: str,
        variables: list[str],
    ) -> dict:
        """创建自定义模板"""
        template_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        template = {
            "template_id": template_id,
            "name": name,
            "content_type": content_type,
            "body_template": body_template,
            "variables": variables,
            "is_builtin": False,
            "created_at": now,
        }
        _templates[template_id] = template
        return template

    def validate_content(self, brand_id: str, content_text: str) -> dict:
        """品牌合规性校验（委托给 BrandStrategyService）

        此处做基础校验，完整校验由 BrandStrategyService.validate_content_against_brand 完成。
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 基础校验
        if len(content_text) > 2000:
            warnings.append("内容超过2000字符，建议精简")

        if len(content_text) < 10:
            errors.append("内容过短，不足10字符")

        # 通用禁忌词
        general_forbidden = ["最低价", "保证", "100%", "绝对", "第一名", "全网最"]
        for word in general_forbidden:
            if word in content_text:
                errors.append(f"包含广告法禁用词「{word}」")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "brand_id": brand_id,
        }

    def get_content_performance(self, content_id: str) -> dict:
        """获取内容效果数据"""
        perf = _content_performance.get(content_id)
        if perf:
            return perf

        # 默认返回零值
        content = _generated_contents.get(content_id)
        if not content:
            return {"error": f"内容不存在: {content_id}"}

        return {
            "content_id": content_id,
            "content_type": content.get("content_type", ""),
            "send_count": 0,
            "open_count": 0,
            "click_count": 0,
            "conversion_count": 0,
            "open_rate": 0.0,
            "click_rate": 0.0,
            "conversion_rate": 0.0,
        }

    def _generate_by_type(
        self,
        content_type: str,
        brand_id: str,
        target_segment: str,
        dish_name: Optional[str],
        event_name: Optional[str],
        tone: str,
    ) -> dict:
        """根据内容类型生成具体内容"""
        dish = dish_name or "招牌剁椒鱼头"
        event = event_name or "春季限定美食节"

        generators: dict[str, dict] = {
            "wecom_chat": {
                "title": f"企微话术-{target_segment}",
                "body": f"您好！上次您点的{dish}，好多老客都说念念不忘呢～这周我们推出了{event}专属福利，给您留了位子，方便的话提前跟我说一声哦",
                "call_to_action": "回复「预约」立即留位",
                "recommended_image_tags": ["菜品特写", "温馨氛围"],
            },
            "moments": {
                "title": f"朋友圈文案-{event}",
                "body": f"春天的味道，从一口{dish}开始。\n主厨严选时令食材，限量供应中。\n到店即享{event}专属礼遇。",
                "call_to_action": "点击预订尝鲜席位",
                "recommended_image_tags": ["精美摆盘", "时令食材", "环境氛围"],
            },
            "miniapp_banner": {
                "title": f"{event}限时开启",
                "body": f"{event} | {dish}领衔上阵\n限时专属价，先到先得",
                "call_to_action": "立即抢购",
                "recommended_image_tags": ["横幅设计", "促销元素", "菜品主图"],
            },
            "sms": {
                "title": f"短信-{target_segment}召回",
                "body": f"好久没见到您了！我们为您准备了{event}专属优惠券，到店即可使用，有效期7天。退订回T",
                "call_to_action": "到店出示短信领取",
                "recommended_image_tags": [],
            },
            "dish_story": {
                "title": f"{dish}的故事",
                "body": f"{dish}，源自湘菜大师三十年的手艺传承。选用洞庭湖鲜活鳙鱼，配以自制剁椒，猛火蒸制8分钟，鱼肉鲜嫩入味，辣而不燥。每一口都是匠心。\n\n主厨推荐搭配：手工米豆腐、农家时蔬",
                "call_to_action": "来品尝这道匠心之作",
                "recommended_image_tags": ["食材溯源", "烹饪过程", "成品特写"],
            },
            "new_dish_promo": {
                "title": f"新品上市-{dish}",
                "body": f"全新{dish}，主厨匠心打造！\n首周上线即获好评如潮，食客回头率92%。\n限时新品尝鲜价，抢先体验。",
                "call_to_action": "点击查看新品详情",
                "recommended_image_tags": ["新品标识", "菜品特写", "主厨推荐"],
            },
            "seasonal_event": {
                "title": f"{event}",
                "body": f"一年一度{event}正式开启！\n本次精选{dish}等8道时令佳肴，邀您共赏春味。\n活动期间到店消费满200元享专属礼遇。",
                "call_to_action": "立即预订席位",
                "recommended_image_tags": ["活动主视觉", "时令元素", "品牌形象"],
            },
            "referral_invite": {
                "title": "好友邀请",
                "body": f"我在这家店发现了超好吃的{dish}！分享给你一张新客专属券，一起来尝尝吧～",
                "call_to_action": "接受邀请领券",
                "recommended_image_tags": ["社交分享", "好友互动"],
            },
            "store_manager_script": {
                "title": f"店长话术-{target_segment}回访",
                "body": f"对象：{target_segment}\n\n开场白：「您好，我是XX店长小李，上次感谢您的光临！」\n推荐：「您上次点的{dish}是我们的招牌，这周我们还新推了几道时令菜，您要不要来试试？」\n收尾：「好的，那我帮您预留个好位子，到时见！」\n\n注意：不要过度推销，以关怀为主",
                "call_to_action": "引导预订",
                "recommended_image_tags": [],
            },
            "banquet_invite": {
                "title": f"宴会邀请-{event}",
                "body": f"诚邀您参加{event}！\n精心定制宴会菜单，{dish}领衔，多道主厨限定菜品。\n包间已为您预留，期待您的光临。",
                "call_to_action": "确认参加并选择套餐",
                "recommended_image_tags": ["宴会场景", "精美摆台", "高端氛围"],
            },
        }

        return generators.get(content_type, {
            "title": f"{content_type}内容",
            "body": f"为{target_segment}生成的{content_type}内容",
            "call_to_action": "了解更多",
            "recommended_image_tags": ["通用"],
        })


def record_content_performance(content_id: str, metrics: dict) -> None:
    """记录内容效果数据（辅助函数，用于测试和数据写入）"""
    _content_performance[content_id] = {
        "content_id": content_id,
        **metrics,
    }


def clear_all_content() -> None:
    """清空所有内容数据（仅测试用）"""
    _templates.clear()
    _generated_contents.clear()
    _content_performance.clear()
