"""企业素材库服务

MaterialService 负责：
- 分组管理：create_group / list_groups(树结构) / update_group / delete_group
- 素材 CRUD：create / update / get / list(筛选) / delete
- 时段匹配：get_current_materials（根据当前时间匹配 time_slots）
- 使用计数：increment_usage
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class MaterialService:
    """企业素材库服务"""

    # ─────────────────────────────────────────────────────────────
    # 分组管理
    # ─────────────────────────────────────────────────────────────

    async def create_group(
        self,
        tenant_id: UUID,
        group_name: str,
        db: AsyncSession,
        parent_id: UUID | None = None,
        icon: str | None = None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        """创建素材分组"""
        log = logger.bind(tenant_id=str(tenant_id), group_name=group_name)
        group_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # 验证 parent_id 存在性
        if parent_id:
            check = await db.execute(
                text("""
                    SELECT id FROM material_groups
                    WHERE id = :parent_id AND tenant_id = :tenant_id AND is_deleted = false
                """),
                {"parent_id": parent_id, "tenant_id": tenant_id},
            )
            if check.fetchone() is None:
                return {"success": False, "error": "父分组不存在"}

        await db.execute(
            text("""
                INSERT INTO material_groups (id, tenant_id, group_name, parent_id, icon, sort_order, created_at, updated_at)
                VALUES (:id, :tenant_id, :group_name, :parent_id, :icon, :sort_order, :created_at, :updated_at)
            """),
            {
                "id": group_id,
                "tenant_id": tenant_id,
                "group_name": group_name,
                "parent_id": parent_id,
                "icon": icon,
                "sort_order": sort_order,
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.commit()

        log.info("material_group_created", group_id=str(group_id))
        return {
            "success": True,
            "group_id": str(group_id),
            "group_name": group_name,
            "parent_id": str(parent_id) if parent_id else None,
        }

    async def list_groups(
        self,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """查询素材分组（递归 CTE 构建树结构）"""
        result = await db.execute(
            text("""
                WITH RECURSIVE group_tree AS (
                    SELECT id, group_name, parent_id, icon, sort_order, 0 AS depth
                    FROM material_groups
                    WHERE tenant_id = :tenant_id AND parent_id IS NULL AND is_deleted = false
                    UNION ALL
                    SELECT g.id, g.group_name, g.parent_id, g.icon, g.sort_order, gt.depth + 1
                    FROM material_groups g
                    JOIN group_tree gt ON g.parent_id = gt.id
                    WHERE g.tenant_id = :tenant_id AND g.is_deleted = false
                )
                SELECT id, group_name, parent_id, icon, sort_order, depth
                FROM group_tree
                ORDER BY depth, sort_order, group_name
            """),
            {"tenant_id": tenant_id},
        )
        rows = result.mappings().all()

        # 构建树结构
        nodes: dict[str, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []

        for r in rows:
            node = {
                "group_id": str(r["id"]),
                "group_name": r["group_name"],
                "parent_id": str(r["parent_id"]) if r["parent_id"] else None,
                "icon": r["icon"],
                "sort_order": r["sort_order"],
                "children": [],
            }
            nodes[str(r["id"])] = node

            parent_key = str(r["parent_id"]) if r["parent_id"] else None
            if parent_key and parent_key in nodes:
                nodes[parent_key]["children"].append(node)
            else:
                roots.append(node)

        return roots

    async def update_group(
        self,
        tenant_id: UUID,
        group_id: UUID,
        db: AsyncSession,
        group_name: str | None = None,
        parent_id: UUID | None = None,
        icon: str | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any]:
        """更新素材分组"""
        sets: list[str] = ["updated_at = :now"]
        params: dict[str, Any] = {
            "group_id": group_id,
            "tenant_id": tenant_id,
            "now": datetime.now(timezone.utc),
        }

        if group_name is not None:
            sets.append("group_name = :group_name")
            params["group_name"] = group_name
        if parent_id is not None:
            sets.append("parent_id = :parent_id")
            params["parent_id"] = parent_id
        if icon is not None:
            sets.append("icon = :icon")
            params["icon"] = icon
        if sort_order is not None:
            sets.append("sort_order = :sort_order")
            params["sort_order"] = sort_order

        result = await db.execute(
            text(f"""
                UPDATE material_groups
                SET {", ".join(sets)}
                WHERE id = :group_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            params,
        )
        await db.commit()

        if result.rowcount == 0:
            return {"success": False, "error": "分组不存在"}
        return {"success": True}

    async def delete_group(
        self,
        tenant_id: UUID,
        group_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """删除素材分组（软删除，子分组和关联素材的 group_id 置空）"""
        log = logger.bind(tenant_id=str(tenant_id), group_id=str(group_id))
        now = datetime.now(timezone.utc)

        # 检查存在
        check = await db.execute(
            text("""
                SELECT id FROM material_groups
                WHERE id = :group_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"group_id": group_id, "tenant_id": tenant_id},
        )
        if check.fetchone() is None:
            return {"success": False, "error": "分组不存在"}

        # 子分组的 parent_id 置空
        await db.execute(
            text("""
                UPDATE material_groups SET parent_id = NULL, updated_at = :now
                WHERE parent_id = :group_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"group_id": group_id, "tenant_id": tenant_id, "now": now},
        )

        # 关联素材的 group_id 置空
        await db.execute(
            text("""
                UPDATE material_library SET group_id = NULL, updated_at = :now
                WHERE group_id = :group_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"group_id": group_id, "tenant_id": tenant_id, "now": now},
        )

        # 软删除分组
        await db.execute(
            text("""
                UPDATE material_groups SET is_deleted = true, updated_at = :now
                WHERE id = :group_id AND tenant_id = :tenant_id
            """),
            {"group_id": group_id, "tenant_id": tenant_id, "now": now},
        )
        await db.commit()

        log.info("material_group_deleted")
        return {"success": True}

    # ─────────────────────────────────────────────────────────────
    # 素材 CRUD
    # ─────────────────────────────────────────────────────────────

    async def create_material(
        self,
        tenant_id: UUID,
        title: str,
        material_type: str,
        db: AsyncSession,
        group_id: UUID | None = None,
        content: str | None = None,
        media_url: str | None = None,
        thumbnail_url: str | None = None,
        link_url: str | None = None,
        link_title: str | None = None,
        miniapp_appid: str | None = None,
        miniapp_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        time_slots: list[dict[str, str]] | None = None,
        tags: list[str] | None = None,
        is_template: bool = False,
        sort_order: int = 0,
        created_by: UUID | None = None,
    ) -> dict[str, Any]:
        """创建素材"""
        log = logger.bind(tenant_id=str(tenant_id), title=title, material_type=material_type)
        mat_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await db.execute(
            text("""
                INSERT INTO material_library (
                    id, tenant_id, group_id, title, material_type,
                    content, media_url, thumbnail_url, link_url, link_title,
                    miniapp_appid, miniapp_path, metadata, time_slots, tags,
                    is_template, sort_order, created_by, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :group_id, :title, :material_type,
                    :content, :media_url, :thumbnail_url, :link_url, :link_title,
                    :miniapp_appid, :miniapp_path, :metadata::jsonb, :time_slots::jsonb, :tags::jsonb,
                    :is_template, :sort_order, :created_by, :created_at, :updated_at
                )
            """),
            {
                "id": mat_id,
                "tenant_id": tenant_id,
                "group_id": group_id,
                "title": title,
                "material_type": material_type,
                "content": content,
                "media_url": media_url,
                "thumbnail_url": thumbnail_url,
                "link_url": link_url,
                "link_title": link_title,
                "miniapp_appid": miniapp_appid,
                "miniapp_path": miniapp_path,
                "metadata": json.dumps(metadata or {}, ensure_ascii=False),
                "time_slots": json.dumps(time_slots or [], ensure_ascii=False),
                "tags": json.dumps(tags or [], ensure_ascii=False),
                "is_template": is_template,
                "sort_order": sort_order,
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.commit()

        log.info("material_created", material_id=str(mat_id))
        return {
            "success": True,
            "material_id": str(mat_id),
            "title": title,
            "material_type": material_type,
        }

    async def update_material(
        self,
        tenant_id: UUID,
        material_id: UUID,
        db: AsyncSession,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """更新素材（只更新传入的字段）"""
        allowed_fields = {
            "title",
            "group_id",
            "content",
            "media_url",
            "thumbnail_url",
            "link_url",
            "link_title",
            "miniapp_appid",
            "miniapp_path",
            "is_template",
            "sort_order",
        }
        jsonb_fields = {"metadata", "time_slots", "tags"}

        sets: list[str] = ["updated_at = :now"]
        params: dict[str, Any] = {
            "material_id": material_id,
            "tenant_id": tenant_id,
            "now": datetime.now(timezone.utc),
        }

        for key, val in kwargs.items():
            if val is None:
                continue
            if key in allowed_fields:
                sets.append(f"{key} = :{key}")
                params[key] = val
            elif key in jsonb_fields:
                sets.append(f"{key} = :{key}::jsonb")
                params[key] = json.dumps(val, ensure_ascii=False)

        if len(sets) == 1:
            return {"success": False, "error": "无可更新字段"}

        result = await db.execute(
            text(f"""
                UPDATE material_library
                SET {", ".join(sets)}
                WHERE id = :material_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            params,
        )
        await db.commit()

        if result.rowcount == 0:
            return {"success": False, "error": "素材不存在"}
        return {"success": True}

    async def get_material(
        self,
        tenant_id: UUID,
        material_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any] | None:
        """获取素材详情"""
        result = await db.execute(
            text("""
                SELECT id, group_id, title, material_type,
                       content, media_url, thumbnail_url, link_url, link_title,
                       miniapp_appid, miniapp_path, metadata, time_slots, tags,
                       usage_count, is_template, sort_order, created_by,
                       created_at, updated_at
                FROM material_library
                WHERE id = :material_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"material_id": material_id, "tenant_id": tenant_id},
        )
        row = result.mappings().fetchone()
        if row is None:
            return None

        return _material_row_to_dict(row)

    async def list_materials(
        self,
        tenant_id: UUID,
        db: AsyncSession,
        group_id: UUID | None = None,
        material_type: str | None = None,
        keyword: str | None = None,
        is_template: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """素材列表（分页 + 筛选）"""
        conditions = "tenant_id = :tenant_id AND is_deleted = false"
        params: dict[str, Any] = {"tenant_id": tenant_id}

        if group_id is not None:
            conditions += " AND group_id = :group_id"
            params["group_id"] = group_id
        if material_type:
            conditions += " AND material_type = :material_type"
            params["material_type"] = material_type
        if keyword:
            conditions += " AND title ILIKE :keyword"
            params["keyword"] = f"%{keyword}%"
        if is_template is not None:
            conditions += " AND is_template = :is_template"
            params["is_template"] = is_template

        # 总数
        count_result = await db.execute(
            text(f"SELECT count(*) FROM material_library WHERE {conditions}"),
            params,
        )
        total = count_result.scalar_one()

        # 列表
        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await db.execute(
            text(f"""
                SELECT id, group_id, title, material_type,
                       content, media_url, thumbnail_url, link_url, link_title,
                       miniapp_appid, miniapp_path, metadata, time_slots, tags,
                       usage_count, is_template, sort_order, created_by,
                       created_at, updated_at
                FROM material_library
                WHERE {conditions}
                ORDER BY sort_order, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()
        items = [_material_row_to_dict(r) for r in rows]
        return {"items": items, "total": total, "page": page, "size": size}

    async def delete_material(
        self,
        tenant_id: UUID,
        material_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """删除素材（软删除）"""
        result = await db.execute(
            text("""
                UPDATE material_library
                SET is_deleted = true, updated_at = :now
                WHERE id = :material_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"material_id": material_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
        )
        await db.commit()

        if result.rowcount == 0:
            return {"success": False, "error": "素材不存在"}
        return {"success": True}

    # ─────────────────────────────────────────────────────────────
    # 时段匹配
    # ─────────────────────────────────────────────────────────────

    async def get_current_materials(
        self,
        tenant_id: UUID,
        db: AsyncSession,
        material_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """根据当前时间匹配 time_slots 中的素材

        time_slots 结构: [{"start": "08:00", "end": "12:00", "label": "早餐"}, ...]
        匹配逻辑：当前时间在任一 slot 的 start-end 范围内，或 time_slots 为空（全天素材）
        """
        now = datetime.now(timezone.utc)
        current_time = now.strftime("%H:%M")

        conditions = "tenant_id = :tenant_id AND is_deleted = false"
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "current_time": current_time,
            "limit": limit,
        }
        if material_type:
            conditions += " AND material_type = :material_type"
            params["material_type"] = material_type

        # 匹配：time_slots 为空数组（全天）或当前时间落在某 slot 内
        result = await db.execute(
            text(f"""
                SELECT id, group_id, title, material_type,
                       content, media_url, thumbnail_url, link_url, link_title,
                       miniapp_appid, miniapp_path, metadata, time_slots, tags,
                       usage_count, is_template, sort_order, created_by,
                       created_at, updated_at
                FROM material_library
                WHERE {conditions}
                  AND (
                      time_slots = '[]'::jsonb
                      OR EXISTS (
                          SELECT 1 FROM jsonb_array_elements(time_slots) AS slot
                          WHERE :current_time >= (slot->>'start')
                            AND :current_time <= (slot->>'end')
                      )
                  )
                ORDER BY sort_order, usage_count DESC
                LIMIT :limit
            """),
            params,
        )
        rows = result.mappings().all()
        return [_material_row_to_dict(r) for r in rows]

    # ─────────────────────────────────────────────────────────────
    # 使用计数
    # ─────────────────────────────────────────────────────────────

    async def increment_usage(
        self,
        tenant_id: UUID,
        material_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """素材使用次数 +1"""
        result = await db.execute(
            text("""
                UPDATE material_library
                SET usage_count = usage_count + 1, updated_at = :now
                WHERE id = :material_id AND tenant_id = :tenant_id AND is_deleted = false
                RETURNING usage_count
            """),
            {"material_id": material_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
        )
        row = result.fetchone()
        await db.commit()

        if row is None:
            return {"success": False, "error": "素材不存在"}
        return {"success": True, "usage_count": row[0]}


def _material_row_to_dict(r: Any) -> dict[str, Any]:
    """将素材行转换为字典"""
    return {
        "material_id": str(r["id"]),
        "group_id": str(r["group_id"]) if r["group_id"] else None,
        "title": r["title"],
        "material_type": r["material_type"],
        "content": r["content"],
        "media_url": r["media_url"],
        "thumbnail_url": r["thumbnail_url"],
        "link_url": r["link_url"],
        "link_title": r["link_title"],
        "miniapp_appid": r["miniapp_appid"],
        "miniapp_path": r["miniapp_path"],
        "metadata": r["metadata"],
        "time_slots": r["time_slots"],
        "tags": r["tags"],
        "usage_count": r["usage_count"],
        "is_template": r["is_template"],
        "sort_order": r["sort_order"],
        "created_by": str(r["created_by"]) if r["created_by"] else None,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }
