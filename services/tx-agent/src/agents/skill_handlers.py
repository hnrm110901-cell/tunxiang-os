"""Skill-aware 事件处理器

SkillEventConsumer 路由到这里的 handler，职责：
1. 判断事件是否需要 Agent 介入（简单事件直接处理，复杂事件交给 Orchestrator）
2. 调用对应的 Skill Agent 或业务逻辑
3. 记录处理结果

设计原则：handler 必须是幂等的，失败不影响主业务流程。
"""

import os

import httpx
import structlog

logger = structlog.get_logger(__name__)

_ORG_URL = os.getenv("TX_ORG_SERVICE_URL", "http://tx-org:8012")


async def handle_order_skill_events(skill_name: str, event_type: str, payload: dict) -> None:
    """处理 order-core Skill 的事件。

    监听事件：
    - order.checkout.completed：检查押金和存酒信息
    - order.paid：记录支付完成日志（后续可触发积分计算）
    """
    try:
        if event_type == "order.checkout.completed":
            order_id = payload.get("order_id", "")
            store_id = payload.get("store_id", "")
            has_deposit = payload.get("has_deposit", False)
            remaining_drinks = payload.get("remaining_drinks")

            log = logger.bind(
                skill=skill_name,
                event_type=event_type,
                order_id=order_id,
                store_id=store_id,
            )

            if has_deposit:
                log.info(
                    "order_checkout_deposit_check_required",
                    msg="订单含押金，触发押金检查",
                    deposit_amount=payload.get("deposit_amount"),
                )

            if remaining_drinks is not None and remaining_drinks > 0:
                log.info(
                    "order_checkout_wine_storage_hint",
                    msg="订单含剩余酒水，触发存酒提示",
                    remaining_drinks=remaining_drinks,
                )

            log.info("order_checkout_completed_handled")

        elif event_type == "order.paid":
            logger.info(
                "order_paid_received",
                skill=skill_name,
                event_type=event_type,
                order_id=payload.get("order_id", ""),
                store_id=payload.get("store_id", ""),
                total_fen=payload.get("total_fen"),
                msg="订单支付完成，后续可触发积分计算",
            )

        else:
            logger.debug(
                "order_skill_event_unhandled",
                skill=skill_name,
                event_type=event_type,
            )

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "handle_order_skill_events_failed",
            skill=skill_name,
            event_type=event_type,
            error=str(exc),
        )


async def handle_member_skill_events(skill_name: str, event_type: str, payload: dict) -> None:
    """处理 member-core Skill 的事件。

    监听事件：
    - member.tier.changed：会员等级变化（高级等级自动延期 wine-storage）
    - member.stored_value.low：储值余额不足告警
    """
    try:
        if event_type == "member.tier.changed":
            member_id = payload.get("member_id", "")
            new_tier = payload.get("new_tier", "")
            old_tier = payload.get("old_tier", "")

            premium_tiers = {"gold", "platinum", "diamond"}
            if new_tier in premium_tiers:
                logger.info(
                    "member_tier_upgraded_premium",
                    skill=skill_name,
                    event_type=event_type,
                    member_id=member_id,
                    old_tier=old_tier,
                    new_tier=new_tier,
                    msg="会员升至高级等级，wine-storage 将自动延期",
                )
            else:
                logger.info(
                    "member_tier_changed",
                    skill=skill_name,
                    event_type=event_type,
                    member_id=member_id,
                    old_tier=old_tier,
                    new_tier=new_tier,
                )

        elif event_type == "member.stored_value.low":
            member_id = payload.get("member_id", "")
            balance_fen = payload.get("balance_fen")
            threshold_fen = payload.get("threshold_fen")

            logger.warning(
                "member_stored_value_low_alert",
                skill=skill_name,
                event_type=event_type,
                member_id=member_id,
                balance_fen=balance_fen,
                threshold_fen=threshold_fen,
                msg="会员储值余额不足告警",
            )

        else:
            logger.debug(
                "member_skill_event_unhandled",
                skill=skill_name,
                event_type=event_type,
            )

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "handle_member_skill_events_failed",
            skill=skill_name,
            event_type=event_type,
            error=str(exc),
        )


async def handle_inventory_skill_events(skill_name: str, event_type: str, payload: dict) -> None:
    """处理 inventory-core Skill 的事件。

    监听事件：
    - inventory.ingredient.low：食材库存不足告警
    - inventory.ingredient.expired：食材过期告警（触发食安约束检查）
    """
    try:
        if event_type == "inventory.ingredient.low":
            ingredient_id = payload.get("ingredient_id", "")
            current_qty = payload.get("current_qty")
            threshold_qty = payload.get("threshold_qty")
            store_id = payload.get("store_id", "")

            logger.warning(
                "inventory_ingredient_low_alert",
                skill=skill_name,
                event_type=event_type,
                ingredient_id=ingredient_id,
                store_id=store_id,
                current_qty=current_qty,
                threshold_qty=threshold_qty,
                msg="食材库存低于阈值，需及时补货",
            )

        elif event_type == "inventory.ingredient.expired":
            ingredient_id = payload.get("ingredient_id", "")
            ingredient_name = payload.get("ingredient_name", "")
            store_id = payload.get("store_id", "")
            expired_at = payload.get("expired_at", "")

            logger.error(
                "inventory_ingredient_expired_alert",
                skill=skill_name,
                event_type=event_type,
                ingredient_id=ingredient_id,
                ingredient_name=ingredient_name,
                store_id=store_id,
                expired_at=expired_at,
                msg="检测到过期食材，触发食安约束检查（硬约束：食安合规）",
            )

        else:
            logger.debug(
                "inventory_skill_event_unhandled",
                skill=skill_name,
                event_type=event_type,
            )

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "handle_inventory_skill_events_failed",
            skill=skill_name,
            event_type=event_type,
            error=str(exc),
        )


async def handle_safety_skill_events(skill_name: str, event_type: str, payload: dict) -> None:
    """处理 safety-compliance Skill 的事件。

    监听事件：
    - safety.inspection.failed：食安检查不合格（硬约束违反！）
    - safety.critical_item.failed：关键食安项目不合格（最高优先级）
    """
    try:
        if event_type == "safety.inspection.failed":
            inspection_id = payload.get("inspection_id", "")
            store_id = payload.get("store_id", "")
            failed_items = payload.get("failed_items", [])
            inspector = payload.get("inspector", "")

            logger.critical(
                "safety_inspection_failed_alert",
                skill=skill_name,
                event_type=event_type,
                inspection_id=inspection_id,
                store_id=store_id,
                failed_items_count=len(failed_items) if isinstance(failed_items, list) else 0,
                inspector=inspector,
                msg="食安检查不合格！这是硬约束违反，需立即处理",
            )

        elif event_type == "safety.critical_item.failed":
            item_id = payload.get("item_id", "")
            item_name = payload.get("item_name", "")
            store_id = payload.get("store_id", "")
            violation_type = payload.get("violation_type", "")

            logger.critical(
                "safety_critical_item_failed_alert",
                skill=skill_name,
                event_type=event_type,
                item_id=item_id,
                item_name=item_name,
                store_id=store_id,
                violation_type=violation_type,
                msg="关键食安项目不合格！最高优先级处理，食安合规硬约束被触发",
            )

        else:
            logger.debug(
                "safety_skill_event_unhandled",
                skill=skill_name,
                event_type=event_type,
            )

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "handle_safety_skill_events_failed",
            skill=skill_name,
            event_type=event_type,
            error=str(exc),
        )


async def handle_finance_skill_events(skill_name: str, event_type: str, payload: dict) -> None:
    """处理财务类 Skill 的事件（deposit/wine_storage/credit）。

    监听事件：
    - deposit.collected：押金收取记录
    - credit.limit_warning：挂账额度预警
    - credit.overdue：挂账逾期告警
    """
    try:
        if event_type == "deposit.collected":
            deposit_id = payload.get("deposit_id", "")
            order_id = payload.get("order_id", "")
            amount_fen = payload.get("amount_fen")
            store_id = payload.get("store_id", "")

            logger.info(
                "deposit_collected_recorded",
                skill=skill_name,
                event_type=event_type,
                deposit_id=deposit_id,
                order_id=order_id,
                amount_fen=amount_fen,
                store_id=store_id,
                msg="押金收取记录成功",
            )

        elif event_type == "credit.limit_warning":
            customer_id = payload.get("customer_id", "")
            store_id = payload.get("store_id", "")
            used_fen = payload.get("used_fen")
            limit_fen = payload.get("limit_fen")
            usage_ratio = payload.get("usage_ratio")

            logger.warning(
                "credit_limit_warning_alert",
                skill=skill_name,
                event_type=event_type,
                customer_id=customer_id,
                store_id=store_id,
                used_fen=used_fen,
                limit_fen=limit_fen,
                usage_ratio=usage_ratio,
                msg="挂账额度接近上限，请注意风险控制",
            )

        elif event_type == "credit.overdue":
            customer_id = payload.get("customer_id", "")
            store_id = payload.get("store_id", "")
            overdue_fen = payload.get("overdue_fen")
            overdue_days = payload.get("overdue_days")

            logger.error(
                "credit_overdue_alert",
                skill=skill_name,
                event_type=event_type,
                customer_id=customer_id,
                store_id=store_id,
                overdue_fen=overdue_fen,
                overdue_days=overdue_days,
                msg="挂账逾期告警，需催收处理",
            )

        else:
            logger.debug(
                "finance_skill_event_unhandled",
                skill=skill_name,
                event_type=event_type,
            )

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "handle_finance_skill_events_failed",
            skill=skill_name,
            event_type=event_type,
            error=str(exc),
        )


async def handle_approval_skill_events(skill_name: str, event_type: str, payload: dict) -> None:
    """处理 approval-flow Skill 的事件。

    监听事件：
    - approval.requested：任何业务Skill发起审批请求时，自动在 approval_engine 创建实例
    """
    try:
        if event_type != "approval.requested":
            logger.debug(
                "approval_skill_event_unhandled",
                skill=skill_name,
                event_type=event_type,
            )
            return

        biz_type = payload.get("approval_type", "custom")
        biz_ref_id = payload.get("subject_id", "")
        applicant_id = payload.get("requested_by", "")
        tenant_id = payload.get("tenant_id", "")
        context = {k: v for k, v in payload.items() if k not in ("approval_type", "requested_by", "tenant_id")}

        log = logger.bind(
            skill=skill_name,
            event_type=event_type,
            biz_type=biz_type,
            biz_ref_id=biz_ref_id,
            tenant_id=tenant_id,
        )
        log.info("approval_requested_received", msg="收到审批请求，自动创建审批实例")

        headers = {"X-Tenant-ID": tenant_id, "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: 按 biz_type 查找激活的模板，取第一个
            tpl_resp = await client.get(
                f"{_ORG_URL}/api/v1/approval-engine/templates",
                params={"business_type": biz_type},
                headers=headers,
            )
            template_id: str | None = None
            if tpl_resp.status_code == 200:
                items = tpl_resp.json().get("data", {}).get("items", [])
                active = [t for t in items if t.get("is_active")]
                if active:
                    template_id = active[0]["id"]
                    log.info("approval_template_found", template_id=template_id)
                else:
                    log.warning(
                        "approval_template_not_found",
                        biz_type=biz_type,
                        msg="未找到激活模板，approval_engine 将使用默认模板",
                    )
            else:
                log.warning(
                    "approval_template_query_failed",
                    status_code=tpl_resp.status_code,
                )

            # Step 2: 创建审批实例（template_id 存在时传入，否则由引擎使用默认）
            body: dict = {
                "biz_type": biz_type,
                "biz_ref_id": biz_ref_id,
                "applicant_id": applicant_id,
                "context": context,
            }
            if template_id:
                body["template_id"] = template_id

            inst_resp = await client.post(
                f"{_ORG_URL}/api/v1/approval-engine/instances",
                json=body,
                headers=headers,
            )

        if inst_resp.status_code >= 400:
            log.warning(
                "approval_instance_create_failed",
                status_code=inst_resp.status_code,
                response=inst_resp.text[:200],
            )
        else:
            instance_id = inst_resp.json().get("data", {}).get("id", "")
            log.info(
                "approval_instance_created",
                instance_id=instance_id,
                template_id=template_id,
                msg="审批实例创建成功",
            )

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "handle_approval_skill_events_failed",
            skill=skill_name,
            event_type=event_type,
            error=str(exc),
        )
    except httpx.HTTPError as exc:
        logger.error(
            "approval_engine_http_error",
            skill=skill_name,
            event_type=event_type,
            error=str(exc),
        )
