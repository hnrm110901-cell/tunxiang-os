"""企微群运营服务

WecomGroupService 负责：
- create_group        — 根据配置建群并邀请分群成员
- send_group_message  — 向企微群发消息并记录历史
- execute_sop         — 执行指定 SOP 类型的内容发送
- scan_and_execute_daily_sop — 定时任务：扫描所有 active 群执行 daily SOP
- get_group_stats     — 群运营统计数据
- sync_group_members  — 同步群成员到会员系统

SOP 模板常量 DEFAULT_SOP_TEMPLATES 定义在本文件，可被 sop_calendar 配置覆盖。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .external_sdk import WecomAPIError, WecomSDK
from .models.wecom_group import WecomGroupConfig, WecomGroupMessage

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────
# 内置 SOP 模板（可被 sop_calendar 中的 content 字段覆盖）
# ─────────────────────────────────────────────────────────────────

DEFAULT_SOP_TEMPLATES: dict[str, str] = {
    "daily_morning": ("早安！今日为您精选 {today_special}，堂食/外卖均可享会员专属价。"),
    "weekly_friday": ("{store_name} 为您准备了精彩菜品，记得预约您的专属座位。"),
    "new_dish": ("【新品上市】{dish_name} 正式上线！前50位品鉴客户可享{offer_desc}，立即预约 →"),
    "holiday_generic": ("节日快乐！{store_name} 全体员工祝您{holiday_name}愉快，特为您准备了{offer_desc}"),
    "member_upgrade": ("恭喜 {display_name} 升级为{level_name}！专属权益已解锁，快来体验吧。"),
}

# ─────────────────────────────────────────────────────────────────
# 服务类
# ─────────────────────────────────────────────────────────────────


class WecomGroupService:
    """企微群运营服务"""

    TX_MEMBER_URL: str = os.getenv("TX_MEMBER_SERVICE_URL", "http://tx-member:8000")
    TX_GROWTH_URL: str = os.getenv("TX_GROWTH_SERVICE_URL", "http://tx-growth:8000")
    TX_MENU_URL: str = os.getenv("TX_MENU_SERVICE_URL", "http://tx-menu:8000")

    def __init__(self, wecom_sdk: WecomSDK | None = None) -> None:
        self._sdk = wecom_sdk or WecomSDK()

    # ── 建群 ──────────────────────────────────────────────────────

    async def create_group(
        self,
        config_id: UUID,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """根据配置建群并邀请成员

        流程：
        1. 查 WecomGroupConfig
        2. 从 tx-growth 拉取分群成员的 wecom_external_userid
        3. 从 tx-member 查第一个成员确认 owner（主导购的企微 userid）
        4. 调用企微 POST /appchat/create 建群
        5. 回填 group_chat_id，更新 config
        6. 返回 {chatid, member_count, success}
        """
        log = logger.bind(config_id=str(config_id), tenant_id=str(tenant_id))

        config = await self._get_config(config_id, tenant_id, db)
        if config is None:
            log.warning("wecom_group_create_config_not_found")
            return {"success": False, "error": "config not found"}

        # 拉取分群成员的企微 external_userid 列表
        member_userids = await self._fetch_segment_wecom_userids(
            config.target_segment_id,
            config.target_store_ids or [],
            config.max_members,
            tenant_id,
        )
        if len(member_userids) < 2:
            log.warning(
                "wecom_group_create_insufficient_members",
                count=len(member_userids),
            )
            return {
                "success": False,
                "error": f"分群成员数不足（需>=2，当前={len(member_userids)}）",
            }

        # owner 取列表中第一个（主导购需在成员列表中，这里简化取第一个企微内部员工）
        # 生产环境应从门店配置中取主导购的 wecom userid
        owner_userid = member_userids[0]
        invite_userids = member_userids[: config.max_members]

        log.info(
            "wecom_group_create_start",
            group_name=config.group_name,
            member_count=len(invite_userids),
        )

        try:
            result = await self._sdk.create_group_chat(
                name=config.group_name,
                owner_userid=owner_userid,
                member_userids=invite_userids,
            )
        except WecomAPIError as exc:
            log.error(
                "wecom_group_create_api_error",
                errcode=exc.errcode,
                errmsg=exc.errmsg,
            )
            return {"success": False, "error": f"WecomAPIError {exc.errcode}: {exc.errmsg}"}
        except httpx.HTTPStatusError as exc:
            log.error("wecom_group_create_http_error", status=exc.response.status_code)
            return {"success": False, "error": f"http_{exc.response.status_code}"}
        except httpx.RequestError as exc:
            log.error("wecom_group_create_request_error", error=str(exc))
            return {"success": False, "error": str(exc)}

        chatid: str = result.get("chatid", "")
        config.group_chat_id = chatid
        config.updated_at = datetime.now(timezone.utc)
        await db.commit()

        log.info("wecom_group_create_ok", chatid=chatid, member_count=len(invite_userids))
        return {
            "success": True,
            "chatid": chatid,
            "member_count": len(invite_userids),
        }

    # ── 发消息 ────────────────────────────────────────────────────

    async def send_group_message(
        self,
        group_chat_id: str,
        message_type: str,
        content: dict[str, Any],
        tenant_id: UUID,
        sop_type: str = "manual",
        db: AsyncSession | None = None,
        config_id: UUID | None = None,
        sent_by: str = "system",
    ) -> dict[str, Any]:
        """向企微群发消息，并记录发送历史

        消息发送失败只记录日志，不抛出异常（不影响业务）。

        Args:
            group_chat_id: 企微群 chatid
            message_type:  text | image | news | miniapp
            content:       消息内容体，如 {"content": "xxx"} 或 {"articles": [...]}
            tenant_id:     租户 UUID
            sop_type:      daily | weekly | holiday | new_dish | manual
            db:            数据库会话（可选，传入则记录历史）
            config_id:     关联配置 ID（可选）
            sent_by:       system 或员工 userid
        """
        log = logger.bind(
            chatid=group_chat_id,
            msgtype=message_type,
            sop_type=sop_type,
            tenant_id=str(tenant_id),
        )

        status = "sent"
        error_msg: str | None = None

        try:
            await self._sdk.send_group_chat_message(
                chatid=group_chat_id,
                msgtype=message_type,
                content_dict=content,
            )
            log.info("wecom_group_message_sent")
        except WecomAPIError as exc:
            status = "failed"
            error_msg = f"WecomAPIError {exc.errcode}: {exc.errmsg}"
            log.warning("wecom_group_message_api_error", errcode=exc.errcode, errmsg=exc.errmsg)
        except httpx.HTTPStatusError as exc:
            status = "failed"
            error_msg = f"http_{exc.response.status_code}"
            log.warning("wecom_group_message_http_error", status_code=exc.response.status_code)
        except httpx.RequestError as exc:
            status = "failed"
            error_msg = str(exc)
            log.warning("wecom_group_message_request_error", error=str(exc))

        # 记录发送历史（即使失败也记录）
        if db is not None and config_id is not None:
            msg_record = WecomGroupMessage(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                group_config_id=config_id,
                group_chat_id=group_chat_id,
                message_type=message_type,
                content=json.dumps(content, ensure_ascii=False),
                sop_type=sop_type,
                sent_at=datetime.now(timezone.utc),
                sent_by=sent_by,
                status=status,
                error_msg=error_msg,
            )
            db.add(msg_record)
            try:
                await db.commit()
            except Exception as db_exc:  # noqa: BLE001 — 历史记录写入失败不影响主流程
                logger.warning("wecom_group_message_record_db_error", error=str(db_exc))
                await db.rollback()

        return {
            "success": status == "sent",
            "status": status,
            "chatid": group_chat_id,
            "sop_type": sop_type,
            "error": error_msg,
        }

    # ── 执行 SOP ──────────────────────────────────────────────────

    async def execute_sop(
        self,
        config_id: UUID,
        sop_type: str,
        tenant_id: UUID,
        db: AsyncSession,
        extra_vars: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """执行指定类型的 SOP 内容发送

        流程：
        1. 查 WecomGroupConfig.sop_calendar，找到匹配 sop_type 的条目
        2. 渲染模板变量（{dish_name} / {store_name} 等）
        3. 调用 send_group_message 发送
        4. 返回执行结果

        Args:
            config_id:  群配置 UUID
            sop_type:   daily | weekly | holiday | new_dish | manual
            tenant_id:  租户 UUID
            db:         数据库会话
            extra_vars: 额外的模板变量（覆盖自动查询的变量）
        """
        log = logger.bind(
            config_id=str(config_id),
            sop_type=sop_type,
            tenant_id=str(tenant_id),
        )

        config = await self._get_config(config_id, tenant_id, db)
        if config is None:
            log.warning("wecom_group_sop_config_not_found")
            return {"success": False, "error": "config not found"}

        if config.status != "active":
            log.info("wecom_group_sop_skipped_inactive", status=config.status)
            return {"success": False, "skipped": True, "reason": f"group status={config.status}"}

        if not config.group_chat_id:
            log.warning("wecom_group_sop_no_chatid")
            return {"success": False, "error": "group_chat_id 未设置，请先执行建群"}

        # 从日历中找到第一个匹配的 SOP 条目
        calendar_entry = self._find_sop_entry(config.sop_calendar or [], sop_type)
        if calendar_entry is None:
            log.info("wecom_group_sop_entry_not_found", sop_type=sop_type)
            return {"success": False, "error": f"sop_calendar 中未找到 type={sop_type} 的条目"}

        # 准备模板变量
        template_vars = await self._build_template_vars(config, sop_type, tenant_id)
        if extra_vars:
            template_vars.update(extra_vars)

        # 渲染内容
        raw_content: str = calendar_entry.get("content", "")
        rendered = self._render_template(raw_content, template_vars)

        log.info("wecom_group_sop_executing", content_preview=rendered[:50])

        return await self.send_group_message(
            group_chat_id=config.group_chat_id,
            message_type="text",
            content={"content": rendered},
            tenant_id=tenant_id,
            sop_type=sop_type,
            db=db,
            config_id=config_id,
            sent_by="system",
        )

    # ── 批量 daily SOP ────────────────────────────────────────────

    async def scan_and_execute_daily_sop(
        self,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """定时任务（每天9点）：扫描所有 active 群执行 daily SOP

        遍历租户下所有 active 群配置，对有 sop_calendar 中 type=daily 条目的群发送。
        发送失败只记录日志，不中断后续群的发送。
        """
        log = logger.bind(tenant_id=str(tenant_id), task="daily_sop")
        log.info("wecom_group_daily_sop_scan_start")

        stmt = select(WecomGroupConfig).where(
            WecomGroupConfig.tenant_id == tenant_id,
            WecomGroupConfig.status == "active",
        )
        result = await db.execute(stmt)
        configs = result.scalars().all()

        total = len(configs)
        success_count = 0
        skip_count = 0
        fail_count = 0

        for config in configs:
            # 只处理有 chatid 且有 daily SOP 的群
            if not config.group_chat_id:
                skip_count += 1
                continue

            has_daily = any(entry.get("type") == "daily" for entry in (config.sop_calendar or []))
            if not has_daily:
                skip_count += 1
                continue

            sop_result = await self.execute_sop(
                config_id=config.id,
                sop_type="daily",
                tenant_id=tenant_id,
                db=db,
            )
            if sop_result.get("success"):
                success_count += 1
            elif sop_result.get("skipped"):
                skip_count += 1
            else:
                fail_count += 1
                log.warning(
                    "wecom_group_daily_sop_item_failed",
                    config_id=str(config.id),
                    group_name=config.group_name,
                    error=sop_result.get("error"),
                )

        log.info(
            "wecom_group_daily_sop_scan_done",
            total=total,
            success=success_count,
            skipped=skip_count,
            failed=fail_count,
        )
        return {
            "total": total,
            "success": success_count,
            "skipped": skip_count,
            "failed": fail_count,
        }

    # ── 群统计 ────────────────────────────────────────────────────

    async def get_group_stats(
        self,
        config_id: UUID,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """群运营统计

        返回：
        - 总发送消息数、各 sop_type 分布
        - 成功/失败率
        - 企微 API 实时成员数
        """
        log = logger.bind(config_id=str(config_id), tenant_id=str(tenant_id))

        config = await self._get_config(config_id, tenant_id, db)
        if config is None:
            return {"success": False, "error": "config not found"}

        # 从历史表统计
        stmt = select(WecomGroupMessage).where(
            WecomGroupMessage.group_config_id == config_id,
            WecomGroupMessage.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        messages = result.scalars().all()

        total_sent = len(messages)
        success_sent = sum(1 for m in messages if m.status == "sent")
        sop_type_counts: dict[str, int] = {}
        for m in messages:
            key = m.sop_type or "manual"
            sop_type_counts[key] = sop_type_counts.get(key, 0) + 1

        # 从企微 API 获取实时成员数（失败不影响统计）
        member_count: int | None = None
        if config.group_chat_id:
            try:
                chat_info = await self._sdk.get_group_chat_info(config.group_chat_id)
                member_count = len(chat_info.get("member_list", []))
            except WecomAPIError as exc:
                log.warning(
                    "wecom_group_stats_get_members_api_error",
                    errcode=exc.errcode,
                    errmsg=exc.errmsg,
                )
            except httpx.RequestError as exc:
                log.warning("wecom_group_stats_get_members_request_error", error=str(exc))

        return {
            "config_id": str(config_id),
            "group_name": config.group_name,
            "group_chat_id": config.group_chat_id,
            "status": config.status,
            "total_messages": total_sent,
            "success_messages": success_sent,
            "failed_messages": total_sent - success_sent,
            "sop_type_breakdown": sop_type_counts,
            "current_member_count": member_count,
        }

    # ── 同步群成员 ────────────────────────────────────────────────

    async def sync_group_members(
        self,
        config_id: UUID,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """同步群成员到会员系统

        流程：
        1. 调用企微 GET /appchat/get 获取当前群成员列表
        2. 从 tx-growth 获取分群符合条件的成员
        3. 对比两份名单，找出需要邀请的新成员
        4. 记录变化日志

        注：实际邀请操作（POST /appchat/update）需要企微接口配合，
        此版本返回待邀请名单，由调用方决定是否执行邀请。
        """
        log = logger.bind(config_id=str(config_id), tenant_id=str(tenant_id))

        config = await self._get_config(config_id, tenant_id, db)
        if config is None:
            return {"success": False, "error": "config not found"}

        if not config.group_chat_id:
            return {"success": False, "error": "group_chat_id 未设置，请先执行建群"}

        # 获取当前群成员
        try:
            chat_info = await self._sdk.get_group_chat_info(config.group_chat_id)
        except WecomAPIError as exc:
            log.error("wecom_group_sync_get_info_api_error", errcode=exc.errcode)
            return {"success": False, "error": f"WecomAPIError {exc.errcode}: {exc.errmsg}"}
        except httpx.RequestError as exc:
            log.error("wecom_group_sync_get_info_request_error", error=str(exc))
            return {"success": False, "error": str(exc)}

        current_member_ids: set[str] = {m["userid"] for m in chat_info.get("member_list", []) if m.get("userid")}

        # 获取分群符合条件的成员（企微 external_userid）
        segment_userids = await self._fetch_segment_wecom_userids(
            config.target_segment_id,
            config.target_store_ids or [],
            config.max_members,
            tenant_id,
        )
        segment_set = set(segment_userids)

        # 计算差集
        to_invite = list(segment_set - current_member_ids)
        already_in = list(segment_set & current_member_ids)

        log.info(
            "wecom_group_sync_diff",
            current_count=len(current_member_ids),
            segment_count=len(segment_set),
            to_invite_count=len(to_invite),
        )

        return {
            "success": True,
            "chatid": config.group_chat_id,
            "current_member_count": len(current_member_ids),
            "segment_member_count": len(segment_set),
            "already_in_group": len(already_in),
            "to_invite": to_invite,
            "to_invite_count": len(to_invite),
        }

    # ── 内部辅助方法 ──────────────────────────────────────────────

    async def _get_config(
        self,
        config_id: UUID,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> WecomGroupConfig | None:
        """查询群配置，自动带租户隔离"""
        stmt = select(WecomGroupConfig).where(
            WecomGroupConfig.id == config_id,
            WecomGroupConfig.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _fetch_segment_wecom_userids(
        self,
        segment_id: str,
        store_ids: list[Any],
        limit: int,
        tenant_id: UUID,
    ) -> list[str]:
        """从 tx-growth 拉取分群成员的 wecom_external_userid

        接口：GET /api/v1/segments/{segment_id}/members?limit=N
        返回 list of wecom_external_userid

        失败时返回空列表（降级策略，不阻塞建群流程）
        """
        log = logger.bind(segment_id=segment_id, tenant_id=str(tenant_id))
        params: dict[str, Any] = {"limit": limit}
        if store_ids:
            params["store_ids"] = ",".join(str(s) for s in store_ids)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.TX_GROWTH_URL}/api/v1/segments/{segment_id}/members",
                    params=params,
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.warning(
                "wecom_group_fetch_segment_http_error",
                status=exc.response.status_code,
            )
            return []
        except httpx.RequestError as exc:
            log.warning("wecom_group_fetch_segment_request_error", error=str(exc))
            return []

        data = resp.json()
        # 兼容 {data: [{wecom_external_userid: ...}]} 和 {items: [...]} 两种响应格式
        items = data.get("data") or data.get("items") or []
        userids = [item["wecom_external_userid"] for item in items if item.get("wecom_external_userid")]
        log.info("wecom_group_fetch_segment_ok", count=len(userids))
        return userids

    def _find_sop_entry(
        self,
        sop_calendar: list[dict[str, Any]],
        sop_type: str,
    ) -> dict[str, Any] | None:
        """从 sop_calendar 中找到第一个匹配 sop_type 的条目"""
        for entry in sop_calendar:
            if entry.get("type") == sop_type:
                return entry
        return None

    async def _build_template_vars(
        self,
        config: WecomGroupConfig,
        sop_type: str,
        tenant_id: UUID,
    ) -> dict[str, str]:
        """构建 SOP 模板变量

        自动查询：
        - today_special: 今日推荐（从 tx-menu 查当日新品/推荐菜）
        - dish_name:      新品名称（new_dish SOP 专用）
        - store_name:     门店名称（从配置推断）

        查询失败时使用占位符，不中断 SOP 发送。
        """
        vars_map: dict[str, str] = {
            "store_name": "本店",
            "today_special": "今日精选",
            "dish_name": "新品",
            "offer_desc": "专属优惠",
            "holiday_name": "节日",
            "display_name": "会员",
            "level_name": "新等级",
        }

        if sop_type in ("new_dish", "daily"):
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    resp = await client.get(
                        f"{self.TX_MENU_URL}/api/v1/dishes/today-specials",
                        headers={"X-Tenant-ID": str(tenant_id)},
                        params={"limit": 1},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("data") or data.get("items") or []
                        if items:
                            dish = items[0]
                            vars_map["dish_name"] = dish.get("name", "新品")
                            vars_map["today_special"] = dish.get("name", "今日精选")
            except httpx.RequestError as exc:
                logger.warning("wecom_group_template_vars_menu_error", error=str(exc))

        return vars_map

    @staticmethod
    def _render_template(template: str, vars_map: dict[str, str]) -> str:
        """渲染模板变量，未匹配的占位符保留原样"""
        try:
            return template.format_map(vars_map)
        except KeyError:
            # 部分变量缺失时逐个替换，保留未匹配的 {key}
            result = template
            for key, value in vars_map.items():
                result = result.replace(f"{{{key}}}", value)
            return result
