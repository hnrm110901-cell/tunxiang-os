"""Tier 1 — S4-02 NLQ SQL 沙箱与危险关键字防火墙

覆盖路径：
  - assert_safe_sql：SELECT/WITH 通过 / 写入关键字 + 多语句 + SECURITY DEFINER 拒
  - run_safe_query：mock session 流程 + firewall 集成 + statement_timeout + 行数上限

技术约束：
  - 全部使用 unittest.mock，不连接真实数据库（mock-based unit）
  - AsyncSession 以 AsyncMock 替代
  - 用例描述按 CLAUDE.md §20 真实餐厅场景，非技术边界值

S4-02 Issue #289 / Tier 1（read-only + RLS 不可绕 + 防火墙 + 超时 + 行限）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import DBAPIError

from ..services.nlq_keyword_firewall import UnsafeSqlError, assert_safe_sql
from ..services.sql_sandbox import (
    RowLimitExceeded,
    SandboxResult,
    SandboxTimeoutError,
    run_safe_query,
)


# ─────────────── assert_safe_sql ───────────────


class TestNlqKeywordFirewallTier1:
    """危险关键字防火墙 — 任何写入语句都必须被拒，零容忍。"""

    def test_select_today_revenue_is_safe(self):
        """店长问"今天营业额是多少" → SELECT SUM ... 应该放行。"""
        assert_safe_sql(
            "SELECT SUM(total_fen) FROM reports.daily_revenue WHERE day = CURRENT_DATE"
        )

    def test_select_dish_top_with_join_is_safe(self):
        """店长问"今日菜品销量 Top 10" → SELECT JOIN ORDER BY LIMIT 应该放行。"""
        assert_safe_sql(
            "SELECT d.name, SUM(o.qty) AS qty FROM orders.line_items o "
            "JOIN reports.dishes d ON o.dish_id = d.id "
            "GROUP BY d.name ORDER BY qty DESC LIMIT 10"
        )

    def test_with_cte_is_safe(self):
        """店长问"高于平均价的菜" → WITH avg AS (...) SELECT ... 应该放行。"""
        assert_safe_sql(
            "WITH avg_price AS (SELECT AVG(price_fen) AS p FROM reports.dishes) "
            "SELECT name, price_fen FROM reports.dishes, avg_price WHERE price_fen > avg_price.p"
        )

    def test_drop_table_orders_is_rejected(self):
        """LLM 误生成 DROP TABLE → 必须拒。攻击者要的就是这一击。"""
        with pytest.raises(UnsafeSqlError, match="DROP"):
            assert_safe_sql("DROP TABLE orders")

    def test_delete_all_orders_is_rejected(self):
        """LLM 误生成 DELETE → 必须拒。删订单等于删收入凭证。"""
        with pytest.raises(UnsafeSqlError, match="DELETE"):
            assert_safe_sql("DELETE FROM orders WHERE 1=1")

    def test_update_dish_price_is_rejected(self):
        """LLM 误生成 UPDATE → 必须拒。改价应走 actionId 白名单 (S4-03)。"""
        with pytest.raises(UnsafeSqlError, match="UPDATE"):
            assert_safe_sql("UPDATE dishes SET price = 0 WHERE id = 1")

    def test_insert_fake_order_is_rejected(self):
        """LLM 误生成 INSERT → 必须拒。伪造订单 = 伪造营收。"""
        with pytest.raises(UnsafeSqlError, match="INSERT"):
            assert_safe_sql("INSERT INTO orders (id, total_fen) VALUES (1, 9999)")

    def test_truncate_table_is_rejected(self):
        """TRUNCATE → 必须拒。比 DROP 更阴险，无 schema 痕迹。"""
        with pytest.raises(UnsafeSqlError, match="TRUNCATE"):
            assert_safe_sql("TRUNCATE TABLE orders")

    def test_grant_role_is_rejected(self):
        """GRANT → 必须拒。攻击者最爱的提权动作。"""
        with pytest.raises(UnsafeSqlError, match="GRANT"):
            assert_safe_sql("GRANT ALL ON orders TO public")

    def test_create_function_is_rejected(self):
        """CREATE FUNCTION → 必须拒。可植入永久后门。"""
        with pytest.raises(UnsafeSqlError, match="CREATE"):
            assert_safe_sql(
                "CREATE FUNCTION evil() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql"
            )

    def test_alter_table_is_rejected(self):
        """ALTER → 必须拒。改表结构等于改业务规则。"""
        with pytest.raises(UnsafeSqlError, match="ALTER"):
            assert_safe_sql("ALTER TABLE orders ADD COLUMN backdoor TEXT")

    def test_security_definer_is_rejected(self):
        """SECURITY DEFINER 是绕 RLS 的标准技巧 → 必须拒（且 violation 报 SECURITY DEFINER 而非 CREATE）。"""
        with pytest.raises(UnsafeSqlError) as exc_info:
            assert_safe_sql(
                "CREATE FUNCTION tp() RETURNS int LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'"
            )
        assert exc_info.value.violation == "SECURITY DEFINER"

    def test_multi_statement_is_rejected(self):
        """SELECT; DROP TABLE → 拒。多语句 = 注入入口。"""
        with pytest.raises(UnsafeSqlError, match="多语句"):
            assert_safe_sql("SELECT 1; DROP TABLE orders")

    def test_comment_then_drop_is_rejected(self):
        """SELECT 1 -- ; DROP TABLE → 拒。-- 注释包裹注入，strip comment 后多语句暴露。"""
        with pytest.raises(UnsafeSqlError):
            assert_safe_sql("SELECT 1 -- safe\n; DROP TABLE orders")

    def test_block_comment_drop_is_rejected(self):
        """SELECT /* */ ; DROP → 拒。块注释也要剥离再检测多语句。"""
        with pytest.raises(UnsafeSqlError):
            assert_safe_sql("SELECT 1 /* hide */ ; DROP TABLE orders")

    def test_empty_sql_is_rejected(self):
        """空 SQL → 拒（防止 LLM 输出空字符串绕过）。"""
        with pytest.raises(UnsafeSqlError, match="为空"):
            assert_safe_sql("")

    def test_whitespace_only_sql_is_rejected(self):
        """纯空白 SQL → 拒。"""
        with pytest.raises(UnsafeSqlError, match="为空"):
            assert_safe_sql("   \n\t  ")

    def test_non_select_keyword_first_is_rejected(self):
        """不以 SELECT/WITH 开头（如 SHOW、EXPLAIN）→ 拒。S4-02 只放行查询，不放行 DDL/utility。"""
        with pytest.raises(UnsafeSqlError):
            assert_safe_sql("SHOW search_path")


# ─────────────── run_safe_query ───────────────


class TestSqlSandboxRunSafeQueryTier1:
    """SQL 沙箱执行器 — 行数上限 / 超时 / firewall 集成（mock session）。"""

    @pytest.mark.asyncio
    async def test_select_revenue_within_limits_returns_rows(self):
        """店长正常查"今日营收"（5 行结果）→ 返回 SandboxResult.row_count=5。"""
        rows = [{"day": "2026-05-08", "total_fen": 12345}] * 5
        session = _mock_session_returning(rows)
        result = await run_safe_query(
            session,
            "SELECT day, SUM(total_fen) FROM reports.daily_revenue GROUP BY day",
        )
        assert isinstance(result, SandboxResult)
        assert result.row_count == 5
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_select_more_than_max_rows_raises_row_limit(self):
        """LLM 输出未带 LIMIT 全表查询返回 10001 行 → RowLimitExceeded。"""
        rows = [{"id": i} for i in range(10001)]
        session = _mock_session_returning(rows)
        with pytest.raises(RowLimitExceeded, match="10000"):
            await run_safe_query(session, "SELECT id FROM reports.dishes")

    @pytest.mark.asyncio
    async def test_drop_attempt_caught_before_db_call(self):
        """DROP 应在 firewall 拦截，不应到达 DB（session.execute 不被调用）。"""
        session = AsyncMock()
        session.execute = AsyncMock()
        with pytest.raises(UnsafeSqlError, match="DROP"):
            await run_safe_query(session, "DROP TABLE orders")
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_pg_statement_timeout_raises_sandbox_timeout(self):
        """LLM 输出 SELECT pg_sleep(60) → PG 5s 后中断，沙箱抛 SandboxTimeoutError。"""
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(),  # SET LOCAL ok
                DBAPIError(
                    statement="SELECT pg_sleep(60)",
                    params={},
                    orig=Exception("canceling statement due to statement timeout"),
                ),
            ]
        )
        with pytest.raises(SandboxTimeoutError):
            await run_safe_query(
                session,
                "SELECT pg_sleep(60) FROM reports.daily_revenue",
                timeout_ms=5000,
            )

    @pytest.mark.asyncio
    async def test_set_local_statement_timeout_uses_int_value(self):
        """timeout_ms 必须以 int 注入 SET LOCAL，防 SQL 注入（PG SET 不接受 bind param）。"""
        session = _mock_session_returning([])
        await run_safe_query(session, "SELECT 1", timeout_ms=3000)
        # 第一次 execute 应该是 SET LOCAL statement_timeout
        first_call_arg = session.execute.call_args_list[0].args[0]
        sql_text = str(first_call_arg)
        assert "3000" in sql_text
        assert "ms" in sql_text

    @pytest.mark.asyncio
    async def test_negative_timeout_is_rejected(self):
        """timeout_ms <= 0 → ValueError（防止 LLM 输出超大值/负数绕过限制）。"""
        session = AsyncMock()
        with pytest.raises(ValueError):
            await run_safe_query(session, "SELECT 1", timeout_ms=0)
        with pytest.raises(ValueError):
            await run_safe_query(session, "SELECT 1", timeout_ms=-1)


# ─────────────── helpers ───────────────


def _mock_session_returning(rows: list) -> AsyncMock:
    """构造 AsyncMock session：第一次 execute = SET LOCAL ok / 第二次 = 实际 query 返回 rows。"""
    session = AsyncMock()
    query_result = MagicMock()
    query_result.mappings.return_value = rows
    session.execute = AsyncMock(side_effect=[MagicMock(), query_result])
    return session
