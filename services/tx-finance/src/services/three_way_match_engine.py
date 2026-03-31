"""采购三单自动匹配引擎

三单 = 采购订单（supply_orders/purchase_orders）
      × 收货记录（receiving_orders + receiving_items）
      × 供应商发票（purchase_invoices / invoices）

所有金额单位：分（fen）。

匹配状态机：
  pending           → 待匹配（初始状态）
  matched           → 完全匹配（在容差范围内）
  quantity_variance → 收货数量 ≠ 订购数量
  price_variance    → 发票单价 ≠ 采购单价
  missing_invoice   → 已收货但无发票
  missing_receiving → 有采购单但无收货记录
  multi_variance    → 多项差异同时存在
  auto_approved     → 小额差异已自动核销
  resolved          → 人工核销/处理完毕

容差规则（双条件 AND）：
  |发票总额 - 采购总额| ≤ MAX(采购总额 × 1%, 1000分)
  当差异金额 ≤ 1000分（10元）时直接视为匹配。

AI 建议触发：差异 > 50000分（500元）
自动核销：默认 max_amount_fen=10000（100元）
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.three_way_match import ThreeWayMatchRecord

logger = structlog.get_logger()


# ── 常量 ──────────────────────────────────────────────────────────────────────

# 1% 容差率
TOLERANCE_RATE = 0.01
# 绝对容差：10元（1000分）
TOLERANCE_ABS_FEN = 1000
# AI 建议触发阈值：500元（50000分）
AI_SUGGESTION_THRESHOLD_FEN = 50000
# 自动核销默认上限：100元（10000分）
DEFAULT_AUTO_APPROVE_MAX_FEN = 10000


# ── 枚举 ──────────────────────────────────────────────────────────────────────


class MatchStatus(str, Enum):
    PENDING = "pending"
    MATCHED = "matched"
    QUANTITY_VARIANCE = "quantity_variance"
    PRICE_VARIANCE = "price_variance"
    MISSING_INVOICE = "missing_invoice"
    MISSING_RECEIVING = "missing_receiving"
    MULTI_VARIANCE = "multi_variance"
    AUTO_APPROVED = "auto_approved"
    RESOLVED = "resolved"


MATCH_STATUS_LABELS: dict[str, str] = {
    MatchStatus.MATCHED: "完全匹配",
    MatchStatus.QUANTITY_VARIANCE: "数量差异",
    MatchStatus.PRICE_VARIANCE: "价格差异",
    MatchStatus.MISSING_INVOICE: "发票缺失",
    MatchStatus.MISSING_RECEIVING: "未收货",
    MatchStatus.MULTI_VARIANCE: "多项差异",
    MatchStatus.AUTO_APPROVED: "已自动核销",
    MatchStatus.RESOLVED: "已核销",
}


# ── 异常 ──────────────────────────────────────────────────────────────────────


class PurchaseOrderNotFoundError(LookupError):
    """采购订单不存在或不属于该租户"""


class ThreeWayMatchError(RuntimeError):
    """三单匹配执行错误"""


# ── Pydantic 数据模型 ──────────────────────────────────────────────────────────


class LineVariance(BaseModel):
    """单行差异明细"""

    ingredient_name: str
    type: str  # quantity_variance / price_variance
    po_qty: Optional[float] = None
    recv_qty: Optional[float] = None
    po_unit_price_fen: Optional[int] = None
    inv_unit_price_fen: Optional[int] = None
    variance_fen: int = 0
    note: str = ""


class MatchResult(BaseModel):
    """单笔三单匹配结果"""

    purchase_order_id: str
    status: MatchStatus
    po_amount_fen: int = 0
    recv_amount_fen: int = 0
    inv_amount_fen: Optional[int] = None
    variance_amount_fen: int = 0
    line_variances: list[dict[str, Any]] = Field(default_factory=list)
    suggestion: Optional[str] = None
    matched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BatchMatchResult(BaseModel):
    """批量匹配汇总结果"""

    tenant_id: str
    total: int = 0
    matched: int = 0
    variance_count: int = 0
    missing_count: int = 0
    auto_approved: int = 0
    total_variance_fen: int = 0
    results: list[MatchResult] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VarianceItem(BaseModel):
    """差异报告中的单条差异记录"""

    id: str
    purchase_order_id: str
    tenant_id: str
    supplier_id: str
    status: MatchStatus
    variance_amount_fen: int
    po_amount_fen: int
    recv_amount_fen: int
    inv_amount_fen: Optional[int] = None
    line_variances: list[dict[str, Any]] = Field(default_factory=list)
    suggestion: Optional[str] = None
    created_at: datetime


# ── 内部计算结果（非 Pydantic，仅引擎内部使用） ──────────────────────────────


class _ComputeResult:
    """_compute_match_status 的返回值"""

    def __init__(
        self,
        status: MatchStatus,
        variance_amount_fen: int,
        recv_amount_fen: int,
        inv_amount_fen: Optional[int],
        line_variances: list[dict[str, Any]],
    ) -> None:
        self.status = status
        self.variance_amount_fen = variance_amount_fen
        self.recv_amount_fen = recv_amount_fen
        self.inv_amount_fen = inv_amount_fen
        self.line_variances = line_variances


# ── 三单匹配引擎 ──────────────────────────────────────────────────────────────


class ThreeWayMatchEngine:
    """采购三单自动匹配引擎

    对外方法：
      match_purchase_order()      — 单笔三单匹配
      batch_match()               — 批量匹配
      get_variance_report()       — 差异报告
      suggest_variance_resolution() — AI 差异建议
      auto_approve_small_variances() — 自动核销小额差异

    内部方法（可在测试中 mock）：
      _fetch_purchase_order()
      _fetch_receiving_orders()
      _fetch_purchase_invoices()
      _fetch_pending_purchase_orders()
      _fetch_small_variances()
      _save_match_result()
      _approve_variance()
      _compute_match_status()     — 纯函数，无副作用
      _should_trigger_ai()
      _can_auto_approve()
    """

    # ── 公开接口 ───────────────────────────────────────────────────────────────

    async def match_purchase_order(
        self,
        purchase_order_id: str,
        tenant_id: str,
        db: AsyncSession,
        model_router: Any = None,
    ) -> MatchResult:
        """对单笔采购订单执行三单匹配。

        流程：
        1. 查采购订单（含明细）
        2. 查收货记录（receiving_orders / receiving_items）
        3. 查供应商发票（purchase_invoices）
        4. 按明细逐行比对数量和单价
        5. 汇总差异，判定匹配状态
        6. 差异 > 50000分时调用 AI 生成建议
        7. 写入 purchase_match_records
        8. 返回 MatchResult
        """
        log = logger.bind(
            purchase_order_id=purchase_order_id,
            tenant_id=tenant_id,
        )
        log.info("three_way_match.start")

        # 1. 查采购订单
        po = await self._fetch_purchase_order(purchase_order_id, tenant_id, db)
        if po is None:
            raise PurchaseOrderNotFoundError(
                f"采购订单 {purchase_order_id} 不存在或不属于租户 {tenant_id}"
            )

        po_items: list[dict] = po.get("items", [])
        po_total_fen: int = int(po.get("total_amount_fen", 0))

        # 2. 查收货记录
        receiving_orders = await self._fetch_receiving_orders(purchase_order_id, tenant_id, db)
        recv_items: list[dict] | None = None
        if receiving_orders:
            recv_items = []
            for ro in receiving_orders:
                recv_items.extend(ro.get("items", []))

        # 3. 查供应商发票
        invoices = await self._fetch_purchase_invoices(purchase_order_id, tenant_id, db)
        inv_items: list[dict] | None = None
        inv_total_fen: int | None = None
        if invoices:
            inv_items = []
            inv_total_fen = 0
            for inv in invoices:
                inv_items.extend(inv.get("items", []))
                inv_total_fen += int(inv.get("amount_fen", 0))

        # 4. 核心匹配计算
        compute = self._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=po_total_fen,
            inv_total_fen=inv_total_fen,
        )

        # 5. AI 建议（仅差异 > 50000分时触发）
        suggestion: str | None = None
        if model_router is not None and compute.variance_amount_fen > AI_SUGGESTION_THRESHOLD_FEN:
            variance_item = VarianceItem(
                id=str(uuid.uuid4()),
                purchase_order_id=purchase_order_id,
                tenant_id=tenant_id,
                supplier_id=str(po.get("supplier_id", "")),
                status=compute.status,
                variance_amount_fen=compute.variance_amount_fen,
                po_amount_fen=po_total_fen,
                recv_amount_fen=compute.recv_amount_fen,
                inv_amount_fen=compute.inv_amount_fen,
                line_variances=compute.line_variances,
                created_at=datetime.now(timezone.utc),
            )
            try:
                suggestion = await self.suggest_variance_resolution(variance_item, model_router)
            except Exception as exc:
                log.warning("three_way_match.ai_suggestion_failed", error=str(exc))
                suggestion = None

        result = MatchResult(
            purchase_order_id=purchase_order_id,
            status=compute.status,
            po_amount_fen=po_total_fen,
            recv_amount_fen=compute.recv_amount_fen,
            inv_amount_fen=compute.inv_amount_fen,
            variance_amount_fen=compute.variance_amount_fen,
            line_variances=compute.line_variances,
            suggestion=suggestion,
        )

        # 6. 持久化
        await self._save_match_result(result, po, db)

        log.info(
            "three_way_match.done",
            status=result.status,
            variance_fen=result.variance_amount_fen,
        )
        return result

    async def batch_match(
        self,
        tenant_id: str,
        db: AsyncSession,
        supplier_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> BatchMatchResult:
        """批量执行三单匹配，支持按供应商/日期区间筛选。

        返回统计：total / matched / variance_count / missing_count
        """
        logger.info(
            "batch_match.start",
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            date_from=str(date_from),
            date_to=str(date_to),
        )

        po_ids = await self._fetch_pending_purchase_orders(
            tenant_id=tenant_id,
            db=db,
            supplier_id=supplier_id,
            date_from=date_from,
            date_to=date_to,
        )

        batch = BatchMatchResult(tenant_id=tenant_id, total=len(po_ids))

        for po_id in po_ids:
            try:
                result = await self.match_purchase_order(
                    purchase_order_id=po_id,
                    tenant_id=tenant_id,
                    db=db,
                )
                batch.results.append(result)
                batch.total_variance_fen += result.variance_amount_fen

                if result.status == MatchStatus.MATCHED:
                    batch.matched += 1
                elif result.status in (
                    MatchStatus.MISSING_INVOICE,
                    MatchStatus.MISSING_RECEIVING,
                ):
                    batch.missing_count += 1
                else:
                    batch.variance_count += 1

            except PurchaseOrderNotFoundError:
                logger.warning("batch_match.po_not_found", po_id=po_id, tenant_id=tenant_id)
            except ThreeWayMatchError as exc:
                logger.error("batch_match.match_error", po_id=po_id, error=str(exc))

        logger.info(
            "batch_match.done",
            tenant_id=tenant_id,
            total=batch.total,
            matched=batch.matched,
            variance=batch.variance_count,
            missing=batch.missing_count,
        )
        return batch

    async def get_variance_report(
        self,
        tenant_id: str,
        db: AsyncSession,
        period_days: int = 30,
    ) -> list[VarianceItem]:
        """差异汇总报告：近 period_days 天内，按差异金额降序排列。"""
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        tid = uuid.UUID(tenant_id)

        result = await db.execute(
            select(ThreeWayMatchRecord)
            .where(
                and_(
                    ThreeWayMatchRecord.tenant_id == tid,
                    ThreeWayMatchRecord.is_deleted.is_(False),
                    ThreeWayMatchRecord.status.not_in([
                        MatchStatus.MATCHED.value,
                        MatchStatus.AUTO_APPROVED.value,
                        MatchStatus.RESOLVED.value,
                    ]),
                    ThreeWayMatchRecord.created_at >= cutoff,
                )
            )
            .order_by(ThreeWayMatchRecord.variance_amount_fen.desc())
        )
        records = result.scalars().all()

        return [
            VarianceItem(
                id=str(r.id),
                purchase_order_id=str(r.purchase_order_id),
                tenant_id=str(r.tenant_id),
                supplier_id=str(r.supplier_id) if r.supplier_id else "",
                status=MatchStatus(r.status),
                variance_amount_fen=r.variance_amount_fen,
                po_amount_fen=r.po_amount_fen,
                recv_amount_fen=r.recv_amount_fen,
                inv_amount_fen=r.inv_amount_fen,
                line_variances=r.line_variances or [],
                suggestion=r.suggestion,
                created_at=r.created_at,
            )
            for r in records
        ]

    async def suggest_variance_resolution(
        self,
        variance_item: VarianceItem,
        model_router: Any,
    ) -> str:
        """AI 差异处理建议（仅当差异金额 > 50000分时调用）。

        分析维度：
        - 季节性价格波动（价格差异）
        - 计量/损耗误差（数量差异）
        - 发票开具错误（金额差异）
        - 建议处理方式（联系供应商/要求重开发票/自动核销）
        """
        amount_yuan = variance_item.variance_amount_fen / 100
        po_yuan = variance_item.po_amount_fen / 100
        variance_ratio = (
            variance_item.variance_amount_fen / variance_item.po_amount_fen
            if variance_item.po_amount_fen > 0
            else 0.0
        )

        prompt = f"""你是餐饮集团财务对账专家。请分析以下采购三单匹配差异，提供简洁的处理建议。

差异类型：{MATCH_STATUS_LABELS.get(variance_item.status, variance_item.status)}
采购金额：{po_yuan:.2f}元
差异金额：{amount_yuan:.2f}元（差异率 {variance_ratio:.1%}）
差异明细：{variance_item.line_variances}

请从以下角度分析（每点1-2句）：
1. 最可能的差异原因（季节性价格波动/计量误差/发票错误/其他）
2. 建议处理方式（联系供应商确认/要求重开发票/按实际结算/申请退款）
3. 风险提示（如有）

输出不超过150字，直接给出结论，无需客套。"""

        suggestion = await model_router.complete(
            prompt=prompt,
            system="你是专业餐饮财务对账顾问，回答精准简洁。",
            max_tokens=300,
        )
        return str(suggestion)

    async def auto_approve_small_variances(
        self,
        tenant_id: str,
        db: AsyncSession,
        max_amount_fen: int = DEFAULT_AUTO_APPROVE_MAX_FEN,
    ) -> int:
        """自动核销小额差异，返回处理数量。

        核销条件：
        - 差异金额 ≤ max_amount_fen
        - 状态为有差异（非 matched/resolved/auto_approved）
        - 写入审计日志
        """
        variance_ids = await self._fetch_small_variances(
            tenant_id=tenant_id,
            max_amount_fen=max_amount_fen,
            db=db,
        )

        count = 0
        for vid in variance_ids:
            try:
                await self._approve_variance(
                    variance_id=vid,
                    tenant_id=tenant_id,
                    note=f"系统自动核销（差异≤{max_amount_fen/100:.0f}元）",
                    db=db,
                )
                count += 1
            except ThreeWayMatchError as exc:
                logger.error(
                    "auto_approve.single_failed",
                    variance_id=vid,
                    error=str(exc),
                )

        logger.info(
            "auto_approve.done",
            tenant_id=tenant_id,
            count=count,
            max_amount_fen=max_amount_fen,
        )
        return count

    # ── 核心匹配计算（纯函数，无副作用，易于单元测试）────────────────────────

    def _compute_match_status(
        self,
        po_items: list[dict],
        recv_items: list[dict] | None,
        inv_items: list[dict] | None,
        po_total_fen: int,
        inv_total_fen: int | None,
    ) -> _ComputeResult:
        """逐行比对数量、单价，判定匹配状态。

        返回 _ComputeResult（含 status / variance_amount_fen / line_variances）。
        """
        # 无收货记录
        if recv_items is None or len(recv_items) == 0:
            return _ComputeResult(
                status=MatchStatus.MISSING_RECEIVING,
                variance_amount_fen=po_total_fen,
                recv_amount_fen=0,
                inv_amount_fen=inv_total_fen,
                line_variances=[],
            )

        # 无发票
        if inv_items is None or len(inv_items) == 0:
            recv_amount_fen = self._sum_recv_amount(recv_items)
            return _ComputeResult(
                status=MatchStatus.MISSING_INVOICE,
                variance_amount_fen=po_total_fen,
                recv_amount_fen=recv_amount_fen,
                inv_amount_fen=None,
                line_variances=[],
            )

        # 汇总收货金额
        recv_amount_fen = self._sum_recv_amount(recv_items)

        # 逐行比对
        line_variances: list[dict] = []
        qty_variance = False
        price_variance = False

        # 建立按名称索引的 dict（简化匹配，生产环境应按 ingredient_id 匹配）
        recv_map = self._build_item_map(recv_items, qty_key="received_qty")
        inv_map = self._build_item_map(inv_items, qty_key="qty")

        for po_item in po_items:
            name = po_item.get("ingredient_name", "")
            po_qty = float(po_item.get("qty", 0))
            po_price = int(po_item.get("unit_price_fen", 0))

            recv_entry = recv_map.get(name)
            inv_entry = inv_map.get(name)

            recv_qty = float(recv_entry.get("received_qty", 0)) if recv_entry else 0.0
            inv_qty = float(inv_entry.get("qty", 0)) if inv_entry else 0.0
            inv_price = int(inv_entry.get("unit_price_fen", 0)) if inv_entry else 0

            # 数量差异：收货数量 < 采购数量（超收不报为差异）
            qty_diff = po_qty - recv_qty
            if qty_diff > 0.001:  # 允许极小浮点误差
                variance_fen = round(qty_diff * po_price)
                line_variances.append({
                    "ingredient_name": name,
                    "type": "quantity_variance",
                    "po_qty": po_qty,
                    "recv_qty": recv_qty,
                    "po_unit_price_fen": po_price,
                    "variance_fen": variance_fen,
                    "note": f"收货少{qty_diff:.2f}件，差{variance_fen/100:.2f}元",
                })
                qty_variance = True

            # 价格差异：发票单价 ≠ 采购单价（在容差外）
            if inv_price > 0 and po_price > 0:
                price_diff_fen = abs(inv_price - po_price) * max(1, round(inv_qty))
                if not self._within_tolerance(abs(inv_price - po_price), po_price):
                    variance_fen = round(abs(inv_price - po_price) * inv_qty)
                    line_variances.append({
                        "ingredient_name": name,
                        "type": "price_variance",
                        "po_qty": po_qty,
                        "recv_qty": recv_qty,
                        "po_unit_price_fen": po_price,
                        "inv_unit_price_fen": inv_price,
                        "variance_fen": variance_fen,
                        "note": (
                            f"发票价{inv_price/100:.2f}元 vs 采购价{po_price/100:.2f}元，"
                            f"差{(inv_price - po_price)/100:.2f}元/件"
                        ),
                    })
                    price_variance = True

        # 总金额差异
        total_variance_fen = abs((inv_total_fen or 0) - po_total_fen)

        # 容差判断（总额级别）：满足任一条件视为匹配
        is_within_tolerance = self._within_tolerance_total(total_variance_fen, po_total_fen)

        # 确定最终状态
        if is_within_tolerance and not line_variances:
            status = MatchStatus.MATCHED
            total_variance_fen = 0
        elif is_within_tolerance and line_variances:
            # 行级有小差异但总额在容差内，仍视为匹配
            status = MatchStatus.MATCHED
            total_variance_fen = 0
            line_variances = []
        elif qty_variance and price_variance:
            status = MatchStatus.MULTI_VARIANCE
        elif qty_variance:
            status = MatchStatus.QUANTITY_VARIANCE
        elif price_variance:
            status = MatchStatus.PRICE_VARIANCE
        else:
            # 总额差异但无法定位到行级（可能是运费/税额等）
            status = MatchStatus.PRICE_VARIANCE

        return _ComputeResult(
            status=status,
            variance_amount_fen=total_variance_fen,
            recv_amount_fen=recv_amount_fen,
            inv_amount_fen=inv_total_fen,
            line_variances=line_variances,
        )

    # ── 辅助工具 ──────────────────────────────────────────────────────────────

    def _within_tolerance(self, diff_fen: int, base_fen: int) -> bool:
        """单价级别容差判断（单位价格差）"""
        if diff_fen == 0:
            return True
        if base_fen == 0:
            return False
        return diff_fen / base_fen <= TOLERANCE_RATE

    def _within_tolerance_total(self, variance_fen: int, po_total_fen: int) -> bool:
        """总额级别容差判断。

        满足任一条件视为容差内（匹配）：
        1. 差异 ≤ 1000分（10元）
        2. 差异率 ≤ 1%
        """
        if variance_fen <= TOLERANCE_ABS_FEN:
            return True
        if po_total_fen > 0 and variance_fen / po_total_fen <= TOLERANCE_RATE:
            return True
        return False

    def _should_trigger_ai(self, variance_item: VarianceItem) -> bool:
        """判断是否触发 AI 建议：差异金额 > 50000分（500元）"""
        return variance_item.variance_amount_fen > AI_SUGGESTION_THRESHOLD_FEN

    def _can_auto_approve(self, variance_amount_fen: int, max_amount_fen: int) -> bool:
        """判断是否可自动核销：差异 ≤ max_amount_fen"""
        return variance_amount_fen <= max_amount_fen

    @staticmethod
    def _sum_recv_amount(recv_items: list[dict]) -> int:
        """汇总收货金额（分）"""
        total = 0
        for item in recv_items:
            qty = float(item.get("received_qty", 0) or 0)
            price = int(item.get("unit_price_fen", 0) or 0)
            total += round(qty * price)
        return total

    @staticmethod
    def _build_item_map(items: list[dict], qty_key: str) -> dict[str, dict]:
        """按 ingredient_name 构建索引 dict（同名合并）"""
        result: dict[str, dict] = {}
        for item in items:
            name = item.get("ingredient_name", "")
            if name not in result:
                result[name] = dict(item)
            else:
                # 合并同名条目（累加数量）
                existing_qty = float(result[name].get(qty_key, 0) or 0)
                new_qty = float(item.get(qty_key, 0) or 0)
                result[name][qty_key] = existing_qty + new_qty
        return result

    # ── DB 访问层（可在测试中 mock）──────────────────────────────────────────

    async def _fetch_purchase_order(
        self,
        purchase_order_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict | None:
        """查采购订单（supply_orders 表）。

        注意：所有查询必须带 tenant_id（RLS 额外保障）。
        返回 dict 或 None（不存在/无权限）。
        """
        from sqlalchemy import text

        tid = uuid.UUID(tenant_id)
        pid = uuid.UUID(purchase_order_id)

        result = await db.execute(
            text("""
                SELECT id, tenant_id, supplier_id, store_id, order_number,
                       status, total_amount_fen, items, created_at
                FROM supply_orders
                WHERE id = :po_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"po_id": pid, "tenant_id": tid},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def _fetch_receiving_orders(
        self,
        purchase_order_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict]:
        """查收货记录（receiving_orders + receiving_items）。"""
        from sqlalchemy import text

        tid = uuid.UUID(tenant_id)
        pid = uuid.UUID(purchase_order_id)

        # 查收货单
        ro_result = await db.execute(
            text("""
                SELECT id, tenant_id, purchase_order_id, status, received_at
                FROM receiving_orders
                WHERE purchase_order_id = :po_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status = 'confirmed'
            """),
            {"po_id": pid, "tenant_id": tid},
        )
        ro_rows = ro_result.mappings().all()
        if not ro_rows:
            return []

        # 查每张收货单的明细
        orders: list[dict] = []
        for ro in ro_rows:
            ri_result = await db.execute(
                text("""
                    SELECT ingredient_name, unit, ordered_qty, received_qty, unit_price_fen
                    FROM receiving_items
                    WHERE receiving_order_id = :ro_id
                      AND tenant_id = :tenant_id
                """),
                {"ro_id": ro["id"], "tenant_id": tid},
            )
            items = [dict(r) for r in ri_result.mappings().all()]
            orders.append({**dict(ro), "items": items})

        return orders

    async def _fetch_purchase_invoices(
        self,
        purchase_order_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict]:
        """查供应商发票（purchase_invoices 表）。

        purchase_invoices 是采购对账专用发票表（区别于 invoices 销售发票表）。
        字段：purchase_order_id / amount_fen / items / status
        """
        from sqlalchemy import text

        tid = uuid.UUID(tenant_id)
        pid = uuid.UUID(purchase_order_id)

        result = await db.execute(
            text("""
                SELECT id, tenant_id, purchase_order_id, invoice_no,
                       amount_fen, status, issued_at, items
                FROM purchase_invoices
                WHERE purchase_order_id = :po_id
                  AND tenant_id = :tenant_id
                  AND status = 'confirmed'
                  AND is_deleted = FALSE
            """),
            {"po_id": pid, "tenant_id": tid},
        )
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def _fetch_pending_purchase_orders(
        self,
        tenant_id: str,
        db: AsyncSession,
        supplier_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[str]:
        """查待匹配的采购订单 ID 列表（状态为 delivered/completed）。"""
        from sqlalchemy import text

        tid = uuid.UUID(tenant_id)

        conditions = [
            "tenant_id = :tenant_id",
            "is_deleted = FALSE",
            "status IN ('delivered', 'completed')",
        ]
        params: dict[str, Any] = {"tenant_id": tid}

        if supplier_id:
            conditions.append("supplier_id = :supplier_id")
            params["supplier_id"] = uuid.UUID(supplier_id)

        if date_from:
            conditions.append("created_at >= :date_from")
            params["date_from"] = datetime.combine(date_from, datetime.min.time()).replace(
                tzinfo=timezone.utc
            )

        if date_to:
            conditions.append("created_at <= :date_to")
            params["date_to"] = datetime.combine(date_to, datetime.max.time()).replace(
                tzinfo=timezone.utc
            )

        where_clause = " AND ".join(conditions)
        result = await db.execute(
            text(f"SELECT id FROM supply_orders WHERE {where_clause} ORDER BY created_at"),
            params,
        )
        return [str(row[0]) for row in result.all()]

    async def _fetch_small_variances(
        self,
        tenant_id: str,
        max_amount_fen: int,
        db: AsyncSession,
    ) -> list[str]:
        """查差异金额 ≤ max_amount_fen 的待处理差异记录 ID。"""
        tid = uuid.UUID(tenant_id)

        result = await db.execute(
            select(ThreeWayMatchRecord.id)
            .where(
                and_(
                    ThreeWayMatchRecord.tenant_id == tid,
                    ThreeWayMatchRecord.is_deleted.is_(False),
                    ThreeWayMatchRecord.status.not_in([
                        MatchStatus.MATCHED.value,
                        MatchStatus.AUTO_APPROVED.value,
                        MatchStatus.RESOLVED.value,
                    ]),
                    ThreeWayMatchRecord.variance_amount_fen <= max_amount_fen,
                    ThreeWayMatchRecord.variance_amount_fen > 0,
                )
            )
        )
        return [str(row[0]) for row in result.all()]

    async def _save_match_result(
        self,
        result: MatchResult,
        po: dict,
        db: AsyncSession,
    ) -> None:
        """将匹配结果写入 purchase_match_records（upsert by purchase_order_id）。"""
        from sqlalchemy import text

        tid = uuid.UUID(str(po.get("tenant_id", "")))
        pid = uuid.UUID(result.purchase_order_id)
        supplier_id = po.get("supplier_id")
        store_id = po.get("store_id")

        # 查是否已有记录（同一采购单已有匹配结果）
        existing = await db.execute(
            select(ThreeWayMatchRecord.id).where(
                and_(
                    ThreeWayMatchRecord.tenant_id == tid,
                    ThreeWayMatchRecord.purchase_order_id == pid,
                    ThreeWayMatchRecord.is_deleted.is_(False),
                )
            )
        )
        existing_id = existing.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing_id is not None:
            # 更新
            await db.execute(
                update(ThreeWayMatchRecord)
                .where(ThreeWayMatchRecord.id == existing_id)
                .values(
                    status=result.status.value,
                    po_amount_fen=result.po_amount_fen,
                    recv_amount_fen=result.recv_amount_fen,
                    inv_amount_fen=result.inv_amount_fen,
                    variance_amount_fen=result.variance_amount_fen,
                    line_variances=result.line_variances,
                    suggestion=result.suggestion,
                    matched_at=now,
                    updated_at=now,
                )
            )
        else:
            # 新建
            record = ThreeWayMatchRecord(
                id=uuid.uuid4(),
                tenant_id=tid,
                purchase_order_id=pid,
                supplier_id=uuid.UUID(str(supplier_id)) if supplier_id else None,
                store_id=uuid.UUID(str(store_id)) if store_id else None,
                status=result.status.value,
                po_amount_fen=result.po_amount_fen,
                recv_amount_fen=result.recv_amount_fen,
                inv_amount_fen=result.inv_amount_fen,
                variance_amount_fen=result.variance_amount_fen,
                line_variances=result.line_variances,
                suggestion=result.suggestion,
                matched_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(record)

        await db.flush()

    async def _approve_variance(
        self,
        variance_id: str,
        tenant_id: str,
        note: str,
        db: AsyncSession,
        resolved_by: str | None = None,
    ) -> None:
        """核销单条差异记录，写入审计信息。"""
        tid = uuid.UUID(tenant_id)
        vid = uuid.UUID(variance_id)
        now = datetime.now(timezone.utc)

        result = await db.execute(
            select(ThreeWayMatchRecord).where(
                and_(
                    ThreeWayMatchRecord.id == vid,
                    ThreeWayMatchRecord.tenant_id == tid,
                    ThreeWayMatchRecord.is_deleted.is_(False),
                )
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise ThreeWayMatchError(f"差异记录 {variance_id} 不存在或已删除")

        record.status = MatchStatus.AUTO_APPROVED.value
        record.resolved_at = now
        record.resolution_note = note
        record.updated_at = now
        if resolved_by:
            record.resolved_by = uuid.UUID(resolved_by)

        await db.flush()

        logger.info(
            "variance.approved",
            variance_id=variance_id,
            tenant_id=tenant_id,
            note=note,
        )
