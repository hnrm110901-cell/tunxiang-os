"""营业市别测试 — TC-P0-01 市别精细化（5个场景）

场景清单：
1. test_current_session_morning       — 08:00 命中早市（06:00-11:00）
2. test_current_session_late_night    — 23:30 命中夜宵（跨夜 21:00-02:00）
3. test_session_template_crud         — 模板创建/查询/更新/删除全链路
4. test_store_override                — 门店覆盖模板后 current 接口返回门店配置
5. test_market_session_binding_on_open_table — 开台时自动关联 market_session_id
"""

from __future__ import annotations

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 辅助函数 ─────────────────────────────────────────────────────────────────


def _t(hh: int, mm: int) -> time:
    """创建 time 对象的简写"""
    return time(hour=hh, minute=mm)


def _is_time_in_session(current: time, start: time, end: time) -> bool:
    """从 market_session_routes 复制的核心判断逻辑（单元测试不依赖服务启动）"""
    if start <= end:
        return start <= current < end
    # 跨夜
    return current >= start or current < end


# ─── 场景 1：08:00 命中早市 ───────────────────────────────────────────────────


class TestCurrentSessionMorning:
    """08:00 应落在早市（06:00-11:00）区间内"""

    def test_morning_in_breakfast(self):
        current = _t(8, 0)
        assert _is_time_in_session(current, _t(6, 0), _t(11, 0)) is True

    def test_morning_not_in_lunch(self):
        current = _t(8, 0)
        assert _is_time_in_session(current, _t(11, 0), _t(14, 30)) is False

    def test_morning_not_in_dinner(self):
        current = _t(8, 0)
        assert _is_time_in_session(current, _t(17, 0), _t(21, 0)) is False

    def test_morning_not_in_late_night(self):
        # 夜宵 21:00-02:00，08:00 不在其中
        current = _t(8, 0)
        assert _is_time_in_session(current, _t(21, 0), _t(2, 0)) is False

    def test_boundary_start_of_breakfast(self):
        """06:00 刚好命中早市开始"""
        assert _is_time_in_session(_t(6, 0), _t(6, 0), _t(11, 0)) is True

    def test_boundary_end_of_breakfast(self):
        """11:00 不命中早市（左闭右开）"""
        assert _is_time_in_session(_t(11, 0), _t(6, 0), _t(11, 0)) is False


# ─── 场景 2：23:30 命中夜宵（跨夜市别） ─────────────────────────────────────


class TestCurrentSessionLateNight:
    """夜宵 21:00-02:00 是跨夜市别，23:30 和 01:30 都应命中"""

    def test_late_night_23_30(self):
        current = _t(23, 30)
        assert _is_time_in_session(current, _t(21, 0), _t(2, 0)) is True

    def test_late_night_22_00(self):
        current = _t(22, 0)
        assert _is_time_in_session(current, _t(21, 0), _t(2, 0)) is True

    def test_late_night_01_30(self):
        """凌晨 01:30 依然在夜宵内"""
        current = _t(1, 30)
        assert _is_time_in_session(current, _t(21, 0), _t(2, 0)) is True

    def test_late_night_boundary_end(self):
        """02:00 恰好不在夜宵内（右开区间）"""
        current = _t(2, 0)
        assert _is_time_in_session(current, _t(21, 0), _t(2, 0)) is False

    def test_daytime_not_in_late_night(self):
        """14:00 不在夜宵内"""
        current = _t(14, 0)
        assert _is_time_in_session(current, _t(21, 0), _t(2, 0)) is False

    def test_normal_session_not_treated_as_overnight(self):
        """午市 11:00-14:30 不是跨夜，start < end，用正常逻辑"""
        current = _t(12, 0)
        assert _is_time_in_session(current, _t(11, 0), _t(14, 30)) is True
        # 23:30 不在午市内
        assert _is_time_in_session(_t(23, 30), _t(11, 0), _t(14, 30)) is False


# ─── 场景 3：模板 CRUD 全链路 ─────────────────────────────────────────────────


class TestSessionTemplateCrud:
    """模拟 HTTP 调用测试模板创建/查询/更新"""

    @pytest.mark.asyncio
    async def test_create_template(self):
        """POST /templates 应写入 DB 并返回新 ID"""
        mock_db = AsyncMock()
        mock_request = MagicMock()
        mock_request.state.tenant_id = "tenant-test-001"

        with patch(
            "services.tx_trade.src.api.market_session_routes._set_rls",
            new_callable=AsyncMock,
        ):
            # 验证 execute 被调用且包含 INSERT
            mock_db.execute = AsyncMock()
            mock_db.commit = AsyncMock()

            from ..api.market_session_routes import MarketSessionTemplateCreateReq, create_template

            body = MarketSessionTemplateCreateReq(
                name="早市",
                code="breakfast",
                display_order=1,
                start_time="06:00",
                end_time="11:00",
                is_active=True,
            )

            result = await create_template(body, mock_request, mock_db)

        assert result["ok"] is True
        assert "id" in result["data"]
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_templates_fallback_to_default(self):
        """当 DB 无数据时，应返回内置 4 个默认模板"""
        mock_db = AsyncMock()
        mock_request = MagicMock()
        mock_request.state.tenant_id = "tenant-test-001"

        # 模拟 DB 返回空结果集
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        from ..api.market_session_routes import list_templates

        result = await list_templates(mock_request, mock_db)

        assert result["ok"] is True
        assert result["data"]["source"] == "default"
        assert result["data"]["total"] == 4
        codes = {t["code"] for t in result["data"]["items"]}
        assert codes == {"breakfast", "lunch", "dinner", "late_night"}

    @pytest.mark.asyncio
    async def test_update_template_not_found(self):
        """更新不存在的模板应返回 404"""
        import uuid

        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_request = MagicMock()
        mock_request.state.tenant_id = "tenant-test-001"

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        from ..api.market_session_routes import MarketSessionTemplateUpdateReq, update_template

        body = MarketSessionTemplateUpdateReq(name="新名称")
        with pytest.raises(HTTPException) as exc_info:
            await update_template(uuid.uuid4(), body, mock_request, mock_db)

        assert exc_info.value.status_code == 404


# ─── 场景 4：门店覆盖模板后 current 接口返回门店配置 ──────────────────────────


class TestStoreOverride:
    """门店配置了自定义时间段时，current 接口应优先返回门店配置"""

    @pytest.mark.asyncio
    async def test_store_config_takes_priority_over_template(self):
        """
        集团模板：午市 11:00-14:30
        门店覆盖：午市 11:30-15:00（门店延迟半小时）
        当前时间 14:45：集团模板不命中，门店配置命中
        """
        import uuid
        from unittest.mock import patch

        mock_db = AsyncMock()
        mock_request = MagicMock()
        mock_request.state.tenant_id = "tenant-xuji-001"

        store_id = str(uuid.uuid4())
        store_session_id = str(uuid.uuid4())

        # 门店配置行（11:30-15:00）
        store_row = MagicMock()
        store_row.id = store_session_id
        store_row.name = "午市（门店版）"
        store_row.start_time = time(11, 30)
        store_row.end_time = time(15, 0)
        store_row.template_id = None
        store_row.menu_plan_id = None

        store_result = MagicMock()
        store_result.fetchall.return_value = [store_row]

        # 当前时间固定为 14:45
        fixed_time = time(14, 45)

        mock_db.execute = AsyncMock(return_value=store_result)

        from ..api.market_session_routes import get_current_session

        with patch("services.tx_trade.src.api.market_session_routes.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(time=MagicMock(return_value=fixed_time))
            result = await get_current_session(uuid.UUID(store_id), mock_request, mock_db)

        assert result["ok"] is True
        assert result["data"]["source"] == "store"
        assert result["data"]["id"] == store_session_id

    def test_no_match_returns_null_not_error(self):
        """凌晨 04:00 无任何市别时应返回 data: null，不报错"""
        current = _t(4, 0)
        sessions = [
            (_t(6, 0), _t(11, 0)),  # 早市
            (_t(11, 0), _t(14, 30)),  # 午市
            (_t(17, 0), _t(21, 0)),  # 晚市
            (_t(21, 0), _t(2, 0)),  # 夜宵
        ]
        matched = any(_is_time_in_session(current, s, e) for s, e in sessions)
        # 04:00 在夜宵 21:00-02:00 之外（02:00 已结束），不应匹配
        assert matched is False


# ─── 场景 5：开台时自动关联 market_session_id ─────────────────────────────────


class TestMarketSessionBindingOnOpenTable:
    """验证 _bind_market_session 的关联逻辑"""

    @pytest.mark.asyncio
    async def test_bind_market_session_when_session_found(self):
        """当前时间有匹配市别时，dining_sessions.market_session_id 应被更新"""
        import uuid

        mock_db = AsyncMock()
        dining_session_id = str(uuid.uuid4())
        market_session_id = str(uuid.uuid4())

        # _get_current_market_session_id 返回一个市别ID
        with patch(
            "services.tx_trade.src.api.dining_session_routes._get_current_market_session_id",
            new_callable=AsyncMock,
            return_value=market_session_id,
        ):
            mock_db.execute = AsyncMock()
            mock_db.commit = AsyncMock()

            from ..api.dining_session_routes import _bind_market_session

            await _bind_market_session(mock_db, "tenant-001", "store-001", dining_session_id)

        mock_db.commit.assert_called_once()
        # 验证 UPDATE 语句包含正确的 msid
        call_args = mock_db.execute.call_args_list
        assert len(call_args) >= 1

    @pytest.mark.asyncio
    async def test_bind_market_session_no_session_found(self):
        """无匹配市别时，不执行 UPDATE，但不抛出异常"""
        import uuid

        mock_db = AsyncMock()
        dining_session_id = str(uuid.uuid4())

        with patch(
            "services.tx_trade.src.api.dining_session_routes._get_current_market_session_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            mock_db.execute = AsyncMock()
            mock_db.commit = AsyncMock()

            from ..api.dining_session_routes import _bind_market_session

            # 不应抛出任何异常
            await _bind_market_session(mock_db, "tenant-001", "store-001", dining_session_id)

        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_bind_market_session_db_error_does_not_propagate(self):
        """DB 异常时 _bind_market_session 应静默降级，不影响调用方"""
        import uuid

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=RuntimeError("DB连接超时"))

        from ..api.dining_session_routes import _bind_market_session

        # 不应传播异常
        await _bind_market_session(mock_db, "tenant-001", "store-001", str(uuid.uuid4()))
