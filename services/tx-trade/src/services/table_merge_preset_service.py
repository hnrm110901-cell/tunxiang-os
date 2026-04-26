"""时段拼桌预设服务 (TableMergePresetService)

管理拼桌方案的创建、执行和回滚。
市别切换时由 market_session_routes.py 调用 on_market_session_switch()。

关键设计：
- 执行时只操作 free 状态桌台，occupied 桌台跳过（不打断正在用餐的客人）
- 回滚时只恢复到 free 状态（occupied 桌台在客人离开后自然释放）
- 拼桌本质是逻辑分组，物理桌台不移动，只是在 tables 表标记合并关系
"""

import json
import uuid
from typing import Optional

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class TableMergePresetService:
    """时段拼桌预设服务"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def execute_preset(
        self,
        preset_id: uuid.UUID,
        triggered_by: str = "manual",
        operator_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """执行拼桌预设

        Args:
            preset_id: 预设方案ID
            triggered_by: 触发方式 auto/manual
            operator_id: 操作员ID（auto时为None）

        Returns:
            执行结果 {executed: [...], skipped: [...], log_id: str}
        """
        # 1. 读取预设
        row = (
            (
                await self.db.execute(
                    sa.text(
                        "SELECT id, store_id, market_session_id, merge_rules "
                        "FROM table_merge_presets "
                        "WHERE id = :pid AND tenant_id = :tid "
                        "AND is_active = TRUE AND is_deleted = FALSE"
                    ),
                    {"pid": str(preset_id), "tid": self.tenant_id},
                )
            )
            .mappings()
            .first()
        )

        if not row:
            raise ValueError("预设不存在或已停用")

        store_id = str(row["store_id"])
        market_session_id = row["market_session_id"]
        merge_rules: list[dict] = row["merge_rules"] or []

        if not merge_rules:
            raise ValueError("预设无拼桌规则")

        executed_merges: list[dict] = []
        skipped_merges: list[dict] = []

        # 2. 逐组处理
        for rule in merge_rules:
            group_name = rule.get("group_name", "")
            table_nos: list[str] = rule.get("table_nos", [])
            effective_seats = rule.get("effective_seats")
            target_scene = rule.get("target_scene", "")

            if len(table_nos) < 2:
                skipped_merges.append(
                    {
                        "group_name": group_name,
                        "table_nos": table_nos,
                        "reason": "桌台数不足2张",
                    }
                )
                continue

            # 3. 查询桌台状态
            placeholders = ", ".join(f":tn{i}" for i in range(len(table_nos)))
            params: dict = {
                "store_id": store_id,
                "tid": self.tenant_id,
                **{f"tn{i}": tn for i, tn in enumerate(table_nos)},
            }
            tables = (
                (
                    await self.db.execute(
                        sa.text(
                            f"SELECT id, table_no, status FROM tables "
                            f"WHERE store_id = :store_id AND tenant_id = :tid "
                            f"AND table_no IN ({placeholders}) "
                            f"AND is_deleted = FALSE"
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )

            table_map = {t["table_no"]: t for t in tables}

            # 检查是否所有桌台都 free
            all_free = True
            occupied_nos: list[str] = []
            for tn in table_nos:
                t = table_map.get(tn)
                if not t:
                    all_free = False
                    occupied_nos.append(f"{tn}(不存在)")
                elif t["status"] != "free":
                    all_free = False
                    occupied_nos.append(f"{tn}({t['status']})")

            if not all_free:
                skipped_merges.append(
                    {
                        "group_name": group_name,
                        "table_nos": table_nos,
                        "reason": f"桌台不可用: {', '.join(occupied_nos)}",
                    }
                )
                continue

            # 4. 执行合并 — 标记 occupied + merge_group
            main_table_no = table_nos[0]
            main_table_id = str(table_map[main_table_no]["id"])
            merge_group_id = str(uuid.uuid4())
            table_ids = [str(table_map[tn]["id"]) for tn in table_nos]

            id_placeholders = ", ".join(f":tid{i}" for i in range(len(table_ids)))
            update_params: dict = {
                "mg": merge_group_id,
                "mt": main_table_id,
                **{f"tid{i}": tid for i, tid in enumerate(table_ids)},
            }
            await self.db.execute(
                sa.text(
                    f"UPDATE tables SET status = 'occupied', "
                    f"merge_group_id = :mg, merged_into = :mt, "
                    f"updated_at = NOW() "
                    f"WHERE id IN ({id_placeholders})"
                ),
                update_params,
            )

            executed_merges.append(
                {
                    "group_name": group_name,
                    "table_nos": table_nos,
                    "table_ids": table_ids,
                    "merge_group_id": merge_group_id,
                    "main_table_id": main_table_id,
                    "effective_seats": effective_seats,
                    "target_scene": target_scene,
                }
            )

        # 5. 写入执行日志
        log_id = str(uuid.uuid4())
        await self.db.execute(
            sa.text(
                "INSERT INTO table_merge_logs "
                "(id, tenant_id, store_id, preset_id, trigger_type, "
                "market_session_id, executed_merges, skipped_merges, "
                "executed_by) "
                "VALUES (:id, :tid, :sid, :pid, :tt, :msid, "
                ":em::jsonb, :sm::jsonb, :eby)"
            ),
            {
                "id": log_id,
                "tid": self.tenant_id,
                "sid": store_id,
                "pid": str(preset_id),
                "tt": triggered_by,
                "msid": str(market_session_id) if market_session_id else None,
                "em": json.dumps(executed_merges, ensure_ascii=False),
                "sm": json.dumps(skipped_merges, ensure_ascii=False),
                "eby": str(operator_id) if operator_id else None,
            },
        )

        await self.db.commit()

        logger.info(
            "preset_executed",
            preset_id=str(preset_id),
            triggered_by=triggered_by,
            executed=len(executed_merges),
            skipped=len(skipped_merges),
            tenant_id=self.tenant_id,
        )

        return {
            "log_id": log_id,
            "executed": executed_merges,
            "skipped": skipped_merges,
        }

    async def rollback_log(self, log_id: uuid.UUID) -> dict:
        """回滚一条拼桌执行日志 — 将合并的桌台恢复为 free

        Args:
            log_id: 执行日志ID

        Returns:
            回滚结果 {restored_tables: int}
        """
        row = (
            (
                await self.db.execute(
                    sa.text(
                        "SELECT id, executed_merges, rollback_at "
                        "FROM table_merge_logs "
                        "WHERE id = :lid AND tenant_id = :tid"
                    ),
                    {"lid": str(log_id), "tid": self.tenant_id},
                )
            )
            .mappings()
            .first()
        )

        if not row:
            raise ValueError("执行日志不存在")
        if row["rollback_at"]:
            raise ValueError("该日志已回滚")

        executed_merges: list[dict] = row["executed_merges"] or []
        if not executed_merges:
            raise ValueError("无可回滚的合并操作")

        restored_count = 0
        for merge in executed_merges:
            table_ids: list[str] = merge.get("table_ids", [])
            if not table_ids:
                continue

            id_placeholders = ", ".join(f":tid{i}" for i in range(len(table_ids)))
            params = {f"tid{i}": tid for i, tid in enumerate(table_ids)}

            await self.db.execute(
                sa.text(
                    f"UPDATE tables SET status = 'free', "
                    f"merge_group_id = NULL, merged_into = NULL, "
                    f"updated_at = NOW() "
                    f"WHERE id IN ({id_placeholders})"
                ),
                params,
            )
            restored_count += len(table_ids)

        # 更新日志回滚时间
        await self.db.execute(
            sa.text("UPDATE table_merge_logs SET rollback_at = NOW() WHERE id = :lid"), {"lid": str(log_id)}
        )

        await self.db.commit()

        logger.info(
            "merge_rollback",
            log_id=str(log_id),
            restored_tables=restored_count,
            tenant_id=self.tenant_id,
        )

        return {"restored_tables": restored_count}

    async def on_market_session_switch(
        self,
        store_id: uuid.UUID,
        new_session_id: uuid.UUID,
    ) -> dict:
        """市别切换时自动触发拼桌预设

        由 market_session_routes.py 在切换市别时调用。
        按 priority DESC 顺序执行所有匹配的 auto_trigger 预设。

        Args:
            store_id: 门店ID
            new_session_id: 新市别ID

        Returns:
            汇总结果 {presets_triggered: int, total_executed: int, total_skipped: int}
        """
        rows = (
            (
                await self.db.execute(
                    sa.text(
                        "SELECT id FROM table_merge_presets "
                        "WHERE store_id = :sid AND tenant_id = :tid "
                        "AND market_session_id = :msid "
                        "AND auto_trigger = TRUE "
                        "AND is_active = TRUE AND is_deleted = FALSE "
                        "ORDER BY priority DESC"
                    ),
                    {
                        "sid": str(store_id),
                        "tid": self.tenant_id,
                        "msid": str(new_session_id),
                    },
                )
            )
            .mappings()
            .all()
        )

        total_executed = 0
        total_skipped = 0
        triggered = 0

        for row in rows:
            try:
                result = await self.execute_preset(
                    preset_id=row["id"],
                    triggered_by="auto",
                    operator_id=None,
                )
                total_executed += len(result["executed"])
                total_skipped += len(result["skipped"])
                triggered += 1
            except ValueError as e:
                logger.warning(
                    "auto_preset_skipped",
                    preset_id=str(row["id"]),
                    reason=str(e),
                    tenant_id=self.tenant_id,
                )

        logger.info(
            "market_session_switch_presets",
            store_id=str(store_id),
            new_session_id=str(new_session_id),
            presets_triggered=triggered,
            total_executed=total_executed,
            total_skipped=total_skipped,
            tenant_id=self.tenant_id,
        )

        return {
            "presets_triggered": triggered,
            "total_executed": total_executed,
            "total_skipped": total_skipped,
        }
