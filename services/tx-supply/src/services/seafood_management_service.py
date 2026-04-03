"""海鲜类食材专项管理服务

功能：
  - 鱼缸/水族箱列表（含水温/盐度/pH）
  - 活鲜库存按品种/规格/产地查询
  - 收货入库（含产地证明/检疫证合规校验）
  - 死亡损耗记录
  - 死亡率统计（近7天/30天，按品种）
  - 水质检测数据记录
  - 综合预警（死亡率/水质/库存低）

存储策略：
  - 无独立海鲜专用表时，使用内存存储 + ingredients.seafood_metadata JSONB（通过 raw SQL 扩展）
  - 内存存储供开发/测试；生产迁移到 DB 后替换 Repository 层即可

预警阈值：
  - 死亡率 > 5%/天 → mortality_alert
  - 水温超出品种适宜范围 → water_temp_alert
  - 库存 < 安全库存 → low_stock_alert
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog

log = structlog.get_logger(__name__)

# ─── 预警阈值常量 ──────────────────────────────────────────────────────────────

MORTALITY_ALERT_THRESHOLD_PCT = 5.0  # 日死亡率 > 5% 触发预警

# 各品种适宜水温范围（℃）。未注册品种使用 DEFAULT。
SPECIES_TEMP_RANGE: Dict[str, Tuple[float, float]] = {
    "草鱼": (15.0, 28.0),
    "鲈鱼": (15.0, 30.0),
    "鲤鱼": (10.0, 30.0),
    "鲫鱼": (10.0, 30.0),
    "龙虾": (18.0, 28.0),
    "螃蟹": (10.0, 25.0),
    "基围虾": (20.0, 30.0),
    "生蚝": (5.0, 20.0),
    "扇贝": (5.0, 20.0),
    "鲍鱼": (12.0, 20.0),
    "石斑鱼": (20.0, 30.0),
    "大黄鱼": (15.0, 28.0),
    "多宝鱼": (12.0, 22.0),
    "DEFAULT": (10.0, 30.0),
}

# ─── 内存存储（生产环境替换为 DB Repository） ─────────────────────────────────

# key: "{tenant_id}:{store_id}:{tank_id}" → tank dict
_tanks: Dict[str, Dict[str, Any]] = {}

# key: "{tenant_id}:{store_id}:{ingredient_id}" → list[stock_item dict]
_seafood_stock: Dict[str, List[Dict[str, Any]]] = {}

# mortality records list，每条含 tenant_id/store_id/ingredient_id/date
_mortality_records: List[Dict[str, Any]] = []

# water reading records list
_water_readings: List[Dict[str, Any]] = []


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return date.today()


def _gen_id(prefix: str = "sf") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _tank_key(tenant_id: str, store_id: str, tank_id: str) -> str:
    return f"{tenant_id}:{store_id}:{tank_id}"


def _stock_key(tenant_id: str, store_id: str, ingredient_id: str) -> str:
    return f"{tenant_id}:{store_id}:{ingredient_id}"


# ─── 鱼缸 / 水族箱 ────────────────────────────────────────────────────────────

async def list_tanks(
    store_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """返回门店所有鱼缸/水族箱，含最新水质数据。"""
    result = []
    prefix = f"{tenant_id}:{store_id}:"
    for key, tank in _tanks.items():
        if key.startswith(prefix):
            tank_id = key.split(":", 2)[2]
            result.append({**tank, "tank_id": tank_id})

    log.info("seafood.list_tanks", store_id=store_id, tenant_id=tenant_id, count=len(result))
    return {
        "store_id": store_id,
        "tanks": result,
        "total": len(result),
    }


# ─── 活鲜库存 ─────────────────────────────────────────────────────────────────

async def list_stock(
    store_id: str,
    tenant_id: str,
    species: Optional[str] = None,
    origin: Optional[str] = None,
    spec: Optional[str] = None,
) -> Dict[str, Any]:
    """活鲜库存查询，支持按品种/规格/产地过滤。"""
    items: List[Dict[str, Any]] = []
    prefix = f"{tenant_id}:{store_id}:"
    for key, stock_list in _seafood_stock.items():
        if not key.startswith(prefix):
            continue
        for item in stock_list:
            if species and item.get("species") != species:
                continue
            if origin and item.get("origin") != origin:
                continue
            if spec and item.get("spec") != spec:
                continue
            items.append(item)

    log.info("seafood.list_stock", store_id=store_id, count=len(items))
    return {
        "store_id": store_id,
        "items": items,
        "total": len(items),
    }


async def intake_stock(
    store_id: str,
    tenant_id: str,
    ingredient_id: str,
    species: str,
    spec: str,
    origin: str,
    quantity_kg: float,
    unit_price_fen: int,
    supplier_name: str,
    origin_certificate_no: str,      # 产地证明（食安硬约束）
    quarantine_certificate_no: str,  # 检疫证（食安硬约束）
    operator_id: str,
    tank_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """活鲜入库。产地证明+检疫证为合规必填项。

    Raises:
        ValueError: 产地证明或检疫证缺失
    """
    if not origin_certificate_no.strip():
        raise ValueError("食安合规：产地证明编号不能为空")
    if not quarantine_certificate_no.strip():
        raise ValueError("食安合规：检疫证编号不能为空")
    if quantity_kg <= 0:
        raise ValueError("入库数量必须大于0")

    record_id = _gen_id("intake")
    now = _now()

    item = {
        "record_id": record_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "ingredient_id": ingredient_id,
        "species": species,
        "spec": spec,
        "origin": origin,
        "quantity_kg": quantity_kg,
        "remaining_kg": quantity_kg,
        "unit_price_fen": unit_price_fen,
        "supplier_name": supplier_name,
        "origin_certificate_no": origin_certificate_no,
        "quarantine_certificate_no": quarantine_certificate_no,
        "tank_id": tank_id,
        "operator_id": operator_id,
        "notes": notes,
        "intake_at": now.isoformat(),
        "status": "alive",
    }

    key = _stock_key(tenant_id, store_id, ingredient_id)
    _seafood_stock.setdefault(key, []).append(item)

    # 如果指定了鱼缸，更新鱼缸库存
    if tank_id:
        tkey = _tank_key(tenant_id, store_id, tank_id)
        if tkey in _tanks:
            _tanks[tkey]["stock_kg"] = _tanks[tkey].get("stock_kg", 0.0) + quantity_kg
            _tanks[tkey]["updated_at"] = now.isoformat()

    log.info(
        "seafood.intake",
        record_id=record_id,
        species=species,
        quantity_kg=quantity_kg,
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return item


# ─── 死亡损耗 ─────────────────────────────────────────────────────────────────

async def record_mortality(
    store_id: str,
    tenant_id: str,
    ingredient_id: str,
    species: str,
    quantity_kg: float,
    reason: str,
    operator_id: str,
    tank_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """记录死亡损耗。

    Raises:
        ValueError: 数量无效
    """
    if quantity_kg <= 0:
        raise ValueError("死亡损耗数量必须大于0")

    record_id = _gen_id("mort")
    now = _now()
    today_str = now.date().isoformat()

    record = {
        "record_id": record_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "ingredient_id": ingredient_id,
        "species": species,
        "quantity_kg": quantity_kg,
        "reason": reason,
        "operator_id": operator_id,
        "tank_id": tank_id,
        "notes": notes,
        "recorded_at": now.isoformat(),
        "date": today_str,
    }
    _mortality_records.append(record)

    # 从库存中扣减（FIFO：最早入库的先扣）
    key = _stock_key(tenant_id, store_id, ingredient_id)
    remaining_to_deduct = quantity_kg
    for stock_item in sorted(
        _seafood_stock.get(key, []),
        key=lambda x: x.get("intake_at", ""),
    ):
        if remaining_to_deduct <= 0:
            break
        available = stock_item.get("remaining_kg", 0.0)
        deducted = min(available, remaining_to_deduct)
        stock_item["remaining_kg"] = round(available - deducted, 4)
        remaining_to_deduct -= deducted

    # 同步更新鱼缸库存
    if tank_id:
        tkey = _tank_key(tenant_id, store_id, tank_id)
        if tkey in _tanks:
            tank_stock = _tanks[tkey].get("stock_kg", 0.0)
            _tanks[tkey]["stock_kg"] = max(0.0, round(tank_stock - quantity_kg, 4))
            _tanks[tkey]["updated_at"] = now.isoformat()

    log.info(
        "seafood.mortality_recorded",
        record_id=record_id,
        species=species,
        quantity_kg=quantity_kg,
        reason=reason,
        store_id=store_id,
    )
    return record


# ─── 死亡率统计 ────────────────────────────────────────────────────────────────

async def get_mortality_rate(
    store_id: str,
    tenant_id: str,
    days: int = 7,
    species: Optional[str] = None,
) -> Dict[str, Any]:
    """死亡率统计（近 N 天，按品种汇总）。

    死亡率 = 期间死亡总量 / (期间死亡总量 + 当前存活量) × 100%
    """
    cutoff = (_now() - timedelta(days=days)).date()

    # 过滤本租户本门店的记录
    filtered = [
        r for r in _mortality_records
        if r["tenant_id"] == tenant_id
        and r["store_id"] == store_id
        and date.fromisoformat(r["date"]) >= cutoff
        and (species is None or r["species"] == species)
    ]

    # 按品种聚合死亡量
    by_species: Dict[str, float] = {}
    for r in filtered:
        sp = r["species"]
        by_species[sp] = by_species.get(sp, 0.0) + r["quantity_kg"]

    # 计算各品种存活库存
    surviving: Dict[str, float] = {}
    prefix = f"{tenant_id}:{store_id}:"
    for key, stock_list in _seafood_stock.items():
        if not key.startswith(prefix):
            continue
        for item in stock_list:
            sp = item.get("species", "")
            if species and sp != species:
                continue
            surviving[sp] = surviving.get(sp, 0.0) + item.get("remaining_kg", 0.0)

    species_stats = []
    for sp, dead_kg in by_species.items():
        alive_kg = surviving.get(sp, 0.0)
        total = dead_kg + alive_kg
        rate_pct = round(dead_kg / total * 100, 2) if total > 0 else 0.0
        is_alert = rate_pct > MORTALITY_ALERT_THRESHOLD_PCT
        species_stats.append({
            "species": sp,
            "dead_kg": round(dead_kg, 4),
            "alive_kg": round(alive_kg, 4),
            "mortality_rate_pct": rate_pct,
            "is_alert": is_alert,
        })

    # 按死亡率降序
    species_stats.sort(key=lambda x: x["mortality_rate_pct"], reverse=True)

    alert_species = [s["species"] for s in species_stats if s["is_alert"]]

    log.info(
        "seafood.mortality_rate",
        store_id=store_id,
        days=days,
        alert_count=len(alert_species),
    )
    return {
        "store_id": store_id,
        "period_days": days,
        "cutoff_date": cutoff.isoformat(),
        "by_species": species_stats,
        "alert_species": alert_species,
        "has_alert": len(alert_species) > 0,
    }


# ─── 水质检测 ─────────────────────────────────────────────────────────────────

async def record_tank_reading(
    store_id: str,
    tenant_id: str,
    tank_id: str,
    temperature: Optional[float],
    salinity_ppt: Optional[float],
    dissolved_oxygen_mgl: Optional[float],
    ph: Optional[float],
    operator_id: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """记录水质检测数据并更新鱼缸状态，触发水温/pH预警。"""
    record_id = _gen_id("wq")
    now = _now()

    reading = {
        "record_id": record_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "tank_id": tank_id,
        "temperature": temperature,
        "salinity_ppt": salinity_ppt,
        "dissolved_oxygen_mgl": dissolved_oxygen_mgl,
        "ph": ph,
        "operator_id": operator_id,
        "notes": notes,
        "recorded_at": now.isoformat(),
    }
    _water_readings.append(reading)

    # 更新鱼缸最新水质数据
    tkey = _tank_key(tenant_id, store_id, tank_id)
    if tkey not in _tanks:
        _tanks[tkey] = {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "tank_id": tank_id,
            "species": None,
            "stock_kg": 0.0,
            "created_at": now.isoformat(),
        }

    tank = _tanks[tkey]
    if temperature is not None:
        tank["temperature"] = temperature
    if salinity_ppt is not None:
        tank["salinity_ppt"] = salinity_ppt
    if dissolved_oxygen_mgl is not None:
        tank["dissolved_oxygen_mgl"] = dissolved_oxygen_mgl
    if ph is not None:
        tank["ph"] = ph
    tank["updated_at"] = now.isoformat()
    tank["last_reading_at"] = now.isoformat()

    # 生成水质预警
    alerts = _check_water_quality_alerts(tank_id, tank, temperature, ph)

    log.info(
        "seafood.tank_reading_recorded",
        record_id=record_id,
        tank_id=tank_id,
        temperature=temperature,
        ph=ph,
        alert_count=len(alerts),
    )
    return {**reading, "alerts": alerts}


def _check_water_quality_alerts(
    tank_id: str,
    tank: Dict[str, Any],
    temperature: Optional[float],
    ph: Optional[float],
) -> List[Dict[str, Any]]:
    """检查水质参数是否超出阈值。"""
    alerts: List[Dict[str, Any]] = []

    species = tank.get("species")
    if temperature is not None and species:
        temp_range = SPECIES_TEMP_RANGE.get(species, SPECIES_TEMP_RANGE["DEFAULT"])
        if temperature < temp_range[0]:
            alerts.append({
                "type": "water_temp_low",
                "tank_id": tank_id,
                "species": species,
                "current": temperature,
                "min_safe": temp_range[0],
                "severity": "warning",
                "message": f"水温 {temperature}℃ 低于 {species} 适宜下限 {temp_range[0]}℃",
            })
        elif temperature > temp_range[1]:
            alerts.append({
                "type": "water_temp_high",
                "tank_id": tank_id,
                "species": species,
                "current": temperature,
                "max_safe": temp_range[1],
                "severity": "warning",
                "message": f"水温 {temperature}℃ 高于 {species} 适宜上限 {temp_range[1]}℃",
            })

    if ph is not None:
        if ph < 6.5 or ph > 8.5:
            severity = "critical" if ph < 6.0 or ph > 9.0 else "warning"
            alerts.append({
                "type": "ph_abnormal",
                "tank_id": tank_id,
                "current_ph": ph,
                "safe_range": "6.5-8.5",
                "severity": severity,
                "message": f"pH {ph} 超出正常范围（6.5-8.5）",
            })

    return alerts


# ─── 综合预警 ─────────────────────────────────────────────────────────────────

async def get_alerts(
    store_id: str,
    tenant_id: str,
    min_stock_kg_threshold: float = 5.0,
) -> Dict[str, Any]:
    """综合预警：死亡率异常 / 水质异常 / 库存低。"""
    alerts: List[Dict[str, Any]] = []

    # 1. 死亡率预警（近7天）
    mortality_data = await get_mortality_rate(store_id, tenant_id, days=7)
    for sp_stat in mortality_data["by_species"]:
        if sp_stat["is_alert"]:
            alerts.append({
                "type": "mortality_alert",
                "severity": "critical",
                "species": sp_stat["species"],
                "mortality_rate_pct": sp_stat["mortality_rate_pct"],
                "threshold_pct": MORTALITY_ALERT_THRESHOLD_PCT,
                "message": (
                    f"{sp_stat['species']} 近7天死亡率 {sp_stat['mortality_rate_pct']}%，"
                    f"超过阈值 {MORTALITY_ALERT_THRESHOLD_PCT}%"
                ),
            })

    # 2. 水质预警（最新水质读数）
    prefix = f"{tenant_id}:{store_id}:"
    for key, tank in _tanks.items():
        if not key.startswith(prefix):
            continue
        tank_id = key.split(":", 2)[2]
        temp = tank.get("temperature")
        ph = tank.get("ph")
        water_alerts = _check_water_quality_alerts(tank_id, tank, temp, ph)
        alerts.extend(water_alerts)

    # 3. 库存低预警
    for key, stock_list in _seafood_stock.items():
        if not key.startswith(prefix):
            continue
        # 按品种聚合存活库存
        species_remaining: Dict[str, float] = {}
        for item in stock_list:
            sp = item.get("species", "unknown")
            species_remaining[sp] = (
                species_remaining.get(sp, 0.0) + item.get("remaining_kg", 0.0)
            )

        # 找安全库存阈值（此处用传入阈值；生产环境从 ingredients.min_quantity 读取）
        for sp, remaining in species_remaining.items():
            if remaining < min_stock_kg_threshold:
                alerts.append({
                    "type": "low_stock",
                    "severity": "warning" if remaining > 0 else "critical",
                    "species": sp,
                    "remaining_kg": round(remaining, 4),
                    "threshold_kg": min_stock_kg_threshold,
                    "message": f"{sp} 库存 {round(remaining, 2)}kg 低于安全库存 {min_stock_kg_threshold}kg",
                })

    log.info(
        "seafood.alerts",
        store_id=store_id,
        tenant_id=tenant_id,
        total=len(alerts),
    )
    return {
        "store_id": store_id,
        "alerts": alerts,
        "total": len(alerts),
        "has_critical": any(a["severity"] == "critical" for a in alerts),
    }
