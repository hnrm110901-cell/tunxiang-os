"""
P3-04 菜品5因子动态排名引擎测试
测试：排名评分完整性 / 权重校验 / 四象限矩阵完整性
"""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ..api.dish_ranking_engine_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

STORE_ID = "store-test-001"


# ─── Test 1: 获取排名，验证5因子评分完整性 ────────────────────────────────────

class TestRankingReturnScores:
    """test_ranking_returns_scores — 每道菜含5因子scores，composite_score在0-1之间，rank从1开始递增"""

    def test_ranking_returns_200(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_each_dish_has_five_factor_scores(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}")
        items = resp.json()["data"]["items"]
        assert len(items) > 0

        required_factors = {"volume", "margin", "reorder", "satisfaction", "trend"}
        for dish in items:
            assert "scores" in dish, f"菜品 {dish.get('dish_name')} 缺少 scores 字段"
            assert required_factors == set(dish["scores"].keys()), \
                f"菜品 {dish.get('dish_name')} 因子不完整: {dish['scores'].keys()}"

    def test_composite_score_between_0_and_1(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}")
        items = resp.json()["data"]["items"]
        for dish in items:
            score = dish["composite_score"]
            assert 0.0 <= score <= 1.0, \
                f"菜品 {dish['dish_name']} 综合分 {score} 超出 [0, 1] 范围"

    def test_individual_factor_scores_in_range(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}")
        items = resp.json()["data"]["items"]
        for dish in items:
            for factor, val in dish["scores"].items():
                assert 0.0 <= val <= 1.0, \
                    f"菜品 {dish['dish_name']} 因子 {factor} 得分 {val} 超出范围"

    def test_rank_starts_from_1_and_increments(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}")
        items = resp.json()["data"]["items"]
        ranks = [d["rank"] for d in items]
        assert ranks[0] == 1, f"第一名应为1，实际为 {ranks[0]}"
        for i in range(len(ranks) - 1):
            assert ranks[i] < ranks[i + 1], \
                f"排名必须递增，第{i+1}名={ranks[i]}，第{i+2}名={ranks[i+1]}"

    def test_rank_change_field_exists(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}")
        items = resp.json()["data"]["items"]
        for dish in items:
            assert "rank_change" in dish, f"菜品 {dish['dish_name']} 缺少 rank_change 字段"
            assert isinstance(dish["rank_change"], int)

    def test_recommendation_tag_exists(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}")
        items = resp.json()["data"]["items"]
        valid_tags = {"明星菜品", "现金牛", "问题菜品", "瘦狗", "潜力菜品"}
        for dish in items:
            assert "recommendation_tag" in dish
            assert dish["recommendation_tag"] in valid_tags, \
                f"菜品 {dish['dish_name']} 标签 {dish['recommendation_tag']} 不在允许集合中"

    def test_limit_parameter_works(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}&limit=5")
        items = resp.json()["data"]["items"]
        assert len(items) <= 5

    def test_weights_applied_in_response(self):
        resp = client.get(f"/api/v1/menu/ranking/dishes?store_id={STORE_ID}")
        data = resp.json()["data"]
        assert "weights_applied" in data
        weights = data["weights_applied"]
        required_keys = {"volume", "margin", "reorder", "satisfaction", "trend"}
        assert set(weights.keys()) == required_keys


# ─── Test 2: 权重更新校验 ─────────────────────────────────────────────────────

class TestWeightUpdateValidation:
    """test_weight_update_validation — 5因子和=1.00时OK，和≠1.00时400"""

    def test_valid_weights_returns_200(self):
        payload = {
            "volume": 0.30,
            "margin": 0.30,
            "reorder": 0.20,
            "satisfaction": 0.10,
            "trend": 0.10,
        }
        resp = client.put("/api/v1/menu/ranking/weights", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total"] == pytest.approx(1.0, abs=0.001)

    def test_weight_sum_not_1_returns_400(self):
        payload = {
            "volume": 0.30,
            "margin": 0.30,
            "reorder": 0.20,
            "satisfaction": 0.15,
            "trend": 0.15,  # 和 = 1.10 ≠ 1.0
        }
        resp = client.put("/api/v1/menu/ranking/weights", json=payload)
        assert resp.status_code == 400
        assert "1.0" in resp.json()["detail"]

    def test_weight_sum_less_than_1_returns_400(self):
        payload = {
            "volume": 0.20,
            "margin": 0.20,
            "reorder": 0.10,
            "satisfaction": 0.10,
            "trend": 0.10,  # 和 = 0.70 < 1.0
        }
        resp = client.put("/api/v1/menu/ranking/weights", json=payload)
        assert resp.status_code == 400

    def test_weight_factor_out_of_range_returns_422(self):
        payload = {
            "volume": 1.5,  # 超出 [0, 1]
            "margin": 0.30,
            "reorder": 0.20,
            "satisfaction": 0.10,
            "trend": 0.10,
        }
        resp = client.put("/api/v1/menu/ranking/weights", json=payload)
        assert resp.status_code == 422

    def test_get_weights_returns_current_config(self):
        resp = client.get("/api/v1/menu/ranking/weights")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "weights" in data
        assert "total" in data
        total = data["total"]
        assert abs(total - 1.0) < 0.01

    def test_calibrate_seafood_brand(self):
        payload = {"brand_type": "seafood", "period_days": 30}
        resp = client.post("/api/v1/menu/ranking/weights/calibrate", json=payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "recommended_weights" in data
        weights = data["recommended_weights"]
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.001

    def test_calibrate_invalid_brand_type_returns_400(self):
        payload = {"brand_type": "invalid_brand", "period_days": 30}
        resp = client.post("/api/v1/menu/ranking/weights/calibrate", json=payload)
        assert resp.status_code == 400


# ─── Test 3: 四象限矩阵完整性 ────────────────────────────────────────────────

class TestMatrixQuadrantCoverage:
    """test_matrix_quadrant_coverage — 返回4个象限key，各象限含dishes列表"""

    def test_matrix_returns_4_quadrants(self):
        resp = client.get(f"/api/v1/menu/ranking/matrix?store_id={STORE_ID}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        required_keys = {"star", "cash_cow", "question", "dog"}
        assert required_keys == set(data.keys()), \
            f"四象限key不完整，实际: {set(data.keys())}"

    def test_each_quadrant_has_dishes_list(self):
        resp = client.get(f"/api/v1/menu/ranking/matrix?store_id={STORE_ID}")
        data = resp.json()["data"]
        for key, quadrant in data.items():
            assert "dishes" in quadrant, f"象限 {key} 缺少 dishes 字段"
            assert isinstance(quadrant["dishes"], list), f"象限 {key} 的 dishes 不是列表"

    def test_each_quadrant_has_label_and_advice(self):
        resp = client.get(f"/api/v1/menu/ranking/matrix?store_id={STORE_ID}")
        data = resp.json()["data"]
        for key, quadrant in data.items():
            assert "label" in quadrant, f"象限 {key} 缺少 label 字段"
            assert "advice" in quadrant, f"象限 {key} 缺少 advice 字段"
            assert len(quadrant["label"]) > 0
            assert len(quadrant["advice"]) > 0

    def test_each_quadrant_has_count(self):
        resp = client.get(f"/api/v1/menu/ranking/matrix?store_id={STORE_ID}")
        data = resp.json()["data"]
        for key, quadrant in data.items():
            assert "count" in quadrant
            assert quadrant["count"] == len(quadrant["dishes"])

    def test_all_dishes_appear_in_exactly_one_quadrant(self):
        resp = client.get(f"/api/v1/menu/ranking/matrix?store_id={STORE_ID}")
        data = resp.json()["data"]
        all_dish_names = []
        for quadrant in data.values():
            all_dish_names.extend([d["dish_name"] for d in quadrant["dishes"]])
        # 每道菜只能属于一个象限
        assert len(all_dish_names) == len(set(all_dish_names)), \
            "存在菜品跨象限出现"

    def test_health_report_returns_all_sections(self):
        resp = client.get(f"/api/v1/menu/ranking/health-report?store_id={STORE_ID}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "attention_needed" in data
        assert "worth_promoting" in data
        assert "price_depression" in data
        assert "summary" in data

    def test_health_report_attention_needed_low_scores(self):
        """需要关注的菜品综合分应 < 0.30"""
        resp = client.get(f"/api/v1/menu/ranking/health-report?store_id={STORE_ID}")
        items = resp.json()["data"]["attention_needed"]
        for item in items:
            assert item["composite_score"] < 0.30, \
                f"菜品 {item['dish_name']} 综合分 {item['composite_score']} 不应进入关注列表（应 < 0.30）"

    def test_trends_endpoint_returns_series(self):
        resp = client.get("/api/v1/menu/ranking/trends?dish_id=dish-001&days=7")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "trend_series" in data
        assert len(data["trend_series"]) == 7

    def test_trends_unknown_dish_returns_404(self):
        resp = client.get("/api/v1/menu/ranking/trends?dish_id=dish-nonexistent&days=7")
        assert resp.status_code == 404
