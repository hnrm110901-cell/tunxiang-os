"""财务凭证模型 — 会计凭证骨架（销售/成本/收款/付款）

迁移链（实际 schema 以 alembic 为准）:
  v031_round2_feature_tables  — 初始建表（period_start/end + total_debit/credit）
  v264_financial_vouchers_sync_orm  — 对齐 ORM + 金额统一到 fen BIGINT
    新增列: store_id, voucher_date, total_amount_fen, source_type, source_id,
            exported_at, updated_at
    松绑:   period_start / period_end DROP NOT NULL
    回填:   voucher_date = period_start
  v265+ (规划中)  — voucher_lines 子表 + 红冲作废字段

金额单位约定（屯象）:
  - total_amount_fen: BIGINT 分（SSOT, 新字段）
  - total_amount:     NUMERIC(12,2) 元（DEPRECATED v264, 双写兼容期保留）
  - entries JSONB 分录: 仍为元（ERP 推送契约, 由 W1.1 PR 统一治理）

⚠️  双写漏同步防护（W1.3 PR 落地, 此处仅文档预告）:
  风险点 (按发生概率排序):
    1. 第三方 ETL 独立作业 (POS/银行/用友 T+ 对接脚本) — 不跟 ORM 变更
    2. Celery 任务里的 raw SQL: text("UPDATE ... SET total_amount=...")
    3. 运维手工 SQL 订正 / 历史数据修补脚本
    4. 红冲/作废凭证取负数时, 两字段正负号不对称
    5. 报表层读不一致: ProfitDashboard 读元 vs hq_briefing 读 fen

  推荐缓解 (W1.3 PR):
    A. DB 层强制同步 — 将 total_amount 改为 GENERATED 列, fen 做 SSOT:
         ALTER TABLE financial_vouchers
             DROP COLUMN total_amount,
             ADD COLUMN total_amount NUMERIC(12,2)
                 GENERATED ALWAYS AS (total_amount_fen::NUMERIC / 100) STORED;
       → 任何代码写 total_amount 会报错, 强制切到 fen.
    B. CI lint 规则: 禁止新代码写 total_amount 不写 total_amount_fen.
    C. 回归测试: 所有写入路径的端到端校验两字段同步.
"""
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .cost_snapshot import Base


class FinancialVoucher(Base):
    """财务凭证

    entries JSONB 结构（每条分录）：
    [
        {
            "account_code": "6001",
            "account_name": "主营业务收入-餐饮",
            "debit": 0.00,        # 借方金额（元）
            "credit": 1000.00,    # 贷方金额（元）
            "summary": "2026-03-30堂食收入"
        },
        ...
    ]

    voucher_type 枚举：
    - sales    : 销售收入凭证
    - cost     : 成本结转凭证
    - payment  : 付款凭证
    - receipt  : 收款凭证

    status 枚举：
    - draft     : 草稿（系统自动生成，未审核）
    - confirmed : 已确认（财务审核通过）
    - exported  : 已导出（推送金蝶/用友等ERP）
    """
    __tablename__ = "financial_vouchers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # v264 后 nullable=True（物理 schema 允许 NULL 以兼容历史行）
    # 应用层对 INSERT 仍强制要求 store_id / voucher_date 非空.
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
        comment="门店 ID (v264 起 nullable, 应用层仍要求新建凭证必填)"
    )

    # 凭证标识
    voucher_no: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True,
        comment="凭证编号，格式: V{store_short}{YYYYMMDD}{SEQ}"
    )
    voucher_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, index=True,
        comment="凭证日期(业务日期). v264 起 nullable, 应用层仍要求新建凭证必填."
    )
    voucher_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="凭证类型: sales/cost/payment/receipt"
    )

    # 金额
    # v264 后 total_amount (NUMERIC 元) DEPRECATED, 过渡期双写, 下游优先读 total_amount_fen.
    total_amount: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="DEPRECATED v264 (NUMERIC 元). 用 total_amount_fen (BIGINT 分). 将在 v270+ drop."
    )
    total_amount_fen: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True,
        comment="凭证总金额 (分, 屯象 fen BIGINT 约定). v264 起为 SSOT."
    )

    # 分录（JSONB）
    entries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="会计分录列表 [{account_code, debit, credit, summary}]"
    )

    # 来源追溯
    source_type: Mapped[str | None] = mapped_column(
        String(30),
        comment="来源类型: order/settlement/payment"
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="来源单据ID（订单ID/日结ID等）"
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), default="draft", index=True,
        comment="状态: draft/confirmed/exported"
    )
    exported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="导出到ERP的时间"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "idx_financial_vouchers_tenant_store_date",
            "tenant_id", "store_id", "voucher_date"
        ),
        Index("idx_financial_vouchers_status", "tenant_id", "status"),
    )

    def is_balanced(self) -> bool:
        """验证借贷平衡——会计绝对约束，零容忍。

        为什么用整数 fen 精确比较:
          - 证监会/四大审计师不接受借贷平衡有"容忍度"
          - 早前 abs(diff) < 0.001 (~0.1 分) 看似单张凭证安全, 实则:
            * 方向错了: 会计平衡是整数等式不是近似
            * 累计放大: 10 万张凭证月汇后误差可达数十元, 每张都"合规"
            * 掩盖真实错账: 0.005 元的税额四舍五入方向错误会被放行
          - IEEE 754 坑: 0.1 + 0.2 = 0.30000000000000004, 直接 float 比较不可靠
          - 解法: round(x * 100) 转 fen 整数后精确比较
        """
        total_debit_fen = sum(round(e.get("debit", 0) * 100) for e in self.entries)
        total_credit_fen = sum(round(e.get("credit", 0) * 100) for e in self.entries)
        return total_debit_fen == total_credit_fen

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id) if self.store_id else None,
            "voucher_no": self.voucher_no,
            "voucher_date": str(self.voucher_date) if self.voucher_date else None,
            "voucher_type": self.voucher_type,
            "total_amount": float(self.total_amount) if self.total_amount is not None else None,
            "total_amount_fen": self.total_amount_fen,
            "entries": self.entries,
            "source_type": self.source_type,
            "source_id": str(self.source_id) if self.source_id else None,
            "status": self.status,
            "exported_at": self.exported_at.isoformat() if self.exported_at else None,
            "is_balanced": self.is_balanced(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
