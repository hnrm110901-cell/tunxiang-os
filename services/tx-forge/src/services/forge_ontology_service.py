"""Ontology 绑定管理 — 对标 Palantir AIP"""

import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

log = structlog.get_logger(__name__)


# ── 有效访问模式 ───────────────────────────────────────────────
VALID_ACCESS_MODES: set[str] = {"read", "write", "read_write"}


class ForgeOntologyService:
    """Ontology 绑定管理 — 对标 Palantir AIP"""

    CORE_ENTITIES: list[str] = [
        "Store", "Order", "Customer", "Dish", "Ingredient", "Employee",
    ]

    # ── 获取绑定关系 ─────────────────────────────────────────────
    async def get_bindings(
        self,
        db: AsyncSession,
        *,
        app_id: str | None = None,
        entity: str | None = None,
    ) -> list[dict]:
        """查询 Ontology 绑定关系（按 app_id 或 entity 过滤）"""
        where_parts = ["is_deleted = false"]
        params: dict = {}

        if app_id is not None:
            where_parts.append("app_id = :app_id")
            params["app_id"] = app_id
        if entity is not None:
            where_parts.append("entity_name = :entity")
            params["entity"] = entity

        where_clause = " AND ".join(where_parts)

        result = await db.execute(
            text(f"""
                SELECT binding_id, app_id, entity_name, access_mode,
                       allowed_fields, constraints, created_at, updated_at
                FROM forge_ontology_bindings
                WHERE {where_clause}
                ORDER BY entity_name ASC, app_id ASC
            """),
            params,
        )
        return [dict(r) for r in result.mappings().all()]

    # ── 设置绑定 ─────────────────────────────────────────────────
    async def set_binding(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        entity_name: str,
        access_mode: str,
        allowed_fields: list | None = None,
        constraints: list | None = None,
    ) -> dict:
        """创建或更新 Ontology 绑定（app_id + entity_name 唯一）"""
        if allowed_fields is None:
            allowed_fields = []
        if constraints is None:
            constraints = []

        if entity_name not in self.CORE_ENTITIES:
            raise HTTPException(
                status_code=422,
                detail=f"无效实体: {entity_name}，可选: {self.CORE_ENTITIES}",
            )
        if access_mode not in VALID_ACCESS_MODES:
            raise HTTPException(
                status_code=422,
                detail=f"无效访问模式: {access_mode}，可选: {sorted(VALID_ACCESS_MODES)}",
            )

        # UPSERT：基于 app_id + entity_name 唯一约束
        binding_id = f"bind_{uuid4().hex[:12]}"
        result = await db.execute(
            text("""
                INSERT INTO forge_ontology_bindings
                    (id, tenant_id, binding_id, app_id, entity_name,
                     access_mode, allowed_fields, constraints)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :binding_id, :app_id, :entity_name,
                     :access_mode, :allowed_fields::jsonb, :constraints::jsonb)
                ON CONFLICT (app_id, entity_name) WHERE is_deleted = false
                DO UPDATE SET
                    access_mode = EXCLUDED.access_mode,
                    allowed_fields = EXCLUDED.allowed_fields,
                    constraints = EXCLUDED.constraints,
                    updated_at = NOW()
                RETURNING binding_id, app_id, entity_name, access_mode,
                          allowed_fields, constraints, created_at, updated_at
            """),
            {
                "binding_id": binding_id,
                "app_id": app_id,
                "entity_name": entity_name,
                "access_mode": access_mode,
                "allowed_fields": json.dumps(allowed_fields, ensure_ascii=False),
                "constraints": json.dumps(constraints, ensure_ascii=False),
            },
        )
        row = dict(result.mappings().one())

        log.info(
            "ontology_binding_set",
            app_id=app_id,
            entity=entity_name,
            access_mode=access_mode,
        )
        return row

    # ── 移除绑定 ─────────────────────────────────────────────────
    async def remove_binding(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        entity_name: str,
    ) -> dict:
        """移除 Ontology 绑定"""
        result = await db.execute(
            text("""
                UPDATE forge_ontology_bindings
                SET is_deleted = true, updated_at = NOW()
                WHERE app_id = :app_id
                  AND entity_name = :entity_name
                  AND is_deleted = false
                RETURNING binding_id, app_id, entity_name
            """),
            {"app_id": app_id, "entity_name": entity_name},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"绑定不存在: {app_id} × {entity_name}",
            )

        log.info("ontology_binding_removed", app_id=app_id, entity=entity_name)
        return dict(row)

    # ── 查询实体关联的所有应用 ─────────────────────────────────────
    async def get_entity_apps(
        self, db: AsyncSession, entity_name: str
    ) -> list[dict]:
        """获取所有访问指定实体的应用，包含应用详情和信任等级"""
        if entity_name not in self.CORE_ENTITIES:
            raise HTTPException(
                status_code=422,
                detail=f"无效实体: {entity_name}，可选: {self.CORE_ENTITIES}",
            )

        result = await db.execute(
            text("""
                SELECT
                    b.binding_id, b.app_id, b.access_mode,
                    b.allowed_fields, b.constraints,
                    a.app_name, a.status,
                    rp.trust_tier
                FROM forge_ontology_bindings b
                LEFT JOIN forge_apps a
                    ON a.app_id = b.app_id AND a.is_deleted = false
                LEFT JOIN forge_runtime_policies rp
                    ON rp.app_id = b.app_id AND rp.is_deleted = false
                WHERE b.entity_name = :entity_name
                  AND b.is_deleted = false
                ORDER BY a.app_name ASC
            """),
            {"entity_name": entity_name},
        )
        return [dict(r) for r in result.mappings().all()]

    # ── 校验 Manifest ────────────────────────────────────────────
    async def validate_manifest(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        manifest_content: dict,
    ) -> dict:
        """校验 FORGE_MANIFEST.yaml 内容"""
        errors: list[str] = []
        warnings: list[str] = []

        # 1. forge_version 必须存在
        forge_version = manifest_content.get("forge_version")
        if not forge_version:
            errors.append("缺少 forge_version 字段")

        # 2. 校验 ontology 绑定
        ontology_section = manifest_content.get("ontology", {})
        bindings = ontology_section.get("bindings", [])
        for i, binding in enumerate(bindings):
            entity = binding.get("entity")
            if not entity:
                errors.append(f"ontology.bindings[{i}]: 缺少 entity 字段")
                continue
            if entity not in self.CORE_ENTITIES:
                errors.append(
                    f"ontology.bindings[{i}]: 无效实体 '{entity}'，"
                    f"可选: {self.CORE_ENTITIES}"
                )
            access_mode = binding.get("access_mode")
            if access_mode and access_mode not in VALID_ACCESS_MODES:
                errors.append(
                    f"ontology.bindings[{i}]: 无效访问模式 '{access_mode}'，"
                    f"可选: {sorted(VALID_ACCESS_MODES)}"
                )
            # 校验约束可解析性
            for j, constraint in enumerate(binding.get("constraints", [])):
                if not isinstance(constraint, dict):
                    errors.append(
                        f"ontology.bindings[{i}].constraints[{j}]: "
                        f"约束必须是对象类型"
                    )

        # 3. 校验 MCP 工具
        mcp_section = manifest_content.get("mcp", {})
        tools = mcp_section.get("tools", [])
        for i, tool in enumerate(tools):
            if not tool.get("name"):
                errors.append(f"mcp.tools[{i}]: 缺少 name 字段")
            tier = tool.get("trust_tier_required")
            if tier and tier not in ("T0", "T1", "T2", "T3", "T4"):
                errors.append(
                    f"mcp.tools[{i}]: 无效信任等级 '{tier}'"
                )

        # 4. 校验 triggers
        triggers = manifest_content.get("triggers", [])
        for i, trigger in enumerate(triggers):
            if not trigger.get("event"):
                warnings.append(f"triggers[{i}]: 缺少 event 字段")
            if not trigger.get("action"):
                warnings.append(f"triggers[{i}]: 缺少 action 字段")

        # 5. app_id 存在性检查
        app_result = await db.execute(
            text("""
                SELECT 1 FROM forge_apps
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"app_id": app_id},
        )
        if not app_result.first():
            errors.append(f"应用不存在: {app_id}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    # ── 提交 Manifest ────────────────────────────────────────────
    async def submit_manifest(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        manifest_content: dict,
    ) -> dict:
        """提交 Manifest：校验、存储版本、同步绑定和工具"""
        # 1. 先校验
        validation = await self.validate_manifest(
            db, app_id=app_id, manifest_content=manifest_content,
        )
        if not validation["valid"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Manifest 校验失败",
                    "errors": validation["errors"],
                    "warnings": validation["warnings"],
                },
            )

        # 2. 生成版本记录
        manifest_id = f"mf_{uuid4().hex[:12]}"
        content_str = json.dumps(manifest_content, ensure_ascii=False, sort_keys=True)
        checksum = hashlib.sha256(content_str.encode()).hexdigest()

        await db.execute(
            text("""
                INSERT INTO forge_manifest_versions
                    (id, tenant_id, manifest_id, app_id,
                     content, checksum, forge_version,
                     submitted_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :manifest_id, :app_id,
                     :content::jsonb, :checksum, :forge_version,
                     NOW())
            """),
            {
                "manifest_id": manifest_id,
                "app_id": app_id,
                "content": content_str,
                "checksum": checksum,
                "forge_version": manifest_content.get("forge_version", ""),
            },
        )

        # 3. 同步 ontology bindings：软删除旧的，插入新的
        await db.execute(
            text("""
                UPDATE forge_ontology_bindings
                SET is_deleted = true, updated_at = NOW()
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"app_id": app_id},
        )

        bindings_synced = 0
        ontology_section = manifest_content.get("ontology", {})
        for binding_def in ontology_section.get("bindings", []):
            entity = binding_def.get("entity")
            if not entity:
                continue
            await self.set_binding(
                db,
                app_id=app_id,
                entity_name=entity,
                access_mode=binding_def.get("access_mode", "read"),
                allowed_fields=binding_def.get("allowed_fields", []),
                constraints=binding_def.get("constraints", []),
            )
            bindings_synced += 1

        # 4. 同步 MCP tools（如果有 mcp section）
        tools_synced = 0
        mcp_section = manifest_content.get("mcp", {})
        mcp_tools = mcp_section.get("tools", [])

        if mcp_tools:
            # 查找该 app 关联的 server
            server_result = await db.execute(
                text("""
                    SELECT server_id FROM forge_mcp_servers
                    WHERE app_id = :app_id AND is_deleted = false
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"app_id": app_id},
            )
            server_row = server_result.mappings().first()

            if server_row:
                server_id = server_row["server_id"]

                # 软删除旧工具
                await db.execute(
                    text("""
                        UPDATE forge_mcp_tools
                        SET is_deleted = true, updated_at = NOW()
                        WHERE server_id = :server_id AND is_deleted = false
                    """),
                    {"server_id": server_id},
                )

                from .forge_mcp_service import ForgeMCPService

                mcp_svc = ForgeMCPService()
                for tool_def in mcp_tools:
                    tool_name = tool_def.get("name")
                    if not tool_name:
                        continue
                    await mcp_svc.register_tool(
                        db,
                        server_id=server_id,
                        tool_name=tool_name,
                        description=tool_def.get("description", ""),
                        input_schema=tool_def.get("input_schema", {}),
                        output_schema=tool_def.get("output_schema", {}),
                        ontology_bindings=tool_def.get("ontology_bindings", []),
                        trust_tier_required=tool_def.get(
                            "trust_tier_required", "T1"
                        ),
                    )
                    tools_synced += 1

        log.info(
            "manifest_submitted",
            manifest_id=manifest_id,
            app_id=app_id,
            checksum=checksum,
            bindings_synced=bindings_synced,
            tools_synced=tools_synced,
        )

        return {
            "manifest_id": manifest_id,
            "app_id": app_id,
            "checksum": checksum,
            "validated": True,
            "bindings_synced": bindings_synced,
            "tools_synced": tools_synced,
            "warnings": validation["warnings"],
        }

    # ── Manifest 历史 ────────────────────────────────────────────
    async def get_manifest_history(
        self, db: AsyncSession, app_id: str
    ) -> list[dict]:
        """获取应用的 Manifest 提交历史"""
        result = await db.execute(
            text("""
                SELECT manifest_id, app_id, forge_version,
                       checksum, submitted_at
                FROM forge_manifest_versions
                WHERE app_id = :app_id AND is_deleted = false
                ORDER BY submitted_at DESC
            """),
            {"app_id": app_id},
        )
        return [dict(r) for r in result.mappings().all()]
