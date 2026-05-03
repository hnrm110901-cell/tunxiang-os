"""身份解析引擎 — S2W5 CDP多源数据融合

支持三种匹配策略：
1. phone_hash 精确匹配（置信度 1.0）
2. 时间关联匹配 — WiFi到店时间与订单时间重叠（置信度 0.6-0.9）
3. 手动匹配（管理后台人工指定）

批量解析：定时任务（nightly batch）遍历所有未匹配记录

UnionID 补全（MU-1）：
- backfill_union_id: 存量会员 WeChat UnionID 批量补全
- 通过微信 API: GET /sns/userinfo 根据 openid 获取 union_id
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import MemberEventType

logger = structlog.get_logger(__name__)

# 时间关联窗口：WiFi 访问时间与订单时间的最大差距
TIME_CORRELATION_WINDOW_HOURS = 2

# 微信 API 配置（从环境变量读取）
WECHAT_APP_ID: str = os.environ.get("WECHAT_APP_ID", "")
WECHAT_APP_SECRET: str = os.environ.get("WECHAT_APP_SECRET", "")

# Access Token 缓存（全局单例）
_ACCESS_TOKEN_CACHE: dict[str, tuple[str, float]] = {}  # {tenant_id: (token, expires_at)}
TOKEN_EXPIRE_BUFFER = 300  # 提前 300 秒刷新，避免边界过期

# 分页大小
BACKFILL_PAGE_SIZE = 100


@dataclass
class BackfillReport:
    """UnionID 批量补全报告"""

    total: int = 0  # 总待处理数
    succeeded: int = 0  # 成功补全数
    failed: int = 0  # 失败数
    errors: list[dict] = field(default_factory=list)  # 错误详情 [{openid, error}]


class IdentityResolver:
        self,
        tenant_id: str,
        wifi_visit_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        解析单条WiFi访问记录的身份：
        1. 先尝试 phone_hash 精确匹配（通过 mac_hash 历史关联）
        2. 再尝试时间关联：同门店、时间窗口内有订单的已知客户
        """
        # 获取WiFi访问记录
        row = await db.execute(
            text("""
                SELECT id, store_id, mac_hash, first_seen_at, last_seen_at,
                       matched_customer_id
                FROM wifi_visit_logs
                WHERE id = :vid AND tenant_id = :tid AND is_deleted = false
            """),
            {"vid": wifi_visit_id, "tid": tenant_id},
        )
        visit = row.mappings().first()
        if not visit:
            raise ValueError(f"WiFi visit {wifi_visit_id} not found")

        if visit["matched_customer_id"]:
            return {
                "visit_id": wifi_visit_id,
                "already_matched": True,
                "customer_id": str(visit["matched_customer_id"]),
            }

        store_id = str(visit["store_id"])
        mac_hash = visit["mac_hash"]
        first_seen = visit["first_seen_at"]

        # 策略1: 查找同mac_hash的历史已匹配记录 → phone_hash 精确匹配
        prev = await db.execute(
            text("""
                SELECT matched_customer_id
                FROM wifi_visit_logs
                WHERE tenant_id = :tid AND mac_hash = :mh
                  AND matched_customer_id IS NOT NULL
                  AND is_deleted = false
                ORDER BY last_seen_at DESC
                LIMIT 1
            """),
            {"tid": tenant_id, "mh": mac_hash},
        )
        prev_match = prev.mappings().first()
        if prev_match:
            customer_id = str(prev_match["matched_customer_id"])
            await self._update_wifi_match(
                db,
                wifi_visit_id,
                customer_id,
                1.0,
                "phone_hash",
            )
            logger.info(
                "identity.wifi_phone_hash_match",
                tenant_id=tenant_id,
                visit_id=wifi_visit_id,
                customer_id=customer_id,
            )
            return {
                "visit_id": wifi_visit_id,
                "matched": True,
                "customer_id": customer_id,
                "confidence": 1.0,
                "method": "phone_hash",
            }

        # 策略2: 时间关联 — 同门店、同时间段内有订单的客户
        window_start = first_seen - timedelta(hours=TIME_CORRELATION_WINDOW_HOURS)
        window_end = first_seen + timedelta(hours=TIME_CORRELATION_WINDOW_HOURS)

        corr = await db.execute(
            text("""
                SELECT o.customer_id, COUNT(*)::int AS order_count
                FROM orders o
                WHERE o.tenant_id = :tid AND o.store_id = :sid
                  AND o.created_at >= :ws AND o.created_at <= :we
                  AND o.customer_id IS NOT NULL
                  AND o.is_deleted = false AND o.status = 'paid'
                GROUP BY o.customer_id
                ORDER BY order_count DESC
                LIMIT 1
            """),
            {
                "tid": tenant_id,
                "sid": store_id,
                "ws": window_start,
                "we": window_end,
            },
        )
        corr_match = corr.mappings().first()
        if corr_match:
            customer_id = str(corr_match["customer_id"])
            # 置信度基于订单数量：1单=0.6, 2单=0.75, 3+单=0.9
            order_count = corr_match["order_count"]
            if order_count >= 3:
                confidence = 0.9
            elif order_count >= 2:
                confidence = 0.75
            else:
                confidence = 0.6

            await self._update_wifi_match(
                db,
                wifi_visit_id,
                customer_id,
                confidence,
                "mac_correlation",
            )
            logger.info(
                "identity.wifi_time_correlation",
                tenant_id=tenant_id,
                visit_id=wifi_visit_id,
                customer_id=customer_id,
                confidence=confidence,
            )
            return {
                "visit_id": wifi_visit_id,
                "matched": True,
                "customer_id": customer_id,
                "confidence": confidence,
                "method": "mac_correlation",
            }

        return {"visit_id": wifi_visit_id, "matched": False}

    async def resolve_external_order(
        self,
        tenant_id: str,
        import_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        解析外部订单的身份 — 通过 phone_hash 与 golden_id 映射精确匹配
        """
        row = await db.execute(
            text("""
                SELECT id, customer_phone_hash, matched_customer_id, source
                FROM external_order_imports
                WHERE id = :iid AND tenant_id = :tid AND is_deleted = false
            """),
            {"iid": import_id, "tid": tenant_id},
        )
        imp = row.mappings().first()
        if not imp:
            raise ValueError(f"External order import {import_id} not found")

        if imp["matched_customer_id"]:
            return {
                "import_id": import_id,
                "already_matched": True,
                "customer_id": str(imp["matched_customer_id"]),
            }

        phone_hash = imp["customer_phone_hash"]
        if not phone_hash:
            return {"import_id": import_id, "matched": False, "reason": "no_phone_hash"}

        # 通过 golden_id 映射查找 phone_hash 对应的 customer
        cust = await db.execute(
            text("""
                SELECT customer_id
                FROM golden_id_mappings
                WHERE tenant_id = :tid
                  AND channel_type = 'phone_hash'
                  AND channel_openid = :ph
                  AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tenant_id, "ph": phone_hash},
        )
        match = cust.mappings().first()
        if match:
            customer_id = str(match["customer_id"])
            await db.execute(
                text("""
                    UPDATE external_order_imports
                    SET matched_customer_id = :cid,
                        match_confidence = 1.0,
                        updated_at = NOW()
                    WHERE id = :iid
                """),
                {"cid": customer_id, "iid": import_id},
            )
            await db.commit()
            logger.info(
                "identity.external_phone_hash_match",
                tenant_id=tenant_id,
                import_id=import_id,
                customer_id=customer_id,
                source=imp["source"],
            )
            return {
                "import_id": import_id,
                "matched": True,
                "customer_id": customer_id,
                "confidence": 1.0,
                "method": "phone_hash",
            }

        return {"import_id": import_id, "matched": False, "reason": "phone_hash_not_found"}

    async def batch_resolve(
        self,
        tenant_id: str,
        db: AsyncSession,
        source: str = "wifi",
    ) -> dict[str, Any]:
        """批量解析所有未匹配记录"""
        resolved = 0
        failed = 0

        if source == "wifi":
            rows = await db.execute(
                text("""
                    SELECT id FROM wifi_visit_logs
                    WHERE tenant_id = :tid
                      AND matched_customer_id IS NULL
                      AND is_deleted = false
                    ORDER BY created_at DESC
                    LIMIT 1000
                """),
                {"tid": tenant_id},
            )
            ids = [str(r["id"]) for r in rows.mappings().all()]
            for vid in ids:
                try:
                    result = await self.resolve_wifi_visit(tenant_id, vid, db)
                    if result.get("matched") or result.get("already_matched"):
                        resolved += 1
                    else:
                        failed += 1
                except (ValueError, RuntimeError) as exc:
                    logger.warning("identity.batch_wifi_error", visit_id=vid, error=str(exc))
                    failed += 1

        elif source == "external":
            rows = await db.execute(
                text("""
                    SELECT id FROM external_order_imports
                    WHERE tenant_id = :tid
                      AND matched_customer_id IS NULL
                      AND is_deleted = false
                    ORDER BY created_at DESC
                    LIMIT 1000
                """),
                {"tid": tenant_id},
            )
            ids = [str(r["id"]) for r in rows.mappings().all()]
            for iid in ids:
                try:
                    result = await self.resolve_external_order(tenant_id, iid, db)
                    if result.get("matched") or result.get("already_matched"):
                        resolved += 1
                    else:
                        failed += 1
                except (ValueError, RuntimeError) as exc:
                    logger.warning("identity.batch_ext_error", import_id=iid, error=str(exc))
                    failed += 1

        logger.info(
            "identity.batch_resolve_done",
            tenant_id=tenant_id,
            source=source,
            resolved=resolved,
            failed=failed,
        )
        return {"source": source, "resolved": resolved, "unmatched": failed, "total": resolved + failed}

    async def get_coverage_stats(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """各数据源的身份匹配率统计"""
        # WiFi 匹配率
        wifi = await db.execute(
            text("""
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE matched_customer_id IS NOT NULL)::int AS matched
                FROM wifi_visit_logs
                WHERE tenant_id = :tid AND is_deleted = false
            """),
            {"tid": tenant_id},
        )
        w = wifi.mappings().first()
        wifi_total = w["total"] if w else 0
        wifi_matched = w["matched"] if w else 0

        # 外部订单按 source 分组
        ext = await db.execute(
            text("""
                SELECT source,
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE matched_customer_id IS NOT NULL)::int AS matched
                FROM external_order_imports
                WHERE tenant_id = :tid AND is_deleted = false
                GROUP BY source
            """),
            {"tid": tenant_id},
        )
        ext_rows = ext.mappings().all()

        sources: dict[str, Any] = {
            "wifi": {
                "total": wifi_total,
                "matched": wifi_matched,
                "match_rate": round(wifi_matched / max(wifi_total, 1) * 100, 1),
            },
        }
        for r in ext_rows:
            sources[r["source"]] = {
                "total": r["total"],
                "matched": r["matched"],
                "match_rate": round(r["matched"] / max(r["total"], 1) * 100, 1),
            }

        return sources

    # ──────────────────────────────────────────────────────────────────────────
    # UnionID 批量补全（MU-1, Task 3.1）
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_wechat_access_token_sync(app_id: str, app_secret: str, tenant_id: str) -> str:
        """从缓存或微信 API 获取 access_token。

        token 有效期 7200 秒，缓存层提前 300 秒刷新。
        返回 None 表示获取失败。
        """
        # 检查缓存
        cached = _ACCESS_TOKEN_CACHE.get(tenant_id)
        if cached:
            token, expires_at = cached
            if time.time() < expires_at - TOKEN_EXPIRE_BUFFER:
                return token

        # 请求新 token
        url = "https://api.weixin.qq.com/cgi-bin/token"
        params = {
            "grant_type": "client_credential",
            "appid": app_id,
            "secret": app_secret,
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.error("wechat.token_http_error", tenant_id=tenant_id, error=str(exc))
            raise RuntimeError(f"微信 Token 请求失败: {exc}") from exc

        if "errcode" in data and data["errcode"] != 0:
            logger.error(
                "wechat.token_api_error",
                tenant_id=tenant_id,
                errcode=data.get("errcode"),
                errmsg=data.get("errmsg"),
            )
            raise RuntimeError(f"微信 Token API 错误: {data.get('errmsg', 'unknown')}")

        token = data.get("access_token", "")
        expires_in = data.get("expires_in", 7200)
        _ACCESS_TOKEN_CACHE[tenant_id] = (token, time.time() + expires_in)
        logger.info("wechat.access_token_refreshed", tenant_id=tenant_id, expires_in=expires_in)
        return token

    @staticmethod
    async def _fetch_union_id(access_token: str, openid: str) -> Optional[str]:
        """通过微信 API 根据 openid 获取 union_id。

        使用 httpx.AsyncClient 异步调用。
        注意：该接口需要用户已关注公众号或已授权 scope=snsapi_userinfo。
        对于未授权的用户返回 None（不发异常）。
        """
        url = "https://api.weixin.qq.com/sns/userinfo"
        params = {
            "access_token": access_token,
            "openid": openid,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("wechat.userinfo_http_error", openid=openid[:10], error=str(exc))
            return None

        if "errcode" in data and data["errcode"] != 0:
            # 40003=invalid openid, 42001=token expired — 不抛异常，仅记录
            logger.warning(
                "wechat.userinfo_api_error",
                openid=openid[:10],
                errcode=data.get("errcode"),
                errmsg=data.get("errmsg"),
            )
            return None

        union_id = data.get("unionid")
        if not union_id:
            logger.info(
                "wechat.no_unionid",
                openid=openid[:10],
                subscribe=data.get("subscribe", 0),
            )
            return None

        return union_id

    async def backfill_union_id(self, tenant_id: str, db: AsyncSession) -> BackfillReport:
        """存量 UnionID 批量补全。

        查询所有有 wechat_openid 但 wechat_unionid 为 NULL 的会员，
        调用微信 API 获取 union_id 并更新 Customer 表。

        分页处理，每页 BACKFILL_PAGE_SIZE=100 条。
        单条失败不影响整体（记录错误日志后继续）。
        """
        if not WECHAT_APP_ID or not WECHAT_APP_SECRET:
            logger.error(
                "backfill.missing_wechat_config",
                tenant_id=tenant_id,
                msg="WECHAT_APP_ID 或 WECHAT_APP_SECRET 未配置",
            )
            return BackfillReport(total=0, succeeded=0, failed=0, errors=[{"error": "微信配置缺失"}])

        # 查询总待处理数
        count_result = await db.execute(
            text("""
                SELECT COUNT(*)::int AS total
                FROM customers
                WHERE tenant_id = :tid
                  AND wechat_openid IS NOT NULL
                  AND wechat_unionid IS NULL
                  AND is_deleted = false
            """),
            {"tid": tenant_id},
        )
        total = count_result.scalar() or 0
        if total == 0:
            logger.info("backfill.no_pending", tenant_id=tenant_id)
            return BackfillReport(total=0, succeeded=0, failed=0)

        logger.info("backfill.start", tenant_id=tenant_id, total=total)

        report = BackfillReport(total=total)
        page = 1

        while True:
            offset = (page - 1) * BACKFILL_PAGE_SIZE

            rows = await db.execute(
                text("""
                    SELECT id, wechat_openid
                    FROM customers
                    WHERE tenant_id = :tid
                      AND wechat_openid IS NOT NULL
                      AND wechat_unionid IS NULL
                      AND is_deleted = false
                    ORDER BY id
                    LIMIT :limit OFFSET :offset
                """),
                {"tid": tenant_id, "limit": BACKFILL_PAGE_SIZE, "offset": offset},
            )
            customers = rows.mappings().all()
            if not customers:
                break

            # 每页获取一次 access_token（缓存命中则不实际请求微信）
            try:
                access_token = self._get_wechat_access_token_sync(
                    WECHAT_APP_ID, WECHAT_APP_SECRET, tenant_id
                )
            except RuntimeError as exc:
                # token 获取失败，整页跳过
                for cust in customers:
                    report.failed += 1
                    report.errors.append({
                        "openid": str(cust["wechat_openid"])[:20],
                        "error": f"access_token获取失败: {exc}",
                    })
                page += 1
                continue

            for cust in customers:
                customer_id = str(cust["id"])
                openid = str(cust["wechat_openid"])

                try:
                    union_id = await self._fetch_union_id(access_token, openid)
                    if union_id:
                        await db.execute(
                            text("""
                                UPDATE customers
                                SET wechat_unionid = :unionid,
                                    updated_at = NOW()
                                WHERE id = :cid AND tenant_id = :tid
                            """),
                            {"unionid": union_id, "cid": customer_id, "tid": tenant_id},
                        )
                        await db.commit()

                        report.succeeded += 1

                        # 事件总线记录
                        asyncio.create_task(
                            emit_event(
                                event_type=MemberEventType.UNIONID_BACKFILLED,
                                tenant_id=tenant_id,
                                stream_id=customer_id,
                                payload={
                                    "openid": openid,
                                    "unionid": union_id,
                                    "source": "backfill",
                                },
                                source_service="tx-member",
                            )
                        )

                        logger.info(
                            "backfill.succeeded",
                            tenant_id=tenant_id,
                            customer_id=customer_id,
                            openid=openid[:10],
                        )
                    else:
                        report.failed += 1
                        report.errors.append({
                            "openid": openid[:20],
                            "error": "微信API未返回union_id（可能用户未关注/未授权）",
                        })
                except (OSError, RuntimeError, ValueError) as exc:
                    await db.rollback()
                    report.failed += 1
                    report.errors.append({"openid": openid[:20], "error": str(exc)})
                    logger.warning(
                        "backfill.failed",
                        tenant_id=tenant_id,
                        customer_id=customer_id,
                        error=str(exc),
                    )

            page += 1

        logger.info(
            "backfill.done",
            tenant_id=tenant_id,
            total=report.total,
            succeeded=report.succeeded,
            failed=report.failed,
        )
        return report

    async def merge_cross_brand_by_unionid(
        self, tenant_id: str, db: AsyncSession
    ) -> dict[str, Any]:
        """基于 UnionID 自动合并跨品牌会员。

        逻辑：
        1. 查询有 wechat_unionid 且 is_merged=false 的 Customer 记录
        2. 按 unionid 分组，每组内的多条记录属于同一自然人在不同品牌
        3. 保留最早创建的记录为主记录（主记录 is_merged=false）
        4. 其余记录设 is_merged=true, merged_into=主记录ID
        5. 使用 golden_id_merge_logs 记录合并操作
        """
        # 查找所有有 unionid 的 customer（按 unionid 分组，count>1 的才需要合并）
        rows = await db.execute(
            text("""
                SELECT id, wechat_unionid, created_at
                FROM customers
                WHERE tenant_id = :tid
                  AND wechat_unionid IS NOT NULL
                  AND is_merged = false
                  AND is_deleted = false
                ORDER BY wechat_unionid, created_at ASC
            """),
            {"tid": tenant_id},
        )
        all_customers = rows.mappings().all()

        # 按 unionid 分组
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in all_customers:
            unionid = row["wechat_unionid"]
            if unionid not in groups:
                groups[unionid] = []
            groups[unionid].append(row)

        # 筛选出需要合并的分组（同一 unionid 有 >1 条记录）
        mergeable_groups = {uid: members for uid, members in groups.items() if len(members) > 1}

        total_merged = 0
        total_skipped = 0
        merged_details: list[dict[str, Any]] = []

        for unionid, members in mergeable_groups.items():
            # 按 created_at 升序，第一条为主记录
            members.sort(key=lambda m: m["created_at"] or "")
            primary = members[0]
            primary_id = str(primary["id"])

            # 合并其他记录到主记录
            for secondary in members[1:]:
                secondary_id = str(secondary["id"])
                try:
                    await db.execute(
                        text("""
                            UPDATE customers
                            SET is_merged = true,
                                merged_into = :primary_id,
                                updated_at = NOW()
                            WHERE id = :secondary_id
                              AND tenant_id = :tid
                              AND is_deleted = false
                        """),
                        {
                            "primary_id": primary_id,
                            "secondary_id": secondary_id,
                            "tid": tenant_id,
                        },
                    )

                    # 写入合并日志
                    await db.execute(
                        text("""
                            INSERT INTO golden_id_merge_logs
                                (tenant_id, source_customer_id, target_customer_id,
                                 merge_reason, merge_metadata, created_at, updated_at)
                            VALUES
                                (:tid, :source, :target, 'unionid_auto_merge',
                                 :metadata::jsonb, NOW(), NOW())
                        """),
                        {
                            "tid": tenant_id,
                            "source": secondary_id,
                            "target": primary_id,
                            "metadata": f'{{"wechat_unionid": "{unionid}", "method": "auto"}}',
                        },
                    )

                    await db.commit()

                    total_merged += 1
                    merged_details.append({
                        "unionid": unionid,
                        "primary": primary_id,
                        "merged": secondary_id,
                    })

                    # 事件总线记录
                    asyncio.create_task(
                        emit_event(
                            event_type=MemberEventType.GOLDEN_ID_MERGED_BY_UNIONID,
                            tenant_id=tenant_id,
                            stream_id=secondary_id,
                            payload={
                                "unionid": unionid,
                                "primary_customer_id": primary_id,
                                "secondary_customer_id": secondary_id,
                            },
                            source_service="tx-member",
                        )
                    )

                    logger.info(
                        "merge_by_unionid.executed",
                        tenant_id=tenant_id,
                        unionid=unionid[:10],
                        primary=primary_id,
                        merged=secondary_id,
                    )

                except (OSError, RuntimeError, ValueError) as exc:
                    await db.rollback()
                    total_skipped += 1
                    logger.warning(
                        "merge_by_unionid.failed",
                        tenant_id=tenant_id,
                        unionid=unionid[:10],
                        secondary=secondary_id,
                        error=str(exc),
                    )

        logger.info(
            "merge_by_unionid.done",
            tenant_id=tenant_id,
            groups=len(mergeable_groups),
            merged=total_merged,
            skipped=total_skipped,
        )
        return {
            "groups_found": len(mergeable_groups),
            "total_merged": total_merged,
            "total_skipped": total_skipped,
            "details": merged_details,
        }

    async def _update_wifi_match(
        self,
        db: AsyncSession,
        visit_id: str,
        customer_id: str,
        confidence: float,
        method: str,
    ) -> None:
        await db.execute(
            text("""
                UPDATE wifi_visit_logs
                SET matched_customer_id = :cid,
                    match_confidence = :conf,
                    match_method = :method,
                    is_new_visitor = false,
                    updated_at = NOW()
                WHERE id = :vid
            """),
            {"cid": customer_id, "conf": confidence, "method": method, "vid": visit_id},
        )
        await db.commit()
