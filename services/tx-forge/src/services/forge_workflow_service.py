"""Agent编排市场 — 卖工作流不只卖零件 (v3.0)"""

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

log = structlog.get_logger(__name__)

_WORKFLOW_STATUSES = {"draft", "published", "archived", "suspended"}
_RUN_STATUSES = {"pending", "running", "completed", "failed", "cancelled", "timeout"}
_TRIGGER_TYPES = {"manual", "scheduled", "event", "webhook"}

_ALLOWED_UPDATE_FIELDS = {"workflow_name", "description", "steps", "trigger", "estimated_value_fen", "status"}


def _validate_steps(steps: list[dict]) -> None:
    """校验 steps 格式：每一步必须包含 step_id, agent_id, action"""
    required_keys = {"step_id", "agent_id", "action"}
    for i, step in enumerate(steps):
        missing = required_keys - set(step.keys())
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"步骤 {i} 缺少必填字段: {sorted(missing)}",
            )
    # 检查 step_id 唯一性
    step_ids = [s["step_id"] for s in steps]
    if len(step_ids) != len(set(step_ids)):
        raise HTTPException(status_code=422, detail="steps 中存在重复的 step_id")


class ForgeWorkflowService:
    """Agent编排市场 — 卖工作流不只卖零件"""

    # ── 创建工作流 ─────────────────────────────────────────────
    async def create_workflow(
        self,
        db: AsyncSession,
        *,
        workflow_name: str,
        description: str,
        creator_id: str,
        steps: list[dict],
        trigger: dict | None = None,
        estimated_value_fen: int = 0,
    ) -> dict:
        if not steps:
            raise HTTPException(status_code=422, detail="至少需要一个步骤")
        _validate_steps(steps)

        workflow_id = f"wf_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_workflows
                    (id, tenant_id, workflow_id, workflow_name, description,
                     creator_id, steps, trigger, estimated_value_fen, status)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :workflow_id, :workflow_name, :description,
                     :creator_id, :steps::jsonb, :trigger::jsonb,
                     :estimated_value_fen, 'draft')
                RETURNING workflow_id, workflow_name, creator_id, status,
                          estimated_value_fen, created_at
            """),
            {
                "workflow_id": workflow_id,
                "workflow_name": workflow_name,
                "description": description,
                "creator_id": creator_id,
                "steps": json.dumps(steps, ensure_ascii=False),
                "trigger": json.dumps(trigger, ensure_ascii=False) if trigger else "{}",
                "estimated_value_fen": estimated_value_fen,
            },
        )
        row = dict(result.mappings().one())
        log.info("workflow.created", workflow_id=workflow_id, steps_count=len(steps))
        return row

    # ── 工作流列表 ─────────────────────────────────────────────
    async def list_workflows(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        creator_id: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        conditions = ["is_deleted = false"]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if status:
            if status not in _WORKFLOW_STATUSES:
                raise HTTPException(
                    status_code=422,
                    detail=f"无效状态: {status}，可选: {sorted(_WORKFLOW_STATUSES)}",
                )
            conditions.append("status = :status")
            params["status"] = status
        if creator_id:
            conditions.append("creator_id = :creator_id")
            params["creator_id"] = creator_id

        where = " AND ".join(conditions)

        total_row = await db.execute(
            text(f"SELECT count(*) FROM forge_workflows WHERE {where}"), params
        )
        total = total_row.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT workflow_id, workflow_name, creator_id, status,
                       estimated_value_fen, created_at, updated_at
                FROM forge_workflows
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in rows.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    # ── 工作流详情 ─────────────────────────────────────────────
    async def get_workflow(self, db: AsyncSession, workflow_id: str) -> dict:
        result = await db.execute(
            text("""
                SELECT workflow_id, workflow_name, description, creator_id,
                       steps, trigger, estimated_value_fen, status,
                       created_at, updated_at
                FROM forge_workflows
                WHERE workflow_id = :wid AND is_deleted = false
            """),
            {"wid": workflow_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")

        workflow = dict(row)

        # 附加最近运行摘要
        runs_row = await db.execute(
            text("""
                SELECT count(*) AS total_runs,
                       count(*) FILTER (WHERE status = 'completed') AS completed,
                       count(*) FILTER (WHERE status = 'failed') AS failed,
                       count(*) FILTER (WHERE status = 'running') AS running
                FROM forge_workflow_runs
                WHERE workflow_id = :wid AND is_deleted = false
            """),
            {"wid": workflow_id},
        )
        workflow["run_summary"] = dict(runs_row.mappings().one())
        return workflow

    # ── 更新工作流 ─────────────────────────────────────────────
    async def update_workflow(
        self, db: AsyncSession, workflow_id: str, updates: dict
    ) -> dict:
        invalid_keys = set(updates.keys()) - _ALLOWED_UPDATE_FIELDS
        if invalid_keys:
            raise HTTPException(
                status_code=422,
                detail=f"不允许更新的字段: {sorted(invalid_keys)}",
            )
        if not updates:
            raise HTTPException(status_code=422, detail="无更新内容")

        # 如果更新 steps，需要校验格式
        if "steps" in updates:
            _validate_steps(updates["steps"])

        existing = await self.get_workflow(db, workflow_id)
        if existing["status"] not in ("draft", "published"):
            raise HTTPException(
                status_code=422,
                detail=f"工作流状态为 {existing['status']}，不可编辑",
            )

        set_parts: list[str] = ["updated_at = NOW()"]
        params: dict = {"wid": workflow_id}
        for key, val in updates.items():
            if key in ("steps", "trigger"):
                set_parts.append(f"{key} = :{key}::jsonb")
                params[key] = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else val
            else:
                set_parts.append(f"{key} = :{key}")
                params[key] = val

        result = await db.execute(
            text(f"""
                UPDATE forge_workflows
                SET {', '.join(set_parts)}
                WHERE workflow_id = :wid AND is_deleted = false
                RETURNING workflow_id, workflow_name, status, updated_at
            """),
            params,
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"更新失败，工作流不存在: {workflow_id}")
        log.info("workflow.updated", workflow_id=workflow_id, fields=list(updates.keys()))
        return dict(row)

    # ── 启动工作流运行 ─────────────────────────────────────────
    async def start_workflow_run(
        self,
        db: AsyncSession,
        *,
        workflow_id: str,
        store_id: str | None = None,
        trigger_type: str = "manual",
        trigger_data: dict | None = None,
    ) -> dict:
        if trigger_type not in _TRIGGER_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"无效触发类型: {trigger_type}，可选: {sorted(_TRIGGER_TYPES)}",
            )

        # 验证工作流存在且已发布
        wf = await self.get_workflow(db, workflow_id)
        if wf["status"] != "published":
            raise HTTPException(
                status_code=422,
                detail=f"工作流状态为 {wf['status']}，仅 published 可运行",
            )

        run_id = f"wfr_{uuid4().hex[:12]}"
        steps = wf.get("steps", [])

        result = await db.execute(
            text("""
                INSERT INTO forge_workflow_runs
                    (id, tenant_id, run_id, workflow_id, store_id,
                     trigger_type, trigger_data, status,
                     total_steps, steps_completed, started_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :run_id, :workflow_id, :store_id,
                     :trigger_type, :trigger_data::jsonb, 'running',
                     :total_steps, 0, NOW())
                RETURNING run_id, workflow_id, store_id, trigger_type,
                          status, total_steps, started_at
            """),
            {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "store_id": store_id,
                "trigger_type": trigger_type,
                "trigger_data": json.dumps(trigger_data or {}, ensure_ascii=False),
                "total_steps": len(steps),
            },
        )
        row = dict(result.mappings().one())
        log.info("workflow.run_started", run_id=run_id, workflow_id=workflow_id, trigger=trigger_type)
        return row

    # ── 更新运行状态 ─────────────────────────────────────────
    async def update_run_status(
        self,
        db: AsyncSession,
        run_id: str,
        *,
        status: str,
        steps_completed: int | None = None,
        result: dict | None = None,
        error_message: str | None = None,
        total_tokens: int = 0,
        total_cost_fen: int = 0,
    ) -> dict:
        if status not in _RUN_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"无效运行状态: {status}，可选: {sorted(_RUN_STATUSES)}",
            )

        set_parts = ["status = :status", "updated_at = NOW()"]
        params: dict = {"rid": run_id, "status": status}

        if steps_completed is not None:
            set_parts.append("steps_completed = :steps_completed")
            params["steps_completed"] = steps_completed
        if result is not None:
            set_parts.append("result = :result::jsonb")
            params["result"] = json.dumps(result, ensure_ascii=False)
        if error_message is not None:
            set_parts.append("error_message = :error_message")
            params["error_message"] = error_message
        if total_tokens > 0:
            set_parts.append("total_tokens = :total_tokens")
            params["total_tokens"] = total_tokens
        if total_cost_fen > 0:
            set_parts.append("total_cost_fen = :total_cost_fen")
            params["total_cost_fen"] = total_cost_fen

        # 终态时设置 finished_at
        if status in ("completed", "failed", "cancelled", "timeout"):
            set_parts.append("finished_at = NOW()")

        row = await db.execute(
            text(f"""
                UPDATE forge_workflow_runs
                SET {', '.join(set_parts)}
                WHERE run_id = :rid AND is_deleted = false
                RETURNING run_id, workflow_id, status, steps_completed,
                          total_tokens, total_cost_fen, started_at, finished_at
            """),
            params,
        )
        updated = row.mappings().first()
        if not updated:
            raise HTTPException(status_code=404, detail=f"运行记录不存在: {run_id}")
        log.info("workflow.run_updated", run_id=run_id, status=status)
        return dict(updated)

    # ── 获取运行详情 ─────────────────────────────────────────
    async def get_run(self, db: AsyncSession, run_id: str) -> dict:
        result = await db.execute(
            text("""
                SELECT run_id, workflow_id, store_id, trigger_type, trigger_data,
                       status, total_steps, steps_completed, result,
                       error_message, total_tokens, total_cost_fen,
                       started_at, finished_at, created_at
                FROM forge_workflow_runs
                WHERE run_id = :rid AND is_deleted = false
            """),
            {"rid": run_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"运行记录不存在: {run_id}")
        return dict(row)

    # ── 运行列表 ─────────────────────────────────────────────
    async def list_runs(
        self,
        db: AsyncSession,
        *,
        workflow_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        conditions = ["is_deleted = false"]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if workflow_id:
            conditions.append("workflow_id = :workflow_id")
            params["workflow_id"] = workflow_id
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)

        total_row = await db.execute(
            text(f"SELECT count(*) FROM forge_workflow_runs WHERE {where}"), params
        )
        total = total_row.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT run_id, workflow_id, store_id, trigger_type,
                       status, steps_completed, total_steps,
                       total_tokens, total_cost_fen,
                       started_at, finished_at
                FROM forge_workflow_runs
                WHERE {where}
                ORDER BY started_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in rows.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    # ── 工作流分析 ─────────────────────────────────────────────
    async def get_workflow_analytics(self, db: AsyncSession, workflow_id: str) -> dict:
        # 验证存在
        await self.get_workflow(db, workflow_id)

        result = await db.execute(
            text("""
                SELECT
                    count(*) AS total_runs,
                    count(*) FILTER (WHERE status = 'completed') AS completed_runs,
                    count(*) FILTER (WHERE status = 'failed') AS failed_runs,
                    CASE WHEN count(*) > 0
                         THEN round(count(*) FILTER (WHERE status = 'completed')::numeric / count(*) * 100, 1)
                         ELSE 0 END AS success_rate,
                    COALESCE(AVG(EXTRACT(EPOCH FROM (finished_at - started_at)))
                             FILTER (WHERE finished_at IS NOT NULL), 0) AS avg_duration_seconds,
                    COALESCE(AVG(total_cost_fen) FILTER (WHERE status = 'completed'), 0) AS avg_cost_fen,
                    COALESCE(AVG(total_tokens) FILTER (WHERE status = 'completed'), 0) AS avg_tokens,
                    COALESCE(SUM(total_cost_fen), 0) AS total_cost_fen,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM forge_workflow_runs
                WHERE workflow_id = :wid AND is_deleted = false
            """),
            {"wid": workflow_id},
        )
        analytics = dict(result.mappings().one())
        analytics["workflow_id"] = workflow_id
        return analytics
