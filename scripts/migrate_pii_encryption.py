"""
一次性数据迁移：明文手机号 → 加密存储

执行环境：本地或跳板机，连接生产DB（通过 DATABASE_URL 环境变量）
支持断点续传（通过记录进度到 /tmp/pii_migration_progress.json）

前提条件：
  1. 已执行 v074_pii_encryption 数据库迁移（添加了 *_encrypted 列）
  2. 已配置环境变量 TX_FIELD_ENCRYPTION_KEY 和 DATABASE_URL

使用方法：
  export TX_FIELD_ENCRYPTION_KEY=<64位hex>
  export DATABASE_URL=postgresql://user:pass@host:5432/dbname
  python scripts/migrate_pii_encryption.py

安全注意事项：
  - 迁移期间原明文列继续可用（渐进式迁移）
  - 迁移完成后验证加密列数据
  - 30天内手动执行 DROP COLUMN 删除明文列（需另建迁移）
  - 迁移日志不打印明文手机号（仅打印脱敏后的 138****6789）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.utils.field_encryption import get_encryption

logger = structlog.get_logger(__name__)

PROGRESS_FILE = Path("/tmp/pii_migration_progress.json")
BATCH_SIZE = 100  # 每批处理记录数


# ─────────────────────────────────────────────────────────────────
# 进度管理
# ─────────────────────────────────────────────────────────────────

def load_progress() -> dict:
    """加载断点续传进度。"""
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_progress(progress: dict) -> None:
    """保存迁移进度。"""
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2, ensure_ascii=False))


# ─────────────────────────────────────────────────────────────────
# 核心迁移函数
# ─────────────────────────────────────────────────────────────────

async def migrate_customers(db_url: str) -> dict:
    """迁移 customers 表手机号：primary_phone → phone_encrypted + phone_last4。

    Returns:
        {"processed": int, "skipped": int, "errors": int}
    """
    enc = get_encryption()
    progress = load_progress()
    last_processed_id = progress.get("customers_last_id")

    stats = {"processed": 0, "skipped": 0, "errors": 0}
    error_log: list[dict] = []

    # TODO: 初始化异步数据库连接
    # 建议使用 asyncpg 或 sqlalchemy async engine：
    #
    # import asyncpg
    # conn = await asyncpg.connect(db_url)
    #
    # 或：
    # from sqlalchemy.ext.asyncio import create_async_engine
    # engine = create_async_engine(db_url.replace("postgresql://", "postgresql+asyncpg://"))

    logger.info("开始迁移 customers 表手机号", batch_size=BATCH_SIZE)

    # TODO: 实现批量迁移循环
    # 示例查询（断点续传，从上次处理的ID继续）：
    #
    # while True:
    #     # 查询一批待迁移记录（phone_encrypted为空且primary_phone不为空）
    #     query = """
    #         SELECT id, primary_phone
    #         FROM customers
    #         WHERE phone_encrypted IS NULL
    #           AND primary_phone IS NOT NULL
    #           AND is_deleted = FALSE
    #           AND ($1::UUID IS NULL OR id > $1)
    #         ORDER BY id
    #         LIMIT $2
    #     """
    #     rows = await conn.fetch(query, last_processed_id, BATCH_SIZE)
    #     if not rows:
    #         break
    #
    #     for row in rows:
    #         customer_id = row["id"]
    #         plain_phone = row["primary_phone"]
    #         try:
    #             encrypted, last4 = enc.encrypt_phone(plain_phone)
    #             await conn.execute(
    #                 "UPDATE customers SET phone_encrypted=$1, phone_last4=$2 WHERE id=$3",
    #                 encrypted, last4, customer_id,
    #             )
    #             stats["processed"] += 1
    #             last_processed_id = customer_id
    #
    #             # 每处理一条立即保存进度（支持中断后续传）
    #             progress["customers_last_id"] = str(customer_id)
    #             save_progress(progress)
    #
    #             # 日志脱敏（绝不打印明文手机号）
    #             logger.debug(
    #                 "已加密客户手机号",
    #                 customer_id=str(customer_id),
    #                 masked_phone=enc.mask_phone(plain_phone),
    #             )
    #         except (ValueError, RuntimeError, OSError) as exc:
    #             logger.error(
    #                 "加密客户手机号失败，跳过",
    #                 customer_id=str(customer_id),
    #                 error=str(exc),
    #             )
    #             error_log.append({"table": "customers", "id": str(customer_id), "error": str(exc)})
    #             stats["errors"] += 1

    # TODO: 关闭数据库连接
    # await conn.close()

    # 保存错误日志
    if error_log:
        error_file = Path(f"/tmp/pii_migration_errors_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
        error_file.write_text(json.dumps(error_log, indent=2, ensure_ascii=False))
        logger.warning("迁移存在错误记录", error_file=str(error_file), count=len(error_log))

    logger.info(
        "customers 表迁移完成",
        processed=stats["processed"],
        skipped=stats["skipped"],
        errors=stats["errors"],
    )
    return stats


async def migrate_employees(db_url: str) -> dict:
    """迁移 employees 表手机号：phone/emergency_phone → *_encrypted + phone_last4。

    Returns:
        {"processed": int, "skipped": int, "errors": int}
    """
    enc = get_encryption()
    progress = load_progress()
    last_processed_id = progress.get("employees_last_id")

    stats = {"processed": 0, "skipped": 0, "errors": 0}
    error_log: list[dict] = []

    logger.info("开始迁移 employees 表手机号", batch_size=BATCH_SIZE)

    # TODO: 初始化数据库连接（同 migrate_customers）

    # TODO: 实现批量迁移循环
    # 与 customers 类似，但需要同时处理 phone 和 emergency_phone 两个字段：
    #
    # query = """
    #     SELECT id, phone, emergency_phone
    #     FROM employees
    #     WHERE (phone_encrypted IS NULL AND phone IS NOT NULL)
    #        OR (emergency_phone_encrypted IS NULL AND emergency_phone IS NOT NULL)
    #       AND ($1::UUID IS NULL OR id > $1)
    #     ORDER BY id
    #     LIMIT $2
    # """
    #
    # for row in rows:
    #     emp_id = row["id"]
    #     try:
    #         updates = {}
    #         if row["phone"] and not enc.is_encrypted(row["phone"]):
    #             enc_phone, last4 = enc.encrypt_phone(row["phone"])
    #             updates.update({"phone_encrypted": enc_phone, "phone_last4": last4})
    #
    #         if row["emergency_phone"] and not enc.is_encrypted(row["emergency_phone"]):
    #             enc_emg, _ = enc.encrypt_phone(row["emergency_phone"])
    #             updates["emergency_phone_encrypted"] = enc_emg
    #
    #         if updates:
    #             # 构造动态UPDATE语句
    #             set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
    #             values = list(updates.values())
    #             await conn.execute(
    #                 f"UPDATE employees SET {set_clause} WHERE id=$1",
    #                 emp_id, *values,
    #             )
    #             stats["processed"] += 1
    #         else:
    #             stats["skipped"] += 1
    #
    #         progress["employees_last_id"] = str(emp_id)
    #         save_progress(progress)
    #
    #     except (ValueError, RuntimeError, OSError) as exc:
    #         logger.error("加密员工手机号失败", emp_id=str(emp_id), error=str(exc))
    #         error_log.append({"table": "employees", "id": str(emp_id), "error": str(exc)})
    #         stats["errors"] += 1

    # TODO: 关闭数据库连接

    if error_log:
        error_file = Path(f"/tmp/pii_migration_errors_employees_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
        error_file.write_text(json.dumps(error_log, indent=2, ensure_ascii=False))
        logger.warning("迁移存在错误记录", error_file=str(error_file), count=len(error_log))

    logger.info(
        "employees 表迁移完成",
        processed=stats["processed"],
        skipped=stats["skipped"],
        errors=stats["errors"],
    )
    return stats


async def backfill_order_integrity(db_url: str) -> dict:
    """为历史订单回填 integrity_hash。

    Returns:
        {"processed": int, "errors": int}
    """
    from shared.utils.data_integrity import sign_order

    progress = load_progress()
    last_processed_id = progress.get("orders_last_id")
    stats = {"processed": 0, "errors": 0}

    logger.info("开始回填 orders.integrity_hash", batch_size=BATCH_SIZE)

    # TODO: 初始化数据库连接

    # TODO: 实现批量回填循环
    # query = """
    #     SELECT id, tenant_id, total_amount, discount_amount, final_amount
    #     FROM orders
    #     WHERE integrity_hash IS NULL
    #       AND ($1::UUID IS NULL OR id > $1)
    #     ORDER BY id
    #     LIMIT $2
    # """
    #
    # for row in rows:
    #     order_id = row["id"]
    #     try:
    #         order_dict = dict(row)
    #         # 金额字段统一转为字符串（sign_order内部会str转换）
    #         hash_value = sign_order(order_dict)
    #         await conn.execute(
    #             "UPDATE orders SET integrity_hash=$1 WHERE id=$2",
    #             hash_value, order_id,
    #         )
    #         stats["processed"] += 1
    #         progress["orders_last_id"] = str(order_id)
    #         save_progress(progress)
    #     except (ValueError, RuntimeError) as exc:
    #         logger.error("回填订单完整性hash失败", order_id=str(order_id), error=str(exc))
    #         stats["errors"] += 1

    logger.info("orders 完整性hash回填完成", **stats)
    return stats


# ─────────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────────

def check_env() -> bool:
    """检查必要的环境变量，返回是否全部就绪。"""
    ok = True
    enc_key = os.environ.get("TX_FIELD_ENCRYPTION_KEY", "")
    integrity_secret = os.environ.get("TX_INTEGRITY_SECRET", "")
    db_url = os.environ.get("DATABASE_URL", "")

    if not enc_key:
        print("  TX_FIELD_ENCRYPTION_KEY  未设置")
        ok = False
    elif len(enc_key) != 64:
        print(f"  TX_FIELD_ENCRYPTION_KEY  长度错误（期望64位hex，实际{len(enc_key)}位）")
        ok = False
    else:
        print("  TX_FIELD_ENCRYPTION_KEY  已设置 (64位hex)")

    if not integrity_secret:
        print("  TX_INTEGRITY_SECRET      未设置（orders integrity_hash回填将跳过）")
    else:
        print("  TX_INTEGRITY_SECRET      已设置")

    if not db_url:
        print("  DATABASE_URL             未设置")
        ok = False
    else:
        # 脱敏打印（隐藏密码）
        safe_url = db_url.split("@")[-1] if "@" in db_url else db_url
        print(f"  DATABASE_URL             已设置 (...@{safe_url})")

    return ok


if __name__ == "__main__":
    print("=" * 60)
    print("屯象OS PII字段加密迁移脚本")
    print(f"执行时间：{datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print("\n环境变量检查：")

    if not check_env():
        print("\n[错误] 必要环境变量未配置，请参考 docs/security-ops/encryption-setup.md")
        sys.exit(1)

    print("\n[警告] 本脚本将修改生产数据库，请确认已备份数据库！")
    print("按 Enter 继续，或 Ctrl+C 取消...")
    input()

    db_url = os.environ["DATABASE_URL"]

    print("\n[1/3] 迁移 customers 表手机号...")
    asyncio.run(migrate_customers(db_url))

    print("\n[2/3] 迁移 employees 表手机号...")
    asyncio.run(migrate_employees(db_url))

    print("\n[3/3] 回填 orders.integrity_hash...")
    asyncio.run(backfill_order_integrity(db_url))

    print("\n" + "=" * 60)
    print("迁移框架执行完成（TODO注释处需实现实际DB连接）")
    print("验证步骤：")
    print("  1. 检查 customers.phone_encrypted 列是否以 enc:v1: 开头")
    print("  2. 检查 customers.phone_last4 列是否为4位数字")
    print("  3. 检查 orders.integrity_hash 列是否为64位十六进制字符串")
    print("  4. 验证通过后，30天内执行明文列删除迁移")
    print("=" * 60)
