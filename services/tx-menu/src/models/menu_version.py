"""菜单版本 ORM 模型

# SCHEMA SQL:
# CREATE TABLE menu_versions (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     brand_id UUID NOT NULL,
#     version_no VARCHAR(30) NOT NULL,     -- e.g. "2026.Q1.v3"
#     version_name VARCHAR(100),
#     dishes_snapshot JSONB NOT NULL,      -- 完整菜品列表快照
#     status VARCHAR(20) DEFAULT 'draft',  -- draft/published/archived
#     published_at TIMESTAMPTZ,
#     created_by UUID,
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE TABLE menu_dispatch_records (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     version_id UUID NOT NULL REFERENCES menu_versions(id),
#     store_id UUID NOT NULL,
#     dispatch_type VARCHAR(20) DEFAULT 'full',  -- full/pilot
#     store_overrides JSONB DEFAULT '{}',         -- 门店微调（新增/停售/改价）
#     applied_at TIMESTAMPTZ,
#     status VARCHAR(20) DEFAULT 'pending',       -- pending/applied/failed
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# -- RLS 策略（使用 app.tenant_id）：
# ALTER TABLE menu_versions ENABLE ROW LEVEL SECURITY;
# CREATE POLICY tenant_isolation ON menu_versions
#     USING (tenant_id = current_setting('app.tenant_id')::uuid);
#
# ALTER TABLE menu_dispatch_records ENABLE ROW LEVEL SECURITY;
# CREATE POLICY tenant_isolation ON menu_dispatch_records
#     USING (tenant_id = current_setting('app.tenant_id')::uuid);
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ─── 版本状态常量 ───
VERSION_STATUS_DRAFT = "draft"
VERSION_STATUS_PUBLISHED = "published"
VERSION_STATUS_ARCHIVED = "archived"
VALID_VERSION_STATUSES = {VERSION_STATUS_DRAFT, VERSION_STATUS_PUBLISHED, VERSION_STATUS_ARCHIVED}

# ─── 下发类型常量 ───
DISPATCH_TYPE_FULL = "full"
DISPATCH_TYPE_PILOT = "pilot"
VALID_DISPATCH_TYPES = {DISPATCH_TYPE_FULL, DISPATCH_TYPE_PILOT}

# ─── 下发状态常量 ───
DISPATCH_STATUS_PENDING = "pending"
DISPATCH_STATUS_APPLIED = "applied"
DISPATCH_STATUS_FAILED = "failed"
VALID_DISPATCH_STATUSES = {DISPATCH_STATUS_PENDING, DISPATCH_STATUS_APPLIED, DISPATCH_STATUS_FAILED}


class MenuVersion(TenantBase):
    """菜单版本 — 记录某一时间点的菜品完整快照"""

    __tablename__ = "menu_versions"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="所属品牌",
    )
    version_no: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="版本号，如 2026.Q1.v3",
    )
    version_name: Mapped[str | None] = mapped_column(
        String(100),
        comment="版本名称，如 春季新菜单",
    )
    dishes_snapshot: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="完整菜品列表快照（防止菜品删除后历史版本失效）",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=VERSION_STATUS_DRAFT,
        comment="版本状态: draft/published/archived",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="发布时间",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="创建人员工 ID",
    )


class MenuDispatchRecord(TenantBase):
    """菜单下发记录 — 记录某版本下发到某门店的状态与门店微调"""

    __tablename__ = "menu_dispatch_records"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_versions.id"),
        nullable=False,
        index=True,
        comment="关联版本",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="目标门店",
    )
    dispatch_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DISPATCH_TYPE_FULL,
        comment="下发类型: full/pilot",
    )
    store_overrides: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment='门店微调: {"add_dishes":[...],"remove_dishes":[...],"price_overrides":{...}}',
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="门店实际应用时间",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DISPATCH_STATUS_PENDING,
        comment="下发状态: pending/applied/failed",
    )
