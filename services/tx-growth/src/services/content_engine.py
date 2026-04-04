"""内容生成引擎 — 基于品牌策略与人群特征生成内容

为不同渠道、不同人群生成品牌调性一致的营销内容，
包括企微话术、朋友圈文案、短信、菜品故事等。

v144 DB 化：移除内存存储，改为 async SQLAlchemy + content_templates 表
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 内置模板定义（首次使用时 UPSERT 到 DB，绑定 tenant_id）
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

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    async def _ensure_builtin_templates(self, db: AsyncSession, tid: uuid.UUID) -> None:
        """为当前租户 UPSERT 内置模板（幂等，首次调用时初始化）"""
        now = datetime.now(timezone.utc)
        for key, tpl in _BUILTIN_TEMPLATES.items():
            await db.execute(
                text("""
                    INSERT INTO content_templates
                        (id, tenant_id, template_key, name, content_type,
                         body_template, variables, is_builtin, is_active,
                         usage_count, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :tid, :key, :name, :content_type,
                         :body, :variables::jsonb, true, true,
                         0, :now, :now)
                    ON CONFLICT ON CONSTRAINT uq_content_templates_tenant_key DO NOTHING
                """),
                {
                    "tid": tid,
                    "key": key,
                    "name": tpl["name"],
                    "content_type": tpl["content_type"],
                    "body": tpl["body_template"],
                    "variables": json.dumps(tpl["variables"]),
                    "now": now,
                },
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_template(
        self,
        name: str,
        content_type: str,
        template_body: str,
        target_channels: list[str],
        variables: list[str],
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """创建自定义内容模板，INSERT into content_templates

        Args:
            name: 模板名称
            content_type: 内容类型（CONTENT_TYPES 之一）
            template_body: 模板正文（使用 {variable_name} 标记变量）
            target_channels: 目标渠道列表（信息字段，不约束入库）
            variables: 模板变量名列表
            tenant_id: 租户ID
            db: 数据库会话
        """
        if content_type not in self.CONTENT_TYPES:
            return {"error": f"不支持的内容类型: {content_type}"}

        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        now = datetime.now(timezone.utc)
        new_id = uuid.uuid4()

        await db.execute(
            text("""
                INSERT INTO content_templates
                    (id, tenant_id, template_key, name, content_type,
                     body_template, variables, is_builtin, is_active,
                     usage_count, created_at, updated_at)
                VALUES
                    (:id, :tid, null, :name, :content_type,
                     :body, :variables::jsonb, false, true,
                     0, :now, :now)
            """),
            {
                "id": new_id,
                "tid": tid,
                "name": name,
                "content_type": content_type,
                "body": template_body,
                "variables": json.dumps(variables),
                "now": now,
            },
        )
        await db.commit()

        logger.info(
            "content_engine.create_template",
            template_id=str(new_id),
            content_type=content_type,
            tenant_id=tenant_id,
        )
        return {
            "template_id": str(new_id),
            "name": name,
            "content_type": content_type,
            "body_template": template_body,
            "target_channels": target_channels,
            "variables": variables,
            "is_builtin": False,
            "is_active": True,
            "usage_count": 0,
            "created_at": now.isoformat(),
        }

    async def get_template(
        self,
        template_id: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """查询单条内容模板，SELECT from content_templates"""
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        tpl_id = uuid.UUID(template_id)

        result = await db.execute(
            text("""
                SELECT id, template_key, name, content_type, body_template,
                       variables, is_builtin, is_active, usage_count,
                       created_at, updated_at
                FROM content_templates
                WHERE id = :tpl_id AND tenant_id = :tid
                  AND is_active = true AND is_deleted = false
                LIMIT 1
            """),
            {"tpl_id": tpl_id, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return {"error": f"模板不存在: {template_id}"}

        return {
            "template_id": str(row.id),
            "template_key": row.template_key,
            "name": row.name,
            "content_type": row.content_type,
            "body_template": row.body_template,
            "variables": row.variables if isinstance(row.variables, list) else [],
            "is_builtin": row.is_builtin,
            "is_active": row.is_active,
            "usage_count": row.usage_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def list_templates(
        self,
        content_type: Optional[str] = None,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict]:
        """查询内容模板列表，SELECT from content_templates（支持 content_type 过滤）

        首次调用时自动初始化该租户的内置模板。
        """
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)

        # 确保内置模板已初始化
        await self._ensure_builtin_templates(db, tid)
        await db.commit()

        where_parts = ["tenant_id = :tid", "is_active = true", "is_deleted = false"]
        params: dict = {"tid": tid}

        if content_type:
            where_parts.append("content_type = :content_type")
            params["content_type"] = content_type

        where_clause = " AND ".join(where_parts)
        result = await db.execute(
            text(f"""
                SELECT id, template_key, name, content_type, body_template,
                       variables, is_builtin, usage_count, created_at, updated_at
                FROM content_templates
                WHERE {where_clause}
                ORDER BY is_builtin DESC, usage_count DESC, created_at DESC
            """),
            params,
        )
        rows = result.fetchall()
        return [
            {
                "template_id": str(r.id),
                "template_key": r.template_key,
                "name": r.name,
                "content_type": r.content_type,
                "body_template": r.body_template,
                "variables": r.variables if isinstance(r.variables, list) else [],
                "is_builtin": r.is_builtin,
                "usage_count": r.usage_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    async def render_template(
        self,
        template_id: str,
        context: dict,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> str:
        """读取模板并替换变量，递增 usage_count，返回渲染后的文本

        Args:
            template_id: 模板 UUID
            context: 变量值字典，如 {"customer_name": "张三", "dish_name": "佛跳墙"}
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            渲染后的文本字符串；若模板不存在返回空字符串
        """
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        tpl_id = uuid.UUID(template_id)

        result = await db.execute(
            text("""
                SELECT id, body_template, variables
                FROM content_templates
                WHERE id = :tpl_id AND tenant_id = :tid
                  AND is_active = true AND is_deleted = false
                LIMIT 1
            """),
            {"tpl_id": tpl_id, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            logger.warning(
                "content_engine.render_template_not_found",
                template_id=template_id,
                tenant_id=tenant_id,
            )
            return ""

        body: str = row.body_template
        declared_vars: list[str] = row.variables if isinstance(row.variables, list) else []
        for var in declared_vars:
            placeholder = f"{{{var}}}"
            if placeholder in body and var in context:
                body = body.replace(placeholder, str(context[var]))

        # 递增使用次数（fire-and-forget：失败不影响主流程）
        try:
            await db.execute(
                text("""
                    UPDATE content_templates
                    SET usage_count = usage_count + 1, updated_at = NOW()
                    WHERE id = :tpl_id AND tenant_id = :tid
                """),
                {"tpl_id": tpl_id, "tid": tid},
            )
            await db.commit()
        except Exception:
            await db.rollback()

        return body

    # ------------------------------------------------------------------
    # 纯业务逻辑（不依赖存储，保留原有算法）
    # ------------------------------------------------------------------

    def generate_content(
        self,
        content_type: str,
        brand_id: str,
        target_segment: str,
        dish_name: Optional[str] = None,
        event_name: Optional[str] = None,
        tone: Optional[str] = None,
    ) -> dict:
        """生成营销内容（纯计算，不读写 DB）

        基于内容类型、品牌策略、目标人群自动生成内容。
        """
        if content_type not in self.CONTENT_TYPES:
            return {"error": f"不支持的内容类型: {content_type}"}

        content_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        effective_tone = tone or "温暖亲切"

        generated = self._generate_by_type(
            content_type, brand_id, target_segment, dish_name, event_name, effective_tone
        )

        return {
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

    def validate_content(self, brand_id: str, content_text: str) -> dict:
        """品牌合规性校验（纯计算，不读写 DB）"""
        errors: list[str] = []
        warnings: list[str] = []

        if len(content_text) > 2000:
            warnings.append("内容超过2000字符，建议精简")

        if len(content_text) < 10:
            errors.append("内容过短，不足10字符")

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
            "offer_desc": "专属优惠",
            "title": "",
            "description": "",
            "btntxt": "查看详情",
        }
        base.update(extra)
        return base

    def _select_template_variant(self, template_key: str, customer: dict) -> str:
        """按会员 RFM 等级选择模板变体"""
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
            import re
            result = template_str
            for key in re.findall(r"\{(\w+)\}", template_str):
                result = result.replace(f"{{{key}}}", vars_dict.get(key, ""))
            return result

    async def _fetch_customer(self, customer_id: UUID, tenant_id: UUID) -> dict:
        """从 tx-member 获取会员数据"""
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
