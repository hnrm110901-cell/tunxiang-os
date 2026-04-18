"""trade_audit_log — Sprint A4 交易路由审计日志写入器

对每次支付 / 退款 / 折扣 / 宴席结算 / 企业团餐 / 抖音券等敏感路由，
在装饰器完成 RBAC 拦截后调用 write_audit(...) 写入 trade_audit_logs 表。

设计约束：
  - 审计日志不应阻塞主业务流程：任何 SQLAlchemyError 捕获 rollback + log.error，
    不向上抛 HTTPException（等保/内控层已通过 RLS 与幂等保证主数据一致性）
  - 先 SELECT set_config('app.tenant_id', ...) 再 INSERT，以触发 v261 RLS 策略
  - amount_fen 单位为"分"（BIGINT），查询/取消等无金额操作传 None
  - ValueError 用于拒绝非法入参（空 action / 空 user_id）

迁移：v261_trade_audit_logs（按月分区 + RLS + 3 条覆盖索引）
"""
from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


async def write_audit(
    db,
    *,
    tenant_id: str,
    store_id: str | None,
    user_id: str,
    user_role: str,
    action: str,
    target_type: str | None,
    target_id: str | None,
    amount_fen: int | None,
    client_ip: str | None,
) -> None:
    """写入一条 trade_audit_logs 记录。

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 UUID 字符串（必填；用于 RLS）
        store_id: 门店 UUID 字符串（可空）
        user_id: 操作员 UUID 字符串（必填）
        user_role: 角色字面量（cashier/store_manager/admin 等）
        action: 动作标识（形如 payment.create / refund.apply / discount.apply）
        target_type: 目标对象类型（order/payment/banquet/voucher ...）
        target_id: 目标对象 UUID 字符串
        amount_fen: 金额（分），查询/取消无金额时传 None
        client_ip: 客户端 IP（可空；优先用 X-Forwarded-For）

    Raises:
        ValueError: action 或 user_id 为空。

    Note:
        SQLAlchemyError 被吞掉并 rollback + log.error，不向上抛，
        避免审计日志故障拖垮主业务路径。
    """
    if not action:
        raise ValueError("action is required")
    if not user_id:
        raise ValueError("user_id is required")

    try:
        # 1) 绑定 RLS tenant
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 2) 插入审计行
        await db.execute(
            text(
                """
                INSERT INTO trade_audit_logs (
                    tenant_id, store_id, user_id, user_role,
                    action, target_type, target_id,
                    amount_fen, client_ip
                ) VALUES (
                    :tenant_id, :store_id, :user_id, :user_role,
                    :action, :target_type, :target_id,
                    :amount_fen, CAST(:client_ip AS INET)
                )
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id) if store_id else None,
                "user_id": str(user_id),
                "user_role": user_role or "",
                "action": action,
                "target_type": target_type,
                "target_id": str(target_id) if target_id else None,
                "amount_fen": int(amount_fen) if amount_fen is not None else None,
                "client_ip": client_ip,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        # 审计日志故障不应阻塞主业务：rollback + log，但不向上抛
        try:
            await db.rollback()
        except SQLAlchemyError as rb_exc:
            logger.error(
                "trade_audit_log_rollback_failed",
                error=str(rb_exc),
                action=action,
                user_id=user_id,
            )
        logger.error(
            "trade_audit_log_write_failed",
            error=str(exc),
            action=action,
            user_id=user_id,
            tenant_id=str(tenant_id),
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
        )
    except Exception as exc:  # noqa: BLE001 — 最外层兜底（§XIV 例外），审计绝不阻塞业务
        # 可能原因：Mock DB / 单元测试未注入 get_db / 连接池异常等
        # 与上方 SQLAlchemyError 相同处理（不向上抛），但额外带 exc_info=True 方便追查
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.error(
            "trade_audit_log_write_unexpected_error",
            error=str(exc),
            action=action,
            user_id=user_id,
            tenant_id=str(tenant_id),
            exc_info=True,
        )
