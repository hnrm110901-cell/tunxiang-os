"""三品牌门店种子数据脚本

为尝在一起、最黔线、尚宫厨三个品牌初始化门店记录（INSERT OR UPDATE）。
门店的 extra_data JSONB 存储品智 store_id / store_token 和奥琦玮 shop_id。

用法：
    python scripts/seed_three_brands_stores.py

依赖：
    asyncpg（pip install asyncpg）
    环境变量 DATABASE_URL（postgresql+asyncpg://... 或 postgresql://...）
"""

import asyncio
import json
import os
import re
import sys
from typing import Any

import asyncpg


# ─── 品牌门店定义 ────────────────────────────────────────────────────────────

BRANDS: list[dict[str, Any]] = [
    {
        "tenant_code": "t-czq",
        "stores": [
            {
                "store_name": "尝在一起·文化城店",
                "store_code": "CZYZ-2461",
                "city": "长沙",
                "pinzhi_store_id": 2461,
                "pinzhi_token": "752b4b16a863ce47def11cf33b1b521f",
                "aoqiwei_shop_id": 2461,
            },
            {
                "store_name": "尝在一起·浏小鲜",
                "store_code": "CZYZ-7269",
                "city": "长沙",
                "pinzhi_store_id": 7269,
                "pinzhi_token": "f5cc1a27db6e215ae7bb5512b6b57981",
                "aoqiwei_shop_id": 7269,
            },
            {
                "store_name": "尝在一起·永安店",
                "store_code": "CZYZ-19189",
                "city": "长沙",
                "pinzhi_store_id": 19189,
                "pinzhi_token": "56cd51b69211297104a0608f6a696b80",
                "aoqiwei_shop_id": 19189,
            },
        ],
    },
    {
        "tenant_code": "t-zqx",
        "stores": [
            {
                "store_name": "最黔线·马家湾店（老江菜馆）",
                "store_code": "ZQX-20529",
                "city": "长沙",
                "pinzhi_store_id": 20529,
                "pinzhi_token": "29cdb6acac3615070bb853afcbb32f60",
                "aoqiwei_shop_id": 20529,
            },
            {
                "store_name": "最黔线·东欣万象店",
                "store_code": "ZQX-32109",
                "city": "长沙",
                "pinzhi_store_id": 32109,
                "pinzhi_token": "ed2c948284d09cf9e096e9d965936aa3",
                "aoqiwei_shop_id": 32109,
            },
            {
                "store_name": "最黔线·合众路店",
                "store_code": "ZQX-32304",
                "city": "长沙",
                "pinzhi_store_id": 32304,
                "pinzhi_token": "43f0b54db12b0618ea612b2a0a4d2675",
                "aoqiwei_shop_id": 32304,
            },
            {
                "store_name": "最黔线·广州路店",
                "store_code": "ZQX-32305",
                "city": "长沙",
                "pinzhi_store_id": 32305,
                "pinzhi_token": "a8a4e4daf86875d4a4e0254b6eb7191e",
                "aoqiwei_shop_id": 32305,
            },
            {
                "store_name": "最黔线·昆明路店",
                "store_code": "ZQX-32306",
                "city": "长沙",
                "pinzhi_store_id": 32306,
                "pinzhi_token": "d656668d285a100c851bbe149d4364f3",
                "aoqiwei_shop_id": 32306,
            },
            {
                "store_name": "最黔线·仁怀店",
                "store_code": "ZQX-32309",
                "city": "长沙",
                "pinzhi_store_id": 32309,
                "pinzhi_token": "36bf0644e5703adc8a4d1ddd7b8f0e95",
                "aoqiwei_shop_id": 32309,
            },
        ],
    },
    {
        "tenant_code": "t-sgc",
        "stores": [
            {
                "store_name": "尚宫厨·采霞街店",
                "store_code": "SGC-2463",
                "city": "长沙",
                "pinzhi_store_id": 2463,
                "pinzhi_token": "852f1d34c75af0b8eb740ef47f133130",
                "aoqiwei_shop_id": 2463,
            },
            {
                "store_name": "尚宫厨·湘江水岸店",
                "store_code": "SGC-7896",
                "city": "长沙",
                "pinzhi_store_id": 7896,
                "pinzhi_token": "27a36f2feea6d3a914438f6cb32108c3",
                "aoqiwei_shop_id": 7896,
            },
            {
                "store_name": "尚宫厨·乐城店",
                "store_code": "SGC-24777",
                "city": "长沙",
                "pinzhi_store_id": 24777,
                "pinzhi_token": "5cbfb449112f698218e0b1be1a3bc7c6",
                "aoqiwei_shop_id": 24777,
            },
            {
                "store_name": "尚宫厨·啫匠亲城店",
                "store_code": "SGC-36199",
                "city": "长沙",
                "pinzhi_store_id": 36199,
                "pinzhi_token": "08f3791e15f48338405728a3a92fcd7f",
                "aoqiwei_shop_id": 36199,
            },
            {
                "store_name": "尚宫厨·酃湖雅院店",
                "store_code": "SGC-41405",
                "city": "长沙",
                "pinzhi_store_id": 41405,
                "pinzhi_token": "bb7e89dcd0ac339b51631eca99e51c9b",
                "aoqiwei_shop_id": 41405,
            },
        ],
    },
]


# ─── DSN 处理 ────────────────────────────────────────────────────────────────

def _to_asyncpg_dsn(database_url: str) -> str:
    """将 SQLAlchemy DSN（含 +asyncpg）转为 asyncpg 原生 DSN。"""
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


# ─── 核心逻辑 ────────────────────────────────────────────────────────────────

async def seed(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        # 1. 查询三品牌 tenant_id 与 brand_id
        tenant_codes = [b["tenant_code"] for b in BRANDS]
        rows = await conn.fetch(
            """
            SELECT id AS tenant_id,
                   code AS tenant_code,
                   -- brand_id 字段如不存在则回退为 NULL
                   COALESCE(
                       (extra_data->>'brand_id'),
                       NULL
                   ) AS brand_id
              FROM tenants
             WHERE code = ANY($1::text[])
            """,
            tenant_codes,
        )

        tenant_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            tenant_map[row["tenant_code"]] = {
                "tenant_id": row["tenant_id"],
                "brand_id": row["brand_id"],
            }

        missing = [c for c in tenant_codes if c not in tenant_map]
        if missing:
            print(f"[WARN] 以下 tenant_code 在数据库中不存在，跳过：{missing}", file=sys.stderr)

        # 2. Upsert 门店记录
        inserted = 0
        updated = 0

        for brand in BRANDS:
            code = brand["tenant_code"]
            if code not in tenant_map:
                continue

            tenant_id = tenant_map[code]["tenant_id"]
            brand_id = tenant_map[code]["brand_id"]

            for store in brand["stores"]:
                extra_data = json.dumps({
                    "pinzhi_store_id": store["pinzhi_store_id"],
                    "pinzhi_token": store["pinzhi_token"],
                    "aoqiwei_shop_id": store["aoqiwei_shop_id"],
                })

                result = await conn.execute(
                    """
                    INSERT INTO stores (
                        store_name,
                        store_code,
                        tenant_id,
                        brand_id,
                        city,
                        status,
                        is_active,
                        extra_data
                    ) VALUES ($1, $2, $3, $4, $5, 'active', TRUE, $6::jsonb)
                    ON CONFLICT (store_code) DO UPDATE
                       SET store_name = EXCLUDED.store_name,
                           tenant_id  = EXCLUDED.tenant_id,
                           brand_id   = EXCLUDED.brand_id,
                           city       = EXCLUDED.city,
                           status     = EXCLUDED.status,
                           is_active  = EXCLUDED.is_active,
                           extra_data = EXCLUDED.extra_data,
                           updated_at = NOW()
                    """,
                    store["store_name"],
                    store["store_code"],
                    tenant_id,
                    brand_id,
                    store["city"],
                    extra_data,
                )

                # asyncpg execute 返回 "INSERT 0 N" 或 "UPDATE N"
                if result.startswith("INSERT"):
                    inserted += 1
                else:
                    updated += 1

                print(
                    f"  [{code}] {store['store_name']} (pinzhi_id={store['pinzhi_store_id']}) — {result}"
                )

        print(f"\n完成：新增 {inserted} 条，更新 {updated} 条门店记录。")

    finally:
        await conn.close()


async def main() -> None:
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        print("[ERROR] 环境变量 DATABASE_URL 未设置", file=sys.stderr)
        sys.exit(1)

    dsn = _to_asyncpg_dsn(raw_url)
    print(f"连接数据库：{re.sub(r':([^@]+)@', ':***@', dsn)}")
    print("开始写入三品牌门店数据...\n")
    await seed(dsn)


if __name__ == "__main__":
    asyncio.run(main())
