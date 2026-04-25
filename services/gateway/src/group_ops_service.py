"""社群运营工具服务

GroupOpsService 负责：
- 标签管理：create_tag / list_tags / delete_tag
- 标签绑定：bind_tags / unbind_tag / get_group_tags / list_groups_by_tag / batch_bind_tags
- 群发任务：create_mass_send / execute_mass_send / get_mass_send / list_mass_sends / cancel_mass_send
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .wecom_group_service import WecomGroupService

logger = structlog.get_logger(__name__)


class GroupOpsService:
    """社群运营工具服务（标签 + 群发）"""

    def __init__(self, wecom_service: WecomGroupService | None = None) -> None:
        self._wecom = wecom_service or WecomGroupService()

    # ─────────────────────────────────────────────────────────────
    # 标签 CRUD
    # ─────────────────────────────────────────────────────────────

    async def create_tag(
        self,
        tenant_id: UUID,
        tag_group: str,
        tag_name: str,
        db: AsyncSession,
        tag_color: str = "#666",
        sort_order: int = 0,
    ) -> dict[str, Any]:
        """创建群标签"""
        log = logger.bind(tenant_id=str(tenant_id), tag_group=tag_group, tag_name=tag_name)
        tag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        try:
            await db.execute(
                text("""
                    INSERT INTO group_tags (id, tenant_id, tag_group, tag_name, tag_color, sort_order, created_at, updated_at)
                    VALUES (:id, :tenant_id, :tag_group, :tag_name, :tag_color, :sort_order, :created_at, :updated_at)
                """),
                {
                    "id": tag_id,
                    "tenant_id": tenant_id,
                    "tag_group": tag_group,
                    "tag_name": tag_name,
                    "tag_color": tag_color,
                    "sort_order": sort_order,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            log.warning("group_ops_create_tag_duplicate", error=str(exc))
            return {"success": False, "error": "标签已存在（同组同名）"}

        log.info("group_ops_tag_created", tag_id=str(tag_id))
        return {
            "success": True,
            "tag_id": str(tag_id),
            "tag_group": tag_group,
            "tag_name": tag_name,
            "tag_color": tag_color,
        }

    async def list_tags(
        self,
        tenant_id: UUID,
        db: AsyncSession,
        tag_group: str | None = None,
    ) -> list[dict[str, Any]]:
        """查询标签列表，可按标签组过滤"""
        conditions = "tenant_id = :tenant_id AND is_deleted = false"
        params: dict[str, Any] = {"tenant_id": tenant_id}
        if tag_group:
            conditions += " AND tag_group = :tag_group"
            params["tag_group"] = tag_group

        result = await db.execute(
            text(f"""
                SELECT id, tag_group, tag_name, tag_color, sort_order, created_at
                FROM group_tags
                WHERE {conditions}
                ORDER BY tag_group, sort_order, tag_name
            """),
            params,
        )
        rows = result.mappings().all()
        return [
            {
                "tag_id": str(r["id"]),
                "tag_group": r["tag_group"],
                "tag_name": r["tag_name"],
                "tag_color": r["tag_color"],
                "sort_order": r["sort_order"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    async def delete_tag(
        self,
        tenant_id: UUID,
        tag_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """删除标签（软删除，同时清除绑定关系）"""
        log = logger.bind(tenant_id=str(tenant_id), tag_id=str(tag_id))

        result = await db.execute(
            text("""
                UPDATE group_tags
                SET is_deleted = true, updated_at = :now
                WHERE id = :tag_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"tag_id": tag_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
        )

        if result.rowcount == 0:
            return {"success": False, "error": "标签不存在"}

        # 清除关联的绑定关系
        await db.execute(
            text("DELETE FROM group_tag_bindings WHERE tag_id = :tag_id AND tenant_id = :tenant_id"),
            {"tag_id": tag_id, "tenant_id": tenant_id},
        )
        await db.commit()

        log.info("group_ops_tag_deleted", tag_id=str(tag_id))
        return {"success": True}

    # ─────────────────────────────────────────────────────────────
    # 标签绑定
    # ─────────────────────────────────────────────────────────────

    async def bind_tags(
        self,
        tenant_id: UUID,
        group_chat_id: str,
        tag_ids: list[UUID],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """为群绑定标签（幂等，已存在则跳过）"""
        log = logger.bind(tenant_id=str(tenant_id), group_chat_id=group_chat_id)
        bound_count = 0

        for tag_id in tag_ids:
            try:
                await db.execute(
                    text("""
                        INSERT INTO group_tag_bindings (id, tenant_id, group_chat_id, tag_id, created_at)
                        VALUES (:id, :tenant_id, :group_chat_id, :tag_id, :created_at)
                        ON CONFLICT (tenant_id, group_chat_id, tag_id) DO NOTHING
                    """),
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "group_chat_id": group_chat_id,
                        "tag_id": tag_id,
                        "created_at": datetime.now(timezone.utc),
                    },
                )
                bound_count += 1
            except IntegrityError as exc:
                log.warning("group_ops_bind_tag_fk_error", tag_id=str(tag_id), error=str(exc))
                await db.rollback()
                return {"success": False, "error": f"标签 {tag_id} 不存在"}

        await db.commit()
        log.info("group_ops_tags_bound", count=bound_count)
        return {"success": True, "bound_count": bound_count}

    async def unbind_tag(
        self,
        tenant_id: UUID,
        group_chat_id: str,
        tag_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """解绑群标签"""
        result = await db.execute(
            text("""
                DELETE FROM group_tag_bindings
                WHERE tenant_id = :tenant_id AND group_chat_id = :group_chat_id AND tag_id = :tag_id
            """),
            {"tenant_id": tenant_id, "group_chat_id": group_chat_id, "tag_id": tag_id},
        )
        await db.commit()

        if result.rowcount == 0:
            return {"success": False, "error": "绑定关系不存在"}
        return {"success": True}

    async def get_group_tags(
        self,
        tenant_id: UUID,
        group_chat_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """获取群已绑定的标签列表"""
        result = await db.execute(
            text("""
                SELECT t.id, t.tag_group, t.tag_name, t.tag_color
                FROM group_tag_bindings b
                JOIN group_tags t ON t.id = b.tag_id AND t.is_deleted = false
                WHERE b.tenant_id = :tenant_id AND b.group_chat_id = :group_chat_id
                ORDER BY t.tag_group, t.sort_order
            """),
            {"tenant_id": tenant_id, "group_chat_id": group_chat_id},
        )
        rows = result.mappings().all()
        return [
            {
                "tag_id": str(r["id"]),
                "tag_group": r["tag_group"],
                "tag_name": r["tag_name"],
                "tag_color": r["tag_color"],
            }
            for r in rows
        ]

    async def list_groups_by_tag(
        self,
        tenant_id: UUID,
        tag_id: UUID,
        db: AsyncSession,
    ) -> list[str]:
        """查询标签下的所有群 chat_id"""
        result = await db.execute(
            text("""
                SELECT group_chat_id
                FROM group_tag_bindings
                WHERE tenant_id = :tenant_id AND tag_id = :tag_id
            """),
            {"tenant_id": tenant_id, "tag_id": tag_id},
        )
        return [row[0] for row in result.fetchall()]

    async def batch_bind_tags(
        self,
        tenant_id: UUID,
        group_chat_ids: list[str],
        tag_ids: list[UUID],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """批量为多个群绑定多个标签"""
        log = logger.bind(
            tenant_id=str(tenant_id),
            group_count=len(group_chat_ids),
            tag_count=len(tag_ids),
        )
        bound_count = 0

        for group_chat_id in group_chat_ids:
            for tag_id in tag_ids:
                try:
                    await db.execute(
                        text("""
                            INSERT INTO group_tag_bindings (id, tenant_id, group_chat_id, tag_id, created_at)
                            VALUES (:id, :tenant_id, :group_chat_id, :tag_id, :created_at)
                            ON CONFLICT (tenant_id, group_chat_id, tag_id) DO NOTHING
                        """),
                        {
                            "id": uuid.uuid4(),
                            "tenant_id": tenant_id,
                            "group_chat_id": group_chat_id,
                            "tag_id": tag_id,
                            "created_at": datetime.now(timezone.utc),
                        },
                    )
                    bound_count += 1
                except IntegrityError as exc:
                    log.warning("group_ops_batch_bind_fk_error", tag_id=str(tag_id), error=str(exc))
                    await db.rollback()
                    return {"success": False, "error": f"标签 {tag_id} 不存在"}

        await db.commit()
        log.info("group_ops_batch_tags_bound", count=bound_count)
        return {"success": True, "bound_count": bound_count}

    # ─────────────────────────────────────────────────────────────
    # 群发任务
    # ─────────────────────────────────────────────────────────────

    async def create_mass_send(
        self,
        tenant_id: UUID,
        send_name: str,
        content: dict[str, Any],
        db: AsyncSession,
        target_tag_ids: list[str] | None = None,
        exclude_tag_ids: list[str] | None = None,
        target_group_ids: list[str] | None = None,
        send_type: str = "immediate",
        scheduled_at: datetime | None = None,
        created_by: UUID | None = None,
    ) -> dict[str, Any]:
        """创建群发任务"""
        log = logger.bind(tenant_id=str(tenant_id), send_name=send_name, send_type=send_type)
        send_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        status = "draft"
        if send_type == "scheduled" and scheduled_at:
            status = "scheduled"

        await db.execute(
            text("""
                INSERT INTO group_mass_sends (
                    id, tenant_id, send_name, content,
                    target_tag_ids, exclude_tag_ids, target_group_ids,
                    send_type, scheduled_at, status,
                    created_by, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :send_name, :content::jsonb,
                    :target_tag_ids::jsonb, :exclude_tag_ids::jsonb, :target_group_ids::jsonb,
                    :send_type, :scheduled_at, :status,
                    :created_by, :created_at, :updated_at
                )
            """),
            {
                "id": send_id,
                "tenant_id": tenant_id,
                "send_name": send_name,
                "content": _json_dumps(content),
                "target_tag_ids": _json_dumps(target_tag_ids or []),
                "exclude_tag_ids": _json_dumps(exclude_tag_ids or []),
                "target_group_ids": _json_dumps(target_group_ids or []),
                "send_type": send_type,
                "scheduled_at": scheduled_at,
                "status": status,
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.commit()

        log.info("group_ops_mass_send_created", send_id=str(send_id), status=status)
        return {
            "success": True,
            "send_id": str(send_id),
            "status": status,
        }

    async def execute_mass_send(
        self,
        tenant_id: UUID,
        send_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """执行群发任务：按标签筛选群 -> 逐群发送 -> 更新记录"""
        log = logger.bind(tenant_id=str(tenant_id), send_id=str(send_id))

        # 查询群发任务
        result = await db.execute(
            text("""
                SELECT id, send_name, content, target_tag_ids, exclude_tag_ids,
                       target_group_ids, status
                FROM group_mass_sends
                WHERE id = :send_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"send_id": send_id, "tenant_id": tenant_id},
        )
        row = result.mappings().fetchone()
        if row is None:
            return {"success": False, "error": "群发任务不存在"}

        if row["status"] not in ("draft", "scheduled"):
            return {"success": False, "error": f"任务状态为 {row['status']}，不可执行"}

        # 更新为 sending
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE group_mass_sends
                SET status = 'sending', sent_at = :now, updated_at = :now
                WHERE id = :send_id AND tenant_id = :tenant_id
            """),
            {"send_id": send_id, "tenant_id": tenant_id, "now": now},
        )
        await db.commit()

        # 筛选目标群
        target_group_chat_ids = await self._resolve_target_groups(
            tenant_id=tenant_id,
            target_tag_ids=row["target_tag_ids"] or [],
            exclude_tag_ids=row["exclude_tag_ids"] or [],
            target_group_ids=row["target_group_ids"] or [],
            db=db,
        )

        total = len(target_group_chat_ids)
        sent_count = 0
        fail_count = 0

        import json

        content = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]

        # 逐群发送
        for chat_id in target_group_chat_ids:
            send_result = await self._wecom.send_group_message(
                group_chat_id=chat_id,
                message_type=content.get("msgtype", "text"),
                content=content,
                tenant_id=tenant_id,
            )
            if send_result.get("success"):
                sent_count += 1
            else:
                fail_count += 1
                log.warning(
                    "group_ops_mass_send_item_failed",
                    chat_id=chat_id,
                    error=send_result.get("error"),
                )

        # 更新完成状态
        final_status = "completed" if fail_count == 0 else ("failed" if sent_count == 0 else "completed")
        await db.execute(
            text("""
                UPDATE group_mass_sends
                SET status = :status, total_groups = :total, sent_groups = :sent,
                    failed_groups = :failed, completed_at = :now, updated_at = :now
                WHERE id = :send_id AND tenant_id = :tenant_id
            """),
            {
                "status": final_status,
                "total": total,
                "sent": sent_count,
                "failed": fail_count,
                "now": datetime.now(timezone.utc),
                "send_id": send_id,
                "tenant_id": tenant_id,
            },
        )
        await db.commit()

        log.info(
            "group_ops_mass_send_done",
            total=total,
            sent=sent_count,
            failed=fail_count,
            status=final_status,
        )
        return {
            "success": True,
            "status": final_status,
            "total_groups": total,
            "sent_groups": sent_count,
            "failed_groups": fail_count,
        }

    async def get_mass_send(
        self,
        tenant_id: UUID,
        send_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any] | None:
        """获取群发任务详情"""
        result = await db.execute(
            text("""
                SELECT id, send_name, content, target_tag_ids, exclude_tag_ids,
                       target_group_ids, send_type, scheduled_at, status,
                       total_groups, sent_groups, failed_groups,
                       created_by, sent_at, completed_at, created_at
                FROM group_mass_sends
                WHERE id = :send_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"send_id": send_id, "tenant_id": tenant_id},
        )
        row = result.mappings().fetchone()
        if row is None:
            return None

        return {
            "send_id": str(row["id"]),
            "send_name": row["send_name"],
            "content": row["content"],
            "target_tag_ids": row["target_tag_ids"],
            "exclude_tag_ids": row["exclude_tag_ids"],
            "target_group_ids": row["target_group_ids"],
            "send_type": row["send_type"],
            "scheduled_at": row["scheduled_at"].isoformat() if row["scheduled_at"] else None,
            "status": row["status"],
            "total_groups": row["total_groups"],
            "sent_groups": row["sent_groups"],
            "failed_groups": row["failed_groups"],
            "created_by": str(row["created_by"]) if row["created_by"] else None,
            "sent_at": row["sent_at"].isoformat() if row["sent_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    async def list_mass_sends(
        self,
        tenant_id: UUID,
        db: AsyncSession,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """群发任务列表（分页）"""
        conditions = "tenant_id = :tenant_id AND is_deleted = false"
        params: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            conditions += " AND status = :status"
            params["status"] = status

        # 总数
        count_result = await db.execute(
            text(f"SELECT count(*) FROM group_mass_sends WHERE {conditions}"),
            params,
        )
        total = count_result.scalar_one()

        # 列表
        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await db.execute(
            text(f"""
                SELECT id, send_name, send_type, status,
                       total_groups, sent_groups, failed_groups,
                       created_at, sent_at, completed_at
                FROM group_mass_sends
                WHERE {conditions}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()
        items = [
            {
                "send_id": str(r["id"]),
                "send_name": r["send_name"],
                "send_type": r["send_type"],
                "status": r["status"],
                "total_groups": r["total_groups"],
                "sent_groups": r["sent_groups"],
                "failed_groups": r["failed_groups"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    async def cancel_mass_send(
        self,
        tenant_id: UUID,
        send_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """取消群发任务（仅 draft/scheduled 可取消）"""
        log = logger.bind(tenant_id=str(tenant_id), send_id=str(send_id))

        result = await db.execute(
            text("""
                UPDATE group_mass_sends
                SET status = 'cancelled', updated_at = :now
                WHERE id = :send_id AND tenant_id = :tenant_id
                  AND status IN ('draft', 'scheduled') AND is_deleted = false
            """),
            {"send_id": send_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
        )
        await db.commit()

        if result.rowcount == 0:
            return {"success": False, "error": "任务不存在或状态不允许取消"}

        log.info("group_ops_mass_send_cancelled")
        return {"success": True}

    # ─────────────────────────────────────────────────────────────
    # 内部辅助
    # ─────────────────────────────────────────────────────────────

    async def _resolve_target_groups(
        self,
        tenant_id: UUID,
        target_tag_ids: list[str],
        exclude_tag_ids: list[str],
        target_group_ids: list[str],
        db: AsyncSession,
    ) -> list[str]:
        """根据标签和直接指定的群ID，解析最终发送目标群列表

        逻辑：
        1. 如果 target_group_ids 非空，直接加入候选集
        2. 如果 target_tag_ids 非空，查询绑定了这些标签的群加入候选集
        3. 如果 exclude_tag_ids 非空，从候选集中排除绑定了这些标签的群
        4. 如果 target_tag_ids 和 target_group_ids 都为空，则选择所有有绑定的群
        """
        candidate_set: set[str] = set()

        # 直接指定的群
        if target_group_ids:
            candidate_set.update(target_group_ids)

        # 按标签筛选
        if target_tag_ids:
            result = await db.execute(
                text("""
                    SELECT DISTINCT group_chat_id
                    FROM group_tag_bindings
                    WHERE tenant_id = :tenant_id AND tag_id = ANY(:tag_ids::uuid[])
                """),
                {"tenant_id": tenant_id, "tag_ids": target_tag_ids},
            )
            for row in result.fetchall():
                candidate_set.add(row[0])

        # 无筛选条件时选择所有群
        if not target_tag_ids and not target_group_ids:
            result = await db.execute(
                text("""
                    SELECT DISTINCT group_chat_id
                    FROM group_tag_bindings
                    WHERE tenant_id = :tenant_id
                """),
                {"tenant_id": tenant_id},
            )
            for row in result.fetchall():
                candidate_set.add(row[0])

        # 排除标签
        if exclude_tag_ids and candidate_set:
            result = await db.execute(
                text("""
                    SELECT DISTINCT group_chat_id
                    FROM group_tag_bindings
                    WHERE tenant_id = :tenant_id AND tag_id = ANY(:tag_ids::uuid[])
                """),
                {"tenant_id": tenant_id, "tag_ids": exclude_tag_ids},
            )
            exclude_set = {row[0] for row in result.fetchall()}
            candidate_set -= exclude_set

        return list(candidate_set)


def _json_dumps(obj: Any) -> str:
    """JSON 序列化辅助"""
    import json

    return json.dumps(obj, ensure_ascii=False)
