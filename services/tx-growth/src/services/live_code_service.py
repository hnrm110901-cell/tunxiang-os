"""活码拉新引擎服务 — 活码CRUD/扫码处理/LBS匹配/渠道统计/门店绑定

核心功能：
  - CRUD:              活码创建/查询/更新/删除/暂停/恢复
  - process_scan:      扫码处理（限额检查→记录→LBS匹配→自动打标）
  - match_nearest:     Haversine最近门店匹配
  - channel_stats:     渠道维度统计
  - overview_stats:    多维概览（按渠道/活码/门店/日期）
  - aggregate_daily:   每日统计聚合（定时任务调用）
  - store_bindings:    门店绑定/解绑管理
"""

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


class LiveCodeError(Exception):
    """活码引擎业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LiveCodeService:
    """活码拉新引擎核心服务"""

    # ===================================================================
    # CRUD — 活码管理
    # ===================================================================

    async def create_live_code(
        self,
        tenant_id: uuid.UUID,
        code_name: str,
        code_type: str,
        created_by: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        wecom_config_id: Optional[uuid.UUID] = None,
        welcome_msg: Optional[str] = None,
        welcome_media_url: Optional[str] = None,
        target_group_ids: Optional[list] = None,
        lbs_radius_meters: int = 3000,
        daily_add_limit: int = 200,
        total_add_limit: Optional[int] = None,
        auto_tag_ids: Optional[list] = None,
        channel_source: Optional[str] = None,
        qr_image_url: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> dict:
        """创建活码"""
        code_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO live_codes (
                    id, tenant_id, store_id, code_name, code_type,
                    wecom_config_id, welcome_msg, welcome_media_url,
                    target_group_ids, lbs_radius_meters,
                    daily_add_limit, total_add_limit,
                    auto_tag_ids, channel_source, qr_image_url,
                    expires_at, created_by
                ) VALUES (
                    :id, :tenant_id, :store_id, :code_name, :code_type,
                    :wecom_config_id, :welcome_msg, :welcome_media_url,
                    :target_group_ids::jsonb, :lbs_radius_meters,
                    :daily_add_limit, :total_add_limit,
                    :auto_tag_ids::jsonb, :channel_source, :qr_image_url,
                    :expires_at, :created_by
                )
            """),
            {
                "id": str(code_id),
                "tenant_id": str(tenant_id),
                "store_id": str(store_id) if store_id else None,
                "code_name": code_name,
                "code_type": code_type,
                "wecom_config_id": str(wecom_config_id) if wecom_config_id else None,
                "welcome_msg": welcome_msg,
                "welcome_media_url": welcome_media_url,
                "target_group_ids": json.dumps(target_group_ids or []),
                "lbs_radius_meters": lbs_radius_meters,
                "daily_add_limit": daily_add_limit,
                "total_add_limit": total_add_limit,
                "auto_tag_ids": json.dumps(auto_tag_ids or []),
                "channel_source": channel_source,
                "qr_image_url": qr_image_url,
                "expires_at": expires_at,
                "created_by": str(created_by),
            },
        )
        log.info("live_code_created", code_id=str(code_id), code_type=code_type)
        return {"code_id": str(code_id)}

    async def get_live_code(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取活码详情"""
        result = await db.execute(
            text("""
                SELECT * FROM live_codes
                WHERE tenant_id = :tenant_id AND id = :code_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "code_id": str(code_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise LiveCodeError("NOT_FOUND", "活码不存在")
        return dict(row)

    async def list_live_codes(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        code_type: Optional[str] = None,
        status: Optional[str] = None,
        channel_source: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询活码列表"""
        where = "tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if store_id:
            where += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        if code_type:
            where += " AND code_type = :code_type"
            params["code_type"] = code_type
        if status:
            where += " AND status = :status"
            params["status"] = status
        if channel_source:
            where += " AND channel_source = :channel_source"
            params["channel_source"] = channel_source

        count_result = await db.execute(text(f"SELECT COUNT(*) FROM live_codes WHERE {where}"), params)
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        data_sql = f"""
            SELECT * FROM live_codes WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = size
        params["offset"] = offset
        result = await db.execute(text(data_sql), params)
        items = [dict(r) for r in result.mappings().all()]

        return {"items": items, "total": total, "page": page, "size": size}

    async def update_live_code(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        updates: dict,
        db: Any,
    ) -> dict:
        """更新活码配置"""
        allowed = {
            "code_name",
            "welcome_msg",
            "welcome_media_url",
            "target_group_ids",
            "lbs_radius_meters",
            "daily_add_limit",
            "total_add_limit",
            "auto_tag_ids",
            "channel_source",
            "qr_image_url",
            "expires_at",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            raise LiveCodeError("EMPTY_UPDATE", "无有效更新字段")

        set_parts = [f"{k} = :{k}" for k in filtered]
        set_parts.append("updated_at = now()")
        sql = f"""
            UPDATE live_codes SET {", ".join(set_parts)}
            WHERE tenant_id = :tenant_id AND id = :code_id AND is_deleted = FALSE
        """
        filtered["tenant_id"] = str(tenant_id)
        filtered["code_id"] = str(code_id)
        result = await db.execute(text(sql), filtered)
        if result.rowcount == 0:
            raise LiveCodeError("NOT_FOUND", "活码不存在")
        return {"updated": True}

    async def delete_live_code(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """软删除活码"""
        result = await db.execute(
            text("""
                UPDATE live_codes SET is_deleted = TRUE, updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :code_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "code_id": str(code_id)},
        )
        if result.rowcount == 0:
            raise LiveCodeError("NOT_FOUND", "活码不存在")
        log.info("live_code_deleted", code_id=str(code_id))
        return {"deleted": True}

    async def pause_live_code(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """暂停活码"""
        result = await db.execute(
            text("""
                UPDATE live_codes SET status = 'paused', updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :code_id
                  AND is_deleted = FALSE AND status = 'active'
            """),
            {"tenant_id": str(tenant_id), "code_id": str(code_id)},
        )
        if result.rowcount == 0:
            raise LiveCodeError("INVALID_STATE", "活码不存在或无法暂停")
        return {"status": "paused"}

    async def resume_live_code(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """恢复活码"""
        result = await db.execute(
            text("""
                UPDATE live_codes SET status = 'active', updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :code_id
                  AND is_deleted = FALSE AND status = 'paused'
            """),
            {"tenant_id": str(tenant_id), "code_id": str(code_id)},
        )
        if result.rowcount == 0:
            raise LiveCodeError("INVALID_STATE", "活码不存在或无法恢复")
        return {"status": "active"}

    # ===================================================================
    # Scan — 扫码处理
    # ===================================================================

    async def process_scan(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        db: Any,
        *,
        customer_id: Optional[uuid.UUID] = None,
        wecom_external_userid: Optional[str] = None,
        scan_source: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        device_info: Optional[dict] = None,
    ) -> dict:
        """处理扫码请求：限额检查→记录→LBS匹配→自动打标"""
        # 1. 获取活码配置
        code = await self.get_live_code(tenant_id, code_id, db)

        # 2. 状态检查
        if code["status"] != "active":
            scan_id = await self._record_scan(
                tenant_id,
                code_id,
                db,
                customer_id=customer_id,
                wecom_external_userid=wecom_external_userid,
                scan_source=scan_source,
                latitude=latitude,
                longitude=longitude,
                device_info=device_info,
                result="expired",
            )
            return {"scan_id": scan_id, "result": "expired", "reason": "活码已暂停或过期"}

        # 3. 过期检查
        if code.get("expires_at") and code["expires_at"] < datetime.now(timezone.utc):
            await db.execute(
                text("UPDATE live_codes SET status = 'expired', updated_at = now() WHERE id = :id"),
                {"id": str(code_id)},
            )
            scan_id = await self._record_scan(
                tenant_id,
                code_id,
                db,
                customer_id=customer_id,
                wecom_external_userid=wecom_external_userid,
                scan_source=scan_source,
                latitude=latitude,
                longitude=longitude,
                device_info=device_info,
                result="expired",
            )
            return {"scan_id": scan_id, "result": "expired", "reason": "活码已过期"}

        # 4. 每日限额检查
        today = date.today()
        daily_count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM live_code_scans
                WHERE live_code_id = :code_id AND result = 'success'
                  AND created_at::date = :today AND is_deleted = FALSE
            """),
            {"code_id": str(code_id), "today": today},
        )
        daily_count = daily_count_result.scalar() or 0
        if daily_count >= code["daily_add_limit"]:
            scan_id = await self._record_scan(
                tenant_id,
                code_id,
                db,
                customer_id=customer_id,
                wecom_external_userid=wecom_external_userid,
                scan_source=scan_source,
                latitude=latitude,
                longitude=longitude,
                device_info=device_info,
                result="limit_reached",
            )
            return {"scan_id": scan_id, "result": "limit_reached", "reason": "今日添加已达上限"}

        # 5. 总量限额检查
        if code.get("total_add_limit"):
            total_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM live_code_scans
                    WHERE live_code_id = :code_id AND result = 'success' AND is_deleted = FALSE
                """),
                {"code_id": str(code_id)},
            )
            total_count = total_result.scalar() or 0
            if total_count >= code["total_add_limit"]:
                scan_id = await self._record_scan(
                    tenant_id,
                    code_id,
                    db,
                    customer_id=customer_id,
                    wecom_external_userid=wecom_external_userid,
                    scan_source=scan_source,
                    latitude=latitude,
                    longitude=longitude,
                    device_info=device_info,
                    result="limit_reached",
                )
                return {"scan_id": scan_id, "result": "limit_reached", "reason": "总量已达上限"}

        # 6. LBS匹配最近门店
        matched_store_id = None
        if code["code_type"] == "lbs" and latitude is not None and longitude is not None:
            matched = await self.match_nearest_store(
                tenant_id,
                code_id,
                latitude,
                longitude,
                code["lbs_radius_meters"],
                db,
            )
            matched_store_id = matched.get("store_id") if matched else None

        # 7. 记录成功扫码
        scan_id = await self._record_scan(
            tenant_id,
            code_id,
            db,
            customer_id=customer_id,
            wecom_external_userid=wecom_external_userid,
            scan_source=scan_source,
            latitude=latitude,
            longitude=longitude,
            matched_store_id=matched_store_id,
            device_info=device_info,
            result="success",
            store_id=code.get("store_id"),
        )

        log.info(
            "live_code_scan_success",
            code_id=str(code_id),
            scan_id=scan_id,
            matched_store=str(matched_store_id) if matched_store_id else None,
        )
        return {
            "scan_id": scan_id,
            "result": "success",
            "matched_store_id": str(matched_store_id) if matched_store_id else None,
            "welcome_msg": code.get("welcome_msg"),
            "welcome_media_url": code.get("welcome_media_url"),
            "auto_tag_ids": code.get("auto_tag_ids", []),
        }

    async def _record_scan(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        db: Any,
        *,
        customer_id: Optional[uuid.UUID] = None,
        wecom_external_userid: Optional[str] = None,
        scan_source: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        matched_store_id: Optional[str] = None,
        device_info: Optional[dict] = None,
        result: str = "success",
        store_id: Optional[Any] = None,
    ) -> str:
        """记录扫码"""
        scan_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO live_code_scans (
                    id, tenant_id, live_code_id, store_id,
                    customer_id, wecom_external_userid,
                    scan_source, latitude, longitude,
                    matched_store_id, result, device_info
                ) VALUES (
                    :id, :tenant_id, :code_id, :store_id,
                    :customer_id, :wecom_external_userid,
                    :scan_source, :latitude, :longitude,
                    :matched_store_id, :result, :device_info::jsonb
                )
            """),
            {
                "id": str(scan_id),
                "tenant_id": str(tenant_id),
                "code_id": str(code_id),
                "store_id": str(store_id) if store_id else None,
                "customer_id": str(customer_id) if customer_id else None,
                "wecom_external_userid": wecom_external_userid,
                "scan_source": scan_source,
                "latitude": latitude,
                "longitude": longitude,
                "matched_store_id": str(matched_store_id) if matched_store_id else None,
                "result": result,
                "device_info": json.dumps(device_info) if device_info else None,
            },
        )
        return str(scan_id)

    # ===================================================================
    # LBS — 最近门店匹配（Haversine）
    # ===================================================================

    async def match_nearest_store(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        latitude: float,
        longitude: float,
        radius_meters: int,
        db: Any,
    ) -> Optional[dict]:
        """Haversine公式匹配最近门店"""
        result = await db.execute(
            text("""
                SELECT store_id, latitude, longitude,
                    (6371000 * acos(
                        LEAST(1.0, cos(radians(:lat)) * cos(radians(latitude))
                        * cos(radians(longitude) - radians(:lng))
                        + sin(radians(:lat)) * sin(radians(latitude)))
                    )) AS distance_meters
                FROM live_code_store_bindings
                WHERE tenant_id = :tenant_id
                  AND live_code_id = :code_id
                  AND is_active = TRUE
                  AND is_deleted = FALSE
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
                ORDER BY distance_meters ASC
                LIMIT 1
            """),
            {
                "tenant_id": str(tenant_id),
                "code_id": str(code_id),
                "lat": latitude,
                "lng": longitude,
            },
        )
        row = result.mappings().first()
        if row is None:
            return None
        if row["distance_meters"] > radius_meters:
            return None
        return {
            "store_id": str(row["store_id"]),
            "distance_meters": float(row["distance_meters"]),
        }

    # ===================================================================
    # Stats — 渠道统计
    # ===================================================================

    async def get_channel_stats(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        code_id: Optional[uuid.UUID] = None,
        store_id: Optional[uuid.UUID] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """获取渠道统计数据"""
        where = "tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if code_id:
            where += " AND live_code_id = :code_id"
            params["code_id"] = str(code_id)
        if store_id:
            where += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        if date_from:
            where += " AND stat_date >= :date_from"
            params["date_from"] = date_from
        if date_to:
            where += " AND stat_date <= :date_to"
            params["date_to"] = date_to

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM live_code_channel_stats WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        data_sql = f"""
            SELECT * FROM live_code_channel_stats WHERE {where}
            ORDER BY stat_date DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = size
        params["offset"] = offset
        result = await db.execute(text(data_sql), params)
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_overview_stats(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        group_by: str = "date",
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        store_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """多维概览统计（group_by: channel/code/store/date）"""
        group_col_map = {
            "channel": "lc.channel_source",
            "code": "s.live_code_id",
            "store": "s.store_id",
            "date": "s.stat_date",
        }
        group_col = group_col_map.get(group_by, "s.stat_date")

        where = "s.tenant_id = :tenant_id AND s.is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if date_from:
            where += " AND s.stat_date >= :date_from"
            params["date_from"] = date_from
        if date_to:
            where += " AND s.stat_date <= :date_to"
            params["date_to"] = date_to
        if store_id:
            where += " AND s.store_id = :store_id"
            params["store_id"] = str(store_id)

        if group_by == "channel":
            sql = f"""
                SELECT {group_col} AS group_key,
                    SUM(s.scan_count) AS total_scans,
                    SUM(s.success_count) AS total_success,
                    SUM(s.new_friend_count) AS total_new_friends,
                    SUM(s.new_group_member_count) AS total_new_group_members,
                    SUM(s.lost_count) AS total_lost,
                    SUM(s.retention_count) AS total_retention
                FROM live_code_channel_stats s
                JOIN live_codes lc ON lc.id = s.live_code_id
                WHERE {where}
                GROUP BY {group_col}
                ORDER BY total_scans DESC
            """
        else:
            sql = f"""
                SELECT {group_col} AS group_key,
                    SUM(s.scan_count) AS total_scans,
                    SUM(s.success_count) AS total_success,
                    SUM(s.new_friend_count) AS total_new_friends,
                    SUM(s.new_group_member_count) AS total_new_group_members,
                    SUM(s.lost_count) AS total_lost,
                    SUM(s.retention_count) AS total_retention
                FROM live_code_channel_stats s
                WHERE {where}
                GROUP BY {group_col}
                ORDER BY {group_col} DESC
            """

        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    async def aggregate_daily_stats(
        self,
        tenant_id: uuid.UUID,
        stat_date: date,
        db: Any,
    ) -> dict:
        """每日统计聚合（定时任务调用）"""
        # 聚合当日扫码数据到 channel_stats 表
        result = await db.execute(
            text("""
                INSERT INTO live_code_channel_stats (
                    tenant_id, live_code_id, store_id, stat_date,
                    scan_count, success_count
                )
                SELECT
                    tenant_id,
                    live_code_id,
                    COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::uuid),
                    :stat_date,
                    COUNT(*),
                    COUNT(*) FILTER (WHERE result = 'success')
                FROM live_code_scans
                WHERE tenant_id = :tenant_id
                  AND created_at::date = :stat_date
                  AND is_deleted = FALSE
                GROUP BY tenant_id, live_code_id, store_id
                ON CONFLICT (tenant_id, live_code_id, store_id, stat_date) DO UPDATE SET
                    scan_count = EXCLUDED.scan_count,
                    success_count = EXCLUDED.success_count,
                    updated_at = now()
            """),
            {"tenant_id": str(tenant_id), "stat_date": stat_date},
        )
        log.info("live_code_daily_stats_aggregated", tenant_id=str(tenant_id), date=str(stat_date))
        return {"aggregated": True, "date": str(stat_date)}

    # ===================================================================
    # Store Bindings — 门店绑定
    # ===================================================================

    async def bind_store(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        store_id: uuid.UUID,
        db: Any,
        *,
        group_chat_id: Optional[str] = None,
        wecom_userid: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> dict:
        """绑定门店到活码"""
        binding_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO live_code_store_bindings (
                    id, tenant_id, live_code_id, store_id,
                    group_chat_id, wecom_userid, latitude, longitude
                ) VALUES (
                    :id, :tenant_id, :code_id, :store_id,
                    :group_chat_id, :wecom_userid, :latitude, :longitude
                )
                ON CONFLICT (tenant_id, live_code_id, store_id) DO UPDATE SET
                    group_chat_id = EXCLUDED.group_chat_id,
                    wecom_userid = EXCLUDED.wecom_userid,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    is_active = TRUE,
                    updated_at = now()
            """),
            {
                "id": str(binding_id),
                "tenant_id": str(tenant_id),
                "code_id": str(code_id),
                "store_id": str(store_id),
                "group_chat_id": group_chat_id,
                "wecom_userid": wecom_userid,
                "latitude": latitude,
                "longitude": longitude,
            },
        )
        log.info("live_code_store_bound", code_id=str(code_id), store_id=str(store_id))
        return {"binding_id": str(binding_id)}

    async def unbind_store(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        store_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """解绑门店"""
        result = await db.execute(
            text("""
                UPDATE live_code_store_bindings
                SET is_active = FALSE, updated_at = now()
                WHERE tenant_id = :tenant_id
                  AND live_code_id = :code_id
                  AND store_id = :store_id
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "code_id": str(code_id),
                "store_id": str(store_id),
            },
        )
        if result.rowcount == 0:
            raise LiveCodeError("NOT_FOUND", "绑定关系不存在")
        return {"unbound": True}

    async def list_store_bindings(
        self,
        tenant_id: uuid.UUID,
        code_id: uuid.UUID,
        db: Any,
    ) -> list[dict]:
        """查询活码的门店绑定列表"""
        result = await db.execute(
            text("""
                SELECT * FROM live_code_store_bindings
                WHERE tenant_id = :tenant_id
                  AND live_code_id = :code_id
                  AND is_deleted = FALSE
                ORDER BY is_active DESC, created_at DESC
            """),
            {"tenant_id": str(tenant_id), "code_id": str(code_id)},
        )
        return [dict(r) for r in result.mappings().all()]
