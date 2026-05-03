"""渠道活码服务

WecomChannelCodeService 负责：
- create_channel_code   — 创建渠道活码
- get_channel_codes     — 查询渠道活码列表
- get_channel_stats     — 渠道扫码统计
- handle_scan           — 处理扫码事件（自动打标签 + 自动回复 + 自动拉群）

支持双模式运行：
- DB 模式（传入 db session）：数据持久化到 PostgreSQL
- 内存模式（db=None）：数据存储在内存中（向后兼容）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from models.wecom_channel_code import WecomChannelCode

logger = structlog.get_logger(__name__)


# ─── ORM 模型（内联定义，避免触发 models/__init__.py 的 shared 模块导入） ────


class _OrmBase(DeclarativeBase):
    """本地 ORM 基类"""


class WecomChannelCodeOrm(_OrmBase):
    """企微渠道活码（映射 v384 迁移）"""

    __tablename__ = "wecom_channel_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    merchant_code: Mapped[str] = mapped_column(String(50), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(200), nullable=False)
    qrcode_url: Mapped[str] = mapped_column(Text, nullable=False)
    auto_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    auto_reply: Mapped[str] = mapped_column(Text, nullable=False, default="")
    group_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    scan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WecomScanRecordOrm(_OrmBase):
    """扫码记录（映射 v388 迁移）"""

    __tablename__ = "wecom_scan_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    external_userid: Mapped[str] = mapped_column(String(128), nullable=False)
    tagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    invited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ─── 服务类 ─────────────────────────────────────────────────────────────────


class WecomChannelCodeService:
    """渠道活码服务（双模式：DB 持久化 + 内存回退）"""

    # ── 内存存储（db=None 时使用） ──────────────────────────────

    _channel_codes: dict[str, WecomChannelCode] = {}
    _scan_records: dict[str, list[dict[str, Any]]] = {}

    # ── 企微 SDK 接口地址 ────────────────────────────────────────

    GATEWAY_URL: str = "http://gateway:8000"

    # ── 创建渠道活码 ─────────────────────────────────────────────

    async def create_channel_code(
        self,
        merchant_code: str,
        channel_name: str,
        qrcode_url: str,
        auto_tags: Optional[list[str]] = None,
        auto_reply: str = "",
        group_id: Optional[str] = None,
        tenant_id: str = "",
        db: Optional[AsyncSession] = None,
    ) -> WecomChannelCode:
        """创建渠道活码

        Args:
            merchant_code: 商户编码
            channel_name:  渠道名称
            qrcode_url:    企微联系二维码 URL
            auto_tags:     自动打标签列表
            auto_reply:    自动回复文案
            group_id:      自动拉群 ID
            tenant_id:     租户 ID（DB 模式必填）
            db:            数据库 session（None 则使用内存存储）

        Returns:
            WecomChannelCode 实例
        """
        log = logger.bind(merchant_code=merchant_code, channel_name=channel_name)

        code = WecomChannelCode(
            merchant_code=merchant_code,
            channel_name=channel_name,
            qrcode_url=qrcode_url,
            auto_tags=auto_tags or [],
            auto_reply=auto_reply,
            group_id=group_id,
        )

        if db is not None:
            # DB 模式
            try:
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )
                orm = WecomChannelCodeOrm(
                    id=uuid.UUID(code.id),
                    tenant_id=uuid.UUID(tenant_id),
                    merchant_code=code.merchant_code,
                    channel_name=code.channel_name,
                    qrcode_url=code.qrcode_url,
                    auto_tags=code.auto_tags,
                    auto_reply=code.auto_reply,
                    group_id=code.group_id,
                    scan_count=0,
                    is_active=True,
                )
                db.add(orm)
                await db.commit()
                await db.refresh(orm)
                log.info("wecom_channel_code_db_created", channel_id=code.id)
            except SQLAlchemyError as e:
                await db.rollback()
                log.error("wecom_channel_code_db_create_error", error=str(e), exc_info=True)
                raise
        else:
            # 内存模式（向后兼容）
            self._channel_codes[code.id] = code
            self._scan_records[code.id] = []
            log.info("wecom_channel_code_mem_created", channel_id=code.id)

        return code

    # ── 查询渠道活码列表 ─────────────────────────────────────────

    async def get_channel_codes(
        self,
        merchant_code: Optional[str] = None,
        page: int = 1,
        size: int = 20,
        tenant_id: str = "",
        db: Optional[AsyncSession] = None,
    ) -> dict[str, Any]:
        """查询渠道活码列表（分页，可按商户编码筛选）

        Args:
            merchant_code: 商户编码（可选，用于筛选）
            page:          页码（从 1 开始）
            size:          每页数量
            tenant_id:     租户 ID（DB 模式必填）
            db:            数据库 session（None 则使用内存存储）

        Returns:
            {"items": [...], "total": int, "page": int, "size": int}
        """
        if db is not None:
            # DB 模式
            try:
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )

                query = select(WecomChannelCodeOrm)
                count_query = select(func.count(WecomChannelCodeOrm.id))

                if merchant_code:
                    query = query.where(WecomChannelCodeOrm.merchant_code == merchant_code)
                    count_query = count_query.where(
                        WecomChannelCodeOrm.merchant_code == merchant_code
                    )

                query = query.order_by(WecomChannelCodeOrm.created_at.desc())
                query = query.offset((page - 1) * size).limit(size)

                total_result = await db.execute(count_query)
                total = total_result.scalar() or 0

                result = await db.execute(query)
                rows = result.scalars().all()

                items = [self._orm_to_dict(r) for r in rows]

                logger.info(
                    "wecom_channel_codes_db_listed",
                    merchant_code=merchant_code,
                    total=total,
                    page=page,
                )
                return {"items": items, "total": total, "page": page, "size": size}
            except SQLAlchemyError as e:
                logger.error("wecom_channel_codes_db_list_error", error=str(e), exc_info=True)
                return {"items": [], "total": 0, "page": page, "size": size}

        # 内存模式（向后兼容）
        codes = list(self._channel_codes.values())
        if merchant_code:
            codes = [c for c in codes if c.merchant_code == merchant_code]

        codes.sort(key=lambda c: c.created_at, reverse=True)

        total = len(codes)
        start = (page - 1) * size
        end = start + size
        page_items = codes[start:end]

        items = [c.to_dict() for c in page_items]

        logger.info(
            "wecom_channel_codes_mem_listed",
            merchant_code=merchant_code,
            total=total,
            page=page,
        )
        return {"items": items, "total": total, "page": page, "size": size}

    # ── 获取渠道活码详情 ─────────────────────────────────────────

    async def get_channel_code(
        self,
        channel_id: str,
        tenant_id: str = "",
        db: Optional[AsyncSession] = None,
    ) -> Optional[WecomChannelCode]:
        """根据 ID 获取渠道活码配置"""
        if db is not None:
            try:
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )
                result = await db.execute(
                    select(WecomChannelCodeOrm).where(
                        WecomChannelCodeOrm.id == uuid.UUID(channel_id)
                    )
                )
                orm = result.scalar_one_or_none()
                if orm is None:
                    logger.warning("wecom_channel_code_db_not_found", channel_id=channel_id)
                    return None
                return self._orm_to_pydantic(orm)
            except SQLAlchemyError as e:
                logger.error("wecom_channel_code_db_get_error", error=str(e), exc_info=True)
                return None

        code = self._channel_codes.get(channel_id)
        if code is None:
            logger.warning("wecom_channel_code_mem_not_found", channel_id=channel_id)
            return None
        return code

    # ── 渠道扫码统计 ─────────────────────────────────────────────

    async def get_channel_stats(
        self,
        channel_id: str,
        tenant_id: str = "",
        db: Optional[AsyncSession] = None,
    ) -> dict[str, Any]:
        """渠道扫码统计

        Args:
            channel_id: 渠道活码 ID
            tenant_id:  租户 ID（DB 模式必填）
            db:         数据库 session（None 则使用内存存储）

        Returns:
            {channel_id, channel_name, total_scans, unique_users, recent_scans}
        """
        log = logger.bind(channel_id=channel_id)

        if db is not None:
            try:
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )

                code_result = await db.execute(
                    select(WecomChannelCodeOrm).where(
                        WecomChannelCodeOrm.id == uuid.UUID(channel_id)
                    )
                )
                orm = code_result.scalar_one_or_none()
                if orm is None:
                    log.warning("wecom_channel_code_stats_not_found")
                    return {"channel_id": channel_id, "error": "channel code not found"}

                stats_result = await db.execute(
                    select(
                        func.count(WecomScanRecordOrm.id),
                        func.count(func.distinct(WecomScanRecordOrm.external_userid)),
                    ).where(WecomScanRecordOrm.channel_id == uuid.UUID(channel_id))
                )
                total_scans, unique_users = stats_result.one()

                recent_result = await db.execute(
                    select(WecomScanRecordOrm)
                    .where(WecomScanRecordOrm.channel_id == uuid.UUID(channel_id))
                    .order_by(WecomScanRecordOrm.created_at.desc())
                    .limit(20)
                )
                recent_rows = recent_result.scalars().all()

                recent_scans = [
                    {
                        "external_userid": r.external_userid,
                        "scanned_at": r.created_at.isoformat() if r.created_at else "",
                        "actions": {
                            "tagged": r.tagged,
                            "replied": r.replied,
                            "invited": r.invited,
                        },
                    }
                    for r in recent_rows
                ]

                log.info(
                    "wecom_channel_code_db_stats",
                    total_scans=total_scans,
                    unique_users=unique_users,
                )
                return {
                    "channel_id": channel_id,
                    "channel_name": orm.channel_name,
                    "total_scans": total_scans,
                    "unique_users": unique_users,
                    "recent_scans": recent_scans,
                }
            except SQLAlchemyError as e:
                log.error("wecom_channel_code_db_stats_error", error=str(e), exc_info=True)
                return {"channel_id": channel_id, "error": "database error"}

        # 内存模式
        code = self._channel_codes.get(channel_id)
        if code is None:
            log.warning("wecom_channel_code_mem_stats_not_found")
            return {"channel_id": channel_id, "error": "channel code not found"}

        records = self._scan_records.get(channel_id, [])
        unique_users = len(
            {r.get("external_userid") for r in records if r.get("external_userid")}
        )
        recent_scans = sorted(
            records, key=lambda r: r.get("scanned_at", ""), reverse=True
        )[:20]

        log.info(
            "wecom_channel_code_mem_stats",
            total_scans=len(records),
            unique_users=unique_users,
        )
        return {
            "channel_id": channel_id,
            "channel_name": code.channel_name,
            "total_scans": len(records),
            "unique_users": unique_users,
            "recent_scans": recent_scans,
        }

    # ── 处理扫码事件 ─────────────────────────────────────────────

    async def handle_scan(
        self,
        channel_id: str,
        external_userid: str,
        tenant_id: str = "",
        db: Optional[AsyncSession] = None,
    ) -> dict[str, Any]:
        """处理扫码事件：自动打标签 + 自动回复 + 自动拉群

        Args:
            channel_id:     渠道活码 ID
            external_userid: 企微外部联系人 ID
            tenant_id:      租户 ID
            db:             数据库 session（None 则使用内存存储）

        Returns:
            {"success": True, "actions": ["tagged", "replied", "invited"]}
        """
        log = logger.bind(channel_id=channel_id, external_userid=external_userid)
        log.info("wecom_channel_code_scan_processing")

        code = await self.get_channel_code(
            channel_id=channel_id, tenant_id=tenant_id, db=db
        )
        if code is None:
            log.warning("wecom_channel_code_scan_not_found")
            return {"success": False, "error": "channel code not found"}

        actions: list[str] = []
        tagged = replied = invited = False

        if code.auto_tags:
            await self._tag_external_user(external_userid, code.auto_tags, tenant_id)
            actions.append("tagged")
            tagged = True

        if code.auto_reply:
            await self._send_auto_reply(external_userid, code.auto_reply, tenant_id)
            actions.append("replied")
            replied = True

        if code.group_id:
            await self._invite_to_group(external_userid, code.group_id, tenant_id)
            actions.append("invited")
            invited = True

        if db is not None:
            try:
                await db.execute(
                    update(WecomChannelCodeOrm)
                    .where(WecomChannelCodeOrm.id == uuid.UUID(channel_id))
                    .values(scan_count=WecomChannelCodeOrm.scan_count + 1)
                )

                scan_record = WecomScanRecordOrm(
                    tenant_id=uuid.UUID(tenant_id),
                    channel_id=uuid.UUID(channel_id),
                    external_userid=external_userid,
                    tagged=tagged,
                    replied=replied,
                    invited=invited,
                )
                db.add(scan_record)
                await db.commit()
            except SQLAlchemyError as e:
                await db.rollback()
                log.error("wecom_channel_code_scan_db_error", error=str(e), exc_info=True)
        else:
            if channel_id not in self._scan_records:
                self._scan_records[channel_id] = []
            self._scan_records[channel_id].append(
                {
                    "channel_id": channel_id,
                    "external_userid": external_userid,
                    "scanned_at": datetime.now().isoformat(),
                }
            )

            if channel_id in self._channel_codes:
                self._channel_codes[channel_id].scan_count += 1

        log.info("wecom_channel_code_scan_done", actions=actions)
        return {"success": True, "actions": actions}

    # ── ORM -> dict/Pydantic 转换 ───────────────────────────────

    @staticmethod
    def _orm_to_dict(orm: WecomChannelCodeOrm) -> dict[str, Any]:
        """ORM → dict（用于列表/详情响应）"""
        return {
            "id": str(orm.id),
            "merchant_code": orm.merchant_code,
            "channel_name": orm.channel_name,
            "qrcode_url": orm.qrcode_url,
            "auto_tags": list(orm.auto_tags) if orm.auto_tags else [],
            "auto_reply": orm.auto_reply or "",
            "group_id": str(orm.group_id) if orm.group_id else None,
            "scan_count": orm.scan_count or 0,
            "is_active": orm.is_active,
            "created_at": orm.created_at.isoformat() if orm.created_at else "",
            "updated_at": orm.updated_at.isoformat() if orm.updated_at else "",
        }

    @staticmethod
    def _orm_to_pydantic(orm: WecomChannelCodeOrm) -> WecomChannelCode:
        """ORM → Pydantic WecomChannelCode"""
        return WecomChannelCode(
            id=str(orm.id),
            merchant_code=orm.merchant_code,
            channel_name=orm.channel_name,
            qrcode_url=orm.qrcode_url,
            auto_tags=list(orm.auto_tags) if orm.auto_tags else [],
            auto_reply=orm.auto_reply or "",
            group_id=str(orm.group_id) if orm.group_id else None,
            scan_count=orm.scan_count or 0,
            is_active=orm.is_active,
            created_at=orm.created_at if orm.created_at else datetime.now(),
            updated_at=orm.updated_at if orm.updated_at else datetime.now(),
        )

    # ── 内部：调用企微 API ──────────────────────────────────────

    async def _tag_external_user(
        self, external_userid: str, tags: list[str], tenant_id: str
    ) -> None:
        """调用企微 API 为外部联系人打标签"""
        log = logger.bind(external_userid=external_userid, tags=tags)
        token = await self._get_wecom_access_token()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/mark_tag",
                    params={"access_token": token},
                    json={"external_userid": external_userid, "add_tag": tags},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    log.warning(
                        "wecom_mark_tag_api_error",
                        errcode=data["errcode"],
                        errmsg=data.get("errmsg"),
                    )
                else:
                    log.info("wecom_mark_tag_ok")
        except httpx.HTTPStatusError as exc:
            log.warning("wecom_mark_tag_http_error", status=exc.response.status_code)
        except httpx.RequestError as exc:
            log.warning("wecom_mark_tag_request_error", error=str(exc))

    async def _send_auto_reply(
        self, external_userid: str, reply_text: str, tenant_id: str
    ) -> None:
        """发送自动回复文本消息"""
        log = logger.bind(external_userid=external_userid)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/api/v1/wecom/messages/send",
                    json={
                        "external_userid": external_userid,
                        "msgtype": "text",
                        "text": {"content": reply_text},
                    },
                    headers={"X-Tenant-ID": tenant_id},
                )
                resp.raise_for_status()
                log.info("wecom_auto_reply_sent")
        except httpx.HTTPStatusError as exc:
            log.warning("wecom_auto_reply_http_error", status=exc.response.status_code)
        except httpx.RequestError as exc:
            log.warning("wecom_auto_reply_request_error", error=str(exc))

    async def _invite_to_group(
        self, external_userid: str, group_id: str, tenant_id: str
    ) -> None:
        """邀请外部联系人加入企微群"""
        log = logger.bind(external_userid=external_userid, group_id=group_id)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/api/v1/wecom/groups/{group_id}/invite",
                    json={"external_userids": [external_userid]},
                    headers={"X-Tenant-ID": tenant_id},
                )
                resp.raise_for_status()
                log.info("wecom_auto_invite_sent")
        except httpx.HTTPStatusError as exc:
            log.warning("wecom_auto_invite_http_error", status=exc.response.status_code)
        except httpx.RequestError as exc:
            log.warning("wecom_auto_invite_request_error", error=str(exc))

    async def _get_wecom_access_token(self) -> str:
        """从环境变量获取企微 access_token"""
        import os

        corp_id = os.getenv("WECOM_CORP_ID", "")
        secret = os.getenv("WECOM_SECRET", "")
        if not corp_id or not secret:
            logger.warning("wecom_channel_code_missing_credentials")
            return ""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                    params={"corpid": corp_id, "corpsecret": secret},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    logger.warning("wecom_get_token_error", errcode=data["errcode"])
                    return ""
                return data.get("access_token", "")
        except httpx.RequestError as exc:
            logger.warning("wecom_get_token_request_error", error=str(exc))
            return ""


# 模块级单例
wecom_channel_code_service = WecomChannelCodeService()
