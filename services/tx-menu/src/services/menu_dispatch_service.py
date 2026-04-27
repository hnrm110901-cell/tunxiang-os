"""菜单下发服务 — 全量/灰度下发、下发进度追踪

灰度策略：随机选取指定比例的门店先试验，确认 OK 后全量推送。
门店列表来源：应由调用方传入（tenant store registry），
              此服务不直接访问 org 域 DB（单一职责）。
"""

import random
from typing import Optional

import structlog

from .menu_version_service import (
    DISPATCH_STATUS_APPLIED,
    DISPATCH_STATUS_FAILED,
    DISPATCH_STATUS_PENDING,
    DISPATCH_TYPE_FULL,
    DISPATCH_TYPE_PILOT,
    MenuVersionService,
    _dispatch_records,
)

log = structlog.get_logger()


class MenuDispatchService:
    @staticmethod
    async def pilot_dispatch(
        version_id: str,
        all_store_ids: list[str],
        tenant_id: str,
        pilot_ratio: float = 0.05,
        db=None,
    ) -> dict:
        """灰度下发：随机选取 pilot_ratio 比例的门店先试验。

        Args:
            version_id: 要下发的版本 ID
            all_store_ids: 品牌下全部门店 ID 列表
            tenant_id: 租户 ID
            pilot_ratio: 灰度比例，默认 5%（至少选 1 家）

        Returns:
            dict — {"pilot_stores": [...], "records": [...], "remaining_stores": [...]}
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not all_store_ids:
            raise ValueError("all_store_ids 不能为空")
        if not (0 < pilot_ratio <= 1):
            raise ValueError(f"pilot_ratio 必须在 (0, 1] 之间，收到: {pilot_ratio}")

        # 至少选 1 家
        pilot_count = max(1, int(len(all_store_ids) * pilot_ratio))
        pilot_stores = random.sample(all_store_ids, pilot_count)
        remaining = [s for s in all_store_ids if s not in pilot_stores]

        records = await MenuVersionService.publish_to_stores(
            version_id=version_id,
            store_ids=pilot_stores,
            tenant_id=tenant_id,
            dispatch_type=DISPATCH_TYPE_PILOT,
            db=db,
        )

        log.info(
            "menu_dispatch.pilot",
            tenant_id=tenant_id,
            version_id=version_id,
            pilot_count=pilot_count,
            total_stores=len(all_store_ids),
            ratio=pilot_ratio,
        )

        return {
            "pilot_stores": pilot_stores,
            "remaining_stores": remaining,
            "records": records,
            "pilot_ratio": pilot_ratio,
            "version_id": version_id,
        }

    @staticmethod
    async def full_dispatch(
        version_id: str,
        all_store_ids: list[str],
        tenant_id: str,
        db=None,
    ) -> dict:
        """全量下发：向所有门店下发版本。

        Args:
            version_id: 要下发的版本 ID
            all_store_ids: 目标门店 ID 列表（全部门店）
            tenant_id: 租户 ID

        Returns:
            dict — {"store_count": int, "records": [...]}
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not all_store_ids:
            raise ValueError("all_store_ids 不能为空")

        records = await MenuVersionService.publish_to_stores(
            version_id=version_id,
            store_ids=all_store_ids,
            tenant_id=tenant_id,
            dispatch_type=DISPATCH_TYPE_FULL,
            db=db,
        )

        log.info(
            "menu_dispatch.full",
            tenant_id=tenant_id,
            version_id=version_id,
            store_count=len(all_store_ids),
        )

        return {
            "version_id": version_id,
            "store_count": len(all_store_ids),
            "records": records,
        }

    @staticmethod
    async def promote_pilot_to_full(
        version_id: str,
        remaining_store_ids: list[str],
        tenant_id: str,
        db=None,
    ) -> dict:
        """灰度确认后，将剩余门店全量推送。

        通常在 pilot 完成且下发状态健康后调用。

        Args:
            version_id: 版本 ID
            remaining_store_ids: 灰度时未下发的门店列表
            tenant_id: 租户 ID

        Returns:
            dict — {"promoted_count": int, "records": [...]}
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not remaining_store_ids:
            raise ValueError("remaining_store_ids 不能为空")

        records = await MenuVersionService.publish_to_stores(
            version_id=version_id,
            store_ids=remaining_store_ids,
            tenant_id=tenant_id,
            dispatch_type=DISPATCH_TYPE_FULL,
            db=db,
        )

        log.info(
            "menu_dispatch.pilot_promoted",
            tenant_id=tenant_id,
            version_id=version_id,
            promoted_count=len(remaining_store_ids),
        )

        return {
            "version_id": version_id,
            "promoted_count": len(remaining_store_ids),
            "records": records,
        }

    @staticmethod
    async def get_dispatch_status(
        version_id: str,
        tenant_id: str,
        db=None,
    ) -> dict:
        """查询版本下发进度统计。

        Returns:
            dict — {
                "version_id": str,
                "total": int,
                "applied": int,
                "pending": int,
                "failed": int,
                "apply_rate": float,  # 应用率 0.0-1.0
                "records": [...]
            }
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        records = [
            r
            for r in _dispatch_records.values()
            if r["tenant_id"] == tenant_id and r["version_id"] == version_id and not r["is_deleted"]
        ]

        total = len(records)
        applied = sum(1 for r in records if r["status"] == DISPATCH_STATUS_APPLIED)
        pending = sum(1 for r in records if r["status"] == DISPATCH_STATUS_PENDING)
        failed = sum(1 for r in records if r["status"] == DISPATCH_STATUS_FAILED)
        apply_rate = applied / total if total > 0 else 0.0

        return {
            "version_id": version_id,
            "total": total,
            "applied": applied,
            "pending": pending,
            "failed": failed,
            "apply_rate": round(apply_rate, 4),
            "records": records,
        }

    @staticmethod
    async def mark_dispatch_failed(
        record_id: str,
        tenant_id: str,
        reason: Optional[str] = None,
        db=None,
    ) -> dict:
        """标记某条下发记录为失败（门店超时或主动上报失败）。"""
        from datetime import datetime, timezone

        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        record = _dispatch_records.get(record_id)
        if not record or record["tenant_id"] != tenant_id:
            raise ValueError(f"下发记录不存在: {record_id}")

        record["status"] = DISPATCH_STATUS_FAILED
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        if reason:
            record["fail_reason"] = reason

        log.warning(
            "menu_dispatch.failed",
            tenant_id=tenant_id,
            record_id=record_id,
            reason=reason,
        )
        return record
