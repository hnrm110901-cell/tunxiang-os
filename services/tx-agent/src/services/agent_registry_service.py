"""AgentRegistryService — Agent 模板/版本/部署管理服务

提供 Agent 模板的 CRUD、版本发布/回滚、部署灰度管理能力。
所有查询强制 tenant_id 过滤（RLS 兜底）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent_deployment import AgentDeployment
from ..models.agent_template import AgentTemplate
from ..models.agent_version import AgentVersion

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., max_length=100, description="唯一标识名(tenant内)")
    display_name: str = Field(..., max_length=200, description="显示名称")
    description: str | None = None
    category: str = Field(..., max_length=50, description="分类")
    priority: str = Field(default="P1", max_length=10)
    run_location: str = Field(default="cloud", max_length=20)
    agent_level: str = Field(default="skill", max_length=20)
    config_json: dict | None = None
    model_preference: str | None = None
    tool_whitelist: list[str] | None = None
    created_by: str | None = None


class UpdateTemplateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    category: str | None = None
    priority: str | None = None
    run_location: str | None = None
    config_json: dict | None = None
    model_preference: str | None = None
    tool_whitelist: list[str] | None = None


class CreateVersionRequest(BaseModel):
    version_tag: str = Field(..., max_length=50, description="版本号如v1.0.0")
    skill_yaml_snapshot: dict | None = None
    prompt_snapshot: str | None = None
    changelog: str | None = None


class CreateDeploymentRequest(BaseModel):
    template_id: UUID
    version_id: UUID
    scope_type: str = Field(..., max_length=20, description="brand/store/region")
    scope_id: UUID
    enabled: bool = True
    rollout_percent: int = Field(default=100, ge=0, le=100)
    allowed_actions: list[str] | None = None
    config_overrides: dict | None = None
    deployed_by: str | None = None


class UpdateDeploymentRequest(BaseModel):
    enabled: bool | None = None
    rollout_percent: int | None = Field(default=None, ge=0, le=100)
    allowed_actions: list[str] | None = None
    config_overrides: dict | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class AgentRegistryService:
    """Agent Registry 服务 — 模板/版本/部署管理"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ══════════════════════════════════════════════════════════════════════════
    #  模板管理
    # ══════════════════════════════════════════════════════════════════════════

    async def create_template(
        self,
        tenant_id: str,
        data: CreateTemplateRequest,
    ) -> AgentTemplate:
        """创建 Agent 模板。校验 name 在 tenant 内唯一，默认 status=draft。"""
        tid = UUID(tenant_id)

        # 唯一性校验
        existing = await self.db.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_id == tid,
                AgentTemplate.name == data.name,
                AgentTemplate.is_deleted == False,  # noqa: E712
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError(f"模板名称 '{data.name}' 在当前租户下已存在")

        template = AgentTemplate(
            tenant_id=tid,
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            category=data.category,
            priority=data.priority,
            run_location=data.run_location,
            agent_level=data.agent_level,
            config_json=data.config_json,
            model_preference=data.model_preference,
            tool_whitelist=data.tool_whitelist,
            status="draft",
            created_by=data.created_by,
        )
        self.db.add(template)
        await self.db.flush()

        logger.info("agent_template_created", template_id=str(template.id), name=data.name)
        return template

    async def update_template(
        self,
        tenant_id: str,
        template_id: UUID,
        data: UpdateTemplateRequest,
    ) -> AgentTemplate:
        """更新 Agent 模板（仅更新非 None 字段）。"""
        template = await self._get_template_or_raise(tenant_id, template_id)

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(template, field, value)

        await self.db.flush()
        logger.info("agent_template_updated", template_id=str(template_id))
        return template

    async def get_template(
        self,
        tenant_id: str,
        template_id: UUID,
    ) -> AgentTemplate | None:
        """获取单个模板，不存在返回 None。"""
        tid = UUID(tenant_id)
        result = await self.db.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_id == tid,
                AgentTemplate.id == template_id,
                AgentTemplate.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def list_templates(
        self,
        tenant_id: str,
        *,
        category: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[AgentTemplate], int]:
        """列出模板（分页+过滤）。返回 (items, total)。"""
        tid = UUID(tenant_id)

        base_where = [
            AgentTemplate.tenant_id == tid,
            AgentTemplate.is_deleted == False,  # noqa: E712
        ]
        if category:
            base_where.append(AgentTemplate.category == category)
        if status:
            base_where.append(AgentTemplate.status == status)

        # total count
        count_stmt = select(func.count()).select_from(AgentTemplate).where(*base_where)
        total = (await self.db.execute(count_stmt)).scalar_one()

        # items
        stmt = (
            select(AgentTemplate)
            .where(*base_where)
            .order_by(AgentTemplate.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def activate_template(
        self,
        tenant_id: str,
        template_id: UUID,
    ) -> AgentTemplate:
        """激活模板（draft -> active）。"""
        template = await self._get_template_or_raise(tenant_id, template_id)
        if template.status != "draft":
            raise ValueError(f"仅 draft 状态可激活，当前状态: {template.status}")
        template.status = "active"
        await self.db.flush()
        logger.info("agent_template_activated", template_id=str(template_id))
        return template

    async def deprecate_template(
        self,
        tenant_id: str,
        template_id: UUID,
    ) -> AgentTemplate:
        """废弃模板（active -> deprecated）。"""
        template = await self._get_template_or_raise(tenant_id, template_id)
        if template.status != "active":
            raise ValueError(f"仅 active 状态可废弃，当前状态: {template.status}")
        template.status = "deprecated"
        await self.db.flush()
        logger.info("agent_template_deprecated", template_id=str(template_id))
        return template

    # ══════════════════════════════════════════════════════════════════════════
    #  版本管理
    # ══════════════════════════════════════════════════════════════════════════

    async def create_version(
        self,
        tenant_id: str,
        template_id: UUID,
        data: CreateVersionRequest,
    ) -> AgentVersion:
        """创建新版本。"""
        # 确保模板存在
        await self._get_template_or_raise(tenant_id, template_id)
        tid = UUID(tenant_id)

        # 检查 version_tag 唯一性
        existing = await self.db.execute(
            select(AgentVersion).where(
                AgentVersion.tenant_id == tid,
                AgentVersion.template_id == template_id,
                AgentVersion.version_tag == data.version_tag,
                AgentVersion.is_deleted == False,  # noqa: E712
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError(f"版本号 '{data.version_tag}' 已存在")

        version = AgentVersion(
            tenant_id=tid,
            template_id=template_id,
            version_tag=data.version_tag,
            skill_yaml_snapshot=data.skill_yaml_snapshot,
            prompt_snapshot=data.prompt_snapshot,
            changelog=data.changelog,
            is_active=False,
        )
        self.db.add(version)
        await self.db.flush()

        logger.info(
            "agent_version_created",
            version_id=str(version.id),
            template_id=str(template_id),
            version_tag=data.version_tag,
        )
        return version

    async def publish_version(
        self,
        tenant_id: str,
        version_id: UUID,
        published_by: str,
    ) -> AgentVersion:
        """发布版本（设 is_active=True，同模板下其他版本 is_active=False）。"""
        tid = UUID(tenant_id)

        # 获取目标版本
        result = await self.db.execute(
            select(AgentVersion).where(
                AgentVersion.tenant_id == tid,
                AgentVersion.id == version_id,
                AgentVersion.is_deleted == False,  # noqa: E712
            )
        )
        version = result.scalar_one_or_none()
        if version is None:
            raise ValueError(f"版本 {version_id} 不存在")

        # 将同模板下其他版本设为非激活
        await self.db.execute(
            update(AgentVersion)
            .where(
                AgentVersion.tenant_id == tid,
                AgentVersion.template_id == version.template_id,
                AgentVersion.id != version_id,
            )
            .values(is_active=False)
        )

        # 激活目标版本
        version.is_active = True
        version.published_at = datetime.now(timezone.utc)
        version.published_by = published_by
        await self.db.flush()

        logger.info(
            "agent_version_published",
            version_id=str(version_id),
            template_id=str(version.template_id),
            published_by=published_by,
        )
        return version

    async def list_versions(
        self,
        tenant_id: str,
        template_id: UUID,
    ) -> list[AgentVersion]:
        """列出某模板的所有版本（按创建时间降序）。"""
        tid = UUID(tenant_id)
        result = await self.db.execute(
            select(AgentVersion)
            .where(
                AgentVersion.tenant_id == tid,
                AgentVersion.template_id == template_id,
                AgentVersion.is_deleted == False,  # noqa: E712
            )
            .order_by(AgentVersion.created_at.desc())
        )
        return list(result.scalars().all())

    async def rollback_version(
        self,
        tenant_id: str,
        template_id: UUID,
        target_version_id: UUID,
    ) -> AgentVersion:
        """回滚到指定版本（本质上是发布目标版本）。"""
        tid = UUID(tenant_id)

        # 确保目标版本属于该模板
        result = await self.db.execute(
            select(AgentVersion).where(
                AgentVersion.tenant_id == tid,
                AgentVersion.id == target_version_id,
                AgentVersion.template_id == template_id,
                AgentVersion.is_deleted == False,  # noqa: E712
            )
        )
        version = result.scalar_one_or_none()
        if version is None:
            raise ValueError(f"版本 {target_version_id} 不存在或不属于模板 {template_id}")

        return await self.publish_version(tenant_id, target_version_id, published_by="rollback")

    # ══════════════════════════════════════════════════════════════════════════
    #  部署管理
    # ══════════════════════════════════════════════════════════════════════════

    async def deploy(
        self,
        tenant_id: str,
        data: CreateDeploymentRequest,
    ) -> AgentDeployment:
        """部署 Agent 到指定范围。"""
        tid = UUID(tenant_id)

        # 确保模板和版本存在
        await self._get_template_or_raise(tenant_id, data.template_id)

        version_result = await self.db.execute(
            select(AgentVersion).where(
                AgentVersion.tenant_id == tid,
                AgentVersion.id == data.version_id,
                AgentVersion.template_id == data.template_id,
                AgentVersion.is_deleted == False,  # noqa: E712
            )
        )
        if version_result.scalar_one_or_none() is None:
            raise ValueError(f"版本 {data.version_id} 不存在或不属于模板 {data.template_id}")

        deployment = AgentDeployment(
            tenant_id=tid,
            template_id=data.template_id,
            version_id=data.version_id,
            scope_type=data.scope_type,
            scope_id=data.scope_id,
            enabled=data.enabled,
            rollout_percent=data.rollout_percent,
            allowed_actions=data.allowed_actions,
            config_overrides=data.config_overrides,
            deployed_by=data.deployed_by,
        )
        self.db.add(deployment)
        await self.db.flush()

        logger.info(
            "agent_deployed",
            deployment_id=str(deployment.id),
            template_id=str(data.template_id),
            scope_type=data.scope_type,
            scope_id=str(data.scope_id),
        )
        return deployment

    async def update_deployment(
        self,
        tenant_id: str,
        deployment_id: UUID,
        data: UpdateDeploymentRequest,
    ) -> AgentDeployment:
        """更新部署（灰度比例/启用状态/白名单）。"""
        deployment = await self._get_deployment_or_raise(tenant_id, deployment_id)

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(deployment, field, value)

        await self.db.flush()
        logger.info("agent_deployment_updated", deployment_id=str(deployment_id))
        return deployment

    async def list_deployments(
        self,
        tenant_id: str,
        *,
        template_id: UUID | None = None,
        scope_type: str | None = None,
        scope_id: UUID | None = None,
    ) -> list[AgentDeployment]:
        """列出部署（支持按模板/范围过滤）。"""
        tid = UUID(tenant_id)
        conditions = [
            AgentDeployment.tenant_id == tid,
            AgentDeployment.is_deleted == False,  # noqa: E712
        ]
        if template_id is not None:
            conditions.append(AgentDeployment.template_id == template_id)
        if scope_type is not None:
            conditions.append(AgentDeployment.scope_type == scope_type)
        if scope_id is not None:
            conditions.append(AgentDeployment.scope_id == scope_id)

        result = await self.db.execute(
            select(AgentDeployment).where(*conditions).order_by(AgentDeployment.deployed_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_agents_for_store(
        self,
        tenant_id: str,
        store_id: UUID,
    ) -> list[dict[str, Any]]:
        """获取某门店当前激活的所有 Agent（考虑灰度比例）。

        查找 scope_type='store' 且 scope_id=store_id 的启用部署，
        联查模板和版本信息，用 store_id 哈希决定灰度是否命中。

        Returns:
            [{template_name, version_tag, config, allowed_actions}, ...]
        """
        tid = UUID(tenant_id)

        # 查找该门店的所有启用部署
        stmt = (
            select(AgentDeployment, AgentTemplate, AgentVersion)
            .join(AgentTemplate, AgentDeployment.template_id == AgentTemplate.id)
            .join(AgentVersion, AgentDeployment.version_id == AgentVersion.id)
            .where(
                AgentDeployment.tenant_id == tid,
                AgentDeployment.scope_type == "store",
                AgentDeployment.scope_id == store_id,
                AgentDeployment.enabled == True,  # noqa: E712
                AgentDeployment.is_deleted == False,  # noqa: E712
                AgentTemplate.is_deleted == False,  # noqa: E712
                AgentTemplate.status == "active",
            )
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        agents: list[dict[str, Any]] = []
        for deployment, template, version in rows:
            # 灰度判断：用 store_id 哈希取模
            if deployment.rollout_percent < 100:
                hash_val = int(hashlib.md5(str(store_id).encode()).hexdigest(), 16) % 100
                if hash_val >= deployment.rollout_percent:
                    continue

            # 合并配置：模板默认配置 + 部署覆盖配置
            merged_config = {**(template.config_json or {}), **(deployment.config_overrides or {})}

            agents.append(
                {
                    "template_name": template.name,
                    "display_name": template.display_name,
                    "version_tag": version.version_tag,
                    "config": merged_config,
                    "allowed_actions": deployment.allowed_actions,
                    "priority": template.priority,
                    "run_location": template.run_location,
                }
            )

        logger.info(
            "active_agents_for_store",
            store_id=str(store_id),
            agent_count=len(agents),
        )
        return agents

    async def undeploy(
        self,
        tenant_id: str,
        deployment_id: UUID,
    ) -> None:
        """取消部署（软删除）。"""
        deployment = await self._get_deployment_or_raise(tenant_id, deployment_id)
        deployment.is_deleted = True
        await self.db.flush()
        logger.info("agent_undeployed", deployment_id=str(deployment_id))

    # ══════════════════════════════════════════════════════════════════════════
    #  内部辅助方法
    # ══════════════════════════════════════════════════════════════════════════

    async def _get_template_or_raise(
        self,
        tenant_id: str,
        template_id: UUID,
    ) -> AgentTemplate:
        """获取模板，不存在则抛 ValueError。"""
        template = await self.get_template(tenant_id, template_id)
        if template is None:
            raise ValueError(f"模板 {template_id} 不存在")
        return template

    async def _get_deployment_or_raise(
        self,
        tenant_id: str,
        deployment_id: UUID,
    ) -> AgentDeployment:
        """获取部署，不存在则抛 ValueError。"""
        tid = UUID(tenant_id)
        result = await self.db.execute(
            select(AgentDeployment).where(
                AgentDeployment.tenant_id == tid,
                AgentDeployment.id == deployment_id,
                AgentDeployment.is_deleted == False,  # noqa: E712
            )
        )
        deployment = result.scalar_one_or_none()
        if deployment is None:
            raise ValueError(f"部署 {deployment_id} 不存在")
        return deployment
