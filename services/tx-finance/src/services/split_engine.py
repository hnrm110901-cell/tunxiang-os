"""分账引擎 — 支付通道分账 + 品牌/加盟分润规则（v100）

核心逻辑：
  1. 维护分润规则（profit_split_rules）：recipient_type、split_method、applicable 范围
  2. execute_split：对一笔交易匹配全部有效规则，生成 profit_split_records 流水
  3. settle_records：批量将 pending 记录标记为 settled（对接实际付款后回调）
  4. get_settlement_summary：按 recipient + 时段聚合应付/已付金额
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 合法的 recipient_type
RECIPIENT_TYPES = {"brand", "franchise", "supplier", "platform", "custom"}
# 合法的 split_method
SPLIT_METHODS = {"percentage", "fixed_fen"}


class SplitEngine:
    """分账引擎数据访问层 + 核心业务逻辑"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════
    # 分润规则 CRUD
    # ══════════════════════════════════════════════════════

    async def upsert_rule(self, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建或更新分润规则（按 name + tenant_id UPSERT）"""
        await self._set_tenant()

        rule_id = rule_data.get("id")
        if rule_id:
            # 更新
            rule_uuid = uuid.UUID(rule_id)
            await self.db.execute(
                text("""
                    UPDATE profit_split_rules
                    SET name               = :name,
                        recipient_type     = :rtype,
                        recipient_id       = :rid,
                        split_method       = :method,
                        percentage         = :pct,
                        fixed_fen          = :fixed,
                        applicable_stores  = :stores::jsonb,
                        applicable_channels= :channels::jsonb,
                        priority           = :priority,
                        is_active          = :active,
                        valid_from         = :vfrom,
                        valid_to           = :vto,
                        updated_at         = NOW()
                    WHERE id = :id AND tenant_id = :tid
                """),
                self._rule_params(rule_data, rule_uuid),
            )
            await self.db.flush()
            log.info("split_rule.updated", rule_id=rule_id, tenant_id=self.tenant_id)
        else:
            # 新建
            rule_uuid = uuid.uuid4()
            await self.db.execute(
                text("""
                    INSERT INTO profit_split_rules
                        (id, tenant_id, name, recipient_type, recipient_id,
                         split_method, percentage, fixed_fen,
                         applicable_stores, applicable_channels,
                         priority, is_active, valid_from, valid_to)
                    VALUES
                        (:id, :tid, :name, :rtype, :rid,
                         :method, :pct, :fixed,
                         :stores::jsonb, :channels::jsonb,
                         :priority, :active, :vfrom, :vto)
                """),
                self._rule_params(rule_data, rule_uuid),
            )
            await self.db.flush()
            log.info("split_rule.created", rule_id=str(rule_uuid), tenant_id=self.tenant_id)

        return await self.get_rule(str(rule_uuid))  # type: ignore[return-value]

    def _rule_params(self, d: Dict[str, Any], rule_uuid: uuid.UUID) -> Dict[str, Any]:
        recipient_id_raw = d.get("recipient_id")
        return {
            "id": rule_uuid,
            "tid": self._tid,
            "name": d["name"],
            "rtype": d["recipient_type"],
            "rid": uuid.UUID(recipient_id_raw) if recipient_id_raw else None,
            "method": d["split_method"],
            "pct": d.get("percentage"),
            "fixed": d.get("fixed_fen"),
            "stores": json.dumps(d.get("applicable_stores", [])),
            "channels": json.dumps(d.get("applicable_channels", [])),
            "priority": d.get("priority", 0),
            "active": d.get("is_active", True),
            "vfrom": d.get("valid_from"),
            "vto": d.get("valid_to"),
        }

    async def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """查询单条规则"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, name, recipient_type, recipient_id,
                       split_method, percentage, fixed_fen,
                       applicable_stores, applicable_channels,
                       priority, is_active, valid_from, valid_to,
                       created_at, updated_at
                FROM profit_split_rules
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(rule_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._rule_row(row) if row else None

    async def list_rules(
        self,
        is_active: Optional[bool] = None,
        recipient_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出租户分润规则"""
        await self._set_tenant()
        sql = """
            SELECT id, name, recipient_type, recipient_id,
                   split_method, percentage, fixed_fen,
                   applicable_stores, applicable_channels,
                   priority, is_active, valid_from, valid_to,
                   created_at, updated_at
            FROM profit_split_rules
            WHERE tenant_id = :tid
        """
        params: Dict[str, Any] = {"tid": self._tid}
        if is_active is not None:
            sql += " AND is_active = :active"
            params["active"] = is_active
        if recipient_type:
            sql += " AND recipient_type = :rtype"
            params["rtype"] = recipient_type
        sql += " ORDER BY priority ASC, created_at ASC"

        result = await self.db.execute(text(sql), params)
        return [self._rule_row(r) for r in result.fetchall()]

    async def deactivate_rule(self, rule_id: str) -> bool:
        """停用规则（软删除）"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                UPDATE profit_split_rules
                SET is_active = FALSE, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND is_active = TRUE
            """),
            {"id": uuid.UUID(rule_id), "tid": self._tid},
        )
        await self.db.flush()
        return result.rowcount > 0

    # ══════════════════════════════════════════════════════
    # 分账执行
    # ══════════════════════════════════════════════════════

    async def execute_split(
        self,
        order_id: str,
        store_id: str,
        channel: Optional[str],
        gross_amount_fen: int,
        transaction_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """对一笔交易匹配所有有效规则，生成分润流水。

        匹配逻辑：
          1. is_active = TRUE
          2. valid_from/valid_to 在交易日期范围内（NULL = 不限）
          3. applicable_stores: 空数组 = 全门店；非空 = 必须包含 store_id
          4. applicable_channels: 空数组 = 全渠道；非空 = 必须包含 channel
        """
        await self._set_tenant()
        t_date = transaction_date or date.today()

        result = await self.db.execute(
            text("""
                SELECT id, name, recipient_type, recipient_id,
                       split_method, percentage, fixed_fen,
                       applicable_stores, applicable_channels
                FROM profit_split_rules
                WHERE tenant_id = :tid
                  AND is_active = TRUE
                  AND (valid_from IS NULL OR valid_from <= :tdate)
                  AND (valid_to   IS NULL OR valid_to   >= :tdate)
                ORDER BY priority ASC
            """),
            {"tid": self._tid, "tdate": t_date},
        )
        all_rules = result.fetchall()

        oid = uuid.UUID(order_id)
        sid = uuid.UUID(store_id)
        created: List[Dict[str, Any]] = []

        for rule in all_rules:
            # 检查门店范围
            stores = rule.applicable_stores if isinstance(rule.applicable_stores, list) else json.loads(rule.applicable_stores or "[]")
            if stores and store_id not in stores:
                continue
            # 检查渠道范围
            channels = rule.applicable_channels if isinstance(rule.applicable_channels, list) else json.loads(rule.applicable_channels or "[]")
            if channels and channel not in channels:
                continue

            # 计算分润金额
            if rule.split_method == "percentage":
                split_amount = int(gross_amount_fen * float(rule.percentage))
            else:
                split_amount = int(rule.fixed_fen)

            if split_amount <= 0:
                continue

            rec_id = uuid.uuid4()
            await self.db.execute(
                text("""
                    INSERT INTO profit_split_records
                        (id, tenant_id, order_id, store_id, channel,
                         rule_id, recipient_type, recipient_id,
                         gross_amount_fen, split_amount_fen, status)
                    VALUES
                        (:id, :tid, :oid, :sid, :channel,
                         :rule_id, :rtype, :rid,
                         :gross, :split, 'pending')
                """),
                {
                    "id": rec_id,
                    "tid": self._tid,
                    "oid": oid,
                    "sid": sid,
                    "channel": channel,
                    "rule_id": rule.id,
                    "rtype": rule.recipient_type,
                    "rid": rule.recipient_id,
                    "gross": gross_amount_fen,
                    "split": split_amount,
                },
            )
            created.append({
                "record_id": str(rec_id),
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "recipient_type": rule.recipient_type,
                "recipient_id": str(rule.recipient_id) if rule.recipient_id else None,
                "split_amount_fen": split_amount,
                "split_amount_yuan": round(split_amount / 100, 2),
            })

        await self.db.flush()
        log.info("split_executed", order_id=order_id, store_id=store_id,
                 gross_fen=gross_amount_fen, records=len(created), tenant_id=self.tenant_id)
        return created

    async def settle_records(self, record_ids: List[str]) -> int:
        """批量将 pending 记录标记为 settled（实际付款后调用）"""
        await self._set_tenant()
        if not record_ids:
            return 0
        uuids = [uuid.UUID(r) for r in record_ids]
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text("""
                UPDATE profit_split_records
                SET status = 'settled', settled_at = :now
                WHERE tenant_id = :tid AND id = ANY(:ids) AND status = 'pending'
            """),
            {"now": now, "tid": self._tid, "ids": uuids},
        )
        await self.db.flush()
        log.info("split_records_settled", count=result.rowcount, tenant_id=self.tenant_id)
        return result.rowcount

    async def fail_records(self, record_ids: List[str]) -> int:
        """将 pending 记录标记为 cancelled（通道分账失败 / 拒付等）。"""
        await self._set_tenant()
        if not record_ids:
            return 0
        uuids = [uuid.UUID(r) for r in record_ids]
        result = await self.db.execute(
            text("""
                UPDATE profit_split_records
                SET status = 'cancelled'
                WHERE tenant_id = :tid AND id = ANY(:ids) AND status = 'pending'
            """),
            {"tid": self._tid, "ids": uuids},
        )
        await self.db.flush()
        log.info(
            "split_records_cancelled",
            count=result.rowcount,
            tenant_id=self.tenant_id,
        )
        return result.rowcount

    async def apply_channel_notification(
        self,
        items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """支付通道异步结果：按条将流水置为 settled 或 cancelled。

        仅处理 ``status = pending`` 的行；已结算/已取消的重试调用不会产生副作用（幂等）。
        """
        settled_ids: List[str] = []
        failed_ids: List[str] = []
        for it in items:
            rid = str(it.get("record_id", "")).strip()
            outcome = str(it.get("outcome", "")).strip().lower()
            if not rid:
                continue
            if outcome == "settled":
                settled_ids.append(rid)
            elif outcome in ("failed", "cancelled", "canceled"):
                failed_ids.append(rid)
        settled_n = await self.settle_records(settled_ids)
        failed_n = await self.fail_records(failed_ids)
        return {
            "settled": settled_n,
            "cancelled": failed_n,
            "settled_requested": len(settled_ids),
            "cancelled_requested": len(failed_ids),
        }

    # ══════════════════════════════════════════════════════
    # 查询 & 汇总
    # ══════════════════════════════════════════════════════

    async def list_split_records(
        self,
        order_id: Optional[str] = None,
        store_id: Optional[str] = None,
        recipient_type: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """查询分润流水列表"""
        await self._set_tenant()
        where = "WHERE tenant_id = :tid"
        params: Dict[str, Any] = {"tid": self._tid}

        if order_id:
            where += " AND order_id = :oid"
            params["oid"] = uuid.UUID(order_id)
        if store_id:
            where += " AND store_id = :sid"
            params["sid"] = uuid.UUID(store_id)
        if recipient_type:
            where += " AND recipient_type = :rtype"
            params["rtype"] = recipient_type
        if status:
            where += " AND status = :status"
            params["status"] = status
        if start_date:
            where += " AND created_at >= :sd::timestamptz"
            params["sd"] = start_date
        if end_date:
            where += " AND created_at < (:ed::date + INTERVAL '1 day')::timestamptz"
            params["ed"] = end_date

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM profit_split_records {where}"), params
        )
        total = count_result.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await self.db.execute(
            text(f"""
                SELECT r.id, r.order_id, r.store_id, r.channel,
                       r.rule_id, r.recipient_type, r.recipient_id,
                       r.gross_amount_fen, r.split_amount_fen, r.status,
                       r.settled_at, r.created_at,
                       rl.name AS rule_name
                FROM profit_split_records r
                LEFT JOIN profit_split_rules rl ON rl.id = r.rule_id
                {where}
                ORDER BY r.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [self._record_row(r) for r in result.fetchall()]
        return {"items": items, "total": total}

    async def get_settlement_summary(
        self,
        recipient_type: Optional[str] = None,
        recipient_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按 recipient 聚合应付（pending）和已付（settled）金额"""
        await self._set_tenant()
        where = "WHERE tenant_id = :tid"
        params: Dict[str, Any] = {"tid": self._tid}

        if recipient_type:
            where += " AND recipient_type = :rtype"
            params["rtype"] = recipient_type
        if recipient_id:
            where += " AND recipient_id = :rid"
            params["rid"] = uuid.UUID(recipient_id)
        if start_date:
            where += " AND created_at >= :sd::timestamptz"
            params["sd"] = start_date
        if end_date:
            where += " AND created_at < (:ed::date + INTERVAL '1 day')::timestamptz"
            params["ed"] = end_date

        result = await self.db.execute(
            text(f"""
                SELECT recipient_type, recipient_id,
                       COUNT(*) AS total_records,
                       SUM(split_amount_fen) AS total_amount_fen,
                       SUM(CASE WHEN status='pending'  THEN split_amount_fen ELSE 0 END) AS pending_fen,
                       SUM(CASE WHEN status='settled'  THEN split_amount_fen ELSE 0 END) AS settled_fen,
                       SUM(CASE WHEN status='cancelled' THEN split_amount_fen ELSE 0 END) AS cancelled_fen
                FROM profit_split_records
                {where}
                GROUP BY recipient_type, recipient_id
                ORDER BY total_amount_fen DESC
            """),
            params,
        )
        rows = result.fetchall()
        summary = []
        for r in rows:
            total_fen = int(r.total_amount_fen or 0)
            summary.append({
                "recipient_type": r.recipient_type,
                "recipient_id": str(r.recipient_id) if r.recipient_id else None,
                "total_records": int(r.total_records),
                "total_amount_fen": total_fen,
                "total_amount_yuan": round(total_fen / 100, 2),
                "pending_fen": int(r.pending_fen or 0),
                "settled_fen": int(r.settled_fen or 0),
                "cancelled_fen": int(r.cancelled_fen or 0),
            })
        return {
            "summary": summary,
            "grand_total_fen": sum(s["total_amount_fen"] for s in summary),
            "grand_pending_fen": sum(s["pending_fen"] for s in summary),
            "grand_settled_fen": sum(s["settled_fen"] for s in summary),
        }

    # ══════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════

    def _rule_row(self, row) -> Dict[str, Any]:
        def _json(v):
            if v is None:
                return []
            return v if isinstance(v, list) else json.loads(v)

        return {
            "rule_id": str(row.id),
            "tenant_id": self.tenant_id,
            "name": row.name,
            "recipient_type": row.recipient_type,
            "recipient_id": str(row.recipient_id) if row.recipient_id else None,
            "split_method": row.split_method,
            "percentage": float(row.percentage) if row.percentage is not None else None,
            "fixed_fen": row.fixed_fen,
            "applicable_stores": _json(row.applicable_stores),
            "applicable_channels": _json(row.applicable_channels),
            "priority": row.priority,
            "is_active": row.is_active,
            "valid_from": str(row.valid_from) if row.valid_from else None,
            "valid_to": str(row.valid_to) if row.valid_to else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _record_row(self, row) -> Dict[str, Any]:
        return {
            "record_id": str(row.id),
            "order_id": str(row.order_id),
            "store_id": str(row.store_id),
            "channel": row.channel,
            "rule_id": str(row.rule_id),
            "rule_name": getattr(row, "rule_name", None),
            "recipient_type": row.recipient_type,
            "recipient_id": str(row.recipient_id) if row.recipient_id else None,
            "gross_amount_fen": row.gross_amount_fen,
            "split_amount_fen": row.split_amount_fen,
            "split_amount_yuan": round(row.split_amount_fen / 100, 2),
            "status": row.status,
            "settled_at": row.settled_at.isoformat() if row.settled_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
