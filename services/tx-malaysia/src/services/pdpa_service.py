"""马来西亚 PDPA 数据保护服务 — Personal Data Protection Act 2010

核心功能：
  1. handle_data_subject_request — 数据主体权利处理（access/correction/deletion/portability）
  2. process_request — 审批/执行/拒绝 PDPA 请求
  3. get_encrypted_customer_profile — 获取解密后的客户全量画像（PDPA 查阅权）
  4. anonymize_customer — 匿名化客户 PII（PDPA 删除权，保留统计信息）
  5. export_customer_data — 数据可携带性导出 JSON（PDPA 可携带权）
  6. log_consent — 记录客户同意/撤回同意（PDPA opt-in 要求）
  7. check_data_retention — 检查过期数据（PDPA 存储限制原则）
  8. get_consent_history — 查询客户同意历史记录

PDPA 2010 关键原则：
  - 数据主体有权查阅、更正、删除其个人数据
  - 处理个人数据前必须获得明确同意（opt-in）
  - 业务目的达成后必须在合理期限内销毁数据
  - 个人数据不得跨境传输至未达同等保护水平的国家/地区

金额单位：分（fen），与全系统 Amount Convention 一致。

依赖：
  - FieldEncryptor: 敏感字段 AES-256-GCM 加密/解密
  - DataSovereigntyRouter: 数据主权路由与跨境传输校验
  - data_masking: 日志输出时自动脱敏
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.security.src.data_sovereignty import DataSovereigntyRouter
from shared.security.src.field_encryption import get_encryptor, is_encrypted
from shared.security.data_masking import mask_value

log = structlog.get_logger(__name__)

PDPA_REQUEST_TYPES = ("access", "correction", "deletion", "portability")
PDPA_STATUSES = ("pending", "processing", "completed", "rejected")

# customers 表 PII 字段匿名化映射
# value=None 表示 SET NULL；value="__ANON__" 表示拼接匿名前缀
_ANONYMIZE_FIELDS: Dict[str, Any] = {
    "primary_phone": None,
    "display_name": "__ANON__",
    "gender": None,
    "wechat_openid": None,
    "wechat_unionid": None,
    "wechat_nickname": None,
    "wechat_avatar_url": None,
    "meituan_user_id": None,
    "meituan_openid": None,
    "douyin_openid": None,
    "eleme_user_id": None,
    "wecom_external_userid": None,
    "wecom_follow_user": None,
    "wecom_follow_at": None,
    "wecom_remark": None,
}

# 匿名化后保留的统计字段（不擦除）
_RETAINED_FIELDS = [
    "total_order_count",
    "total_order_amount_fen",
    "total_reservation_count",
    "first_order_at",
    "last_order_at",
    "first_store_id",
    "rfm_recency_days",
    "rfm_frequency",
    "rfm_monetary_fen",
    "rfm_level",
    "r_score",
    "f_score",
    "m_score",
    "risk_score",
    "tags",
]


class PDPAService:
    """PDPA 数据保护服务

    用法:
        svc = PDPAService(db=db, tenant_id="...")
        req = await svc.handle_data_subject_request(
            customer_id="...", request_type="access"
        )
    """

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)
        self._encryptor = get_encryptor()
        self._sovereignty = DataSovereigntyRouter()

    async def _set_tenant(self) -> None:
        """设置 RLS 上下文（app.tenant_id）"""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════════════
    # 数据主体权利处理入口
    # ══════════════════════════════════════════════════════════════

    async def handle_data_subject_request(
        self,
        customer_id: str,
        request_type: str,
        requested_by: Optional[str] = None,
        notes: Optional[str] = None,
        request_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """PDPA 数据主体权利处理

        Args:
            customer_id: 客户 ID
            request_type: 请求类型
                - access:     查阅权，返回解密后的完整客户数据画像
                - correction: 更正权，需在 request_data 中提供 corrections 字典
                - deletion:   删除权（匿名化），需人工审批后执行
                - portability: 可携带权，直接返回 JSON 格式的客户数据导出
            requested_by: 请求人（员工 ID 或 "system"）
            notes: 备注
            request_data: 请求附加数据
                - correction 类型需包含 {"corrections": {"field": "value", ...}}

        Returns:
            pdpa_requests 表记录（含 request_id / status 等）

        Raises:
            ValueError: 请求类型不合法、存在进行中请求、或客户不存在
        """
        await self._set_tenant()

        if request_type not in PDPA_REQUEST_TYPES:
            raise ValueError(f"request_type 必须是: {', '.join(PDPA_REQUEST_TYPES)}")

        # 检查是否存在同类型进行中请求
        existing = await self.db.execute(
            text("""
                SELECT id FROM pdpa_requests
                WHERE tenant_id = :tid AND customer_id = :cid
                  AND request_type = :rtype
                  AND status IN ('pending', 'processing')
            """),
            {"tid": self._tid, "cid": uuid.UUID(customer_id), "rtype": request_type},
        )
        if existing.fetchone():
            raise ValueError(f"该客户已有进行中的 {request_type} 申请，请等待处理完成")

        request_id = uuid.uuid4()

        # access 和 portability 自动完成（立即返回数据）
        auto_complete = request_type in ("access", "portability")

        await self.db.execute(
            text("""
                INSERT INTO pdpa_requests
                    (id, tenant_id, customer_id, request_type, status,
                     requested_by, request_data, notes)
                VALUES
                    (:id, :tid, :cid, :rtype, :status,
                     :by, :req_data::jsonb, :notes)
            """),
            {
                "id": request_id,
                "tid": self._tid,
                "cid": uuid.UUID(customer_id),
                "rtype": request_type,
                "status": "completed" if auto_complete else "pending",
                "by": requested_by,
                "req_data": json.dumps(request_data or {}),
                "notes": notes,
            },
        )

        log.info(
            "pdpa.request_created",
            request_id=str(request_id),
            customer_id=mask_value("customer_id", customer_id),
            request_type=request_type,
            tenant_id=mask_value("tenant_id", self.tenant_id),
        )

        # ── 自动处理 access（返回解密后全量数据画像） ──
        if request_type == "access":
            profile = await self.get_encrypted_customer_profile(customer_id)
            resp_data = {"profile_summary": self._summarize_profile(profile)}
            await self._update_response_data(request_id, resp_data)
            log.info(
                "pdpa.access_fulfilled",
                request_id=str(request_id),
                customer_id=mask_value("customer_id", customer_id),
                field_count=len(profile),
            )
            return await self.get_request(str(request_id))

        # ── 自动处理 portability（返回 JSON 导出） ──
        if request_type == "portability":
            export_data = await self.export_customer_data(customer_id)
            await self._update_response_data(request_id, {"export": export_data})
            log.info(
                "pdpa.portability_fulfilled",
                request_id=str(request_id),
                customer_id=mask_value("customer_id", customer_id),
            )
            return await self.get_request(str(request_id))

        return await self.get_request(str(request_id))

    async def create_access_request(
        self,
        customer_id: str,
        requested_by: str = "customer",
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """便捷方法：创建数据访问请求（PDPA Right of Access）

        Returns:
            pdpa_requests 记录（status 为 "pending"）

        注：
            handle_data_subject_request 会自动完成 access 请求并解密数据。
            create_access_request 只创建请求（pending 状态）不触发自动处理。
        """
        await self._set_tenant()

        # 检查是否存在进行中的 access 请求
        existing = await self.db.execute(
            text("""
                SELECT id FROM pdpa_requests
                WHERE tenant_id = :tid AND customer_id = :cid
                  AND request_type = 'access'
                  AND status IN ('pending', 'processing')
            """),
            {"tid": self._tid, "cid": uuid.UUID(customer_id)},
        )
        if existing.fetchone():
            raise ValueError("该客户已有进行中的 access 申请，请等待处理完成")

        request_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text("""
                INSERT INTO pdpa_requests
                    (id, tenant_id, customer_id, request_type, status,
                     requested_by, notes, created_at, updated_at)
                VALUES
                    (:id, :tid, :cid, 'access', 'pending',
                     :by, :notes, :now, :now)
            """),
            {
                "id": request_id,
                "tid": self._tid,
                "cid": uuid.UUID(customer_id),
                "by": requested_by,
                "notes": notes,
                "now": now,
            },
        )
        await self.db.commit()

        return {
            "id": str(request_id),
            "tenant_id": self.tenant_id,
            "customer_id": str(customer_id),
            "request_type": "access",
            "status": "pending",
            "requested_by": requested_by,
            "created_at": now.isoformat(),
        }

    async def create_correction_request(
        self,
        customer_id: str,
        field_name: str,
        current_value: str,
        new_value: str,
        reason: str,
        requested_by: str = "customer",
    ) -> Dict[str, Any]:
        """便捷方法：创建数据更正请求（PDPA Right of Correction）

        Args:
            customer_id: 客户 ID
            field_name:  需要更正的字段名
            current_value: 当前值（用于确认）
            new_value:   更正后的值
            reason:      更正原因
            requested_by: 请求人

        Returns:
            pdpa_requests 记录（status 为 "pending"）
        """
        request_data = {
            "corrections": {field_name: new_value},
            "current_value": current_value,
            "reason": reason,
        }
        result = await self.handle_data_subject_request(
            customer_id=customer_id,
            request_type="correction",
            requested_by=requested_by,
            request_data=request_data,
            notes=reason,
        )
        if result is None:
            raise RuntimeError("创建更正请求失败：数据库写入异常")
        if result.get("status") != "pending":
            result["status"] = "pending"
        return result

    async def process_request(
        self,
        request_id: str,
        action: str,
        rejection_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """处理 PDPA 请求（审批/执行/拒绝）

        Args:
            request_id: 请求 ID
            action: approve / reject
            rejection_reason: 拒绝原因（action=reject 时必填）

        Returns:
            更新后的 pdpa_requests 记录

        Raises:
            ValueError: 请求不存在、状态不合法、或 action 未知
        """
        await self._set_tenant()
        req = await self.get_request(request_id)
        if not req:
            raise ValueError(f"PDPA 请求 {request_id} 不存在")

        now = datetime.now(timezone.utc)
        rtype = req["request_type"]
        customer_id = req["customer_id"]

        # ── 拒绝 ─────────────────────────────────────────
        if action == "reject":
            if req["status"] not in ("pending", "processing"):
                raise ValueError(f"只能拒绝 pending/processing 状态的请求，当前: {req['status']}")

            await self.db.execute(
                text("""
                    UPDATE pdpa_requests
                    SET status = 'rejected',
                        response_data = :resp::jsonb,
                        updated_at = :now
                    WHERE id = :id AND tenant_id = :tid
                """),
                {
                    "resp": json.dumps({"rejection_reason": rejection_reason}),
                    "now": now,
                    "id": uuid.UUID(request_id),
                    "tid": self._tid,
                },
            )
            log.info(
                "pdpa.request_rejected",
                request_id=request_id,
                request_type=rtype,
                reason=rejection_reason,
                tenant_id=mask_value("tenant_id", self.tenant_id),
            )
            return await self.get_request(request_id)

        # ── 审批 ─────────────────────────────────────────
        if action == "approve":
            if req["status"] != "pending":
                raise ValueError(f"只能审批 pending 状态的请求，当前: {req['status']}")

            # 标记为 processing
            await self.db.execute(
                text("""
                    UPDATE pdpa_requests
                    SET status = 'processing', updated_at = :now
                    WHERE id = :id AND tenant_id = :tid
                """),
                {"now": now, "id": uuid.UUID(request_id), "tid": self._tid},
            )

            # ── 处理 deletion（匿名化） ──
            if rtype == "deletion":
                anon_log = await self.anonymize_customer(customer_id)
                await self._update_response_data(request_id, {"anonymization": anon_log})
                log.info(
                    "pdpa.deletion_executed",
                    request_id=request_id,
                    customer_id=mask_value("customer_id", customer_id),
                    rows_affected=anon_log.get("rows_affected"),
                )
                return await self.get_request(request_id)

            # ── 处理 correction（字段更正） ──
            if rtype == "correction":
                req_data = req.get("request_data") or {}
                corrections = req_data.get("corrections", {})
                if not corrections:
                    raise ValueError("correction 请求必须提供 corrections 字段")
                affected = await self._apply_correction(customer_id, corrections)
                await self._update_response_data(
                    request_id,
                    {
                        "corrections_applied": list(corrections.keys()),
                        "rows_affected": affected,
                    },
                )
                log.info(
                    "pdpa.correction_executed",
                    request_id=request_id,
                    customer_id=mask_value("customer_id", customer_id),
                    fields=list(corrections.keys()),
                )
                return await self.get_request(request_id)

            # 其他类型标记完成
            await self._update_response_data(request_id, {"status": "completed"})
            return await self.get_request(request_id)

        raise ValueError(f"未知操作: {action}，支持: approve / reject")

    # ══════════════════════════════════════════════════════════════
    # 客户数据查阅 (PDPA Right of Access)
    # ══════════════════════════════════════════════════════════════

    async def get_encrypted_customer_profile(
        self,
        customer_id: str,
    ) -> Dict[str, Any]:
        """获取客户完整数据画像，自动解密加密字段

        遍历 customers 表所有字段：
          - ENC: 前缀的字段自动 AES-256-GCM 解密
          - 解密失败的字段返回 None（记录告警日志）
          - 非加密字段原样返回

        Returns:
            包含客户所有字段的字典（加密字段已解密）
        """
        await self._set_tenant()
        cid = uuid.UUID(customer_id)

        result = await self.db.execute(
            text("""
                SELECT *
                FROM customers
                WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": cid, "tid": self._tid},
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"客户 {customer_id} 不存在")

        # 将 Row 转为字典，自动解密加密字段
        profile: Dict[str, Any] = {}
        for key in row._mapping.keys():
            value = row._mapping[key]
            if isinstance(value, str) and is_encrypted(value):
                try:
                    profile[key] = self._encryptor.decrypt(value)
                except Exception as exc:
                    log.warning(
                        "pdpa.decrypt_failed",
                        field=key,
                        error=str(exc),
                        customer_id=mask_value("customer_id", customer_id),
                    )
                    profile[key] = None
            elif isinstance(value, (datetime,)):
                profile[key] = value.isoformat()
            elif isinstance(value, uuid.UUID):
                profile[key] = str(value)
            else:
                profile[key] = value

        log.info(
            "pdpa.profile_accessed",
            customer_id=mask_value("customer_id", customer_id),
            field_count=len(profile),
            tenant_id=mask_value("tenant_id", self.tenant_id),
        )

        return profile

    async def _apply_correction(
        self,
        customer_id: str,
        correction_fields: Dict[str, Any],
    ) -> int:
        """应用客户数据更正（PDPA Right of Correction）

        敏感字段自动加密后写入。
        """
        if not correction_fields:
            raise ValueError("更正字段不能为空")

        # 允许更新的字段白名单（防止 SQL 注入）
        allowed_fields = {
            "primary_phone", "display_name", "gender", "birth_date",
            "dietary_restrictions", "wechat_openid", "wechat_unionid",
            "meituan_user_id", "meituan_openid", "douyin_openid",
            "eleme_user_id", "wecom_external_userid",
        }
        unknown_fields = set(correction_fields.keys()) - allowed_fields
        if unknown_fields:
            raise ValueError(f"不允许更新以下字段: {unknown_fields}")

        cid = uuid.UUID(customer_id)
        set_clauses: list[str] = []
        params: Dict[str, Any] = {
            "cid": cid,
            "tid": self._tid,
            "now": datetime.now(timezone.utc),
        }

        # 敏感字段列表（需要加密存储）
        sensitive_fields = {
            "primary_phone", "wechat_openid", "wechat_unionid",
            "meituan_user_id", "meituan_openid", "douyin_openid",
            "eleme_user_id", "wecom_external_userid",
        }

        for i, (field, value) in enumerate(correction_fields.items()):
            param = f"val_{i}"

            # 敏感字段自动加密
            if value is not None and isinstance(value, str) and field in sensitive_fields:
                try:
                    value = self._encryptor.encrypt(value)
                except (ValueError, TypeError, RuntimeError) as exc:
                    log.error(
                        "pdpa.correction_encrypt_failed",
                        field=field,
                        error=str(exc),
                        exc_info=True,
                    )
                    raise RuntimeError(
                        f"敏感字段加密失败，已中止更新: {field}"
                    ) from exc

            set_clauses.append(f"{field} = :{param}")
            params[param] = value

        set_clauses.append("updated_at = :now")

        sql = f"""
            UPDATE customers
            SET {', '.join(set_clauses)}
            WHERE id = :cid AND tenant_id = :tid
        """

        result = await self.db.execute(text(sql), params)

        log.info(
            "pdpa.correction_applied",
            customer_id=mask_value("customer_id", customer_id),
            fields_updated=list(correction_fields.keys()),
            tenant_id=mask_value("tenant_id", self.tenant_id),
        )
        return result.rowcount

    # ══════════════════════════════════════════════════════════════
    # 匿名化 (PDPA Deletion / Right to Erasure)
    # ══════════════════════════════════════════════════════════════

    async def anonymize_customer(
        self,
        customer_id: str,
    ) -> Dict[str, Any]:
        """匿名化客户数据

        策略（符合 PDPA 2010 及国标 GB/T 35273）：
          - display_name → "已注销用户_{customer_id[:8]}"
          - primary_phone → NULL
          - 微信/美团/抖音/饿了么/企微身份 → NULL
          - gender / 地址类 → NULL
          - 保留：RFM 评分、消费统计、标签（用于经营分析）
          - 不物理删除数据（审计合规要求）

        Returns:
            anonymization_log: 匿名化操作日志
        """
        await self._set_tenant()
        cid = uuid.UUID(customer_id)
        now = datetime.now(timezone.utc)
        anon_name = f"已注销用户_{customer_id[:8]}"

        set_clauses: list[str] = []
        params: Dict[str, Any] = {
            "cid": cid,
            "tid": self._tid,
            "now": now,
            "anon_name": anon_name,
        }

        for field, default_value in _ANONYMIZE_FIELDS.items():
            if default_value == "__ANON__":
                set_clauses.append(f"{field} = :anon_name")
            else:
                param = f"f_{field}"
                set_clauses.append(f"{field} = :{param}")
                params[param] = default_value

        set_clauses.append("updated_at = :now")

        sql = f"""
            UPDATE customers
            SET {', '.join(set_clauses)}
            WHERE id = :cid AND tenant_id = :tid
        """

        result = await self.db.execute(text(sql), params)
        affected = result.rowcount

        anon_log = {
            "executed_at": now.isoformat(),
            "customer_id": customer_id,
            "fields_anonymized": list(_ANONYMIZE_FIELDS.keys()),
            "fields_retained": _RETAINED_FIELDS,
            "rows_affected": affected,
            "strategy": "in_place_nullify",
            "regulation": "Malaysia Personal Data Protection Act 2010",
        }

        log.info(
            "pdpa.anonymization_executed",
            customer_id=mask_value("customer_id", customer_id),
            rows_affected=affected,
            fields_anonymized=len(_ANONYMIZE_FIELDS),
            tenant_id=mask_value("tenant_id", self.tenant_id),
        )

        return anon_log

    # ══════════════════════════════════════════════════════════════
    # 数据可携带性 (PDPA Data Portability)
    # ══════════════════════════════════════════════════════════════

    async def export_customer_data(
        self,
        customer_id: str,
    ) -> Dict[str, Any]:
        """导出客户全部数据为 JSON

        PDPA 数据可携带权：数据主体有权以结构化、通用、机器可读的格式
        获取其个人数据，并有权将该数据传输给其他数据控制者。

        返回内容：
          - profile: 客户基本信息（加密字段解密后）
          - statistics: 消费统计概要
          - orders: 最近 1000 条订单记录
        """
        await self._set_tenant()
        cid = uuid.UUID(customer_id)

        # 基本信息
        cust_result = await self.db.execute(
            text("""
                SELECT id, primary_phone, display_name, gender, birth_date,
                       total_order_count, total_order_amount_fen,
                       rfm_recency_days, rfm_frequency, rfm_monetary_fen,
                       rfm_level, tags, dietary_restrictions,
                       created_at, updated_at, country_code
                FROM customers
                WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": cid, "tid": self._tid},
        )
        cust = cust_result.fetchone()
        if not cust:
            raise ValueError(f"客户 {customer_id} 不存在")

        # 解密加密字段
        phone_raw = cust.primary_phone
        if isinstance(phone_raw, str) and is_encrypted(phone_raw):
            try:
                phone_raw = self._encryptor.decrypt(phone_raw)
            except Exception:
                phone_raw = None

        # 消费历史（最近 1000 条）
        orders_result = await self.db.execute(
            text("""
                SELECT id, store_id, total_amount_fen, discount_amount_fen,
                       final_amount_fen, status, order_type, order_time,
                       completed_at
                FROM orders
                WHERE customer_id = :cid AND tenant_id = :tid
                ORDER BY order_time DESC
                LIMIT 1000
            """),
            {"cid": cid, "tid": self._tid},
        )
        orders = [
            {
                "order_id": str(r.id),
                "store_id": str(r.store_id) if r.store_id else None,
                "total_amount_fen": r.total_amount_fen,
                "discount_amount_fen": r.discount_amount_fen,
                "final_amount_fen": r.final_amount_fen,
                "status": r.status,
                "order_type": r.order_type,
                "order_time": r.order_time.isoformat() if r.order_time else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in orders_result.fetchall()
        ]

        export_data: Dict[str, Any] = {
            "customer_id": customer_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "regulation": "Malaysia Personal Data Protection Act 2010",
            "notice": "本数据导出依据马来西亚 PDPA 2010 数据可携带权（Right of Data Portability），仅供数据主体本人使用",
            "country_code": cust.country_code or "MY",
            "profile": {
                "primary_phone": phone_raw,
                "display_name": cust.display_name,
                "gender": cust.gender,
                "birth_date": str(cust.birth_date) if cust.birth_date else None,
                "member_since": cust.created_at.isoformat() if cust.created_at else None,
                "rfm_level": cust.rfm_level,
            },
            "statistics": {
                "total_order_count": cust.total_order_count or 0,
                "total_amount_fen": cust.total_order_amount_fen or 0,
                "rfm_recency_days": cust.rfm_recency_days,
                "rfm_frequency": cust.rfm_frequency,
                "rfm_monetary_fen": cust.rfm_monetary_fen,
            },
            "orders": orders,
            "order_count": len(orders),
        }

        log.info(
            "pdpa.data_exported",
            customer_id=mask_value("customer_id", customer_id),
            order_count=len(orders),
            tenant_id=mask_value("tenant_id", self.tenant_id),
        )

        return export_data

    # ══════════════════════════════════════════════════════════════
    # 同意管理 (PDPA Consent)
    # ══════════════════════════════════════════════════════════════

    async def log_consent(
        self,
        customer_id: str,
        consent_type: str,
        granted: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录客户同意/撤回同意

        PDPA 2010 要求：
          - 处理个人数据前必须获得明确同意（opt-in）
          - 同意必须可记录、可审计（本表提供审计轨迹）
          - 数据主体有权随时撤回同意
          - 撤回同意不影响撤回前基于同意处理的合法性

        Args:
            customer_id: 客户 ID
            consent_type: 同意类型
                - marketing_sms:    SMS 营销
                - marketing_email:  邮件营销
                - data_processing:  个人数据处理
                - cross_border:     跨境数据传输
                - third_party:      第三方共享
            granted: True=同意, False=撤回同意
            ip_address: 客户端 IP（审计需要）
            user_agent: User-Agent（审计需要）
        """
        await self._set_tenant()

        log_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text("""
                INSERT INTO pdpa_consent_logs
                    (id, tenant_id, customer_id, consent_type, granted,
                     ip_address, user_agent, created_at)
                VALUES
                    (:id, :tid, :cid, :ctype, :granted,
                     :ip, :ua, :now)
            """),
            {
                "id": log_id,
                "tid": self._tid,
                "cid": uuid.UUID(customer_id),
                "ctype": consent_type,
                "granted": granted,
                "ip": ip_address,
                "ua": user_agent,
                "now": now,
            },
        )

        action_label = "granted" if granted else "withdrawn"
        log.info(
            f"pdpa.consent_{action_label}",
            consent_log_id=str(log_id),
            customer_id=mask_value("customer_id", customer_id),
            consent_type=consent_type,
            granted=granted,
            ip_address=ip_address,
            tenant_id=mask_value("tenant_id", self.tenant_id),
        )

        return {
            "consent_log_id": str(log_id),
            "customer_id": customer_id,
            "consent_type": consent_type,
            "granted": granted,
            "created_at": now.isoformat(),
        }

    async def get_consent_history(
        self,
        customer_id: str,
    ) -> List[Dict[str, Any]]:
        """查询客户同意历史（按时间倒序）"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, consent_type, granted, ip_address, user_agent, created_at
                FROM pdpa_consent_logs
                WHERE tenant_id = :tid AND customer_id = :cid
                ORDER BY created_at DESC
            """),
            {"tid": self._tid, "cid": uuid.UUID(customer_id)},
        )
        return [
            {
                "id": str(r.id),
                "consent_type": r.consent_type,
                "granted": r.granted,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in result.fetchall()
        ]

    # ══════════════════════════════════════════════════════════════
    # 数据留存检查 (PDPA Storage Limitation)
    # ══════════════════════════════════════════════════════════════

    async def check_data_retention(
        self,
        retention_days: int = 365,
    ) -> Dict[str, Any]:
        """检查过期数据

        PDPA 存储限制原则（Storage Limitation Principle）：
          个人数据在完成业务目的后，应在合理期限内销毁或匿名化。

        默认标准：无任何消费记录超过 365 天 或 从未消费的客户。

        Args:
            retention_days: 无活动超过此天数的客户视为过期数据

        Returns:
            {
                "candidate_count": 候选客户数,
                "candidates": [...] (最多 100 条，字段已脱敏),
                "retention_policy_days": retention_days,
                "note": "候选数据需人工审核确认后通过 deletion 请求处理"
            }
        """
        await self._set_tenant()

        result = await self.db.execute(
            text("""
                SELECT c.id, c.display_name, c.primary_phone,
                       c.last_order_at, c.total_order_count,
                       c.created_at
                FROM customers c
                WHERE c.tenant_id = :tid
                  AND c.is_deleted = false
                  AND c.display_name NOT LIKE '已注销%'
                  AND (
                      c.last_order_at IS NULL
                      OR c.last_order_at < NOW() - :retention_days * INTERVAL '1 day'
                  )
                ORDER BY c.last_order_at ASC NULLS FIRST
                LIMIT 100
            """),
            {"tid": self._tid, "retention_days": retention_days},
        )
        rows = result.fetchall()

        candidates = []
        for r in rows:
            candidates.append({
                "customer_id": str(r.id),
                "display_name": mask_value("display_name", r.display_name) if r.display_name else None,
                "phone": mask_value("phone", r.primary_phone) if r.primary_phone else None,
                "last_order_at": r.last_order_at.isoformat() if r.last_order_at else None,
                "total_order_count": r.total_order_count or 0,
                "member_since": r.created_at.isoformat() if r.created_at else None,
            })

        log.info(
            "pdpa.retention_check",
            candidate_count=len(candidates),
            retention_days=retention_days,
            tenant_id=mask_value("tenant_id", self.tenant_id),
        )

        return {
            "candidate_count": len(candidates),
            "candidates": candidates,
            "retention_policy_days": retention_days,
            "regulation": "Malaysia Personal Data Protection Act 2010 — Storage Limitation Principle",
            "note": "候选数据需人工审核确认后通过 PDPA deletion 请求处理",
        }

    # ══════════════════════════════════════════════════════════════
    # 查询
    # ══════════════════════════════════════════════════════════════

    async def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """查询单条 PDPA 请求"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, tenant_id, customer_id, request_type, status,
                       request_data, response_data, notes,
                       requested_by, created_at, updated_at
                FROM pdpa_requests
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(request_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_request_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        """查询 PDPA 请求状态（get_request 别名）"""
        return await self.get_request(request_id)

    async def list_requests(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
        request_type: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询 PDPA 请求列表"""
        await self._set_tenant()

        conditions = ["tenant_id = :tid"]
        params: Dict[str, Any] = {"tid": self._tid}

        if customer_id:
            conditions.append("customer_id = :cid")
            params["cid"] = uuid.UUID(customer_id)
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if request_type:
            conditions.append("request_type = :rtype")
            params["rtype"] = request_type

        where = " AND ".join(conditions)

        # Count
        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM pdpa_requests WHERE {where}"),
            params,
        )
        total: int = count_result.scalar_one()

        # Fetch page
        if page < 1:
            page = 1
        if size < 1:
            size = 20
        if size > 100:
            size = 100
        offset = (page - 1) * size

        rows_result = await self.db.execute(
            text(f"""
                SELECT id, tenant_id, customer_id, request_type, status,
                       request_data, response_data, notes,
                       requested_by, created_at, updated_at
                FROM pdpa_requests
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": size, "offset": offset},
        )

        items = [self._row_to_dict(r) for r in rows_result.fetchall()]

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    # ══════════════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════════════

    async def _update_response_data(self, request_id: str, data: Dict[str, Any]) -> None:
        """更新 pdpa_requests 的 response_data 字段"""
        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                UPDATE pdpa_requests
                SET status = 'completed',
                    response_data = response_data || :resp::jsonb,
                    updated_at = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {
                "resp": json.dumps(data),
                "now": now,
                "id": uuid.UUID(request_id),
                "tid": self._tid,
            },
        )

    def _row_to_dict(self, row) -> Dict[str, Any]:
        """将 SQLAlchemy Row 转为字典"""
        def _parse_json(v):
            if v is None:
                return None
            return v if isinstance(v, (dict, list)) else json.loads(v)

        return {
            "request_id": str(row.id),
            "tenant_id": self.tenant_id,
            "customer_id": str(row.customer_id),
            "request_type": row.request_type,
            "status": row.status,
            "request_data": _parse_json(row.request_data),
            "response_data": _parse_json(row.response_data),
            "requested_by": row.requested_by,
            "notes": getattr(row, "notes", None),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def _summarize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
        """精简数据画像用于 response_data（避免存储全量数据到 JSONB）"""
        summary: Dict[str, Any] = {}
        for key in ("id", "display_name", "primary_phone", "gender", "birth_date",
                     "total_order_count", "total_order_amount_fen",
                     "rfm_level", "tags", "dietary_restrictions",
                     "created_at", "updated_at", "country_code"):
            if key in profile:
                summary[key] = profile[key]
        summary["field_count"] = len(profile)
        return summary
