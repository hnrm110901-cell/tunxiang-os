"""宴会漏斗投影器（Track D / Sprint R1）

消费 events 表中 banquet.* 三类事件：
    banquet.lead_created
    banquet.lead_stage_changed
    banquet.lead_converted

物化为 mv_banquet_funnel（如该视图暂未建，投影器降级为直接聚合函数）。

运行方式：
    python3 -m services.tx-trade.src.services.banquet_funnel_projector

Sprint R2 投影器上线包会正式建 mv_banquet_funnel（见 docs/reservation-r1-contracts.md §7）。
当前阶段投影器内部维护简单内存聚合，用于 e2e 冒烟 + Agent 早期调试。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import structlog

from shared.events.src.projector import ProjectorBase

logger = structlog.get_logger(__name__)


class BanquetFunnelProjector(ProjectorBase):
    """Banquet Lead 漏斗投影器。

    订阅事件：
        banquet.lead_created / banquet.lead_stage_changed / banquet.lead_converted

    聚合语义：
        - 每个 lead_id（stream_id）维护一个当前 stage 状态
        - 按 source_channel / sales_employee_id（如 payload 中存在）双维度汇总
        - 写入 mv_banquet_funnel（upsert）；DB 不存在时降级为内存 dict

    物化视图（R2 交付）DDL（示意）：
        CREATE MATERIALIZED VIEW mv_banquet_funnel AS
        SELECT
            tenant_id,
            COALESCE(payload->>'sales_employee_id', 'unassigned') AS sales_employee_id,
            payload->>'source_channel' AS source_channel,
            payload->>'stage' AS stage,
            COUNT(*) AS lead_count,
            SUM((payload->>'estimated_amount_fen')::BIGINT) AS amount_fen_total
        FROM events
        WHERE event_type LIKE 'banquet.%'
        GROUP BY tenant_id, sales_employee_id, source_channel, stage;
    """

    name = "banquet_funnel"
    event_types = {
        "banquet.lead_created",
        "banquet.lead_stage_changed",
        "banquet.lead_converted",
    }

    def __init__(self, tenant_id: Any) -> None:
        super().__init__(tenant_id)
        # 内存聚合：lead_id -> 当前状态
        self._state: dict[str, dict[str, Any]] = {}
        # (group_key, stage) -> count
        self._funnel_by_employee: dict[tuple[str, str], int] = defaultdict(int)
        self._funnel_by_channel: dict[tuple[str, str], int] = defaultdict(int)

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        """处理单条事件，更新漏斗物化聚合。

        参数遵循 ProjectorBase 约定：
            event:  {event_id, event_type, stream_id, payload, metadata, ...}
            conn:   asyncpg.Connection（已 set app.tenant_id）
        """
        event_type = event["event_type"]
        stream_id = str(event["stream_id"])
        payload: dict[str, Any] = event.get("payload") or {}

        if event_type == "banquet.lead_created":
            self._apply_created(stream_id, payload)
        elif event_type == "banquet.lead_stage_changed":
            self._apply_stage_changed(stream_id, payload)
        elif event_type == "banquet.lead_converted":
            self._apply_converted(stream_id, payload)
        else:
            # 未知事件类型，直接忽略
            logger.debug(
                "banquet_funnel_projector_skip",
                event_type=event_type,
                stream_id=stream_id,
            )
            return

        # 如 mv_banquet_funnel 存在，则尝试 upsert（DB 失败不抛）
        await self._try_upsert_view(conn)

    # ─────────────────────────────────────────────────────────────────
    # 聚合应用（内存）
    # ─────────────────────────────────────────────────────────────────

    def _apply_created(
        self, stream_id: str, payload: dict[str, Any]
    ) -> None:
        sales_employee_id = payload.get("sales_employee_id") or "unassigned"
        source_channel = payload.get("source_channel") or "booking_desk"
        stage = payload.get("stage") or "all"

        prior = self._state.get(stream_id)
        if prior:
            # 已有状态，幂等跳过
            return

        self._state[stream_id] = {
            "sales_employee_id": sales_employee_id,
            "source_channel": source_channel,
            "stage": stage,
        }
        self._funnel_by_employee[(sales_employee_id, stage)] += 1
        self._funnel_by_channel[(source_channel, stage)] += 1

    def _apply_stage_changed(
        self, stream_id: str, payload: dict[str, Any]
    ) -> None:
        prev_stage = payload.get("previous_stage")
        next_stage = payload.get("next_stage")
        if not next_stage:
            return
        record = self._state.get(stream_id)
        if record is None:
            # 未见 CREATED 事件但直接收到 STAGE_CHANGED（补数/重放），先填骨架
            record = {
                "sales_employee_id": "unassigned",
                "source_channel": "booking_desk",
                "stage": prev_stage or "all",
            }
            self._state[stream_id] = record

        emp = record["sales_employee_id"]
        ch = record["source_channel"]
        cur_stage = record["stage"]
        if cur_stage == next_stage:
            return
        # 扣减旧格子
        self._funnel_by_employee[(emp, cur_stage)] = max(
            0, self._funnel_by_employee[(emp, cur_stage)] - 1
        )
        self._funnel_by_channel[(ch, cur_stage)] = max(
            0, self._funnel_by_channel[(ch, cur_stage)] - 1
        )
        # 累加新格子
        self._funnel_by_employee[(emp, next_stage)] += 1
        self._funnel_by_channel[(ch, next_stage)] += 1
        record["stage"] = next_stage

    def _apply_converted(
        self, stream_id: str, payload: dict[str, Any]
    ) -> None:
        # converted 本身不改 stage（stage 已经是 order），只登记 reservation
        record = self._state.get(stream_id)
        if record is None:
            return
        record["converted_reservation_id"] = payload.get(
            "converted_reservation_id"
        )

    # ─────────────────────────────────────────────────────────────────
    # 物化视图写入（可选，DB 不存在时降级）
    # ─────────────────────────────────────────────────────────────────

    async def _try_upsert_view(self, conn: object) -> None:
        """若 mv_banquet_funnel 表存在则 upsert，否则静默跳过（R2 交付）。"""
        # 动态检查表是否存在（便于 R1 R2 平滑过渡）
        try:
            exists = await conn.fetchval(  # type: ignore[attr-defined]
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'mv_banquet_funnel'
                )
                """
            )
        except (AttributeError, TypeError):
            # conn 是 mock（测试场景），跳过
            return
        if not exists:
            return

        try:
            # 按 channel 维度 upsert
            for (channel, stage), count in self._funnel_by_channel.items():
                await conn.execute(  # type: ignore[attr-defined]
                    """
                    INSERT INTO mv_banquet_funnel
                        (tenant_id, dimension, group_key, stage, lead_count, updated_at)
                    VALUES ($1, 'source_channel', $2, $3, $4, NOW())
                    ON CONFLICT (tenant_id, dimension, group_key, stage)
                    DO UPDATE SET lead_count = $4, updated_at = NOW()
                    """,
                    self.tenant_id,
                    channel,
                    stage,
                    count,
                )
            for (emp, stage), count in self._funnel_by_employee.items():
                await conn.execute(  # type: ignore[attr-defined]
                    """
                    INSERT INTO mv_banquet_funnel
                        (tenant_id, dimension, group_key, stage, lead_count, updated_at)
                    VALUES ($1, 'sales_employee_id', $2, $3, $4, NOW())
                    ON CONFLICT (tenant_id, dimension, group_key, stage)
                    DO UPDATE SET lead_count = $4, updated_at = NOW()
                    """,
                    self.tenant_id,
                    emp,
                    stage,
                    count,
                )
        except (AttributeError, TypeError, RuntimeError) as exc:
            logger.warning(
                "banquet_funnel_upsert_failed",
                error=str(exc),
                tenant_id=str(self.tenant_id),
            )

    # ─────────────────────────────────────────────────────────────────
    # 视图导出（供 Agent/报表降级查询，mv 不可用时使用）
    # ─────────────────────────────────────────────────────────────────

    def snapshot_by_channel(self) -> list[dict[str, Any]]:
        """导出按渠道的当前漏斗聚合快照（内存版）。"""
        out: dict[str, dict[str, int]] = defaultdict(
            lambda: {"all": 0, "opportunity": 0, "order": 0, "invalid": 0, "total": 0}
        )
        for (channel, stage), count in self._funnel_by_channel.items():
            bucket = out[channel]
            if stage in bucket:
                bucket[stage] = count
                bucket["total"] += count
        return [{"source_channel": k, **v} for k, v in out.items()]

    def snapshot_by_sales_employee(self) -> list[dict[str, Any]]:
        """导出按销售员工的当前漏斗聚合快照（内存版）。"""
        out: dict[str, dict[str, int]] = defaultdict(
            lambda: {"all": 0, "opportunity": 0, "order": 0, "invalid": 0, "total": 0}
        )
        for (emp, stage), count in self._funnel_by_employee.items():
            bucket = out[emp]
            if stage in bucket:
                bucket[stage] = count
                bucket["total"] += count
        return [{"sales_employee_id": k, **v} for k, v in out.items()]


__all__ = ["BanquetFunnelProjector"]
