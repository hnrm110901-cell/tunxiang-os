"""菜单版本服务 — 创建快照、发布到门店、版本回滚、门店微调

所有操作强制 tenant_id 租户隔离。
使用 in-memory 存储（可替换为 DB 实现）。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

# ─── 版本状态常量 ───
VERSION_STATUS_DRAFT = "draft"
VERSION_STATUS_PUBLISHED = "published"
VERSION_STATUS_ARCHIVED = "archived"

# ─── 下发类型常量 ───
DISPATCH_TYPE_FULL = "full"
DISPATCH_TYPE_PILOT = "pilot"

# ─── 下发状态常量 ───
DISPATCH_STATUS_PENDING = "pending"
DISPATCH_STATUS_APPLIED = "applied"
DISPATCH_STATUS_FAILED = "failed"

log = structlog.get_logger()

# ─── In-Memory Storage ───
_versions: dict[str, dict] = {}
_dispatch_records: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── 版本管理 ───


class MenuVersionService:

    @staticmethod
    async def create_version(
        *,
        brand_id: str,
        version_name: Optional[str] = None,
        tenant_id: str,
        db=None,
        dishes_snapshot: Optional[list] = None,
        created_by: Optional[str] = None,
    ) -> dict:
        """基于当前菜品表生成快照，创建 draft 版本。

        Args:
            brand_id: 品牌 ID
            version_name: 版本名称，如 "春季新菜单"
            tenant_id: 租户 ID（强制隔离）
            db: 数据库连接（预留，当前为 in-memory）
            dishes_snapshot: 菜品快照列表；None 时可从 DB 获取
            created_by: 创建人员工 ID

        Returns:
            dict — 完整版本记录
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not brand_id:
            raise ValueError("brand_id 不能为空")

        # 生成版本号（时间戳格式）
        now = datetime.now(timezone.utc)
        quarter = (now.month - 1) // 3 + 1
        # 统计该品牌下本季度的版本数（v1, v2...）
        prefix = f"{now.year}.Q{quarter}."
        existing = [
            v for v in _versions.values()
            if v["tenant_id"] == tenant_id
            and v["brand_id"] == brand_id
            and v["version_no"].startswith(prefix)
        ]
        seq = len(existing) + 1
        version_no = f"{prefix}v{seq}"

        version_id = str(uuid.uuid4())
        version = {
            "id": version_id,
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "version_no": version_no,
            "version_name": version_name,
            "dishes_snapshot": dishes_snapshot or [],
            "status": VERSION_STATUS_DRAFT,
            "published_at": None,
            "created_by": created_by,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "is_deleted": False,
        }
        _versions[version_id] = version
        log.info(
            "menu_version.created",
            tenant_id=tenant_id,
            version_id=version_id,
            version_no=version_no,
            brand_id=brand_id,
        )
        return version

    @staticmethod
    async def get_version(version_id: str, tenant_id: str) -> Optional[dict]:
        """获取版本详情"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        v = _versions.get(version_id)
        if v and v["tenant_id"] == tenant_id and not v["is_deleted"]:
            return v
        return None

    @staticmethod
    async def list_versions(
        tenant_id: str,
        brand_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
        db=None,
    ) -> dict:
        """列出版本（按品牌筛选，分页）"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        items = [
            v for v in _versions.values()
            if v["tenant_id"] == tenant_id and not v["is_deleted"]
        ]
        if brand_id:
            items = [v for v in items if v["brand_id"] == brand_id]

        # 按创建时间降序
        items.sort(key=lambda v: v["created_at"], reverse=True)
        total = len(items)
        start = (page - 1) * size
        return {"items": items[start:start + size], "total": total, "page": page, "size": size}

    @staticmethod
    async def publish_to_stores(
        version_id: str,
        store_ids: list[str],
        tenant_id: str,
        dispatch_type: str = DISPATCH_TYPE_FULL,
        db=None,
    ) -> list[dict]:
        """下发版本到指定门店。

        每个门店创建一条 dispatch_record（pending），
        实际门店应用后通过 confirm_applied 回调更新 status=applied。

        Args:
            version_id: 版本 ID
            store_ids: 目标门店 ID 列表
            tenant_id: 租户 ID
            dispatch_type: full / pilot
            db: 数据库连接（预留）

        Returns:
            list[dict] — 创建的 dispatch_records
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not store_ids:
            raise ValueError("store_ids 不能为空")

        version = _versions.get(version_id)
        if not version or version["tenant_id"] != tenant_id or version["is_deleted"]:
            raise ValueError(f"版本不存在: {version_id}")

        if version["status"] == VERSION_STATUS_ARCHIVED:
            raise ValueError("已归档的版本不允许下发")

        # 将版本状态更新为 published（首次下发时）
        if version["status"] == VERSION_STATUS_DRAFT:
            version["status"] = VERSION_STATUS_PUBLISHED
            version["published_at"] = _now_iso()
            version["updated_at"] = _now_iso()

        records = []
        for store_id in store_ids:
            record_id = str(uuid.uuid4())
            record = {
                "id": record_id,
                "tenant_id": tenant_id,
                "version_id": version_id,
                "store_id": store_id,
                "dispatch_type": dispatch_type,
                "store_overrides": {},
                "applied_at": None,
                "status": DISPATCH_STATUS_PENDING,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "is_deleted": False,
            }
            _dispatch_records[record_id] = record
            records.append(record)

        log.info(
            "menu_version.dispatched",
            tenant_id=tenant_id,
            version_id=version_id,
            store_count=len(store_ids),
            dispatch_type=dispatch_type,
        )

        # TODO: 推送 WebSocket 通知各门店更新菜单
        # await websocket_broadcast(tenant_id, store_ids, {"event": "menu_update", "version_id": version_id})

        return records

    @staticmethod
    async def confirm_applied(
        record_id: str,
        tenant_id: str,
        db=None,
    ) -> dict:
        """门店确认应用版本后回调，更新 status=applied。"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        record = _dispatch_records.get(record_id)
        if not record or record["tenant_id"] != tenant_id:
            raise ValueError(f"下发记录不存在: {record_id}")
        record["status"] = DISPATCH_STATUS_APPLIED
        record["applied_at"] = _now_iso()
        record["updated_at"] = _now_iso()
        log.info("menu_version.applied", tenant_id=tenant_id, record_id=record_id)
        return record

    @staticmethod
    async def rollback_store(
        store_id: str,
        version_id: str,
        tenant_id: str,
        db=None,
    ) -> dict:
        """回滚门店到指定版本（创建新下发记录指向目标版本）。

        Args:
            store_id: 目标门店
            version_id: 要回滚到的版本 ID
            tenant_id: 租户 ID

        Returns:
            dict — 新建的 dispatch_record
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        version = _versions.get(version_id)
        if not version or version["tenant_id"] != tenant_id or version["is_deleted"]:
            raise ValueError(f"版本不存在: {version_id}")
        if version["status"] != VERSION_STATUS_PUBLISHED:
            raise ValueError(f"只能回滚到已发布版本，当前状态: {version['status']}")

        record_id = str(uuid.uuid4())
        record = {
            "id": record_id,
            "tenant_id": tenant_id,
            "version_id": version_id,
            "store_id": store_id,
            "dispatch_type": "rollback",
            "store_overrides": {},
            "applied_at": None,
            "status": DISPATCH_STATUS_PENDING,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "is_deleted": False,
        }
        _dispatch_records[record_id] = record
        log.info(
            "menu_version.rollback",
            tenant_id=tenant_id,
            store_id=store_id,
            version_id=version_id,
        )
        return record

    @staticmethod
    async def apply_store_override(
        store_id: str,
        overrides: dict,
        tenant_id: str,
        db=None,
    ) -> dict:
        """门店微调：在最新下发记录基础上叠加门店个性化配置。

        overrides 格式：
        {
            "add_dishes": [...],        # 本店独有菜品
            "remove_dishes": [...],     # 停售菜品 dish_id 列表
            "price_overrides": {...}    # {dish_id: price_fen} 本店价格覆盖
        }

        微调叠加在基础版本上，不修改版本本身。

        Returns:
            dict — 更新后的 dispatch_record
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not store_id:
            raise ValueError("store_id 不能为空")

        # 找该门店最新的 applied 或 pending 记录
        store_records = [
            r for r in _dispatch_records.values()
            if r["tenant_id"] == tenant_id
            and r["store_id"] == store_id
            and not r["is_deleted"]
        ]
        if not store_records:
            raise ValueError(f"门店没有下发记录: {store_id}")

        store_records.sort(key=lambda r: r["created_at"], reverse=True)
        record = store_records[0]

        # 合并 overrides（新的覆盖旧的）
        existing_overrides = record.get("store_overrides") or {}

        merged = {
            "add_dishes": overrides.get("add_dishes", existing_overrides.get("add_dishes", [])),
            "remove_dishes": overrides.get("remove_dishes", existing_overrides.get("remove_dishes", [])),
            "price_overrides": {
                **existing_overrides.get("price_overrides", {}),
                **overrides.get("price_overrides", {}),
            },
        }
        record["store_overrides"] = merged
        record["updated_at"] = _now_iso()

        log.info(
            "menu_version.store_override",
            tenant_id=tenant_id,
            store_id=store_id,
            record_id=record["id"],
        )
        return record

    @staticmethod
    async def get_store_current_version(
        store_id: str,
        tenant_id: str,
        db=None,
    ) -> Optional[dict]:
        """查询门店当前使用的版本（最新 applied 记录）"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        store_records = [
            r for r in _dispatch_records.values()
            if r["tenant_id"] == tenant_id
            and r["store_id"] == store_id
            and r["status"] == DISPATCH_STATUS_APPLIED
            and not r["is_deleted"]
        ]
        if not store_records:
            return None

        store_records.sort(key=lambda r: r["applied_at"] or "", reverse=True)
        latest_record = store_records[0]
        version = _versions.get(latest_record["version_id"])
        return {
            "dispatch_record": latest_record,
            "version": version,
        }

    @staticmethod
    async def archive_version(
        version_id: str,
        tenant_id: str,
        db=None,
    ) -> dict:
        """将版本标记为已归档"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        version = _versions.get(version_id)
        if not version or version["tenant_id"] != tenant_id or version["is_deleted"]:
            raise ValueError(f"版本不存在: {version_id}")
        version["status"] = VERSION_STATUS_ARCHIVED
        version["updated_at"] = _now_iso()
        log.info("menu_version.archived", tenant_id=tenant_id, version_id=version_id)
        return version

    @staticmethod
    async def get_dispatch_records(
        version_id: str,
        tenant_id: str,
        db=None,
    ) -> list[dict]:
        """获取某版本所有下发记录"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        return [
            r for r in _dispatch_records.values()
            if r["tenant_id"] == tenant_id
            and r["version_id"] == version_id
            and not r["is_deleted"]
        ]


# ─── 测试工具 ───


def _clear_all() -> None:
    """清空所有内存数据，仅供测试用"""
    _versions.clear()
    _dispatch_records.clear()


def _get_versions_store() -> dict:
    return _versions


def _get_dispatch_store() -> dict:
    return _dispatch_records
