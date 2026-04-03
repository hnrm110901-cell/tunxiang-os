"""TV Menu Wall 测试"""
import pytest
from services.tx_trade_src_services import tv_menu_service as svc


class TestZoneLayouts:
    def test_2_screens(self):
        assert len(svc.ZONE_LAYOUTS[2]) == 2
        assert svc.ZONE_LAYOUTS[2][0]["zone"] == "signature"

    def test_4_screens(self):
        assert len(svc.ZONE_LAYOUTS[4]) == 4

    def test_8_screens(self):
        assert len(svc.ZONE_LAYOUTS[8]) == 8
        zones = [z["zone"] for z in svc.ZONE_LAYOUTS[8]]
        assert "seafood" in zones
        assert "recommend" in zones

    def test_12_screens(self):
        assert len(svc.ZONE_LAYOUTS[12]) == 11  # 12屏但hero占2屏
        zones = [z["zone"] for z in svc.ZONE_LAYOUTS[12]]
        assert "combo" in zones
        assert "kids" in zones
        assert "ranking" in zones


class TestTimeSlot:
    def test_all_hours_covered(self):
        """每个小时都能找到对应时段"""
        for hour in range(6, 26):
            found = False
            for slot in svc.TIME_SLOTS:
                if slot["start"] <= hour < slot["end"]:
                    found = True
                    break
            assert found, f"hour {hour} not covered"

    def test_lunch_slot(self):
        slot = svc.TIME_SLOTS[1]
        assert slot["slot"] == "lunch"
        assert slot["start"] == 10
        assert slot["end"] == 14


class TestWeatherRecommendation:
    def test_rainy(self):
        config = svc.WEATHER_RECOMMENDATIONS["rainy"]
        assert "火锅" in config["prefer_tags"]

    def test_hot(self):
        config = svc.WEATHER_RECOMMENDATIONS["hot"]
        assert "冷饮" in config["prefer_tags"]

    def test_unknown_weather_fallback(self):
        config = svc.WEATHER_RECOMMENDATIONS.get("tornado", svc.WEATHER_RECOMMENDATIONS["normal"])
        assert config["label"] == "今日推荐"


class TestDisplayScore:
    def test_high_margin_high_sales(self):
        score = svc.compute_dish_display_score(0.6, 100, 4.5, False)
        assert score > 0.5

    def test_new_dish_bonus(self):
        score_old = svc.compute_dish_display_score(0.3, 10, 3.0, False)
        score_new = svc.compute_dish_display_score(0.3, 10, 3.0, True)
        assert score_new > score_old

    def test_zero_everything(self):
        score = svc.compute_dish_display_score(0, 0, 0, False)
        assert score == 0.0


class TestClassifyDisplaySize:
    def test_hero(self):
        assert svc.classify_display_size(0.9, 0.85) == "hero"

    def test_medium(self):
        assert svc.classify_display_size(0.5, 0.6) == "medium"

    def test_small(self):
        assert svc.classify_display_size(0.3, 0.3) == "small"

    def test_text(self):
        assert svc.classify_display_size(0.1, 0.1) == "text"


class TestRankingValidation:
    @pytest.mark.asyncio
    async def test_valid_metric(self):
        result = await svc.get_ranking_board("S1", "hot_sales", "T1", None)
        assert result["metric"] == "hot_sales"

    @pytest.mark.asyncio
    async def test_invalid_metric(self):
        with pytest.raises(ValueError, match="无效的排行指标"):
            await svc.get_ranking_board("S1", "invalid", "T1", None)
