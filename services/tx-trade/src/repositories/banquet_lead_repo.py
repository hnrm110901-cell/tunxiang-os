"""宴会商机 Repository — 数据访问层（SQL + InMemory 双实现）

Track D / Sprint R1 新增。

SQL 实现（BanquetLeadRepository）：
    基于 asyncpg / SQLAlchemy Core，直接操作 banquet_leads 表（v267 迁移）。
    所有查询均在 RLS 上下文下执行（`app.tenant_id` 由 `get_db_with_tenant` 注入）。

内存实现（InMemoryBanquetLeadRepository）：
    Tier 1 单元测试使用，无需真实 DB。保持接口与 SQL 实现对齐。

CRUD + 查询：
    - insert / get_by_id / update
    - list_by_sales_employee / list_by_stage / list_by_source_channel
    - bulk_funnel_counts（按 sales_employee_id 或 source_channel 分组聚合）
    - bulk_source_attribution（按 source_channel 聚合，含 order/converted 计数）
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any, Optional

from shared.ontology.src.extensions.banquet_leads import (
    BanquetLead,
    BanquetType,
    LeadStage,
    SourceChannel,
)

# ──────────────────────────────────────────────────────────────────────────
# 抽象接口
# ──────────────────────────────────────────────────────────────────────────


class BanquetLeadRepositoryBase(ABC):
    """宴会商机 Repository 抽象接口。"""

    @abstractmethod
    async def insert(self, lead: BanquetLead) -> BanquetLead: ...

    @abstractmethod
    async def get_by_id(
        self, lead_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetLead]: ...

    @abstractmethod
    async def update(self, lead: BanquetLead) -> BanquetLead: ...

    @abstractmethod
    async def list_by_sales_employee(
        self,
        tenant_id: uuid.UUID,
        sales_employee_id: uuid.UUID,
        *,
        stage: Optional[LeadStage] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]: ...

    @abstractmethod
    async def list_by_stage(
        self,
        tenant_id: uuid.UUID,
        stage: LeadStage,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]: ...

    @abstractmethod
    async def list_by_source_channel(
        self,
        tenant_id: uuid.UUID,
        source_channel: SourceChannel,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]: ...

    @abstractmethod
    async def bulk_funnel_counts(
        self,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        group_by: str,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def bulk_source_attribution(
        self,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> list[dict[str, Any]]: ...


# ──────────────────────────────────────────────────────────────────────────
# 内存实现（Tier 1 单元测试 & 轻量集成使用）
# ──────────────────────────────────────────────────────────────────────────


class InMemoryBanquetLeadRepository(BanquetLeadRepositoryBase):
    """内存版 Repository，严格按 tenant_id 隔离。"""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, BanquetLead] = {}

    async def insert(self, lead: BanquetLead) -> BanquetLead:
        self._rows[lead.lead_id] = lead
        return lead

    async def get_by_id(
        self, lead_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetLead]:
        row = self._rows.get(lead_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return row

    async def update(self, lead: BanquetLead) -> BanquetLead:
        self._rows[lead.lead_id] = lead
        return lead

    def _tenant_rows(self, tenant_id: uuid.UUID) -> list[BanquetLead]:
        return [r for r in self._rows.values() if r.tenant_id == tenant_id]

    async def list_by_sales_employee(
        self,
        tenant_id: uuid.UUID,
        sales_employee_id: uuid.UUID,
        *,
        stage: Optional[LeadStage] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]:
        rows = [
            r
            for r in self._tenant_rows(tenant_id)
            if r.sales_employee_id == sales_employee_id
            and (stage is None or r.stage == stage)
        ]
        total = len(rows)
        return rows[offset : offset + limit], total

    async def list_by_stage(
        self,
        tenant_id: uuid.UUID,
        stage: LeadStage,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]:
        rows = [r for r in self._tenant_rows(tenant_id) if r.stage == stage]
        total = len(rows)
        return rows[offset : offset + limit], total

    async def list_by_source_channel(
        self,
        tenant_id: uuid.UUID,
        source_channel: SourceChannel,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]:
        rows = [
            r
            for r in self._tenant_rows(tenant_id)
            if r.source_channel == source_channel
        ]
        total = len(rows)
        return rows[offset : offset + limit], total

    async def bulk_funnel_counts(
        self,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        group_by: str,
    ) -> list[dict[str, Any]]:
        if group_by not in ("sales_employee_id", "source_channel"):
            raise ValueError(
                f"group_by must be 'sales_employee_id' or 'source_channel', got {group_by}"
            )

        groups: dict[str, dict[str, Any]] = {}
        for r in self._tenant_rows(tenant_id):
            if r.stage_changed_at < period_start or r.stage_changed_at > period_end:
                # 用 stage_changed_at 判断，与 SQL 侧一致
                # 注意：CREATED 阶段的 lead，stage_changed_at = created_at
                continue
            if group_by == "sales_employee_id":
                key = str(r.sales_employee_id) if r.sales_employee_id else "unassigned"
            else:
                key = r.source_channel.value

            bucket = groups.setdefault(
                key,
                {
                    "group_key": key,
                    "all": 0,
                    "opportunity": 0,
                    "order": 0,
                    "invalid": 0,
                    "total": 0,
                    "estimated_amount_fen_total": 0,
                },
            )
            bucket[r.stage.value] += 1
            bucket["total"] += 1
            bucket["estimated_amount_fen_total"] += r.estimated_amount_fen

        return list(groups.values())

    async def bulk_source_attribution(
        self,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for r in self._tenant_rows(tenant_id):
            if r.stage_changed_at < period_start or r.stage_changed_at > period_end:
                continue
            key = r.source_channel.value
            bucket = out.setdefault(
                key,
                {
                    "source_channel": key,
                    "total": 0,
                    "converted": 0,
                    "invalid": 0,
                    "estimated_amount_fen_total": 0,
                },
            )
            bucket["total"] += 1
            bucket["estimated_amount_fen_total"] += r.estimated_amount_fen
            if r.stage == LeadStage.ORDER:
                bucket["converted"] += 1
            elif r.stage == LeadStage.INVALID:
                bucket["invalid"] += 1
        return list(out.values())

    # ── 测试专用 hook：直接种植一条已存在的 lead（不发事件）──
    async def seed_lead(
        self,
        *,
        tenant_id: uuid.UUID,
        sales_employee_id: Optional[uuid.UUID],
        banquet_type: BanquetType,
        source_channel: SourceChannel,
        stage: LeadStage,
        estimated_amount_fen: int,
        estimated_tables: int,
        scheduled_date: Optional[date],
        stage_changed_at: datetime,
        store_id: Optional[uuid.UUID] = None,
        customer_id: Optional[uuid.UUID] = None,
        invalidation_reason: Optional[str] = None,
    ) -> BanquetLead:
        now = datetime.now(timezone.utc)
        lead = BanquetLead(
            lead_id=uuid.uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=customer_id or uuid.uuid4(),
            sales_employee_id=sales_employee_id,
            banquet_type=banquet_type,
            source_channel=source_channel,
            stage=stage,
            estimated_amount_fen=estimated_amount_fen,
            estimated_tables=estimated_tables,
            scheduled_date=scheduled_date,
            stage_changed_at=stage_changed_at,
            previous_stage=None,
            invalidation_reason=invalidation_reason,
            converted_reservation_id=None,
            metadata={},
            created_by=None,
            created_at=now,
            updated_at=now,
        )
        return await self.insert(lead)


# ──────────────────────────────────────────────────────────────────────────
# SQL 实现（生产使用，通过 asyncpg 直连 banquet_leads）
# ──────────────────────────────────────────────────────────────────────────


_INSERT_SQL = """
INSERT INTO banquet_leads (
    lead_id, tenant_id, store_id, customer_id, sales_employee_id,
    banquet_type, source_channel, stage, estimated_amount_fen, estimated_tables,
    scheduled_date, stage_changed_at, previous_stage, invalidation_reason,
    converted_reservation_id, metadata, created_by, created_at, updated_at
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8, $9, $10,
    $11, $12, $13, $14,
    $15, $16::jsonb, $17, $18, $19
)
"""

_UPDATE_SQL = """
UPDATE banquet_leads
SET stage = $2,
    previous_stage = $3,
    stage_changed_at = $4,
    invalidation_reason = $5,
    converted_reservation_id = $6,
    metadata = $7::jsonb,
    updated_at = $8
WHERE lead_id = $1 AND tenant_id = $9
"""

_SELECT_BY_ID_SQL = """
SELECT lead_id, tenant_id, store_id, customer_id, sales_employee_id,
       banquet_type, source_channel, stage, estimated_amount_fen, estimated_tables,
       scheduled_date, stage_changed_at, previous_stage, invalidation_reason,
       converted_reservation_id, metadata, created_by, created_at, updated_at
FROM banquet_leads
WHERE lead_id = $1 AND tenant_id = $2
"""


def _row_to_lead(row: Any) -> BanquetLead:
    import json

    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return BanquetLead(
        lead_id=row["lead_id"],
        tenant_id=row["tenant_id"],
        store_id=row["store_id"],
        customer_id=row["customer_id"],
        sales_employee_id=row["sales_employee_id"],
        banquet_type=BanquetType(row["banquet_type"]),
        source_channel=SourceChannel(row["source_channel"]),
        stage=LeadStage(row["stage"]),
        estimated_amount_fen=row["estimated_amount_fen"],
        estimated_tables=row["estimated_tables"],
        scheduled_date=row["scheduled_date"],
        stage_changed_at=row["stage_changed_at"],
        previous_stage=(
            LeadStage(row["previous_stage"]) if row["previous_stage"] else None
        ),
        invalidation_reason=row["invalidation_reason"],
        converted_reservation_id=row["converted_reservation_id"],
        metadata=metadata or {},
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class BanquetLeadRepository(BanquetLeadRepositoryBase):
    """asyncpg 版 Repository。连接由调用方（服务/路由层）通过 RLS 上下文提供。"""

    def __init__(self, conn: Any) -> None:
        # conn 是 asyncpg.Connection（应该已设置 app.tenant_id）
        self._conn = conn

    async def insert(self, lead: BanquetLead) -> BanquetLead:
        import json

        await self._conn.execute(
            _INSERT_SQL,
            lead.lead_id,
            lead.tenant_id,
            lead.store_id,
            lead.customer_id,
            lead.sales_employee_id,
            lead.banquet_type.value,
            lead.source_channel.value,
            lead.stage.value,
            lead.estimated_amount_fen,
            lead.estimated_tables,
            lead.scheduled_date,
            lead.stage_changed_at,
            lead.previous_stage.value if lead.previous_stage else None,
            lead.invalidation_reason,
            lead.converted_reservation_id,
            json.dumps(lead.metadata or {}),
            lead.created_by,
            lead.created_at,
            lead.updated_at,
        )
        return lead

    async def get_by_id(
        self, lead_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetLead]:
        row = await self._conn.fetchrow(_SELECT_BY_ID_SQL, lead_id, tenant_id)
        if row is None:
            return None
        return _row_to_lead(row)

    async def update(self, lead: BanquetLead) -> BanquetLead:
        import json

        await self._conn.execute(
            _UPDATE_SQL,
            lead.lead_id,
            lead.stage.value,
            lead.previous_stage.value if lead.previous_stage else None,
            lead.stage_changed_at,
            lead.invalidation_reason,
            lead.converted_reservation_id,
            json.dumps(lead.metadata or {}),
            lead.updated_at,
            lead.tenant_id,
        )
        return lead

    async def list_by_sales_employee(
        self,
        tenant_id: uuid.UUID,
        sales_employee_id: uuid.UUID,
        *,
        stage: Optional[LeadStage] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]:
        params: list[Any] = [tenant_id, sales_employee_id]
        stage_clause = ""
        if stage is not None:
            params.append(stage.value)
            stage_clause = f"AND stage = ${len(params)}"

        total_row = await self._conn.fetchrow(
            f"""
            SELECT COUNT(*) AS n FROM banquet_leads
            WHERE tenant_id = $1 AND sales_employee_id = $2 {stage_clause}
            """,
            *params,
        )
        total = int(total_row["n"]) if total_row else 0

        params.extend([limit, offset])
        rows = await self._conn.fetch(
            f"""
            SELECT * FROM banquet_leads
            WHERE tenant_id = $1 AND sales_employee_id = $2 {stage_clause}
            ORDER BY stage_changed_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            *params,
        )
        return [_row_to_lead(r) for r in rows], total

    async def list_by_stage(
        self,
        tenant_id: uuid.UUID,
        stage: LeadStage,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]:
        total_row = await self._conn.fetchrow(
            "SELECT COUNT(*) AS n FROM banquet_leads WHERE tenant_id = $1 AND stage = $2",
            tenant_id,
            stage.value,
        )
        total = int(total_row["n"]) if total_row else 0
        rows = await self._conn.fetch(
            """
            SELECT * FROM banquet_leads
            WHERE tenant_id = $1 AND stage = $2
            ORDER BY stage_changed_at DESC
            LIMIT $3 OFFSET $4
            """,
            tenant_id,
            stage.value,
            limit,
            offset,
        )
        return [_row_to_lead(r) for r in rows], total

    async def list_by_source_channel(
        self,
        tenant_id: uuid.UUID,
        source_channel: SourceChannel,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetLead], int]:
        total_row = await self._conn.fetchrow(
            "SELECT COUNT(*) AS n FROM banquet_leads WHERE tenant_id = $1 AND source_channel = $2",
            tenant_id,
            source_channel.value,
        )
        total = int(total_row["n"]) if total_row else 0
        rows = await self._conn.fetch(
            """
            SELECT * FROM banquet_leads
            WHERE tenant_id = $1 AND source_channel = $2
            ORDER BY stage_changed_at DESC
            LIMIT $3 OFFSET $4
            """,
            tenant_id,
            source_channel.value,
            limit,
            offset,
        )
        return [_row_to_lead(r) for r in rows], total

    async def bulk_funnel_counts(
        self,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        group_by: str,
    ) -> list[dict[str, Any]]:
        if group_by not in ("sales_employee_id", "source_channel"):
            raise ValueError(
                f"group_by must be 'sales_employee_id' or 'source_channel', got {group_by}"
            )

        # 静态白名单，group_by 已校验，下面拼接安全
        group_col = group_by
        rows = await self._conn.fetch(
            f"""
            SELECT
                COALESCE({group_col}::TEXT, 'unassigned') AS group_key,
                COUNT(*) FILTER (WHERE stage = 'all') AS count_all,
                COUNT(*) FILTER (WHERE stage = 'opportunity') AS count_opportunity,
                COUNT(*) FILTER (WHERE stage = 'order') AS count_order,
                COUNT(*) FILTER (WHERE stage = 'invalid') AS count_invalid,
                COUNT(*) AS total,
                COALESCE(SUM(estimated_amount_fen), 0) AS estimated_amount_fen_total
            FROM banquet_leads
            WHERE tenant_id = $1
              AND stage_changed_at >= $2
              AND stage_changed_at <= $3
            GROUP BY {group_col}
            """,
            tenant_id,
            period_start,
            period_end,
        )
        return [
            {
                "group_key": r["group_key"],
                "all": int(r["count_all"]),
                "opportunity": int(r["count_opportunity"]),
                "order": int(r["count_order"]),
                "invalid": int(r["count_invalid"]),
                "total": int(r["total"]),
                "estimated_amount_fen_total": int(r["estimated_amount_fen_total"]),
            }
            for r in rows
        ]

    async def bulk_source_attribution(
        self,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            """
            SELECT
                source_channel::TEXT AS source_channel,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE stage = 'order') AS converted,
                COUNT(*) FILTER (WHERE stage = 'invalid') AS invalid,
                COALESCE(SUM(estimated_amount_fen), 0) AS estimated_amount_fen_total
            FROM banquet_leads
            WHERE tenant_id = $1
              AND stage_changed_at >= $2
              AND stage_changed_at <= $3
            GROUP BY source_channel
            """,
            tenant_id,
            period_start,
            period_end,
        )
        return [
            {
                "source_channel": r["source_channel"],
                "total": int(r["total"]),
                "converted": int(r["converted"]),
                "invalid": int(r["invalid"]),
                "estimated_amount_fen_total": int(r["estimated_amount_fen_total"]),
            }
            for r in rows
        ]


__all__ = [
    "BanquetLeadRepositoryBase",
    "InMemoryBanquetLeadRepository",
    "BanquetLeadRepository",
]
