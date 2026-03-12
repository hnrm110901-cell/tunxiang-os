#!/usr/bin/env python3
"""
种子脚本 — 创建管理员账号 + 演示商户数据
用法: cd apps/api-gateway && python3 scripts/seed_admin.py
"""
import asyncio
import sys
import os

# 确保 src 可以被 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database import engine, AsyncSessionLocal, init_db
from src.core.security import get_password_hash
from src.models.user import User, UserRole
from src.models.organization import Group, Brand
from src.models.store import Store
from sqlalchemy import select
import uuid


async def seed():
    # 1. 建表
    print("初始化数据库表...")
    await init_db()

    async with AsyncSessionLocal() as session:
        # 2. 创建管理员（如果不存在）
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one_or_none()
        if admin:
            print(f"管理员账号已存在: admin (ID: {admin.id})")
        else:
            admin = User(
                id=uuid.uuid4(),
                username="admin",
                email="admin@tunxiang-os.com",
                hashed_password=get_password_hash("admin123"),
                full_name="平台管理员",
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin)
            await session.flush()
            print(f"✅ 管理员账号已创建: admin / admin123")

        # 3. 创建演示商户 —— 尝在一起
        result = await session.execute(select(Brand).where(Brand.brand_name == "尝在一起"))
        if result.scalar_one_or_none():
            print("演示商户「尝在一起」已存在，跳过")
        else:
            grp1 = Group(
                group_id="GRP_CZYZ0001",
                group_name="贵州尝在一起餐饮管理有限公司",
                legal_entity="张三",
                unified_social_credit_code="915201005678901234",
                industry_type="chinese_formal",
                contact_person="张三",
                contact_phone="13800138001",
                address="贵阳市南明区花果园",
            )
            session.add(grp1)

            brd1 = Brand(
                brand_id="BRD_CZYZ0001",
                group_id="GRP_CZYZ0001",
                brand_name="尝在一起",
                cuisine_type="guizhou",
                avg_ticket_yuan=68,
                target_food_cost_pct=35,
                target_labor_cost_pct=22,
                target_rent_cost_pct=10,
                target_waste_pct=3,
                status="active",
            )
            session.add(brd1)

            # 门店
            for i, (name, code, city) in enumerate([
                ("花果园店", "CZYZ-GY001", "贵阳"),
                ("永安店", "CZYZ-GY002", "贵阳"),
                ("文化城店", "CZYZ-GY003", "贵阳"),
            ]):
                session.add(Store(
                    id=f"STORE_CZYZ{i+1:04d}",
                    name=name, code=code, city=city,
                    brand_id="BRD_CZYZ0001", status="active", is_active=True,
                    seats=80 + i * 20,
                ))

            # 店长
            sm1 = User(
                id=uuid.uuid4(),
                username="czyz_manager",
                email="manager@czyz.com",
                hashed_password=get_password_hash("czyz123"),
                full_name="李店长",
                role=UserRole.STORE_MANAGER,
                is_active=True,
                brand_id="BRD_CZYZ0001",
                store_id="STORE_CZYZ0001",
            )
            session.add(sm1)
            print("✅ 演示商户「尝在一起」已创建（3 家门店 + 1 个店长账号 czyz_manager/czyz123）")

        # 4. 创建演示商户 —— 最黔线
        result = await session.execute(select(Brand).where(Brand.brand_name == "最黔线"))
        if result.scalar_one_or_none():
            print("演示商户「最黔线」已存在，跳过")
        else:
            grp2 = Group(
                group_id="GRP_ZQX00001",
                group_name="贵州最黔线餐饮有限公司",
                legal_entity="李四",
                unified_social_credit_code="915201009876543210",
                industry_type="chinese_formal",
                contact_person="李四",
                contact_phone="13900139002",
                address="贵阳市云岩区",
            )
            session.add(grp2)

            brd2 = Brand(
                brand_id="BRD_ZQX00001",
                group_id="GRP_ZQX00001",
                brand_name="最黔线",
                cuisine_type="guizhou",
                avg_ticket_yuan=55,
                target_food_cost_pct=33,
                target_labor_cost_pct=24,
                target_rent_cost_pct=12,
                target_waste_pct=2.5,
                status="active",
            )
            session.add(brd2)

            session.add(Store(
                id="STORE_ZQX00001",
                name="喷水池店", code="ZQX-GY001", city="贵阳",
                brand_id="BRD_ZQX00001", status="active", is_active=True, seats=60,
            ))

            sm2 = User(
                id=uuid.uuid4(),
                username="zqx_manager",
                email="manager@zqx.com",
                hashed_password=get_password_hash("zqx12345"),
                full_name="王店长",
                role=UserRole.STORE_MANAGER,
                is_active=True,
                brand_id="BRD_ZQX00001",
                store_id="STORE_ZQX00001",
            )
            session.add(sm2)
            print("✅ 演示商户「最黔线」已创建（1 家门店 + 1 个店长账号 zqx_manager/zqx12345）")

        # 5. 创建演示商户 —— 尚宫厨（已停用示例）
        result = await session.execute(select(Brand).where(Brand.brand_name == "尚宫厨"))
        if result.scalar_one_or_none():
            print("演示商户「尚宫厨」已存在，跳过")
        else:
            grp3 = Group(
                group_id="GRP_SGC00001",
                group_name="深圳尚宫厨餐饮管理有限公司",
                legal_entity="王五",
                unified_social_credit_code="914403001234567890",
                industry_type="chinese_formal",
                contact_person="王五",
                contact_phone="13700137003",
                address="深圳市福田区",
            )
            session.add(grp3)

            brd3 = Brand(
                brand_id="BRD_SGC00001",
                group_id="GRP_SGC00001",
                brand_name="尚宫厨",
                cuisine_type="cantonese",
                avg_ticket_yuan=128,
                target_food_cost_pct=38,
                target_labor_cost_pct=20,
                target_rent_cost_pct=15,
                target_waste_pct=2,
                status="inactive",
            )
            session.add(brd3)
            print("✅ 演示商户「尚宫厨」已创建（已停用状态，无门店）")

        await session.commit()

    await engine.dispose()
    print("\n" + "=" * 50)
    print("种子数据初始化完成！")
    print("=" * 50)
    print("\n📋 账号汇总:")
    print("┌─────────────────┬──────────────┬──────────┐")
    print("│ 角色            │ 用户名       │ 密码     │")
    print("├─────────────────┼──────────────┼──────────┤")
    print("│ 平台管理员      │ admin        │ admin123 │")
    print("│ 尝在一起·店长   │ czyz_manager │ czyz123  │")
    print("│ 最黔线·店长     │ zqx_manager  │ zqx12345 │")
    print("└─────────────────┴──────────────┴──────────┘")
    print("\n🌐 访问地址:")
    print("  前端: http://localhost:5173")
    print("  API:  http://localhost:8000/docs")
    print("  商户管理: 登录 admin → 侧边栏「平台与治理」→「商户管理」")


if __name__ == "__main__":
    asyncio.run(seed())
