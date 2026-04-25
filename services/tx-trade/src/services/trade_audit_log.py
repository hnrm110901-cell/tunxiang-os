"""trade_audit_log — Sprint A4 交易路由审计日志写入器

对每次支付 / 退款 / 折扣 / 宴席结算 / 企业团餐 / 抖音券等敏感路由，
在装饰器完成 RBAC 拦截后调用 write_audit(...) 写入 trade_audit_logs 表。

设计约束：
  - 审计日志不应阻塞主业务流程：任何 SQLAlchemyError 捕获 rollback + log.error，
    不向上抛 HTTPException（等保/内控层已通过 RLS 与幂等保证主数据一致性）
  - 先 SELECT set_config('app.tenant_id', ...) 再 INSERT，以触发 v261 RLS 策略
  - amount_fen 单位为"分"（BIGINT），查询/取消等无金额操作传 None
  - ValueError 用于拒绝非法入参（空 action / 空 user_id）

迁移：
  - v261_trade_audit_logs（按月分区 + RLS + 3 条覆盖索引）
  - v290_trade_audit_logs_deny_ext（R-补1-1 / Tier1）：扩 result/reason/severity/
    request_id/session_id/before_state/after_state 7 列 + idx_trade_audit_deny

R-补1-1（§19 独立审查发现）：
  - 历史 write_audit 只覆盖 allow 路径，cashier 被 403 拒绝时数据库无任何记录
  - 现新增 audit_deny() 专门记录拒绝路径；require_role_audited 装饰器在拒绝前调用
  - severity 值域 info/warn/error/critical（SIEM 标准 4 级），不与 result 重叠
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


# ──────────────── result / severity 枚举（v290 列） ────────────────

_VALID_RESULTS: frozenset[str] = frozenset({"allow", "deny", "mfa_required"})
_VALID_SEVERITIES: frozenset[str] = frozenset({"info", "warn", "error", "critical"})


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
    # ── v290 / R-补1-1 扩字段（全部可选，向后兼容） ─────────────────
    result: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    severity: str | None = None,
    session_id: str | None = None,
    before_state: Mapping[str, Any] | None = None,
    after_state: Mapping[str, Any] | None = None,
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
        result: v290 — allow / deny / mfa_required（装饰器分支产物）
        reason: v290 — 人类可读拒绝/通过原因（ROLE_FORBIDDEN / over_threshold 等）
        request_id: v290 — 链路追踪 ID
        severity: v290 — info / warn / error / critical（SIEM 标准 4 级）
        session_id: v290 — 前端 session ID
        before_state: v290 — 变更前快照（JSONB）
        after_state: v290 — 变更后快照（JSONB）

    Raises:
        ValueError: action 或 user_id 为空；result / severity 不在白名单。

    Note:
        SQLAlchemyError 被吞掉并 rollback + log.error，不向上抛，
        避免审计日志故障拖垮主业务路径。
    """
    if not action:
        raise ValueError("action is required")
    if not user_id:
        raise ValueError("user_id is required")
    if result is not None and result not in _VALID_RESULTS:
        raise ValueError(f"result must be one of {sorted(_VALID_RESULTS)}; got {result!r}")
    if severity is not None and severity not in _VALID_SEVERITIES:
        raise ValueError(
            f"severity must be one of {sorted(_VALID_SEVERITIES)}; got {severity!r}"
        )

    try:
        # 1) 绑定 RLS tenant
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 2) 插入审计行（v290 扩列在缺失时由 PG 自动填 NULL，不影响旧 schema）
        await db.execute(
            text(
                """
                INSERT INTO trade_audit_logs (
                    tenant_id, store_id, user_id, user_role,
                    action, target_type, target_id,
                    amount_fen, client_ip,
                    result, reason, request_id, severity, session_id,
                    before_state, after_state
                ) VALUES (
                    :tenant_id, :store_id, :user_id, :user_role,
                    :action, :target_type, :target_id,
                    :amount_fen, CAST(:client_ip AS INET),
                    :result, :reason, :request_id, :severity, :session_id,
                    CAST(:before_state AS JSONB), CAST(:after_state AS JSONB)
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
                "result": result,
                "reason": reason,
                "request_id": request_id,
                "severity": severity,
                "session_id": session_id,
                "before_state": json.dumps(dict(before_state)) if before_state else None,
                "after_state": json.dumps(dict(after_state)) if after_state else None,
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


# ──────────────────────────────────────────────────────────────────────────
#  audit_deny — Sprint A4 R-补1-1 / Tier1
#  专用于 require_role / require_mfa 抛 HTTPException 拦截路径的审计写入。
#  与 require_role_audited / require_mfa_audited 装饰器配套使用。
# ──────────────────────────────────────────────────────────────────────────


async def audit_deny(
    db,
    *,
    tenant_id: str,
    store_id: str | None,
    user_id: str,
    user_role: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    amount_fen: int | None = None,
    client_ip: str | None = None,
    reason: str,
    severity: str = "warn",
    request_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """记录一次 RBAC 拒绝事件（result='deny'）。

    与 write_audit 共用底层写入路径，强制 result='deny' + severity='warn'/'error'，
    保证 idx_trade_audit_deny 部分索引命中。

    Args:
        reason: 拒绝原因（ROLE_FORBIDDEN / MFA_REQUIRED / cross_tenant_blocked /
                over_threshold_without_mfa 等机器可读 token）
        severity: 默认 warn；跨租户、超阈值无 MFA 等高敏感场景应传 error/critical
        其他参数语义同 write_audit。

    设计：
      - 与 write_audit 一样吞掉 SQLAlchemyError，绝不阻塞 HTTPException 抛出
      - 调用方应在装饰器层 *await* 本函数（非 create_task），否则 deny 响应可能
        在审计写入之前发出 → 短暂时间窗内审计缺失。50ms 同步代价对 4xx 响应
        UX 无影响（用户已被拒）。
    """
    # 入参兜底：user_id 缺失时仍要写一条（特别是 401 AUTH_MISSING 路径）
    safe_user_id = user_id or "(unauthenticated)"
    safe_user_role = user_role or "(unauthenticated)"

    await write_audit(
        db,
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=safe_user_id,
        user_role=safe_user_role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        amount_fen=amount_fen,
        client_ip=client_ip,
        result="deny",
        reason=reason,
        request_id=request_id,
        severity=severity,
        session_id=session_id,
    )
