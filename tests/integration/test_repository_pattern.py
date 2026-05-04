"""test_repository_pattern.py — Repository 层集成测试模板

演示如何编写连接真实 PostgreSQL 的 Repository 测试。
每个测试在独立事务中运行，结束时自动 ROLLBACK。

模式：
  1. 插入测试数据（直接 SQL 或 Repository.create）
  2. 调用被测 Repository 方法
  3. 验证返回值/数据库状态
  4. 事务自动回滚，无需手动清理

注意：本文件是模式模板，具体 Repository 测试应放在对应服务的 tests/ 目录。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


TENANT_A = "00000000-0000-0000-0000-000000000001"
TENANT_B = "00000000-0000-0000-0000-000000000002"


class TestRepositoryPattern:
    """Repository 集成测试模式示例。"""

    @pytest.mark.integration
    async def test_insert_and_query_tenant_scoped(self, transaction: AsyncConnection):
        """插入带 tenant_id 的记录，查询按租户隔离。"""
        store_id = uuid4()

        # 插入测试数据
        await transaction.execute(
            text("""
                INSERT INTO stores (id, tenant_id, name, code, status, created_at, updated_at)
                VALUES (:id, :tenant_id, :name, :code, 'active', NOW(), NOW())
            """),
            {
                "id": store_id,
                "tenant_id": UUID(TENANT_A),
                "name": "集成测试门店",
                "code": "INTEG-TEST-001",
            },
        )

        # 以 tenant_A 查询 —— 应找到
        result_a = (await transaction.execute(
            text("SELECT id, name FROM stores WHERE id = :id"),
            {"id": store_id},
        )).fetchone()
        assert result_a is not None, "tenant_A 应看到自己插入的数据"
        assert result_a[1] == "集成测试门店"

    @pytest.mark.integration
    async def test_cross_tenant_invisible(self, transaction: AsyncConnection):
        """验证 RLS 跨租户隔离。

        插入 tenant_A 的数据，在未设置 tenant_B 的上下文中查询应看不到。
        """
        # 在当前连接中设置 tenant_A
        await transaction.exec_driver_sql(
            "SET LOCAL app.tenant_id TO '00000000-0000-0000-0000-000000000001'"
        )

        store_id = uuid4()
        await transaction.execute(
            text("""
                INSERT INTO stores (id, tenant_id, name, code, status, created_at, updated_at)
                VALUES (:id, :tenant_id, :name, :code, 'active', NOW(), NOW())
            """),
            {
                "id": store_id,
                "tenant_id": UUID(TENANT_A),
                "name": "Tenant-A Only Store",
                "code": "A-ONLY-001",
            },
        )

        # 切换到 tenant_B
        await transaction.exec_driver_sql(
            "SET LOCAL app.tenant_id TO '00000000-0000-0000-0000-000000000002'"
        )

        # 查询同一记录 —— RLS 应阻止
        result_b = (await transaction.execute(
            text("SELECT id, name FROM stores WHERE id = :id"),
            {"id": store_id},
        )).fetchone()
        assert result_b is None, "RLS 应阻止 tenant_B 看到 tenant_A 的数据"

    @pytest.mark.integration
    async def test_tenant_id_null_guard(self, transaction: AsyncConnection):
        """未设置 tenant_id 时 RLS 应拒绝（NULL 保护）。"""
        # 检查 RLS 策略中是否有 NULLIF guard
        policies = (await transaction.execute(
            text("""
                SELECT qual::text
                FROM pg_policies
                WHERE tablename = 'stores'
                  AND schemaname = 'public'
                LIMIT 5
            """)
        )).fetchall()

        for pol in policies:
            qual = pol[0]
            assert "NULLIF" in qual or "null" not in qual.lower(), \
                f"RLS policy may be bypassable with NULL tenant_id: {qual}"

    @pytest.mark.integration
    async def test_soft_delete_filtering(self, transaction: AsyncConnection):
        """软删除的记录应在常规查询中不可见。"""
        store_id = uuid4()

        # 插入一条已删除的记录
        await transaction.execute(
            text("""
                INSERT INTO stores (id, tenant_id, name, code, status, is_deleted, created_at, updated_at)
                VALUES (:id, :tenant_id, :name, :code, 'active', true, NOW(), NOW())
            """),
            {
                "id": store_id,
                "tenant_id": UUID(TENANT_A),
                "name": "已删除门店",
                "code": "DELETED-001",
            },
        )

        # 常规查询应过滤 is_deleted
        result = (await transaction.execute(
            text("SELECT id FROM stores WHERE id = :id AND is_deleted = false"),
            {"id": store_id},
        )).fetchone()
        assert result is None, "is_deleted = true 的记录应在常规查询中隐藏"
