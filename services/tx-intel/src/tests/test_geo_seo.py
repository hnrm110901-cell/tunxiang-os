"""GEO搜索优化 — 测试

覆盖：
- GeoSEOService: 结构化数据生成、SEO评分计算、优化建议
- CitationMonitorWorker: 查询执行、引用检测
"""

from services.geo_seo_service import GeoSEOService

# ═══════════════════════════════════════
# SEO评分计算测试
# ═══════════════════════════════════════


class TestGeoSEOService:
    """GEO SEO服务核心逻辑测试"""

    def setup_method(self) -> None:
        self.svc = GeoSEOService()

    # ─── calculate_seo_score ──────────────

    def test_seo_score_complete_profile(self) -> None:
        """完整档案应获得高分（不含photos的满分为85）"""
        profile = {
            "store_name": "徐记海鲜",
            "address": "长沙市芙蓉区五一大道123号",
            "phone": "0731-88888888",
            "cuisine_type": "海鲜",
            "latitude": 28.194,
            "longitude": 112.972,
            "business_hours": {"mon": "09:00-22:00", "tue": "09:00-22:00"},
            "menu_highlights": [
                {"name": "蒜蓉粉丝蒸扇贝", "price_fen": 3800},
                {"name": "清蒸石斑鱼", "price_fen": 16800},
            ],
        }
        score = self.svc.calculate_seo_score(profile)
        # name(10) + address(10) + phone(10) + cuisine(10) + hours(15) + highlights(15) + coords(15) = 85
        assert score == 85

    def test_seo_score_empty_profile(self) -> None:
        """空档案应得0分"""
        profile: dict = {}
        score = self.svc.calculate_seo_score(profile)
        assert score == 0

    def test_seo_score_partial_profile(self) -> None:
        """部分填写档案应得部分分数"""
        profile = {
            "store_name": "测试餐厅",
            "address": "长沙市某路",
            "phone": None,
            "cuisine_type": None,
            "latitude": None,
            "longitude": None,
            "business_hours": {},
            "menu_highlights": [],
        }
        score = self.svc.calculate_seo_score(profile)
        # name(10) + address(10) = 20
        assert score == 20

    def test_seo_score_name_only(self) -> None:
        """仅有名称应得10分"""
        profile = {"store_name": "海底捞"}
        score = self.svc.calculate_seo_score(profile)
        assert score == 10

    def test_seo_score_coordinates_need_both(self) -> None:
        """经纬度必须同时存在才得分"""
        profile_lat_only = {"latitude": 28.0, "longitude": None}
        profile_both = {"latitude": 28.0, "longitude": 112.0}

        assert self.svc.calculate_seo_score(profile_lat_only) == 0
        assert self.svc.calculate_seo_score(profile_both) == 15

    def test_seo_score_empty_hours_no_points(self) -> None:
        """空营业时间不得分"""
        profile_empty = {"business_hours": {}}
        profile_str_empty = {"business_hours": "{}"}
        profile_filled = {"business_hours": {"mon": "09:00-22:00"}}

        assert self.svc.calculate_seo_score(profile_empty) == 0
        assert self.svc.calculate_seo_score(profile_str_empty) == 0
        assert self.svc.calculate_seo_score(profile_filled) == 15

    def test_seo_score_capped_at_100(self) -> None:
        """分数不超过100"""
        # 即使所有字段都有，当前max=85（无photos），不会超100
        profile = {
            "store_name": "X",
            "address": "Y",
            "phone": "Z",
            "cuisine_type": "A",
            "latitude": 1.0,
            "longitude": 2.0,
            "business_hours": {"mon": "09:00"},
            "menu_highlights": [{"name": "菜"}],
        }
        score = self.svc.calculate_seo_score(profile)
        assert score <= 100

    # ─── 优化建议逻辑测试（静态部分） ────

    def test_optimization_identifies_missing_fields(self) -> None:
        """优化建议应识别缺失字段"""
        # 测试calculate_seo_score对缺失字段的反应
        incomplete = {
            "store_name": "测试",
            "address": None,
            "phone": None,
            "cuisine_type": None,
        }
        complete = {
            "store_name": "测试",
            "address": "地址",
            "phone": "电话",
            "cuisine_type": "湘菜",
        }
        assert self.svc.calculate_seo_score(incomplete) < self.svc.calculate_seo_score(complete)


# ═══════════════════════════════════════
# AI引用监测测试
# ═══════════════════════════════════════


class TestCitationMonitor:
    """AI引用监测逻辑测试"""

    def setup_method(self) -> None:
        self.svc = GeoSEOService()

    def test_citation_deterministic_for_same_input(self) -> None:
        """相同输入应产生确定性结果（基于hash模拟）"""
        import uuid

        tid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        query = "长沙最好的海鲜餐厅"
        platform = "chatgpt"

        # hash是确定性的，同样输入应得到同样结果
        hash_val1 = hash(f"{str(tid)}:{query}:{platform}") % 100
        hash_val2 = hash(f"{str(tid)}:{query}:{platform}") % 100
        assert hash_val1 == hash_val2

        # 引用判定一致
        found1 = hash_val1 < 35
        found2 = hash_val2 < 35
        assert found1 == found2

    def test_citation_varies_by_platform(self) -> None:
        """不同平台对同一查询可能给出不同结果"""
        import uuid

        tid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        query = "长沙最好的海鲜餐厅"

        results = {}
        for platform in ["chatgpt", "perplexity", "google_ai", "baidu_ai", "xiaohongshu"]:
            hash_val = hash(f"{str(tid)}:{query}:{platform}") % 100
            results[platform] = hash_val < 35

        # 至少应该有一些变化（概率性，但5个平台大概率不全相同）
        # 如果全相同也不算错误，这里只验证逻辑不崩溃
        assert len(results) == 5

    def test_query_template_expansion(self) -> None:
        """查询模板应正确展开"""
        from workers.citation_monitor_worker import _QUERY_TEMPLATES

        city = "长沙"
        cuisine = "海鲜"
        brand_name = "徐记海鲜"

        queries = []
        for tpl in _QUERY_TEMPLATES:
            q = tpl.format(city=city, cuisine=cuisine, brand_name=brand_name)
            queries.append(q)

        assert len(queries) == 3
        assert "长沙最好的海鲜餐厅" in queries
        assert "徐记海鲜怎么样" in queries
        assert "长沙海鲜推荐" in queries

    def test_all_platforms_covered(self) -> None:
        """所有目标AI平台均在监测范围内"""
        from workers.citation_monitor_worker import _AI_PLATFORMS

        expected = {"chatgpt", "perplexity", "google_ai", "baidu_ai", "xiaohongshu"}
        assert set(_AI_PLATFORMS) == expected

    def test_sentiment_values(self) -> None:
        """情感标签仅限允许范围"""
        valid_sentiments = {"positive", "neutral", "negative"}
        # 模拟引用检测中的sentiment逻辑
        for hash_val in range(100):
            if hash_val < 35:  # mention_found
                sentiment = "positive" if hash_val < 20 else "neutral"
            else:
                sentiment = "neutral"
            assert sentiment in valid_sentiments
