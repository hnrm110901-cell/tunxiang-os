"""GDPR 合规服务 — 数据主体删除/被遗忘权/数据可携权（v103）

核心功能：
  1. create_request: 接收数据主体权利申请（erasure/portability/restriction）
  2. review_request: 人工审核（批准/拒绝）
  3. execute_erasure: 执行匿名化（在 customers 表脱敏 PII，不物理删除）
  4. export_customer_data: 数据可携性导出（返回该客户全部数据 JSON）
  5. list_requests: 查询请求列表

匿名化策略（符合 GDPR Art.17 & 国标 GB/T 35273）：
  - name → "已删除用户_{customer_id[:8]}"
  - phone → NULL
  - email → NULL
  - wechat_openid → NULL（保留 encrypted 哈希但设为 NULL）
  - birth_date → NULL
  - gender → NULL
  不删除：orders（脱敏后保留用于统计）、消费记录（仅保留金额）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

REQUEST_TYPES = ("erasure", "portability", "restriction")
STATUSES = ("pending", "reviewing", "executed", "rejected")

# customers 表 PII 字段匿名化映射
_ANONYMIZE_FIELDS: Dict[str, Any] = {
    "phone": None,
    "email": None,
    "wechat_openid": None,
    "name": "__ANON__",  # 特殊处理：拼接 customer_id 前缀
    "birth_date": None,
    "gender": None,
    "avatar_url": None,
}


class GDPRService:
    """GDPR 请求管理 + PII 匿名化"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════
    # 请求管理
    # ══════════════════════════════════════════════════════

    async def create_request(
        self,
        customer_id: str,
        request_type: str,
        requested_by: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """提交 GDPR 权利申请"""
        await self._set_tenant()
        if request_type not in REQUEST_TYPES:
            raise ValueError(f"request_type 必须是: {', '.join(REQUEST_TYPES)}")

        # 检查是否有同类型 pending/reviewing 请求
        existing = await self.db.execute(
            text("""
                SELECT id FROM gdpr_requests
                WHERE tenant_id = :tid AND customer_id = :cid
                  AND request_type = :rtype
                  AND status IN ('pending','reviewing')
            """),
            {"tid": self._tid, "cid": uuid.UUID(customer_id), "rtype": request_type},
        )
        if existing.fetchone():
            raise ValueError(f"该客户已有进行中的 {request_type} 申请，请等待处理完成")

        req_id = uuid.uuid4()
        await self.db.execute(
            text("""
                INSERT INTO gdpr_requests
                    (id, tenant_id, customer_id, request_type, status,
                     requested_by, note)
                VALUES
                    (:id, :tid, :cid, :rtype, 'pending',
                     :by, :note)
            """),
            {
                "id": req_id,
                "tid": self._tid,
                "cid": uuid.UUID(customer_id),
                "rtype": request_type,
                "by": requested_by,
                "note": note,
            },
        )
        await self.db.flush()
        log.info(
            "gdpr_request_created",
            request_id=str(req_id),
            customer_id=customer_id,
            request_type=request_type,
            tenant_id=self.tenant_id,
        )
        return await self.get_request(str(req_id))  # type: ignore[return-value]

    async def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """查询单条请求"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, customer_id, request_type, status,
                       requested_by, requested_at,
                       reviewed_by, reviewed_at,
                       executed_by, executed_at,
                       rejection_reason, anonymization_log,
                       export_data_url, note, created_at, updated_at
                FROM gdpr_requests
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(request_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._request_row(row) if row else None

    async def list_requests(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
        request_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询请求列表"""
        await self._set_tenant()
        sql = """
            SELECT id, customer_id, request_type, status,
                   requested_by, requested_at,
                   reviewed_by, reviewed_at,
                   executed_by, executed_at,
                   rejection_reason, anonymization_log,
                   export_data_url, note, created_at, updated_at
            FROM gdpr_requests
            WHERE tenant_id = :tid
        """
        params: Dict[str, Any] = {"tid": self._tid}
        if customer_id:
            sql += " AND customer_id = :cid"
            params["cid"] = uuid.UUID(customer_id)
        if status:
            sql += " AND status = :status"
            params["status"] = status
        if request_type:
            sql += " AND request_type = :rtype"
            params["rtype"] = request_type
        sql += " ORDER BY created_at DESC"

        result = await self.db.execute(text(sql), params)
        return [self._request_row(r) for r in result.fetchall()]

    async def review_request(
        self,
        request_id: str,
        approved: bool,
        reviewed_by: str,
        rejection_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """人工审核：批准（→reviewing）或拒绝（→rejected）"""
        await self._set_tenant()
        req = await self.get_request(request_id)
        if not req:
            raise ValueError(f"GDPR 请求 {request_id} 不存在")
        if req["status"] != "pending":
            raise ValueError(f"只有 pending 状态可审核，当前: {req['status']}")

        now = datetime.now(timezone.utc)
        if approved:
            new_status = "reviewing"
            await self.db.execute(
                text("""
                    UPDATE gdpr_requests
                    SET status = 'reviewing', reviewed_by = :by,
                        reviewed_at = :now, updated_at = :now
                    WHERE id = :id AND tenant_id = :tid
                """),
                {"by": uuid.UUID(reviewed_by), "now": now, "id": uuid.UUID(request_id), "tid": self._tid},
            )
        else:
            new_status = "rejected"
            await self.db.execute(
                text("""
                    UPDATE gdpr_requests
                    SET status = 'rejected', reviewed_by = :by,
                        reviewed_at = :now, rejection_reason = :reason,
                        updated_at = :now
                    WHERE id = :id AND tenant_id = :tid
                """),
                {
                    "by": uuid.UUID(reviewed_by),
                    "now": now,
                    "reason": rejection_reason,
                    "id": uuid.UUID(request_id),
                    "tid": self._tid,
                },
            )

        await self.db.flush()
        log.info("gdpr_request_reviewed", request_id=request_id, new_status=new_status, tenant_id=self.tenant_id)
        return await self.get_request(request_id)  # type: ignore[return-value]

    # ══════════════════════════════════════════════════════
    # 被遗忘权执行
    # ══════════════════════════════════════════════════════

    async def execute_erasure(self, request_id: str, executed_by: str) -> Dict[str, Any]:
        """执行匿名化：脱敏 customers 表 PII 字段"""
        await self._set_tenant()
        req = await self.get_request(request_id)
        if not req:
            raise ValueError(f"GDPR 请求 {request_id} 不存在")
        if req["status"] != "reviewing":
            raise ValueError(f"只有 reviewing 状态可执行，当前: {req['status']}")
        if req["request_type"] != "erasure":
            raise ValueError(f"此接口只处理 erasure 类型，当前: {req['request_type']}")

        customer_id = req["customer_id"]
        cid = uuid.UUID(customer_id)
        now = datetime.now(timezone.utc)
        anon_name = f"已删除用户_{customer_id[:8]}"

        # 执行匿名化
        result = await self.db.execute(
            text("""
                UPDATE customers
                SET name          = :anon_name,
                    phone         = NULL,
                    email         = NULL,
                    wechat_openid = NULL,
                    birth_date    = NULL,
                    gender        = NULL,
                    avatar_url    = NULL,
                    updated_at    = :now
                WHERE id = :cid AND tenant_id = :tid
            """),
            {"anon_name": anon_name, "now": now, "cid": cid, "tid": self._tid},
        )
        affected = result.rowcount

        anonymization_log = {
            "executed_at": now.isoformat(),
            "executed_by": executed_by,
            "customer_id": customer_id,
            "fields_anonymized": list(_ANONYMIZE_FIELDS.keys()),
            "rows_affected": affected,
            "strategy": "in_place_nullify",
        }

        await self.db.execute(
            text("""
                UPDATE gdpr_requests
                SET status = 'executed', executed_by = :by,
                    executed_at = :now,
                    anonymization_log = :log::jsonb,
                    updated_at = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {
                "by": uuid.UUID(executed_by),
                "now": now,
                "log": json.dumps(anonymization_log),
                "id": uuid.UUID(request_id),
                "tid": self._tid,
            },
        )
        await self.db.flush()
        log.info(
            "gdpr_erasure_executed",
            request_id=request_id,
            customer_id=customer_id,
            rows_affected=affected,
            tenant_id=self.tenant_id,
        )
        return await self.get_request(request_id)  # type: ignore[return-value]

    # ══════════════════════════════════════════════════════
    # 数据可携性导出
    # ══════════════════════════════════════════════════════

    async def export_customer_data(self, customer_id: str) -> Dict[str, Any]:
        """导出客户全部数据（数据可携性 Art.20）"""
        await self._set_tenant()
        cid = uuid.UUID(customer_id)

        # 基本信息
        cust_result = await self.db.execute(
            text("""
                SELECT id, name, phone, email, gender, birth_date,
                       created_at, updated_at
                FROM customers
                WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": cid, "tid": self._tid},
        )
        cust = cust_result.fetchone()
        if not cust:
            raise ValueError(f"客户 {customer_id} 不存在")

        # 消费历史（订单摘要）
        orders_result = await self.db.execute(
            text("""
                SELECT id, store_id, total_amount_fen, status, created_at
                FROM orders
                WHERE customer_id = :cid AND tenant_id = :tid
                ORDER BY created_at DESC
                LIMIT 1000
            """),
            {"cid": cid, "tid": self._tid},
        )
        orders = [
            {
                "order_id": str(r.id),
                "store_id": str(r.store_id),
                "total_amount_fen": r.total_amount_fen,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in orders_result.fetchall()
        ]

        return {
            "customer_id": customer_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "profile": {
                "name": cust.name,
                "phone": cust.phone,
                "email": cust.email,
                "gender": cust.gender,
                "birth_date": str(cust.birth_date) if cust.birth_date else None,
                "member_since": cust.created_at.isoformat() if cust.created_at else None,
            },
            "orders": orders,
            "order_count": len(orders),
            "notice": "本数据导出依据 GDPR Art.20 数据可携权，仅供数据主体本人使用",
        }

    # ══════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════

    def _request_row(self, row) -> Dict[str, Any]:
        def _json(v):
            if v is None:
                return None
            return v if isinstance(v, dict) else json.loads(v)

        return {
            "request_id": str(row.id),
            "tenant_id": self.tenant_id,
            "customer_id": str(row.customer_id),
            "request_type": row.request_type,
            "status": row.status,
            "requested_by": row.requested_by,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "executed_by": str(row.executed_by) if row.executed_by else None,
            "executed_at": row.executed_at.isoformat() if row.executed_at else None,
            "rejection_reason": row.rejection_reason,
            "anonymization_log": _json(row.anonymization_log),
            "export_data_url": row.export_data_url,
            "note": getattr(row, "note", None),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
