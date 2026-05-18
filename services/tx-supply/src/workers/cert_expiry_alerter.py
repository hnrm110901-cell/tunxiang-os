"""证件临期/过期 alerter（PR-01B sub-PR B / PRD-01）

每日扫描 supplier_certificates，按 D-30/D-15/D-7 临期阈值 + D+0 起每天
推送给食安总监 + 采购员（企微 webhook）+ supplier_portal（D+0 起写 inbox）。

去重：cert_alert_log UNIQUE (cert_id, alert_threshold, channel)
跨 tenant：遍历 active tenants + per-tenant set_config('app.tenant_id')
推送通道：sub-PR B 内 stub return (True, None)，sub-PR C 替换真接线
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from typing import Optional, Tuple

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine, AsyncEngine

logger = structlog.get_logger(__name__)

# ─── channel 常量 ────────────────────────────────────────────────────────────

CHANNEL_WECOM_SAFETY = "wecom_safety_director"
CHANNEL_WECOM_PURCHASER = "wecom_purchaser"
CHANNEL_SUPPLIER_PORTAL = "supplier_portal"

# ─── DB engine 懒初始化 ───────────────────────────────────────────────────────

_engine: Optional[AsyncEngine] = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/tunxiang",
        )
        _engine = create_async_engine(
            db_url,
            pool_size=int(os.getenv("CERT_ALERTER_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("CERT_ALERTER_POOL_OVERFLOW", "10")),
        )
    return _engine


# ─── 推送通道实现（sub-PR C 真接线）──────────────────────────────────────────
#
# fail-open 契约：任何异常都不向上抛，统一返回 (False, error_msg)。
# 调用方 _scan_one_tenant 拿到 (success, error_msg) 后落 cert_alert_log，下
# 一日 daily scan 失败记录会重试（_already_alerted 仅以 success=TRUE 行为准）。
#
# 安全：webhook_url 内容不入 log（避免泄漏 webhook token）。


async def _push_wecom_safety_director(
    tenant_id: str,
    cert: dict,
    threshold: str,
    webhook_url: str,
) -> Tuple[bool, Optional[str]]:
    """食安总监企微 webhook 推送：调 IMNotificationService 渲染模板 + send_wecom_bot。

    fail-open 契约：dict 读取 / 懒 import / IMNotificationService 调用全部包
    在 try 内，避免 KeyError/TypeError/ImportError 漏出 escaping fail-open。
    """
    try:
        # 懒 import 在 try 内：未来 tx-org 包不可用时不直接抛 ImportError 给调用方
        from services.tx_org.src.services.im_notification_service import IMNotificationService

        supplier_name = cert.get("supplier_name") or "(未知供应商)"
        cert_id_val = cert["cert_id"]
        cert_type = cert["cert_type"]
        cert_number = cert["cert_number"]
        expire_date = str(cert["expire_date"])
        days_until_expiry = int(cert["days_until_expiry"])

        svc = IMNotificationService()
        message = await svc.notify_cert_expiry(
            supplier_name=supplier_name,
            cert_type=cert_type,
            cert_number=cert_number,
            expire_date=expire_date,
            days_until_expiry=days_until_expiry,
            threshold=threshold,
            recipient_role="食安总监",
        )
        sent = await svc.send_wecom_bot(webhook_url, message)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError, ImportError) as exc:
        logger.warning(
            "cert_alert_wecom_safety_director_exception",
            tenant_id=str(tenant_id),
            cert_id=str(cert.get("cert_id", "")),
            threshold=threshold,
            error=str(exc),
            exc_info=True,
        )
        return (False, f"wecom_send_exception: {exc.__class__.__name__}")

    if sent:
        logger.info(
            "cert_alert_wecom_safety_director_sent",
            tenant_id=str(tenant_id),
            cert_id=str(cert_id_val),
            threshold=threshold,
        )
        return (True, None)
    logger.warning(
        "cert_alert_wecom_safety_director_failed",
        tenant_id=str(tenant_id),
        cert_id=str(cert_id_val),
        threshold=threshold,
    )
    return (False, "wecom_send_failed")


async def _push_wecom_purchaser(
    tenant_id: str,
    cert: dict,
    threshold: str,
    webhook_url: str,
) -> Tuple[bool, Optional[str]]:
    """采购员企微 webhook 推送：模板 recipient_role='采购员'，复用 send_wecom_bot 通道。

    fail-open 契约：dict 读取 / 懒 import / IMNotificationService 调用全部包
    在 try 内（与 _push_wecom_safety_director 同模式）。
    """
    try:
        from services.tx_org.src.services.im_notification_service import IMNotificationService

        supplier_name = cert.get("supplier_name") or "(未知供应商)"
        cert_id_val = cert["cert_id"]
        cert_type = cert["cert_type"]
        cert_number = cert["cert_number"]
        expire_date = str(cert["expire_date"])
        days_until_expiry = int(cert["days_until_expiry"])

        svc = IMNotificationService()
        message = await svc.notify_cert_expiry(
            supplier_name=supplier_name,
            cert_type=cert_type,
            cert_number=cert_number,
            expire_date=expire_date,
            days_until_expiry=days_until_expiry,
            threshold=threshold,
            recipient_role="采购员",
        )
        sent = await svc.send_wecom_bot(webhook_url, message)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError, ImportError) as exc:
        logger.warning(
            "cert_alert_wecom_purchaser_exception",
            tenant_id=str(tenant_id),
            cert_id=str(cert.get("cert_id", "")),
            threshold=threshold,
            error=str(exc),
            exc_info=True,
        )
        return (False, f"wecom_send_exception: {exc.__class__.__name__}")

    if sent:
        logger.info(
            "cert_alert_wecom_purchaser_sent",
            tenant_id=str(tenant_id),
            cert_id=str(cert_id_val),
            threshold=threshold,
        )
        return (True, None)
    logger.warning(
        "cert_alert_wecom_purchaser_failed",
        tenant_id=str(tenant_id),
        cert_id=str(cert_id_val),
        threshold=threshold,
    )
    return (False, "wecom_send_failed")


async def _push_supplier_portal(
    conn: AsyncConnection,
    tenant_id: str,
    cert: dict,
    threshold: str,
) -> Tuple[bool, Optional[str]]:
    """写入 supplier_portal_messages inbox 表（v424 schema：subject/body/metadata JSONB）。

    RLS：调用方 _scan_one_tenant 已 set_config('app.tenant_id') 生效，本函数不重复设置。

    P0 防御（PR #608 round-2）：INSERT 包在 conn.begin_nested() SAVEPOINT 中，
    单 cert 失败（如 RLS WITH CHECK / IntegrityError）只回滚 savepoint，
    外层 _scan_one_tenant 事务保持干净，后续 _already_alerted / _log_alert
    不会被 InFailedSqlTransaction 污染。

    fail-open 契约：dict 读取也在 try 内，避免 KeyError 漏出。
    """
    try:
        cert_id_val = cert["cert_id"]
        supplier_id_val = cert["supplier_id"]
        cert_type = cert["cert_type"]
        cert_number = cert["cert_number"]
        expire_date = cert["expire_date"]
        days_until_expiry = int(cert["days_until_expiry"])

        if threshold.startswith("D+"):
            subject = f"【已过期】{cert_type} 请立即续证"
        else:
            subject = f"【临期 {threshold}】{cert_type} 即将过期"

        body = (
            f"您的{cert_type}（编号 {cert_number}）"
            f"将于 {expire_date} 过期，距今 {days_until_expiry} 天。"
            f"请尽快上传续证文件至供应商门户。"
        )
        metadata = {
            "cert_id": str(cert_id_val),
            "cert_type": cert_type,
            "cert_number": cert_number,
            "expire_date": str(expire_date),
            "days_until_expiry": days_until_expiry,
            "threshold": threshold,
        }

        # SAVEPOINT 隔离：INSERT 失败只回滚到 savepoint，不污染外层 txn
        # #613 闭环：ON CONFLICT DO NOTHING 配 v431 partial UNIQUE 索引
        # uq_supplier_portal_cert_alert 防 _log_alert 失败-after-INSERT 次日 re-scan 重复入 inbox
        async with conn.begin_nested():
            await conn.execute(
                text(
                    """
                    INSERT INTO supplier_portal_messages
                        (tenant_id, supplier_id, message_type, subject, body, metadata)
                    VALUES
                        (:tenant_id::uuid, :supplier_id::uuid, :message_type,
                         :subject, :body, CAST(:metadata AS JSONB))
                    ON CONFLICT (
                        tenant_id, supplier_id, message_type,
                        (metadata->>'cert_id'), (metadata->>'threshold')
                    )
                    WHERE message_type = 'cert_expiry_alert'
                    DO NOTHING
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "supplier_id": str(supplier_id_val),
                    "message_type": "cert_expiry_alert",
                    "subject": subject,
                    "body": body,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                },
            )
    except SQLAlchemyError as exc:
        logger.warning(
            "cert_alert_supplier_portal_insert_failed",
            tenant_id=str(tenant_id),
            cert_id=str(cert.get("cert_id", "")),
            error=str(exc),
            exc_info=True,
        )
        return (False, f"portal_insert_failed: {exc.__class__.__name__}")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        logger.warning(
            "cert_alert_supplier_portal_payload_invalid",
            tenant_id=str(tenant_id),
            cert_id=str(cert.get("cert_id", "")),
            error=str(exc),
            exc_info=True,
        )
        return (False, f"portal_payload_invalid: {exc.__class__.__name__}")

    logger.info(
        "cert_alert_supplier_portal_inserted",
        tenant_id=str(tenant_id),
        cert_id=str(cert_id_val),
        supplier_id=str(supplier_id_val),
        threshold=threshold,
    )
    return (True, None)


# ─── 阈值判定 ─────────────────────────────────────────────────────────────────


def _classify_threshold(days_until_expiry: int) -> Optional[str]:
    """返回推送阈值标签，不在任何阈值时返回 None（不推）。

    D-30 / D-15 / D-7：临期预警（窗口模式 ±2 天容错）
      - 窗口模式防止 Celery task 当天未跑（infra down）导致阈值永久丢失
      - 依赖 _already_alerted(success=TRUE) 过滤：窗口内多天触发只推一次
    D+0 / D+1 / D+2 / ...：过期每日催续证（threshold 按日区分以支持去重）
    """
    if 28 <= days_until_expiry <= 30:
        return "D-30"
    if 13 <= days_until_expiry <= 15:
        return "D-15"
    if 5 <= days_until_expiry <= 7:
        return "D-7"
    if days_until_expiry <= 0:
        return f"D+{-days_until_expiry}"
    return None


# ─── DB helpers ──────────────────────────────────────────────────────────────


async def _fetch_active_tenants() -> list[str]:
    """查询 tenants 表返回所有 active tenant_id 列表。

    Filter 语义: `status = 'active'` 匹配 v006 建表 schema
    (id/code/name/brand_name/pos_system/pos_config/status/created_at/updated_at,
    无软删列). PR #698 §19 round-1 P1-2 反查 v006 发现原 SQL 用软删列过滤会
    运行时 ProgrammingError, 被外层 fail-open 吞 → worker 永不告警,
    supplier cert 食安合规 alert 静默失效. 见 feedback_tenants_v006_schema_no_is_deleted.
    """
    engine = _get_engine()
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT id::text AS tenant_id
                FROM tenants
                WHERE status = 'active'
                ORDER BY id
                LIMIT 1000
                """
            )
        )
        return [row.tenant_id for row in rows.fetchall()]


async def _get_tenant_webhook_urls(conn: AsyncConnection, tenant_id: str) -> dict:
    """从 tenants.systems_config 读取企微 webhook URLs（issue #708 fix B 决策）。

    Issue #708: v006 建 tenants 表无 extra_data 列；自 PR #608 (2026-05-14)
    IM 通道接线起读路径全 fail-open silent OFF。修法 B (复用 v232 systems_config
    JSONB) — 不加新 schema，不与 v232 已有 tenants 列重叠。

    JSON 路径：`systems_config->>'safety_director_webhook'` 和
    `systems_config->>'purchaser_webhook'`（顶层 keys，与 v232 skeleton 的
    pinzhi/aoqiwei_crm/aoqiwei_supply/yiding 系统配置嵌套同层；ops 端在
    tenants 管理 API 写入真值）。

    返回 {"safety_director_webhook": str | None, "purchaser_webhook": str | None}
    """
    row = (
        await conn.execute(
            text(
                """
                SELECT
                    systems_config->>'safety_director_webhook' AS safety_director_webhook,
                    systems_config->>'purchaser_webhook'       AS purchaser_webhook
                FROM tenants
                WHERE id = :tenant_id::uuid
                  AND status = 'active'
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id)},
        )
    ).mappings().first()

    if row is None:
        return {"safety_director_webhook": None, "purchaser_webhook": None}
    return dict(row)


async def _already_alerted(
    conn: AsyncConnection, cert_id: str, threshold: str, channel: str
) -> bool:
    """检查 cert_alert_log 是否已有推送成功记录（cert_id, threshold, channel, success=TRUE）。

    仅 success=TRUE 的行算"已告知"。推送失败（success=FALSE）不阻断重试，
    次日 daily scan 仍可重推。

    RLS 已由调用层 _scan_one_tenant 设置（set_config app.tenant_id）。
    """
    row = (
        await conn.execute(
            text(
                """
                SELECT 1
                FROM cert_alert_log
                WHERE cert_id         = :cert_id::uuid
                  AND alert_threshold = :threshold
                  AND channel         = :channel
                  AND success         = TRUE
                LIMIT 1
                """
            ),
            {"cert_id": str(cert_id), "threshold": threshold, "channel": channel},
        )
    ).first()
    return row is not None


async def _log_alert(
    conn: AsyncConnection,
    tenant_id: str,
    cert_id: str,
    threshold: str,
    channel: str,
    success: bool,
    error_msg: Optional[str],
) -> None:
    """写入 cert_alert_log 推送记录（UPSERT — 结果可覆盖）。

    UNIQUE (cert_id, alert_threshold, channel)：冲突时 UPDATE success + error_msg + sent_at，
    允许"成功覆盖失败"和"再次失败覆盖前次失败"，确保幂等查询 _already_alerted(success=TRUE)
    在推送成功后能正确命中。

    P0 防御（PR #608 round-2）：INSERT 包在 conn.begin_nested() SAVEPOINT 中，
    单条 INSERT 失败（NOT NULL / RLS WITH CHECK）只回滚 savepoint，外层
    _scan_one_tenant txn 保持干净；调用方仍以 SQLAlchemyError 捕获并跳过本 cert。
    """
    async with conn.begin_nested():
        await conn.execute(
            text(
                """
                INSERT INTO cert_alert_log
                    (tenant_id, cert_id, alert_threshold, channel, success, error_msg)
                VALUES
                    (:tenant_id::uuid, :cert_id::uuid, :threshold, :channel, :success, :error_msg)
                ON CONFLICT (cert_id, alert_threshold, channel)
                DO UPDATE SET
                    success   = EXCLUDED.success,
                    error_msg = EXCLUDED.error_msg,
                    sent_at   = NOW()
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "cert_id": str(cert_id),
                "threshold": threshold,
                "channel": channel,
                "success": success,
                "error_msg": error_msg,
            },
        )


# ─── 单 tenant 扫描 ───────────────────────────────────────────────────────────


async def _scan_one_tenant(tenant_id: str, today: date) -> dict:
    """单 tenant 扫描 + 推送 + cert_alert_log 落表。

    使用 conn.execute() 直接模式（与 tx-ops celery_tasks_sync.py 一致）。
    不再用 AsyncSession(bind=conn) SA 1.x 遗留写法，避免资源泄漏。

    Returns: {"evaluated": N, "sent": N}
    """
    from ..services.cert_service import list_alertable

    engine = _get_engine()
    evaluated = 0
    sent = 0

    async with engine.connect() as conn:
      # 显式外层事务：set_config('app.tenant_id', true) 是 transaction-local，
      # 必须在同一显式 txn 内完成所有 RLS-bound 操作；SAVEPOINT 由
      # _push_supplier_portal / _log_alert 内部 conn.begin_nested() 提供
      # 单 cert 隔离，避免 IntegrityError 污染外层 txn → 后续 cert 的
      # _already_alerted / _log_alert 全部失败 → 下次 daily scan 重复推送。
      async with conn.begin():
        # 设置 RLS 租户上下文（true=transaction-local，依赖外层 begin()）
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 读 webhook URLs（在显式 txn 内，set_config 生效）
        webhook_urls = await _get_tenant_webhook_urls(conn, tenant_id)

        # 查询临期 + 过期证件（list_alertable 接受 AsyncConnection — text() 层接口兼容）
        alertable_certs = await list_alertable(conn, tenant_id, today=today)

        for cert in alertable_certs:
            evaluated += 1
            cert_id = cert["cert_id"]
            days = cert["days_until_expiry"]
            threshold = _classify_threshold(days)

            if threshold is None:
                # 临期窗口内但非阈值天数（如 D-25）→ 不推
                continue

            # channel matrix（D3/D4 决策）：
            # D-30 / D-15 / D-7：食安总监 + 采购员（2 channel）
            # D+0 起每天：食安总监 + 采购员 + supplier_portal（3 channel）
            channels_to_push: list[Tuple[str, ...]] = [
                (CHANNEL_WECOM_SAFETY,),
                (CHANNEL_WECOM_PURCHASER,),
            ]
            if days <= 0:
                channels_to_push.append((CHANNEL_SUPPLIER_PORTAL,))

            for (channel,) in channels_to_push:
                # 幂等检查
                try:
                    if await _already_alerted(conn, cert_id, threshold, channel):
                        continue
                except SQLAlchemyError as exc:
                    logger.warning(
                        "cert_alerter_idempotent_check_failed",
                        cert_id=cert_id,
                        channel=channel,
                        error=str(exc),
                        exc_info=True,
                    )
                    continue

                # 推送（fail-open — 单 channel 失败不阻塞其他 channel）
                success = False
                error_msg: Optional[str] = None
                try:
                    if channel == CHANNEL_WECOM_SAFETY:
                        webhook_url = webhook_urls.get("safety_director_webhook") or ""
                        if not webhook_url:
                            logger.warning(
                                "cert_alert_no_safety_director_webhook",
                                tenant_id=str(tenant_id),
                                cert_id=cert_id,
                            )
                            continue
                        success, error_msg = await _push_wecom_safety_director(
                            tenant_id, cert, threshold, webhook_url
                        )
                    elif channel == CHANNEL_WECOM_PURCHASER:
                        webhook_url = webhook_urls.get("purchaser_webhook") or ""
                        if not webhook_url:
                            logger.warning(
                                "cert_alert_no_purchaser_webhook",
                                tenant_id=str(tenant_id),
                                cert_id=cert_id,
                            )
                            continue
                        success, error_msg = await _push_wecom_purchaser(
                            tenant_id, cert, threshold, webhook_url
                        )
                    elif channel == CHANNEL_SUPPLIER_PORTAL:
                        success, error_msg = await _push_supplier_portal(
                            conn, tenant_id, cert, threshold
                        )
                except (
                    OSError,
                    ValueError,
                    RuntimeError,
                    KeyError,
                    TypeError,
                    AttributeError,
                ) as exc:
                    success = False
                    error_msg = str(exc)
                    logger.warning(
                        "cert_alert_push_failed_fail_open",
                        tenant_id=str(tenant_id),
                        cert_id=cert_id,
                        channel=channel,
                        threshold=threshold,
                        error=str(exc),
                        exc_info=True,
                    )

                # 落 cert_alert_log（无论成功/失败都记录）
                # _log_alert 内部用 SAVEPOINT 隔离 INSERT 失败，外层 txn 不被污染
                try:
                    await _log_alert(conn, tenant_id, cert_id, threshold, channel, success, error_msg)
                except SQLAlchemyError as exc:
                    logger.warning(
                        "cert_alerter_log_write_failed",
                        cert_id=cert_id,
                        channel=channel,
                        error=str(exc),
                        exc_info=True,
                    )

                if success:
                    sent += 1

      # async with conn.begin() 自动 commit；不再需要显式 conn.commit()

    return {"evaluated": evaluated, "sent": sent}


# ─── 主入口 ───────────────────────────────────────────────────────────────────


async def run_cert_expiry_scan(today: Optional[date] = None) -> dict:
    """供 Celery beat / 手动调用入口。

    遍历所有 active tenants，对每个 tenant 扫描临期/过期证件并推送告警。

    Returns:
        {
            "tenants_scanned": N,
            "certs_evaluated": N,
            "alerts_sent": N,
            "errors": [{"tenant_id": str, "error": str}, ...],
        }
    """
    if today is None:
        today = datetime.now(timezone.utc).date()

    try:
        tenants = await _fetch_active_tenants()
    except SQLAlchemyError as exc:
        logger.error("cert_alerter_fetch_tenants_failed", error=str(exc), exc_info=True)
        return {"tenants_scanned": 0, "certs_evaluated": 0, "alerts_sent": 0, "errors": [str(exc)]}

    summary: dict = {
        "tenants_scanned": 0,
        "certs_evaluated": 0,
        "alerts_sent": 0,
        "errors": [],
    }

    for tenant_id in tenants:
        try:
            tenant_summary = await _scan_one_tenant(tenant_id, today)
            summary["tenants_scanned"] += 1
            summary["certs_evaluated"] += tenant_summary["evaluated"]
            summary["alerts_sent"] += tenant_summary["sent"]
        except (SQLAlchemyError, ValueError, RuntimeError, OSError) as exc:
            logger.error(
                "cert_alerter_tenant_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
                exc_info=True,
            )
            summary["errors"].append({"tenant_id": str(tenant_id), "error": str(exc)})

    logger.info(
        "cert_alerter_scan_complete",
        tenants_scanned=summary["tenants_scanned"],
        certs_evaluated=summary["certs_evaluated"],
        alerts_sent=summary["alerts_sent"],
        error_count=len(summary["errors"]),
    )
    return summary
