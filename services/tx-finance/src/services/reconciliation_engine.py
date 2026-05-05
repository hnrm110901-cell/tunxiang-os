"""跨平台结算对账引擎

匹配各外卖平台结算报告与内部订单，标记差异项供人工审核。

平台结算特性：
  - 美团：T+1 结算，佣金率 ~20%（含配送补贴）
  - 饿了么：T+1 结算，佣金率 ~18%
  - 抖音：T+3 结算，佣金率 ~5%（团购券核销后结算）
  - 高德：T+1 结算，佣金率 ~10%
  - 淘宝：T+1 结算，佣金率 ~15%（含流量推广费）

所有金额单位：分（fen）。金额 /100 转元仅在展示层做。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ── 常量 ──────────────────────────────────────────────────────────────────────

# 佣金率容差：±5%（平台因补贴活动可能微调）
COMMISSION_TOLERANCE_RATE = 0.05
# 金额容差：50 分（0.5 元），用于处理四舍五入差异
AMOUNT_TOLERANCE_FEN = 50
# 自动标记为确认到账的延迟天数
DEFAULT_CONFIRMATION_DELAY_DAYS: dict[str, int] = {
    "meituan": 2,
    "eleme": 2,
    "douyin": 5,
    "amap": 2,
    "taobao": 2,
}


# ── 枚举 ──────────────────────────────────────────────────────────────────────


class ReconciliationStatus(str, Enum):
    """单条结算记录的对账状态"""

    MATCHED = "matched"  # 完全匹配
    MISMATCH = "mismatch"  # 金额/佣金不符
    MISSING_INTERNAL = "missing_internal"  # 平台有结算但内部无订单
    MISSING_PLATFORM = "missing_platform"  # 内部有订单但平台无结算
    PENDING = "pending"  # 待对账（初始状态）
    PENDING_ARRIVAL = "pending_arrival"  # 金额一致，待确认到账


class PaymentArrivalStatus(str, Enum):
    """T+N 到账跟踪状态"""

    PENDING = "pending"  # 未到账
    ARRIVED = "arrived"  # 已到账
    PARTIAL = "partial"  # 部分到账
    OVERDUE = "overdue"  # 逾期未到账
    DISPUTED = "disputed"  # 争议中


RECONCILIATION_LABELS: dict[str, str] = {
    ReconciliationStatus.MATCHED: "完全匹配",
    ReconciliationStatus.MISMATCH: "金额/佣金不符",
    ReconciliationStatus.MISSING_INTERNAL: "平台有记录但内部缺失",
    ReconciliationStatus.MISSING_PLATFORM: "内部有订单但平台缺失",
    ReconciliationStatus.PENDING: "待对账",
    ReconciliationStatus.PENDING_ARRIVAL: "待确认到账",
}

ARRIVAL_LABELS: dict[str, str] = {
    PaymentArrivalStatus.PENDING: "未到账",
    PaymentArrivalStatus.ARRIVED: "已到账",
    PaymentArrivalStatus.PARTIAL: "部分到账",
    PaymentArrivalStatus.OVERDUE: "逾期未到账",
    PaymentArrivalStatus.DISPUTED: "争议中",
}

PLATFORM_LABELS: dict[str, str] = {
    "meituan": "美团",
    "eleme": "饿了么",
    "douyin": "抖音",
    "amap": "高德",
    "taobao": "淘宝",
}


# ── 数据类 ────────────────────────────────────────────────────────────────────


@dataclass
class SettlementRecord:
    """单条平台结算记录"""

    platform: str
    platform_order_id: str
    platform_amount_fen: int
    platform_commission_fen: int
    platform_settlement_fen: int  # 结算净额 = amount - commission
    settlement_date: str  # YYYY-MM-DD
    internal_order_id: Optional[str] = None
    internal_amount_fen: int = 0
    internal_commission_fen: int = 0
    status: ReconciliationStatus = ReconciliationStatus.PENDING
    discrepancy_fen: int = 0  # 差异绝对值
    notes: str = ""


@dataclass
class PaymentArrivalRecord:
    """T+N 到账跟踪记录"""

    platform: str
    platform_order_id: str
    internal_order_id: str
    expected_amount_fen: int
    actual_arrival_fen: int = 0
    expected_arrival_date: Optional[str] = None  # YYYY-MM-DD
    actual_arrival_date: Optional[str] = None
    arrival_status: PaymentArrivalStatus = PaymentArrivalStatus.PENDING
    delay_days: int = 0  # 逾期天数
    notes: str = ""


@dataclass
class PlatformSummary:
    """单个平台的对账汇总"""

    platform: str
    total_settlements: int = 0
    total_amount_fen: int = 0
    total_commission_fen: int = 0
    matched: int = 0
    mismatched: int = 0
    missing_internal: int = 0
    missing_platform: int = 0
    pending_arrival: int = 0
    total_discrepancy_fen: int = 0
    match_rate: float = 0.0
    expected_commission_fen: int = 0


# ── 异常 ──────────────────────────────────────────────────────────────────────


class ReconciliationError(RuntimeError):
    """对账引擎执行错误"""


class SettlementNotFoundError(LookupError):
    """结算记录不存在"""


# ── 对账引擎 ──────────────────────────────────────────────────────────────────


class ReconciliationEngine:
    """跨平台结算对账引擎

    对账流程：
      1. 从平台结算报告读取结算记录
      2. 按 platform_order_id 匹配内部订单
      3. 比对金额，标记差异
      4. 校验佣金是否在预期范围内
      5. 生成对账报告
      6. T+N 到账跟踪

    对外接口：
      match_settlement()           — 单笔结算对账
      batch_reconcile()            — 批量对账
      track_payment_arrival()      — T+N 到账跟踪
      get_platform_summary()       — 按平台汇总对账结果
      get_discrepancy_report()     — 差异明细报告
    """

    # 各平台预期佣金率（基于合同费率）
    PLATFORM_COMMISSION_RATES: dict[str, float] = {
        "meituan": 0.20,
        "eleme": 0.18,
        "douyin": 0.05,
        "amap": 0.10,
        "taobao": 0.15,
    }

    def get_expected_commission(self, platform: str, amount_fen: int) -> int:
        """按平台合同费率计算预期佣金。

        对于费率未知的平台，按 20%（行业平均）计算。
        """
        rate = self.PLATFORM_COMMISSION_RATES.get(platform, 0.20)
        return int(amount_fen * rate)

    def match_settlement(
        self,
        platform: str,
        platform_order_id: str,
        platform_amount_fen: int,
        platform_commission_fen: int,
        internal_order_id: str = "",
        internal_amount_fen: int = 0,
    ) -> SettlementRecord:
        """单笔结算记录对账。

        判定逻辑：
          1. 无内部订单 → MISSING_INTERNAL
          2. 金额差异 > 容差 → MISMATCH
          3. 佣金偏离预期 > 5% → MISMATCH
          4. 完全一致 → MATCHED
        """
        expected_commission = self.get_expected_commission(platform, platform_amount_fen)
        commission_ok = (
            abs(platform_commission_fen - expected_commission)
            <= max(1, round(expected_commission * COMMISSION_TOLERANCE_RATE))
        )

        # 结算净额
        platform_settlement_fen = platform_amount_fen - platform_commission_fen

        record = SettlementRecord(
            platform=platform,
            platform_order_id=platform_order_id,
            platform_amount_fen=platform_amount_fen,
            platform_commission_fen=platform_commission_fen,
            platform_settlement_fen=platform_settlement_fen,
            settlement_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            internal_order_id=internal_order_id or None,
            internal_amount_fen=internal_amount_fen,
            internal_commission_fen=expected_commission,
        )

        if not internal_order_id:
            record.status = ReconciliationStatus.MISSING_INTERNAL
            record.discrepancy_fen = platform_amount_fen
            record.notes = f"平台【{PLATFORM_LABELS.get(platform, platform)}】有结算记录但内部无对应订单"
            logger.warning(
                "reconciliation.missing_internal",
                platform=platform,
                platform_order_id=platform_order_id,
                amount_fen=platform_amount_fen,
            )
        elif abs(internal_amount_fen - platform_amount_fen) > AMOUNT_TOLERANCE_FEN:
            record.status = ReconciliationStatus.MISMATCH
            record.discrepancy_fen = abs(internal_amount_fen - platform_amount_fen)
            record.notes = (
                f"金额不符: 平台={platform_amount_fen}分, "
                f"内部={internal_amount_fen}分, "
                f"差={internal_amount_fen - platform_amount_fen}分"
            )
            logger.warning(
                "reconciliation.amount_mismatch",
                platform=platform,
                platform_order_id=platform_order_id,
                platform_amount=platform_amount_fen,
                internal_amount=internal_amount_fen,
                discrepancy=record.discrepancy_fen,
            )
        elif not commission_ok:
            record.status = ReconciliationStatus.MISMATCH
            record.discrepancy_fen = abs(platform_commission_fen - expected_commission)
            record.notes = (
                f"佣金异常: 平台扣={platform_commission_fen}分, "
                f"预期={expected_commission}分, "
                f"差={platform_commission_fen - expected_commission}分"
            )
            logger.warning(
                "reconciliation.commission_mismatch",
                platform=platform,
                platform_order_id=platform_order_id,
                platform_commission=platform_commission_fen,
                expected_commission=expected_commission,
            )
        else:
            record.status = ReconciliationStatus.MATCHED
            record.notes = "对账一致"

        logger.info(
            "reconciliation.settlement_matched",
            platform=platform,
            platform_order_id=platform_order_id,
            status=record.status.value,
            discrepancy_fen=record.discrepancy_fen,
        )

        return record

    def batch_reconcile(
        self,
        settlements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """批量对账。

        参数 settlements 格式（每条）：
          {
            "platform": "meituan",
            "platform_order_id": "MT202605010001",
            "platform_amount_fen": 8800,
            "platform_commission_fen": 1760,
            "internal_order_id": "uuid-or-empty",
            "internal_amount_fen": 8800,
          }

        返回：
          {
            "results": [SettlementRecord as dict, ...],
            "summary": { total, matched, mismatched, missing, total_discrepancy_fen, match_rate },
            "platform_summaries": { "meituan": { ... }, ... },
          }
        """
        results: list[SettlementRecord] = []
        matched = mismatched = missing_internal = missing_platform = 0
        total_discrepancy = 0
        platform_stats: dict[str, dict[str, int]] = {}

        for s in settlements:
            r = self.match_settlement(
                platform=s.get("platform", ""),
                platform_order_id=s.get("platform_order_id", ""),
                platform_amount_fen=s.get("platform_amount_fen", 0),
                platform_commission_fen=s.get("platform_commission_fen", 0),
                internal_order_id=s.get("internal_order_id", ""),
                internal_amount_fen=s.get("internal_amount_fen", 0),
            )
            results.append(r)

            # 统计
            if r.status == ReconciliationStatus.MATCHED:
                matched += 1
            elif r.status == ReconciliationStatus.MISMATCH:
                mismatched += 1
                total_discrepancy += r.discrepancy_fen
            elif r.status == ReconciliationStatus.MISSING_INTERNAL:
                missing_internal += 1
            elif r.status == ReconciliationStatus.MISSING_PLATFORM:
                missing_platform += 1

            # 按平台统计
            pf = r.platform
            if pf not in platform_stats:
                platform_stats[pf] = {
                    "total": 0,
                    "matched": 0,
                    "mismatched": 0,
                    "missing_internal": 0,
                    "missing_platform": 0,
                    "total_amount_fen": 0,
                    "total_commission_fen": 0,
                    "total_discrepancy_fen": 0,
                }
            platform_stats[pf]["total"] += 1
            platform_stats[pf]["matched"] += 1 if r.status == ReconciliationStatus.MATCHED else 0
            platform_stats[pf]["mismatched"] += 1 if r.status == ReconciliationStatus.MISMATCH else 0
            platform_stats[pf]["missing_internal"] += 1 if r.status == ReconciliationStatus.MISSING_INTERNAL else 0
            platform_stats[pf]["missing_platform"] += 1 if r.status == ReconciliationStatus.MISSING_PLATFORM else 0
            platform_stats[pf]["total_amount_fen"] += r.platform_amount_fen
            platform_stats[pf]["total_commission_fen"] += r.platform_commission_fen
            platform_stats[pf]["total_discrepancy_fen"] += r.discrepancy_fen

        total = len(results)
        missing = missing_internal + missing_platform

        summary: dict[str, Any] = {
            "total": total,
            "matched": matched,
            "mismatched": mismatched,
            "missing_internal": missing_internal,
            "missing_platform": missing_platform,
            "missing_total": missing,
            "total_discrepancy_fen": total_discrepancy,
            "match_rate": round(matched / max(total, 1), 4),
        }

        # 按平台汇总
        platform_summaries: dict[str, dict[str, Any]] = {}
        for pf, st in platform_stats.items():
            pf_total = st["total"]
            platform_summaries[pf] = {
                "platform": pf,
                "platform_label": PLATFORM_LABELS.get(pf, pf),
                "total": pf_total,
                "matched": st["matched"],
                "mismatched": st["mismatched"],
                "missing_internal": st["missing_internal"],
                "missing_platform": st["missing_platform"],
                "total_amount_fen": st["total_amount_fen"],
                "total_commission_fen": st["total_commission_fen"],
                "total_discrepancy_fen": st["total_discrepancy_fen"],
                "match_rate": round(st["matched"] / max(pf_total, 1), 4),
            }

        logger.info(
            "reconciliation.batch_completed",
            total=summary["total"],
            matched=summary["matched"],
            mismatched=summary["mismatched"],
            missing=summary["missing_total"],
            total_discrepancy_fen=summary["total_discrepancy_fen"],
            match_rate=summary["match_rate"],
        )

        return {
            "results": [_record_to_dict(r) for r in results],
            "summary": summary,
            "platform_summaries": platform_summaries,
        }

    # ── T+N 到账跟踪 ──────────────────────────────────────────────────────────

    def track_payment_arrival(
        self,
        platform: str,
        platform_order_id: str,
        internal_order_id: str,
        expected_amount_fen: int,
        actual_arrival_fen: int = 0,
        settlement_date: Optional[str] = None,
    ) -> PaymentArrivalRecord:
        """T+N 到账跟踪。

        根据平台类型确定预期到账日期（T+N），
        对比实际到账金额和日期，标记逾期/部分到账。

        到账判定：
          - 金额一致 + 日期在预期内 → ARRIVED
          - 金额一致 + 日期超期 → OVERDUE
          - 金额不一致 → PARTIAL 或 PENDING
        """
        settle_dt = _parse_date(settlement_date) if settlement_date else datetime.now(timezone.utc)
        delay_days = DEFAULT_CONFIRMATION_DELAY_DAYS.get(platform, 2)

        # 预期到账日 = 结算日 + N 个工作日（简化为 N 个自然日）
        from datetime import timedelta

        expected_arrival = settle_dt + timedelta(days=delay_days)
        expected_arrival_str = expected_arrival.strftime("%Y-%m-%d")

        today = datetime.now(timezone.utc)
        actual_arrival_str: Optional[str] = None
        record_status: PaymentArrivalStatus

        if actual_arrival_fen <= 0:
            # 未到账
            if today >= expected_arrival + timedelta(days=1):
                record_status = PaymentArrivalStatus.OVERDUE
            else:
                record_status = PaymentArrivalStatus.PENDING
        elif actual_arrival_fen == expected_amount_fen:
            # 全额到账
            record_status = PaymentArrivalStatus.ARRIVED
            actual_arrival_str = today.strftime("%Y-%m-%d")
        elif actual_arrival_fen < expected_amount_fen:
            # 部分到账
            record_status = PaymentArrivalStatus.PARTIAL
            actual_arrival_str = today.strftime("%Y-%m-%d")
        else:
            # 超收到账（金额大于预期，需人工确认）
            record_status = PaymentArrivalStatus.DISPUTED
            actual_arrival_str = today.strftime("%Y-%m-%d")

        overdue_days: int = 0
        if record_status == PaymentArrivalStatus.OVERDUE and expected_arrival < today:
            overdue_days = (today - expected_arrival).days

        record = PaymentArrivalRecord(
            platform=platform,
            platform_order_id=platform_order_id,
            internal_order_id=internal_order_id,
            expected_amount_fen=expected_amount_fen,
            actual_arrival_fen=actual_arrival_fen,
            expected_arrival_date=expected_arrival_str,
            actual_arrival_date=actual_arrival_str,
            arrival_status=record_status,
            delay_days=overdue_days,
        )

        arrival_label = ARRIVAL_LABELS.get(record_status, "未知")
        record.notes = (
            f"预期到账: {expected_arrival_str}, "
            f"状态: {arrival_label}"
        )

        logger.info(
            "reconciliation.payment_arrival",
            platform=platform,
            platform_order_id=platform_order_id,
            internal_order_id=internal_order_id,
            expected_fen=expected_amount_fen,
            actual_fen=actual_arrival_fen,
            status=record_status.value,
            delay_days=overdue_days,
        )

        return record

    # ── 报告 ──────────────────────────────────────────────────────────────────

    def get_platform_summary(
        self,
        results: list[SettlementRecord],
    ) -> dict[str, dict[str, Any]]:
        """从对账结果中按平台汇总。

        返回 { platform: { total, matched, mismatched, ... }, ... }
        """
        from collections import defaultdict

        stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "total": 0,
                "matched": 0,
                "mismatched": 0,
                "missing_internal": 0,
                "missing_platform": 0,
                "total_amount_fen": 0,
                "total_commission_fen": 0,
                "total_settlement_fen": 0,
                "total_discrepancy_fen": 0,
            }
        )

        for r in results:
            pf = r.platform
            stats[pf]["total"] += 1
            stats[pf]["total_amount_fen"] += r.platform_amount_fen
            stats[pf]["total_commission_fen"] += r.platform_commission_fen
            stats[pf]["total_settlement_fen"] += r.platform_settlement_fen
            stats[pf]["total_discrepancy_fen"] += r.discrepancy_fen

            if r.status == ReconciliationStatus.MATCHED:
                stats[pf]["matched"] += 1
            elif r.status == ReconciliationStatus.MISMATCH:
                stats[pf]["mismatched"] += 1
            elif r.status == ReconciliationStatus.MISSING_INTERNAL:
                stats[pf]["missing_internal"] += 1
            elif r.status == ReconciliationStatus.MISSING_PLATFORM:
                stats[pf]["missing_platform"] += 1

        # 补充计算字段
        result: dict[str, dict[str, Any]] = {}
        for pf, st in stats.items():
            total = st["total"]
            st["platform_label"] = PLATFORM_LABELS.get(pf, pf)
            st["match_rate"] = round(st["matched"] / max(total, 1), 4)
            st["expected_commission_fen"] = sum(
                self.get_expected_commission(pf, st["total_amount_fen"])
            )
            result[pf] = st

        return result

    def get_discrepancy_report(
        self,
        results: list[SettlementRecord],
        min_discrepancy_fen: int = 100,
    ) -> list[dict[str, Any]]:
        """筛选差异明细报告。

        参数：
          results: 对账结果列表
          min_discrepancy_fen: 最小差异金额阈值（分），默认 100 分（1 元）

        返回差异记录，按 discrepancy_fen 降序排列。
        """
        discrepancies = [
            r
            for r in results
            if r.status
            in (
                ReconciliationStatus.MISMATCH,
                ReconciliationStatus.MISSING_INTERNAL,
                ReconciliationStatus.MISSING_PLATFORM,
            )
            and r.discrepancy_fen >= min_discrepancy_fen
        ]

        # 按差异金额降序
        discrepancies.sort(key=lambda r: r.discrepancy_fen, reverse=True)

        logger.info(
            "reconciliation.discrepancy_report",
            total_discrepancies=len(discrepancies),
            min_discrepancy_fen=min_discrepancy_fen,
            largest_discrepancy_fen=discrepancies[0].discrepancy_fen if discrepancies else 0,
        )

        return [_record_to_dict(r) for r in discrepancies]


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _record_to_dict(record: SettlementRecord) -> dict[str, Any]:
    """将 SettlementRecord 转为可序列化的 dict。"""
    return {
        "platform": record.platform,
        "platform_order_id": record.platform_order_id,
        "platform_amount_fen": record.platform_amount_fen,
        "platform_commission_fen": record.platform_commission_fen,
        "platform_settlement_fen": record.platform_settlement_fen,
        "settlement_date": record.settlement_date,
        "internal_order_id": record.internal_order_id,
        "internal_amount_fen": record.internal_amount_fen,
        "internal_commission_fen": record.internal_commission_fen,
        "status": record.status.value,
        "status_label": RECONCILIATION_LABELS.get(record.status, "未知"),
        "discrepancy_fen": record.discrepancy_fen,
        "notes": record.notes,
    }


def _parse_date(date_str: str) -> datetime:
    """解析 YYYY-MM-DD 字符串为 UTC datetime。"""
    try:
        parts = date_str.split("-")
        return datetime(
            year=int(parts[0]),
            month=int(parts[1]),
            day=int(parts[2]),
            tzinfo=timezone.utc,
        )
    except (IndexError, ValueError, TypeError):
        return datetime.now(timezone.utc)
