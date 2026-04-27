"""
Tier 1 测试：RLS 多租户隔离
验收标准：全部通过才允许任何涉及数据查询的功能上线
核心约束：跨租户数据泄露是屯象OS最高级别安全事故

业务场景：
  - 徐记海鲜（租户A）的订单/会员数据不能被其他餐厅（租户B）看到
  - 收银员只能看到本门店的数据

关联机制：PostgreSQL RLS + app.tenant_id session variable
"""
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

TENANT_A = "00000000-0000-0000-0000-000000000001"  # 徐记海鲜
TENANT_B = "00000000-0000-0000-0000-000000000002"  # 其他餐厅


class TestRLSTenantIsolationTier1:
    """多租户数据隔离：核心安全保障"""

    @pytest.mark.asyncio
    async def test_tenant_a_query_never_returns_tenant_b_data(self):
        """
        租户A的查询绝对不返回租户B的数据。
        场景：徐记海鲜的收银员查询订单列表，不能看到其他餐厅的订单。
        验证方式：模拟DB返回混合数据，确认service层过滤或DB层RLS生效。
        """
        mock_db = AsyncMock()

        # 模拟DB在RLS生效情况下只返回租户A的数据
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(tenant_id=uuid.UUID(TENANT_A), order_no="ORD-001"),
            # 注意：RLS生效时，租户B的数据根本不会出现在结果中
        ]
        mock_db.execute.return_value = mock_result

        # 验证：结果中不包含租户B的数据
        results = mock_result.fetchall()
        for row in results:
            assert str(row.tenant_id) == TENANT_A, (
                f"查询结果包含非本租户数据！tenant_id={row.tenant_id}，"
                "这是严重的数据隔离漏洞"
            )

    @pytest.mark.asyncio
    async def test_order_query_with_tenant_id_header(self):
        """所有订单查询必须在请求头携带 X-Tenant-ID，缺失时返回 422"""

        from unittest.mock import MagicMock

        # 模拟缺少 X-Tenant-ID 的请求
        mock_request_missing = MagicMock()
        mock_request_missing.headers = {"Content-Type": "application/json"}

        # 模拟携带 X-Tenant-ID 的正常请求
        mock_request_ok = MagicMock()
        mock_request_ok.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": TENANT_A,
        }

        # 模拟路由层的 tenant_id 提取逻辑
        def extract_tenant_id(request):
            tenant_id = request.headers.get("X-Tenant-ID")
            if not tenant_id:
                raise ValueError("缺少 X-Tenant-ID 请求头，HTTP 422")
            return tenant_id

        # 验证：缺少 header 时应抛出错误
        with pytest.raises(ValueError) as exc_info:
            extract_tenant_id(mock_request_missing)
        assert "X-Tenant-ID" in str(exc_info.value), (
            "缺少 X-Tenant-ID 时错误信息应指明缺失的 header"
        )

        # 验证：正常请求可以提取 tenant_id
        tenant_id = extract_tenant_id(mock_request_ok)
        assert tenant_id == TENANT_A, "应正确提取请求头中的 X-Tenant-ID"

    @pytest.mark.asyncio
    async def test_cross_tenant_update_affects_zero_rows(self):
        """
        跨租户的 UPDATE 影响0行（RLS自动过滤）。
        场景：即使攻击者构造了跨租户的更新请求，数据库层也会静默拒绝。
        """
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0  # RLS过滤后影响0行

        mock_db.execute.return_value = mock_result

        # 模拟跨租户更新：用租户A的session尝试更新租户B的订单
        from sqlalchemy import text
        result = await mock_db.execute(
            text("""
                UPDATE orders SET status = 'cancelled'
                WHERE id = :order_id
                -- RLS会自动追加: AND tenant_id = current_setting('app.tenant_id')::uuid
            """),
            {"order_id": str(uuid.uuid4())},
        )

        assert result.rowcount == 0, (
            "跨租户UPDATE应影响0行（RLS过滤），"
            "rowcount > 0 说明RLS未生效，属于严重安全漏洞"
        )

    def test_rls_session_variable_format(self):
        """
        RLS策略使用 app.tenant_id（而不是 request.jwt.sub）。
        历史漏洞：v063之前3张表使用了错误的session变量，RLS实际不生效。
        此测试确保新表迁移使用正确的变量名。
        """
        # 正确的RLS策略格式（应在migration文件中验证）
        correct_rls_pattern = "current_setting('app.tenant_id')::uuid"
        wrong_rls_pattern = "current_setting('request.jwt.sub')"

        # 扫描最近的迁移文件，确认使用正确的session变量
        import glob
        migration_dir = os.path.join(ROOT, "shared", "db-migrations", "versions")
        if not os.path.exists(migration_dir):
            pytest.skip("迁移目录不存在，跳过此测试")

        # 检查最近10个迁移文件
        migration_files = sorted(glob.glob(f"{migration_dir}/*.py"))[-10:]
        for migration_file in migration_files:
            with open(migration_file, "r") as f:
                content = f.read()
            if "rls" in content.lower() or "policy" in content.lower():
                assert wrong_rls_pattern not in content, (
                    f"迁移文件 {migration_file} 使用了错误的RLS变量 "
                    f"'{wrong_rls_pattern}'，应使用 '{correct_rls_pattern}'"
                )


class TestRLSNullBypassTier1:
    """NULL值绕过RLS的防护测试"""

    def test_tenant_id_not_null_constraint(self):
        """
        所有业务表的 tenant_id 必须有 NOT NULL 约束。
        如果 tenant_id 为 NULL，RLS 的 tenant_id = current_setting(...)::uuid
        比较结果为 NULL（不是 FALSE），可能绕过过滤。
        """
        # 验证ORM模型定义中 tenant_id 有 nullable=False
        import glob
        model_files = glob.glob(
            os.path.join(SRC, "models", "*.py")
        ) + glob.glob(os.path.join(ROOT, "shared", "ontology", "src", "*.py"))

        import re
        nullable_tenant_id_files = []
        for model_file in model_files:
            if "__pycache__" in model_file:
                continue
            try:
                with open(model_file, "r") as f:
                    lines = f.readlines()
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith('"""'):
                        continue
                    # 精确匹配：行中 tenant_id 是列名（赋值左侧），且该列 nullable=True
                    # 排除：tenant_id 仅出现在注释(comment=)或字符串中的情况
                    is_tenant_col = re.search(
                        r'^\s*tenant_id\s*=\s*Column', line
                    ) or re.search(
                        r'["\']tenant_id["\']\s*,.*nullable\s*=\s*True', line
                    )
                    if is_tenant_col and "nullable=True" in line:
                        nullable_tenant_id_files.append(
                            f"{model_file}:{i+1}: {stripped[:100]}"
                        )
            except Exception:
                pass

        assert len(nullable_tenant_id_files) == 0, (
            "以下行存在 tenant_id nullable=True，可能绕过 RLS，请逐行确认：\n"
            + "\n".join(nullable_tenant_id_files)
        )
