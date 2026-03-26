"""Voice Service 测试

覆盖：
- 10 种意图的中文短语识别
- 实体提取（桌号、菜名、数量）
- Mock 转写
- 语音指令流水线端到端
- 边界情况（空输入、无意义文本）
- FastAPI 路由层
"""

from __future__ import annotations

import io
import pytest
import pytest_asyncio

from voice_service import (
    VoiceService,
    TranscriptionResult,
    IntentResult,
    VoiceCommandResult,
    _chinese_num_to_int,
    router,
)


# ─── Fixtures ───


@pytest.fixture
def svc() -> VoiceService:
    return VoiceService()


# ─── 中文数字转换 ───


class TestChineseNumToInt:
    def test_arabic_digits(self) -> None:
        assert _chinese_num_to_int("1") == 1
        assert _chinese_num_to_int("23") == 23
        assert _chinese_num_to_int("100") == 100

    def test_single_chinese(self) -> None:
        assert _chinese_num_to_int("一") == 1
        assert _chinese_num_to_int("五") == 5
        assert _chinese_num_to_int("九") == 9

    def test_tens(self) -> None:
        assert _chinese_num_to_int("十") == 10
        assert _chinese_num_to_int("十二") == 12
        assert _chinese_num_to_int("三十") == 30
        assert _chinese_num_to_int("二十五") == 25

    def test_two_liang(self) -> None:
        assert _chinese_num_to_int("两") == 2


# ─── open_table 意图 ───


class TestOpenTable:
    @pytest.mark.asyncio
    async def test_kai_tai(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("开台")
        assert r.intent == "open_table"

    @pytest.mark.asyncio
    async def test_kai_zhuo(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("开桌")
        assert r.intent == "open_table"

    @pytest.mark.asyncio
    async def test_table_kai_tai(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("5号桌开台")
        assert r.intent == "open_table"
        assert r.entities.get("table_no") == "5"

    @pytest.mark.asyncio
    async def test_kai_tai_table(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("开台3号桌")
        assert r.intent == "open_table"
        assert r.entities.get("table_no") == "3"

    @pytest.mark.asyncio
    async def test_table_no_zhuo(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("12号开台")
        assert r.intent == "open_table"
        assert r.entities.get("table_no") == "12"

    @pytest.mark.asyncio
    async def test_suggested_action(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("开台")
        assert r.suggested_action["agent_id"] == "serve_dispatch"
        assert r.suggested_action["action"] == "assign_table"


# ─── add_dish 意图 ───


class TestAddDish:
    @pytest.mark.asyncio
    async def test_jia_cai(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("加菜")
        assert r.intent == "add_dish"

    @pytest.mark.asyncio
    async def test_jia_yi_fen(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("加一份红烧肉")
        assert r.intent == "add_dish"
        assert r.entities.get("dish_name") == "红烧肉"
        assert r.entities.get("quantity") == 1

    @pytest.mark.asyncio
    async def test_lai_ge(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("来个宫保鸡丁")
        assert r.intent == "add_dish"
        assert r.entities.get("dish_name") == "宫保鸡丁"

    @pytest.mark.asyncio
    async def test_lai_liang_fen(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("来两份酸菜鱼")
        assert r.intent == "add_dish"
        assert r.entities.get("dish_name") == "酸菜鱼"
        assert r.entities.get("quantity") == 2

    @pytest.mark.asyncio
    async def test_shang_san_ge(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("上三个小炒肉")
        assert r.intent == "add_dish"
        assert r.entities.get("dish_name") == "小炒肉"
        assert r.entities.get("quantity") == 3

    @pytest.mark.asyncio
    async def test_zai_lai(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("再来一份麻婆豆腐")
        assert r.intent == "add_dish"
        assert r.entities.get("dish_name") == "麻婆豆腐"
        assert r.entities.get("quantity") == 1

    @pytest.mark.asyncio
    async def test_table_add(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("5号桌加一份红烧肉")
        assert r.intent == "add_dish"
        assert r.entities.get("table_no") == "5"
        assert r.entities.get("dish_name") == "红烧肉"

    @pytest.mark.asyncio
    async def test_dish_quantity_order(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("红烧肉来两份")
        assert r.intent == "add_dish"
        assert r.entities.get("dish_name") == "红烧肉"
        assert r.entities.get("quantity") == 2

    @pytest.mark.asyncio
    async def test_suggested_action(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("加一份红烧肉")
        assert r.suggested_action["agent_id"] == "smart_menu"
        assert r.suggested_action["action"] == "recommend_dishes"


# ─── checkout 意图 ───


class TestCheckout:
    @pytest.mark.asyncio
    async def test_mai_dan(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("买单")
        assert r.intent == "checkout"

    @pytest.mark.asyncio
    async def test_jie_zhang(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("结账")
        assert r.intent == "checkout"

    @pytest.mark.asyncio
    async def test_mai_dan_alias(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("埋单")
        assert r.intent == "checkout"

    @pytest.mark.asyncio
    async def test_table_checkout(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("8号桌结账")
        assert r.intent == "checkout"
        assert r.entities.get("table_no") == "8"

    @pytest.mark.asyncio
    async def test_checkout_table(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("结账7号桌")
        assert r.intent == "checkout"
        assert r.entities.get("table_no") == "7"


# ─── rush_order 意图 ───


class TestRushOrder:
    @pytest.mark.asyncio
    async def test_cui_cai(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("催菜")
        assert r.intent == "rush_order"

    @pytest.mark.asyncio
    async def test_cui_yi_xia(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("催一下")
        assert r.intent == "rush_order"

    @pytest.mark.asyncio
    async def test_cui_dan(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("催单")
        assert r.intent == "rush_order"

    @pytest.mark.asyncio
    async def test_table_rush(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("3号桌催菜")
        assert r.intent == "rush_order"
        assert r.entities.get("table_no") == "3"

    @pytest.mark.asyncio
    async def test_suggested_action(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("催菜")
        assert r.suggested_action["agent_id"] == "serve_dispatch"
        assert r.suggested_action["action"] == "prioritize_order"


# ─── cancel_dish 意图 ───


class TestCancelDish:
    @pytest.mark.asyncio
    async def test_tui_cai(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("退菜")
        assert r.intent == "cancel_dish"

    @pytest.mark.asyncio
    async def test_tui_dish(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("退红烧肉")
        assert r.intent == "cancel_dish"
        assert r.entities.get("dish_name") == "红烧肉"

    @pytest.mark.asyncio
    async def test_qu_xiao_dish(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("取消宫保鸡丁")
        assert r.intent == "cancel_dish"
        assert r.entities.get("dish_name") == "宫保鸡丁"

    @pytest.mark.asyncio
    async def test_dish_bu_yao_le(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("酸菜鱼不要了")
        assert r.intent == "cancel_dish"
        assert r.entities.get("dish_name") == "酸菜鱼"

    @pytest.mark.asyncio
    async def test_tui_with_quantity(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("退一份麻婆豆腐")
        assert r.intent == "cancel_dish"
        assert r.entities.get("dish_name") == "麻婆豆腐"
        assert r.entities.get("quantity") == 1


# ─── call_service 意图 ───


class TestCallService:
    @pytest.mark.asyncio
    async def test_fu_wu_yuan(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("服务员")
        assert r.intent == "call_service"

    @pytest.mark.asyncio
    async def test_jiao_yi_xia(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("叫一下服务员")
        assert r.intent == "call_service"

    @pytest.mark.asyncio
    async def test_hu_jiao(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("呼叫服务员")
        assert r.intent == "call_service"

    @pytest.mark.asyncio
    async def test_suggested_action(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("服务员")
        assert r.suggested_action["agent_id"] == "smart_service"
        assert r.suggested_action["action"] == "handle_request"


# ─── query_status 意图 ───


class TestQueryStatus:
    @pytest.mark.asyncio
    async def test_table_status(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("6号桌什么情况")
        assert r.intent == "query_status"
        assert r.entities.get("table_no") == "6"

    @pytest.mark.asyncio
    async def test_table_zenmeyang(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("10号桌怎么样了")
        assert r.intent == "query_status"
        assert r.entities.get("table_no") == "10"

    @pytest.mark.asyncio
    async def test_cha_yi_xia_dingdan(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("查一下订单")
        assert r.intent == "query_status"

    @pytest.mark.asyncio
    async def test_cha_kan_zhuangtai(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("查看状态")
        assert r.intent == "query_status"

    @pytest.mark.asyncio
    async def test_suggested_action(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("6号桌什么情况")
        assert r.suggested_action["agent_id"] == "serve_dispatch"
        assert r.suggested_action["action"] == "get_kitchen_status"


# ─── daily_report 意图 ───


class TestDailyReport:
    @pytest.mark.asyncio
    async def test_jintian_yingyee(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("今天营业额")
        assert r.intent == "daily_report"

    @pytest.mark.asyncio
    async def test_jintian_mai_le_duoshao(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("今天卖了多少")
        assert r.intent == "daily_report"

    @pytest.mark.asyncio
    async def test_zuotian_shouru(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("昨天收入")
        assert r.intent == "daily_report"

    @pytest.mark.asyncio
    async def test_benyue_liushui(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("本月流水")
        assert r.intent == "daily_report"

    @pytest.mark.asyncio
    async def test_yingyee_duoshao(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("营业额多少")
        assert r.intent == "daily_report"

    @pytest.mark.asyncio
    async def test_ri_bao(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("日报")
        assert r.intent == "daily_report"

    @pytest.mark.asyncio
    async def test_suggested_action(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("今天营业额")
        assert r.suggested_action["agent_id"] == "finance_audit"
        assert r.suggested_action["action"] == "daily_summary"


# ─── stock_check 意图 ───


class TestStockCheck:
    @pytest.mark.asyncio
    async def test_dish_hai_you_duoshao(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("红烧肉还有多少")
        assert r.intent == "stock_check"
        assert r.entities.get("dish_name") == "红烧肉"

    @pytest.mark.asyncio
    async def test_dish_hai_you_ma(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("酸菜鱼还有吗")
        assert r.intent == "stock_check"
        assert r.entities.get("dish_name") == "酸菜鱼"

    @pytest.mark.asyncio
    async def test_kucun_cha(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("库存查一下")
        assert r.intent == "stock_check"

    @pytest.mark.asyncio
    async def test_cha_yi_xia_kucun(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("查一下库存")
        assert r.intent == "stock_check"

    @pytest.mark.asyncio
    async def test_dish_you_mei_you(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("小龙虾有没有")
        assert r.intent == "stock_check"
        assert r.entities.get("dish_name") == "小龙虾"

    @pytest.mark.asyncio
    async def test_suggested_action(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("红烧肉还有多少")
        assert r.suggested_action["agent_id"] == "inventory_alert"
        assert r.suggested_action["action"] == "check_stock"


# ─── unknown 意图（边界情况）───


class TestUnknown:
    @pytest.mark.asyncio
    async def test_empty_string(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("")
        assert r.intent == "unknown"
        assert r.confidence == 0.0

    @pytest.mark.asyncio
    async def test_whitespace_only(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("   ")
        assert r.intent == "unknown"
        assert r.confidence == 0.0

    @pytest.mark.asyncio
    async def test_nonsense(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("阿斯顿发生的烦恼哈哈")
        assert r.intent == "unknown"

    @pytest.mark.asyncio
    async def test_english_unrelated(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("hello world good morning")
        assert r.intent == "unknown"

    @pytest.mark.asyncio
    async def test_numbers_only(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("12345")
        assert r.intent == "unknown"

    @pytest.mark.asyncio
    async def test_empty_action(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("")
        assert r.suggested_action == {}


# ─── 转写 Mock 模式 ───


class TestTranscriptionMock:
    @pytest.mark.asyncio
    async def test_mock_chinese(self, svc: VoiceService) -> None:
        result = await svc.transcribe(b"fake_audio_bytes", language="zh")
        assert result.source == "mock"
        assert result.language == "zh"
        assert len(result.text) > 0
        assert result.confidence == 0.0
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_mock_english(self, svc: VoiceService) -> None:
        result = await svc.transcribe(b"fake_audio_bytes", language="en")
        assert result.source == "mock"
        assert result.language == "en"
        assert "table" in result.text.lower()

    @pytest.mark.asyncio
    async def test_mock_returns_dataclass(self, svc: VoiceService) -> None:
        result = await svc.transcribe(b"bytes", language="zh")
        assert isinstance(result, TranscriptionResult)


# ─── 语音指令流水线 ───


class TestVoiceCommandPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, svc: VoiceService) -> None:
        """端到端：mock 转写 → 意图解析 → Agent 路由"""
        result = await svc.execute_voice_command(b"fake_audio", language="zh")
        assert isinstance(result, VoiceCommandResult)
        assert isinstance(result.transcription, TranscriptionResult)
        assert isinstance(result.intent, IntentResult)
        # mock 中文转写是 "五号桌加一份红烧肉"，应解析为 add_dish
        assert result.transcription.source == "mock"
        assert result.intent.intent == "add_dish"

    @pytest.mark.asyncio
    async def test_pipeline_entities(self, svc: VoiceService) -> None:
        """mock 中文 "五号桌加一份红烧肉" 应提取完整实体"""
        result = await svc.execute_voice_command(b"fake_audio", language="zh")
        entities = result.intent.entities
        assert entities.get("table_no") == "5"
        assert entities.get("dish_name") == "红烧肉"
        assert entities.get("quantity") == 1

    @pytest.mark.asyncio
    async def test_pipeline_agent_routing(self, svc: VoiceService) -> None:
        """add_dish 应路由到 smart_menu Agent"""
        result = await svc.execute_voice_command(b"fake_audio", language="zh")
        assert result.agent_result is not None
        assert result.agent_result["agent_id"] == "smart_menu"
        assert result.agent_result["action"] == "recommend_dishes"
        assert result.agent_result["status"] == "pending"


# ─── 实体提取综合 ───


class TestEntityExtraction:
    @pytest.mark.asyncio
    async def test_table_number_single_digit(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("3号桌催菜")
        assert r.entities["table_no"] == "3"

    @pytest.mark.asyncio
    async def test_table_number_double_digit(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("15号桌结账")
        assert r.entities["table_no"] == "15"

    @pytest.mark.asyncio
    async def test_dish_name_two_chars(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("加一份凉面")
        assert r.entities["dish_name"] == "凉面"

    @pytest.mark.asyncio
    async def test_dish_name_four_chars(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("加一份麻婆豆腐")
        assert r.entities["dish_name"] == "麻婆豆腐"

    @pytest.mark.asyncio
    async def test_quantity_arabic(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("加3份红烧肉")
        assert r.entities["quantity"] == 3

    @pytest.mark.asyncio
    async def test_quantity_chinese_wu(self, svc: VoiceService) -> None:
        r = await svc.parse_intent("加五份小炒肉")
        assert r.entities["quantity"] == 5

    @pytest.mark.asyncio
    async def test_confidence_with_entities(self, svc: VoiceService) -> None:
        """有实体的匹配应该有更高置信度"""
        r = await svc.parse_intent("5号桌开台")
        assert r.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_confidence_without_entities(self, svc: VoiceService) -> None:
        """无实体的匹配置信度稍低"""
        r = await svc.parse_intent("催菜")
        assert r.confidence >= 0.8


# ─── FastAPI 路由层测试 ───


class TestFastAPIRoutes:
    """使用 httpx + FastAPI TestClient 测试路由层"""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_parse_intent_endpoint(self, client) -> None:
        resp = client.post("/api/v1/voice/parse-intent", json={"text": "5号桌开台"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["intent"] == "open_table"
        assert body["data"]["entities"]["table_no"] == "5"

    def test_parse_intent_unknown(self, client) -> None:
        resp = client.post("/api/v1/voice/parse-intent", json={"text": "随便说说"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["intent"] == "unknown"

    def test_transcribe_endpoint_mock(self, client) -> None:
        audio_content = b"fake wav content"
        resp = client.post(
            "/api/v1/voice/transcribe",
            files={"file": ("test.wav", io.BytesIO(audio_content), "audio/wav")},
            data={"language": "zh"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["source"] == "mock"
        assert len(body["data"]["text"]) > 0

    def test_transcribe_empty_file(self, client) -> None:
        resp = client.post(
            "/api/v1/voice/transcribe",
            files={"file": ("test.wav", io.BytesIO(b""), "audio/wav")},
            data={"language": "zh"},
        )
        assert resp.status_code == 400

    def test_transcribe_bad_language(self, client) -> None:
        resp = client.post(
            "/api/v1/voice/transcribe",
            files={"file": ("test.wav", io.BytesIO(b"data"), "audio/wav")},
            data={"language": "fr"},
        )
        assert resp.status_code == 400

    def test_command_endpoint(self, client) -> None:
        audio_content = b"fake wav content"
        resp = client.post(
            "/api/v1/voice/command",
            files={"file": ("test.wav", io.BytesIO(audio_content), "audio/wav")},
            data={"language": "zh"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "transcription" in body["data"]
        assert "intent" in body["data"]
        assert "agent_result" in body["data"]

    def test_command_empty_audio(self, client) -> None:
        resp = client.post(
            "/api/v1/voice/command",
            files={"file": ("test.wav", io.BytesIO(b""), "audio/wav")},
            data={"language": "zh"},
        )
        assert resp.status_code == 400
