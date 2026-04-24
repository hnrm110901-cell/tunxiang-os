"""电子邀请函服务 — S7 宴会电子邀请函

功能：
  - 邀请函模板 CRUD（系统预置 + 租户自定义）
  - 邀请函实例创建/发布/获取
  - 公开访问（通过 share_code，无需认证）
  - 浏览量记录
  - RSVP 回执提交
  - 邀请函统计

数据来源：
  - invitation_templates     模板表（v289）
  - invitation_instances     实例表（v289）
"""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─── 常量 ─────────────────────────────────────────────────────────────────────

SHARE_CODE_LENGTH = 8
SHARE_CODE_CHARS = string.ascii_lowercase + string.digits


def _generate_share_code() -> str:
    """生成 8 位随机短码"""
    return "".join(secrets.choice(SHARE_CODE_CHARS) for _ in range(SHARE_CODE_LENGTH))


# ═══════════════════════════════════════════════════════════════════════════════
# 模板 CRUD
# ═══════════════════════════════════════════════════════════════════════════════


async def list_templates(
    db: AsyncSession,
    tenant_id: str,
    banquet_type: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """获取邀请函模板列表（系统预置 + 租户自定义）"""
    offset = (page - 1) * size
    type_filter = ""
    params: dict = {"tenant_id": tenant_id, "limit": size, "offset": offset}
    if banquet_type:
        type_filter = "AND t.banquet_type = :banquet_type"
        params["banquet_type"] = banquet_type

    # 查询总数
    count_result = await db.execute(
        text(f"""
            SELECT COUNT(*) AS total
            FROM invitation_templates t
            WHERE (t.tenant_id IS NULL OR t.tenant_id = :tenant_id)
              AND t.is_active = true
              AND t.is_deleted = false
              {type_filter}
        """),
        params,
    )
    total = count_result.scalar() or 0

    # 查询列表
    result = await db.execute(
        text(f"""
            SELECT
                t.id, t.tenant_id, t.template_name, t.template_code,
                t.banquet_type, t.cover_image_url, t.background_color,
                t.layout_config, t.music_url, t.animation_type,
                t.is_system, t.sort_order, t.created_at
            FROM invitation_templates t
            WHERE (t.tenant_id IS NULL OR t.tenant_id = :tenant_id)
              AND t.is_active = true
              AND t.is_deleted = false
              {type_filter}
            ORDER BY t.is_system DESC, t.sort_order, t.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = []
    for r in result.mappings():
        row = dict(r)
        row["id"] = str(row["id"])
        if row.get("tenant_id"):
            row["tenant_id"] = str(row["tenant_id"])
        if row.get("created_at"):
            row["created_at"] = str(row["created_at"])
        items.append(row)

    return {"items": items, "total": total, "page": page, "size": size}


async def get_template(
    db: AsyncSession,
    tenant_id: str,
    template_id: str,
) -> Optional[dict]:
    """获取单个模板详情"""
    result = await db.execute(
        text("""
            SELECT *
            FROM invitation_templates
            WHERE id = :template_id
              AND (tenant_id IS NULL OR tenant_id = :tenant_id)
              AND is_deleted = false
        """),
        {"template_id": template_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("tenant_id"):
        d["tenant_id"] = str(d["tenant_id"])
    return d


async def create_template(
    db: AsyncSession,
    tenant_id: str,
    data: dict,
) -> dict:
    """创建租户自定义模板"""
    template_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO invitation_templates (
                id, tenant_id, template_name, template_code,
                banquet_type, cover_image_url, background_color,
                layout_config, music_url, animation_type,
                is_system, is_active, sort_order,
                created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :template_name, :template_code,
                :banquet_type, :cover_image_url, :background_color,
                :layout_config::jsonb, :music_url, :animation_type,
                false, true, :sort_order,
                :now, :now
            )
        """),
        {
            "id": template_id,
            "tenant_id": tenant_id,
            "template_name": data["template_name"],
            "template_code": data.get("template_code", f"custom_{template_id[:8]}"),
            "banquet_type": data.get("banquet_type", "other"),
            "cover_image_url": data.get("cover_image_url"),
            "background_color": data.get("background_color"),
            "layout_config": data.get("layout_config", "{}"),
            "music_url": data.get("music_url"),
            "animation_type": data.get("animation_type"),
            "sort_order": data.get("sort_order", 0),
            "now": now,
        },
    )
    await db.commit()

    logger.info("invitation_template_created", template_id=template_id, tenant_id=tenant_id)
    return {"id": template_id, "template_name": data["template_name"], "created_at": now.isoformat()}


async def update_template(
    db: AsyncSession,
    tenant_id: str,
    template_id: str,
    data: dict,
) -> Optional[dict]:
    """更新租户自定义模板（系统模板不可修改）"""
    # 检查模板存在且为租户自有
    existing = await db.execute(
        text("""
            SELECT id, is_system
            FROM invitation_templates
            WHERE id = :template_id
              AND tenant_id = :tenant_id
              AND is_deleted = false
        """),
        {"template_id": template_id, "tenant_id": tenant_id},
    )
    row = existing.mappings().first()
    if not row:
        return None
    if row["is_system"]:
        return None  # 系统模板不可修改

    now = datetime.now(timezone.utc)
    set_clauses = ["updated_at = :now"]
    params: dict = {"template_id": template_id, "tenant_id": tenant_id, "now": now}

    updatable_fields = [
        "template_name",
        "banquet_type",
        "cover_image_url",
        "background_color",
        "music_url",
        "animation_type",
        "sort_order",
        "is_active",
    ]
    for field in updatable_fields:
        if field in data:
            set_clauses.append(f"{field} = :{field}")
            params[field] = data[field]

    if "layout_config" in data:
        set_clauses.append("layout_config = :layout_config::jsonb")
        params["layout_config"] = data["layout_config"]

    await db.execute(
        text(f"""
            UPDATE invitation_templates
            SET {", ".join(set_clauses)}
            WHERE id = :template_id AND tenant_id = :tenant_id AND is_deleted = false
        """),
        params,
    )
    await db.commit()

    logger.info("invitation_template_updated", template_id=template_id)
    return {"id": template_id, "updated_at": now.isoformat()}


async def delete_template(
    db: AsyncSession,
    tenant_id: str,
    template_id: str,
) -> bool:
    """软删除租户自定义模板"""
    result = await db.execute(
        text("""
            UPDATE invitation_templates
            SET is_deleted = true, updated_at = NOW()
            WHERE id = :template_id
              AND tenant_id = :tenant_id
              AND is_system = false
              AND is_deleted = false
        """),
        {"template_id": template_id, "tenant_id": tenant_id},
    )
    await db.commit()
    return result.rowcount > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 邀请函实例
# ═══════════════════════════════════════════════════════════════════════════════


async def create_invitation(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    data: dict,
) -> dict:
    """创建邀请函实例（草稿状态）"""
    invitation_id = str(uuid.uuid4())
    share_code = _generate_share_code()
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO invitation_instances (
                id, tenant_id, store_id, template_id, banquet_order_id,
                share_code, title, host_names, event_date,
                event_address, event_hall, greeting_text,
                custom_fields, cover_image_url, gallery_urls,
                music_url, status, rsvp_enabled, rsvp_deadline,
                created_by, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :store_id, :template_id, :banquet_order_id,
                :share_code, :title, :host_names, :event_date,
                :event_address, :event_hall, :greeting_text,
                :custom_fields::jsonb, :cover_image_url, :gallery_urls::jsonb,
                :music_url, 'draft', :rsvp_enabled, :rsvp_deadline,
                :created_by, :now, :now
            )
        """),
        {
            "id": invitation_id,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "template_id": data["template_id"],
            "banquet_order_id": data.get("banquet_order_id"),
            "share_code": share_code,
            "title": data["title"],
            "host_names": data.get("host_names"),
            "event_date": data["event_date"],
            "event_address": data.get("event_address"),
            "event_hall": data.get("event_hall"),
            "greeting_text": data.get("greeting_text"),
            "custom_fields": data.get("custom_fields", "{}"),
            "cover_image_url": data.get("cover_image_url"),
            "gallery_urls": data.get("gallery_urls", "[]"),
            "music_url": data.get("music_url"),
            "rsvp_enabled": data.get("rsvp_enabled", True),
            "rsvp_deadline": data.get("rsvp_deadline"),
            "created_by": data["created_by"],
            "now": now,
        },
    )
    await db.commit()

    logger.info(
        "invitation_created",
        invitation_id=invitation_id,
        share_code=share_code,
        tenant_id=tenant_id,
    )
    return {
        "id": invitation_id,
        "share_code": share_code,
        "status": "draft",
        "created_at": now.isoformat(),
    }


async def publish_invitation(
    db: AsyncSession,
    tenant_id: str,
    invitation_id: str,
) -> Optional[dict]:
    """发布邀请函（draft → published）"""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            UPDATE invitation_instances
            SET status = 'published',
                published_at = :now,
                updated_at = :now
            WHERE id = :invitation_id
              AND tenant_id = :tenant_id
              AND status = 'draft'
              AND is_deleted = false
            RETURNING id, share_code, published_at
        """),
        {"invitation_id": invitation_id, "tenant_id": tenant_id, "now": now},
    )
    row = result.mappings().first()
    await db.commit()

    if not row:
        return None

    logger.info("invitation_published", invitation_id=invitation_id)
    return {
        "id": str(row["id"]),
        "share_code": row["share_code"],
        "status": "published",
        "published_at": str(row["published_at"]),
    }


async def get_invitation(
    db: AsyncSession,
    tenant_id: str,
    invitation_id: str,
) -> Optional[dict]:
    """获取邀请函详情（管理端，需认证）"""
    result = await db.execute(
        text("""
            SELECT
                i.*,
                t.template_name,
                t.layout_config AS template_layout,
                t.animation_type AS template_animation
            FROM invitation_instances i
            LEFT JOIN invitation_templates t ON i.template_id = t.id
            WHERE i.id = :invitation_id
              AND i.tenant_id = :tenant_id
              AND i.is_deleted = false
        """),
        {"invitation_id": invitation_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if not row:
        return None
    return _serialize_invitation(dict(row))


async def get_invitation_by_share_code(
    db: AsyncSession,
    share_code: str,
) -> Optional[dict]:
    """通过 share_code 获取邀请函（公开访问，无需认证）

    注意：此查询不过滤 tenant_id，因为是公开访问。
    只返回已发布的邀请函。
    """
    result = await db.execute(
        text("""
            SELECT
                i.id, i.template_id, i.share_code,
                i.title, i.host_names, i.event_date,
                i.event_address, i.event_hall, i.greeting_text,
                i.custom_fields, i.cover_image_url, i.gallery_urls,
                i.music_url, i.status, i.published_at,
                i.rsvp_enabled, i.rsvp_deadline,
                i.view_count, i.rsvp_yes_count, i.rsvp_total_guests,
                t.template_name, t.layout_config AS template_layout,
                t.background_color, t.animation_type AS template_animation,
                t.cover_image_url AS template_cover_url
            FROM invitation_instances i
            LEFT JOIN invitation_templates t ON i.template_id = t.id
            WHERE i.share_code = :share_code
              AND i.status = 'published'
              AND i.is_deleted = false
        """),
        {"share_code": share_code},
    )
    row = result.mappings().first()
    if not row:
        return None

    d = dict(row)
    d["id"] = str(d["id"])
    d["template_id"] = str(d["template_id"])
    if d.get("event_date"):
        d["event_date"] = str(d["event_date"])
    if d.get("published_at"):
        d["published_at"] = str(d["published_at"])
    if d.get("rsvp_deadline"):
        d["rsvp_deadline"] = str(d["rsvp_deadline"])
    return d


async def record_view(
    db: AsyncSession,
    share_code: str,
) -> bool:
    """记录邀请函浏览量（公开端点，无需认证）"""
    result = await db.execute(
        text("""
            UPDATE invitation_instances
            SET view_count = view_count + 1,
                updated_at = NOW()
            WHERE share_code = :share_code
              AND status = 'published'
              AND is_deleted = false
        """),
        {"share_code": share_code},
    )
    await db.commit()
    return result.rowcount > 0


async def submit_rsvp(
    db: AsyncSession,
    share_code: str,
    data: dict,
) -> Optional[dict]:
    """提交 RSVP 回执（公开端点，无需认证）

    data:
      - attending: bool
      - guest_count: int (出席人数)
      - guest_name: str
      - message: str (祝福语)
    """
    # 检查邀请函存在且 RSVP 开启
    check = await db.execute(
        text("""
            SELECT id, rsvp_enabled, rsvp_deadline
            FROM invitation_instances
            WHERE share_code = :share_code
              AND status = 'published'
              AND is_deleted = false
        """),
        {"share_code": share_code},
    )
    invitation = check.mappings().first()
    if not invitation:
        return None

    if not invitation["rsvp_enabled"]:
        return {"error": "RSVP is not enabled for this invitation"}

    if invitation["rsvp_deadline"]:
        deadline = invitation["rsvp_deadline"]
        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)
        if datetime.now(timezone.utc) > deadline.replace(tzinfo=timezone.utc):
            return {"error": "RSVP deadline has passed"}

    attending = data.get("attending", True)
    guest_count = data.get("guest_count", 1) if attending else 0

    # 更新统计
    if attending:
        await db.execute(
            text("""
                UPDATE invitation_instances
                SET rsvp_yes_count = rsvp_yes_count + 1,
                    rsvp_total_guests = rsvp_total_guests + :guest_count,
                    updated_at = NOW()
                WHERE share_code = :share_code
                  AND is_deleted = false
            """),
            {"share_code": share_code, "guest_count": guest_count},
        )
    else:
        await db.execute(
            text("""
                UPDATE invitation_instances
                SET rsvp_no_count = rsvp_no_count + 1,
                    updated_at = NOW()
                WHERE share_code = :share_code
                  AND is_deleted = false
            """),
            {"share_code": share_code},
        )
    await db.commit()

    logger.info(
        "invitation_rsvp_submitted",
        share_code=share_code,
        attending=attending,
        guest_count=guest_count,
    )
    return {
        "attending": attending,
        "guest_count": guest_count,
        "guest_name": data.get("guest_name", ""),
        "message": data.get("message", ""),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_invitation_stats(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    page: int = 1,
    size: int = 20,
) -> dict:
    """获取邀请函统计列表"""
    offset = (page - 1) * size

    count_result = await db.execute(
        text("""
            SELECT COUNT(*) AS total
            FROM invitation_instances
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND is_deleted = false
        """),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        text("""
            SELECT
                i.id, i.share_code, i.title, i.host_names,
                i.event_date, i.status, i.published_at,
                i.view_count, i.rsvp_yes_count, i.rsvp_no_count,
                i.rsvp_total_guests, i.rsvp_enabled,
                i.created_at,
                t.template_name, t.banquet_type
            FROM invitation_instances i
            LEFT JOIN invitation_templates t ON i.template_id = t.id
            WHERE i.tenant_id = :tenant_id
              AND i.store_id = :store_id
              AND i.is_deleted = false
            ORDER BY i.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "limit": size,
            "offset": offset,
        },
    )
    items = []
    for r in result.mappings():
        row = dict(r)
        row["id"] = str(row["id"])
        if row.get("event_date"):
            row["event_date"] = str(row["event_date"])
        if row.get("published_at"):
            row["published_at"] = str(row["published_at"])
        if row.get("created_at"):
            row["created_at"] = str(row["created_at"])
        items.append(row)

    return {"items": items, "total": total, "page": page, "size": size}


# ─── 内部辅助 ─────────────────────────────────────────────────────────────────


def _serialize_invitation(row: dict) -> dict:
    """序列化邀请函数据"""
    for key in ("id", "tenant_id", "store_id", "template_id", "banquet_order_id", "created_by"):
        if row.get(key):
            row[key] = str(row[key])
    for key in ("event_date", "published_at", "expires_at", "rsvp_deadline", "created_at", "updated_at"):
        if row.get(key):
            row[key] = str(row[key])
    return row
