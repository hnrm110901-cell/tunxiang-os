"""内容生成引擎 — 基于品牌策略与人群特征生成内容

为不同渠道、不同人群生成品牌调性一致的营销内容，
包括企微话术、朋友圈文案、短信、菜品故事等。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

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


# ---------------------------------------------------------------------------
# PersonalizedContentEngine — 基于 RFM 分层的个性化内容生成
# ---------------------------------------------------------------------------

import os
from uuid import UUID

import httpx


class PersonalizedContentEngine:
    """基于模板变量替换 + RFM 分层差异化的个性化内容生成引擎

    职责：
    - 从 tx-member 获取会员画像（RFM / 偏好菜品 / 最后到店时间）
    - 按 VIP(S1/S2) / 普通(S3/S4) 选择对应模板变体
    - 替换模板变量，生成最终推送内容
    - 缺失变量优雅降级（使用默认值，不报错）
    """

    TX_MEMBER_URL: str = os.getenv("TX_MEMBER_SERVICE_URL", "http://tx-member:8000")

    # 内置个性化内容模板库
    CONTENT_TEMPLATES: dict[str, dict] = {
        # ── 流失召回系列 ──────────────────────────────────────────────
        "churn_recovery_vip": {
            "title": "【专属】{display_name}，好久不见！",
            "description": "您已{days_since_last_order}天未到店，特为您准备{offer_desc}，期待您的归来。",
            "btntxt": "立即领取",
        },
        "churn_recovery_normal": {
            "title": "想你了！来享受优惠吧",
            "description": "好久没见到您啦，送您{offer_desc}，快来尝尝我们的{favorite_dish}！",
            "btntxt": "查看优惠",
        },
        # ── 生日系列 ──────────────────────────────────────────────────
        "birthday_vip": {
            "title": "🎂 {display_name}，生日快乐！",
            "description": "感谢您{total_order_count}次的光临与信任，特为您准备生日专属礼遇：{offer_desc}",
            "btntxt": "查看礼遇",
        },
        "birthday_normal": {
            "title": "生日快乐！送您专属礼物",
            "description": "祝您生日快乐！凭此消息到店可享受{offer_desc}",
            "btntxt": "立即使用",
        },
        # ── 新品推送 ──────────────────────────────────────────────────
        "new_dish_vip": {
            "title": "新品抢先尝 | 专为{rfm_level}会员",
            "description": "根据您对{favorite_dish}的喜爱，特邀您体验我们的新品，前50位体验者享{offer_desc}",
            "btntxt": "了解新品",
        },
        "new_dish_normal": {
            "title": "新品上线，快来尝鲜！",
            "description": "我们推出了新品，和您喜爱的{favorite_dish}同样用心制作，{offer_desc}",
            "btntxt": "查看新品",
        },
        # ── 复购触发 ──────────────────────────────────────────────────
        "repurchase_cycle": {
            "title": "您最爱的{favorite_dish}等你来",
            "description": "距离上次品尝已经{days_since_last_order}天了，{display_name}，是时候犒劳自己了！",
            "btntxt": "立即预订",
        },
        # ── 通用（透传 extra_vars） ────────────────────────────────────
        "generic": {
            "title": "{title}",
            "description": "{description}",
            "btntxt": "{btntxt}",
        },
    }

    async def generate_content(
        self,
        template_key: str,
        customer_id: UUID,
        tenant_id: UUID,
        extra_vars: dict | None = None,
    ) -> dict:
        """根据模板 key 和会员数据生成个性化内容

        步骤：
        1. 从 tx-member API 查询会员数据
        2. 构建模板变量字典（display_name / days_since_last_order / favorite_dish 等）
        3. 按 RFM 等级选择模板变体（VIP 优先 _vip 版本）
        4. 替换模板变量（缺失 key 用默认值兜底）
        5. 返回 {title, description, btntxt}

        Args:
            template_key:  模板基础 key，如 "churn_recovery" / "birthday" / "generic"
            customer_id:   会员 UUID
            tenant_id:     租户 UUID
            extra_vars:    额外变量（优先级高于会员数据，常用：offer_desc / url）

        Returns:
            {"title": str, "description": str, "btntxt": str}
        """
        customer = await self._fetch_customer(customer_id, tenant_id)
        vars_dict = self._build_template_vars(customer, extra_vars or {})
        actual_key = self._select_template_variant(template_key, customer)
        template = self.CONTENT_TEMPLATES.get(
            actual_key, self.CONTENT_TEMPLATES["generic"]
        )
        return {
            "title": self._safe_format(template["title"], vars_dict),
            "description": self._safe_format(template["description"], vars_dict),
            "btntxt": self._safe_format(template.get("btntxt", "查看详情"), vars_dict),
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_template_vars(self, customer: dict, extra: dict) -> dict:
        """构建模板变量字典，extra 中的同名键覆盖默认值"""
        from datetime import datetime, timezone

        last_order_at: str | None = customer.get("last_order_at")
        if last_order_at:
            try:
                last_dt = datetime.fromisoformat(last_order_at.replace("Z", "+00:00"))
                days_since: int = (datetime.now(timezone.utc) - last_dt).days
            except ValueError:
                days_since = 999
        else:
            days_since = 999

        favorite_dishes: list = customer.get("favorite_dishes", [])
        favorite: str = (
            favorite_dishes[0]["name"] if favorite_dishes else "招牌菜"
        )

        base: dict = {
            "display_name": customer.get("display_name") or "亲",
            "days_since_last_order": str(days_since),
            "favorite_dish": favorite,
            "rfm_level": customer.get("rfm_level") or "S3",
            "total_order_count": str(customer.get("total_order_count") or 0),
            "member_level": customer.get("member_level") or "普通会员",
            # 以下由 extra_vars 提供，设默认值防止 KeyError
            "offer_desc": "专属优惠",
            "title": "",
            "description": "",
            "btntxt": "查看详情",
        }
        # extra 覆盖 base（extra 优先）
        base.update(extra)
        return base

    def _select_template_variant(self, template_key: str, customer: dict) -> str:
        """按会员 RFM 等级选择模板变体

        优先级：{template_key}_vip > {template_key}_normal > template_key > generic
        """
        rfm_level: str = customer.get("rfm_level") or "S3"
        is_vip: bool = rfm_level in ("S1", "S2")

        vip_key = f"{template_key}_vip"
        normal_key = f"{template_key}_normal"

        if is_vip and vip_key in self.CONTENT_TEMPLATES:
            return vip_key
        if normal_key in self.CONTENT_TEMPLATES:
            return normal_key
        if template_key in self.CONTENT_TEMPLATES:
            return template_key
        return "generic"

    @staticmethod
    def _safe_format(template_str: str, vars_dict: dict) -> str:
        """安全格式化：缺失的 key 用空字符串替换，不抛出 KeyError"""
        try:
            return template_str.format(**vars_dict)
        except KeyError:
            # 逐个替换，缺失 key 降级为空字符串
            import re
            result = template_str
            for key in re.findall(r"\{(\w+)\}", template_str):
                result = result.replace(f"{{{key}}}", vars_dict.get(key, ""))
            return result

    async def _fetch_customer(self, customer_id: UUID, tenant_id: UUID) -> dict:
        """从 tx-member 获取会员数据

        API: GET /api/v1/member/customers/{customer_id}
        响应包含：display_name, rfm_level, last_order_at, favorite_dishes,
                  total_order_count, member_level, wecom_external_userid
        """
        import structlog
        log = structlog.get_logger(__name__)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers/{customer_id}",
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except httpx.HTTPStatusError as exc:
            log.warning(
                "personalized_content_fetch_customer_http_error",
                customer_id=str(customer_id),
                status_code=exc.response.status_code,
            )
            return {}
        except httpx.RequestError as exc:
            log.warning(
                "personalized_content_fetch_customer_request_error",
                customer_id=str(customer_id),
                error=str(exc),
            )
            return {}


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
