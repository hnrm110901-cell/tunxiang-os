"""门店供给联动服务 — 门店能力 → 旅程权益动态匹配"""
import json as _json
import structlog
from typing import Any
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class GrowthStoreCapabilityService:
    """门店能力评估 → 增长策略适配

    核心能力维度:
    - has_private_room: 有包厢（宴席旅程可用）
    - has_live_seafood: 有活鲜（高端体验旅程可用）
    - has_outdoor_seating: 有露台（天气好时推荐）
    - has_delivery: 支持外卖（渠道回流可用）
    - has_stored_value: 支持储值卡（储值续航可用）
    - peak_capacity: 高峰容纳人数（影响预约推荐）
    """

    # 旅程→所需门店能力映射
    JOURNEY_CAPABILITY_MAP: dict[str, list[str]] = {
        "banquet_repurchase_v1": ["has_private_room"],
        "stored_value_renewal_v1": ["has_stored_value"],
        "channel_reflow_v1": ["has_delivery"],
        "super_user_relationship_v1": ["has_private_room"],
    }

    # 通用旅程（所有门店都支持）
    UNIVERSAL_JOURNEYS: list[str] = [
        "first_to_second_v2",
        "reactivation_loss_aversion_v2",
        "service_repair_v2",
        "psych_distance_bridge_v1",
        "milestone_celebration_v1",
        "referral_activation_v1",
    ]

    TOTAL_JOURNEY_COUNT = 10  # 特殊旅程(4) + 通用旅程(6)

    async def get_store_capabilities(
        self, store_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """获取门店能力标签（从stores.config JSON中提取）"""
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

        result = await db.execute(text("""
            SELECT store_name, config, seats, status, city, district
            FROM stores WHERE id = :sid AND is_deleted = FALSE
        """), {"sid": str(store_id)})
        row = result.fetchone()

        if not row:
            return {"ok": False, "error": "Store not found"}

        config = row[1] or {}
        if isinstance(config, str):
            config = _json.loads(config)

        capabilities: dict[str, Any] = {
            "store_id": str(store_id),
            "store_name": row[0],
            "city": row[4],
            "district": row[5],
            "seats": row[2],
            "status": row[3],
            "has_private_room": config.get("has_private_room", False),
            "has_live_seafood": config.get("has_live_seafood", False),
            "has_outdoor_seating": config.get("has_outdoor_seating", False),
            "has_delivery": config.get("has_delivery", True),
            "has_stored_value": config.get("has_stored_value", True),
            "peak_capacity": config.get("peak_capacity", row[2] or 0),
            "supported_journey_types": [],
        }

        # 计算支持的旅程类型
        for journey, required_caps in self.JOURNEY_CAPABILITY_MAP.items():
            if all(capabilities.get(cap, False) for cap in required_caps):
                capabilities["supported_journey_types"].append(journey)

        # 通用旅程所有门店都支持
        capabilities["supported_journey_types"].extend(self.UNIVERSAL_JOURNEYS)

        return capabilities

    async def match_journey_to_stores(
        self, journey_code: str, tenant_id: str, db: AsyncSession
    ) -> dict:
        """查找支持特定旅程的所有门店"""
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

        required_caps = self.JOURNEY_CAPABILITY_MAP.get(journey_code, [])

        if not required_caps:
            # 通用旅程，所有活跃门店都支持
            result = await db.execute(text("""
                SELECT id, store_name, city, district, seats
                FROM stores WHERE is_deleted = FALSE AND status = 'active'
                ORDER BY store_name
            """))
            stores = [
                {"store_id": str(r[0]), "store_name": r[1], "city": r[2], "district": r[3], "seats": r[4]}
                for r in result.fetchall()
            ]
            return {
                "journey_code": journey_code,
                "required_capabilities": [],
                "matching_stores": stores,
                "total": len(stores),
            }

        # 需要特定能力的旅程，从config JSON中过滤
        conditions = " AND ".join(
            [f"(config->>'{cap}')::boolean = true" for cap in required_caps]
        )
        result = await db.execute(text(f"""
            SELECT id, store_name, city, district, seats, config
            FROM stores
            WHERE is_deleted = FALSE AND status = 'active'
              AND {conditions}
            ORDER BY store_name
        """))
        stores = [
            {"store_id": str(r[0]), "store_name": r[1], "city": r[2], "district": r[3], "seats": r[4]}
            for r in result.fetchall()
        ]

        return {
            "journey_code": journey_code,
            "required_capabilities": required_caps,
            "matching_stores": stores,
            "total": len(stores),
        }

    async def get_store_growth_readiness(
        self, store_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """门店增长就绪度评估 — 该门店能支撑多少种旅程"""
        caps = await self.get_store_capabilities(store_id, tenant_id, db)
        if not caps.get("store_name"):
            return {"ok": False, "error": "Store not found"}

        supported = len(set(caps.get("supported_journey_types", [])))
        readiness_pct = round(supported / self.TOTAL_JOURNEY_COUNT * 100)

        # 缺失的能力建议
        missing_capabilities: list[dict] = []
        seen_caps: set[str] = set()
        for journey, required in self.JOURNEY_CAPABILITY_MAP.items():
            for cap in required:
                if not caps.get(cap, False) and cap not in seen_caps:
                    seen_caps.add(cap)
                    missing_capabilities.append({
                        "capability": cap,
                        "blocked_journey": journey,
                        "recommendation": f"开启{cap}可解锁旅程: {journey}",
                    })

        return {
            "store_id": str(store_id),
            "store_name": caps["store_name"],
            "readiness_pct": readiness_pct,
            "supported_journeys": supported,
            "total_journeys": self.TOTAL_JOURNEY_COUNT,
            "capabilities": {k: v for k, v in caps.items() if k.startswith("has_")},
            "missing_capabilities": missing_capabilities,
        }

    async def get_all_stores_readiness(
        self, tenant_id: str, db: AsyncSession
    ) -> dict:
        """所有门店增长就绪度排行"""
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

        result = await db.execute(text("""
            SELECT id, store_name, config, seats, city
            FROM stores WHERE is_deleted = FALSE AND status = 'active'
            ORDER BY store_name
        """))

        stores: list[dict] = []
        for row in result.fetchall():
            config = row[2] or {}
            if isinstance(config, str):
                config = _json.loads(config)

            supported_count = len(self.UNIVERSAL_JOURNEYS)  # 基础旅程数（所有门店都支持）
            for _journey, required_caps in self.JOURNEY_CAPABILITY_MAP.items():
                if all(config.get(cap, False) for cap in required_caps):
                    supported_count += 1

            readiness = round(supported_count / self.TOTAL_JOURNEY_COUNT * 100)
            stores.append({
                "store_id": str(row[0]),
                "store_name": row[1],
                "city": row[4],
                "seats": row[3],
                "supported_journeys": supported_count,
                "readiness_pct": readiness,
            })

        stores.sort(key=lambda s: s["readiness_pct"], reverse=True)
        return {"stores": stores, "total": len(stores)}
