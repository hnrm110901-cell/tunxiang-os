"""储值跨店分账服务 — 规则匹配 / 分账计算 / 消费触发

核心场景：
  顾客在 A 店充值，在 B 店消费 → 需按规则将消费金额拆分给：
    - 充值店（recharge_store_ratio）：承担了资金沉淀风险
    - 消费店（consume_store_ratio）：提供了实际服务
    - 总部（hq_ratio）：运营管理费

规则匹配优先级：
  1. applicable_store_ids 包含充值店或消费店的自定义规则
  2. scope_type 匹配的规则（brand > region > custom）
  3. is_default=TRUE 的兜底规则

金额单位：分（fen），整数运算，避免浮点误差。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class NoApplicableRuleError(ValueError):
    """没有匹配的分账规则"""
    pass


class StoredValueSplitService:
    """储值跨店分账核心服务"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════════════
    # 分账规则 CRUD
    # ══════════════════════════════════════════════════════════════

    async def create_rule(self, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建分账规则"""
        await self._set_tenant()
        rule_id = uuid.uuid4()

        # 验证三方比例之和 = 1.0000
        recharge_ratio = Decimal(str(rule_data.get("recharge_store_ratio", "0.1500")))
        consume_ratio = Decimal(str(rule_data.get("consume_store_ratio", "0.7000")))
        hq_ratio = Decimal(str(rule_data.get("hq_ratio", "0.1500")))
        if recharge_ratio + consume_ratio + hq_ratio != Decimal("1.0000"):
            raise ValueError(
                f"三方比例之和必须为 1.0000，当前: "
                f"{recharge_ratio} + {consume_ratio} + {hq_ratio} = "
                f"{recharge_ratio + consume_ratio + hq_ratio}"
            )

        store_ids = rule_data.get("applicable_store_ids")
        store_ids_sql = (
            "ARRAY[" + ",".join(f"'{s}'::UUID" for s in store_ids) + "]"
            if store_ids
            else "NULL"
        )

        await self.db.execute(
            text(f"""
                INSERT INTO stored_value_split_rules
                    (id, tenant_id, rule_name,
                     recharge_store_ratio, consume_store_ratio, hq_ratio,
                     scope_type, applicable_store_ids, is_default,
                     effective_from, effective_to)
                VALUES
                    (:id, :tid, :name,
                     :r_ratio, :c_ratio, :h_ratio,
                     :scope, {store_ids_sql}, :is_default,
                     :eff_from, :eff_to)
            """),
            {
                "id": rule_id,
                "tid": self._tid,
                "name": rule_data["rule_name"],
                "r_ratio": float(recharge_ratio),
                "c_ratio": float(consume_ratio),
                "h_ratio": float(hq_ratio),
                "scope": rule_data.get("scope_type", "brand"),
                "is_default": rule_data.get("is_default", False),
                "eff_from": rule_data.get("effective_from"),
                "eff_to": rule_data.get("effective_to"),
            },
        )
        await self.db.flush()
        log.info(
            "sv_split_rule.created",
            rule_id=str(rule_id),
            tenant_id=self.tenant_id,
        )
        return await self.get_rule(str(rule_id))  # type: ignore[return-value]

    async def update_rule(
        self, rule_id: str, rule_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """更新分账规则"""
        await self._set_tenant()

        recharge_ratio = Decimal(str(rule_data.get("recharge_store_ratio", "0.1500")))
        consume_ratio = Decimal(str(rule_data.get("consume_store_ratio", "0.7000")))
        hq_ratio = Decimal(str(rule_data.get("hq_ratio", "0.1500")))
        if recharge_ratio + consume_ratio + hq_ratio != Decimal("1.0000"):
            raise ValueError(
                f"三方比例之和必须为 1.0000，当前: "
                f"{recharge_ratio + consume_ratio + hq_ratio}"
            )

        store_ids = rule_data.get("applicable_store_ids")
        store_ids_sql = (
            "ARRAY[" + ",".join(f"'{s}'::UUID" for s in store_ids) + "]"
            if store_ids
            else "NULL"
        )

        result = await self.db.execute(
            text(f"""
                UPDATE stored_value_split_rules
                SET rule_name               = :name,
                    recharge_store_ratio    = :r_ratio,
                    consume_store_ratio     = :c_ratio,
                    hq_ratio               = :h_ratio,
                    scope_type             = :scope,
                    applicable_store_ids   = {store_ids_sql},
                    is_default             = :is_default,
                    effective_from         = :eff_from,
                    effective_to           = :eff_to,
                    updated_at             = NOW()
                WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {
                "id": uuid.UUID(rule_id),
                "tid": self._tid,
                "name": rule_data["rule_name"],
                "r_ratio": float(recharge_ratio),
                "c_ratio": float(consume_ratio),
                "h_ratio": float(hq_ratio),
                "scope": rule_data.get("scope_type", "brand"),
                "is_default": rule_data.get("is_default", False),
                "eff_from": rule_data.get("effective_from"),
                "eff_to": rule_data.get("effective_to"),
            },
        )
        await self.db.flush()
        if result.rowcount == 0:
            return None
        log.info("sv_split_rule.updated", rule_id=rule_id, tenant_id=self.tenant_id)
        return await self.get_rule(rule_id)

    async def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """查询单条规则"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, rule_name, recharge_store_ratio, consume_store_ratio,
                       hq_ratio, scope_type, applicable_store_ids, is_default,
                       effective_from, effective_to, created_at, updated_at
                FROM stored_value_split_rules
                WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"id": uuid.UUID(rule_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._rule_to_dict(row) if row else None

    async def list_rules(
        self,
        scope_type: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """列出分账规则"""
        await self._set_tenant()
        sql = """
            SELECT id, rule_name, recharge_store_ratio, consume_store_ratio,
                   hq_ratio, scope_type, applicable_store_ids, is_default,
                   effective_from, effective_to, created_at, updated_at
            FROM stored_value_split_rules
            WHERE tenant_id = :tid AND is_deleted = FALSE
        """
        params: Dict[str, Any] = {"tid": self._tid}
        if scope_type:
            sql += " AND scope_type = :scope"
            params["scope"] = scope_type
        if is_default is not None:
            sql += " AND is_default = :is_default"
            params["is_default"] = is_default
        sql += " ORDER BY is_default DESC, created_at ASC"

        result = await self.db.execute(text(sql), params)
        return [self._rule_to_dict(r) for r in result.fetchall()]

    # ══════════════════════════════════════════════════════════════
    # 核心分账逻辑
    # ══════════════════════════════════════════════════════════════

    async def get_applicable_rule(
        self,
        recharge_store_id: str,
        consume_store_id: str,
    ) -> Dict[str, Any]:
        """匹配最适用的分账规则

        优先级：
          1. applicable_store_ids 包含消费店或充值店的自定义规则
          2. scope_type 匹配的非默认规则
          3. is_default=TRUE 的兜底规则
        """
        await self._set_tenant()
        today = date.today()

        # 先查包含消费店或充值店的自定义规则
        result = await self.db.execute(
            text("""
                SELECT id, rule_name, recharge_store_ratio, consume_store_ratio,
                       hq_ratio, scope_type, applicable_store_ids, is_default,
                       effective_from, effective_to, created_at, updated_at
                FROM stored_value_split_rules
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
                  AND (effective_from IS NULL OR effective_from <= :today)
                  AND (effective_to   IS NULL OR effective_to   >= :today)
                  AND (
                    :r_store = ANY(applicable_store_ids)
                    OR :c_store = ANY(applicable_store_ids)
                  )
                ORDER BY created_at ASC
                LIMIT 1
            """),
            {
                "tid": self._tid,
                "today": today,
                "r_store": uuid.UUID(recharge_store_id),
                "c_store": uuid.UUID(consume_store_id),
            },
        )
        row = result.fetchone()
        if row:
            return self._rule_to_dict(row)

        # 再查默认规则
        result = await self.db.execute(
            text("""
                SELECT id, rule_name, recharge_store_ratio, consume_store_ratio,
                       hq_ratio, scope_type, applicable_store_ids, is_default,
                       effective_from, effective_to, created_at, updated_at
                FROM stored_value_split_rules
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
                  AND is_default = TRUE
                  AND (effective_from IS NULL OR effective_from <= :today)
                  AND (effective_to   IS NULL OR effective_to   >= :today)
                ORDER BY created_at ASC
                LIMIT 1
            """),
            {"tid": self._tid, "today": today},
        )
        row = result.fetchone()
        if row:
            return self._rule_to_dict(row)

        raise NoApplicableRuleError(
            f"未找到适用的分账规则 (recharge_store={recharge_store_id}, "
            f"consume_store={consume_store_id})"
        )

    async def create_split_record(
        self,
        transaction_id: str,
        rule: Dict[str, Any],
        amount_fen: int,
        recharge_store_id: str,
        consume_store_id: str,
    ) -> Dict[str, Any]:
        """按规则比例计算分账金额，插入分账流水

        分配策略（避免尾差）：
          1. 充值店 = floor(amount * recharge_ratio)
          2. 总部   = floor(amount * hq_ratio)
          3. 消费店 = amount - 充值店 - 总部（吸收尾差）
        """
        await self._set_tenant()

        r_ratio = Decimal(str(rule["recharge_store_ratio"]))
        h_ratio = Decimal(str(rule["hq_ratio"]))

        recharge_amount = int(Decimal(amount_fen) * r_ratio)
        hq_amount = int(Decimal(amount_fen) * h_ratio)
        consume_amount = amount_fen - recharge_amount - hq_amount

        ledger_id = uuid.uuid4()
        await self.db.execute(
            text("""
                INSERT INTO stored_value_split_ledger
                    (id, tenant_id, transaction_id, rule_id,
                     recharge_store_id, consume_store_id,
                     total_amount_fen, recharge_store_amount_fen,
                     consume_store_amount_fen, hq_amount_fen,
                     settlement_status)
                VALUES
                    (:id, :tid, :txn_id, :rule_id,
                     :r_store, :c_store,
                     :total, :r_amount,
                     :c_amount, :h_amount,
                     'pending')
            """),
            {
                "id": ledger_id,
                "tid": self._tid,
                "txn_id": uuid.UUID(transaction_id),
                "rule_id": uuid.UUID(rule["rule_id"]),
                "r_store": uuid.UUID(recharge_store_id),
                "c_store": uuid.UUID(consume_store_id),
                "total": amount_fen,
                "r_amount": recharge_amount,
                "c_amount": consume_amount,
                "h_amount": hq_amount,
            },
        )
        await self.db.flush()

        log.info(
            "sv_split_record.created",
            ledger_id=str(ledger_id),
            transaction_id=transaction_id,
            total=amount_fen,
            recharge_store=recharge_amount,
            consume_store=consume_amount,
            hq=hq_amount,
            tenant_id=self.tenant_id,
        )

        return {
            "ledger_id": str(ledger_id),
            "transaction_id": transaction_id,
            "rule_id": rule["rule_id"],
            "rule_name": rule["rule_name"],
            "total_amount_fen": amount_fen,
            "recharge_store_id": recharge_store_id,
            "recharge_store_amount_fen": recharge_amount,
            "consume_store_id": consume_store_id,
            "consume_store_amount_fen": consume_amount,
            "hq_amount_fen": hq_amount,
            "settlement_status": "pending",
        }

    async def create_reversal_record(
        self,
        original_transaction_id: str,
        refund_transaction_id: str,
        refund_amount_fen: int,
    ) -> Optional[Dict[str, Any]]:
        """退款时创建冲正分账记录

        按原始分账比例反向冲正。如果原始交易无分账记录，返回 None。
        """
        await self._set_tenant()

        # 查原始分账记录
        result = await self.db.execute(
            text("""
                SELECT rule_id, recharge_store_id, consume_store_id,
                       total_amount_fen, recharge_store_amount_fen,
                       consume_store_amount_fen, hq_amount_fen
                FROM stored_value_split_ledger
                WHERE tenant_id = :tid
                  AND transaction_id = :txn_id
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"tid": self._tid, "txn_id": uuid.UUID(original_transaction_id)},
        )
        orig = result.fetchone()
        if not orig:
            return None

        # 按原始比例计算冲正金额
        if orig.total_amount_fen == 0:
            return None

        ratio = Decimal(refund_amount_fen) / Decimal(orig.total_amount_fen)
        r_reversal = int(Decimal(orig.recharge_store_amount_fen) * ratio)
        h_reversal = int(Decimal(orig.hq_amount_fen) * ratio)
        c_reversal = refund_amount_fen - r_reversal - h_reversal

        ledger_id = uuid.uuid4()
        await self.db.execute(
            text("""
                INSERT INTO stored_value_split_ledger
                    (id, tenant_id, transaction_id, rule_id,
                     recharge_store_id, consume_store_id,
                     total_amount_fen, recharge_store_amount_fen,
                     consume_store_amount_fen, hq_amount_fen,
                     settlement_status)
                VALUES
                    (:id, :tid, :txn_id, :rule_id,
                     :r_store, :c_store,
                     :total, :r_amount,
                     :c_amount, :h_amount,
                     'pending')
            """),
            {
                "id": ledger_id,
                "tid": self._tid,
                "txn_id": uuid.UUID(refund_transaction_id),
                "rule_id": orig.rule_id,
                "r_store": orig.recharge_store_id,
                "c_store": orig.consume_store_id,
                "total": -refund_amount_fen,
                "r_amount": -r_reversal,
                "c_amount": -c_reversal,
                "h_amount": -h_reversal,
            },
        )
        await self.db.flush()

        log.info(
            "sv_split_reversal.created",
            ledger_id=str(ledger_id),
            original_txn=original_transaction_id,
            refund_txn=refund_transaction_id,
            refund_amount=refund_amount_fen,
            tenant_id=self.tenant_id,
        )

        return {
            "ledger_id": str(ledger_id),
            "transaction_id": refund_transaction_id,
            "original_transaction_id": original_transaction_id,
            "total_amount_fen": -refund_amount_fen,
            "recharge_store_amount_fen": -r_reversal,
            "consume_store_amount_fen": -c_reversal,
            "hq_amount_fen": -h_reversal,
            "settlement_status": "pending",
        }

    async def trigger_split_on_consume(
        self,
        transaction_id: str,
        recharge_store_id: str,
        consume_store_id: str,
        amount_fen: int,
    ) -> Optional[Dict[str, Any]]:
        """消费时自动触发分账 — 仅跨店时生成分账记录

        同店消费不分账（资金不需要跨店流转）。
        """
        if recharge_store_id == consume_store_id:
            log.info(
                "sv_split.same_store_skip",
                transaction_id=transaction_id,
                store_id=recharge_store_id,
            )
            return None

        try:
            rule = await self.get_applicable_rule(
                recharge_store_id=recharge_store_id,
                consume_store_id=consume_store_id,
            )
        except NoApplicableRuleError:
            log.warning(
                "sv_split.no_rule",
                transaction_id=transaction_id,
                recharge_store=recharge_store_id,
                consume_store=consume_store_id,
            )
            return None

        return await self.create_split_record(
            transaction_id=transaction_id,
            rule=rule,
            amount_fen=amount_fen,
            recharge_store_id=recharge_store_id,
            consume_store_id=consume_store_id,
        )

    # ══════════════════════════════════════════════════════════════
    # 分账流水查询
    # ══════════════════════════════════════════════════════════════

    async def list_ledger(
        self,
        store_id: Optional[str] = None,
        settlement_status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """查询分账流水（支持按门店/日期/状态筛选）"""
        await self._set_tenant()
        where = "WHERE l.tenant_id = :tid AND l.is_deleted = FALSE"
        params: Dict[str, Any] = {"tid": self._tid}

        if store_id:
            where += " AND (l.recharge_store_id = :store OR l.consume_store_id = :store)"
            params["store"] = uuid.UUID(store_id)
        if settlement_status:
            where += " AND l.settlement_status = :status"
            params["status"] = settlement_status
        if start_date:
            where += " AND l.created_at >= :sd::timestamptz"
            params["sd"] = start_date
        if end_date:
            where += " AND l.created_at < (:ed::date + INTERVAL '1 day')::timestamptz"
            params["ed"] = end_date

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM stored_value_split_ledger l {where}"),
            params,
        )
        total = count_result.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await self.db.execute(
            text(f"""
                SELECT l.id, l.transaction_id, l.rule_id,
                       l.recharge_store_id, l.consume_store_id,
                       l.total_amount_fen, l.recharge_store_amount_fen,
                       l.consume_store_amount_fen, l.hq_amount_fen,
                       l.settlement_status, l.settlement_batch_id,
                       l.settled_at, l.created_at,
                       r.rule_name
                FROM stored_value_split_ledger l
                LEFT JOIN stored_value_split_rules r ON r.id = l.rule_id
                {where}
                ORDER BY l.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [self._ledger_to_dict(row) for row in result.fetchall()]
        return {"items": items, "total": total, "page": page, "size": size}

    # ══════════════════════════════════════════════════════════════
    # 看板数据
    # ══════════════════════════════════════════════════════════════

    async def get_dashboard(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分账看板 — 汇总统计"""
        await self._set_tenant()
        where = "WHERE tenant_id = :tid AND is_deleted = FALSE"
        params: Dict[str, Any] = {"tid": self._tid}

        if start_date:
            where += " AND created_at >= :sd::timestamptz"
            params["sd"] = start_date
        if end_date:
            where += " AND created_at < (:ed::date + INTERVAL '1 day')::timestamptz"
            params["ed"] = end_date

        result = await self.db.execute(
            text(f"""
                SELECT
                    COUNT(*) AS total_records,
                    COALESCE(SUM(ABS(total_amount_fen)), 0) AS total_amount_fen,
                    COALESCE(SUM(CASE WHEN total_amount_fen > 0
                        THEN recharge_store_amount_fen ELSE 0 END), 0)
                        AS total_recharge_store_fen,
                    COALESCE(SUM(CASE WHEN total_amount_fen > 0
                        THEN consume_store_amount_fen ELSE 0 END), 0)
                        AS total_consume_store_fen,
                    COALESCE(SUM(CASE WHEN total_amount_fen > 0
                        THEN hq_amount_fen ELSE 0 END), 0)
                        AS total_hq_fen,
                    COUNT(CASE WHEN settlement_status = 'pending' THEN 1 END)
                        AS pending_count,
                    COUNT(CASE WHEN settlement_status = 'settled' THEN 1 END)
                        AS settled_count,
                    COALESCE(SUM(CASE WHEN settlement_status = 'pending'
                        THEN ABS(total_amount_fen) ELSE 0 END), 0)
                        AS pending_amount_fen,
                    COALESCE(SUM(CASE WHEN settlement_status = 'settled'
                        THEN ABS(total_amount_fen) ELSE 0 END), 0)
                        AS settled_amount_fen
                FROM stored_value_split_ledger
                {where}
            """),
            params,
        )
        row = result.fetchone()

        return {
            "total_records": int(row.total_records),
            "total_amount_fen": int(row.total_amount_fen),
            "total_amount_yuan": round(int(row.total_amount_fen) / 100, 2),
            "total_recharge_store_fen": int(row.total_recharge_store_fen),
            "total_consume_store_fen": int(row.total_consume_store_fen),
            "total_hq_fen": int(row.total_hq_fen),
            "pending_count": int(row.pending_count),
            "settled_count": int(row.settled_count),
            "pending_amount_fen": int(row.pending_amount_fen),
            "settled_amount_fen": int(row.settled_amount_fen),
        }

    # ══════════════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════════════

    def _rule_to_dict(self, row) -> Dict[str, Any]:
        store_ids = row.applicable_store_ids
        if store_ids is None:
            store_ids = []
        elif not isinstance(store_ids, list):
            store_ids = list(store_ids)

        return {
            "rule_id": str(row.id),
            "rule_name": row.rule_name,
            "recharge_store_ratio": float(row.recharge_store_ratio),
            "consume_store_ratio": float(row.consume_store_ratio),
            "hq_ratio": float(row.hq_ratio),
            "scope_type": row.scope_type,
            "applicable_store_ids": [str(s) for s in store_ids],
            "is_default": row.is_default,
            "effective_from": str(row.effective_from) if row.effective_from else None,
            "effective_to": str(row.effective_to) if row.effective_to else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _ledger_to_dict(self, row) -> Dict[str, Any]:
        return {
            "ledger_id": str(row.id),
            "transaction_id": str(row.transaction_id),
            "rule_id": str(row.rule_id),
            "rule_name": getattr(row, "rule_name", None),
            "recharge_store_id": str(row.recharge_store_id),
            "consume_store_id": str(row.consume_store_id),
            "total_amount_fen": int(row.total_amount_fen),
            "recharge_store_amount_fen": int(row.recharge_store_amount_fen),
            "consume_store_amount_fen": int(row.consume_store_amount_fen),
            "hq_amount_fen": int(row.hq_amount_fen),
            "settlement_status": row.settlement_status,
            "settlement_batch_id": str(row.settlement_batch_id) if row.settlement_batch_id else None,
            "settled_at": row.settled_at.isoformat() if row.settled_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
