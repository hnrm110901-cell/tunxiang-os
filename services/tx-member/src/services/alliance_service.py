"""跨品牌联盟忠诚度引擎 -- 合作伙伴管理/积分兑换/优惠券兑换/联盟仪表盘

多租户 RLS 隔离，structlog 日志。积分为整数，不支持小数。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ── 自定义异常 ──────────────────────────────────────────────────


class AllianceServiceError(Exception):
    """联盟服务业务异常"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ── 工具函数 ──────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── AllianceService ─────────────────────────────────────────────


class AllianceService:
    """跨品牌联盟忠诚度服务"""

    # ── 合作伙伴 CRUD ──────────────────────────────────────────

    async def create_partner(
        self,
        tenant_id: str,
        partner_data: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """创建联盟合作伙伴"""
        await _set_tenant(db, tenant_id)

        partner_id = str(uuid.uuid4())
        now = _now_utc()

        await db.execute(
            text("""
                INSERT INTO alliance_partners
                    (id, tenant_id, partner_name, partner_type,
                     partner_brand_logo, contact_name, contact_phone, contact_email,
                     api_endpoint, api_key_encrypted,
                     exchange_rate_out, exchange_rate_in, daily_exchange_limit,
                     status, contract_start, contract_end, terms_summary,
                     created_at, updated_at)
                VALUES
                    (:id, :tid, :partner_name, :partner_type,
                     :partner_brand_logo, :contact_name, :contact_phone, :contact_email,
                     :api_endpoint, :api_key_encrypted,
                     :exchange_rate_out, :exchange_rate_in, :daily_exchange_limit,
                     'pending', :contract_start, :contract_end, :terms_summary,
                     :now, :now)
            """),
            {
                "id": partner_id,
                "tid": tenant_id,
                "partner_name": partner_data["partner_name"],
                "partner_type": partner_data["partner_type"],
                "partner_brand_logo": partner_data.get("partner_brand_logo"),
                "contact_name": partner_data.get("contact_name"),
                "contact_phone": partner_data.get("contact_phone"),
                "contact_email": partner_data.get("contact_email"),
                "api_endpoint": partner_data.get("api_endpoint"),
                "api_key_encrypted": partner_data.get("api_key_encrypted"),
                "exchange_rate_out": partner_data.get("exchange_rate_out", 1.0),
                "exchange_rate_in": partner_data.get("exchange_rate_in", 1.0),
                "daily_exchange_limit": partner_data.get("daily_exchange_limit", 1000),
                "contract_start": partner_data.get("contract_start"),
                "contract_end": partner_data.get("contract_end"),
                "terms_summary": partner_data.get("terms_summary"),
                "now": now,
            },
        )

        logger.info(
            "alliance_partner_created",
            tenant_id=tenant_id,
            partner_id=partner_id,
            partner_name=partner_data["partner_name"],
        )

        return {
            "id": partner_id,
            "tenant_id": tenant_id,
            "partner_name": partner_data["partner_name"],
            "partner_type": partner_data["partner_type"],
            "status": "pending",
            "created_at": now.isoformat(),
        }

    async def update_partner(
        self,
        tenant_id: str,
        partner_id: str,
        update_data: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """更新联盟合作伙伴信息"""
        await _set_tenant(db, tenant_id)

        # 检查伙伴是否存在
        result = await db.execute(
            text("""
                SELECT id, status FROM alliance_partners
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id},
        )
        row = result.mappings().first()
        if not row:
            raise AllianceServiceError("partner_not_found", f"合作伙伴 {partner_id} 不存在")

        # 构建动态 UPDATE 字段
        allowed_fields = [
            "partner_name", "partner_type", "partner_brand_logo",
            "contact_name", "contact_phone", "contact_email",
            "api_endpoint", "api_key_encrypted",
            "exchange_rate_out", "exchange_rate_in", "daily_exchange_limit",
            "contract_start", "contract_end", "terms_summary",
        ]
        set_clauses = []
        params: dict[str, Any] = {"pid": partner_id, "tid": tenant_id, "now": _now_utc()}

        for field in allowed_fields:
            if field in update_data:
                set_clauses.append(f"{field} = :{field}")
                params[field] = update_data[field]

        if not set_clauses:
            raise AllianceServiceError("no_fields", "没有可更新的字段")

        set_clauses.append("updated_at = :now")
        set_sql = ", ".join(set_clauses)

        await db.execute(
            text(f"""
                UPDATE alliance_partners SET {set_sql}
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            params,
        )

        logger.info(
            "alliance_partner_updated",
            tenant_id=tenant_id,
            partner_id=partner_id,
            fields=list(update_data.keys()),
        )

        return {"id": partner_id, "updated": True}

    async def activate_partner(
        self,
        tenant_id: str,
        partner_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """激活合作伙伴"""
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT id, status FROM alliance_partners
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id},
        )
        row = result.mappings().first()
        if not row:
            raise AllianceServiceError("partner_not_found", f"合作伙伴 {partner_id} 不存在")
        if row["status"] == "terminated":
            raise AllianceServiceError("partner_terminated", "已终止的合作伙伴不可激活")

        await db.execute(
            text("""
                UPDATE alliance_partners
                SET status = 'active', updated_at = :now
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id, "now": _now_utc()},
        )

        logger.info("alliance_partner_activated", tenant_id=tenant_id, partner_id=partner_id)
        return {"id": partner_id, "status": "active"}

    async def suspend_partner(
        self,
        tenant_id: str,
        partner_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """暂停合作伙伴"""
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT id, status FROM alliance_partners
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id},
        )
        row = result.mappings().first()
        if not row:
            raise AllianceServiceError("partner_not_found", f"合作伙伴 {partner_id} 不存在")
        if row["status"] != "active":
            raise AllianceServiceError("partner_not_active", "只能暂停活跃状态的合作伙伴")

        await db.execute(
            text("""
                UPDATE alliance_partners
                SET status = 'suspended', updated_at = :now
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id, "now": _now_utc()},
        )

        logger.info("alliance_partner_suspended", tenant_id=tenant_id, partner_id=partner_id)
        return {"id": partner_id, "status": "suspended"}

    # ── 积分兑换 ──────────────────────────────────────────────

    async def _check_daily_limit(
        self,
        tenant_id: str,
        partner_id: str,
        points_amount: int,
        db: AsyncSession,
    ) -> int:
        """检查每日兑换限额，返回 daily_exchange_limit"""
        result = await db.execute(
            text("""
                SELECT daily_exchange_limit FROM alliance_partners
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id},
        )
        row = result.mappings().first()
        if not row:
            raise AllianceServiceError("partner_not_found", f"合作伙伴 {partner_id} 不存在")

        daily_limit = row["daily_exchange_limit"]

        # 查询今日已兑换总量
        result = await db.execute(
            text("""
                SELECT COALESCE(SUM(points_amount), 0) AS today_total
                FROM alliance_transactions
                WHERE partner_id = :pid AND tenant_id = :tid
                  AND status IN ('pending', 'completed')
                  AND created_at::date = CURRENT_DATE
                  AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id},
        )
        today_row = result.mappings().first()
        today_total = today_row["today_total"] if today_row else 0

        if today_total + points_amount > daily_limit:
            raise AllianceServiceError(
                "daily_limit_exceeded",
                f"每日兑换限额 {daily_limit}，今日已兑换 {today_total}，"
                f"本次请求 {points_amount} 超出限额",
            )

        return daily_limit

    async def exchange_points_out(
        self,
        tenant_id: str,
        customer_id: str,
        partner_id: str,
        points_amount: int,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """积分外兑：扣减我方客户积分，兑换为合作方积分

        Args:
            points_amount: 我方积分数量
        """
        await _set_tenant(db, tenant_id)

        # 检查合作伙伴状态
        result = await db.execute(
            text("""
                SELECT id, status, exchange_rate_out, partner_name
                FROM alliance_partners
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id},
        )
        partner = result.mappings().first()
        if not partner:
            raise AllianceServiceError("partner_not_found", f"合作伙伴 {partner_id} 不存在")
        if partner["status"] != "active":
            raise AllianceServiceError("partner_not_active", "合作伙伴未激活，无法兑换")

        # 检查每日限额
        await self._check_daily_limit(tenant_id, partner_id, points_amount, db)

        # 计算兑换后积分
        exchange_rate = partner["exchange_rate_out"]
        converted_points = int(points_amount * exchange_rate)

        # 扣减客户积分（检查余额，FOR UPDATE 防止并发扣减导致负余额）
        result = await db.execute(
            text("""
                SELECT COALESCE(SUM(CASE WHEN type = 'earn' THEN points ELSE -points END), 0) AS balance
                FROM points_ledger
                WHERE customer_id = :cid AND tenant_id = :tid AND is_deleted = false
                FOR UPDATE
            """),
            {"cid": customer_id, "tid": tenant_id},
        )
        balance_row = result.mappings().first()
        current_balance = balance_row["balance"] if balance_row else 0

        if current_balance < points_amount:
            raise AllianceServiceError(
                "insufficient_points",
                f"积分余额不足：当前 {current_balance}，需要 {points_amount}",
            )

        # 记录积分扣减
        ledger_id = str(uuid.uuid4())
        now = _now_utc()
        await db.execute(
            text("""
                INSERT INTO points_ledger
                    (id, tenant_id, customer_id, type, points, source, memo, created_at)
                VALUES
                    (:id, :tid, :cid, 'spend', :pts, 'alliance_exchange_out',
                     :memo, :now)
            """),
            {
                "id": ledger_id,
                "tid": tenant_id,
                "cid": customer_id,
                "pts": points_amount,
                "memo": f"联盟兑出至{partner['partner_name']}",
                "now": now,
            },
        )

        # 创建兑换交易记录
        tx_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO alliance_transactions
                    (id, tenant_id, partner_id, customer_id, direction,
                     points_amount, converted_points, exchange_rate,
                     status, completed_at, created_at, updated_at)
                VALUES
                    (:id, :tid, :pid, :cid, 'outbound',
                     :pts, :converted, :rate,
                     'completed', :now, :now, :now)
            """),
            {
                "id": tx_id,
                "tid": tenant_id,
                "pid": partner_id,
                "cid": customer_id,
                "pts": points_amount,
                "converted": converted_points,
                "rate": exchange_rate,
                "now": now,
            },
        )

        # 更新合作伙伴累计兑出
        await db.execute(
            text("""
                UPDATE alliance_partners
                SET total_points_exchanged_out = total_points_exchanged_out + :pts,
                    updated_at = :now
                WHERE id = :pid AND tenant_id = :tid
            """),
            {"pid": partner_id, "tid": tenant_id, "pts": points_amount, "now": now},
        )

        logger.info(
            "alliance_exchange_out",
            tenant_id=tenant_id,
            customer_id=customer_id,
            partner_id=partner_id,
            points=points_amount,
            converted=converted_points,
        )

        return {
            "transaction_id": tx_id,
            "direction": "outbound",
            "points_amount": points_amount,
            "converted_points": converted_points,
            "exchange_rate": exchange_rate,
            "status": "completed",
        }

    async def exchange_points_in(
        self,
        tenant_id: str,
        customer_id: str,
        partner_id: str,
        external_points: int,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """积分内兑：合作方积分兑换为我方客户积分

        Args:
            external_points: 合作方积分数量
        """
        await _set_tenant(db, tenant_id)

        # 检查合作伙伴状态
        result = await db.execute(
            text("""
                SELECT id, status, exchange_rate_in, partner_name
                FROM alliance_partners
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id},
        )
        partner = result.mappings().first()
        if not partner:
            raise AllianceServiceError("partner_not_found", f"合作伙伴 {partner_id} 不存在")
        if partner["status"] != "active":
            raise AllianceServiceError("partner_not_active", "合作伙伴未激活，无法兑换")

        # 检查每日限额
        await self._check_daily_limit(tenant_id, partner_id, external_points, db)

        # 计算兑换后积分
        exchange_rate = partner["exchange_rate_in"]
        converted_points = int(external_points * exchange_rate)

        # 增加客户积分
        ledger_id = str(uuid.uuid4())
        now = _now_utc()
        await db.execute(
            text("""
                INSERT INTO points_ledger
                    (id, tenant_id, customer_id, type, points, source, memo, created_at)
                VALUES
                    (:id, :tid, :cid, 'earn', :pts, 'alliance_exchange_in',
                     :memo, :now)
            """),
            {
                "id": ledger_id,
                "tid": tenant_id,
                "cid": customer_id,
                "pts": converted_points,
                "memo": f"联盟兑入自{partner['partner_name']}",
                "now": now,
            },
        )

        # 创建兑换交易记录
        tx_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO alliance_transactions
                    (id, tenant_id, partner_id, customer_id, direction,
                     points_amount, converted_points, exchange_rate,
                     status, completed_at, created_at, updated_at)
                VALUES
                    (:id, :tid, :pid, :cid, 'inbound',
                     :pts, :converted, :rate,
                     'completed', :now, :now, :now)
            """),
            {
                "id": tx_id,
                "tid": tenant_id,
                "pid": partner_id,
                "cid": customer_id,
                "pts": external_points,
                "converted": converted_points,
                "rate": exchange_rate,
                "now": now,
            },
        )

        # 更新合作伙伴累计兑入
        await db.execute(
            text("""
                UPDATE alliance_partners
                SET total_points_exchanged_in = total_points_exchanged_in + :pts,
                    updated_at = :now
                WHERE id = :pid AND tenant_id = :tid
            """),
            {"pid": partner_id, "tid": tenant_id, "pts": external_points, "now": now},
        )

        logger.info(
            "alliance_exchange_in",
            tenant_id=tenant_id,
            customer_id=customer_id,
            partner_id=partner_id,
            external_points=external_points,
            converted=converted_points,
        )

        return {
            "transaction_id": tx_id,
            "direction": "inbound",
            "points_amount": external_points,
            "converted_points": converted_points,
            "exchange_rate": exchange_rate,
            "status": "completed",
        }

    async def exchange_for_coupon(
        self,
        tenant_id: str,
        customer_id: str,
        partner_id: str,
        coupon_template_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """合作方积分兑换我方优惠券"""
        await _set_tenant(db, tenant_id)

        # 检查合作伙伴
        result = await db.execute(
            text("""
                SELECT id, status, exchange_rate_in, partner_name
                FROM alliance_partners
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": partner_id, "tid": tenant_id},
        )
        partner = result.mappings().first()
        if not partner:
            raise AllianceServiceError("partner_not_found", f"合作伙伴 {partner_id} 不存在")
        if partner["status"] != "active":
            raise AllianceServiceError("partner_not_active", "合作伙伴未激活，无法兑换")

        # 查询优惠券模板
        result = await db.execute(
            text("""
                SELECT id, name, points_cost
                FROM coupon_templates
                WHERE id = :ctid AND tenant_id = :tid AND is_deleted = false
            """),
            {"ctid": coupon_template_id, "tid": tenant_id},
        )
        coupon_tpl = result.mappings().first()
        if not coupon_tpl:
            raise AllianceServiceError(
                "coupon_template_not_found",
                f"优惠券模板 {coupon_template_id} 不存在",
            )

        points_cost = coupon_tpl["points_cost"] or 0
        coupon_name = coupon_tpl["name"]

        # 创建兑换交易记录
        tx_id = str(uuid.uuid4())
        now = _now_utc()
        await db.execute(
            text("""
                INSERT INTO alliance_transactions
                    (id, tenant_id, partner_id, customer_id, direction,
                     points_amount, converted_points, exchange_rate,
                     coupon_id, coupon_name,
                     status, completed_at, created_at, updated_at)
                VALUES
                    (:id, :tid, :pid, :cid, 'inbound',
                     :pts, 0, :rate,
                     :coupon_id, :coupon_name,
                     'completed', :now, :now, :now)
            """),
            {
                "id": tx_id,
                "tid": tenant_id,
                "pid": partner_id,
                "cid": customer_id,
                "pts": points_cost,
                "rate": partner["exchange_rate_in"],
                "coupon_id": coupon_template_id,
                "coupon_name": coupon_name,
                "now": now,
            },
        )

        logger.info(
            "alliance_exchange_coupon",
            tenant_id=tenant_id,
            customer_id=customer_id,
            partner_id=partner_id,
            coupon_template_id=coupon_template_id,
        )

        return {
            "transaction_id": tx_id,
            "coupon_id": coupon_template_id,
            "coupon_name": coupon_name,
            "points_cost": points_cost,
            "status": "completed",
        }

    # ── 查询 ──────────────────────────────────────────────────

    async def get_partner_list(
        self,
        tenant_id: str,
        db: AsyncSession,
        status: Optional[str] = None,
        partner_type: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """获取合作伙伴列表（分页）"""
        await _set_tenant(db, tenant_id)

        where_clauses = ["tenant_id = :tid", "is_deleted = false"]
        params: dict[str, Any] = {"tid": tenant_id}

        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if partner_type:
            where_clauses.append("partner_type = :partner_type")
            params["partner_type"] = partner_type

        where_sql = " AND ".join(where_clauses)

        # 总数
        result = await db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM alliance_partners WHERE {where_sql}"),
            params,
        )
        total = result.mappings().first()["cnt"]

        # 分页数据
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await db.execute(
            text(f"""
                SELECT id, tenant_id, partner_name, partner_type,
                       partner_brand_logo, contact_name, contact_phone, contact_email,
                       exchange_rate_out, exchange_rate_in, daily_exchange_limit,
                       status, contract_start, contract_end,
                       total_points_exchanged_out, total_points_exchanged_in,
                       created_at, updated_at
                FROM alliance_partners
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()
        items = [dict(r) for r in rows]

        return {"items": items, "total": total}

    async def get_customer_transactions(
        self,
        tenant_id: str,
        customer_id: str,
        db: AsyncSession,
        partner_id: Optional[str] = None,
        direction: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """获取客户兑换交易列表（分页）"""
        await _set_tenant(db, tenant_id)

        where_clauses = ["t.tenant_id = :tid", "t.customer_id = :cid", "t.is_deleted = false"]
        params: dict[str, Any] = {"tid": tenant_id, "cid": customer_id}

        if partner_id:
            where_clauses.append("t.partner_id = :pid")
            params["pid"] = partner_id
        if direction:
            where_clauses.append("t.direction = :direction")
            params["direction"] = direction

        where_sql = " AND ".join(where_clauses)

        # 总数
        result = await db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM alliance_transactions t WHERE {where_sql}"),
            params,
        )
        total = result.mappings().first()["cnt"]

        # 分页数据
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await db.execute(
            text(f"""
                SELECT t.id, t.partner_id, t.customer_id, t.direction,
                       t.points_amount, t.converted_points, t.exchange_rate,
                       t.coupon_id, t.coupon_name, t.status, t.failure_reason,
                       t.partner_reference_id, t.completed_at, t.created_at,
                       p.partner_name
                FROM alliance_transactions t
                LEFT JOIN alliance_partners p ON p.id = t.partner_id
                WHERE {where_sql}
                ORDER BY t.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()
        items = [dict(r) for r in rows]

        return {"items": items, "total": total}

    async def get_alliance_dashboard(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """联盟仪表盘统计"""
        await _set_tenant(db, tenant_id)

        # 合作伙伴统计
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_partners,
                    COUNT(*) FILTER (WHERE status = 'active') AS active_partners,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending_partners,
                    COUNT(*) FILTER (WHERE status = 'suspended') AS suspended_partners,
                    COALESCE(SUM(total_points_exchanged_out), 0) AS total_points_out,
                    COALESCE(SUM(total_points_exchanged_in), 0) AS total_points_in
                FROM alliance_partners
                WHERE tenant_id = :tid AND is_deleted = false
            """),
            {"tid": tenant_id},
        )
        stats = dict(result.mappings().first())

        # 每个合作伙伴的兑换量排名
        result = await db.execute(
            text("""
                SELECT id, partner_name, partner_type, status,
                       total_points_exchanged_out, total_points_exchanged_in,
                       (total_points_exchanged_out + total_points_exchanged_in) AS total_volume
                FROM alliance_partners
                WHERE tenant_id = :tid AND is_deleted = false
                ORDER BY total_volume DESC
                LIMIT 10
            """),
            {"tid": tenant_id},
        )
        top_partners = [dict(r) for r in result.mappings().all()]

        # 最近30天交易趋势
        result = await db.execute(
            text("""
                SELECT
                    created_at::date AS tx_date,
                    direction,
                    COUNT(*) AS tx_count,
                    COALESCE(SUM(points_amount), 0) AS total_points
                FROM alliance_transactions
                WHERE tenant_id = :tid AND is_deleted = false
                  AND status = 'completed'
                  AND created_at >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY created_at::date, direction
                ORDER BY tx_date DESC
            """),
            {"tid": tenant_id},
        )
        trend = [dict(r) for r in result.mappings().all()]

        return {
            "total_partners": stats["total_partners"],
            "active_partners": stats["active_partners"],
            "pending_partners": stats["pending_partners"],
            "suspended_partners": stats["suspended_partners"],
            "total_points_out": stats["total_points_out"],
            "total_points_in": stats["total_points_in"],
            "top_partners": top_partners,
            "trend_30d": trend,
        }
