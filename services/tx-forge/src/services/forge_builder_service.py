"""Forge Builder 可视化Agent构建器 — PostgreSQL 异步实现 (v2.5)"""

import json
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class ForgeBuilderService:
    """Forge Builder — 可视化Agent构建器"""

    TEMPLATE_TYPES = {
        "data_analysis": "数据分析型 — 读取Ontology→Claude分析→生成报告",
        "automation": "自动化执行型 — 事件触发→条件判断→执行Action",
        "conversational": "对话交互型 — 用户提问→检索知识库→回答",
        "monitoring": "监控预警型 — 定时巡检→异常检测→告警",
        "optimization": "优化决策型 — 收集数据→建模→推荐→人类审批",
    }

    _ALLOWED_UPDATE_FIELDS = {"project_name", "canvas", "generated_code", "status"}

    # ── 创建项目 ─────────────────────────────────────────────
    async def create_project(
        self,
        db: AsyncSession,
        *,
        developer_id: str,
        project_name: str,
        template_type: str,
    ) -> dict:
        if template_type not in self.TEMPLATE_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"无效模板类型: {template_type}，可选: {sorted(self.TEMPLATE_TYPES)}",
            )

        # 验证开发者存在
        dev_check = await db.execute(
            text("SELECT 1 FROM forge_developers WHERE developer_id = :did AND is_deleted = false"),
            {"did": developer_id},
        )
        if not dev_check.first():
            raise HTTPException(status_code=404, detail=f"开发者不存在: {developer_id}")

        project_id = f"proj_{uuid4().hex[:12]}"

        # 加载模板脚手架
        tpl_row = await db.execute(
            text("""
                SELECT template_id, template_name, scaffold_canvas, scaffold_code
                FROM forge_builder_templates
                WHERE template_type = :tt AND is_deleted = false
                ORDER BY created_at DESC LIMIT 1
            """),
            {"tt": template_type},
        )
        tpl = tpl_row.mappings().first()
        initial_canvas = json.dumps(tpl["scaffold_canvas"]) if tpl and tpl["scaffold_canvas"] else "{}"
        initial_code = tpl["scaffold_code"] if tpl else ""

        result = await db.execute(
            text("""
                INSERT INTO forge_builder_projects
                    (id, tenant_id, project_id, developer_id, project_name,
                     template_type, canvas, generated_code, status)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :project_id, :developer_id, :project_name,
                     :template_type, :canvas::jsonb, :generated_code, 'draft')
                RETURNING project_id, developer_id, project_name, template_type, status, created_at
            """),
            {
                "project_id": project_id,
                "developer_id": developer_id,
                "project_name": project_name,
                "template_type": template_type,
                "canvas": initial_canvas,
                "generated_code": initial_code,
            },
        )
        row = dict(result.mappings().one())
        log.info("builder.project_created", project_id=project_id, template_type=template_type)
        return row

    # ── 列表查询 ─────────────────────────────────────────────
    async def list_projects(
        self,
        db: AsyncSession,
        *,
        developer_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        conditions = ["is_deleted = false"]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if developer_id:
            conditions.append("developer_id = :developer_id")
            params["developer_id"] = developer_id
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)

        total_row = await db.execute(text(f"SELECT count(*) FROM forge_builder_projects WHERE {where}"), params)
        total = total_row.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT project_id, developer_id, project_name, template_type,
                       status, created_at, updated_at
                FROM forge_builder_projects
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in rows.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    # ── 获取项目详情 ─────────────────────────────────────────
    async def get_project(self, db: AsyncSession, project_id: str) -> dict:
        result = await db.execute(
            text("""
                SELECT project_id, developer_id, project_name, template_type,
                       canvas, generated_code, status, created_at, updated_at
                FROM forge_builder_projects
                WHERE project_id = :pid AND is_deleted = false
            """),
            {"pid": project_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")
        return dict(row)

    # ── 更新项目 ─────────────────────────────────────────────
    async def update_project(self, db: AsyncSession, project_id: str, updates: dict) -> dict:
        invalid_keys = set(updates.keys()) - self._ALLOWED_UPDATE_FIELDS
        if invalid_keys:
            raise HTTPException(
                status_code=422,
                detail=f"不允许更新的字段: {sorted(invalid_keys)}",
            )
        if not updates:
            raise HTTPException(status_code=422, detail="无更新内容")

        # 验证项目存在且为 draft
        existing = await self.get_project(db, project_id)
        if existing["status"] not in ("draft", "revision"):
            raise HTTPException(
                status_code=422,
                detail=f"项目状态为 {existing['status']}，仅 draft/revision 可编辑",
            )

        set_parts: list[str] = ["updated_at = NOW()"]
        params: dict = {"pid": project_id}
        for key, val in updates.items():
            if key == "canvas":
                set_parts.append(f"canvas = :{key}::jsonb")
                params[key] = json.dumps(val) if isinstance(val, dict) else val
            else:
                set_parts.append(f"{key} = :{key}")
                params[key] = val

        result = await db.execute(
            text(f"""
                UPDATE forge_builder_projects
                SET {", ".join(set_parts)}
                WHERE project_id = :pid AND is_deleted = false
                RETURNING project_id, project_name, status, updated_at
            """),
            params,
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"更新失败，项目不存在: {project_id}")
        log.info("builder.project_updated", project_id=project_id, fields=list(updates.keys()))
        return dict(row)

    # ── 提交项目 ─────────────────────────────────────────────
    async def submit_project(self, db: AsyncSession, project_id: str) -> dict:
        existing = await self.get_project(db, project_id)
        if existing["status"] not in ("draft", "revision"):
            raise HTTPException(
                status_code=422,
                detail=f"项目状态为 {existing['status']}，仅 draft/revision 可提交",
            )

        # 更新项目状态为 submitted
        await db.execute(
            text("""
                UPDATE forge_builder_projects
                SET status = 'submitted', updated_at = NOW()
                WHERE project_id = :pid AND is_deleted = false
            """),
            {"pid": project_id},
        )

        # 自动创建 forge_app 记录
        app_id = f"app_{uuid4().hex[:12]}"
        await db.execute(
            text("""
                INSERT INTO forge_apps
                    (id, tenant_id, app_id, developer_id, app_name, category,
                     description, status, current_version, source_project_id)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :app_id, :developer_id, :app_name, 'ai_addon',
                     :description, 'pending_review', '1.0.0', :project_id)
            """),
            {
                "app_id": app_id,
                "developer_id": existing["developer_id"],
                "app_name": existing["project_name"],
                "description": f"由 Forge Builder 项目 {project_id} 生成",
                "project_id": project_id,
            },
        )

        log.info("builder.project_submitted", project_id=project_id, app_id=app_id)
        return {
            "project_id": project_id,
            "status": "submitted",
            "app_id": app_id,
            "message": "项目已提交，应用已自动创建并进入审核流程",
        }

    # ── 模板列表 ─────────────────────────────────────────────
    async def list_templates(self, db: AsyncSession, *, template_type: str | None = None) -> list[dict]:
        conditions = ["is_deleted = false"]
        params: dict = {}

        if template_type:
            if template_type not in self.TEMPLATE_TYPES:
                raise HTTPException(
                    status_code=422,
                    detail=f"无效模板类型: {template_type}，可选: {sorted(self.TEMPLATE_TYPES)}",
                )
            conditions.append("template_type = :tt")
            params["tt"] = template_type

        where = " AND ".join(conditions)
        rows = await db.execute(
            text(f"""
                SELECT template_id, template_name, template_type,
                       description, created_at
                FROM forge_builder_templates
                WHERE {where}
                ORDER BY template_type, template_name
            """),
            params,
        )
        return [dict(r) for r in rows.mappings().all()]

    # ── 模板详情 ─────────────────────────────────────────────
    async def get_template(self, db: AsyncSession, template_id: str) -> dict:
        result = await db.execute(
            text("""
                SELECT template_id, template_name, template_type, description,
                       scaffold_canvas, scaffold_code, created_at
                FROM forge_builder_templates
                WHERE template_id = :tid AND is_deleted = false
            """),
            {"tid": template_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
        return dict(row)
