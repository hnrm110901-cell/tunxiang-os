"""ERP 适配器基类 — 定义统一接口契约

所有 ERP 对接适配器（金蝶/用友/畅捷通等）必须继承此基类并实现全部抽象方法。

接口约定：
  - 所有方法 async/await
  - 金额单位：分(fen), int 类型
  - push_voucher 失败时抛出具体异常，由调用方决策是否入队重试
  - 密钥全部通过环境变量注入，基类不持有任何硬编码凭据
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ─── 枚举 ───────────────────────────────────────────────────────────────────


class ERPType(str, Enum):
    """支持的 ERP 系统类型"""
    KINGDEE = "kingdee"       # 金蝶 K3/Cloud
    YONYOU = "yonyou"         # 用友云 YonBIP/NC
    CHANJET = "chanjet"       # 畅捷通（预留）


class VoucherType(str, Enum):
    """凭证字类型（与金蝶/用友通用叫法对齐）"""
    RECEIPT = "收"            # 收款凭证
    PAYMENT = "付"            # 付款凭证
    TRANSFER = "转"           # 转账凭证
    MEMO = "记"               # 记账凭证


class PushStatus(str, Enum):
    """推送状态"""
    SUCCESS = "success"
    FAILED = "failed"
    QUEUED = "queued"         # 推送失败已入本地队列，待重试


# ─── 数据模型 ────────────────────────────────────────────────────────────────


class ERPVoucherEntry(BaseModel):
    """单条凭证分录（借贷二择其一，另一方必须为 0）"""

    account_code: str = Field(..., description="科目编码，如 '1403'")
    account_name: str = Field(..., description="科目名称，如 '原材料'")
    debit_fen: int = Field(default=0, ge=0, description="借方金额（分）")
    credit_fen: int = Field(default=0, ge=0, description="贷方金额（分）")
    summary: str = Field(..., description="摘要，不超过 200 字")

    @model_validator(mode="after")
    def validate_debit_credit(self) -> "ERPVoucherEntry":
        """确保分录借贷不同时为 0，且不同时非零（单边原则）"""
        if self.debit_fen == 0 and self.credit_fen == 0:
            raise ValueError(
                f"分录 [{self.account_code}] 借贷金额不能同时为 0"
            )
        if self.debit_fen > 0 and self.credit_fen > 0:
            raise ValueError(
                f"分录 [{self.account_code}] 借贷金额不能同时非零（单边原则）"
            )
        return self


class ERPVoucher(BaseModel):
    """ERP 财务凭证（系统无关的统一格式）"""

    voucher_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="屯象系统内部凭证ID",
    )
    voucher_type: VoucherType = Field(..., description="凭证字类型")
    business_date: date = Field(..., description="业务日期")
    entries: list[ERPVoucherEntry] = Field(
        ..., min_length=2, description="凭证分录列表，至少 2 条"
    )
    source_type: str = Field(..., description="来源类型：purchase_order/daily_revenue/payroll...")
    source_id: str = Field(..., description="来源单据 ID（采购单/日结ID等）")
    tenant_id: str = Field(..., description="租户 ID")
    store_id: str = Field(..., description="门店 ID")
    memo: str = Field(default="", description="凭证备注")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def validate_balance(self) -> "ERPVoucher":
        """借贷必须平衡（分为单位，避免浮点误差）"""
        total_debit = sum(e.debit_fen for e in self.entries)
        total_credit = sum(e.credit_fen for e in self.entries)
        if total_debit != total_credit:
            raise ValueError(
                f"凭证借贷不平衡: 借方合计={total_debit}分, 贷方合计={total_credit}分"
            )
        return self

    @property
    def total_fen(self) -> int:
        return sum(e.debit_fen for e in self.entries)

    @property
    def total_yuan(self) -> float:
        return self.total_fen / 100


class ERPAccount(BaseModel):
    """科目表条目"""

    code: str = Field(..., description="科目编码，如 '1403'")
    name: str = Field(..., description="科目名称，如 '原材料'")
    account_type: str = Field(..., description="科目类型：资产/负债/收入/费用/权益")
    parent_code: str | None = Field(default=None, description="上级科目编码")
    is_leaf: bool = Field(default=True, description="是否末级科目（末级才能做分录）")
    currency: str = Field(default="CNY")
    extra: dict[str, Any] = Field(default_factory=dict, description="ERP 平台附加字段")


class ERPPushResult(BaseModel):
    """凭证推送结果"""

    voucher_id: str = Field(..., description="屯象内部凭证 ID")
    erp_voucher_id: str | None = Field(
        default=None, description="ERP 系统返回的凭证 ID（失败时为 None）"
    )
    status: PushStatus
    erp_type: ERPType
    error_message: str | None = Field(default=None)
    pushed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    raw_response: dict[str, Any] = Field(
        default_factory=dict, description="ERP 原始响应（用于排查问题）"
    )


# ─── 基类 ────────────────────────────────────────────────────────────────────


class ERPAdapter(ABC):
    """ERP 对接基类，定义统一接口契约

    子类必须：
    1. 实现所有 @abstractmethod
    2. 通过环境变量获取密钥（不硬编码）
    3. 推送失败时抛出具体异常（httpx.HTTPError / ValueError 等），
       不吞掉异常，由调用方（VoucherGenerator.push_to_erp）决策是否入队
    """

    @abstractmethod
    async def push_voucher(self, voucher: ERPVoucher) -> ERPPushResult:
        """推送财务凭证到 ERP

        Args:
            voucher: 统一格式凭证

        Returns:
            ERPPushResult（包含 ERP 侧凭证 ID 和推送状态）

        Raises:
            httpx.HTTPError: 网络或 HTTP 层错误
            ValueError: 凭证格式或业务校验错误
            RuntimeError: ERP 系统返回业务错误
        """

    @abstractmethod
    async def sync_chart_of_accounts(self) -> list[ERPAccount]:
        """同步科目表

        Returns:
            科目列表（末级科目可用于分录）

        Raises:
            httpx.HTTPError: 网络错误
            RuntimeError: ERP 接口错误
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """连通性检查

        Returns:
            True 表示 ERP 可达，False 表示不可达（不抛异常）
        """

    @abstractmethod
    async def close(self) -> None:
        """释放 HTTP 连接等资源，在服务关闭时调用"""
