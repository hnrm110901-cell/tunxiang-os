"""品牌策略中枢 DB 服务层

将品牌档案（brand_profiles）、营销日历（brand_seasonal_calendar）、
内容约束（brand_content_constraints）持久化到 PostgreSQL，
并提供 build_content_brief() 核心方法供 content_generation agent 消费。

金额单位：无（品牌档案不含金额字段）
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from models.brand_strategy import (
    BrandContentConstraintsCreate,
    BrandProfileCreate,
    BrandProfileUpdate,
    BrandSeasonalCalendarCreate,
    ContentBrief,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 24 节气 → 大致日期范围（月/日，不含年，仅用于匹配近似节气上下文）
# ---------------------------------------------------------------------------
_SOLAR_TERMS: list[dict[str, Any]] = [
    {"name": "小寒",  "month": 1,  "day_approx": 6},
    {"name": "大寒",  "month": 1,  "day_approx": 20},
    {"name": "立春",  "month": 2,  "day_approx": 4},
    {"name": "雨水",  "month": 2,  "day_approx": 19},
    {"name": "惊蛰",  "month": 3,  "day_approx": 6},
    {"name": "春分",  "month": 3,  "day_approx": 21},
    {"name": "清明",  "month": 4,  "day_approx": 5},
    {"name": "谷雨",  "month": 4,  "day_approx": 20},
    {"name": "立夏",  "month": 5,  "day_approx": 6},
    {"name": "小满",  "month": 5,  "day_approx": 21},
    {"name": "芒种",  "month": 6,  "day_approx": 6},
    {"name": "夏至",  "month": 6,  "day_approx": 21},
    {"name": "小暑",  "month": 7,  "day_approx": 7},
    {"name": "大暑",  "month": 7,  "day_approx": 23},
    {"name": "立秋",  "month": 8,  "day_approx": 7},
    {"name": "处暑",  "month": 8,  "day_approx": 23},
    {"name": "白露",  "month": 9,  "day_approx": 8},
    {"name": "秋分",  "month": 9,  "day_approx": 23},
    {"name": "寒露",  "month": 10, "day_approx": 8},
    {"name": "霜降",  "month": 10, "day_approx": 23},
    {"name": "立冬",  "month": 11, "day_approx": 7},
    {"name": "小雪",  "month": 11, "day_approx": 22},
    {"name": "大雪",  "month": 12, "day_approx": 7},
    {"name": "冬至",  "month": 12, "day_approx": 22},
]

# 节气名 → 适合餐饮营销的食材/主题提示
_SOLAR_TERM_HINTS: dict[str, str] = {
    "春分": "春季时令食材上市，适合推广春笋、荠菜等清新菜品",
    "清明": "清明前后，茶叶、春笋正当时，可推春季养生主题",
    "谷雨": "谷雨前后鱼肥虾美，适合推荐河鲜海鲜特色菜",
    "立夏": "夏季来临，主打清爽凉菜和时令饮品",
    "夏至": "夏至吃面的传统，适合推出面食特色活动",
    "立秋": "贴秋膘时节，可主推炖品/滋补菜系",
    "秋分": "秋分蟹肥，适合主推大闸蟹/螃蟹主题活动",
    "冬至": "冬至吃饺子传统，适合推出饺子/汤圆/暖锅",
    "大寒": "年关将近，适合预热春节年夜饭预订营销",
    "立春": "春节档期后，春季菜单上新时机",
}


def _nearest_solar_term(today: date) -> dict[str, str]:
    """返回距离今天最近（±10 天内）的节气名和提示"""
    for term in _SOLAR_TERMS:
        term_date = date(today.year, term["month"], term["day_approx"])
        delta = abs((today - term_date).days)
        if delta <= 10:
            return {
                "name": term["name"],
                "hint": _SOLAR_TERM_HINTS.get(term["name"], f"{term['name']}时令食材上市"),
                "days_delta": delta,
            }
    return {}


class BrandStrategyDbService:
    """品牌策略中枢 — PostgreSQL 持久化版本

    所有方法接收 AsyncSession（已设置 app.tenant_id），由调用方通过
    shared.ontology.src.database.get_db_with_tenant 注入。
    """

    # ─────────────────────────────────────────────────────────────────
    # brand_profiles CRUD
    # ─────────────────────────────────────────────────────────────────

    async def get_active_profile(
        self, tenant_id: uuid.UUID, db: AsyncSession
    ) -> Optional[dict[str, Any]]:
        """获取当前激活的品牌档案"""
        result = await db.execute(
            text("""
                SELECT id, tenant_id, brand_name, brand_slogan, brand_story,
                       cuisine_type, price_tier, core_value_proposition,
                       target_segments, key_scenarios, brand_voice, color_palette,
                       is_active, version, created_at, updated_at
                FROM brand_profiles
                WHERE tenant_id = :tid AND is_active = TRUE
                ORDER BY version DESC
                LIMIT 1
            """),
            {"tid": str(tenant_id)},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return dict(row)

    async def create_profile(
        self, tenant_id: uuid.UUID, data: BrandProfileCreate, db: AsyncSession
    ) -> dict[str, Any]:
        """创建品牌档案

        若 is_active=True，先将同租户其他档案设为非激活。
        """
        if data.is_active:
            await db.execute(
                text("UPDATE brand_profiles SET is_active = FALSE WHERE tenant_id = :tid"),
                {"tid": str(tenant_id)},
            )

        result = await db.execute(
            text("""
                INSERT INTO brand_profiles (
                    tenant_id, brand_name, brand_slogan, brand_story,
                    cuisine_type, price_tier, core_value_proposition,
                    target_segments, key_scenarios, brand_voice, color_palette,
                    is_active, version
                ) VALUES (
                    :tid, :brand_name, :brand_slogan, :brand_story,
                    :cuisine_type, :price_tier, :core_value_proposition,
                    :target_segments::jsonb, :key_scenarios::jsonb,
                    :brand_voice::jsonb, :color_palette::jsonb,
                    :is_active, 1
                )
                RETURNING id, tenant_id, brand_name, brand_slogan, brand_story,
                          cuisine_type, price_tier, core_value_proposition,
                          target_segments, key_scenarios, brand_voice, color_palette,
                          is_active, version, created_at, updated_at
            """),
            {
                "tid": str(tenant_id),
                "brand_name": data.brand_name,
                "brand_slogan": data.brand_slogan,
                "brand_story": data.brand_story,
                "cuisine_type": data.cuisine_type,
                "price_tier": data.price_tier,
                "core_value_proposition": data.core_value_proposition,
                "target_segments": _jsonb(data.target_segments),
                "key_scenarios": _jsonb(data.key_scenarios),
                "brand_voice": _jsonb(data.brand_voice),
                "color_palette": _jsonb(data.color_palette),
                "is_active": data.is_active,
            },
        )
        row = result.mappings().first()
        log.info("brand_profile_created", tenant_id=str(tenant_id), profile_id=str(row["id"]))
        return dict(row)

    async def update_profile(
        self,
        tenant_id: uuid.UUID,
        profile_id: uuid.UUID,
        data: BrandProfileUpdate,
        db: AsyncSession,
    ) -> Optional[dict[str, Any]]:
        """更新品牌档案，version +1

        若 is_active 设为 True，先将其他档案设为非激活。
        """
        if data.is_active is True:
            await db.execute(
                text(
                    "UPDATE brand_profiles SET is_active = FALSE "
                    "WHERE tenant_id = :tid AND id != :pid"
                ),
                {"tid": str(tenant_id), "pid": str(profile_id)},
            )

        # 动态构建 SET 子句，只更新传入的字段
        set_parts: list[str] = ["version = version + 1", "updated_at = NOW()"]
        params: dict[str, Any] = {"tid": str(tenant_id), "pid": str(profile_id)}

        scalar_fields = {
            "brand_name", "brand_slogan", "brand_story",
            "cuisine_type", "price_tier", "core_value_proposition", "is_active",
        }
        jsonb_fields = {"target_segments", "key_scenarios", "brand_voice", "color_palette"}

        for field in scalar_fields:
            val = getattr(data, field)
            if val is not None:
                set_parts.append(f"{field} = :{field}")
                params[field] = val

        for field in jsonb_fields:
            val = getattr(data, field)
            if val is not None:
                set_parts.append(f"{field} = :{field}::jsonb")
                params[field] = _jsonb(val)

        if len(set_parts) == 2:
            # 没有实质字段变化，直接查询返回
            return await self.get_active_profile(tenant_id, db)

        sql = (
            f"UPDATE brand_profiles SET {', '.join(set_parts)} "
            f"WHERE tenant_id = :tid AND id = :pid "
            f"RETURNING id, tenant_id, brand_name, brand_slogan, brand_story, "
            f"cuisine_type, price_tier, core_value_proposition, "
            f"target_segments, key_scenarios, brand_voice, color_palette, "
            f"is_active, version, created_at, updated_at"
        )
        result = await db.execute(text(sql), params)
        row = result.mappings().first()
        if row is None:
            return None
        log.info("brand_profile_updated", profile_id=str(profile_id), version=row["version"])
        return dict(row)

    # ─────────────────────────────────────────────────────────────────
    # brand_seasonal_calendar CRUD
    # ─────────────────────────────────────────────────────────────────

    async def list_calendar(
        self, tenant_id: uuid.UUID, db: AsyncSession,
        brand_profile_id: Optional[uuid.UUID] = None,
    ) -> list[dict[str, Any]]:
        """查询营销日历列表"""
        sql = """
            SELECT id, tenant_id, brand_profile_id, period_type, period_name,
                   start_date, end_date, campaign_theme, recommended_dishes,
                   marketing_focus, target_segments, created_at
            FROM brand_seasonal_calendar
            WHERE tenant_id = :tid
        """
        params: dict[str, Any] = {"tid": str(tenant_id)}
        if brand_profile_id:
            sql += " AND brand_profile_id = :bpid"
            params["bpid"] = str(brand_profile_id)
        sql += " ORDER BY start_date ASC"
        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings()]

    async def create_calendar_entry(
        self, tenant_id: uuid.UUID, data: BrandSeasonalCalendarCreate, db: AsyncSession
    ) -> dict[str, Any]:
        """添加营销日历节点"""
        result = await db.execute(
            text("""
                INSERT INTO brand_seasonal_calendar (
                    tenant_id, brand_profile_id, period_type, period_name,
                    start_date, end_date, campaign_theme, recommended_dishes,
                    marketing_focus, target_segments
                ) VALUES (
                    :tid, :bpid, :period_type, :period_name,
                    :start_date, :end_date, :campaign_theme, :recommended_dishes::jsonb,
                    :marketing_focus, :target_segments::jsonb
                )
                RETURNING id, tenant_id, brand_profile_id, period_type, period_name,
                          start_date, end_date, campaign_theme, recommended_dishes,
                          marketing_focus, target_segments, created_at
            """),
            {
                "tid": str(tenant_id),
                "bpid": str(data.brand_profile_id),
                "period_type": data.period_type,
                "period_name": data.period_name,
                "start_date": data.start_date,
                "end_date": data.end_date,
                "campaign_theme": data.campaign_theme,
                "recommended_dishes": _jsonb(data.recommended_dishes),
                "marketing_focus": data.marketing_focus,
                "target_segments": _jsonb(data.target_segments),
            },
        )
        row = result.mappings().first()
        log.info("brand_calendar_entry_created", tenant_id=str(tenant_id), entry_id=str(row["id"]))
        return dict(row)

    async def get_current_season_context(
        self, tenant_id: uuid.UUID, db: AsyncSession
    ) -> dict[str, Any]:
        """获取当前节气/节日上下文

        优先从 brand_seasonal_calendar 中查找覆盖今天的活跃营销节点；
        若未配置，则从内置 24 节气表推断最近节气并返回通用提示。
        """
        today = date.today()
        result = await db.execute(
            text("""
                SELECT id, period_type, period_name, start_date, end_date,
                       campaign_theme, recommended_dishes, marketing_focus, target_segments
                FROM brand_seasonal_calendar
                WHERE tenant_id = :tid
                  AND start_date <= :today
                  AND end_date >= :today
                ORDER BY start_date DESC
                LIMIT 3
            """),
            {"tid": str(tenant_id), "today": today},
        )
        rows = [dict(r) for r in result.mappings()]

        nearest_term = _nearest_solar_term(today)

        return {
            "today": today.isoformat(),
            "active_campaigns": rows,
            "nearest_solar_term": nearest_term,
            "has_active_campaign": len(rows) > 0,
        }

    # ─────────────────────────────────────────────────────────────────
    # brand_content_constraints CRUD
    # ─────────────────────────────────────────────────────────────────

    async def get_content_constraints(
        self,
        tenant_id: uuid.UUID,
        channel: str,
        db: AsyncSession,
        brand_profile_id: Optional[uuid.UUID] = None,
    ) -> list[dict[str, Any]]:
        """获取指定渠道的内容约束规则

        同时返回渠道专属规则（channel=channel）和全渠道通用规则（channel='all'）。
        """
        sql = """
            SELECT id, tenant_id, brand_profile_id, constraint_type, channel,
                   max_length, required_elements, forbidden_elements, template_hints, created_at
            FROM brand_content_constraints
            WHERE tenant_id = :tid
              AND channel IN (:channel, 'all')
        """
        params: dict[str, Any] = {"tid": str(tenant_id), "channel": channel}
        if brand_profile_id:
            sql += " AND brand_profile_id = :bpid"
            params["bpid"] = str(brand_profile_id)
        sql += " ORDER BY channel DESC"  # 渠道专属规则排在 'all' 前面
        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings()]

    async def list_constraints(
        self, tenant_id: uuid.UUID, db: AsyncSession,
        brand_profile_id: Optional[uuid.UUID] = None,
    ) -> list[dict[str, Any]]:
        """列出所有内容约束规则"""
        sql = """
            SELECT id, tenant_id, brand_profile_id, constraint_type, channel,
                   max_length, required_elements, forbidden_elements, template_hints, created_at
            FROM brand_content_constraints
            WHERE tenant_id = :tid
        """
        params: dict[str, Any] = {"tid": str(tenant_id)}
        if brand_profile_id:
            sql += " AND brand_profile_id = :bpid"
            params["bpid"] = str(brand_profile_id)
        sql += " ORDER BY channel, constraint_type"
        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings()]

    async def create_constraint(
        self, tenant_id: uuid.UUID, data: BrandContentConstraintsCreate, db: AsyncSession
    ) -> dict[str, Any]:
        """添加内容约束规则"""
        result = await db.execute(
            text("""
                INSERT INTO brand_content_constraints (
                    tenant_id, brand_profile_id, constraint_type, channel,
                    max_length, required_elements, forbidden_elements, template_hints
                ) VALUES (
                    :tid, :bpid, :constraint_type, :channel,
                    :max_length, :required_elements::jsonb,
                    :forbidden_elements::jsonb, :template_hints::jsonb
                )
                RETURNING id, tenant_id, brand_profile_id, constraint_type, channel,
                          max_length, required_elements, forbidden_elements, template_hints, created_at
            """),
            {
                "tid": str(tenant_id),
                "bpid": str(data.brand_profile_id),
                "constraint_type": data.constraint_type,
                "channel": data.channel,
                "max_length": data.max_length,
                "required_elements": _jsonb(data.required_elements),
                "forbidden_elements": _jsonb(data.forbidden_elements),
                "template_hints": _jsonb(data.template_hints),
            },
        )
        row = result.mappings().first()
        log.info("brand_constraint_created", tenant_id=str(tenant_id), constraint_id=str(row["id"]))
        return dict(row)

    # ─────────────────────────────────────────────────────────────────
    # build_content_brief — 核心方法
    # ─────────────────────────────────────────────────────────────────

    async def build_content_brief(
        self,
        tenant_id: uuid.UUID,
        channel: str,
        target_segment: str,
        purpose: str,
        db: AsyncSession,
    ) -> ContentBrief:
        """生成完整的内容简报，供 content_generation agent 直接消费

        汇聚以下信息：
          1. 品牌档案（brand_voice / price_tier / cuisine_type 等）
          2. 渠道内容约束（max_length / forbidden_elements / template_hints）
          3. 当前节气/节日上下文
          4. 目标客群描述（从 target_segments JSONB 中匹配）
          5. 生成 system_prompt 字符串，可直接注入 LLM

        Args:
            tenant_id: 租户 UUID
            channel:   渠道标识（wechat/miniapp/sms/poster/wecom/douyin/xiaohongshu）
            target_segment: 目标客群名称（如「高价值常客」）
            purpose:   内容目的（如「复购召回」「节日祝福」「新品推介」）
            db:        AsyncSession（已设置 RLS tenant_id）

        Returns:
            ContentBrief 对象
        """
        # 1. 获取品牌档案
        profile = await self.get_active_profile(tenant_id, db)
        if profile is None:
            # 若未配置品牌档案，返回最小化简报
            log.warning("brand_profile_not_found", tenant_id=str(tenant_id))
            return _minimal_brief(tenant_id, channel, target_segment, purpose)

        # 2. 获取渠道约束
        constraints = await self.get_content_constraints(
            tenant_id, channel, db, brand_profile_id=profile["id"]
        )

        # 3. 获取当前节气/节日上下文
        season_ctx = await self.get_current_season_context(tenant_id, db)

        # 4. 解析品牌语气
        brand_voice: dict[str, Any] = profile.get("brand_voice") or {}
        tone: str = brand_voice.get("tone", "温暖亲切")
        style: str = brand_voice.get("style", "短句为主")
        forbidden_words: list[str] = brand_voice.get("forbidden_words", [])
        preferred_words: list[str] = brand_voice.get("preferred_words", [])

        # 5. 合并渠道约束（渠道专属 > 全渠道通用）
        max_length: Optional[int] = None
        required_elements: list[Any] = []
        forbidden_elements: list[Any] = list(forbidden_words)  # 品牌禁忌词也加入
        template_hints: dict[str, Any] = {}

        for c in constraints:
            if c["max_length"] and (max_length is None or c["max_length"] < max_length):
                max_length = c["max_length"]
            required_elements.extend(c.get("required_elements") or [])
            forbidden_elements.extend(c.get("forbidden_elements") or [])
            if c.get("template_hints"):
                template_hints.update(c["template_hints"])

        # 去重
        required_elements = list(dict.fromkeys(required_elements))
        forbidden_elements = list(dict.fromkeys(forbidden_elements))

        # 6. 匹配目标客群描述
        segment_description: Optional[str] = None
        target_segments_data: list[dict] = profile.get("target_segments") or []
        for seg in target_segments_data:
            if seg.get("segment_name") == target_segment:
                segment_description = seg.get("description")
                break

        # 7. 构建 system_prompt
        system_prompt = _build_system_prompt(
            brand_name=profile["brand_name"],
            brand_slogan=profile.get("brand_slogan"),
            cuisine_type=profile.get("cuisine_type"),
            price_tier=profile["price_tier"],
            core_value=profile.get("core_value_proposition"),
            tone=tone,
            style=style,
            forbidden_words=forbidden_words,
            preferred_words=preferred_words,
            channel=channel,
            max_length=max_length,
            required_elements=required_elements,
            forbidden_elements=forbidden_elements,
            template_hints=template_hints,
            target_segment=target_segment,
            segment_description=segment_description,
            purpose=purpose,
            season_ctx=season_ctx,
        )

        log.info(
            "content_brief_built",
            tenant_id=str(tenant_id),
            channel=channel,
            target_segment=target_segment,
            purpose=purpose,
        )

        return ContentBrief(
            tenant_id=tenant_id,
            channel=channel,
            target_segment=target_segment,
            purpose=purpose,
            brand_name=profile["brand_name"],
            brand_slogan=profile.get("brand_slogan"),
            cuisine_type=profile.get("cuisine_type"),
            price_tier=profile["price_tier"],
            core_value_proposition=profile.get("core_value_proposition"),
            tone=tone,
            style=style,
            forbidden_words=forbidden_words,
            preferred_words=preferred_words,
            max_length=max_length,
            required_elements=required_elements,
            forbidden_elements=forbidden_elements,
            template_hints=template_hints,
            current_season_context=season_ctx if season_ctx["has_active_campaign"] or season_ctx["nearest_solar_term"] else None,
            segment_description=segment_description,
            system_prompt=system_prompt,
            generated_at=datetime.now(timezone.utc),
        )


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _jsonb(value: Any) -> str:
    """将 Python 对象序列化为 JSON 字符串，用于 ::jsonb 绑定"""
    import json
    return json.dumps(value, ensure_ascii=False, default=str)


def _minimal_brief(
    tenant_id: uuid.UUID, channel: str, target_segment: str, purpose: str
) -> ContentBrief:
    """未配置品牌档案时返回最小化简报（带通用 system prompt）"""
    return ContentBrief(
        tenant_id=tenant_id,
        channel=channel,
        target_segment=target_segment,
        purpose=purpose,
        brand_name="本品牌",
        brand_slogan=None,
        cuisine_type=None,
        price_tier="mid",
        core_value_proposition=None,
        tone="温暖亲切",
        style="简洁明了",
        forbidden_words=[],
        preferred_words=[],
        max_length=None,
        required_elements=[],
        forbidden_elements=[],
        template_hints={},
        current_season_context=None,
        segment_description=None,
        system_prompt=(
            f"你是一位专业的餐饮品牌文案撰写专家。\n"
            f"请为目标客群「{target_segment}」撰写一则{channel}渠道的{purpose}内容。\n"
            f"风格：温暖亲切，简洁明了。请直接输出文案正文，不要附加说明。"
        ),
        generated_at=datetime.now(timezone.utc),
    )


def _build_system_prompt(
    brand_name: str,
    brand_slogan: Optional[str],
    cuisine_type: Optional[str],
    price_tier: str,
    core_value: Optional[str],
    tone: str,
    style: str,
    forbidden_words: list[str],
    preferred_words: list[str],
    channel: str,
    max_length: Optional[int],
    required_elements: list[Any],
    forbidden_elements: list[Any],
    template_hints: dict[str, Any],
    target_segment: str,
    segment_description: Optional[str],
    purpose: str,
    season_ctx: dict[str, Any],
) -> str:
    """组装注入 LLM 的 system message"""
    price_tier_zh = {
        "budget": "经济实惠（人均50元以下）",
        "mid":    "中等消费（人均50-150元）",
        "upscale": "高档（人均150-500元）",
        "luxury": "奢华（人均500元以上）",
    }.get(price_tier, price_tier)

    lines = [
        f"你是「{brand_name}」品牌的专业文案撰写专家。",
        "",
        "# 品牌基础信息",
        f"- 品牌名称：{brand_name}",
    ]
    if brand_slogan:
        lines.append(f"- 品牌口号：{brand_slogan}")
    if cuisine_type:
        lines.append(f"- 菜系：{cuisine_type}")
    lines.append(f"- 价格带：{price_tier_zh}")
    if core_value:
        lines.append(f"- 核心价值主张：{core_value}")

    lines += [
        "",
        "# 品牌语气要求",
        f"- 语气风格：{tone}",
        f"- 写作风格：{style}",
    ]
    if preferred_words:
        lines.append(f"- 推荐使用词汇：{'、'.join(preferred_words)}")
    if forbidden_words:
        lines.append(f"- 禁止使用词汇：{'、'.join(forbidden_words)}")

    lines += [
        "",
        "# 本次内容生成任务",
        f"- 发布渠道：{channel}",
        f"- 目标客群：{target_segment}",
    ]
    if segment_description:
        lines.append(f"- 客群描述：{segment_description}")
    lines.append(f"- 内容目的：{purpose}")
    if max_length:
        lines.append(f"- 最大字数限制：{max_length} 字")

    if required_elements:
        lines.append(f"- 必须包含：{'、'.join(str(e) for e in required_elements)}")
    if forbidden_elements:
        lines.append(f"- 禁止出现：{'、'.join(str(e) for e in forbidden_elements)}")

    if template_hints:
        lines += ["", "# 内容模板参考"]
        for k, v in template_hints.items():
            if isinstance(v, list):
                lines.append(f"- {k}：{'、'.join(str(i) for i in v)}")
            else:
                lines.append(f"- {k}：{v}")

    # 节气/节日上下文
    active_campaigns = season_ctx.get("active_campaigns", [])
    nearest_term = season_ctx.get("nearest_solar_term", {})

    if active_campaigns:
        camp = active_campaigns[0]
        lines += [
            "",
            "# 当前营销节点",
            f"- 节点名称：{camp.get('period_name', '')}",
            f"- 营销主题：{camp.get('campaign_theme', '')}",
        ]
        if camp.get("marketing_focus"):
            lines.append(f"- 主推方向：{camp['marketing_focus']}")
    elif nearest_term:
        lines += [
            "",
            "# 当前节气参考",
            f"- 最近节气：{nearest_term.get('name', '')}（{nearest_term.get('days_delta', 0)} 天内）",
            f"- 营销提示：{nearest_term.get('hint', '')}",
        ]

    lines += [
        "",
        "# 输出要求",
        "请直接输出文案正文，不要添加任何前缀说明或标注。",
        "确保内容符合品牌调性，不出现任何禁止词汇。",
    ]

    return "\n".join(lines)
