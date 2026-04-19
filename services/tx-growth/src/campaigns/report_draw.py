"""报名抽奖

典型场景: 活动报名后参与抽奖, 抽取免单/大额优惠
区别于 lottery(即时抽奖), 本模板是先报名再统一开奖。

持久化: campaign_report_entries 表（v207 迁移创建）
"""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import _set_tenant_on_session

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "prizes", "draw_time"],
    "properties": {
        "name": {"type": "string"},
        "draw_time": {"type": "string", "description": "开奖时间 ISO8601"},
        "max_participants": {"type": "integer", "default": 0, "description": "最大报名人数(0=不限)"},
        "prizes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["prize_id", "name", "winner_count"],
                "properties": {
                    "prize_id": {"type": "string"},
                    "name": {"type": "string"},
                    "winner_count": {"type": "integer", "description": "中奖人数"},
                    "reward": {"type": "object"},
                },
            },
        },
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行报名或开奖。

    Args:
        customer_id:   顾客ID
        config:        活动配置（含 prizes/max_participants 等）
        trigger_event: 触发事件（含 campaign_id 和 action）
        tenant_id:     租户ID
        db:            AsyncSession（持久化时必传）

    Returns:
        执行结果字典
    """
    campaign_id = trigger_event.get("campaign_id", "")
    action = trigger_event.get("action", "report")

    if db is None:
        log.warning(
            "report_draw.no_db_session",
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            action=action,
        )
        return {"success": False, "reason": "数据库会话未提供，无法持久化报名数据"}

    if action == "report":
        return await _handle_report(
            customer_id=customer_id,
            campaign_id=campaign_id,
            config=config,
            tenant_id=tenant_id,
            db=db,
        )

    if action == "draw":
        return await _handle_draw(
            campaign_id=campaign_id,
            config=config,
            tenant_id=tenant_id,
            db=db,
        )

    return {"success": False, "reason": f"未知操作: {action}"}


async def _handle_report(
    customer_id: str,
    campaign_id: str,
    config: dict,
    tenant_id: str,
    db: Any,
) -> dict:
    """处理报名逻辑 — 写入 campaign_report_entries。"""
    # 设置 RLS 上下文
    try:
        await _set_tenant_on_session(db, tenant_id)
    except SQLAlchemyError as exc:
        log.error("report_draw.rls_setup_failed", error=str(exc), exc_info=True)
        return {"success": False, "reason": "数据库配置失败"}

    # 检查已报名
    try:
        exists_res = await db.execute(
            text("""
                SELECT id FROM campaign_report_entries
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                  AND customer_id = :customer_id
                  AND is_deleted = false
                LIMIT 1
            """),
            {
                "tenant_id": uuid.UUID(tenant_id),
                "campaign_id": campaign_id,
                "customer_id": customer_id,
            },
        )
        if exists_res.fetchone():
            return {"success": False, "reason": "已报名"}
    except SQLAlchemyError as exc:
        log.error("report_draw.check_exists_failed", error=str(exc), exc_info=True)
        return {"success": False, "reason": "数据库查询失败"}

    # 检查报名人数上限
    max_p = config.get("max_participants", 0)
    if max_p > 0:
        try:
            count_res = await db.execute(
                text("""
                    SELECT COUNT(*) FROM campaign_report_entries
                    WHERE tenant_id = :tenant_id
                      AND campaign_id = :campaign_id
                      AND is_deleted = false
                """),
                {
                    "tenant_id": uuid.UUID(tenant_id),
                    "campaign_id": campaign_id,
                },
            )
            current_count = count_res.scalar() or 0
            if current_count >= max_p:
                return {"success": False, "reason": "报名人数已满"}
        except SQLAlchemyError as exc:
            log.error("report_draw.count_check_failed", error=str(exc), exc_info=True)
            return {"success": False, "reason": "数据库查询失败"}

    # 写入报名记录
    try:
        entry_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO campaign_report_entries
                    (id, tenant_id, campaign_id, customer_id, is_winner, is_deleted)
                VALUES
                    (:id, :tenant_id, :campaign_id, :customer_id, false, false)
            """),
            {
                "id": entry_id,
                "tenant_id": uuid.UUID(tenant_id),
                "campaign_id": campaign_id,
                "customer_id": customer_id,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("report_draw.insert_failed", error=str(exc), exc_info=True)
        return {"success": False, "reason": "报名写入失败"}

    # 返回当前报名人数（作为 position）
    try:
        pos_res = await db.execute(
            text("""
                SELECT COUNT(*) FROM campaign_report_entries
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                  AND is_deleted = false
            """),
            {
                "tenant_id": uuid.UUID(tenant_id),
                "campaign_id": campaign_id,
            },
        )
        position = pos_res.scalar() or 1
    except SQLAlchemyError:
        log.warning("report_draw.count_position_failed", exc_info=True)
        position = 1

    log.info(
        "campaign.report_draw.reported",
        customer_id=customer_id,
        campaign_id=campaign_id,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "action": "reported",
        "position": position,
    }


async def _handle_draw(
    campaign_id: str,
    config: dict,
    tenant_id: str,
    db: Any,
) -> dict:
    """处理开奖逻辑 — 从 campaign_report_entries 读取报名列表并随机抽奖。"""
    # 设置 RLS 上下文
    try:
        await _set_tenant_on_session(db, tenant_id)
    except SQLAlchemyError as exc:
        log.error("report_draw.rls_setup_failed", error=str(exc), exc_info=True)
        return {"success": False, "reason": "数据库配置失败"}

    prizes = config.get("prizes", [])
    if not prizes:
        return {"success": False, "reason": "奖项配置为空"}

    # 统计参与人数，判断是否有人报名
    try:
        count_res = await db.execute(
            text("""
                SELECT COUNT(*) FROM campaign_report_entries
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                  AND is_winner = false
                  AND drawn_at IS NULL
                  AND is_deleted = false
            """),
            {"tenant_id": uuid.UUID(tenant_id), "campaign_id": campaign_id},
        )
        total_entries: int = count_res.scalar() or 0
    except SQLAlchemyError as exc:
        log.error("report_draw.count_entries_failed", error=str(exc), exc_info=True)
        return {"success": False, "reason": "数据库查询失败"}

    if total_entries == 0:
        return {"success": False, "reason": "无人报名"}

    winners: list[dict] = []

    # 每个奖项做一次数据库端随机采样，避免全量拉取到 Python 内存
    # 使用 SELECT ... FOR UPDATE 防止并发开奖抽到同一人
    for prize in prizes:
        prize_count = min(prize.get("winner_count", 1), total_entries - len(winners))
        if prize_count <= 0:
            continue
        try:
            exclude_ids = [uuid.UUID(w["entry_id"]) for w in winners] if winners else []
            rows_res = await db.execute(
                text("""
                    SELECT id, customer_id FROM campaign_report_entries
                    WHERE tenant_id = :tenant_id
                      AND campaign_id = :campaign_id
                      AND is_winner = false
                      AND drawn_at IS NULL
                      AND is_deleted = false
                      AND NOT (id = ANY(:exclude_ids))
                    ORDER BY random()
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                """),
                {
                    "tenant_id": uuid.UUID(tenant_id),
                    "campaign_id": campaign_id,
                    "exclude_ids": exclude_ids,
                    "limit": prize_count,
                },
            )
            for row in rows_res.fetchall():
                winners.append({"entry_id": str(row[0]), "customer_id": row[1], "prize": prize})
        except SQLAlchemyError as exc:
            log.error("report_draw.sample_entries_failed", error=str(exc), exc_info=True)
            return {"success": False, "reason": "数据库随机抽取失败"}

    # 批量 UPDATE 中奖记录 — 逐条参数化更新，避免 SQL 注入
    if winners:
        try:
            for w in winners:
                prize_json = json.dumps(w["prize"], ensure_ascii=False)
                await db.execute(
                    text("""
                        UPDATE campaign_report_entries
                        SET is_winner = true,
                            prize = :prize::jsonb,
                            drawn_at = NOW(),
                            updated_at = NOW()
                        WHERE id = :entry_id
                          AND tenant_id = :tenant_id
                    """),
                    {
                        "entry_id": uuid.UUID(w["entry_id"]),
                        "prize": prize_json,
                        "tenant_id": uuid.UUID(tenant_id),
                    },
                )
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            log.error("report_draw.update_winners_failed", error=str(exc), exc_info=True)
            return {"success": False, "reason": "开奖结果写入失败"}

    log.info(
        "campaign.report_draw.drawn",
        campaign_id=campaign_id,
        winners_count=len(winners),
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "action": "drawn",
        "total_participants": total_entries,
        "winners": [{"customer_id": w["customer_id"], "prize": w["prize"]} for w in winners],
    }
