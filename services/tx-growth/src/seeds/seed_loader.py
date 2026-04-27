"""种子数据加载器 — 初始化系统旅程模板和触达模板

幂等加载: ON CONFLICT DO NOTHING，可重复执行。
加载顺序: 先加载触达模板（被旅程步骤引用），再加载旅程模板和步骤。
"""

import json

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .growth_journey_seeds import SYSTEM_JOURNEY_TEMPLATES
from .growth_touch_seeds import SYSTEM_TOUCH_TEMPLATES

logger = structlog.get_logger(__name__)


async def seed_growth_templates(tenant_id: str, db: AsyncSession) -> dict:
    """为指定租户加载系统旅程模板和触达模板（幂等，ON CONFLICT DO NOTHING）

    Args:
        tenant_id: 租户ID
        db: 异步数据库会话

    Returns:
        {"touch_loaded": int, "journey_loaded": int} 实际新增的模板数量
    """
    # 设置 RLS 租户上下文
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

    # 1. 加载触达模板（旅程步骤会引用触达模板，所以先加载）
    touch_loaded = 0
    for tmpl in SYSTEM_TOUCH_TEMPLATES:
        result = await db.execute(
            text("""
                INSERT INTO growth_touch_templates
                    (tenant_id, code, name, template_family, mechanism_type, channel, tone,
                     content_template, variables_schema_json, forbidden_phrases_json,
                     requires_human_review, is_system, is_active)
                VALUES
                    (:tenant_id, :code, :name, :template_family, :mechanism_type, :channel, :tone,
                     :content_template, :variables_schema_json::jsonb, :forbidden_phrases_json::jsonb,
                     :requires_human_review, TRUE, TRUE)
                ON CONFLICT (tenant_id, code) DO NOTHING
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "code": tmpl["code"],
                "name": tmpl["name"],
                "template_family": tmpl["template_family"],
                "mechanism_type": tmpl["mechanism_type"],
                "channel": tmpl["channel"],
                "tone": tmpl["tone"],
                "content_template": tmpl["content_template"],
                "variables_schema_json": json.dumps(tmpl["variables_schema_json"], ensure_ascii=False),
                "forbidden_phrases_json": json.dumps(tmpl["forbidden_phrases_json"], ensure_ascii=False),
                "requires_human_review": tmpl["requires_human_review"],
            },
        )
        if result.fetchone():
            touch_loaded += 1

    # 2. 加载旅程模板及步骤
    journey_loaded = 0
    for jtmpl in SYSTEM_JOURNEY_TEMPLATES:
        # 取出steps（不修改原始数据）
        steps = jtmpl.get("steps", [])

        # 插入旅程模板
        result = await db.execute(
            text("""
                INSERT INTO growth_journey_templates
                    (tenant_id, code, name, journey_type, mechanism_family,
                     entry_rule_json, exit_rule_json, pause_rule_json,
                     priority, is_system, is_active)
                VALUES
                    (:tenant_id, :code, :name, :journey_type, :mechanism_family,
                     :entry_rule_json::jsonb, :exit_rule_json::jsonb, :pause_rule_json::jsonb,
                     :priority, TRUE, TRUE)
                ON CONFLICT (tenant_id, code) DO NOTHING
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "code": jtmpl["code"],
                "name": jtmpl["name"],
                "journey_type": jtmpl["journey_type"],
                "mechanism_family": jtmpl["mechanism_family"],
                "entry_rule_json": json.dumps(jtmpl["entry_rule_json"], ensure_ascii=False),
                "exit_rule_json": json.dumps(jtmpl["exit_rule_json"], ensure_ascii=False),
                "pause_rule_json": json.dumps(jtmpl.get("pause_rule_json", {}), ensure_ascii=False),
                "priority": jtmpl.get("priority", 100),
            },
        )
        row = result.fetchone()
        if row:
            journey_loaded += 1
            template_id = str(row[0])

            # 插入旅程步骤
            for step in steps:
                await db.execute(
                    text("""
                        INSERT INTO growth_journey_template_steps
                            (tenant_id, journey_template_id, step_no, step_type, mechanism_type,
                             wait_minutes, decision_rule_json, offer_rule_json, touch_template_id,
                             observe_window_hours, success_next_step_no, fail_next_step_no, skip_next_step_no)
                        VALUES
                            (:tenant_id, :template_id::uuid, :step_no, :step_type, :mechanism_type,
                             :wait_minutes, :decision_rule_json::jsonb, :offer_rule_json::jsonb,
                             (SELECT id FROM growth_touch_templates
                              WHERE tenant_id = :tenant_id AND code = :touch_code LIMIT 1),
                             :observe_window_hours, :success_next, :fail_next, :skip_next)
                    """),
                    {
                        "tenant_id": tenant_id,
                        "template_id": template_id,
                        "step_no": step["step_no"],
                        "step_type": step["step_type"],
                        "mechanism_type": step.get("mechanism_type"),
                        "wait_minutes": step.get("wait_minutes"),
                        "decision_rule_json": json.dumps(step["decision_rule_json"], ensure_ascii=False)
                        if step.get("decision_rule_json")
                        else None,
                        "offer_rule_json": json.dumps(step["offer_rule_json"], ensure_ascii=False)
                        if step.get("offer_rule_json")
                        else None,
                        "touch_code": step.get("touch_template_code"),
                        "observe_window_hours": step.get("observe_window_hours"),
                        "success_next": step.get("success_next_step_no"),
                        "fail_next": step.get("fail_next_step_no"),
                        "skip_next": step.get("skip_next_step_no"),
                    },
                )

    logger.info(
        "growth_seeds_loaded",
        tenant_id=tenant_id,
        touch_loaded=touch_loaded,
        journey_loaded=journey_loaded,
    )
    return {"touch_loaded": touch_loaded, "journey_loaded": journey_loaded}
