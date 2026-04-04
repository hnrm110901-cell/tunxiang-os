"""渠道触达引擎 API — prefix /api/v1/channels

端点（5个）:
1. POST /api/v1/channels/send                      发送消息（记录发送日志）
2. GET  /api/v1/channels/{channel}/frequency/{uid} 检查发送频率限制
3. GET  /api/v1/channels/{channel}/stats           渠道发送统计
4. POST /api/v1/channels/configure                 配置渠道参数
5. GET  /api/v1/channels/send-log                  查询发送日志

v144 表：channel_configs / message_send_logs
RLS 通过 set_config('app.tenant_id') 激活
"""
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["growth-channels"])

# 支持的渠道及默认频率配置
_DEFAULT_CHANNELS: dict[str, dict] = {
    "wecom":            {"name": "企业微信",     "max_daily": 3},
    "sms":              {"name": "短信",          "max_daily": 2},
    "miniapp":          {"name": "小程序订阅消息", "max_daily": 5},
    "app_push":         {"name": "App Push",      "max_daily": 3},
    "pos_receipt":      {"name": "POS小票二维码",  "max_daily": 999},
    "reservation_page": {"name": "预订确认页",     "max_daily": 1},
    "store_task":       {"name": "门店人工任务",   "max_daily": 1},
}

_VALID_CHANNELS = set(_DEFAULT_CHANNELS.keys())


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------

def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _is_table_missing(exc: SQLAlchemyError) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or ("relation" in msg and "exist" in msg)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    channel: str
    user_id: str                         # 外部 user_id（企微 external_userid 或手机号）
    content: str                         # 消息内容摘要
    offer_id: Optional[str] = None       # 关联优惠 ID
    campaign_id: Optional[str] = None    # 关联活动 ID
    customer_id: Optional[str] = None    # 内部 customer UUID（可选）

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        if v not in _VALID_CHANNELS:
            raise ValueError(f"channel 须为 {_VALID_CHANNELS} 之一")
        return v


class ChannelConfigRequest(BaseModel):
    channel: str
    settings: dict
    max_daily_per_user: Optional[int] = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        if v not in _VALID_CHANNELS:
            raise ValueError(f"channel 须为 {_VALID_CHANNELS} 之一")
        return v


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.post("/send")
async def send_message(
    req: SendMessageRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发送渠道消息（记录发送日志）

    核心逻辑：
    1. 检查该渠道今日已发送次数（频率控制）
    2. 若超限则返回 blocked；否则写入 message_send_logs
    3. 实际发送由 ChannelEngine 处理（外部服务集成，本接口仅记录日志）
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)

        # 获取该渠道的频率配置
        channel_info = _DEFAULT_CHANNELS.get(req.channel, {})
        max_daily = channel_info.get("max_daily", 3)

        # 查询 channel_configs 覆盖默认值
        try:
            cfg_result = await db.execute(
                text("""
                    SELECT max_daily_per_user FROM channel_configs
                    WHERE tenant_id = :tid AND channel = :channel AND is_deleted = false
                    LIMIT 1
                """),
                {"tid": tid, "channel": req.channel},
            )
            cfg = cfg_result.fetchone()
            if cfg:
                max_daily = cfg.max_daily_per_user
        except SQLAlchemyError:
            # 表不存在时使用默认值
            pass

        # 频率检查：查今日已发送数
        today = datetime.now(timezone.utc).date()
        try:
            count_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM message_send_logs
                    WHERE tenant_id = :tid
                      AND channel = :channel
                      AND external_user_id = :uid
                      AND sent_at::date = :today
                      AND status = 'sent'
                      AND is_deleted = false
                """),
                {"tid": tid, "channel": req.channel, "uid": req.user_id, "today": today},
            )
            sent_today = count_result.scalar() or 0
        except SQLAlchemyError:
            sent_today = 0

        if sent_today >= max_daily:
            return ok_response({
                "channel": req.channel,
                "status": "blocked",
                "reason": f"已达今日发送上限（{max_daily}次/天）",
                "sent_today": sent_today,
            })

        # 写入发送日志
        customer_uuid: Optional[uuid.UUID] = None
        if req.customer_id:
            try:
                customer_uuid = uuid.UUID(req.customer_id)
            except ValueError:
                pass

        offer_uuid: Optional[uuid.UUID] = None
        if req.offer_id:
            try:
                offer_uuid = uuid.UUID(req.offer_id)
            except ValueError:
                pass

        campaign_uuid: Optional[uuid.UUID] = None
        if req.campaign_id:
            try:
                campaign_uuid = uuid.UUID(req.campaign_id)
            except ValueError:
                pass

        now = datetime.now(timezone.utc)
        log_id = uuid.uuid4()

        try:
            await db.execute(
                text("""
                    INSERT INTO message_send_logs
                        (id, tenant_id, channel, customer_id, external_user_id,
                         content_summary, offer_id, campaign_id, status, sent_at, created_at)
                    VALUES
                        (:id, :tid, :channel, :customer_id, :uid,
                         :content, :offer_id, :campaign_id, 'sent', :now, :now)
                """),
                {
                    "id": log_id,
                    "tid": tid,
                    "channel": req.channel,
                    "customer_id": customer_uuid,
                    "uid": req.user_id,
                    "content": req.content[:200],
                    "offer_id": offer_uuid,
                    "campaign_id": campaign_uuid,
                    "now": now,
                },
            )
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            if _is_table_missing(exc):
                logger.warning("channel.send_log_table_not_ready", error=str(exc))
                return ok_response({
                    "log_id": str(log_id),
                    "channel": req.channel,
                    "status": "sent",
                    "_note": "TABLE_NOT_READY: 日志未持久化",
                })
            raise

        logger.info(
            "channel.message_sent",
            log_id=str(log_id),
            channel=req.channel,
            user_id=req.user_id,
            tenant_id=x_tenant_id,
        )
        return ok_response({
            "log_id": str(log_id),
            "channel": req.channel,
            "status": "sent",
            "sent_at": now.isoformat(),
            "sent_today_after": sent_today + 1,
            "daily_limit": max_daily,
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("channel.send_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "发送消息失败")


@router.get("/{channel}/frequency/{user_id}")
async def check_frequency(
    channel: str,
    user_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """检查用户渠道发送频率限制状态

    返回今日已发送次数、日限制、是否还可发送
    """
    if channel not in _VALID_CHANNELS:
        return error_response("INVALID_CHANNEL", f"channel 须为 {_VALID_CHANNELS} 之一")

    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        today = datetime.now(timezone.utc).date()

        # 获取渠道配置
        channel_info = _DEFAULT_CHANNELS.get(channel, {})
        max_daily = channel_info.get("max_daily", 3)
        try:
            cfg_result = await db.execute(
                text("""
                    SELECT max_daily_per_user, is_enabled FROM channel_configs
                    WHERE tenant_id = :tid AND channel = :channel AND is_deleted = false
                    LIMIT 1
                """),
                {"tid": tid, "channel": channel},
            )
            cfg = cfg_result.fetchone()
            if cfg:
                max_daily = cfg.max_daily_per_user
        except SQLAlchemyError:
            pass

        # 查今日发送次数
        sent_today = 0
        try:
            count_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM message_send_logs
                    WHERE tenant_id = :tid
                      AND channel = :channel
                      AND external_user_id = :uid
                      AND sent_at::date = :today
                      AND status = 'sent'
                      AND is_deleted = false
                """),
                {"tid": tid, "channel": channel, "uid": user_id, "today": today},
            )
            sent_today = count_result.scalar() or 0
        except SQLAlchemyError:
            pass

        allowed = sent_today < max_daily
        return ok_response({
            "channel": channel,
            "user_id": user_id,
            "allowed": allowed,
            "sent_today": int(sent_today),
            "daily_limit": max_daily,
            "remaining": max(0, max_daily - int(sent_today)),
            "reason": "" if allowed else f"已达今日发送上限（{max_daily}次/天）",
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        logger.error("channel.frequency_check_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "频率检查失败")


@router.get("/{channel}/stats")
async def get_channel_stats(
    channel: str,
    start: str = Query(default="", description="开始日期 YYYY-MM-DD"),
    end: str = Query(default="", description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """渠道发送统计

    返回：总发送数、成功数、失败数、拦截数、日均发送量
    """
    if channel not in _VALID_CHANNELS:
        return error_response("INVALID_CHANNEL", f"channel 须为 {_VALID_CHANNELS} 之一")

    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        today = datetime.now(timezone.utc).date()

        try:
            start_date = date.fromisoformat(start) if start else date(today.year, today.month, 1)
        except ValueError:
            return error_response("INVALID_PARAM", f"start 日期格式无效（YYYY-MM-DD）: {start}")
        try:
            end_date = date.fromisoformat(end) if end else today
        except ValueError:
            return error_response("INVALID_PARAM", f"end 日期格式无效（YYYY-MM-DD）: {end}")

        try:
            result = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'sent')    AS sent_count,
                        COUNT(*) FILTER (WHERE status = 'failed')  AS failed_count,
                        COUNT(*) FILTER (WHERE status = 'blocked') AS blocked_count,
                        COUNT(DISTINCT external_user_id) AS unique_users
                    FROM message_send_logs
                    WHERE tenant_id = :tid
                      AND channel = :channel
                      AND sent_at::date BETWEEN :start_date AND :end_date
                      AND is_deleted = false
                """),
                {"tid": tid, "channel": channel, "start_date": start_date, "end_date": end_date},
            )
            row = result.fetchone()
        except SQLAlchemyError as exc:
            if _is_table_missing(exc):
                logger.warning("channel.stats_table_not_ready", error=str(exc))
                return ok_response({
                    "channel": channel,
                    "period": {"start": str(start_date), "end": str(end_date)},
                    "stats": {"total": 0, "sent_count": 0, "failed_count": 0, "blocked_count": 0, "unique_users": 0},
                    "_note": "TABLE_NOT_READY",
                })
            raise

        days = max(1, (end_date - start_date).days + 1)
        total = int(row.total) if row else 0
        return ok_response({
            "channel": channel,
            "channel_name": _DEFAULT_CHANNELS.get(channel, {}).get("name", channel),
            "period": {"start": str(start_date), "end": str(end_date), "days": days},
            "stats": {
                "total": total,
                "sent_count": int(row.sent_count) if row else 0,
                "failed_count": int(row.failed_count) if row else 0,
                "blocked_count": int(row.blocked_count) if row else 0,
                "unique_users": int(row.unique_users) if row else 0,
                "daily_avg": round(total / days, 1),
            },
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        logger.error("channel.stats_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询渠道统计失败")


@router.post("/configure")
async def configure_channel(
    req: ChannelConfigRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """配置渠道参数（幂等：相同渠道 UPSERT）

    支持设置：日发送上限、渠道专属 API 参数（如企微 corpid / 短信签名）
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        now = datetime.now(timezone.utc)
        import json as _json

        channel_info = _DEFAULT_CHANNELS.get(req.channel, {})
        max_daily = req.max_daily_per_user or channel_info.get("max_daily", 3)

        await db.execute(
            text("""
                INSERT INTO channel_configs
                    (id, tenant_id, channel, max_daily_per_user, settings, is_enabled, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :tid, :channel, :max_daily, :settings::jsonb, true, :now, :now)
                ON CONFLICT (tenant_id, channel) DO UPDATE
                SET max_daily_per_user = EXCLUDED.max_daily_per_user,
                    settings = EXCLUDED.settings,
                    updated_at = EXCLUDED.updated_at
            """),
            {
                "tid": tid,
                "channel": req.channel,
                "max_daily": max_daily,
                "settings": _json.dumps(req.settings),
                "now": now,
            },
        )
        await db.commit()

        logger.info(
            "channel.configured",
            channel=req.channel,
            max_daily=max_daily,
            tenant_id=x_tenant_id,
        )
        return ok_response({
            "channel": req.channel,
            "max_daily_per_user": max_daily,
            "settings_updated": True,
            "updated_at": now.isoformat(),
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("channel.config_table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "渠道配置功能尚未初始化")
        logger.error("channel.configure_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "配置渠道失败")


@router.get("/send-log")
async def get_send_log(
    user_id: Optional[str] = Query(default=None, description="外部 user_id 过滤"),
    channel: Optional[str] = Query(default=None, description="渠道过滤"),
    start: str = Query(default="", description="开始日期 YYYY-MM-DD"),
    end: str = Query(default="", description="结束日期 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询消息发送日志（支持按用户/渠道/日期过滤，分页）"""
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        today = datetime.now(timezone.utc).date()

        try:
            start_date = date.fromisoformat(start) if start else date(today.year, today.month, 1)
        except ValueError:
            return error_response("INVALID_PARAM", f"start 日期格式无效: {start}")
        try:
            end_date = date.fromisoformat(end) if end else today
        except ValueError:
            return error_response("INVALID_PARAM", f"end 日期格式无效: {end}")

        where_parts = [
            "tenant_id = :tid",
            "sent_at::date BETWEEN :start_date AND :end_date",
            "is_deleted = false",
        ]
        params: dict = {
            "tid": tid,
            "start_date": start_date,
            "end_date": end_date,
            "limit": size,
            "offset": (page - 1) * size,
        }

        if user_id:
            where_parts.append("external_user_id = :uid")
            params["uid"] = user_id
        if channel:
            if channel not in _VALID_CHANNELS:
                return error_response("INVALID_CHANNEL", f"channel 须为 {_VALID_CHANNELS} 之一")
            where_parts.append("channel = :channel")
            params["channel"] = channel

        where_clause = " AND ".join(where_parts)

        try:
            count_result = await db.execute(
                text(f"SELECT COUNT(*) FROM message_send_logs WHERE {where_clause}"),
                params,
            )
            total = count_result.scalar() or 0

            result = await db.execute(
                text(f"""
                    SELECT id, channel, customer_id, external_user_id,
                           content_summary, offer_id, campaign_id,
                           status, error_reason, sent_at
                    FROM message_send_logs
                    WHERE {where_clause}
                    ORDER BY sent_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()
        except SQLAlchemyError as exc:
            if _is_table_missing(exc):
                logger.warning("channel.send_log_table_not_ready", error=str(exc))
                return ok_response({"items": [], "total": 0, "page": page, "size": size, "_note": "TABLE_NOT_READY"})
            raise

        items = [
            {
                "log_id": str(r.id),
                "channel": r.channel,
                "customer_id": str(r.customer_id) if r.customer_id else None,
                "user_id": r.external_user_id,
                "content_summary": r.content_summary,
                "offer_id": str(r.offer_id) if r.offer_id else None,
                "campaign_id": str(r.campaign_id) if r.campaign_id else None,
                "status": r.status,
                "error_reason": r.error_reason,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in rows
        ]
        return ok_response({
            "items": items,
            "total": int(total),
            "page": page,
            "size": size,
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        logger.error("channel.send_log_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询发送日志失败")
