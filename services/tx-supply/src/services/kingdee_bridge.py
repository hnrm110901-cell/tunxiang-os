"""金蝶ERP桥接层 — 屯象OS业务数据 → 金蝶K3/Cloud凭证格式

Mock接口，结构与金蝶K3/Cloud兼容。
凭证格式: {voucher_type, date, entries: [{account, debit_fen, credit_fen, summary}]}
金额单位: 分(fen), int类型。
导出状态: pending → processing → completed / failed
"""
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ─── 导出状态常量 ───

EXPORT_STATUS_PENDING = "pending"
EXPORT_STATUS_PROCESSING = "processing"
EXPORT_STATUS_COMPLETED = "completed"
EXPORT_STATUS_FAILED = "failed"

# ─── 金蝶科目编码常量 ───

ACCOUNT_RAW_MATERIAL = "1403"       # 原材料
ACCOUNT_AP = "2202"                 # 应付账款
ACCOUNT_MAIN_BIZ_COST = "5401"     # 主营业务成本
ACCOUNT_GOODS_IN_TRANSIT = "1406"   # 在途物资
ACCOUNT_SALARY_PAYABLE = "2211"     # 应付职工薪酬
ACCOUNT_ADMIN_EXPENSE = "5602"      # 管理费用-工资
ACCOUNT_CASH = "1001"               # 库存现金
ACCOUNT_BANK = "1002"               # 银行存款
ACCOUNT_WECHAT_PAY = "1012.01"     # 微信收款
ACCOUNT_ALIPAY = "1012.02"         # 支付宝收款
ACCOUNT_MAIN_BIZ_REVENUE = "5001"  # 主营业务收入
ACCOUNT_INVENTORY_GOODS = "1405"   # 库存商品


def _make_voucher_entry(
    account: str,
    debit_fen: int = 0,
    credit_fen: int = 0,
    summary: str = "",
) -> dict:
    """构建一条金蝶凭证分录"""
    return {
        "account": account,
        "debit_fen": debit_fen,
        "credit_fen": credit_fen,
        "summary": summary,
    }


def _make_export_record(
    export_type: str,
    store_id: str,
    period: str,
    tenant_id: str,
    voucher: dict,
) -> dict:
    """构建导出记录"""
    return {
        "export_id": uuid.uuid4().hex,
        "export_type": export_type,
        "store_id": store_id,
        "period": period,
        "tenant_id": tenant_id,
        "status": EXPORT_STATUS_COMPLETED,
        "voucher": voucher,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "error_message": None,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 采购入库汇总 → 金蝶凭证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def export_purchase_receipt(
    store_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """采购入库汇总 → 金蝶记账凭证

    借: 原材料(1403)
    贷: 应付账款(2202)

    Args:
        store_id: 门店ID
        month: 月份 YYYY-MM
        tenant_id: 租户ID
        db: 异步数据库会话

    Returns:
        导出记录(含凭证)
    """
    log.info(
        "kingdee.export_purchase_receipt",
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
    )

    start_date = f"{month}-01"
    # 月末: 用下月第一天减一天的方式
    result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(it.cost_fen), 0) AS total_cost_fen,
                COUNT(*) AS tx_count
            FROM inventory_transactions it
            WHERE it.tenant_id = :tenant_id
              AND it.store_id = :store_id::UUID
              AND it.is_deleted = FALSE
              AND it.tx_type = 'purchase'
              AND it.tx_date >= :start_date::DATE
              AND it.tx_date < (:start_date::DATE + INTERVAL '1 month')
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "start_date": start_date},
    )
    row = result.mappings().first()
    total_fen = row["total_cost_fen"] if row else 0
    tx_count = row["tx_count"] if row else 0

    voucher = {
        "voucher_type": "记",
        "date": f"{month}-01",
        "entries": [
            _make_voucher_entry(
                ACCOUNT_RAW_MATERIAL,
                debit_fen=total_fen,
                summary=f"{month}采购入库汇总({tx_count}笔)",
            ),
            _make_voucher_entry(
                ACCOUNT_AP,
                credit_fen=total_fen,
                summary=f"{month}采购入库应付",
            ),
        ],
        "total_debit_fen": total_fen,
        "total_credit_fen": total_fen,
    }

    return _make_export_record(
        "purchase_receipt", store_id, month, tenant_id, voucher,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 成本结转汇总 → 金蝶凭证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def export_cost_transfer(
    store_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """成本结转汇总 → 金蝶记账凭证

    借: 主营业务成本(5401)
    贷: 原材料(1403)

    Args:
        store_id: 门店ID
        month: 月份 YYYY-MM
        tenant_id: 租户ID
        db: 异步数据库会话
    """
    log.info(
        "kingdee.export_cost_transfer",
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
    )

    start_date = f"{month}-01"
    result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(it.cost_fen), 0) AS total_cost_fen,
                COUNT(*) AS tx_count
            FROM inventory_transactions it
            WHERE it.tenant_id = :tenant_id
              AND it.store_id = :store_id::UUID
              AND it.is_deleted = FALSE
              AND it.tx_type = 'usage'
              AND it.tx_date >= :start_date::DATE
              AND it.tx_date < (:start_date::DATE + INTERVAL '1 month')
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "start_date": start_date},
    )
    row = result.mappings().first()
    total_fen = row["total_cost_fen"] if row else 0
    tx_count = row["tx_count"] if row else 0

    voucher = {
        "voucher_type": "转",
        "date": f"{month}-01",
        "entries": [
            _make_voucher_entry(
                ACCOUNT_MAIN_BIZ_COST,
                debit_fen=total_fen,
                summary=f"{month}成本结转({tx_count}笔消耗)",
            ),
            _make_voucher_entry(
                ACCOUNT_RAW_MATERIAL,
                credit_fen=total_fen,
                summary=f"{month}原材料消耗结转",
            ),
        ],
        "total_debit_fen": total_fen,
        "total_credit_fen": total_fen,
    }

    return _make_export_record(
        "cost_transfer", store_id, month, tenant_id, voucher,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 调拨出入库汇总 → 金蝶凭证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def export_transfer_in_out(
    store_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """调拨出入库汇总 → 金蝶凭证

    调出: 借 在途物资(1406) / 贷 原材料(1403)
    调入: 借 原材料(1403) / 贷 在途物资(1406)
    """
    log.info(
        "kingdee.export_transfer_in_out",
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
    )

    start_date = f"{month}-01"
    # 调出金额
    result_out = await db.execute(
        text("""
            SELECT COALESCE(SUM(it.cost_fen), 0) AS total_fen, COUNT(*) AS cnt
            FROM inventory_transactions it
            WHERE it.tenant_id = :tenant_id
              AND it.store_id = :store_id::UUID
              AND it.is_deleted = FALSE
              AND it.tx_type = 'transfer_out'
              AND it.tx_date >= :start_date::DATE
              AND it.tx_date < (:start_date::DATE + INTERVAL '1 month')
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "start_date": start_date},
    )
    row_out = result_out.mappings().first()
    out_fen = row_out["total_fen"] if row_out else 0
    out_cnt = row_out["cnt"] if row_out else 0

    # 调入金额
    result_in = await db.execute(
        text("""
            SELECT COALESCE(SUM(it.cost_fen), 0) AS total_fen, COUNT(*) AS cnt
            FROM inventory_transactions it
            WHERE it.tenant_id = :tenant_id
              AND it.to_store_id = :store_id::UUID
              AND it.is_deleted = FALSE
              AND it.tx_type = 'transfer_in'
              AND it.tx_date >= :start_date::DATE
              AND it.tx_date < (:start_date::DATE + INTERVAL '1 month')
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "start_date": start_date},
    )
    row_in = result_in.mappings().first()
    in_fen = row_in["total_fen"] if row_in else 0
    in_cnt = row_in["cnt"] if row_in else 0

    entries = []
    if out_fen > 0:
        entries.extend([
            _make_voucher_entry(
                ACCOUNT_GOODS_IN_TRANSIT,
                debit_fen=out_fen,
                summary=f"{month}调拨出库({out_cnt}笔)",
            ),
            _make_voucher_entry(
                ACCOUNT_RAW_MATERIAL,
                credit_fen=out_fen,
                summary=f"{month}调拨出库-原材料减少",
            ),
        ])
    if in_fen > 0:
        entries.extend([
            _make_voucher_entry(
                ACCOUNT_RAW_MATERIAL,
                debit_fen=in_fen,
                summary=f"{month}调拨入库({in_cnt}笔)",
            ),
            _make_voucher_entry(
                ACCOUNT_GOODS_IN_TRANSIT,
                credit_fen=in_fen,
                summary=f"{month}调拨入库-在途冲减",
            ),
        ])

    voucher = {
        "voucher_type": "转",
        "date": f"{month}-01",
        "entries": entries,
        "total_debit_fen": out_fen + in_fen,
        "total_credit_fen": out_fen + in_fen,
    }

    return _make_export_record(
        "transfer_in_out", store_id, month, tenant_id, voucher,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 工资计提 → 金蝶凭证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def export_salary_accrual(
    store_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """工资计提 → 金蝶凭证

    借: 管理费用-工资(5602)
    贷: 应付职工薪酬(2211)
    """
    log.info(
        "kingdee.export_salary_accrual",
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
    )

    start_date = f"{month}-01"
    result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(p.base_salary_fen + COALESCE(p.bonus_fen, 0)
                             + COALESCE(p.overtime_fen, 0)), 0) AS total_salary_fen,
                COUNT(*) AS employee_count
            FROM payroll_records p
            WHERE p.tenant_id = :tenant_id
              AND p.store_id = :store_id::UUID
              AND p.is_deleted = FALSE
              AND p.pay_month = :month
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "month": month},
    )
    row = result.mappings().first()
    total_fen = row["total_salary_fen"] if row else 0
    emp_count = row["employee_count"] if row else 0

    voucher = {
        "voucher_type": "记",
        "date": f"{month}-01",
        "entries": [
            _make_voucher_entry(
                ACCOUNT_ADMIN_EXPENSE,
                debit_fen=total_fen,
                summary=f"{month}工资计提({emp_count}人)",
            ),
            _make_voucher_entry(
                ACCOUNT_SALARY_PAYABLE,
                credit_fen=total_fen,
                summary=f"{month}应付工资",
            ),
        ],
        "total_debit_fen": total_fen,
        "total_credit_fen": total_fen,
    }

    return _make_export_record(
        "salary_accrual", store_id, month, tenant_id, voucher,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 收营日报 → 金蝶凭证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def export_daily_revenue(
    store_id: str,
    date_str: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """收营日报 → 金蝶凭证

    按支付方式生成分录:
      借: 库存现金/银行存款/微信/支付宝
      贷: 主营业务收入(5001)
    """
    log.info(
        "kingdee.export_daily_revenue",
        store_id=store_id,
        date=date_str,
        tenant_id=tenant_id,
    )

    result = await db.execute(
        text("""
            SELECT
                p.pay_method,
                COALESCE(SUM(p.amount_fen), 0) AS amount_fen,
                COUNT(*) AS pay_count
            FROM payments p
            JOIN orders o ON p.order_id = o.id AND o.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tenant_id
              AND o.store_id = :store_id::UUID
              AND p.is_deleted = FALSE
              AND o.is_deleted = FALSE
              AND o.status IN ('completed', 'paid')
              AND COALESCE(o.biz_date, DATE(o.created_at)) = :biz_date::DATE
            GROUP BY p.pay_method
            ORDER BY amount_fen DESC
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "biz_date": date_str},
    )
    rows = result.mappings().all()

    pay_method_accounts = {
        "cash": (ACCOUNT_CASH, "现金"),
        "bank_card": (ACCOUNT_BANK, "银行卡"),
        "wechat": (ACCOUNT_WECHAT_PAY, "微信"),
        "alipay": (ACCOUNT_ALIPAY, "支付宝"),
    }

    entries = []
    total_fen = 0
    for row in rows:
        method = row["pay_method"]
        amount = row["amount_fen"]
        total_fen += amount
        account, label = pay_method_accounts.get(method, (ACCOUNT_BANK, method))
        entries.append(
            _make_voucher_entry(
                account,
                debit_fen=amount,
                summary=f"{date_str}{label}收入({row['pay_count']}笔)",
            )
        )

    entries.append(
        _make_voucher_entry(
            ACCOUNT_MAIN_BIZ_REVENUE,
            credit_fen=total_fen,
            summary=f"{date_str}营业收入",
        )
    )

    voucher = {
        "voucher_type": "收",
        "date": date_str,
        "entries": entries,
        "total_debit_fen": total_fen,
        "total_credit_fen": total_fen,
    }

    return _make_export_record(
        "daily_revenue", store_id, date_str, tenant_id, voucher,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 销售出库汇总 → 金蝶凭证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def export_sales_delivery(
    store_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """销售出库汇总 → 金蝶凭证

    借: 主营业务成本(5401)
    贷: 库存商品(1405)
    """
    log.info(
        "kingdee.export_sales_delivery",
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
    )

    start_date = f"{month}-01"
    result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0) AS total_cost_fen,
                COUNT(DISTINCT o.id) AS order_count
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.id AND oi.tenant_id = o.tenant_id
            WHERE o.tenant_id = :tenant_id
              AND o.store_id = :store_id::UUID
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
              AND o.status IN ('completed', 'paid')
              AND COALESCE(o.biz_date, DATE(o.created_at)) >= :start_date::DATE
              AND COALESCE(o.biz_date, DATE(o.created_at)) < (:start_date::DATE + INTERVAL '1 month')
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "start_date": start_date},
    )
    row = result.mappings().first()
    total_fen = row["total_cost_fen"] if row else 0
    order_count = row["order_count"] if row else 0

    voucher = {
        "voucher_type": "转",
        "date": f"{month}-01",
        "entries": [
            _make_voucher_entry(
                ACCOUNT_MAIN_BIZ_COST,
                debit_fen=total_fen,
                summary=f"{month}销售出库成本({order_count}单)",
            ),
            _make_voucher_entry(
                ACCOUNT_INVENTORY_GOODS,
                credit_fen=total_fen,
                summary=f"{month}销售出库-库存商品减少",
            ),
        ],
        "total_debit_fen": total_fen,
        "total_credit_fen": total_fen,
    }

    return _make_export_record(
        "sales_delivery", store_id, month, tenant_id, voucher,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 导出历史查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def get_export_history(
    tenant_id: str,
    db: AsyncSession,
    *,
    store_id: Optional[str] = None,
    export_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询金蝶导出历史

    Returns:
        {"items": [...], "total": int, "page": int, "page_size": int}
    """
    log.info(
        "kingdee.get_export_history",
        tenant_id=tenant_id,
        store_id=store_id,
        export_type=export_type,
    )

    filters = ["eh.tenant_id = :tenant_id", "eh.is_deleted = FALSE"]
    params: dict = {"tenant_id": tenant_id}

    if store_id:
        filters.append("eh.store_id = :store_id::UUID")
        params["store_id"] = store_id
    if export_type:
        filters.append("eh.export_type = :export_type")
        params["export_type"] = export_type

    where_clause = " AND ".join(filters)
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    # 查总数
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM erp_export_history eh WHERE {where_clause}"),
        params,
    )
    total = count_result.scalar() or 0

    # 查明细
    result = await db.execute(
        text(f"""
            SELECT
                eh.id AS export_id,
                eh.export_type,
                eh.store_id,
                eh.period,
                eh.status,
                eh.voucher_data,
                eh.error_message,
                eh.created_at,
                eh.completed_at
            FROM erp_export_history eh
            WHERE {where_clause}
            ORDER BY eh.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = [dict(r) for r in result.mappings().all()]

    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 重试失败导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def retry_failed_export(
    export_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """重试失败的金蝶导出

    查找原导出记录，重新执行对应的导出函数。

    Returns:
        新的导出记录
    """
    log.info(
        "kingdee.retry_failed_export",
        export_id=export_id,
        tenant_id=tenant_id,
    )

    # 查原导出记录
    result = await db.execute(
        text("""
            SELECT id, export_type, store_id, period, status
            FROM erp_export_history
            WHERE id = :export_id::UUID
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"export_id": export_id, "tenant_id": tenant_id},
    )
    original = result.mappings().first()
    if original is None:
        raise ValueError(f"Export record not found: {export_id}")

    if original["status"] != EXPORT_STATUS_FAILED:
        raise ValueError(
            f"Only failed exports can be retried, current status: {original['status']}"
        )

    export_type = original["export_type"]
    store_id = original["store_id"]
    period = original["period"]

    # 根据类型重新调用对应函数
    export_funcs = {
        "purchase_receipt": export_purchase_receipt,
        "cost_transfer": export_cost_transfer,
        "transfer_in_out": export_transfer_in_out,
        "salary_accrual": export_salary_accrual,
        "sales_delivery": export_sales_delivery,
    }

    if export_type == "daily_revenue":
        new_record = await export_daily_revenue(store_id, period, tenant_id, db)
    elif export_type in export_funcs:
        new_record = await export_funcs[export_type](store_id, period, tenant_id, db)
    else:
        raise ValueError(f"Unknown export type: {export_type}")

    new_record["retry_of"] = export_id
    return new_record
