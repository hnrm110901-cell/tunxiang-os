"""活鲜全链路管理 -- 海鲜酒楼的核心差异化能力

从进货入池 -> 海鲜池管理 -> 日常巡检 -> 时价管理 -> 称重售卖 -> 全链路溯源 -> 食安合规。

所有金额单位：分（fen）。重量单位：千克（kg）。温度单位：摄氏度（C）。
"""
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 物种数据库 ───

SPECIES_DATABASE: dict[str, dict] = {
    "lobster": {
        "name_cn": "龙虾",
        "name_en": "Lobster",
        "category": "crustacean",
        "temp_min": 12.0,
        "temp_max": 18.0,
        "salinity_min": 28.0,
        "salinity_max": 32.0,
        "ph_min": 7.8,
        "ph_max": 8.4,
        "max_density_kg_per_sqm": 8.0,
        "typical_mortality_rate": 0.02,  # 2%/day baseline
        "shelf_life_days": 7,
        "default_margin": 0.55,
        "yield_rate": 0.45,  # 出成率
        "cooking_methods": ["蒜蓉蒸", "芝士焗", "上汤焗", "刺身", "白灼"],
    },
    "grouper": {
        "name_cn": "石斑鱼",
        "name_en": "Grouper",
        "category": "fish",
        "temp_min": 18.0,
        "temp_max": 25.0,
        "salinity_min": 25.0,
        "salinity_max": 32.0,
        "ph_min": 7.5,
        "ph_max": 8.5,
        "max_density_kg_per_sqm": 12.0,
        "typical_mortality_rate": 0.015,
        "shelf_life_days": 5,
        "default_margin": 0.50,
        "yield_rate": 0.55,
        "cooking_methods": ["清蒸", "红烧", "煲汤", "刺身"],
    },
    "abalone": {
        "name_cn": "鲍鱼",
        "name_en": "Abalone",
        "category": "mollusk",
        "temp_min": 15.0,
        "temp_max": 22.0,
        "salinity_min": 30.0,
        "salinity_max": 35.0,
        "ph_min": 7.8,
        "ph_max": 8.4,
        "max_density_kg_per_sqm": 15.0,
        "typical_mortality_rate": 0.01,
        "shelf_life_days": 10,
        "default_margin": 0.60,
        "yield_rate": 0.40,
        "cooking_methods": ["鲍汁扣", "清蒸", "刺身", "红烧", "煲汤"],
    },
    "king_crab": {
        "name_cn": "帝王蟹",
        "name_en": "King Crab",
        "category": "crustacean",
        "temp_min": 2.0,
        "temp_max": 6.0,
        "salinity_min": 30.0,
        "salinity_max": 35.0,
        "ph_min": 7.5,
        "ph_max": 8.3,
        "max_density_kg_per_sqm": 6.0,
        "typical_mortality_rate": 0.03,
        "shelf_life_days": 5,
        "default_margin": 0.50,
        "yield_rate": 0.35,
        "cooking_methods": ["清蒸", "刺身", "火锅", "椒盐"],
    },
    "boston_lobster": {
        "name_cn": "波士顿龙虾",
        "name_en": "Boston Lobster",
        "category": "crustacean",
        "temp_min": 5.0,
        "temp_max": 10.0,
        "salinity_min": 28.0,
        "salinity_max": 32.0,
        "ph_min": 7.8,
        "ph_max": 8.4,
        "max_density_kg_per_sqm": 8.0,
        "typical_mortality_rate": 0.025,
        "shelf_life_days": 7,
        "default_margin": 0.50,
        "yield_rate": 0.40,
        "cooking_methods": ["蒜蓉蒸", "芝士焗", "上汤焗", "白灼", "刺身"],
    },
    "geoduck": {
        "name_cn": "象拔蚌",
        "name_en": "Geoduck",
        "category": "mollusk",
        "temp_min": 8.0,
        "temp_max": 15.0,
        "salinity_min": 28.0,
        "salinity_max": 32.0,
        "ph_min": 7.5,
        "ph_max": 8.5,
        "max_density_kg_per_sqm": 10.0,
        "typical_mortality_rate": 0.02,
        "shelf_life_days": 5,
        "default_margin": 0.55,
        "yield_rate": 0.50,
        "cooking_methods": ["刺身", "白灼", "XO酱炒", "煲粥"],
    },
    "leopard_coral_grouper": {
        "name_cn": "东星斑",
        "name_en": "Leopard Coral Grouper",
        "category": "fish",
        "temp_min": 20.0,
        "temp_max": 28.0,
        "salinity_min": 28.0,
        "salinity_max": 33.0,
        "ph_min": 7.8,
        "ph_max": 8.5,
        "max_density_kg_per_sqm": 10.0,
        "typical_mortality_rate": 0.015,
        "shelf_life_days": 5,
        "default_margin": 0.55,
        "yield_rate": 0.55,
        "cooking_methods": ["清蒸", "红烧", "煲汤", "刺身"],
    },
    "australian_lobster": {
        "name_cn": "澳洲龙虾",
        "name_en": "Australian Lobster",
        "category": "crustacean",
        "temp_min": 15.0,
        "temp_max": 20.0,
        "salinity_min": 30.0,
        "salinity_max": 35.0,
        "ph_min": 7.8,
        "ph_max": 8.4,
        "max_density_kg_per_sqm": 7.0,
        "typical_mortality_rate": 0.02,
        "shelf_life_days": 7,
        "default_margin": 0.55,
        "yield_rate": 0.42,
        "cooking_methods": ["蒜蓉蒸", "芝士焗", "上汤焗", "刺身", "白灼"],
    },
}


# ─── 数据模型 ───

@dataclass
class TankStatus:
    """海鲜池状态"""
    tank_id: str
    species: list[str]  # species keys from SPECIES_DATABASE
    temperature: float  # celsius
    salinity: float  # ppt
    ph: float
    density_kg_per_sqm: float
    water_quality: str  # excellent/good/fair/poor
    last_water_change: str  # ISO datetime
    current_stock_kg: float
    alert_level: str  # normal/warning/critical
    alerts: list[dict] = field(default_factory=list)


def _gen_id() -> str:
    return uuid.uuid4().hex[:12].upper()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str) -> datetime:
    """Parse ISO datetime string to datetime object."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# ─── 内存存储（生产环境替换为 DB Repository） ───

_batches: dict[str, dict] = {}       # batch_id -> intake record
_tanks: dict[str, dict] = {}         # tank_id -> tank state
_inspections: dict[str, list] = {}   # tank_id -> [inspection records]
_market_prices: dict[str, dict] = {} # species -> current price info
_price_history: dict[str, list] = {} # species -> [price records]
_sales: dict[str, dict] = {}         # sale_id -> sale record
_compliance_logs: dict[str, list] = {}  # store_id -> [compliance records]


class LiveSeafoodService:
    """活鲜全链路管理 -- 海鲜酒楼的核心差异化能力"""

    def __init__(self, tenant_id: str, store_id: str):
        self.tenant_id = tenant_id
        self.store_id = store_id

    # ─── 1. Intake (进货入池) ───

    def record_intake(
        self,
        batch_id: str,
        species: str,
        supplier_id: str,
        quantity_kg: float,
        unit_price_fen: int,
        quarantine_cert: str,
        tank_id: str,
        intake_date: Optional[str] = None,
    ) -> dict:
        """记录活鲜进货入池

        Args:
            batch_id: 批次号（供应商提供或自动生成）
            species: 物种代码（对应 SPECIES_DATABASE 的 key）
            supplier_id: 供应商ID
            quantity_kg: 进货重量(kg)
            unit_price_fen: 进货单价(分/kg)
            quarantine_cert: 检疫证号
            tank_id: 入池ID
            intake_date: 进货日期 (ISO)，默认当前时间
        """
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}. "
                             f"Known: {list(SPECIES_DATABASE.keys())}")
        if quantity_kg <= 0:
            raise ValueError("quantity_kg must be positive")
        if unit_price_fen <= 0:
            raise ValueError("unit_price_fen must be positive")
        if not quarantine_cert:
            raise ValueError("quarantine_cert is required for food safety compliance")

        sp = SPECIES_DATABASE[species]
        intake_date = intake_date or _now_iso()

        # 计算批次总成本
        total_cost_fen = int(quantity_kg * unit_price_fen)

        # 计算保质期截止
        shelf_life_days = sp["shelf_life_days"]
        intake_dt = _parse_iso(intake_date)
        expiry_date = (intake_dt + timedelta(days=shelf_life_days)).isoformat()

        record = {
            "batch_id": batch_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "species": species,
            "species_name_cn": sp["name_cn"],
            "supplier_id": supplier_id,
            "quantity_kg": quantity_kg,
            "remaining_kg": quantity_kg,
            "mortality_kg": 0.0,
            "sold_kg": 0.0,
            "unit_price_fen": unit_price_fen,
            "total_cost_fen": total_cost_fen,
            "quarantine_cert": quarantine_cert,
            "tank_id": tank_id,
            "intake_date": intake_date,
            "expiry_date": expiry_date,
            "status": "active",  # active/depleted/expired/disposed
            "created_at": _now_iso(),
        }

        _batches[batch_id] = record

        # 更新池子库存
        self._add_to_tank(tank_id, species, quantity_kg)

        logger.info("seafood_intake_recorded", batch_id=batch_id, species=species,
                     quantity_kg=quantity_kg, tank_id=tank_id)
        return record

    def _add_to_tank(self, tank_id: str, species: str, quantity_kg: float) -> None:
        """将库存添加到海鲜池"""
        if tank_id not in _tanks:
            sp = SPECIES_DATABASE.get(species, {})
            _tanks[tank_id] = {
                "tank_id": tank_id,
                "store_id": self.store_id,
                "species": [species],
                "temperature": (sp.get("temp_min", 15) + sp.get("temp_max", 25)) / 2,
                "salinity": (sp.get("salinity_min", 28) + sp.get("salinity_max", 35)) / 2,
                "ph": (sp.get("ph_min", 7.5) + sp.get("ph_max", 8.5)) / 2,
                "density_kg_per_sqm": 0.0,
                "area_sqm": 10.0,  # default 10 sqm (commercial seafood tank)
                "water_quality": "good",
                "last_water_change": _now_iso(),
                "current_stock_kg": 0.0,
                "alert_level": "normal",
                "alerts": [],
                "batches": [],
                "updated_at": _now_iso(),
            }

        tank = _tanks[tank_id]
        tank["current_stock_kg"] += quantity_kg
        if species not in tank["species"]:
            tank["species"].append(species)
        if not any(b == species for b in tank.get("batches", [])):
            tank.setdefault("batches", []).append(species)
        tank["density_kg_per_sqm"] = tank["current_stock_kg"] / tank.get("area_sqm", 2.0)
        tank["updated_at"] = _now_iso()

    # ─── 2. Tank Management (海鲜池管理) ───

    def update_tank_status(
        self,
        tank_id: str,
        temperature: float,
        salinity: float,
        ph: float,
        density: Optional[float] = None,
        water_quality: Optional[str] = None,
    ) -> dict:
        """更新海鲜池环境参数"""
        if tank_id not in _tanks:
            raise ValueError(f"Tank not found: {tank_id}")

        tank = _tanks[tank_id]
        tank["temperature"] = temperature
        tank["salinity"] = salinity
        tank["ph"] = ph
        if density is not None:
            tank["density_kg_per_sqm"] = density
        if water_quality is not None:
            tank["water_quality"] = water_quality
        tank["updated_at"] = _now_iso()

        # 检查告警
        alerts = self._check_parameter_alerts(tank)
        tank["alerts"] = alerts
        tank["alert_level"] = (
            "critical" if any(a["severity"] == "critical" for a in alerts) else
            "warning" if any(a["severity"] == "warning" for a in alerts) else
            "normal"
        )

        logger.info("tank_status_updated", tank_id=tank_id,
                     temp=temperature, salinity=salinity, ph=ph,
                     alert_level=tank["alert_level"])
        return {
            "tank_id": tank_id,
            "temperature": temperature,
            "salinity": salinity,
            "ph": ph,
            "water_quality": tank["water_quality"],
            "alert_level": tank["alert_level"],
            "alerts": alerts,
        }

    def _check_parameter_alerts(self, tank: dict) -> list[dict]:
        """检查海鲜池参数是否在安全范围"""
        alerts = []
        temp = tank["temperature"]
        sal = tank["salinity"]
        ph = tank["ph"]
        density = tank["density_kg_per_sqm"]

        for species_key in tank.get("species", []):
            sp = SPECIES_DATABASE.get(species_key)
            if not sp:
                continue

            name = sp["name_cn"]

            # 温度检查
            if temp < sp["temp_min"]:
                diff = sp["temp_min"] - temp
                severity = "critical" if diff > 3 else "warning"
                alerts.append({
                    "type": "temperature_low",
                    "detail": f"{name}水温过低: {temp}C (要求 {sp['temp_min']}-{sp['temp_max']}C)",
                    "severity": severity,
                    "species": species_key,
                })
            elif temp > sp["temp_max"]:
                diff = temp - sp["temp_max"]
                severity = "critical" if diff > 3 else "warning"
                alerts.append({
                    "type": "temperature_high",
                    "detail": f"{name}水温过高: {temp}C (要求 {sp['temp_min']}-{sp['temp_max']}C)",
                    "severity": severity,
                    "species": species_key,
                })

            # 盐度检查
            if sal < sp["salinity_min"]:
                diff = sp["salinity_min"] - sal
                severity = "critical" if diff > 3 else "warning"
                alerts.append({
                    "type": "salinity_low",
                    "detail": f"{name}盐度过低: {sal}ppt (要求 {sp['salinity_min']}-{sp['salinity_max']}ppt)",
                    "severity": severity,
                    "species": species_key,
                })
            elif sal > sp["salinity_max"]:
                diff = sal - sp["salinity_max"]
                severity = "critical" if diff > 3 else "warning"
                alerts.append({
                    "type": "salinity_high",
                    "detail": f"{name}盐度过高: {sal}ppt (要求 {sp['salinity_min']}-{sp['salinity_max']}ppt)",
                    "severity": severity,
                    "species": species_key,
                })

            # pH检查
            if ph < sp["ph_min"] or ph > sp["ph_max"]:
                alerts.append({
                    "type": "ph_out_of_range",
                    "detail": f"{name}pH异常: {ph} (要求 {sp['ph_min']}-{sp['ph_max']})",
                    "severity": "warning",
                    "species": species_key,
                })

            # 密度检查
            if density > sp["max_density_kg_per_sqm"]:
                severity = "critical" if density > sp["max_density_kg_per_sqm"] * 1.3 else "warning"
                alerts.append({
                    "type": "overstocked",
                    "detail": f"{name}密度过高: {density:.1f}kg/m2 (上限 {sp['max_density_kg_per_sqm']}kg/m2)",
                    "severity": severity,
                    "species": species_key,
                })

        return alerts

    def get_tank_dashboard(self, store_id: Optional[str] = None) -> list[dict]:
        """获取所有海鲜池仪表盘"""
        target_store = store_id or self.store_id
        results = []
        for tank_id, tank in _tanks.items():
            if tank.get("store_id") != target_store:
                continue

            species_info = []
            for sp_key in tank.get("species", []):
                sp = SPECIES_DATABASE.get(sp_key, {})
                species_info.append({
                    "key": sp_key,
                    "name_cn": sp.get("name_cn", sp_key),
                    "optimal_temp": f"{sp.get('temp_min', '?')}-{sp.get('temp_max', '?')}C",
                    "optimal_salinity": f"{sp.get('salinity_min', '?')}-{sp.get('salinity_max', '?')}ppt",
                })

            results.append({
                "tank_id": tank_id,
                "species": species_info,
                "temperature": tank["temperature"],
                "salinity": tank["salinity"],
                "ph": tank["ph"],
                "density_kg_per_sqm": round(tank["density_kg_per_sqm"], 2),
                "water_quality": tank["water_quality"],
                "current_stock_kg": round(tank["current_stock_kg"], 2),
                "last_water_change": tank.get("last_water_change"),
                "alert_level": tank["alert_level"],
                "alert_count": len(tank.get("alerts", [])),
                "alerts": tank.get("alerts", []),
            })

        return results

    def check_tank_alerts(self, store_id: Optional[str] = None) -> list[dict]:
        """检查所有海鲜池告警"""
        target_store = store_id or self.store_id
        all_alerts = []
        for tank_id, tank in _tanks.items():
            if tank.get("store_id") != target_store:
                continue
            # Refresh alerts
            alerts = self._check_parameter_alerts(tank)
            tank["alerts"] = alerts
            for alert in alerts:
                all_alerts.append({
                    "tank_id": tank_id,
                    **alert,
                    "checked_at": _now_iso(),
                })

        # Sort: critical first
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        all_alerts.sort(key=lambda a: severity_order.get(a.get("severity", "info"), 9))
        return all_alerts

    # ─── 3. Daily Inspection (日常巡检) ───

    def record_inspection(
        self,
        tank_id: str,
        inspector: str,
        mortality_count: int,
        mortality_kg: float,
        water_changed: bool,
        notes: Optional[str] = None,
    ) -> dict:
        """记录每日巡检

        Args:
            tank_id: 池子ID
            inspector: 巡检员姓名
            mortality_count: 死亡数量(尾/只)
            mortality_kg: 死亡重量(kg)
            water_changed: 是否换水
            notes: 巡检备注
        """
        if tank_id not in _tanks:
            raise ValueError(f"Tank not found: {tank_id}")

        tank = _tanks[tank_id]
        inspection_id = f"INSP-{_gen_id()}"

        # 更新库存（扣除死损）
        old_stock = tank["current_stock_kg"]
        tank["current_stock_kg"] = max(0, old_stock - mortality_kg)
        tank["density_kg_per_sqm"] = tank["current_stock_kg"] / tank.get("area_sqm", 2.0)
        if water_changed:
            tank["last_water_change"] = _now_iso()
        tank["updated_at"] = _now_iso()

        # 更新对应批次的死损
        for batch in _batches.values():
            if batch.get("tank_id") == tank_id and batch["status"] == "active":
                batch["mortality_kg"] += mortality_kg
                batch["remaining_kg"] = max(0, batch["remaining_kg"] - mortality_kg)
                if batch["remaining_kg"] <= 0:
                    batch["status"] = "depleted"
                break  # 先进先出：优先扣最早批次

        # 计算死损率
        mortality_rate = mortality_kg / old_stock if old_stock > 0 else 0

        record = {
            "inspection_id": inspection_id,
            "tank_id": tank_id,
            "store_id": self.store_id,
            "inspector": inspector,
            "mortality_count": mortality_count,
            "mortality_kg": mortality_kg,
            "mortality_rate": round(mortality_rate, 4),
            "stock_before_kg": round(old_stock, 2),
            "stock_after_kg": round(tank["current_stock_kg"], 2),
            "water_changed": water_changed,
            "temperature": tank["temperature"],
            "salinity": tank["salinity"],
            "ph": tank["ph"],
            "water_quality": tank["water_quality"],
            "notes": notes,
            "inspected_at": _now_iso(),
            "alert_level": "warning" if mortality_rate > 0.03 else "normal",
        }

        _inspections.setdefault(tank_id, []).append(record)

        logger.info("seafood_inspection_recorded", inspection_id=inspection_id,
                     tank_id=tank_id, mortality_kg=mortality_kg,
                     mortality_rate=round(mortality_rate, 4))
        return record

    def get_mortality_trend(self, species: str, days: int = 30) -> dict:
        """获取指定物种死损率趋势"""
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}")

        sp = SPECIES_DATABASE[species]
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        daily_data: dict[str, dict] = {}
        for tank_id, inspections in _inspections.items():
            tank = _tanks.get(tank_id, {})
            if species not in tank.get("species", []):
                continue

            for insp in inspections:
                insp_dt = _parse_iso(insp["inspected_at"])
                if insp_dt < cutoff:
                    continue
                date_key = insp_dt.strftime("%Y-%m-%d")
                if date_key not in daily_data:
                    daily_data[date_key] = {"mortality_kg": 0, "stock_kg": 0, "count": 0}
                daily_data[date_key]["mortality_kg"] += insp["mortality_kg"]
                daily_data[date_key]["stock_kg"] += insp["stock_before_kg"]
                daily_data[date_key]["count"] += 1

        trend = []
        total_mortality = 0.0
        total_stock = 0.0
        for date_key in sorted(daily_data.keys()):
            d = daily_data[date_key]
            rate = d["mortality_kg"] / d["stock_kg"] if d["stock_kg"] > 0 else 0
            trend.append({
                "date": date_key,
                "mortality_kg": round(d["mortality_kg"], 2),
                "stock_kg": round(d["stock_kg"], 2),
                "mortality_rate": round(rate, 4),
            })
            total_mortality += d["mortality_kg"]
            total_stock += d["stock_kg"]

        avg_rate = total_mortality / total_stock if total_stock > 0 else 0
        baseline = sp["typical_mortality_rate"]

        return {
            "species": species,
            "species_name_cn": sp["name_cn"],
            "period_days": days,
            "trend": trend,
            "avg_mortality_rate": round(avg_rate, 4),
            "baseline_mortality_rate": baseline,
            "status": (
                "excellent" if avg_rate < baseline * 0.5 else
                "good" if avg_rate <= baseline else
                "concerning" if avg_rate <= baseline * 2 else
                "critical"
            ),
            "total_mortality_kg": round(total_mortality, 2),
        }

    def predict_mortality(self, tank_id: str, species: str) -> dict:
        """基于当前环境条件预测死损率

        使用物种最适参数偏离度作为风险因子计算预测死损率。
        """
        if tank_id not in _tanks:
            raise ValueError(f"Tank not found: {tank_id}")
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}")

        tank = _tanks[tank_id]
        sp = SPECIES_DATABASE[species]
        baseline = sp["typical_mortality_rate"]

        # 计算各参数偏离因子
        temp = tank["temperature"]
        temp_mid = (sp["temp_min"] + sp["temp_max"]) / 2
        temp_range = (sp["temp_max"] - sp["temp_min"]) / 2
        temp_deviation = abs(temp - temp_mid) / temp_range if temp_range > 0 else 0

        sal = tank["salinity"]
        sal_mid = (sp["salinity_min"] + sp["salinity_max"]) / 2
        sal_range = (sp["salinity_max"] - sp["salinity_min"]) / 2
        sal_deviation = abs(sal - sal_mid) / sal_range if sal_range > 0 else 0

        ph = tank["ph"]
        ph_mid = (sp["ph_min"] + sp["ph_max"]) / 2
        ph_range = (sp["ph_max"] - sp["ph_min"]) / 2
        ph_deviation = abs(ph - ph_mid) / ph_range if ph_range > 0 else 0

        density = tank["density_kg_per_sqm"]
        density_ratio = density / sp["max_density_kg_per_sqm"] if sp["max_density_kg_per_sqm"] > 0 else 0

        # 综合风险因子 — 指数增长模型
        # 当所有参数在最适范围中心时，risk_factor = 1.0
        # 偏离越大，风险指数级增长
        risk_factor = 1.0
        if temp_deviation > 1.0:
            risk_factor *= (1 + (temp_deviation - 1.0) * 3)  # 温度超出范围，风险×3
        else:
            risk_factor *= (1 + temp_deviation * 0.5)

        if sal_deviation > 1.0:
            risk_factor *= (1 + (sal_deviation - 1.0) * 2)
        else:
            risk_factor *= (1 + sal_deviation * 0.3)

        if ph_deviation > 1.0:
            risk_factor *= (1 + (ph_deviation - 1.0) * 1.5)
        else:
            risk_factor *= (1 + ph_deviation * 0.2)

        if density_ratio > 1.0:
            risk_factor *= (1 + (density_ratio - 1.0) * 2)
        elif density_ratio > 0.8:
            risk_factor *= (1 + (density_ratio - 0.8) * 0.5)

        # 水质因子
        wq_factor = {"excellent": 0.8, "good": 1.0, "fair": 1.5, "poor": 3.0}
        risk_factor *= wq_factor.get(tank.get("water_quality", "good"), 1.0)

        predicted_rate = min(1.0, baseline * risk_factor)

        # 风险等级
        if predicted_rate <= baseline:
            risk_level = "low"
        elif predicted_rate <= baseline * 2:
            risk_level = "medium"
        elif predicted_rate <= baseline * 4:
            risk_level = "high"
        else:
            risk_level = "critical"

        # 建议
        recommendations = []
        if temp < sp["temp_min"]:
            recommendations.append(f"升温至{sp['temp_min']}C以上")
        elif temp > sp["temp_max"]:
            recommendations.append(f"降温至{sp['temp_max']}C以下")
        if sal < sp["salinity_min"]:
            recommendations.append(f"提高盐度至{sp['salinity_min']}ppt以上")
        elif sal > sp["salinity_max"]:
            recommendations.append(f"降低盐度至{sp['salinity_max']}ppt以下")
        if density_ratio > 0.9:
            recommendations.append("减少密度，分池养殖")
        if tank.get("water_quality") in ("fair", "poor"):
            recommendations.append("立即换水改善水质")

        result = {
            "tank_id": tank_id,
            "species": species,
            "species_name_cn": sp["name_cn"],
            "baseline_mortality_rate": baseline,
            "predicted_mortality_rate": round(predicted_rate, 4),
            "risk_factor": round(risk_factor, 2),
            "risk_level": risk_level,
            "parameter_deviations": {
                "temperature": round(temp_deviation, 2),
                "salinity": round(sal_deviation, 2),
                "ph": round(ph_deviation, 2),
                "density_ratio": round(density_ratio, 2),
            },
            "current_conditions": {
                "temperature": temp,
                "salinity": sal,
                "ph": ph,
                "density": density,
                "water_quality": tank.get("water_quality", "unknown"),
            },
            "optimal_conditions": {
                "temperature": f"{sp['temp_min']}-{sp['temp_max']}C",
                "salinity": f"{sp['salinity_min']}-{sp['salinity_max']}ppt",
                "ph": f"{sp['ph_min']}-{sp['ph_max']}",
                "max_density": f"{sp['max_density_kg_per_sqm']}kg/m2",
            },
            "recommendations": recommendations,
            "predicted_loss_kg_24h": round(tank["current_stock_kg"] * predicted_rate, 2),
        }

        logger.info("mortality_predicted", tank_id=tank_id, species=species,
                     predicted_rate=round(predicted_rate, 4), risk_level=risk_level)
        return result

    # ─── 4. Market Price Engine (时价管理) ───

    def update_market_price(
        self,
        species: str,
        market_price_fen: int,
        source: str,
    ) -> dict:
        """更新市场时价

        Args:
            species: 物种代码
            market_price_fen: 市场价格 (分/kg)
            source: 价格来源 (e.g., "黄沙水产市场", "supplier_quote", "京东到家")
        """
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}")
        if market_price_fen <= 0:
            raise ValueError("market_price_fen must be positive")

        sp = SPECIES_DATABASE[species]
        old_price = _market_prices.get(species, {}).get("market_price_fen")

        price_record = {
            "species": species,
            "species_name_cn": sp["name_cn"],
            "market_price_fen": market_price_fen,
            "source": source,
            "updated_at": _now_iso(),
            "change_pct": round((market_price_fen - old_price) / old_price * 100, 2) if old_price else None,
        }

        _market_prices[species] = price_record

        # 追加历史记录
        _price_history.setdefault(species, []).append({
            "price_fen": market_price_fen,
            "source": source,
            "recorded_at": _now_iso(),
        })

        logger.info("market_price_updated", species=species,
                     price_fen=market_price_fen, source=source)
        return price_record

    def calculate_selling_price(
        self,
        species: str,
        cost_price_fen: int,
        target_margin: float = 0.45,
    ) -> dict:
        """计算建议售价 — 确保目标毛利率

        Args:
            species: 物种代码
            cost_price_fen: 成本价 (分/kg)
            target_margin: 目标毛利率 (默认 45%)
        """
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}")
        if target_margin <= 0 or target_margin >= 1:
            raise ValueError("target_margin must be between 0 and 1")

        sp = SPECIES_DATABASE[species]
        yield_rate = sp["yield_rate"]

        # 考虑出成率的实际成本
        actual_cost_per_kg_edible = int(cost_price_fen / yield_rate) if yield_rate > 0 else cost_price_fen

        # 目标售价 = 实际成本 / (1 - 目标毛利率)
        target_selling_price = int(actual_cost_per_kg_edible / (1 - target_margin))

        # 市场参考价
        market = _market_prices.get(species, {})
        market_price = market.get("market_price_fen")

        # 如果市场价低于目标售价，使用市场价但警告毛利不足
        margin_at_market = None
        if market_price:
            margin_at_market = round(1 - actual_cost_per_kg_edible / market_price, 4) if market_price > 0 else 0

        # 最终建议价 — 取目标售价和市场价的较高者，确保毛利底线
        recommended_price = target_selling_price
        price_note = "按目标毛利率定价"
        if market_price and market_price > target_selling_price:
            recommended_price = market_price
            price_note = "市场价高于成本定价，建议跟市场走"
        elif market_price and market_price < target_selling_price:
            price_note = f"市场价偏低，建议维持目标售价，当前市场毛利率仅{margin_at_market}"

        result = {
            "species": species,
            "species_name_cn": sp["name_cn"],
            "cost_price_fen": cost_price_fen,
            "yield_rate": yield_rate,
            "actual_cost_per_kg_edible_fen": actual_cost_per_kg_edible,
            "target_margin": target_margin,
            "target_selling_price_fen": target_selling_price,
            "market_price_fen": market_price,
            "margin_at_market_price": margin_at_market,
            "recommended_price_fen": recommended_price,
            "note": price_note,
        }

        logger.info("selling_price_calculated", species=species,
                     recommended_fen=recommended_price)
        return result

    def get_price_history(self, species: str, days: int = 90) -> list[dict]:
        """获取物种价格历史"""
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}")

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        history = _price_history.get(species, [])

        filtered = []
        for record in history:
            rec_dt = _parse_iso(record["recorded_at"])
            if rec_dt >= cutoff:
                filtered.append(record)

        return filtered

    def detect_price_anomaly(self, species: str, proposed_price_fen: int) -> dict:
        """检测价格异常 — 防止录入错误或恶意定价"""
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}")

        history = _price_history.get(species, [])
        if len(history) < 3:
            return {
                "species": species,
                "proposed_price_fen": proposed_price_fen,
                "is_anomaly": False,
                "reason": "历史数据不足，无法判断",
                "confidence": 0.3,
            }

        # 计算最近价格的均值和标准差
        recent_prices = [r["price_fen"] for r in history[-30:]]
        mean_price = sum(recent_prices) / len(recent_prices)
        variance = sum((p - mean_price) ** 2 for p in recent_prices) / len(recent_prices)
        std_dev = math.sqrt(variance) if variance > 0 else mean_price * 0.1

        # Z-score 检测
        z_score = abs(proposed_price_fen - mean_price) / std_dev if std_dev > 0 else 0

        is_anomaly = z_score > 2.5
        deviation_pct = round((proposed_price_fen - mean_price) / mean_price * 100, 2) if mean_price > 0 else 0

        if is_anomaly:
            if proposed_price_fen > mean_price:
                reason = f"价格高于均值{abs(deviation_pct)}%，疑似录入错误"
            else:
                reason = f"价格低于均值{abs(deviation_pct)}%，疑似异常低价"
        else:
            reason = "价格在正常波动范围内"

        return {
            "species": species,
            "species_name_cn": SPECIES_DATABASE[species]["name_cn"],
            "proposed_price_fen": proposed_price_fen,
            "mean_price_fen": int(mean_price),
            "std_dev_fen": int(std_dev),
            "z_score": round(z_score, 2),
            "deviation_pct": deviation_pct,
            "is_anomaly": is_anomaly,
            "reason": reason,
            "confidence": min(0.95, 0.5 + len(recent_prices) * 0.02),
        }

    # ─── 5. Weighing & Sale (称重售卖) ───

    def record_sale(
        self,
        batch_id: str,
        species: str,
        weight_kg: float,
        selling_price_fen: int,
        order_id: str,
        cooking_method: str,
    ) -> dict:
        """记录称重售卖

        Args:
            batch_id: 批次号
            species: 物种代码
            weight_kg: 售卖重量(kg)
            selling_price_fen: 售价(分/kg)
            order_id: 关联订单ID
            cooking_method: 做法
        """
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}")

        batch = _batches.get(batch_id)
        if not batch:
            raise ValueError(f"Batch not found: {batch_id}")
        if batch["status"] != "active":
            raise ValueError(f"Batch {batch_id} is {batch['status']}, cannot sell")
        if weight_kg > batch["remaining_kg"]:
            raise ValueError(
                f"Insufficient stock: requested {weight_kg}kg, "
                f"remaining {batch['remaining_kg']}kg"
            )

        sp = SPECIES_DATABASE[species]
        sale_id = f"SALE-{_gen_id()}"
        sale_amount_fen = int(weight_kg * selling_price_fen)
        cost_amount_fen = int(weight_kg * batch["unit_price_fen"])
        margin_fen = sale_amount_fen - cost_amount_fen
        margin_rate = margin_fen / sale_amount_fen if sale_amount_fen > 0 else 0

        # 更新批次
        batch["sold_kg"] += weight_kg
        batch["remaining_kg"] -= weight_kg
        if batch["remaining_kg"] <= 0.01:  # float precision
            batch["remaining_kg"] = 0
            batch["status"] = "depleted"

        # 更新池子
        tank_id = batch["tank_id"]
        if tank_id in _tanks:
            tank = _tanks[tank_id]
            tank["current_stock_kg"] = max(0, tank["current_stock_kg"] - weight_kg)
            tank["density_kg_per_sqm"] = tank["current_stock_kg"] / tank.get("area_sqm", 2.0)
            tank["updated_at"] = _now_iso()

        sale = {
            "sale_id": sale_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "batch_id": batch_id,
            "species": species,
            "species_name_cn": sp["name_cn"],
            "weight_kg": weight_kg,
            "selling_price_fen": selling_price_fen,
            "sale_amount_fen": sale_amount_fen,
            "cost_price_fen": batch["unit_price_fen"],
            "cost_amount_fen": cost_amount_fen,
            "margin_fen": margin_fen,
            "margin_rate": round(margin_rate, 4),
            "order_id": order_id,
            "cooking_method": cooking_method,
            "tank_id": tank_id,
            "sold_at": _now_iso(),
        }

        _sales[sale_id] = sale

        logger.info("seafood_sale_recorded", sale_id=sale_id, species=species,
                     weight_kg=weight_kg, margin_rate=round(margin_rate, 4))
        return sale

    def calculate_yield_rate(
        self,
        species: str,
        raw_weight_kg: float,
        cooked_weight_kg: float,
    ) -> dict:
        """计算出成率

        Args:
            species: 物种代码
            raw_weight_kg: 原料重量(kg)
            cooked_weight_kg: 成品重量(kg)
        """
        if species not in SPECIES_DATABASE:
            raise ValueError(f"Unknown species: {species}")
        if raw_weight_kg <= 0:
            raise ValueError("raw_weight_kg must be positive")

        sp = SPECIES_DATABASE[species]
        actual_yield = cooked_weight_kg / raw_weight_kg
        standard_yield = sp["yield_rate"]
        deviation = actual_yield - standard_yield

        return {
            "species": species,
            "species_name_cn": sp["name_cn"],
            "raw_weight_kg": raw_weight_kg,
            "cooked_weight_kg": cooked_weight_kg,
            "actual_yield_rate": round(actual_yield, 4),
            "standard_yield_rate": standard_yield,
            "deviation": round(deviation, 4),
            "status": (
                "excellent" if deviation > 0.05 else
                "normal" if deviation >= -0.05 else
                "below_standard"
            ),
            "waste_kg": round(raw_weight_kg - cooked_weight_kg, 2),
            "waste_rate": round(1 - actual_yield, 4),
        }

    # ─── 6. Full Traceability (全链路溯源) ───

    def trace_item(self, order_item_id: str) -> dict:
        """全链路溯源 — 从订单追溯到供应商

        Args:
            order_item_id: 订单项ID（对应销售记录的 order_id）
        """
        # 查找相关销售记录
        related_sales = [s for s in _sales.values() if s.get("order_id") == order_item_id]
        if not related_sales:
            return {"order_item_id": order_item_id, "found": False, "message": "No traceability record found"}

        traces = []
        for sale in related_sales:
            batch = _batches.get(sale["batch_id"], {})
            tank_id = sale.get("tank_id") or batch.get("tank_id")
            tank = _tanks.get(tank_id, {})

            # 获取该池子的巡检记录
            inspections = _inspections.get(tank_id, [])
            inspection_summary = []
            for insp in inspections[-5:]:  # 最近5次巡检
                inspection_summary.append({
                    "date": insp["inspected_at"],
                    "inspector": insp["inspector"],
                    "mortality_kg": insp["mortality_kg"],
                    "water_quality": insp.get("water_quality"),
                })

            traces.append({
                "sale": {
                    "sale_id": sale["sale_id"],
                    "weight_kg": sale["weight_kg"],
                    "cooking_method": sale["cooking_method"],
                    "sold_at": sale["sold_at"],
                },
                "batch": {
                    "batch_id": sale["batch_id"],
                    "intake_date": batch.get("intake_date"),
                    "expiry_date": batch.get("expiry_date"),
                    "quarantine_cert": batch.get("quarantine_cert"),
                    "supplier_id": batch.get("supplier_id"),
                },
                "tank": {
                    "tank_id": tank_id,
                    "temperature": tank.get("temperature"),
                    "salinity": tank.get("salinity"),
                    "water_quality": tank.get("water_quality"),
                },
                "inspections": inspection_summary,
                "species": sale["species"],
                "species_name_cn": sale["species_name_cn"],
            })

        return {
            "order_item_id": order_item_id,
            "found": True,
            "trace_count": len(traces),
            "traces": traces,
            "traced_at": _now_iso(),
        }

    def get_batch_summary(self, batch_id: str) -> dict:
        """获取批次汇总"""
        batch = _batches.get(batch_id)
        if not batch:
            raise ValueError(f"Batch not found: {batch_id}")

        # 计算售出收入
        batch_sales = [s for s in _sales.values() if s.get("batch_id") == batch_id]
        total_revenue_fen = sum(s["sale_amount_fen"] for s in batch_sales)
        total_sold_kg = sum(s["weight_kg"] for s in batch_sales)
        avg_selling_price = int(total_revenue_fen / total_sold_kg) if total_sold_kg > 0 else 0

        # 计算利润
        total_cost_fen = batch["total_cost_fen"]
        # 成本按已售占比分摊
        sold_ratio = total_sold_kg / batch["quantity_kg"] if batch["quantity_kg"] > 0 else 0
        allocated_cost = int(total_cost_fen * sold_ratio)
        margin_fen = total_revenue_fen - allocated_cost
        margin_rate = margin_fen / total_revenue_fen if total_revenue_fen > 0 else 0

        # 损耗率
        loss_rate = batch["mortality_kg"] / batch["quantity_kg"] if batch["quantity_kg"] > 0 else 0

        return {
            "batch_id": batch_id,
            "species": batch["species"],
            "species_name_cn": batch.get("species_name_cn"),
            "supplier_id": batch["supplier_id"],
            "intake_date": batch["intake_date"],
            "expiry_date": batch["expiry_date"],
            "status": batch["status"],
            "quantity": {
                "total_intake_kg": batch["quantity_kg"],
                "mortality_kg": batch["mortality_kg"],
                "sold_kg": round(total_sold_kg, 2),
                "remaining_kg": round(batch["remaining_kg"], 2),
            },
            "financials": {
                "total_cost_fen": total_cost_fen,
                "unit_cost_fen": batch["unit_price_fen"],
                "total_revenue_fen": total_revenue_fen,
                "avg_selling_price_fen": avg_selling_price,
                "margin_fen": margin_fen,
                "margin_rate": round(margin_rate, 4),
            },
            "metrics": {
                "loss_rate": round(loss_rate, 4),
                "sell_through_rate": round(sold_ratio, 4),
                "sale_count": len(batch_sales),
            },
        }

    # ─── 7. Food Safety Compliance (食安合规) ───

    def check_compliance(self, store_id: Optional[str] = None) -> dict:
        """食品安全合规检查"""
        target_store = store_id or self.store_id
        now = datetime.now(timezone.utc)
        issues = []

        # 1. 检疫证有效性
        cert_valid = True
        for batch_id, batch in _batches.items():
            if batch.get("store_id") != target_store:
                continue
            if batch["status"] != "active":
                continue
            if not batch.get("quarantine_cert"):
                cert_valid = False
                issues.append({
                    "type": "missing_quarantine_cert",
                    "severity": "critical",
                    "detail": f"批次 {batch_id} ({batch.get('species_name_cn', batch['species'])}) 缺少检疫证",
                    "batch_id": batch_id,
                })

        # 2. 温度是否在范围内
        temp_ok = True
        for tank_id, tank in _tanks.items():
            if tank.get("store_id") != target_store:
                continue
            for sp_key in tank.get("species", []):
                sp = SPECIES_DATABASE.get(sp_key)
                if not sp:
                    continue
                if tank["temperature"] < sp["temp_min"] or tank["temperature"] > sp["temp_max"]:
                    temp_ok = False
                    issues.append({
                        "type": "temperature_out_of_range",
                        "severity": "warning",
                        "detail": f"池 {tank_id} {sp['name_cn']} 温度 {tank['temperature']}C 超出 {sp['temp_min']}-{sp['temp_max']}C",
                        "tank_id": tank_id,
                    })

        # 3. 过期批次检查
        no_expired = True
        for batch_id, batch in _batches.items():
            if batch.get("store_id") != target_store:
                continue
            if batch["status"] != "active":
                continue
            if batch.get("expiry_date"):
                expiry_dt = _parse_iso(batch["expiry_date"])
                if now > expiry_dt:
                    no_expired = False
                    issues.append({
                        "type": "expired_batch",
                        "severity": "critical",
                        "detail": f"批次 {batch_id} ({batch.get('species_name_cn')}) 已过期 (到期: {batch['expiry_date'][:10]})",
                        "batch_id": batch_id,
                    })
                elif (expiry_dt - now).days <= 2:
                    issues.append({
                        "type": "near_expiry_batch",
                        "severity": "warning",
                        "detail": f"批次 {batch_id} ({batch.get('species_name_cn')}) 即将过期 ({(expiry_dt - now).days}天后)",
                        "batch_id": batch_id,
                    })

        # 4. 溯源完整性
        traceability_complete = True
        for batch_id, batch in _batches.items():
            if batch.get("store_id") != target_store:
                continue
            if batch["status"] != "active":
                continue
            if not batch.get("supplier_id") or not batch.get("quarantine_cert") or not batch.get("tank_id"):
                traceability_complete = False
                issues.append({
                    "type": "incomplete_traceability",
                    "severity": "warning",
                    "detail": f"批次 {batch_id} 溯源信息不完整",
                    "batch_id": batch_id,
                })

        # 5. 巡检频率检查
        for tank_id, tank in _tanks.items():
            if tank.get("store_id") != target_store:
                continue
            inspections = _inspections.get(tank_id, [])
            if inspections:
                last_insp = _parse_iso(inspections[-1]["inspected_at"])
                hours_since = (now - last_insp).total_seconds() / 3600
                if hours_since > 24:
                    issues.append({
                        "type": "inspection_overdue",
                        "severity": "warning",
                        "detail": f"池 {tank_id} 超过{int(hours_since)}小时未巡检",
                        "tank_id": tank_id,
                    })
            elif tank["current_stock_kg"] > 0:
                issues.append({
                    "type": "no_inspection_record",
                    "severity": "warning",
                    "detail": f"池 {tank_id} 有库存但无巡检记录",
                    "tank_id": tank_id,
                })

        # 总体评分
        critical_count = sum(1 for i in issues if i["severity"] == "critical")
        warning_count = sum(1 for i in issues if i["severity"] == "warning")
        compliance_score = max(0, 100 - critical_count * 20 - warning_count * 5)

        return {
            "store_id": target_store,
            "checked_at": _now_iso(),
            "quarantine_cert_valid": cert_valid,
            "temp_in_range": temp_ok,
            "no_expired_batch": no_expired,
            "traceability_complete": traceability_complete,
            "compliance_score": compliance_score,
            "compliance_level": (
                "excellent" if compliance_score >= 90 else
                "good" if compliance_score >= 70 else
                "needs_improvement" if compliance_score >= 50 else
                "critical"
            ),
            "critical_issues": critical_count,
            "warning_issues": warning_count,
            "issues": issues,
        }

    def generate_safety_report(
        self,
        store_id: Optional[str] = None,
        date_range: Optional[tuple[str, str]] = None,
    ) -> dict:
        """生成食安报告"""
        target_store = store_id or self.store_id
        compliance = self.check_compliance(target_store)

        # 统计活跃批次
        active_batches = [
            b for b in _batches.values()
            if b.get("store_id") == target_store and b["status"] == "active"
        ]

        # 统计池子
        active_tanks = [
            t for t in _tanks.values()
            if t.get("store_id") == target_store and t["current_stock_kg"] > 0
        ]

        # 统计巡检
        total_inspections = 0
        total_mortality_kg = 0.0
        for tank_id, insps in _inspections.items():
            tank = _tanks.get(tank_id, {})
            if tank.get("store_id") != target_store:
                continue
            for insp in insps:
                if date_range:
                    dt = insp["inspected_at"]
                    if dt < date_range[0] or dt > date_range[1]:
                        continue
                total_inspections += 1
                total_mortality_kg += insp["mortality_kg"]

        # 统计销售
        total_sales_count = 0
        total_sales_kg = 0.0
        total_revenue_fen = 0
        for sale in _sales.values():
            if sale.get("store_id") != target_store:
                continue
            total_sales_count += 1
            total_sales_kg += sale["weight_kg"]
            total_revenue_fen += sale["sale_amount_fen"]

        total_stock_kg = sum(b["remaining_kg"] for b in active_batches)

        report = {
            "store_id": target_store,
            "report_date": _now_iso()[:10],
            "date_range": date_range,
            "compliance": compliance,
            "inventory_summary": {
                "active_batches": len(active_batches),
                "active_tanks": len(active_tanks),
                "total_stock_kg": round(total_stock_kg, 2),
                "species_breakdown": {},
            },
            "inspection_summary": {
                "total_inspections": total_inspections,
                "total_mortality_kg": round(total_mortality_kg, 2),
            },
            "sales_summary": {
                "total_sales": total_sales_count,
                "total_weight_kg": round(total_sales_kg, 2),
                "total_revenue_fen": total_revenue_fen,
            },
            "recommendations": [],
        }

        # 物种细分
        species_breakdown: dict[str, float] = {}
        for batch in active_batches:
            sp = batch["species"]
            species_breakdown[sp] = species_breakdown.get(sp, 0) + batch["remaining_kg"]
        report["inventory_summary"]["species_breakdown"] = {
            k: round(v, 2) for k, v in species_breakdown.items()
        }

        # 生成建议
        if compliance["compliance_score"] < 70:
            report["recommendations"].append("食安合规评分偏低，请立即处理关键问题")
        if total_mortality_kg > total_stock_kg * 0.1:
            report["recommendations"].append("死损率偏高，建议检查养殖环境和进货质量")
        if not active_batches:
            report["recommendations"].append("当前无活跃批次库存")

        return report
