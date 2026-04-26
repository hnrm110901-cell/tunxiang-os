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
  - v295_trade_audit_logs_deny_ext（R-补1-1 / Tier1）：扩 result/reason/severity/
    request_id/session_id/before_state/after_state 7 列 + idx_trade_audit_deny

R-补1-1（§19 独立审查发现）：
  - 历史 write_audit 只覆盖 allow 路径，cashier 被 403 拒绝时数据库无任何记录
  - 现新增 audit_deny() 专门记录拒绝路径；require_role_audited 装饰器在拒绝前调用
  - severity 值域 info/warn/error/critical（SIEM 标准 4 级），不与 result 重叠
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .audit_outbox import write_audit_to_outbox

logger = structlog.get_logger(__name__)


def _spill_to_outbox_safe(**audit_row: Any) -> None:
    """PR-3 / R-A4-2：把一条审计行送到本地 JSONL outbox（最后一道防线）。

    write_audit 的 except 分支调用本函数：PG 写入失败时，至少保证审计落本地，
    sync-engine 后续重放到 PG。本函数自身永远不抛 — outbox 模块内部已 fail-safe，
    最坏情况只 log.critical（仍比静默丢失好）。

    截断（防 outbox 文件被超长字符串撑爆）由 outbox 模块的 PIPE_BUF guard 处理：
    单行编码 > 4000 字节会被拒绝并 log.critical。
    """
    try:
        write_audit_to_outbox(audit_row)
    except Exception:  # noqa: BLE001 — outbox 失败也不能让 write_audit 抛出
        logger.critical("audit_outbox_spill_failed", exc_info=True)


# ──────────────── result / severity 枚举（v295 列） ────────────────

_VALID_RESULTS: frozenset[str] = frozenset({"allow", "deny", "mfa_required"})
_VALID_SEVERITIES: frozenset[str] = frozenset({"info", "warn", "error", "critical"})

# RFC 4122 NIL UUID — audit_deny 401 路径 tenant_id / user_id 兜底（参见 rbac.py 同名常量）。
# 与 v261 RLS 策略兼容：set_config('app.tenant_id', NIL) → INSERT tenant_id=NIL → policy 通过。
# 同时复用为 user_id 兜底：v261 user_id 是 UUID NOT NULL，原 "(unauthenticated)" 字符串
# 给 PG 会触发 cast 失败 → SQLAlchemyError → broad except 吞 → 审计永久丢失（与 da70fd0c
# 修复前 tenant_id="" 同根因）。NIL UUID 是合法 UUID，audit_deny 把语义"未认证"
# 放在 user_role 列（TEXT，无 cast 限制），user_id 列只承担"是否合法 UUID"。
_NIL_TENANT_UUID: str = "00000000-0000-0000-0000-000000000000"
_NIL_USER_UUID: str = "00000000-0000-0000-0000-000000000000"

# v295 字符串列长度限制 — 攻击者可通过 X-Request-Id / 自定义 session_id /
# 长 exc.detail 让 PG 抛 StringDataRightTruncation（同样进 broad except → 静默丢审计）。
# write_audit 在写入前主动截断到列限制 - 1（保留 1 位给 trailing marker '~'），
# 让 INSERT 永远成功，丢失的尾部字节由 reason 末尾的 '~' 或 structlog 留痕。
_REASON_MAX_LEN: int = 128
_REQUEST_ID_MAX_LEN: int = 64
_SESSION_ID_MAX_LEN: int = 64
_USER_ROLE_MAX_LEN: int = 64  # TEXT 列无硬限，但留软限避免日志查询索引膨胀


def _truncate(value: str | None, max_len: int) -> str | None:
    """裁剪字符串到列限制；溢出时尾部加 '~' 标记，便于 SIEM 识别 truncation。"""
    if value is None:
        return None
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "~"


# ──────────────── target_id 跨租户校验（A4-R2 / Tier1） ────────────────
#
# 背景（§19 独立审查 R-A4-2）：
#   长沙经理可在请求体中传入韶山店订单 UUID 作为 target_id。原 write_audit
#   不校验 target 所属租户，会把跨租户 target_id 写入长沙审计行，构成探测信道
#   （管理员查 audit 表可枚举其他租户订单是否存在）。
#
# 修复策略：
#   1. write_audit 在执行 set_config 后、INSERT 前，向 target_type 对应的
#      实体表发起 SELECT 1 LIMIT 1，依赖已绑定的 app.tenant_id RLS 自动 scope
#      到 caller 租户：
#        - 查到行 → target 在 caller 租户内，正常写入
#        - 查不到 → 不在 caller 租户（跨租户 / 已删除 / 不存在）
#        - 表/列不在或 cast 失败 → 试下一张表
#   2. 检测到"不在 caller 租户"时：
#        - target_id / amount_fen / before_state / after_state 全部置 NULL
#        - result 升级为 'deny'，severity 升级为 'critical'，
#          reason 拼上 cross_tenant_target_blocked:<target_type>
#        - 额外记一条 structlog.error（带 'critical' 级别）触发 SIEM 告警
#   3. fail-open 原则：如果 target_type 未注册（如 voucher / coupon /
#      reconcile / retry_queue 这类无 DB 实体的）→ 跳过校验。
#
# 为什么不抛 raise（审查建议）：
#   "审计不阻塞业务"是 Tier1 不变量。raise 会让 4xx/5xx 业务路径继续抛但
#   审计写入失败，反而丢证据。降级 + 高严重性 structlog 既保留行为又留痕。
#
# 为什么不用 SECURITY DEFINER：
#   RLS 自身就提供租户隔离。借力即可，无需新增 PG 函数（v295 已稳定，避免再
#   加迁移）。

# target_type → [(table, id_column, id_pg_type), ...]
# id_pg_type 用于 CAST(:id AS <type>) 防 SQL 注入；只列允许值。
_TARGET_TENANT_LOOKUPS: dict[str, list[tuple[str, str, str]]] = {
    "order": [
        ("orders", "id", "UUID"),
        ("banquet_orders", "id", "UUID"),
        ("enterprise_meal_orders", "id", "UUID"),
    ],
    "banquet": [
        ("banquet_orders", "id", "UUID"),
    ],
    "banquet_deposit": [
        ("banquet_deposits", "id", "UUID"),
    ],
    "banquet_confirmation": [
        ("banquet_confirmations", "id", "UUID"),
    ],
    "discount_rule": [
        ("discount_rules", "id", "UUID"),
    ],
    "payment": [
        ("scan_pay_transactions", "payment_id", "TEXT"),
    ],
    "refund": [
        ("refund_requests", "id", "UUID"),
    ],
    # 未注册类型（voucher / voucher_batch / coupon / reconcile / retry_queue
    # / retry_task / store）→ 跳过校验，fail-open。这些类型在现有路由中
    # target_id 多为 None 或非 DB 实体（如批次号、协调标识），无 cross-tenant
    # 探测面。新增类型若涉及 DB 实体，应在此处补登记。
}

_ALLOWED_PG_TYPES: frozenset[str] = frozenset({"UUID", "TEXT", "BIGINT"})


def _is_valid_uuid(s: str | None) -> bool:
    if not s:
        return False
    try:
        uuid.UUID(str(s))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def _target_in_caller_tenant(
    db,
    *,
    target_type: str,
    target_id: str,
) -> bool | None:
    """检查 target_id 是否在 caller 当前 RLS 绑定的租户内。

    前置条件：调用方必须已经 SELECT set_config('app.tenant_id', :tid, true)。
    RLS 策略会自动让 SELECT 只看见 caller 租户的行，所以"查到"即"同租户"。

    Returns:
        True  — target 在 caller 租户内（正常审计）
        False — 至少有一张候选表查询成功但都未命中（跨租户 / 已删除 / 不存在
                统一视为"不允许把此 target_id 落到本租户审计行")
        None  — target_type 未注册 / target_id 为空 / 所有候选表都查询失败
                （fail-open：不阻塞合法审计）
    """
    if not target_type or not target_id:
        return None
    tables = _TARGET_TENANT_LOOKUPS.get(target_type)
    if not tables:
        return None

    target_id_str = str(target_id)
    is_uuid_format = _is_valid_uuid(target_id_str)
    any_table_queried = False

    for table, id_col, id_type in tables:
        if id_type not in _ALLOWED_PG_TYPES:
            # 防御：仅允许白名单类型，避免 f-string 拼接构成的 SQL 注入面
            continue
        if id_type == "UUID" and not is_uuid_format:
            # 非 UUID 格式 id 不要喂给 UUID 列，CAST 必败 → 直接跳过
            continue
        # 表名 / 列名来自硬编码字典，非用户输入；id 通过参数化绑定
        sql = (
            f"SELECT 1 FROM {table} "  # noqa: S608 — table/col from hardcoded whitelist
            f"WHERE {id_col} = CAST(:id AS {id_type}) LIMIT 1"
        )
        try:
            result = await db.execute(text(sql), {"id": target_id_str})
            row = result.first()
        except SQLAlchemyError as exc:
            # 单表查询失败（cast 错 / 表不存在）不影响其他表
            logger.warning(
                "trade_audit_target_check_table_error",
                table=table,
                target_type=target_type,
                error=str(exc),
            )
            continue
        except Exception as exc:  # noqa: BLE001 — 防御 mock / 异常 driver
            logger.warning(
                "trade_audit_target_check_unexpected_error",
                table=table,
                target_type=target_type,
                error=str(exc),
            )
            continue
        any_table_queried = True
        if row is not None:
            return True  # 在 caller 租户内找到

    if any_table_queried:
        # 至少一张表 SELECT 成功但没找到 → 不在 caller 租户
        return False
    return None  # 全部表 SELECT 都失败 → fail-open


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
    # ── v295 / R-补1-1 扩字段（全部可选，向后兼容） ─────────────────
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
        result: v295 — allow / deny / mfa_required（装饰器分支产物）
        reason: v295 — 人类可读拒绝/通过原因（ROLE_FORBIDDEN / over_threshold 等）
        request_id: v295 — 链路追踪 ID
        severity: v295 — info / warn / error / critical（SIEM 标准 4 级）
        session_id: v295 — 前端 session ID
        before_state: v295 — 变更前快照（JSONB）
        after_state: v295 — 变更后快照（JSONB）

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

        # 1.5) A4-R2 / Tier1：跨租户 target_id 校验
        # 借助已绑定的 app.tenant_id RLS：SELECT 只能看见 caller 租户的行。
        # 查不到 → 不在 caller 租户 → 必须 sanitize 防止 target_id 探测信道。
        if target_type and target_id:
            ownership = await _target_in_caller_tenant(
                db, target_type=target_type, target_id=str(target_id),
            )
            if ownership is False:
                # 触发 SIEM critical 告警 + sanitize 落审计行
                logger.error(
                    "trade_audit_cross_tenant_target_blocked",
                    tenant_id=str(tenant_id),
                    user_id=user_id,
                    user_role=user_role,
                    action=action,
                    target_type=target_type,
                    target_id_blocked=str(target_id),  # 仅 log，不落 DB
                    severity="critical",
                )
                # 清空 target 相关字段（防探测）
                target_id = None
                amount_fen = None
                before_state = None
                after_state = None
                # 只升级 allow 路径；deny / mfa_required 保留原 result，仅追加 reason
                if result not in {"deny", "mfa_required"}:
                    result = "deny"
                severity = "critical"
                _block_tag = f"cross_tenant_target_blocked:{target_type}"
                if reason and _block_tag not in reason:
                    reason = f"{reason} | {_block_tag}"
                elif not reason:
                    reason = _block_tag

        # 1.7) 字符串列长度防御 — 见 _truncate 注释。攻击者可控的 X-Request-Id /
        # 长 exc.detail / 拼接后的 reason 都可能溢出 PG VARCHAR → StringDataRightTruncation
        # → broad except → 静默丢审计。在 INSERT 前主动截断让写入永远成功。
        safe_reason = _truncate(reason, _REASON_MAX_LEN)
        safe_request_id = _truncate(request_id, _REQUEST_ID_MAX_LEN)
        safe_session_id = _truncate(session_id, _SESSION_ID_MAX_LEN)
        safe_user_role = _truncate(user_role or "", _USER_ROLE_MAX_LEN)

        # 2) 插入审计行（v295 扩列在缺失时由 PG 自动填 NULL，不影响旧 schema）
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
                "user_role": safe_user_role,
                "action": action,
                "target_type": target_type,
                "target_id": str(target_id) if target_id else None,
                "amount_fen": int(amount_fen) if amount_fen is not None else None,
                "client_ip": client_ip,
                "result": result,
                "reason": safe_reason,
                "request_id": safe_request_id,
                "severity": severity,
                "session_id": safe_session_id,
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
        # PR-3 / R-A4-2：PG 写入失败 → 落本地 JSONL outbox（sync-engine 后续重放）
        # 不让 broad except 静默丢审计；本地落盘是最后一道防线
        _spill_to_outbox_safe(
            tenant_id=tenant_id, store_id=store_id, user_id=user_id,
            user_role=user_role, action=action,
            target_type=target_type, target_id=target_id,
            amount_fen=amount_fen, client_ip=client_ip,
            result=result, reason=reason, request_id=request_id,
            severity=severity, session_id=session_id,
            before_state=before_state, after_state=after_state,
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
        # PR-3 / R-A4-2：连接池 / mock 异常 → 也走 outbox 兜底
        _spill_to_outbox_safe(
            tenant_id=tenant_id, store_id=store_id, user_id=user_id,
            user_role=user_role, action=action,
            target_type=target_type, target_id=target_id,
            amount_fen=amount_fen, client_ip=client_ip,
            result=result, reason=reason, request_id=request_id,
            severity=severity, session_id=session_id,
            before_state=before_state, after_state=after_state,
        )
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
    # 入参兜底（401 AUTH_MISSING / 未认证路径）：
    #   user_id 列是 PG UUID NOT NULL → 字符串如 "(unauthenticated)" cast 失败 →
    #     SQLAlchemyError → broad except → 静默丢审计（与 da70fd0c 修复前 tenant_id
    #     同根因，但当时只兜底了 tenant_id 这一列；此处补上）。
    #   语义"未认证"放在 user_role 列（TEXT 列无 cast 限制），user_id 用 NIL UUID。
    #   tenant_id 同样兜底（防御 wrapper 漏 resolve / 直接调用绕过 wrapper）。
    safe_user_id = user_id or _NIL_USER_UUID
    safe_user_role = user_role or "(unauthenticated)"
    safe_tenant_id = tenant_id or _NIL_TENANT_UUID

    await write_audit(
        db,
        tenant_id=safe_tenant_id,
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
