"""证件临期/过期 alerter（PR-01B sub-PR B / PRD-01）

每日扫描 supplier_certificates，按 D-30/D-15/D-7 临期阈值 + D+0 起每天
推送给食安总监 + 采购员（企微 webhook）+ supplier_portal（D+0 起写 inbox）。

去重：cert_alert_log UNIQUE (cert_id, alert_threshold, channel)
跨 tenant：遍历 active tenants + per-tenant set_config('app.tenant_id')
推送通道：sub-PR B 内 stub return (True, None)，sub-PR C 替换真接线
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Optional, Tuple

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine

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
        _engine = create_async_engine(db_url, pool_size=5, max_overflow=10)
    return _engine


# ─── 推送通道 stub（sub-PR C 替换为真实现）──────────────────────────────────


async def _push_wecom_safety_director(
    tenant_id: str,
    cert: dict,
    threshold: str,
    webhook_url: str,
) -> Tuple[bool, Optional[str]]:
    """食安总监企微 webhook 推送 stub（sub-PR C 替换为真 HTTP 调用）。"""
    logger.info(
        "cert_alert_stub_wecom_safety_director",
        tenant_id=str(tenant_id),
        cert_id=str(cert["cert_id"]),
        threshold=threshold,
    )
    return (True, None)


async def _push_wecom_purchaser(
    tenant_id: str,
    cert: dict,
    threshold: str,
    webhook_url: str,
) -> Tuple[bool, Optional[str]]:
    """采购员企微 webhook 推送 stub（sub-PR C 替换为真 HTTP 调用）。"""
    logger.info(
        "cert_alert_stub_wecom_purchaser",
        tenant_id=str(tenant_id),
        cert_id=str(cert["cert_id"]),
        threshold=threshold,
    )
    return (True, None)


async def _push_supplier_portal(
    db: AsyncSession,
    tenant_id: str,
    cert: dict,
    threshold: str,
) -> Tuple[bool, Optional[str]]:
    """写入 supplier_portal_messages inbox 表 stub（sub-PR C 真实现 INSERT）。"""
    logger.info(
        "cert_alert_stub_supplier_portal",
        tenant_id=str(tenant_id),
        cert_id=str(cert["cert_id"]),
        threshold=threshold,
    )
    return (True, None)


# ─── 阈值判定 ─────────────────────────────────────────────────────────────────


def _classify_threshold(days_until_expiry: int) -> Optional[str]:
    """返回推送阈值标签，不在任何阈值时返回 None（不推）。

    D-30 / D-15 / D-7：临期预警（各推一次）
    D+0 / D+1 / D+2 / ...：过期每日催续证（threshold 按日区分以支持去重）
    """
    if days_until_expiry == 30:
        return "D-30"
    if days_until_expiry == 15:
        return "D-15"
    if days_until_expiry == 7:
        return "D-7"
    if days_until_expiry <= 0:
        return f"D+{-days_until_expiry}"
    return None


# ─── DB helpers ──────────────────────────────────────────────────────────────


async def _fetch_active_tenants() -> list[str]:
    """查询 tenants 表返回所有 active tenant_id 列表。"""
    engine = _get_engine()
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT id::text AS tenant_id
                FROM tenants
                WHERE is_deleted = FALSE
                ORDER BY id
                LIMIT 1000
                """
            )
        )
        return [row.tenant_id for row in rows.fetchall()]


async def _get_tenant_webhook_urls(db: AsyncSession, tenant_id: str) -> dict:
    """从 tenants.extra_data 读取企微 webhook URLs（D2 决策：2a JSON 存储）。

    返回 {"safety_director_webhook": str | None, "purchaser_webhook": str | None}
    """
    row = (
        await db.execute(
            text(
                """
                SELECT
                    extra_data->>'safety_director_webhook' AS safety_director_webhook,
                    extra_data->>'purchaser_webhook'       AS purchaser_webhook
                FROM tenants
                WHERE id = :tenant_id::uuid
                  AND is_deleted = FALSE
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
    db: AsyncSession, cert_id: str, threshold: str, channel: str
) -> bool:
    """检查 cert_alert_log 是否已有该 (cert_id, threshold, channel) 记录。

    RLS 已由调用层 _scan_one_tenant 设置（set_config app.tenant_id）。
    """
    row = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM cert_alert_log
                WHERE cert_id         = :cert_id::uuid
                  AND alert_threshold = :threshold
                  AND channel         = :channel
                LIMIT 1
                """
            ),
            {"cert_id": str(cert_id), "threshold": threshold, "channel": channel},
        )
    ).first()
    return row is not None


async def _log_alert(
    db: AsyncSession,
    tenant_id: str,
    cert_id: str,
    threshold: str,
    channel: str,
    success: bool,
    error_msg: Optional[str],
) -> None:
    """写入 cert_alert_log 推送记录（INSERT OR IGNORE on conflict）。

    UNIQUE (cert_id, alert_threshold, channel)：重复时忽略（Celery retry 安全）。
    """
    await db.execute(
        text(
            """
            INSERT INTO cert_alert_log
                (tenant_id, cert_id, alert_threshold, channel, success, error_msg)
            VALUES
                (:tenant_id::uuid, :cert_id::uuid, :threshold, :channel, :success, :error_msg)
            ON CONFLICT (cert_id, alert_threshold, channel) DO NOTHING
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

    Returns: {"evaluated": N, "sent": N}
    """
    from ..services.cert_service import list_alertable

    engine = _get_engine()
    evaluated = 0
    sent = 0

    async with engine.connect() as conn:
        # 创建 AsyncSession 包装 conn（不用 sessionmaker 避免复杂依赖）
        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
        db = _AsyncSession(bind=conn)

        # 设置 RLS 租户上下文
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 读 webhook URLs
        webhook_urls = await _get_tenant_webhook_urls(db, tenant_id)

        # 查询临期 + 过期证件
        alertable_certs = await list_alertable(db, tenant_id, today=today)

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
                    if await _already_alerted(db, cert_id, threshold, channel):
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
                            db, tenant_id, cert, threshold
                        )
                except (OSError, ValueError, RuntimeError) as exc:
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
                try:
                    await _log_alert(db, tenant_id, cert_id, threshold, channel, success, error_msg)
                    await db.flush()
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

        await conn.commit()

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
