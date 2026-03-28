"""服务费管理 — 按人/按桌/按时/按金额多种收费方案

服务费计入订单总额但不算菜品收入。
支持总部模板下发到门店。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()

# ─── 内存存储（mock） ───

_charge_configs: dict[str, dict] = {}  # key: f"{store_id}:{tenant_id}"
_charge_templates: dict[str, dict] = {}  # key: template_id
_charge_records: dict[str, dict] = {}  # key: charge_id


class ChargeMode:
    BY_PERSON = "by_person"
    BY_TABLE = "by_table"
    BY_TIME = "by_time"
    BY_AMOUNT = "by_amount"


async def get_charge_config(
    store_id: str,
    tenant_id: str,
    db=None,
) -> Optional[dict]:
    """获取门店服务费配置"""
    key = f"{store_id}:{tenant_id}"
    config = _charge_configs.get(key)
    logger.info(
        "charge_config_queried",
        store_id=store_id,
        tenant_id=tenant_id,
        found=config is not None,
    )
    return config


async def set_charge_config(
    store_id: str,
    config: dict,
    tenant_id: str,
    db=None,
) -> dict:
    """设置门店服务费配置

    config 示例:
    {
        "mode": "by_person",           # by_person / by_table / by_time / by_amount
        "charge_per_person_fen": 500,   # 按人: 每人5元
        "room_charge_fen": 8800,        # 按桌: 包厢费88元
        "time_unit_minutes": 30,        # 按时: 每30分钟
        "charge_per_unit_fen": 2000,    # 按时: 每单位20元
        "free_minutes": 120,            # 按时: 免费时长
        "waive_above_fen": 50000,       # 按金额: 满500免服务费
        "enabled": true
    }
    """
    key = f"{store_id}:{tenant_id}"
    config_record = {
        "id": str(uuid.uuid4()),
        "store_id": store_id,
        "tenant_id": tenant_id,
        "config": config,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _charge_configs[key] = config_record
    logger.info(
        "charge_config_set",
        store_id=store_id,
        tenant_id=tenant_id,
        mode=config.get("mode"),
    )
    return config_record


async def calculate_service_charge(
    order_id: str,
    store_id: str,
    tenant_id: str,
    db=None,
    *,
    guest_count: int = 1,
    room_type: Optional[str] = None,
    duration_minutes: int = 0,
    order_amount_fen: int = 0,
) -> dict:
    """根据门店配置自动计算服务费

    返回:
    {
        "charge_id": str,
        "order_id": str,
        "mode": str,
        "amount_fen": int,
        "waived": bool,
        "detail": dict
    }
    """
    config_record = await get_charge_config(store_id, tenant_id, db)
    if not config_record or not config_record.get("config", {}).get("enabled", False):
        return {
            "charge_id": None,
            "order_id": order_id,
            "mode": None,
            "amount_fen": 0,
            "waived": False,
            "detail": {"reason": "no_config_or_disabled"},
        }

    cfg = config_record["config"]
    mode = cfg.get("mode", ChargeMode.BY_PERSON)
    amount_fen = 0
    waived = False
    detail: dict = {}

    if mode == ChargeMode.BY_PERSON:
        charge_per_person = cfg.get("charge_per_person_fen", 0)
        amount_fen = guest_count * charge_per_person
        detail = {
            "guest_count": guest_count,
            "charge_per_person_fen": charge_per_person,
        }

    elif mode == ChargeMode.BY_TABLE:
        amount_fen = cfg.get("room_charge_fen", 0)
        detail = {"room_type": room_type, "room_charge_fen": amount_fen}

    elif mode == ChargeMode.BY_TIME:
        free_minutes = cfg.get("free_minutes", 0)
        billable_minutes = max(0, duration_minutes - free_minutes)
        time_unit = cfg.get("time_unit_minutes", 30)
        charge_per_unit = cfg.get("charge_per_unit_fen", 0)
        units = (billable_minutes + time_unit - 1) // time_unit if time_unit > 0 else 0
        amount_fen = units * charge_per_unit
        detail = {
            "duration_minutes": duration_minutes,
            "free_minutes": free_minutes,
            "billable_minutes": billable_minutes,
            "units": units,
            "charge_per_unit_fen": charge_per_unit,
        }

    elif mode == ChargeMode.BY_AMOUNT:
        waive_above = cfg.get("waive_above_fen", 0)
        base_charge = cfg.get("base_charge_fen", 0)
        if order_amount_fen >= waive_above and waive_above > 0:
            waived = True
            amount_fen = 0
        else:
            amount_fen = base_charge
        detail = {
            "order_amount_fen": order_amount_fen,
            "waive_above_fen": waive_above,
            "base_charge_fen": base_charge,
        }

    charge_id = str(uuid.uuid4())
    result = {
        "charge_id": charge_id,
        "order_id": order_id,
        "mode": mode,
        "amount_fen": amount_fen,
        "waived": waived,
        "detail": detail,
    }
    _charge_records[charge_id] = result

    logger.info(
        "service_charge_calculated",
        order_id=order_id,
        store_id=store_id,
        tenant_id=tenant_id,
        mode=mode,
        amount_fen=amount_fen,
        waived=waived,
    )
    return result


async def create_charge_template(
    name: str,
    rules: dict,
    tenant_id: str,
    db=None,
) -> dict:
    """创建总部服务费模板"""
    template_id = str(uuid.uuid4())
    template = {
        "id": template_id,
        "name": name,
        "rules": rules,
        "tenant_id": tenant_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    }
    _charge_templates[template_id] = template
    logger.info(
        "charge_template_created",
        template_id=template_id,
        name=name,
        tenant_id=tenant_id,
    )
    return template


async def publish_template(
    template_id: str,
    store_ids: list[str],
    tenant_id: str,
    db=None,
) -> dict:
    """将总部模板下发到指定门店"""
    template = _charge_templates.get(template_id)
    if not template:
        raise ValueError(f"Template not found: {template_id}")
    if template["tenant_id"] != tenant_id:
        raise PermissionError("Template does not belong to this tenant")

    published: list[str] = []
    for store_id in store_ids:
        config = dict(template["rules"])
        config["enabled"] = True
        config["source_template_id"] = template_id
        await set_charge_config(store_id, config, tenant_id, db)
        published.append(store_id)

    logger.info(
        "charge_template_published",
        template_id=template_id,
        tenant_id=tenant_id,
        store_count=len(published),
    )
    return {
        "template_id": template_id,
        "published_stores": published,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
