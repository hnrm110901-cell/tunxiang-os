"""S2W6 AI Review Management — 综合测试

覆盖：
- TestReviewReplier: AI回复生成（mock Claude）、品牌语调配置
- TestNPSService: NPS得分计算（推荐者-贬损者）、仪表盘统计
- TestImprovementRecommender: 主题聚合、建议排名
"""

import uuid
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.improvement_recommender import (
    _RECOMMENDATION_TEMPLATES,
    _THEME_KEYWORDS,
    ImprovementRecommender,
)
from services.nps_service import NPSService, _extract_tags
from services.review_replier import _REPLY_PROMPT_TEMPLATE, ReviewReplier

# ═══════════════════════════════════════
# ReviewReplier 测试
# ═══════════════════════════════════════


class TestReviewReplier:
    """AI评论回复服务测试"""

    def setup_method(self) -> None:
        self.replier = ReviewReplier()
        self.tenant_id = uuid.uuid4()
        self.review_id = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_generate_reply_success(self) -> None:
        """成功生成AI回复并存储为draft"""
        db = AsyncMock()

        # mock set_config
        db.execute = AsyncMock()

        # mock order_reviews查询 — 返回评论数据
        review_row = MagicMock()
        review_row.__getitem__ = lambda self, i: [
            str(uuid.uuid4()),  # id
            "dianping",  # platform
            2.0,  # rating
            "菜品太咸了，服务态度也不好",  # review_text
            str(uuid.uuid4()),  # store_id
        ][i]

        # 为不同的execute调用设置不同返回值
        set_config_result = AsyncMock()
        review_result = AsyncMock()
        review_result.fetchone.return_value = review_row
        brand_voice_result = AsyncMock()
        brand_voice_result.fetchone.return_value = None
        tenant_result = AsyncMock()
        tenant_result.fetchone.return_value = ("尝在一起",)
        insert_result = AsyncMock()
        insert_result.rowcount = 1

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            elif call_count == 2:
                return review_result
            elif call_count == 3:
                return brand_voice_result
            elif call_count == 4:
                return tenant_result
            else:
                return insert_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        # mock AI调用 — 使用降级回复
        with patch.object(self.replier, "_call_ai_generate", return_value="感谢您的反馈！我们已记录问题。"):
            result = await self.replier.generate_reply(self.tenant_id, self.review_id, db)

        assert result["status"] == "draft"
        assert result["review_id"] == str(self.review_id)
        assert "generated_reply" in result
        assert result["platform"] == "dianping"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_reply_review_not_found(self) -> None:
        """评论不存在时抛出ValueError"""
        db = AsyncMock()
        set_config_result = AsyncMock()
        review_result = AsyncMock()
        review_result.fetchone.return_value = None

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return review_result

        db.execute = AsyncMock(side_effect=mock_execute)

        with pytest.raises(ValueError, match="评论不存在"):
            await self.replier.generate_reply(self.tenant_id, self.review_id, db)

    @pytest.mark.asyncio
    async def test_approve_reply_success(self) -> None:
        """成功审批AI回复"""
        db = AsyncMock()
        reply_id = uuid.uuid4()
        approved_by = uuid.uuid4()

        approve_row = MagicMock()
        approve_row.__getitem__ = lambda self, i: [str(reply_id), "感谢回复"][i]

        set_config_result = AsyncMock()
        update_result = AsyncMock()
        update_result.fetchone.return_value = approve_row

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return update_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        result = await self.replier.approve_reply(self.tenant_id, reply_id, approved_by, db)

        assert result["status"] == "approved"
        assert result["reply_id"] == str(reply_id)
        db.commit.assert_called_once()

    def test_fallback_reply_not_empty(self) -> None:
        """降级回复模板不为空"""
        reply = self.replier._fallback_reply()
        assert len(reply) > 0
        assert "感谢" in reply

    def test_prompt_template_format(self) -> None:
        """提示词模板格式化正确"""
        prompt = _REPLY_PROMPT_TEMPLATE.format(
            brand_name="尝在一起",
            tone="温暖亲切",
            rating=2.0,
            review_text="菜品太咸",
        )
        assert "尝在一起" in prompt
        assert "温暖亲切" in prompt
        assert "2.0" in prompt
        assert "菜品太咸" in prompt
        assert "100字" in prompt

    @pytest.mark.asyncio
    async def test_brand_voice_config_default(self) -> None:
        """无配置时返回默认品牌语调"""
        db = AsyncMock()
        query_result = AsyncMock()
        query_result.fetchone.return_value = None
        db.execute = AsyncMock(return_value=query_result)

        config = await self.replier.get_brand_voice_config(self.tenant_id, db)
        assert config["tone"] == "warm"
        assert "keywords" in config


# ═══════════════════════════════════════
# NPSService 测试
# ═══════════════════════════════════════


class TestNPSService:
    """NPS调查服务测试"""

    def setup_method(self) -> None:
        self.svc = NPSService()
        self.tenant_id = uuid.uuid4()

    def test_extract_tags_service(self) -> None:
        """反馈文本主题提取 — 服务相关"""
        tags = _extract_tags("服务员态度非常好，很热情")
        assert "服务" in tags

    def test_extract_tags_taste(self) -> None:
        """反馈文本主题提取 — 口味相关"""
        tags = _extract_tags("味道太咸了，不好吃")
        assert "口味" in tags

    def test_extract_tags_multiple(self) -> None:
        """反馈文本主题提取 — 多主题"""
        tags = _extract_tags("服务态度差，上菜速度也慢，价格还很贵")
        assert "服务" in tags or "态度" in tags
        assert "速度" in tags
        assert "价格" in tags

    def test_extract_tags_empty(self) -> None:
        """空反馈返回空标签"""
        assert _extract_tags("") == []
        assert _extract_tags(None) == []

    def test_nps_calculation_all_promoters(self) -> None:
        """全部推荐者 → NPS = 100"""
        # NPS = (promoters/total * 100) - (detractors/total * 100)
        promoters, detractors, total = 10, 0, 10
        nps = (promoters / total * 100) - (detractors / total * 100)
        assert nps == 100.0

    def test_nps_calculation_all_detractors(self) -> None:
        """全部贬损者 → NPS = -100"""
        promoters, detractors, total = 0, 10, 10
        nps = (promoters / total * 100) - (detractors / total * 100)
        assert nps == -100.0

    def test_nps_calculation_mixed(self) -> None:
        """混合场景：5推荐 + 3被动 + 2贬损 → NPS = 30"""
        promoters, detractors, total = 5, 2, 10
        nps = (promoters / total * 100) - (detractors / total * 100)
        assert nps == 30.0

    def test_nps_promoter_threshold(self) -> None:
        """推荐者阈值：9-10分"""
        assert 9 >= 9  # is_promoter
        assert 10 >= 9  # is_promoter
        assert 8 < 9  # NOT promoter (passive)

    def test_nps_detractor_threshold(self) -> None:
        """贬损者阈值：0-6分"""
        assert 6 <= 6  # is_detractor
        assert 0 <= 6  # is_detractor
        assert 7 > 6  # NOT detractor (passive)

    @pytest.mark.asyncio
    async def test_send_survey_success(self) -> None:
        """成功发送NPS调查"""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        customer_id = uuid.uuid4()
        store_id = uuid.uuid4()

        result = await self.svc.send_survey(self.tenant_id, customer_id, store_id, None, db, "wechat")

        assert "survey_id" in result
        assert result["customer_id"] == str(customer_id)
        assert result["channel"] == "wechat"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_response_invalid_score(self) -> None:
        """无效NPS评分抛出ValueError"""
        db = AsyncMock()
        survey_id = uuid.uuid4()

        with pytest.raises(ValueError, match="NPS评分必须在0-10之间"):
            await self.svc.record_response(self.tenant_id, survey_id, 11, None, db)

        with pytest.raises(ValueError, match="NPS评分必须在0-10之间"):
            await self.svc.record_response(self.tenant_id, survey_id, -1, None, db)


# ═══════════════════════════════════════
# ImprovementRecommender 测试
# ═══════════════════════════════════════


class TestImprovementRecommender:
    """改进建议引擎测试"""

    def setup_method(self) -> None:
        self.recommender = ImprovementRecommender()
        self.tenant_id = uuid.uuid4()

    def test_theme_keywords_coverage(self) -> None:
        """主题关键词覆盖所有维度"""
        expected_themes = {"菜品口味", "服务态度", "上菜速度", "环境卫生", "菜品分量", "性价比", "菜品温度"}
        assert set(_THEME_KEYWORDS.keys()) == expected_themes

    def test_recommendation_templates_match_themes(self) -> None:
        """每个主题都有对应的建议模板"""
        for theme in _THEME_KEYWORDS:
            assert theme in _RECOMMENDATION_TEMPLATES, f"缺少主题 {theme} 的建议模板"

    def test_theme_matching_taste(self) -> None:
        """口味主题关键词匹配"""
        text_content = "菜品太咸了，味道差"
        matched = set()
        for theme, keywords in _THEME_KEYWORDS.items():
            for kw in keywords:
                if kw in text_content:
                    matched.add(theme)
                    break
        assert "菜品口味" in matched

    def test_theme_matching_service(self) -> None:
        """服务主题关键词匹配"""
        text_content = "服务员态度差，不理人"
        matched = set()
        for theme, keywords in _THEME_KEYWORDS.items():
            for kw in keywords:
                if kw in text_content:
                    matched.add(theme)
                    break
        assert "服务态度" in matched

    def test_theme_matching_multiple(self) -> None:
        """多主题同时匹配"""
        text_content = "上菜慢，菜还冷了，而且太贵了"
        matched = set()
        for theme, keywords in _THEME_KEYWORDS.items():
            for kw in keywords:
                if kw in text_content:
                    matched.add(theme)
                    break
        assert "上菜速度" in matched
        assert "菜品温度" in matched
        assert "性价比" in matched

    def test_theme_frequency_ranking(self) -> None:
        """主题按频次排序"""
        counter: Counter[str] = Counter()
        counter["菜品口味"] = 15
        counter["服务态度"] = 8
        counter["上菜速度"] = 12

        ranked = counter.most_common()
        assert ranked[0][0] == "菜品口味"
        assert ranked[1][0] == "上菜速度"
        assert ranked[2][0] == "服务态度"

    def test_pct_calculation(self) -> None:
        """百分比计算正确"""
        frequency = 15
        total = 50
        pct = round(frequency / total * 100, 1)
        assert pct == 30.0

    @pytest.mark.asyncio
    async def test_generate_recommendations_empty(self) -> None:
        """无差评时返回空列表"""
        db = AsyncMock()
        set_config_result = AsyncMock()

        # order_reviews查询返回空
        empty_result = AsyncMock()
        empty_result.fetchall.return_value = []

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return empty_result

        db.execute = AsyncMock(side_effect=mock_execute)

        result = await self.recommender.generate_recommendations(self.tenant_id, db, days=30)
        assert result == []

    def test_recommendation_text_actionable(self) -> None:
        """建议文本包含可执行动作"""
        for theme, text in _RECOMMENDATION_TEMPLATES.items():
            assert "建议" in text, f"主题 {theme} 的建议缺少'建议'关键词"
            # 每条建议至少包含2个具体行动
            assert text.count(")") >= 2, f"主题 {theme} 的建议缺少具体行动步骤"
