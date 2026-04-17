#!/usr/bin/env python3
"""
种子脚本 — 初始化会计科目表（D7-P0 Must-Fix Task 1）

参考《企业会计准则——应用指南》附录一级科目代码体系。
brand_id=NULL 表示全局默认科目（所有品牌共用）。

用法:
    cd apps/api-gateway && python3 scripts/seed_chart_of_accounts.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from src.core.database import AsyncSessionLocal, init_db  # noqa: E402
from src.models.accounting import AccountType, ChartOfAccounts  # noqa: E402


# 全局默认科目（brand_id=NULL） — 按《企业会计准则》
DEFAULT_ACCOUNTS = [
    # ─── 资产类 asset（借方为正） ───
    ("1001", "库存现金", AccountType.ASSET, None, "debit"),
    ("1002", "银行存款", AccountType.ASSET, None, "debit"),
    ("1012", "其他货币资金", AccountType.ASSET, None, "debit"),
    ("1122", "应收账款", AccountType.ASSET, None, "debit"),
    ("1123", "预付账款", AccountType.ASSET, None, "debit"),
    ("1221", "其他应收款", AccountType.ASSET, None, "debit"),
    ("1403", "原材料", AccountType.ASSET, None, "debit"),
    ("1405", "库存商品", AccountType.ASSET, None, "debit"),
    ("1601", "固定资产", AccountType.ASSET, None, "debit"),
    # ─── 负债类 liability（贷方为正） ───
    ("2001", "短期借款", AccountType.LIABILITY, None, "credit"),
    ("2202", "应付账款", AccountType.LIABILITY, None, "credit"),
    ("2203", "预收账款", AccountType.LIABILITY, None, "credit"),
    # 二级明细：预收账款——储值卡（便于追溯）
    ("220301", "预收账款——储值卡", AccountType.LIABILITY, "2203", "credit"),
    ("2211", "应付职工薪酬", AccountType.LIABILITY, None, "credit"),
    ("2221", "应交税费", AccountType.LIABILITY, None, "credit"),
    ("222101", "应交税费——应交增值税", AccountType.LIABILITY, "2221", "credit"),
    # ─── 权益类 equity（贷方为正） ───
    ("4001", "实收资本", AccountType.EQUITY, None, "credit"),
    ("4103", "本年利润", AccountType.EQUITY, None, "credit"),
    # ─── 收入类 revenue（贷方为正） ───
    ("6001", "主营业务收入", AccountType.REVENUE, None, "credit"),
    ("6051", "其他业务收入", AccountType.REVENUE, None, "credit"),
    # ─── 成本类 cost（借方为正） ───
    ("6401", "主营业务成本", AccountType.COST, None, "debit"),
    ("6402", "其他业务成本", AccountType.COST, None, "debit"),
    # ─── 费用类 expense（借方为正） ───
    ("6601", "销售费用", AccountType.EXPENSE, None, "debit"),
    ("6602", "管理费用", AccountType.EXPENSE, None, "debit"),
    ("6603", "财务费用", AccountType.EXPENSE, None, "debit"),
]


async def seed():
    print("确保数据库表已创建 …")
    await init_db()

    async with AsyncSessionLocal() as session:
        # 只补齐缺失的科目（brand_id=NULL）
        existing_stmt = select(ChartOfAccounts.code).where(ChartOfAccounts.brand_id.is_(None))
        existing = {row[0] for row in (await session.execute(existing_stmt)).all()}

        inserted = 0
        for code, name, acct_type, parent, normal in DEFAULT_ACCOUNTS:
            if code in existing:
                continue
            session.add(
                ChartOfAccounts(
                    brand_id=None,
                    code=code,
                    name=name,
                    account_type=acct_type,
                    parent_code=parent,
                    normal_balance=normal,
                    is_active="true",
                )
            )
            inserted += 1

        await session.commit()
        print(f"科目表初始化完成：新增 {inserted} 条，已存在 {len(existing)} 条")


if __name__ == "__main__":
    asyncio.run(seed())
