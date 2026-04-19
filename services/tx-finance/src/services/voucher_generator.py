"""财务凭证自动生成器 — 从采购单/日营收/工资等业务数据生成 ERP 凭证并推送

核心职责：
  1. 从数据库查询业务数据（采购单/日结/工资单）
  2. 按科目映射规则生成借贷平衡的 ERPVoucher
  3. 通过对应 ERP 适配器推送（金蝶/用友，按租户配置选择）
  4. 推送失败写入本地队列，不影响主业务流程

科目映射优先级：
  租户自定义 (tenant_config) > 默认映射 (ACCOUNT_MAPPING)

金额单位：全程用分(fen)，推送 ERP 前在适配器内转换为元。
"""
from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.adapters.erp.src import (
    ERPPushResult,
    ERPType,
    ERPVoucher,
    ERPVoucherEntry,
    PushStatus,
    VoucherType,
    get_erp_adapter,
)

log = structlog.get_logger(__name__)

# ─── 默认科目映射 ─────────────────────────────────────────────────────────────
# 格式：业务场景 → {debit: {code, name}, credit: {code, name}}
# 可被租户在 tenant_config 表的 erp_account_mapping JSONB 字段覆盖

ACCOUNT_MAPPING: dict[str, dict[str, dict[str, str]]] = {
    "purchase_payment": {
        "debit":  {"code": "1403", "name": "原材料"},
        "credit": {"code": "2202", "name": "应付账款"},
    },
    "sales_revenue": {
        "debit":  {"code": "1122", "name": "应收账款"},
        "credit": {"code": "5001", "name": "主营业务收入"},
    },
    "sales_cash": {
        "debit":  {"code": "1001", "name": "库存现金"},
        "credit": {"code": "5001", "name": "主营业务收入"},
    },
    "sales_wechat": {
        "debit":  {"code": "1012.01", "name": "微信收款"},
        "credit": {"code": "5001", "name": "主营业务收入"},
    },
    "sales_alipay": {
        "debit":  {"code": "1012.02", "name": "支付宝收款"},
        "credit": {"code": "5001", "name": "主营业务收入"},
    },
    "sales_bank_card": {
        "debit":  {"code": "1002", "name": "银行存款"},
        "credit": {"code": "5001", "name": "主营业务收入"},
    },
    "waste_loss": {
        "debit":  {"code": "5602", "name": "管理费用"},
        "credit": {"code": "1403", "name": "原材料"},
    },
    "payroll": {
        "debit":  {"code": "5602", "name": "管理费用"},
        "credit": {"code": "2211", "name": "应付职工薪酬"},
    },
    "cost_transfer": {
        "debit":  {"code": "5401", "name": "主营业务成本"},
        "credit": {"code": "1403", "name": "原材料"},
    },
}

# W1.7 VoucherType (中文 ERP 约定) → financial_vouchers.voucher_type (英文 DB 约定)
_VOUCHER_TYPE_ERP_TO_DB: dict[str, str] = {
    "收": "receipt",     # RECEIPT — 收款凭证
    "付": "payment",     # PAYMENT — 付款凭证
    "记": "cost",        # MEMO    — 记账凭证 (通常成本结转)
    "转": "cost",        # TRANSFER — 转账凭证 (归到 cost, 后续 W2 可独立)
}


# 收款方式 → 科目映射
_PAY_METHOD_ACCOUNTS: dict[str, tuple[str, str]] = {
    "cash":      ("1001",    "库存现金"),
    "wechat":    ("1012.01", "微信收款"),
    "alipay":    ("1012.02", "支付宝收款"),
    "bank_card": ("1002",    "银行存款"),
    "unionpay":  ("1002",    "银行存款"),
}


class VoucherGenerator:
    """财务凭证自动生成器

    由 tx-finance 路由层实例化，传入 tenant_id 上下文。
    """

    # ─── 科目映射 ──────────────────────────────────────────────────────────

    async def _get_account_mapping(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, dict[str, dict[str, str]]]:
        """加载租户科目映射：优先读 tenant_config，缺省用全局默认"""
        try:
            result = await db.execute(
                text("""
                    SELECT config_value
                    FROM tenant_config
                    WHERE tenant_id = :tenant_id
                      AND config_key = 'erp_account_mapping'
                      AND is_deleted = FALSE
                    LIMIT 1
                """),
                {"tenant_id": tenant_id},
            )
            row = result.mappings().first()
            if row and row["config_value"]:
                tenant_mapping: dict[str, Any] = row["config_value"]
                # 合并：租户配置覆盖默认，未覆盖的场景保留默认
                merged = {**ACCOUNT_MAPPING, **tenant_mapping}
                log.debug(
                    "voucher.account_mapping.tenant",
                    tenant_id=tenant_id,
                    overrides=list(tenant_mapping.keys()),
                )
                return merged
        except Exception as exc:  # noqa: BLE001 — 兜底降级：科目配置读取失败不阻断凭证生成
            log.warning(
                "voucher.account_mapping.fallback",
                tenant_id=tenant_id,
                error=str(exc),
                exc_info=True,
            )
        return ACCOUNT_MAPPING

    def _resolve_account(
        self,
        mapping: dict[str, dict[str, dict[str, str]]],
        scene: str,
        side: str,  # "debit" | "credit"
    ) -> dict[str, str]:
        """解析科目，scene 不存在时抛出 ValueError"""
        try:
            return mapping[scene][side]
        except KeyError:
            raise ValueError(f"科目映射缺失: scene={scene!r}, side={side!r}")

    # ─── 采购凭证 ──────────────────────────────────────────────────────────

    async def generate_from_purchase_order(
        self,
        purchase_order_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> ERPVoucher:
        """采购结算单 → 应付账款凭证

        借: 原材料(1403)
        贷: 应付账款(2202)

        Raises:
            ValueError: 采购单不存在或金额为 0
        """
        log.info(
            "voucher.generate.purchase",
            purchase_order_id=purchase_order_id,
            tenant_id=tenant_id,
        )

        result = await db.execute(
            text("""
                SELECT
                    po.id,
                    po.store_id,
                    po.order_no,
                    po.total_amount_fen,
                    po.order_date,
                    po.supplier_name,
                    po.status
                FROM purchase_orders po
                WHERE po.id = :order_id::UUID
                  AND po.tenant_id = :tenant_id
                  AND po.is_deleted = FALSE
                LIMIT 1
            """),
            {"order_id": purchase_order_id, "tenant_id": tenant_id},
        )
        row = result.mappings().first()
        if row is None:
            raise ValueError(f"采购单不存在或无权限: {purchase_order_id}")

        total_fen = int(row["total_amount_fen"] or 0)
        if total_fen <= 0:
            raise ValueError(f"采购单金额为 0，不生成凭证: {purchase_order_id}")

        mapping = await self._get_account_mapping(tenant_id, db)
        debit_acc = self._resolve_account(mapping, "purchase_payment", "debit")
        credit_acc = self._resolve_account(mapping, "purchase_payment", "credit")
        order_date: date = row["order_date"]
        supplier = row["supplier_name"] or "供应商"

        voucher = ERPVoucher(
            voucher_type=VoucherType.MEMO,
            business_date=order_date,
            entries=[
                ERPVoucherEntry(
                    account_code=debit_acc["code"],
                    account_name=debit_acc["name"],
                    debit_fen=total_fen,
                    summary=f"采购入库-{supplier}-{row['order_no']}",
                ),
                ERPVoucherEntry(
                    account_code=credit_acc["code"],
                    account_name=credit_acc["name"],
                    credit_fen=total_fen,
                    summary=f"应付-{supplier}-{row['order_no']}",
                ),
            ],
            source_type="purchase_order",
            source_id=purchase_order_id,
            tenant_id=tenant_id,
            store_id=str(row["store_id"]),
            memo=f"采购单#{row['order_no']} 共{total_fen/100:.2f}元",
        )
        log.info(
            "voucher.generate.purchase.ok",
            voucher_id=voucher.voucher_id,
            total_fen=total_fen,
        )
        return voucher

    # ─── 日收入凭证 ───────────────────────────────────────────────────────

    async def generate_from_daily_revenue(
        self,
        store_id: str,
        business_date: date,
        tenant_id: str,
        db: AsyncSession,
    ) -> ERPVoucher:
        """日营业额 → 收入确认凭证（按支付方式分借方分录）

        借: 现金/微信/支付宝/银行卡（各支付方式分录）
        贷: 主营业务收入(5001) 合计

        Raises:
            ValueError: 当日无收入数据
        """
        log.info(
            "voucher.generate.daily_revenue",
            store_id=store_id,
            business_date=business_date,
            tenant_id=tenant_id,
        )

        date_str = business_date.isoformat()
        result = await db.execute(
            text("""
                SELECT
                    p.pay_method,
                    COALESCE(SUM(p.amount_fen), 0) AS amount_fen,
                    COUNT(*) AS pay_count
                FROM payments p
                JOIN orders o ON p.order_id = o.id AND o.tenant_id = p.tenant_id
                WHERE p.tenant_id = :tenant_id
                  AND o.store_id = :store_id::UUID
                  AND p.is_deleted = FALSE
                  AND o.is_deleted = FALSE
                  AND o.status IN ('completed', 'paid')
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :biz_date::DATE
                GROUP BY p.pay_method
                ORDER BY amount_fen DESC
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "biz_date": date_str},
        )
        rows = result.mappings().all()

        if not rows:
            raise ValueError(f"门店 {store_id} 在 {date_str} 无收入数据")

        mapping = await self._get_account_mapping(tenant_id, db)
        credit_acc = self._resolve_account(mapping, "sales_revenue", "credit")

        entries: list[ERPVoucherEntry] = []
        total_fen = 0

        for row in rows:
            method = row["pay_method"]
            amount = int(row["amount_fen"])
            total_fen += amount

            # 优先从全局 pay_method 映射找，其次降级到银行存款
            if method in _PAY_METHOD_ACCOUNTS:
                acc_code, acc_name = _PAY_METHOD_ACCOUNTS[method]
            else:
                acc_code, acc_name = "1002", "银行存款"

            entries.append(ERPVoucherEntry(
                account_code=acc_code,
                account_name=acc_name,
                debit_fen=amount,
                summary=f"{date_str}{acc_name}收入({row['pay_count']}笔)",
            ))

        # 贷方：主营业务收入（合计）
        entries.append(ERPVoucherEntry(
            account_code=credit_acc["code"],
            account_name=credit_acc["name"],
            credit_fen=total_fen,
            summary=f"{date_str}营业收入合计",
        ))

        voucher = ERPVoucher(
            voucher_type=VoucherType.RECEIPT,
            business_date=business_date,
            entries=entries,
            source_type="daily_revenue",
            source_id=f"{store_id}_{date_str}",
            tenant_id=tenant_id,
            store_id=store_id,
            memo=f"日收入凭证 {date_str} 合计{total_fen/100:.2f}元",
        )
        log.info(
            "voucher.generate.daily_revenue.ok",
            voucher_id=voucher.voucher_id,
            total_fen=total_fen,
            entry_count=len(entries),
        )
        return voucher

    # ─── W1.7: 持久化 + 推送端到端 ────────────────────────────────────────

    async def persist_to_db(
        self,
        erp_voucher: ERPVoucher,
        *,
        voucher_service,  # FinancialVoucherService (forward ref 避循环导入)
        session: AsyncSession,
        voucher_no: str | None = None,
        event_type: str | None = None,
        event_id: "uuid.UUID | None" = None,
    ) -> "FinancialVoucher":
        """ERPVoucher pydantic → FinancialVoucher ORM 持久化.

        把推 ERP 前的 pydantic 生成物落地到 financial_vouchers + lines.
        调用方继续拿 erp_voucher 走 push_to_erp — DB 写入是 SSOT, ERP 推送是同步.

        Args:
            erp_voucher: 由 generate_from_* 方法生成的 pydantic.
            voucher_service: FinancialVoucherService 实例 (W1.3+).
                注入 period_service 时自动走账期校验.
            voucher_no: 自定义凭证编号. None 时默认 AUTO_{erp_voucher_id[:8]}.
            event_type/event_id: 幂等键 (可选). 建议:
                daily_revenue: uuid.uuid5(NAMESPACE_URL, f"daily_revenue:{store}:{date}")
                purchase_order: uuid.uuid5(NAMESPACE_URL, f"purchase_order:{order_id}")

        Returns:
            已 flush 未 commit 的 FinancialVoucher. caller 持事务边界.
        """
        import uuid as _uuid

        # 延迟 import 避循环: service 依赖 model 依赖 generator
        from services.financial_voucher_service import (  # type: ignore
            VoucherCreateInput,
            VoucherLineInput,
        )

        payload = VoucherCreateInput(
            tenant_id=_uuid.UUID(erp_voucher.tenant_id),
            store_id=_uuid.UUID(erp_voucher.store_id) if erp_voucher.store_id else None,
            voucher_no=voucher_no or f"AUTO_{erp_voucher.voucher_id[:8]}",
            voucher_date=erp_voucher.business_date,
            voucher_type=_VOUCHER_TYPE_ERP_TO_DB[erp_voucher.voucher_type.value],
            source_type=erp_voucher.source_type,
            source_id=(
                _uuid.UUID(erp_voucher.source_id)
                if erp_voucher.source_id and self._looks_like_uuid(erp_voucher.source_id)
                else None
            ),
            event_type=event_type,
            event_id=event_id,
            lines=[
                VoucherLineInput(
                    account_code=e.account_code,
                    account_name=e.account_name,
                    debit_fen=e.debit_fen,
                    credit_fen=e.credit_fen,
                    summary=e.summary,
                )
                for e in erp_voucher.entries
            ],
        )
        return await voucher_service.create(payload, session=session)

    async def persist_and_push(
        self,
        erp_voucher: ERPVoucher,
        *,
        voucher_service,
        erp_type: str,
        session: AsyncSession,
        voucher_no: str | None = None,
        event_type: str | None = None,
        event_id: "uuid.UUID | None" = None,
    ) -> "tuple[FinancialVoucher, ERPPushResult]":
        """端到端编排: 持久化 → 推 ERP → 推成功时标记 exported.

        顺序:
          1. persist_to_db: 写 financial_vouchers + lines (SSOT).
          2. push_to_erp: 推金蝶/用友. 失败记 erp_push_log, 不回滚 DB.
          3. 推成功时: 更新 status='exported' + exported_at.

        事务边界: 调用方持 commit, service 内只 flush. 典型用法:
            async with db.begin():
                voucher, push_result = await gen.persist_and_push(...)
                # 若要求推 ERP 失败也回滚 DB, 此处 raise

        Returns:
            (FinancialVoucher ORM, ERPPushResult).
        """
        from datetime import datetime, timezone

        # 1. 持久化 DB
        financial_voucher = await self.persist_to_db(
            erp_voucher,
            voucher_service=voucher_service,
            session=session,
            voucher_no=voucher_no,
            event_type=event_type,
            event_id=event_id,
        )

        log.info(
            "voucher.persist_and_push.persisted",
            db_voucher_id=str(financial_voucher.id),
            voucher_no=financial_voucher.voucher_no,
        )

        # 2. 推 ERP (失败不回滚 DB)
        push_result = await self.push_to_erp(
            erp_voucher,
            tenant_id=erp_voucher.tenant_id,
            erp_type=erp_type,
            db=session,
        )

        # 3. 推成功 → 更新 status
        if push_result.status == PushStatus.SUCCESS:
            financial_voucher.status = "exported"
            financial_voucher.exported_at = datetime.now(timezone.utc)
            await session.flush()

        log.info(
            "voucher.persist_and_push.done",
            db_voucher_id=str(financial_voucher.id),
            push_status=push_result.status.value,
            erp_voucher_id=push_result.erp_voucher_id,
        )

        return financial_voucher, push_result

    @staticmethod
    def _looks_like_uuid(s: str) -> bool:
        """保守判 source_id 是否 UUID 格式 (否则置 None 避免 UUID() 报错)."""
        import uuid as _uuid

        try:
            _uuid.UUID(s)
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    # ─── 推送凭证 ─────────────────────────────────────────────────────────

    async def push_to_erp(
        self,
        voucher: ERPVoucher,
        tenant_id: str,
        erp_type: str,
        db: AsyncSession,
    ) -> ERPPushResult:
        """推送凭证到对应 ERP（按 tenant_id 选择适配器）

        ERP 连接失败不影响主业务流程：
          - 金蝶适配器：抛出异常，由此方法捕获并返回 FAILED 状态
          - 用友适配器：内部捕获并写本地队列，返回 QUEUED 状态

        Raises:
            ValueError: 不支持的 ERP 类型
        """
        log.info(
            "voucher.push",
            voucher_id=voucher.voucher_id,
            erp_type=erp_type,
            tenant_id=tenant_id,
        )

        import httpx  # 在此导入避免循环依赖

        adapter = get_erp_adapter(erp_type)
        try:
            result = await adapter.push_voucher(voucher)
            # 记录推送结果到 erp_push_log（异步，失败不阻断）
            await self._record_push_result(voucher, result, db)
            log.info(
                "voucher.push.done",
                voucher_id=voucher.voucher_id,
                status=result.status,
                erp_voucher_id=result.erp_voucher_id,
            )
            return result
        except httpx.HTTPError as exc:
            # 网络/HTTP 层错误（金蝶适配器会抛出）
            error_msg = f"HTTP错误: {exc}"
            log.error(
                "voucher.push.http_error",
                voucher_id=voucher.voucher_id,
                erp_type=erp_type,
                error=error_msg,
            )
            failed_result = ERPPushResult(
                voucher_id=voucher.voucher_id,
                status=PushStatus.FAILED,
                erp_type=ERPType(erp_type),
                error_message=error_msg,
            )
            await self._record_push_result(voucher, failed_result, db)
            return failed_result
        except RuntimeError as exc:
            # ERP 业务层错误（如凭证格式不符）
            error_msg = str(exc)
            log.error(
                "voucher.push.runtime_error",
                voucher_id=voucher.voucher_id,
                erp_type=erp_type,
                error=error_msg,
            )
            failed_result = ERPPushResult(
                voucher_id=voucher.voucher_id,
                status=PushStatus.FAILED,
                erp_type=ERPType(erp_type),
                error_message=error_msg,
            )
            await self._record_push_result(voucher, failed_result, db)
            return failed_result
        finally:
            await adapter.close()

    async def _record_push_result(
        self,
        voucher: ERPVoucher,
        result: ERPPushResult,
        db: AsyncSession,
    ) -> None:
        """异步记录推送结果到 erp_push_log 表（失败不阻断主流程）"""
        try:
            await db.execute(
                text("""
                    INSERT INTO erp_push_log (
                        id, tenant_id, store_id, voucher_id, erp_type,
                        status, erp_voucher_id, error_message,
                        source_type, source_id, pushed_at, created_at
                    ) VALUES (
                        gen_random_uuid(),
                        :tenant_id::UUID,
                        :store_id::UUID,
                        :voucher_id,
                        :erp_type,
                        :status,
                        :erp_voucher_id,
                        :error_message,
                        :source_type,
                        :source_id,
                        :pushed_at,
                        NOW()
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "tenant_id": voucher.tenant_id,
                    "store_id": voucher.store_id,
                    "voucher_id": voucher.voucher_id,
                    "erp_type": result.erp_type.value,
                    "status": result.status.value,
                    "erp_voucher_id": result.erp_voucher_id,
                    "error_message": result.error_message,
                    "source_type": voucher.source_type,
                    "source_id": voucher.source_id,
                    "pushed_at": result.pushed_at.isoformat(),
                },
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — 兜底：日志记录失败不阻断主业务
            log.error("voucher.record_push_result.failed", error=str(exc), exc_info=True)
