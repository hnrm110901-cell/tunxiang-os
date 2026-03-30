"""品牌组配置模型 — 集团跨品牌管理

集团视角：一个集团主租户管理多个品牌租户（brand_tenant_ids）。
tenant_id 在此表中代表"集团主租户ID"，由集团管理员身份写入。

金额单位：分（fen）。
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BrandGroup(TenantBase):
    """品牌组（集团定义哪些 tenant 属于同一集团）

    tenant_id 含义：集团主租户 ID（非品牌级）。
    brand_tenant_ids：旗下各品牌的 tenant_id 列表（JSONB 存储 UUID 字符串数组）。

    设计原则：
    - 继承 TenantBase 保留 tenant_id 字段格式一致性
    - 集团管理员通过 Header `X-Group-Admin: true` 访问，后续接入完整权限系统
    - RLS：开启，tenant_id = 集团主租户 ID（和普通品牌 RLS 逻辑一致）
    """

    __tablename__ = "brand_groups"

    group_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="集团名称，如「徐记海鲜集团」",
    )
    group_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="集团唯一标识码，如「xjhx」",
    )

    # 旗下品牌租户 ID 列表（JSONB 存 UUID 字符串数组）
    brand_tenant_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="旗下品牌 tenant_id 列表（UUID 字符串数组）",
    )

    # 跨品牌策略
    stored_value_interop: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="储值卡是否跨品牌互通",
    )
    member_data_shared: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="会员数据是否集团共享（影响跨品牌查询权限）",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="active | inactive",
    )

    # 操作审计
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="创建人（集团管理员 operator_id）",
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="最后更新人",
    )

    __table_args__ = (
        UniqueConstraint("group_code", name="uq_brand_group_code"),
        Index("idx_brand_group_tenant", "tenant_id", "status"),
        {"comment": "品牌组配置（集团跨品牌管理）"},
    )
