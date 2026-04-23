"""
消防安全管理 — Fire Safety Management

消防设备登记、巡检记录、待检清单。
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import text

from shared.ontology.src.database import TenantSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 标准消防巡检清单模板
# ---------------------------------------------------------------------------
FIRE_CHECKLIST: list[dict[str, str]] = [
    {"item": "灭火器", "check": "压力表指针在绿色区域，瓶体无锈蚀"},
    {"item": "烟感报警器", "check": "指示灯正常闪烁，测试按钮功能正常"},
    {"item": "消防栓", "check": "箱门完好，水枪水带齐全，阀门开启灵活"},
    {"item": "安全出口", "check": "指示灯常亮，通道畅通无堆放杂物"},
    {"item": "应急照明", "check": "主电正常指示灯亮，按测试键灯具点亮"},
    {"item": "燃气阀门", "check": "接口无泄漏，紧急切断阀可正常操作"},
    {"item": "油烟管道", "check": "无油垢积聚过厚，防火阀完好"},
    {"item": "电气线路", "check": "无裸露电线，配电箱门关闭，无超负荷迹象"},
    {"item": "消防通道", "check": "内外通道畅通，无锁闭，无堆放物"},
    {"item": "灭火毯", "check": "完好无损，取用方便，位于厨房显眼处"},
]


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def is_inspection_overdue(next_date: date | str | None, today: date | None = None) -> bool:
    """判断是否逾期未检。"""
    if next_date is None:
        return True
    if isinstance(next_date, str):
        next_date = date.fromisoformat(next_date)
    if today is None:
        today = date.today()
    return today > next_date


# ---------------------------------------------------------------------------
# 业务服务
# ---------------------------------------------------------------------------


async def register_equipment(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
) -> dict:
    """登记消防设备。

    data: equipment_type, location, model, manufacture_date,
          last_inspection_date, next_inspection_date, serial_no
    """
    equip_id = str(uuid.uuid4())

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_fire_equipment "
                "(id, tenant_id, store_id, equipment_type, location, model, "
                " serial_no, manufacture_date, last_inspection_date, "
                " next_inspection_date, status, created_at) "
                "VALUES (:id, :tenant_id, :store_id, :equipment_type, :location, "
                " :model, :serial_no, :manufacture_date, :last_inspection_date, "
                " :next_inspection_date, 'active', NOW())"
            ),
            {
                "id": equip_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "equipment_type": data["equipment_type"],
                "location": data.get("location"),
                "model": data.get("model"),
                "serial_no": data.get("serial_no"),
                "manufacture_date": data.get("manufacture_date"),
                "last_inspection_date": data.get("last_inspection_date"),
                "next_inspection_date": data.get("next_inspection_date"),
            },
        )
        await db.commit()

    logger.info("fire_equipment_registered", tenant_id=tenant_id, equip_id=equip_id, type=data["equipment_type"])
    return {"id": equip_id, "status": "active", **data}


async def get_equipment(tenant_id: str, store_id: str) -> list[dict]:
    """设备列表。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT id, equipment_type, location, model, serial_no, "
                "  manufacture_date, last_inspection_date, next_inspection_date, "
                "  status, created_at "
                "FROM civic_fire_equipment "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "ORDER BY next_inspection_date NULLS FIRST"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        results = []
        for r in rows.mappings().all():
            row = dict(r)
            row["overdue"] = is_inspection_overdue(row.get("next_inspection_date"))
            results.append(row)

    return results


async def get_equipment_due(tenant_id: str, days: int = 7) -> list[dict]:
    """待检设备清单 — 全品牌中N天内需要检查的设备。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT e.id, e.store_id, e.equipment_type, e.location, "
                "  e.serial_no, e.last_inspection_date, e.next_inspection_date "
                "FROM civic_fire_equipment e "
                "WHERE e.tenant_id = :tenant_id AND e.status = 'active' "
                "  AND (e.next_inspection_date IS NULL "
                "       OR e.next_inspection_date <= CURRENT_DATE + :days) "
                "ORDER BY e.next_inspection_date NULLS FIRST"
            ),
            {"tenant_id": tenant_id, "days": days},
        )
        results = []
        for r in rows.mappings().all():
            row = dict(r)
            row["overdue"] = is_inspection_overdue(row.get("next_inspection_date"))
            if row.get("next_inspection_date") and isinstance(row["next_inspection_date"], date):
                row["days_until_due"] = (row["next_inspection_date"] - date.today()).days
            else:
                row["days_until_due"] = None
            results.append(row)

    logger.info("equipment_due_checked", tenant_id=tenant_id, due_count=len(results))
    return results


async def record_inspection(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
) -> dict:
    """记录巡检。

    data: inspector, inspection_date, checklist_results(list of {item, passed, note}),
          equipment_ids(可选，关联设备), overall_passed
    """
    inspection_id = str(uuid.uuid4())
    checklist_results = data.get("checklist_results", [])
    total_items = len(checklist_results)
    passed_items = sum(1 for c in checklist_results if c.get("passed"))
    overall = data.get("overall_passed", passed_items == total_items and total_items > 0)

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_fire_inspections "
                "(id, tenant_id, store_id, inspector, inspection_date, "
                " total_items, passed_items, overall_passed, "
                " checklist_json, notes, created_at) "
                "VALUES (:id, :tenant_id, :store_id, :inspector, "
                " COALESCE(:inspection_date, CURRENT_DATE), "
                " :total_items, :passed_items, :overall_passed, "
                " :checklist_json, :notes, NOW())"
            ),
            {
                "id": inspection_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "inspector": data["inspector"],
                "inspection_date": data.get("inspection_date"),
                "total_items": total_items,
                "passed_items": passed_items,
                "overall_passed": overall,
                "checklist_json": json.dumps(checklist_results, ensure_ascii=False, default=str),
                "notes": data.get("notes"),
            },
        )

        # 更新关联设备的检查日期
        equipment_ids = data.get("equipment_ids", [])
        inspection_date = data.get("inspection_date", date.today().isoformat())
        for eid in equipment_ids:
            await db.execute(
                text(
                    "UPDATE civic_fire_equipment "
                    "SET last_inspection_date = :inspection_date, "
                    "    next_inspection_date = :inspection_date::date + INTERVAL '30 days', "
                    "    updated_at = NOW() "
                    "WHERE tenant_id = :tenant_id AND id = :equipment_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "equipment_id": eid,
                    "inspection_date": inspection_date,
                },
            )

        await db.commit()

    logger.info(
        "fire_inspection_recorded",
        tenant_id=tenant_id,
        inspection_id=inspection_id,
        passed=passed_items,
        total=total_items,
    )
    return {
        "id": inspection_id,
        "total_items": total_items,
        "passed_items": passed_items,
        "overall_passed": overall,
    }


async def get_inspections(
    tenant_id: str,
    store_id: str,
    page: int = 1,
    size: int = 20,
) -> dict:
    """巡检历史。"""
    offset = (page - 1) * size

    async with TenantSession(tenant_id) as db:
        count_result = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM civic_fire_inspections "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                "SELECT id, inspector, inspection_date, total_items, passed_items, "
                "  overall_passed, notes, created_at "
                "FROM civic_fire_inspections "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "ORDER BY inspection_date DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {"tenant_id": tenant_id, "store_id": store_id, "limit": size, "offset": offset},
        )
        items = [dict(r) for r in rows.mappings().all()]

    return {"total": total, "page": page, "size": size, "items": items}
