#!/usr/bin/env python3
"""
多租户 Schema 初始化脚本

用法:
  cd apps/api-gateway
  python3 scripts/create_tenant_schema.py czq          # 创建单个 schema
  python3 scripts/create_tenant_schema.py --all        # 创建所有预设 schema
  python3 scripts/create_tenant_schema.py --list       # 列出已有 schema

功能:
  1. CREATE SCHEMA IF NOT EXISTS
  2. 从 public schema 复制租户表结构（不含数据）
  3. 在 tenant_schema_map 表中注册映射关系
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text


# ---- 预设商户 Schema 映射 ----
PRESET_SCHEMAS = {
    "czq": {
        "brand_id": "BRD_CZYZ0001",
        "brand_name": "尝在一起",
        "subdomain": "changzaiyiqi",
    },
    "zqx": {
        "brand_id": "BRD_ZQX00001",
        "brand_name": "最黔线",
        "subdomain": "zuiqianxian",
    },
    "sgc": {
        "brand_id": "BRD_SGC00001",
        "brand_name": "尚宫厨",
        "subdomain": "shanggongchu",
    },
}

# ---- 需要按租户隔离的表（从 tenant_filter.py 同步） ----
TENANT_TABLES = [
    "orders",
    "order_items",
    "reservations",
    "inventory_items",
    "inventory_transactions",
    "schedules",
    "employees",
    "training_records",
    "training_plans",
    "service_feedbacks",
    "complaints",
    "tasks",
    "notifications",
    "pos_transactions",
    "member_transactions",
    "financial_records",
    "supply_orders",
    "reconciliation_records",
    # 扩展表
    "stores",
    "dishes",
    "dish_categories",
    "dish_ingredients",
    "bom_templates",
    "bom_items",
    "inventory_batches",
    "inventory_counts",
    "suppliers",
    "purchase_orders",
    "purchase_order_items",
    "daily_reports",
    "kpis",
    "waste_events",
    "edge_hubs",
    "edge_devices",
    "headset_bindings",
    "edge_alerts",
]

# ---- 系统表（保留在 public，不复制） ----
SYSTEM_TABLES = [
    "users",
    "groups",
    "brands",
    "regions",
    "roles",
    "permissions",
    "audit_logs",
    "alembic_version",
    "system_config",
    "ai_models",
    "tenant_schema_map",
]


async def create_schema(schema_name: str, brand_info: dict):
    """创建租户 Schema 并复制表结构"""
    from src.core.database import engine

    async with engine.begin() as conn:
        # 1. 创建 Schema
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        print(f"  ✅ Schema '{schema_name}' 已创建")

        # 2. 复制 public 表结构到新 Schema
        # 获取 public 中实际存在的表
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables WHERE schemaname = 'public'
        """))
        existing_tables = {row[0] for row in result.fetchall()}

        copied = 0
        skipped = 0
        for table in TENANT_TABLES:
            if table not in existing_tables:
                skipped += 1
                continue

            # 检查目标表是否已存在
            check = await conn.execute(text(f"""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = :table
                )
            """), {"schema": schema_name, "table": table})
            if check.scalar():
                skipped += 1
                continue

            # 复制表结构（不含数据）
            await conn.execute(text(
                f"CREATE TABLE {schema_name}.{table} (LIKE public.{table} INCLUDING ALL)"
            ))
            copied += 1

        print(f"  ✅ 复制了 {copied} 张表结构（跳过 {skipped} 张已存在/不存在的表）")

        # 3. 注册到映射表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.tenant_schema_map (
                id SERIAL PRIMARY KEY,
                schema_name VARCHAR(50) NOT NULL UNIQUE,
                brand_id VARCHAR(50) NOT NULL UNIQUE,
                brand_name VARCHAR(100),
                subdomain VARCHAR(100),
                tenant_id VARCHAR(100),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # brand_czq 格式的 tenant_id
        tenant_id = f"brand_{schema_name}"

        await conn.execute(text("""
            INSERT INTO public.tenant_schema_map (schema_name, brand_id, brand_name, subdomain, tenant_id)
            VALUES (:schema_name, :brand_id, :brand_name, :subdomain, :tenant_id)
            ON CONFLICT (schema_name) DO UPDATE SET
                brand_id = EXCLUDED.brand_id,
                brand_name = EXCLUDED.brand_name,
                subdomain = EXCLUDED.subdomain,
                tenant_id = EXCLUDED.tenant_id
        """), {
            "schema_name": schema_name,
            "brand_id": brand_info["brand_id"],
            "brand_name": brand_info["brand_name"],
            "subdomain": brand_info["subdomain"],
            "tenant_id": tenant_id,
        })
        print(f"  ✅ 映射已注册: {brand_info['brand_id']} → {schema_name} ({tenant_id})")

    await engine.dispose()


async def list_schemas():
    """列出已有的租户 Schema"""
    from src.core.database import engine

    async with engine.begin() as conn:
        # 检查映射表是否存在
        check = await conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'tenant_schema_map'
            )
        """))
        if not check.scalar():
            print("  映射表尚未创建，无租户 Schema")
            await engine.dispose()
            return

        result = await conn.execute(text("""
            SELECT schema_name, brand_id, brand_name, subdomain, tenant_id, is_active
            FROM public.tenant_schema_map ORDER BY schema_name
        """))
        rows = result.fetchall()

        if not rows:
            print("  无已注册的租户 Schema")
        else:
            print(f"  {'Schema':<10} {'Brand ID':<18} {'品牌':<12} {'子域名':<25} {'Tenant ID':<18} {'状态'}")
            print("  " + "-" * 95)
            for r in rows:
                status = "✅ 活跃" if r[5] else "❌ 停用"
                print(f"  {r[0]:<10} {r[1]:<18} {r[2]:<12} {r[3]:<25} {r[4]:<18} {status}")

    await engine.dispose()


async def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 scripts/create_tenant_schema.py czq       # 创建单个")
        print("  python3 scripts/create_tenant_schema.py --all     # 创建所有预设")
        print("  python3 scripts/create_tenant_schema.py --list    # 列出已有")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--list":
        print("\n📋 已注册的租户 Schema:")
        await list_schemas()
    elif arg == "--all":
        print("\n🔧 创建所有预设 Schema:")
        for name, info in PRESET_SCHEMAS.items():
            print(f"\n[{name}] {info['brand_name']}:")
            await create_schema(name, info)
        print("\n✅ 全部完成！")
    elif arg in PRESET_SCHEMAS:
        info = PRESET_SCHEMAS[arg]
        print(f"\n🔧 创建 Schema [{arg}] {info['brand_name']}:")
        await create_schema(arg, info)
        print("\n✅ 完成！")
    else:
        print(f"❌ 未知的 Schema 名: {arg}")
        print(f"   可用: {', '.join(PRESET_SCHEMAS.keys())} 或 --all / --list")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
