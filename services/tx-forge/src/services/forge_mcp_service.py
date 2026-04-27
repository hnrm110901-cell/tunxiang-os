"""MCP Server 注册与管理 — 对标 Anthropic MCP 生态"""

import json
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ── 支持的传输协议 ─────────────────────────────────────────────
VALID_TRANSPORTS: set[str] = {"stdio", "sse", "streamable-http"}

# ── 有效健康状态 ───────────────────────────────────────────────
HEALTH_STATUSES: set[str] = {"healthy", "degraded", "unhealthy", "unknown"}


class ForgeMCPService:
    """MCP Server 注册与管理 — 对标 Anthropic MCP 生态"""

    # ── 注册 MCP Server ──────────────────────────────────────────
    async def register_server(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        server_name: str,
        transport: str = "streamable-http",
        base_url: str = "",
        capabilities: dict | None = None,
        health_endpoint: str | None = None,
    ) -> dict:
        """注册 MCP Server 并同步注册其声明的工具"""
        if transport not in VALID_TRANSPORTS:
            raise HTTPException(
                status_code=422,
                detail=f"无效传输协议: {transport}，可选: {sorted(VALID_TRANSPORTS)}",
            )

        server_id = f"mcp_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_mcp_servers
                    (id, tenant_id, server_id, app_id, server_name,
                     transport, base_url, capabilities,
                     health_endpoint, health_status, last_health_check)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :server_id, :app_id, :server_name,
                     :transport, :base_url, :capabilities::jsonb,
                     :health_endpoint, 'unknown', NOW())
                RETURNING server_id, app_id, server_name, transport,
                          base_url, capabilities, health_endpoint,
                          health_status, created_at
            """),
            {
                "server_id": server_id,
                "app_id": app_id,
                "server_name": server_name,
                "transport": transport,
                "base_url": base_url,
                "capabilities": json.dumps(capabilities or {}, ensure_ascii=False),
                "health_endpoint": health_endpoint,
            },
        )
        server_row = dict(result.mappings().one())

        # 如果 capabilities 声明了 tools，批量注册
        tools_registered = 0
        if capabilities and "tools" in capabilities:
            for tool_def in capabilities["tools"]:
                tool_name = tool_def.get("name")
                if not tool_name:
                    continue
                await self.register_tool(
                    db,
                    server_id=server_id,
                    tool_name=tool_name,
                    description=tool_def.get("description", ""),
                    input_schema=tool_def.get("input_schema", {}),
                    output_schema=tool_def.get("output_schema", {}),
                    ontology_bindings=tool_def.get("ontology_bindings", []),
                    trust_tier_required=tool_def.get("trust_tier_required", "T1"),
                )
                tools_registered += 1

        server_row["tools_registered"] = tools_registered

        log.info(
            "mcp_server_registered",
            server_id=server_id,
            app_id=app_id,
            server_name=server_name,
            transport=transport,
            tools=tools_registered,
        )
        return server_row

    # ── MCP Server 列表 ──────────────────────────────────────────
    async def list_servers(
        self,
        db: AsyncSession,
        *,
        app_id: str | None = None,
        health_status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询 MCP Server，包含每个 server 的工具数量"""
        where_parts = ["s.is_deleted = false"]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if app_id is not None:
            where_parts.append("s.app_id = :app_id")
            params["app_id"] = app_id
        if health_status is not None:
            where_parts.append("s.health_status = :health_status")
            params["health_status"] = health_status

        where_clause = " AND ".join(where_parts)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM forge_mcp_servers s WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text(f"""
                SELECT s.server_id, s.app_id, s.server_name, s.transport,
                       s.base_url, s.health_status, s.last_health_check,
                       s.created_at,
                       COALESCE(tc.tool_count, 0) AS tool_count
                FROM forge_mcp_servers s
                LEFT JOIN (
                    SELECT server_id, COUNT(*) AS tool_count
                    FROM forge_mcp_tools
                    WHERE is_deleted = false
                    GROUP BY server_id
                ) tc ON tc.server_id = s.server_id
                WHERE {where_clause}
                ORDER BY s.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total}

    # ── MCP Server 详情 ──────────────────────────────────────────
    async def get_server(self, db: AsyncSession, server_id: str) -> dict:
        """获取 MCP Server 详情及其所有工具"""
        result = await db.execute(
            text("""
                SELECT server_id, app_id, server_name, transport,
                       base_url, capabilities, health_endpoint,
                       health_status, last_health_check,
                       created_at, updated_at
                FROM forge_mcp_servers
                WHERE server_id = :server_id AND is_deleted = false
            """),
            {"server_id": server_id},
        )
        server_row = result.mappings().first()
        if not server_row:
            raise HTTPException(status_code=404, detail=f"MCP Server 不存在: {server_id}")

        server_dict = dict(server_row)

        # 获取所有工具
        tools_result = await db.execute(
            text("""
                SELECT tool_id, tool_name, description,
                       input_schema, output_schema,
                       ontology_bindings, trust_tier_required,
                       call_count, avg_latency_ms,
                       created_at
                FROM forge_mcp_tools
                WHERE server_id = :server_id AND is_deleted = false
                ORDER BY tool_name ASC
            """),
            {"server_id": server_id},
        )
        server_dict["tools"] = [dict(t) for t in tools_result.mappings().all()]
        return server_dict

    # ── 更新 Server 健康状态 ─────────────────────────────────────
    async def update_server_health(
        self,
        db: AsyncSession,
        server_id: str,
        *,
        health_status: str,
    ) -> dict:
        """更新 MCP Server 健康检查状态"""
        if health_status not in HEALTH_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"无效健康状态: {health_status}，可选: {sorted(HEALTH_STATUSES)}",
            )

        result = await db.execute(
            text("""
                UPDATE forge_mcp_servers
                SET health_status = :health_status,
                    last_health_check = NOW(),
                    updated_at = NOW()
                WHERE server_id = :server_id AND is_deleted = false
                RETURNING server_id, server_name, health_status, last_health_check
            """),
            {"server_id": server_id, "health_status": health_status},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"MCP Server 不存在: {server_id}")

        log.info(
            "mcp_server_health_updated",
            server_id=server_id,
            health_status=health_status,
        )
        return dict(row)

    # ── 工具列表 ─────────────────────────────────────────────────
    async def list_tools(
        self,
        db: AsyncSession,
        *,
        server_id: str | None = None,
        entity: str | None = None,
        trust_tier: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询 MCP 工具"""
        where_parts = ["t.is_deleted = false"]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if server_id is not None:
            where_parts.append("t.server_id = :server_id")
            params["server_id"] = server_id
        if entity is not None:
            # JSONB 包含查询：ontology_bindings 中有指定 entity
            where_parts.append("""t.ontology_bindings @> :entity_filter::jsonb""")
            params["entity_filter"] = json.dumps([{"entity": entity}])
        if trust_tier is not None:
            where_parts.append("t.trust_tier_required = :trust_tier")
            params["trust_tier"] = trust_tier

        where_clause = " AND ".join(where_parts)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM forge_mcp_tools t WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text(f"""
                SELECT t.tool_id, t.server_id, t.tool_name, t.description,
                       t.ontology_bindings, t.trust_tier_required,
                       t.call_count, t.avg_latency_ms,
                       t.created_at
                FROM forge_mcp_tools t
                WHERE {where_clause}
                ORDER BY t.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total}

    # ── 工具 Schema 详情 ─────────────────────────────────────────
    async def get_tool_schema(self, db: AsyncSession, tool_id: str) -> dict:
        """获取单个工具的完整 Schema，包括所属 Server 信息"""
        result = await db.execute(
            text("""
                SELECT t.tool_id, t.server_id, t.tool_name, t.description,
                       t.input_schema, t.output_schema,
                       t.ontology_bindings, t.trust_tier_required,
                       t.call_count, t.avg_latency_ms,
                       t.created_at, t.updated_at,
                       s.server_name, s.transport, s.base_url,
                       s.health_status, s.app_id
                FROM forge_mcp_tools t
                LEFT JOIN forge_mcp_servers s ON s.server_id = t.server_id
                    AND s.is_deleted = false
                WHERE t.tool_id = :tool_id AND t.is_deleted = false
            """),
            {"tool_id": tool_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"MCP 工具不存在: {tool_id}")
        return dict(row)

    # ── 注册工具 ─────────────────────────────────────────────────
    async def register_tool(
        self,
        db: AsyncSession,
        *,
        server_id: str,
        tool_name: str,
        description: str = "",
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        ontology_bindings: list | None = None,
        trust_tier_required: str = "T1",
    ) -> dict:
        """注册单个 MCP 工具"""
        if input_schema is None:
            input_schema = {}
        if output_schema is None:
            output_schema = {}
        if ontology_bindings is None:
            ontology_bindings = []

        tool_id = f"tool_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_mcp_tools
                    (id, tenant_id, tool_id, server_id, tool_name,
                     description, input_schema, output_schema,
                     ontology_bindings, trust_tier_required,
                     call_count, avg_latency_ms)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :tool_id, :server_id, :tool_name,
                     :description, :input_schema::jsonb, :output_schema::jsonb,
                     :ontology_bindings::jsonb, :trust_tier_required,
                     0, 0)
                RETURNING tool_id, server_id, tool_name, description,
                          input_schema, output_schema,
                          ontology_bindings, trust_tier_required,
                          created_at
            """),
            {
                "tool_id": tool_id,
                "server_id": server_id,
                "tool_name": tool_name,
                "description": description,
                "input_schema": json.dumps(input_schema, ensure_ascii=False),
                "output_schema": json.dumps(output_schema, ensure_ascii=False),
                "ontology_bindings": json.dumps(ontology_bindings, ensure_ascii=False),
                "trust_tier_required": trust_tier_required,
            },
        )
        tool_row = dict(result.mappings().one())

        log.info(
            "mcp_tool_registered",
            tool_id=tool_id,
            server_id=server_id,
            tool_name=tool_name,
        )
        return tool_row

    # ── 记录工具调用 ─────────────────────────────────────────────
    async def record_tool_call(
        self,
        db: AsyncSession,
        tool_id: str,
        *,
        latency_ms: int,
    ) -> None:
        """记录一次工具调用，更新调用计数和滚动平均延迟"""
        await db.execute(
            text("""
                UPDATE forge_mcp_tools
                SET call_count = call_count + 1,
                    avg_latency_ms = CASE
                        WHEN call_count = 0 THEN :latency_ms
                        ELSE (avg_latency_ms * call_count + :latency_ms) / (call_count + 1)
                    END,
                    updated_at = NOW()
                WHERE tool_id = :tool_id AND is_deleted = false
            """),
            {"tool_id": tool_id, "latency_ms": latency_ms},
        )
