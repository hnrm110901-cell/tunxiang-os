"""
奥琦玮供应链增量同步服务

提供三个核心同步入口：
  - sync_purchase_orders  — 采购入库单增量拉取 + UPSERT
  - sync_suppliers        — 供应商列表同步 + UPSERT
  - sync_receiving_records — 配送出库单 → 收货记录

所有 DB 操作遵循 tx-supply 的 Repository 模式：
  Service → 直接操作 DB session（此层无独立 Repository，与项目现状一致）

增量策略：
  - 采购单/配送单：按日期区间拉取，以 external_id 去重 UPSERT
  - 供应商：全量拉取（分页），以 external_id 去重 UPSERT
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# 采购单 UPSERT 时写入的表名（与屯象现有迁移保持一致）
_PURCHASE_ORDERS_TABLE = "purchase_orders"
_SUPPLIER_PROFILES_TABLE = "supplier_profiles"
_RECEIVING_RECORDS_TABLE = "receiving_records"


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────


def _date_range(since_date: str, until_date: Optional[str] = None) -> List[str]:
    """生成 [since_date, until_date] 区间的日期字符串列表（含两端）。"""
    start = date.fromisoformat(since_date)
    end = date.fromisoformat(until_date) if until_date else date.today()
    days: List[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


# ──────────────────────────────────────────────────────────────
# 1. 采购入库单同步
# ──────────────────────────────────────────────────────────────


async def sync_purchase_orders(
    tenant_id: str,
    store_id: str,
    since_date: str,
    until_date: Optional[str] = None,
    *,
    adapter: Any,
    db: Any,
    depot_code: Optional[str] = None,
    page_size: int = 50,
) -> Dict[str, Any]:
    """从奥琦玮拉采购入库单，UPSERT 到 purchase_orders 表。

    增量策略：按 since_date ~ until_date 日期区间拉取所有采购单，
    以 (tenant_id, external_id) 为唯一键做 UPSERT。

    Args:
        tenant_id: 租户ID
        store_id: 门店ID（屯象内部）
        since_date: 起始日期 YYYY-MM-DD
        until_date: 截止日期 YYYY-MM-DD（默认今日）
        adapter: AoqiweiAdapter 实例
        db: 数据库 session（传入以支持测试注入）
        depot_code: 仓库编码过滤（可选）
        page_size: 每页条数

    Returns:
        同步统计 {"total_fetched", "upserted", "failed", "skipped"}
    """
    # 延迟导入映射层（避免循环依赖）
    import os as _os
    import sys

    _service_dir = _os.path.dirname(__file__)
    _repo_root = _os.path.abspath(_os.path.join(_service_dir, "../../../../.."))
    _mapper_dir = _os.path.join(_repo_root, "shared", "adapters", "aoqiwei", "src")
    if _mapper_dir not in sys.path:
        sys.path.insert(0, _mapper_dir)
    from supply_mapper import aoqiwei_purchase_order_to_unified  # noqa: E402

    until = until_date or date.today().isoformat()
    total_fetched = 0
    upserted = 0
    failed = 0
    skipped = 0

    # 奥琦玮 query_purchase_orders 支持日期区间，直接传入
    page = 1
    while True:
        try:
            result = await adapter.query_purchase_orders(
                start_date=since_date,
                end_date=until,
                depot_code=depot_code,
                page=page,
                page_size=page_size,
            )
        except (ValueError, RuntimeError) as exc:
            log.error(
                "aoqiwei_purchase_orders_fetch_error",
                tenant_id=tenant_id,
                store_id=store_id,
                page=page,
                error=str(exc),
            )
            failed += 1
            break

        raw_list: List[dict] = result.get("list") or [] if isinstance(result, dict) else []
        if not raw_list:
            break

        total_fetched += len(raw_list)

        for raw in raw_list:
            try:
                unified = aoqiwei_purchase_order_to_unified(raw, tenant_id, store_id)
            except (KeyError, ValueError) as exc:
                log.warning(
                    "aoqiwei_purchase_order_map_error",
                    order_no=raw.get("orderNo"),
                    tenant_id=tenant_id,
                    error=str(exc),
                )
                failed += 1
                continue

            # UPSERT 到 DB（以 external_id + tenant_id 去重）
            try:
                await _upsert_purchase_order(unified, db)
                upserted += 1
            except (KeyError, ValueError, RuntimeError) as exc:
                log.warning(
                    "aoqiwei_purchase_order_upsert_error",
                    external_id=unified.get("external_id"),
                    tenant_id=tenant_id,
                    error=str(exc),
                )
                failed += 1

        total_in_db = result.get("total", 0) if isinstance(result, dict) else 0
        if len(raw_list) < page_size or total_fetched >= total_in_db:
            break
        page += 1

    log.info(
        "aoqiwei_purchase_orders_synced",
        tenant_id=tenant_id,
        store_id=store_id,
        since_date=since_date,
        until_date=until,
        total_fetched=total_fetched,
        upserted=upserted,
        failed=failed,
        skipped=skipped,
    )
    return {
        "total_fetched": total_fetched,
        "upserted": upserted,
        "failed": failed,
        "skipped": skipped,
    }


async def _upsert_purchase_order(unified: dict, db: Any) -> None:
    """将统一格式采购单写入 DB（INSERT OR UPDATE）。

    DB session 约定：db 具有 execute(sql, params) 异步方法。
    实际项目中替换为 SQLAlchemy / asyncpg UPSERT 语句。
    """
    import json

    sql = f"""
        INSERT INTO {_PURCHASE_ORDERS_TABLE}
            (id, external_id, source, tenant_id, store_id, supplier_id,
             order_date, total_amount, status, items, remark, depot_code,
             created_at, updated_at)
        VALUES
            (:id, :external_id, :source, :tenant_id, :store_id, :supplier_id,
             :order_date, :total_amount, :status, :items, :remark, :depot_code,
             NOW(), NOW())
        ON CONFLICT (tenant_id, external_id, source)
        DO UPDATE SET
            status = EXCLUDED.status,
            total_amount = EXCLUDED.total_amount,
            items = EXCLUDED.items,
            updated_at = NOW()
    """
    params = dict(unified)
    params["items"] = json.dumps(unified.get("items") or [], ensure_ascii=False)
    await db.execute(sql, params)


# ──────────────────────────────────────────────────────────────
# 2. 供应商同步
# ──────────────────────────────────────────────────────────────


async def sync_suppliers(
    tenant_id: str,
    *,
    adapter: Any,
    db: Any,
    page_size: int = 100,
) -> Dict[str, Any]:
    """从奥琦玮拉全量供应商列表，UPSERT 到 supplier_profiles 表。

    供应商数量通常不大（百~千量级），全量拉取分页即可。

    Args:
        tenant_id: 租户ID
        adapter: AoqiweiAdapter 实例
        db: 数据库 session
        page_size: 每页条数

    Returns:
        同步统计 {"total_fetched", "upserted", "failed"}
    """
    import os as _os
    import sys

    _service_dir = _os.path.dirname(__file__)
    _repo_root = _os.path.abspath(_os.path.join(_service_dir, "../../../../.."))
    _mapper_dir = _os.path.join(_repo_root, "shared", "adapters", "aoqiwei", "src")
    if _mapper_dir not in sys.path:
        sys.path.insert(0, _mapper_dir)
    from supply_mapper import aoqiwei_supplier_to_unified  # noqa: E402

    total_fetched = 0
    upserted = 0
    failed = 0
    page = 1

    while True:
        try:
            result = await adapter.query_suppliers(page=page, page_size=page_size)
        except (ValueError, RuntimeError) as exc:
            log.error(
                "aoqiwei_suppliers_fetch_error",
                tenant_id=tenant_id,
                page=page,
                error=str(exc),
            )
            failed += 1
            break

        raw_list: List[dict] = result.get("list") or [] if isinstance(result, dict) else []
        if not raw_list:
            break

        total_fetched += len(raw_list)

        for raw in raw_list:
            try:
                unified = aoqiwei_supplier_to_unified(raw, tenant_id)
            except (KeyError, ValueError) as exc:
                log.warning(
                    "aoqiwei_supplier_map_error",
                    supplier_code=raw.get("supplierCode"),
                    tenant_id=tenant_id,
                    error=str(exc),
                )
                failed += 1
                continue

            try:
                await _upsert_supplier(unified, db)
                upserted += 1
            except (KeyError, ValueError, RuntimeError) as exc:
                log.warning(
                    "aoqiwei_supplier_upsert_error",
                    external_id=unified.get("external_id"),
                    tenant_id=tenant_id,
                    error=str(exc),
                )
                failed += 1

        total_in_db = result.get("total", 0) if isinstance(result, dict) else 0
        if len(raw_list) < page_size or total_fetched >= total_in_db:
            break
        page += 1

    log.info(
        "aoqiwei_suppliers_synced",
        tenant_id=tenant_id,
        total_fetched=total_fetched,
        upserted=upserted,
        failed=failed,
    )
    return {
        "total_fetched": total_fetched,
        "upserted": upserted,
        "failed": failed,
    }


async def _upsert_supplier(unified: dict, db: Any) -> None:
    """将统一格式供应商写入 DB。"""
    import json

    sql = f"""
        INSERT INTO {_SUPPLIER_PROFILES_TABLE}
            (id, external_id, source, tenant_id, name, contact_name,
             contact_phone, categories, address, is_active,
             created_at, updated_at)
        VALUES
            (:id, :external_id, :source, :tenant_id, :name, :contact_name,
             :contact_phone, :categories, :address, :is_active,
             NOW(), NOW())
        ON CONFLICT (tenant_id, external_id, source)
        DO UPDATE SET
            name = EXCLUDED.name,
            contact_name = EXCLUDED.contact_name,
            contact_phone = EXCLUDED.contact_phone,
            categories = EXCLUDED.categories,
            address = EXCLUDED.address,
            is_active = EXCLUDED.is_active,
            updated_at = NOW()
    """
    params = dict(unified)
    params["categories"] = json.dumps(unified.get("categories") or [], ensure_ascii=False)
    await db.execute(sql, params)


# ──────────────────────────────────────────────────────────────
# 3. 配送出库单 → 收货记录同步
# ──────────────────────────────────────────────────────────────


async def sync_receiving_records(
    tenant_id: str,
    store_id: str,
    since_date: str,
    until_date: Optional[str] = None,
    *,
    adapter: Any,
    db: Any,
    shop_code: Optional[str] = None,
) -> Dict[str, Any]:
    """从奥琦玮拉配送出库单，转为收货记录写入 DB。

    配送出库单代表仓库向门店发货，门店侧应创建对应的收货验收记录。
    此函数使用 receiving_service.create_receiving() 的逻辑，但直接写 DB
    以支持批量同步场景。

    Args:
        tenant_id: 租户ID
        store_id: 门店ID（屯象内部）
        since_date: 起始日期 YYYY-MM-DD
        until_date: 截止日期 YYYY-MM-DD（默认今日）
        adapter: AoqiweiAdapter 实例
        db: 数据库 session
        shop_code: 奥琦玮门店编码过滤（可选）

    Returns:
        同步统计 {"total_fetched", "upserted", "failed"}
    """
    import os as _os
    import sys

    _service_dir = _os.path.dirname(__file__)
    _repo_root = _os.path.abspath(_os.path.join(_service_dir, "../../../../.."))
    _mapper_dir = _os.path.join(_repo_root, "shared", "adapters", "aoqiwei", "src")
    if _mapper_dir not in sys.path:
        sys.path.insert(0, _mapper_dir)
    from supply_mapper import aoqiwei_dispatch_to_receiving  # noqa: E402

    until = until_date or date.today().isoformat()
    total_fetched = 0
    upserted = 0
    failed = 0

    try:
        raw_list: List[dict] = await adapter.query_delivery_dispatch_out(
            start_date=since_date,
            end_date=until,
            shop_code=shop_code,
        )
    except (ValueError, RuntimeError) as exc:
        log.error(
            "aoqiwei_dispatch_fetch_error",
            tenant_id=tenant_id,
            store_id=store_id,
            error=str(exc),
        )
        return {"total_fetched": 0, "upserted": 0, "failed": 1}

    total_fetched = len(raw_list)

    for raw in raw_list:
        try:
            receiving = aoqiwei_dispatch_to_receiving(raw, tenant_id, store_id)
        except (KeyError, ValueError) as exc:
            log.warning(
                "aoqiwei_dispatch_map_error",
                dispatch_no=raw.get("dispatchOrderNo"),
                tenant_id=tenant_id,
                error=str(exc),
            )
            failed += 1
            continue

        try:
            await _upsert_receiving_record(receiving, db)
            upserted += 1
        except (KeyError, ValueError, RuntimeError) as exc:
            log.warning(
                "aoqiwei_receiving_upsert_error",
                dispatch_no=receiving.get("external_dispatch_no"),
                tenant_id=tenant_id,
                error=str(exc),
            )
            failed += 1

    log.info(
        "aoqiwei_receiving_records_synced",
        tenant_id=tenant_id,
        store_id=store_id,
        since_date=since_date,
        until_date=until,
        total_fetched=total_fetched,
        upserted=upserted,
        failed=failed,
    )
    return {
        "total_fetched": total_fetched,
        "upserted": upserted,
        "failed": failed,
    }


async def _upsert_receiving_record(receiving: dict, db: Any) -> None:
    """将配送出库单转换的收货记录写入 DB。"""
    import json

    record_id = f"rcv_aq_{uuid.uuid4().hex[:8]}"

    sql = f"""
        INSERT INTO {_RECEIVING_RECORDS_TABLE}
            (id, external_dispatch_no, source, tenant_id, store_id,
             shop_code, dispatch_date, items, item_count,
             status, created_at, updated_at)
        VALUES
            (:id, :external_dispatch_no, :source, :tenant_id, :store_id,
             :shop_code, :dispatch_date, :items, :item_count,
             'pending_review', NOW(), NOW())
        ON CONFLICT (tenant_id, external_dispatch_no, source)
        DO UPDATE SET
            items = EXCLUDED.items,
            item_count = EXCLUDED.item_count,
            updated_at = NOW()
    """
    params = dict(receiving)
    params["id"] = record_id
    params["items"] = json.dumps(receiving.get("items") or [], ensure_ascii=False)
    await db.execute(sql, params)
