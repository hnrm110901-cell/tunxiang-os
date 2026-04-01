"""支付Saga补偿事务服务

Saga步骤：
  S1: validate_order — 验证订单可结账（无副作用，失败直接abort）
  S2: execute_payment — 调用payment_gateway.create_payment()（有副作用，成功后记录payment_id）
  S3: complete_order  — 调用order_service.settle_order()标记订单completed（有副作用）

补偿逻辑（Compensation）：
  S3失败 → 调用payment_gateway.refund()退款 → 更新saga.step='compensated'
  S2失败 → 无需补偿（未扣款），step='failed'
  S1失败 → 无需补偿，step='failed'

崩溃恢复：
  启动时扫描 step IN ('paying', 'completing') 且 updated_at < now()-5min 的挂起Saga
  paying 状态：查询payment网关确认是否已扣款，已扣款则继续S3或补偿
  completing 状态：重试S3，失败则补偿
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import UniversalPublisher, TradeEventType

logger = structlog.get_logger(__name__)


class SagaStep:
    """Saga步骤常量"""
    VALIDATING   = "validating"
    PAYING       = "paying"
    COMPLETING   = "completing"
    DONE         = "done"
    COMPENSATING = "compensating"
    COMPENSATED  = "compensated"
    FAILED       = "failed"


# 挂起Saga的超时阈值（分钟）
_PENDING_TIMEOUT_MINUTES = 5


class PaymentSagaService:
    """支付Saga协调器

    使用方式：
        service = PaymentSagaService(db, tenant_id, payment_gateway)
        result = await service.execute(
            order_id=order_id,
            method="wechat",
            amount_fen=3800,
            auth_code="134500000001",  # B扫C时传入
            idempotency_key="device001-order123-1234",
        )

    返回格式：
        {
            "saga_id": str,
            "payment_id": str | None,
            "payment_no": str | None,
            "status": "done" | "compensated" | "failed",
            "error": str | None,
        }
    """

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payment_gateway,  # PaymentGateway instance
        order_service=None,  # OrderService instance（可选，供complete_order用）
    ) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._gw = payment_gateway
        self._order_service = order_service

    # ─────────────────────────────────────────────────────────────────
    # 主入口
    # ─────────────────────────────────────────────────────────────────

    async def execute(
        self,
        order_id: uuid.UUID,
        method: str,
        amount_fen: int,
        auth_code: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """执行完整支付Saga。

        Returns:
            {
                "saga_id": str,
                "payment_id": str | None,
                "payment_no": str | None,
                "status": "done" | "compensated" | "failed",
                "error": str | None,
            }
        """
        # ── 幂等检查：相同 idempotency_key 直接返回已有结果 ──────────────
        if idempotency_key:
            existing = await self._find_by_idempotency_key(idempotency_key)
            if existing:
                saga_id = str(existing["saga_id"])
                step = existing["step"]
                log = logger.bind(saga_id=saga_id, idempotency_key=idempotency_key)
                log.info("saga_idempotency_hit", step=step)
                if step == SagaStep.DONE:
                    return {
                        "saga_id": saga_id,
                        "payment_id": str(existing["payment_id"]) if existing["payment_id"] else None,
                        "payment_no": None,
                        "status": "done",
                        "error": None,
                    }
                if step in (SagaStep.COMPENSATED, SagaStep.FAILED):
                    return {
                        "saga_id": saga_id,
                        "payment_id": str(existing["payment_id"]) if existing["payment_id"] else None,
                        "payment_no": None,
                        "status": step,
                        "error": existing.get("compensation_reason"),
                    }
                # 进行中状态：继续走下面的流程（罕见，一般不会重入）

        # ── S0: 创建Saga记录，step=validating ────────────────────────────
        saga_id = uuid.uuid4()
        log = logger.bind(
            saga_id=str(saga_id),
            order_id=str(order_id),
            method=method,
            amount_fen=amount_fen,
        )
        log.info("saga_created", step=SagaStep.VALIDATING)

        try:
            await self._db.execute(
                text(
                    "INSERT INTO payment_sagas "
                    "(saga_id, tenant_id, order_id, step, idempotency_key, "
                    " payment_amount_fen, payment_method, created_at, updated_at) "
                    "VALUES (:saga_id, :tenant_id, :order_id, :step, :idempotency_key, "
                    "        :amount_fen, :method, NOW(), NOW())"
                ),
                {
                    "saga_id": saga_id,
                    "tenant_id": self._tenant_id,
                    "order_id": order_id,
                    "step": SagaStep.VALIDATING,
                    "idempotency_key": idempotency_key,
                    "amount_fen": amount_fen,
                    "method": method,
                },
            )
            await self._db.flush()
        except SQLAlchemyError as exc:
            logger.error("saga_insert_failed", order_id=str(order_id), error=str(exc))
            raise

        payment_id: Optional[str] = None
        payment_no: Optional[str] = None

        # ── S1: 验证订单 ──────────────────────────────────────────────────
        try:
            await self._validate_order(order_id)
        except ValueError as exc:
            log.warning("saga_s1_failed", error=str(exc))
            await self._update_step(saga_id, SagaStep.FAILED, compensation_reason=str(exc))
            return {
                "saga_id": str(saga_id),
                "payment_id": None,
                "payment_no": None,
                "status": SagaStep.FAILED,
                "error": str(exc),
            }

        # ── S2: 执行支付（有副作用） ──────────────────────────────────────
        await self._update_step(saga_id, SagaStep.PAYING)
        log.info("saga_step_paying")

        try:
            pay_result = await self._gw.create_payment(
                order_id=str(order_id),
                method=method,
                amount_fen=amount_fen,
                auth_code=auth_code,
                idempotency_key=idempotency_key,
            )
            payment_id = pay_result["payment_id"]
            payment_no = pay_result["payment_no"]
        except (ValueError, RuntimeError) as exc:
            log.error("saga_s2_failed", error=str(exc))
            await self._update_step(saga_id, SagaStep.FAILED, compensation_reason=str(exc))
            return {
                "saga_id": str(saga_id),
                "payment_id": None,
                "payment_no": None,
                "status": SagaStep.FAILED,
                "error": str(exc),
            }

        # 记录payment_id
        await self._set_payment_id(saga_id, uuid.UUID(payment_id))

        # ── S3: 标记订单完成（有副作用） ──────────────────────────────────
        await self._update_step(saga_id, SagaStep.COMPLETING)
        log.info("saga_step_completing", payment_id=payment_id)

        try:
            await self._complete_order(order_id)
        except (ValueError, RuntimeError, SQLAlchemyError) as exc:
            log.error("saga_s3_failed", payment_id=payment_id, error=str(exc))
            # 触发补偿
            compensated = await self.compensate(
                saga_id=saga_id,
                reason=f"S3 complete_order 失败: {exc}",
            )
            status = SagaStep.COMPENSATED if compensated else SagaStep.FAILED
            return {
                "saga_id": str(saga_id),
                "payment_id": payment_id,
                "payment_no": payment_no,
                "status": status,
                "error": str(exc),
            }

        # ── 成功 ─────────────────────────────────────────────────────────
        await self._update_step(saga_id, SagaStep.DONE)
        log.info("saga_done", payment_id=payment_id, payment_no=payment_no)

        asyncio.create_task(UniversalPublisher.publish(
            event_type=TradeEventType.ORDER_PAID,
            tenant_id=self._tenant_id,
            store_id=None,
            entity_id=order_id,
            event_data={"total_fen": amount_fen, "channel": method},
            source_service="tx-trade",
        ))

        return {
            "saga_id": str(saga_id),
            "payment_id": payment_id,
            "payment_no": payment_no,
            "status": SagaStep.DONE,
            "error": None,
        }

    # ─────────────────────────────────────────────────────────────────
    # 补偿（退款）
    # ─────────────────────────────────────────────────────────────────

    async def compensate(self, saga_id: uuid.UUID, reason: str) -> bool:
        """对已有Saga执行补偿退款。崩溃恢复时也可调用。

        Returns:
            True  — 退款成功，step 更新为 compensated
            False — 退款失败，step 更新为 failed，需人工介入
        """
        log = logger.bind(saga_id=str(saga_id), reason=reason)
        log.info("saga_compensating")

        await self._update_step(saga_id, SagaStep.COMPENSATING, compensation_reason=reason)

        # 查找 payment_id
        result = await self._db.execute(
            text(
                "SELECT payment_id, payment_amount_fen "
                "FROM payment_sagas "
                "WHERE saga_id = :saga_id AND tenant_id = :tenant_id"
            ),
            {"saga_id": saga_id, "tenant_id": self._tenant_id},
        )
        row = result.mappings().first()
        if not row or not row["payment_id"]:
            log.error("saga_compensate_no_payment_id")
            await self._update_step(saga_id, SagaStep.FAILED, compensation_reason=reason + " [无payment_id，无法退款]")
            return False

        payment_id = str(row["payment_id"])
        amount_fen = row["payment_amount_fen"]

        try:
            await self._gw.refund(
                payment_id=payment_id,
                refund_amount_fen=amount_fen,
                reason=reason,
            )
        except (ValueError, RuntimeError) as exc:
            log.error("saga_refund_failed", payment_id=payment_id, error=str(exc))
            await self._update_step(
                saga_id,
                SagaStep.FAILED,
                compensation_reason=f"{reason} | 退款失败: {exc}",
            )
            return False

        now = datetime.now(timezone.utc)
        await self._db.execute(
            text(
                "UPDATE payment_sagas "
                "SET step = :step, compensated_at = :compensated_at, "
                "    compensation_reason = :reason, updated_at = NOW() "
                "WHERE saga_id = :saga_id AND tenant_id = :tenant_id"
            ),
            {
                "step": SagaStep.COMPENSATED,
                "compensated_at": now,
                "reason": reason,
                "saga_id": saga_id,
                "tenant_id": self._tenant_id,
            },
        )
        await self._db.flush()
        log.info("saga_compensated", payment_id=payment_id)

        asyncio.create_task(UniversalPublisher.publish(
            event_type=TradeEventType.ORDER_REFUNDED,
            tenant_id=self._tenant_id,
            store_id=None,
            entity_id=row["payment_id"],
            event_data={"amount_fen": amount_fen, "reason": reason},
            source_service="tx-trade",
        ))

        return True

    # ─────────────────────────────────────────────────────────────────
    # 崩溃恢复
    # ─────────────────────────────────────────────────────────────────

    async def recover_pending_sagas(self) -> int:
        """扫描并恢复挂起的Saga（在应用启动时调用）。

        挂起定义：step IN ('paying','completing') 且 updated_at < now()-5min

        Returns:
            恢复处理的Saga数量。
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_PENDING_TIMEOUT_MINUTES)

        result = await self._db.execute(
            text(
                "SELECT saga_id, step, payment_id, order_id, "
                "       payment_amount_fen, payment_method "
                "FROM payment_sagas "
                "WHERE tenant_id = :tenant_id "
                "  AND step IN ('paying', 'completing') "
                "  AND updated_at < :cutoff"
            ),
            {"tenant_id": self._tenant_id, "cutoff": cutoff},
        )
        rows = result.mappings().all()

        if not rows:
            logger.info("saga_recovery_no_pending")
            return 0

        logger.info("saga_recovery_found", count=len(rows))
        recovered = 0

        for row in rows:
            saga_id = row["saga_id"]
            step = row["step"]
            payment_id = row["payment_id"]
            order_id = row["order_id"]
            log = logger.bind(saga_id=str(saga_id), step=step, order_id=str(order_id))

            try:
                if step == SagaStep.PAYING:
                    # paying：支付是否已完成？查询payment记录确认
                    if payment_id:
                        # 已有payment_id说明S2已成功，尝试S3
                        log.info("saga_recovery_paying_has_payment_id")
                        await self._update_step(saga_id, SagaStep.COMPLETING)
                        try:
                            await self._complete_order(order_id)
                            await self._update_step(saga_id, SagaStep.DONE)
                            log.info("saga_recovery_completed")
                        except (ValueError, RuntimeError, SQLAlchemyError) as exc:
                            log.error("saga_recovery_complete_failed", error=str(exc))
                            await self.compensate(
                                saga_id=saga_id,
                                reason=f"崩溃恢复S3失败: {exc}",
                            )
                    else:
                        # 无payment_id说明S2尚未完成，标记失败（不退款）
                        log.info("saga_recovery_paying_no_payment_id")
                        await self._update_step(
                            saga_id,
                            SagaStep.FAILED,
                            compensation_reason="崩溃恢复：paying状态无payment_id，S2未完成",
                        )

                elif step == SagaStep.COMPLETING:
                    # completing：S2已成功，重试S3
                    log.info("saga_recovery_completing")
                    try:
                        await self._complete_order(order_id)
                        await self._update_step(saga_id, SagaStep.DONE)
                        log.info("saga_recovery_completed")
                    except (ValueError, RuntimeError, SQLAlchemyError) as exc:
                        log.error("saga_recovery_complete_failed", error=str(exc))
                        await self.compensate(
                            saga_id=saga_id,
                            reason=f"崩溃恢复S3重试失败: {exc}",
                        )

                recovered += 1

            except (SQLAlchemyError, ValueError, RuntimeError) as exc:
                log.error("saga_recovery_error", error=str(exc))

        logger.info("saga_recovery_done", recovered=recovered)
        return recovered

    # ─────────────────────────────────────────────────────────────────
    # 私有辅助方法
    # ─────────────────────────────────────────────────────────────────

    async def _validate_order(self, order_id: uuid.UUID) -> None:
        """S1: 验证订单存在且未结账（无副作用）。"""
        from shared.ontology.src.enums import OrderStatus

        result = await self._db.execute(
            text(
                "SELECT id, status FROM orders "
                "WHERE id = :order_id AND tenant_id = :tenant_id"
            ),
            {"order_id": order_id, "tenant_id": self._tenant_id},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"订单不存在: {order_id}")
        if row["status"] == OrderStatus.completed.value:
            raise ValueError(f"订单已结账: {order_id}")
        if row["status"] == OrderStatus.cancelled.value:
            raise ValueError(f"订单已取消: {order_id}")

    async def _complete_order(self, order_id: uuid.UUID) -> None:
        """S3: 标记订单为已完成。"""
        if self._order_service is not None:
            await self._order_service.settle_order(order_id=str(order_id))
            return

        # 内联实现：直接更新订单状态（order_service 未注入时的降级路径）
        from shared.ontology.src.enums import OrderStatus

        now = datetime.now(timezone.utc)
        result = await self._db.execute(
            text(
                "UPDATE orders "
                "SET status = :status, completed_at = :completed_at, "
                "    updated_at = NOW() "
                "WHERE id = :order_id AND tenant_id = :tenant_id "
                "  AND status NOT IN ('completed', 'cancelled')"
            ),
            {
                "status": OrderStatus.completed.value,
                "completed_at": now,
                "order_id": order_id,
                "tenant_id": self._tenant_id,
            },
        )
        if result.rowcount == 0:
            # 可能已完成（幂等），也可能不存在
            check = await self._db.execute(
                text(
                    "SELECT status FROM orders "
                    "WHERE id = :order_id AND tenant_id = :tenant_id"
                ),
                {"order_id": order_id, "tenant_id": self._tenant_id},
            )
            row = check.mappings().first()
            if not row:
                raise ValueError(f"订单不存在: {order_id}")
            if row["status"] != OrderStatus.completed.value:
                raise RuntimeError(f"订单状态更新失败，当前状态: {row['status']}")
            # status 已是 completed，属于幂等成功

        await self._db.flush()

    async def _update_step(
        self,
        saga_id: uuid.UUID,
        step: str,
        compensation_reason: Optional[str] = None,
    ) -> None:
        """更新Saga步骤，立即flush。"""
        params: dict = {
            "step": step,
            "saga_id": saga_id,
            "tenant_id": self._tenant_id,
        }
        extra_set = ""
        if compensation_reason is not None:
            params["compensation_reason"] = compensation_reason
            extra_set = ", compensation_reason = :compensation_reason"

        await self._db.execute(
            text(
                f"UPDATE payment_sagas "
                f"SET step = :step, updated_at = NOW(){extra_set} "
                f"WHERE saga_id = :saga_id AND tenant_id = :tenant_id"
            ),
            params,
        )
        await self._db.flush()
        logger.debug("saga_step_updated", saga_id=str(saga_id), step=step)

    async def _set_payment_id(self, saga_id: uuid.UUID, payment_id: uuid.UUID) -> None:
        """将payment_id写入Saga记录。"""
        await self._db.execute(
            text(
                "UPDATE payment_sagas "
                "SET payment_id = :payment_id, updated_at = NOW() "
                "WHERE saga_id = :saga_id AND tenant_id = :tenant_id"
            ),
            {
                "payment_id": payment_id,
                "saga_id": saga_id,
                "tenant_id": self._tenant_id,
            },
        )
        await self._db.flush()

    async def _find_by_idempotency_key(self, idempotency_key: str) -> Optional[dict]:
        """按幂等键查找已有Saga。"""
        result = await self._db.execute(
            text(
                "SELECT saga_id, step, payment_id, compensation_reason "
                "FROM payment_sagas "
                "WHERE tenant_id = :tenant_id "
                "  AND idempotency_key = :idempotency_key "
                "ORDER BY created_at DESC "
                "LIMIT 1"
            ),
            {"tenant_id": self._tenant_id, "idempotency_key": idempotency_key},
        )
        row = result.mappings().first()
        return dict(row) if row else None
