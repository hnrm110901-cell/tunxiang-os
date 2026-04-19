"""菜品三级发布方案 — 纯函数实现（不依赖DB）"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional

from shared.events import MenuEventType, UniversalPublisher

VALID_ADJUSTMENT_TYPES = {"time_period", "holiday", "delivery"}

VALID_CONDITIONS = {
    "time_period": {"breakfast", "lunch", "afternoon", "dinner", "late_night"},
    "holiday": {"spring_festival", "national_day", "mid_autumn", "weekend", "workday", "custom"},
    "delivery": {"meituan", "eleme", "douyin", "self_delivery"},
}


def create_publish_plan(
    plan_name: str,
    dish_ids: list[str],
    target_store_ids: list[str],
    schedule_time: Optional[str] = None,
) -> dict:
    """创建发布方案（纯函数，返回方案字典）。

    Args:
        plan_name: 方案名称
        dish_ids: 待发布菜品 ID 列表
        target_store_ids: 目标门店 ID 列表
        schedule_time: 可选，定时发布时间 (ISO 格式字符串)

    Returns:
        dict — 完整的发布方案描述
    """
    if not plan_name or not plan_name.strip():
        raise ValueError("plan_name 不能为空")
    if not dish_ids:
        raise ValueError("dish_ids 不能为空列表")
    if not target_store_ids:
        raise ValueError("target_store_ids 不能为空列表")

    plan_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    return {
        "plan_id": plan_id,
        "plan_name": plan_name.strip(),
        "dish_ids": list(dish_ids),
        "target_store_ids": list(target_store_ids),
        "schedule_time": schedule_time,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }


def execute_publish(
    plan_id: str,
    dish_data: list[dict],
    target_stores: list[str],
    tenant_id: Optional[str] = None,
    effective_date: Optional[str] = None,
) -> dict:
    """执行发布方案，返回每个门店的发布结果。

    Args:
        plan_id: 发布方案 ID
        dish_data: 菜品详情列表，每项至少含 {"dish_id": str, ...}
        target_stores: 目标门店 ID 列表

    Returns:
        dict — 包含整体状态和每个门店的发布结果
    """
    if not plan_id:
        raise ValueError("plan_id 不能为空")
    if not dish_data:
        raise ValueError("dish_data 不能为空")
    if not target_stores:
        raise ValueError("target_stores 不能为空")

    results: dict[str, dict] = {}
    success_count = 0
    fail_count = 0

    for store_id in target_stores:
        # 纯函数模拟：为每个门店生成发布结果
        dish_results = []
        for dish in dish_data:
            dish_id = dish.get("dish_id", "unknown")
            dish_results.append(
                {
                    "dish_id": dish_id,
                    "status": "published",
                    "published_at": datetime.utcnow().isoformat(),
                }
            )

        results[store_id] = {
            "store_id": store_id,
            "status": "success",
            "dish_count": len(dish_results),
            "dishes": dish_results,
        }
        success_count += 1

    execution_result = {
        "plan_id": plan_id,
        "status": "completed",
        "total_stores": len(target_stores),
        "success_count": success_count,
        "fail_count": fail_count,
        "results": results,
        "executed_at": datetime.utcnow().isoformat(),
    }

    if tenant_id and success_count > 0:
        dish_ids = [d.get("dish_id") for d in dish_data if d.get("dish_id")]
        asyncio.create_task(
            UniversalPublisher.publish(
                event_type=MenuEventType.DISH_PUBLISHED,
                tenant_id=uuid.UUID(tenant_id),
                store_id=None,
                entity_id=uuid.UUID(dish_ids[0]) if dish_ids else None,
                event_data={"dish_ids": dish_ids, "store_ids": list(target_stores), "effective_date": effective_date},
                source_service="tx-menu",
            )
        )

    return execution_result


def create_price_adjustment(
    store_id: str,
    adjustment_type: str,
    rules: list[dict],
) -> dict:
    """创建价格调整方案。

    Args:
        store_id: 门店 ID
        adjustment_type: 调整类型 — "time_period"(时段定价) / "holiday"(节假日) / "delivery"(外卖差异价)
        rules: 调整规则列表，例如 [{"condition": "lunch", "price_modifier": -500}]
               price_modifier 以分为单位，负数为降价，正数为加价

    Returns:
        dict — 价格调整方案
    """
    if not store_id:
        raise ValueError("store_id 不能为空")
    if adjustment_type not in VALID_ADJUSTMENT_TYPES:
        raise ValueError(f"adjustment_type 必须为 {VALID_ADJUSTMENT_TYPES} 之一，收到: {adjustment_type!r}")
    if not rules:
        raise ValueError("rules 不能为空列表")

    # 校验每条规则
    validated_rules = []
    for idx, rule in enumerate(rules):
        if "condition" not in rule:
            raise ValueError(f"rules[{idx}] 缺少 'condition' 字段")
        if "price_modifier" not in rule:
            raise ValueError(f"rules[{idx}] 缺少 'price_modifier' 字段")

        modifier = rule["price_modifier"]
        if not isinstance(modifier, (int, float)):
            raise ValueError(f"rules[{idx}].price_modifier 必须为数值，收到: {type(modifier).__name__}")

        validated_rules.append(
            {
                "condition": rule["condition"],
                "price_modifier": int(modifier),
                **{k: v for k, v in rule.items() if k not in ("condition", "price_modifier")},
            }
        )

    adjustment_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    return {
        "adjustment_id": adjustment_id,
        "store_id": store_id,
        "adjustment_type": adjustment_type,
        "rules": validated_rules,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
