"""营销Banner管理 — 创建/上下线/点击追踪/效果分析

支持 banner_type: hero / promotion / announcement / campaign
存储层：PostgreSQL banners 表（v162 迁移创建）
计数器直接在 banners 表内维护（impression_count / click_count）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

VALID_BANNER_TYPES = ("hero", "promotion", "announcement", "campaign")


# ── 工具函数 ──────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_dict(row: Any) -> dict:
    """将 SQLAlchemy RowMapping 转为普通 dict，处理 datetime 序列化"""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


# ── 服务函数 ──────────────────────────────────────────────────


async def create_banner(
    title: str,
    banner_type: str,
    image_url: Optional[str],
    link_url: Optional[str],
    target_segment: Optional[dict],
    display_order: int,
    start_at: Optional[datetime],
    end_at: Optional[datetime],
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建Banner

    Args:
        title: Banner标题
        banner_type: 类型 (hero/promotion/announcement/campaign)
        image_url: 图片URL
        link_url: 跳转URL
        target_segment: 目标客群条件（JSONB）
        display_order: 显示顺序（数值越小越靠前）
        start_at: 上线时间 (None=立即生效)
        end_at: 下线时间 (None=永久有效)
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"id", "title", "banner_type", "is_active", "created_at", ...}
    """
    if banner_type not in VALID_BANNER_TYPES:
        raise ValueError(f"invalid_banner_type:{banner_type}, must be one of {VALID_BANNER_TYPES}")

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    result = await db.execute(
        text("""
            INSERT INTO banners
                (tenant_id, title, banner_type, image_url, link_url,
                 target_segment, display_order, start_at, end_at,
                 is_active, impression_count, click_count)
            VALUES
                (:tenant_id, :title, :banner_type, :image_url, :link_url,
                 :target_segment::jsonb, :display_order, :start_at, :end_at,
                 TRUE, 0, 0)
            RETURNING id, tenant_id, title, banner_type, image_url, link_url,
                      target_segment, display_order, start_at, end_at,
                      is_active, impression_count, click_count, created_at, updated_at
        """),
        {
            "tenant_id": tenant_id,
            "title": title,
            "banner_type": banner_type,
            "image_url": image_url,
            "link_url": link_url,
            "target_segment": json.dumps(target_segment, ensure_ascii=False) if target_segment else "null",
            "display_order": display_order,
            "start_at": start_at,
            "end_at": end_at,
        },
    )
    row = result.mappings().one()
    await db.commit()

    banner = _row_to_dict(row)
    logger.info(
        "banner.created",
        banner_id=str(banner["id"]),
        title=title,
        banner_type=banner_type,
        tenant_id=tenant_id,
    )
    return banner


async def list_banners(
    is_active: bool = True,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """获取Banner列表（按 display_order 排序）

    Args:
        is_active: 是否只返回激活的 Banner
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        Banner 列表，按 display_order 升序
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if is_active:
        conditions.append("is_active = TRUE")
        conditions.append("(start_at IS NULL OR start_at <= NOW())")
        conditions.append("(end_at IS NULL OR end_at >= NOW())")

    where = " AND ".join(conditions)
    result = await db.execute(
        text(f"""
            SELECT id, title, banner_type, image_url, link_url,
                   target_segment, display_order, start_at, end_at,
                   is_active, impression_count, click_count, created_at, updated_at
            FROM banners
            WHERE {where}
            ORDER BY display_order ASC, created_at DESC
        """),
        params,
    )
    rows = result.mappings().all()

    return [_row_to_dict(row) for row in rows]


async def record_impression(
    banner_id: str,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """记录展示次数（原子递增）

    Args:
        banner_id: Banner ID
        tenant_id: 租户ID
        db: 数据库会话
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    await db.execute(
        text("""
            UPDATE banners
            SET impression_count = impression_count + 1,
                updated_at = NOW()
            WHERE id = :banner_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"banner_id": banner_id, "tenant_id": tenant_id},
    )
    await db.commit()


async def record_click(
    banner_id: str,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """记录点击次数（原子递增）

    Args:
        banner_id: Banner ID
        tenant_id: 租户ID
        db: 数据库会话
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    await db.execute(
        text("""
            UPDATE banners
            SET click_count = click_count + 1,
                updated_at = NOW()
            WHERE id = :banner_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"banner_id": banner_id, "tenant_id": tenant_id},
    )
    await db.commit()


async def get_banner_stats(
    banner_id: str,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """获取Banner效果统计（展示/点击/CTR）

    Args:
        banner_id: Banner ID
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"banner_id", "title", "impression_count", "click_count", "ctr"}
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    result = await db.execute(
        text("""
            SELECT id, title, banner_type, impression_count, click_count,
                   is_active, created_at, updated_at
            FROM banners
            WHERE id = :banner_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"banner_id": banner_id, "tenant_id": tenant_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ValueError(f"banner_not_found:{banner_id}")

    impression_count = row["impression_count"] or 0
    click_count = row["click_count"] or 0
    ctr = round(click_count / max(impression_count, 1), 4)

    return {
        "banner_id": str(row["id"]),
        "title": row["title"],
        "banner_type": row["banner_type"],
        "impression_count": impression_count,
        "click_count": click_count,
        "ctr": ctr,
        "is_active": row["is_active"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def disable_banner(
    banner_id: str,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """下线Banner（is_active=FALSE）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    result = await db.execute(
        text("""
            UPDATE banners
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = :banner_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            RETURNING id
        """),
        {"banner_id": banner_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise ValueError(f"banner_not_found:{banner_id}")
    await db.commit()

    logger.info("banner.disabled", banner_id=banner_id, tenant_id=tenant_id)
    return {"banner_id": banner_id, "is_active": False}


# 保留旧接口别名以兼容现有路由（已 async 化）
async def create_banner_legacy(
    title: str,
    image_url: str,
    link_type: str,
    link_target: str,
    position: str,
    priority: int,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """兼容旧路由签名 → 转发到新 create_banner（banner_type 默认 promotion）"""
    if db is None:
        raise ValueError("db session required")
    return await create_banner(
        title=title,
        banner_type="promotion",
        image_url=image_url,
        link_url=link_target,
        target_segment={"link_type": link_type},
        display_order=priority,
        start_at=start_date,
        end_at=end_date,
        tenant_id=tenant_id,
        db=db,
    )
