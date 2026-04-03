"""食安合规与追溯中心 -- 食品安全全链路管理

硬约束：过期食材 = 绝对禁止出品，无例外。
留样规则：至少保留 48 小时。
温控标准：冷藏 0-4C, 冷冻 <-18C, 热链 >60C。
食安事件：severity=critical 时自动通知区域经理。
"""
import asyncio
import json
import uuid
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import SupplyEventType, UniversalPublisher
from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import TransactionType

logger = structlog.get_logger()


# ─── 常量 ───


SAMPLE_RETENTION_HOURS = 48

TEMP_THRESHOLDS = {
    "cold_storage": {"min": 0.0, "max": 4.0, "label": "冷藏"},
    "freezer": {"min": -999.0, "max": -18.0, "label": "冷冻"},
    "hot_chain": {"min": 60.0, "max": 999.0, "label": "热链"},
}


class EventSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


# ─── 内部工具 ───


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _parse_notes(notes: Optional[str]) -> dict:
    if not notes:
        return {}
    try:
        return json.loads(notes)
    except (json.JSONDecodeError, TypeError):
        return {}


def _check_temperature(location: str, temperature: float) -> dict:
    """检查温度是否在合规范围内"""
    threshold = TEMP_THRESHOLDS.get(location)
    if not threshold:
        return {"compliant": True, "message": "未知区域，跳过校验"}

    compliant = threshold["min"] <= temperature <= threshold["max"]
    message = (
        f"{threshold['label']}温度合规"
        if compliant
        else (
            f"{threshold['label']}温度异常: {temperature}C, "
            f"允许范围 {threshold['min']}~{threshold['max']}C"
        )
    )
    return {
        "compliant": compliant,
        "location": location,
        "temperature": temperature,
        "threshold": threshold,
        "message": message,
    }


async def _notify_regional_manager(
    store_id: str, event_type: str, detail: str, tenant_id: str,
) -> None:
    """severity=critical 时通知区域经理（异步推送占位）"""
    logger.critical(
        "food_safety_critical_event_notify",
        store_id=store_id,
        event_type=event_type,
        detail=detail,
        tenant_id=tenant_id,
        action="notify_regional_manager",
    )
    # 发布到 supply_events Redis Stream，区域经理端和告警 Worker 消费该事件
    asyncio.create_task(
        UniversalPublisher.publish(
            event_type=SupplyEventType.INGREDIENT_EXPIRED,
            tenant_id=UUID(tenant_id),
            store_id=UUID(store_id),
            entity_id=None,
            event_data={"event_type": event_type, "detail": detail, "severity": "critical"},
            source_service="tx-supply",
        )
    )


# ─── 核心服务函数 ───


async def block_expired_ingredient(
    ingredient_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """禁用过期原料 -- 不可出品（硬约束）

    将原料标记为 is_deleted=True，并记录禁用原因。
    过期 = 绝对禁止出品，无例外。
    """
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)
    sid = _uuid(store_id)
    iid = _uuid(ingredient_id)

    result = await db.execute(
        select(Ingredient).where(
            Ingredient.tenant_id == tid,
            Ingredient.store_id == sid,
            Ingredient.id == iid,
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    ingredient = result.scalars().first()

    if not ingredient:
        logger.warning(
            "block_expired_ingredient_not_found",
            ingredient_id=ingredient_id,
            store_id=store_id,
            tenant_id=tenant_id,
        )
        return {"blocked": False, "reason": "原料不存在或已禁用"}

    # 标记为删除（禁用）
    ingredient.is_deleted = True
    await db.flush()

    logger.warning(
        "expired_ingredient_blocked",
        ingredient_id=ingredient_id,
        ingredient_name=ingredient.ingredient_name,
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return {
        "blocked": True,
        "ingredient_id": ingredient_id,
        "ingredient_name": ingredient.ingredient_name,
        "reason": "过期原料已禁用，不可出品",
    }


async def check_banned_ingredients(
    order_items: list[dict],
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """检查订单中是否包含禁用食材

    Args:
        order_items: [{"ingredient_id": str, "name": str, ...}, ...]

    Returns:
        {"passed": bool, "banned_items": [...]}
    """
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)
    sid = _uuid(store_id)

    if not order_items:
        return {"passed": True, "banned_items": []}

    ingredient_ids = [
        _uuid(item["ingredient_id"])
        for item in order_items
        if item.get("ingredient_id")
    ]
    if not ingredient_ids:
        return {"passed": True, "banned_items": []}

    # 查询已删除（禁用）的原料
    result = await db.execute(
        select(Ingredient).where(
            Ingredient.tenant_id == tid,
            Ingredient.store_id == sid,
            Ingredient.id.in_(ingredient_ids),
            Ingredient.is_deleted == True,  # noqa: E712
        )
    )
    banned = result.scalars().all()

    banned_items = [
        {
            "ingredient_id": str(b.id),
            "ingredient_name": b.ingredient_name,
            "reason": "食材已被禁用（过期/食安问题）",
        }
        for b in banned
    ]

    passed = len(banned_items) == 0

    if not passed:
        logger.warning(
            "banned_ingredients_detected",
            store_id=store_id,
            banned_count=len(banned_items),
            tenant_id=tenant_id,
        )

    return {"passed": passed, "banned_items": banned_items}


async def trace_batch(
    batch_no: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """批次追溯：供应商 -> 入库 -> 领用 -> 出品 -> 客户

    全链路追溯某个批次号的流转记录。
    """
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)

    # 查询该批次所有事务
    result = await db.execute(
        select(IngredientTransaction).where(
            IngredientTransaction.tenant_id == tid,
            IngredientTransaction.reference_id == batch_no,
            IngredientTransaction.is_deleted == False,  # noqa: E712
        ).order_by(IngredientTransaction.created_at.asc())
    )
    transactions = result.scalars().all()

    if not transactions:
        return {
            "batch_no": batch_no,
            "found": False,
            "trace": [],
            "summary": "未找到该批次记录",
        }

    trace = []
    for txn in transactions:
        notes_data = _parse_notes(txn.notes)
        trace.append({
            "transaction_id": str(txn.id),
            "transaction_type": txn.transaction_type,
            "ingredient_id": str(txn.ingredient_id),
            "store_id": str(txn.store_id),
            "quantity": float(txn.quantity),
            "performed_by": notes_data.get("performed_by"),
            "supplier": notes_data.get("supplier"),
            "expiry_date": notes_data.get("expiry_date"),
            "created_at": txn.created_at.isoformat() if txn.created_at else None,
            "notes": notes_data,
        })

    # 按事务类型分组汇总
    type_summary = {}
    for t in trace:
        tt = t["transaction_type"]
        type_summary.setdefault(tt, {"count": 0, "total_quantity": 0.0})
        type_summary[tt]["count"] += 1
        type_summary[tt]["total_quantity"] += t["quantity"]

    logger.info(
        "batch_traced",
        batch_no=batch_no,
        transaction_count=len(trace),
        tenant_id=tenant_id,
    )

    return {
        "batch_no": batch_no,
        "found": True,
        "trace": trace,
        "type_summary": type_summary,
        "summary": f"批次 {batch_no} 共 {len(trace)} 条流转记录",
    }


def record_sample(
    store_id: str,
    dish_id: str,
    sample_time: datetime,
    photo_url: str,
    operator_id: str,
    tenant_id: str,
) -> dict:
    """留样记录

    留样规则：至少保留 48 小时。
    返回留样记录及过期时间。

    注：此函数为纯计算+日志，不直接写 DB。
    实际存储由调用方完成（写入留样表或 JSON 文档库）。
    """
    retention_until = sample_time + timedelta(hours=SAMPLE_RETENTION_HOURS)
    now = datetime.now()
    is_within_retention = now < retention_until

    record = {
        "store_id": store_id,
        "dish_id": dish_id,
        "sample_time": sample_time.isoformat(),
        "retention_until": retention_until.isoformat(),
        "retention_hours": SAMPLE_RETENTION_HOURS,
        "photo_url": photo_url,
        "operator_id": operator_id,
        "tenant_id": tenant_id,
        "is_within_retention": is_within_retention,
    }

    logger.info(
        "food_sample_recorded",
        store_id=store_id,
        dish_id=dish_id,
        operator_id=operator_id,
        retention_until=retention_until.isoformat(),
        tenant_id=tenant_id,
    )
    return record


def record_temperature(
    store_id: str,
    location: str,
    temperature: float,
    operator_id: str,
    tenant_id: str,
) -> dict:
    """温控记录

    温控标准：
      - 冷藏 (cold_storage): 0-4C
      - 冷冻 (freezer): <-18C
      - 热链 (hot_chain): >60C

    返回温度记录及合规状态。
    """
    check = _check_temperature(location, temperature)
    record = {
        "store_id": store_id,
        "location": location,
        "temperature": temperature,
        "operator_id": operator_id,
        "tenant_id": tenant_id,
        "recorded_at": datetime.now().isoformat(),
        **check,
    }

    if not check["compliant"]:
        logger.warning(
            "temperature_out_of_range",
            store_id=store_id,
            location=location,
            temperature=temperature,
            tenant_id=tenant_id,
        )
    else:
        logger.info(
            "temperature_recorded",
            store_id=store_id,
            location=location,
            temperature=temperature,
            tenant_id=tenant_id,
        )
    return record


def get_compliance_checklist(
    store_id: str,
    check_date: date,
    tenant_id: str,
) -> dict:
    """合规检查表

    返回门店当日需要完成的食安合规检查项目清单。
    """
    checklist = [
        {
            "item": "晨检",
            "description": "员工健康晨检（体温、手部伤口、传染病症状）",
            "required": True,
            "frequency": "每日开餐前",
        },
        {
            "item": "冷藏温控",
            "description": "冷藏库温度检查 (0-4C)",
            "required": True,
            "frequency": "每日 2 次（开餐前 + 午后）",
        },
        {
            "item": "冷冻温控",
            "description": "冷冻库温度检查 (<-18C)",
            "required": True,
            "frequency": "每日 2 次",
        },
        {
            "item": "热链温控",
            "description": "保温设备温度检查 (>60C)",
            "required": True,
            "frequency": "供餐期间每 30 分钟",
        },
        {
            "item": "留样",
            "description": "当日菜品留样（>=125g，保留 48 小时）",
            "required": True,
            "frequency": "每餐",
        },
        {
            "item": "效期检查",
            "description": "库存原料效期巡检，过期品立即下架",
            "required": True,
            "frequency": "每日",
        },
        {
            "item": "消毒记录",
            "description": "餐具/工具/台面消毒记录",
            "required": True,
            "frequency": "每餐前后",
        },
        {
            "item": "虫害检查",
            "description": "厨房虫害防治检查",
            "required": False,
            "frequency": "每周",
        },
    ]

    logger.info(
        "compliance_checklist_generated",
        store_id=store_id,
        check_date=check_date.isoformat(),
        item_count=len(checklist),
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "date": check_date.isoformat(),
        "tenant_id": tenant_id,
        "items": checklist,
        "total": len(checklist),
        "required_count": sum(1 for c in checklist if c["required"]),
    }


async def report_food_safety_event(
    store_id: str,
    event_type: str,
    detail: str,
    severity: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """食安事件上报

    severity=critical 时自动通知区域经理。

    Args:
        event_type: expired_ingredient / temperature_violation / foreign_object /
                    food_poisoning / pest / other
        severity: low / medium / high / critical
    """
    await _set_tenant(db, tenant_id)

    event_id = str(uuid.uuid4())
    event = {
        "event_id": event_id,
        "store_id": store_id,
        "event_type": event_type,
        "detail": detail,
        "severity": severity,
        "tenant_id": tenant_id,
        "reported_at": datetime.now().isoformat(),
        "status": "open",
    }

    logger.warning(
        "food_safety_event_reported",
        event_id=event_id,
        store_id=store_id,
        event_type=event_type,
        severity=severity,
        tenant_id=tenant_id,
    )

    # severity=critical 时自动通知区域经理
    if severity == EventSeverity.critical.value:
        await _notify_regional_manager(store_id, event_type, detail, tenant_id)
        event["auto_notified"] = True

    return event


async def get_responsibility_chain(
    event_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    batch_no: Optional[str] = None,
    ingredient_id: Optional[str] = None,
    store_id: Optional[str] = None,
) -> dict:
    """责任追踪链：谁采购 -> 谁验收 -> 谁领用 -> 谁出品

    基于批次号或原料 ID 回溯整条链路上的操作人。
    """
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)

    chain: list[dict] = []

    # 如果有 batch_no，按批次追溯
    if batch_no:
        trace_result = await trace_batch(batch_no, tenant_id, db)
        if trace_result["found"]:
            for t in trace_result["trace"]:
                chain.append({
                    "step": t["transaction_type"],
                    "operator": t.get("performed_by"),
                    "time": t.get("created_at"),
                    "quantity": t.get("quantity"),
                    "store_id": t.get("store_id"),
                })

    # 如果有 ingredient_id + store_id，查询该原料最近事务
    elif ingredient_id and store_id:
        sid = _uuid(store_id)
        iid = _uuid(ingredient_id)
        result = await db.execute(
            select(IngredientTransaction).where(
                IngredientTransaction.tenant_id == tid,
                IngredientTransaction.store_id == sid,
                IngredientTransaction.ingredient_id == iid,
                IngredientTransaction.is_deleted == False,  # noqa: E712
            ).order_by(IngredientTransaction.created_at.desc()).limit(20)
        )
        transactions = result.scalars().all()
        for txn in transactions:
            notes_data = _parse_notes(txn.notes)
            chain.append({
                "step": txn.transaction_type,
                "operator": notes_data.get("performed_by"),
                "time": txn.created_at.isoformat() if txn.created_at else None,
                "quantity": float(txn.quantity),
                "store_id": str(txn.store_id),
            })
        chain.reverse()

    # 按责任链阶段分类
    responsibility = {
        "procurement": [],    # 采购
        "receiving": [],      # 验收入库
        "requisition": [],    # 领用
        "production": [],     # 出品
    }

    step_mapping = {
        TransactionType.purchase.value: "procurement",
        TransactionType.usage.value: "requisition",
        TransactionType.waste.value: "requisition",
        TransactionType.transfer.value: "requisition",
    }

    for c in chain:
        stage = step_mapping.get(c["step"], "production")
        responsibility[stage].append(c)

    logger.info(
        "responsibility_chain_resolved",
        event_id=event_id,
        chain_length=len(chain),
        tenant_id=tenant_id,
    )

    return {
        "event_id": event_id,
        "chain": chain,
        "responsibility": responsibility,
        "summary": f"责任链共 {len(chain)} 个环节",
    }
