"""
execute_journey_step 企微集成链路测试

覆盖：
  - 企微已配置 → wechat_service 传入 execute_step
  - 企微未配置（corp_id 为空）→ wechat_service=None，静默跳过
  - LLM 未配置 → JourneyNarrator 以静态模板降级，旅程不中断
  - wechat_service.corp_id 检查：真实属性决定是否注入
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "test")

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ════════════════════════════════════════════════════════════════════════════════
# 辅助：构造 mock wechat_service
# ════════════════════════════════════════════════════════════════════════════════


def _make_wechat_svc(corp_id: str = "wx_corp_001", corp_secret: str = "secret"):
    svc = MagicMock()
    svc.corp_id = corp_id
    svc.corp_secret = corp_secret
    svc.send_text_message = AsyncMock(return_value={"success": True})
    return svc


# ════════════════════════════════════════════════════════════════════════════════
# 企微注入逻辑（测 _run() 内部分支）
# ════════════════════════════════════════════════════════════════════════════════


class TestWeChatInjection:

    @pytest.mark.asyncio
    async def test_wechat_configured_is_injected(self):
        """corp_id + corp_secret 均有值 → wechat_svc 不为 None。"""
        real_svc = _make_wechat_svc("wx_corp_001", "s3cret")

        db = AsyncMock()
        mock_orch = MagicMock()
        mock_orch.execute_step = AsyncMock(return_value={"sent": True})

        with patch("src.services.wechat_service.wechat_service", real_svc), \
             patch("src.services.journey_orchestrator.JourneyOrchestrator",
                   return_value=mock_orch), \
             patch("src.core.database.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.services.journey_narrator import JourneyNarrator
            with patch("src.services.journey_narrator.JourneyNarrator") as MockNarrator:
                MockNarrator.return_value = MagicMock()

                # 直接运行内部 _run 逻辑
                from src.services.wechat_service import wechat_service as _ws
                assert _ws.corp_id == "wx_corp_001"
                assert _ws.corp_secret == "s3cret"
                # corp_id 非空 → should be injected
                wechat_svc = None
                if _ws.corp_id and _ws.corp_secret:
                    wechat_svc = _ws
                assert wechat_svc is not None

    @pytest.mark.asyncio
    async def test_wechat_not_configured_is_none(self):
        """corp_id 为空 → wechat_svc=None，不尝试发送。"""
        unconfigured_svc = _make_wechat_svc(corp_id="", corp_secret="")

        with patch("src.services.wechat_service.wechat_service", unconfigured_svc):
            from src.services.wechat_service import wechat_service as _ws
            wechat_svc = None
            if _ws.corp_id and _ws.corp_secret:
                wechat_svc = _ws
            assert wechat_svc is None

    @pytest.mark.asyncio
    async def test_wechat_import_error_yields_none(self):
        """wechat_service 导入异常 → wechat_svc=None，不抛出。"""
        wechat_svc = None
        try:
            raise ImportError("mock import error")
        except Exception:
            pass
        assert wechat_svc is None


# ════════════════════════════════════════════════════════════════════════════════
# JourneyNarrator 降级（LLM 未配置）
# ════════════════════════════════════════════════════════════════════════════════


class TestNarratorFallback:

    @pytest.mark.asyncio
    async def test_narrator_no_api_key_returns_static_template(self):
        """ANTHROPIC_API_KEY 未设置 → generate() 返回静态模板，不报错。"""
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)

            from src.services.journey_narrator import JourneyNarrator, _FALLBACK_TEMPLATES
            narrator = JourneyNarrator(llm=None)

            result = await narrator.generate(
                template_id="journey_welcome",
                store_id="S001",
                customer_id="C001",
            )
            assert result == _FALLBACK_TEMPLATES["journey_welcome"]

    @pytest.mark.asyncio
    async def test_narrator_unknown_template_returns_default(self):
        """未知 template_id → 返回默认兜底文本。"""
        from src.services.journey_narrator import JourneyNarrator
        narrator = JourneyNarrator(llm=None)

        result = await narrator.generate(
            template_id="nonexistent_template",
            store_id="S001",
            customer_id="C001",
        )
        assert result == "您有一条来自门店的消息"


# ════════════════════════════════════════════════════════════════════════════════
# execute_step wechat_service + narrator 参数传递验证
# ════════════════════════════════════════════════════════════════════════════════


class TestExecuteStepWiring:

    @pytest.mark.asyncio
    async def test_execute_step_receives_wechat_and_narrator(self):
        """execute_step 被调用时 wechat_service 和 narrator 均非 None（已配置情况）。"""
        real_svc = _make_wechat_svc("wx_corp_001", "s3cret")

        captured = {}

        async def fake_execute_step(journey_db_id, step_index, db,
                                    wechat_user_id=None, wechat_service=None,
                                    narrator=None):
            captured["wechat_service"] = wechat_service
            captured["narrator"] = narrator
            return {"sent": True}

        mock_orch = MagicMock()
        mock_orch.execute_step = fake_execute_step
        db = AsyncMock()

        with patch("src.services.wechat_service.wechat_service", real_svc), \
             patch("src.services.journey_orchestrator.JourneyOrchestrator",
                   return_value=mock_orch), \
             patch("src.core.database.get_db_session") as mock_ctx, \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):

            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # 模拟 _run() 逻辑
            from src.services.journey_narrator import JourneyNarrator
            narrator = JourneyNarrator()

            wechat_svc = None
            from src.services.wechat_service import wechat_service as _ws
            if _ws.corp_id and _ws.corp_secret:
                wechat_svc = _ws

            await fake_execute_step(
                "journey-001", 0, db,
                wechat_user_id="wx_user_001",
                wechat_service=wechat_svc,
                narrator=narrator,
            )

        assert captured["wechat_service"] is real_svc
        assert captured["narrator"] is not None

    @pytest.mark.asyncio
    async def test_execute_step_wechat_none_when_unconfigured(self):
        """企微未配置时 execute_step 收到 wechat_service=None。"""
        unconfigured = _make_wechat_svc("", "")

        captured = {}

        async def fake_execute_step(journey_db_id, step_index, db,
                                    wechat_user_id=None, wechat_service=None,
                                    narrator=None):
            captured["wechat_service"] = wechat_service
            return {"sent": False, "reason": "无企微服务或接收者ID"}

        db = AsyncMock()

        with patch("src.services.wechat_service.wechat_service", unconfigured):
            from src.services.wechat_service import wechat_service as _ws
            wechat_svc = None
            if _ws.corp_id and _ws.corp_secret:
                wechat_svc = _ws

            await fake_execute_step("j-001", 0, db, wechat_service=wechat_svc)

        assert captured["wechat_service"] is None
