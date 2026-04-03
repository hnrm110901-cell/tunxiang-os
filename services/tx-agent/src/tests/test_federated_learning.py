"""联邦学习服务测试

覆盖范围：
- 模型注册与列表
- 训练轮次生命周期 (创建 → 加入 → 提交 → 聚合)
- 差分隐私噪声添加与预算追踪
- FedAvg 聚合正确性
- 模型分发与版本管理
- 性能追踪与对比
- 隐私合规检查
- 多门店联合训练模拟
"""
import math
import os
import sys

import pytest

# 确保 src/services 可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))

from federated_learning import FEDERATED_MODELS, FederatedLearningService

# ─── Fixtures ───


@pytest.fixture
def service() -> FederatedLearningService:
    return FederatedLearningService()


@pytest.fixture
def registered_service(service: FederatedLearningService) -> FederatedLearningService:
    """已注册 discount_anomaly 模型的服务"""
    service.register_model(
        model_id="test_discount",
        model_type="discount_anomaly",
        description="测试折扣异常检测",
        input_schema=["discount_rate", "order_amount", "time_of_day",
                      "waiter_id", "table_type", "payment_method"],
        output_schema="anomaly_score (0-1)",
    )
    return service


@pytest.fixture
def training_service(registered_service: FederatedLearningService) -> tuple:
    """已创建训练轮次且有3家门店加入的服务，返回 (service, round_id)"""
    svc = registered_service
    result = svc.create_training_round(
        model_id="test_discount",
        min_participants=3,
        max_rounds=5,
        target_metric="accuracy",
        target_value=0.90,
    )
    round_id = result["round"]["round_id"]

    for i, store_id in enumerate(["store_a", "store_b", "store_c"]):
        svc.join_training_round(round_id, store_id, local_sample_count=100 + i * 50)

    return svc, round_id


# ─── 1. 模型注册与列表 ───


class TestModelRegistry:
    def test_register_model(self, service: FederatedLearningService):
        result = service.register_model(
            model_id="m1",
            model_type="discount_anomaly",
            description="折扣异常检测",
            input_schema=["discount_rate", "order_amount"],
            output_schema="anomaly_score",
        )
        assert result["ok"] is True
        assert result["model"]["model_id"] == "m1"
        assert result["model"]["model_type"] == "discount_anomaly"
        assert result["model"]["version"] == "1.0.0"
        assert result["model"]["default_epsilon"] == 1.0

    def test_register_duplicate_model(self, registered_service: FederatedLearningService):
        result = registered_service.register_model(
            model_id="test_discount",
            model_type="discount_anomaly",
            description="重复注册",
            input_schema=[],
            output_schema="",
        )
        assert result["ok"] is False
        assert "已注册" in result["error"]

    def test_list_models(self, service: FederatedLearningService):
        service.register_model("m1", "discount_anomaly", "模型1", ["f1"], "out1")
        service.register_model("m2", "traffic_forecast", "模型2", ["f2"], "out2")
        models = service.list_models()
        assert len(models) == 2
        ids = {m["model_id"] for m in models}
        assert ids == {"m1", "m2"}

    def test_get_model_info(self, registered_service: FederatedLearningService):
        result = registered_service.get_model_info("test_discount")
        assert result["ok"] is True
        assert result["model"]["model_type"] == "discount_anomaly"

    def test_get_model_info_not_found(self, service: FederatedLearningService):
        result = service.get_model_info("nonexistent")
        assert result["ok"] is False

    def test_model_initial_weights(self, registered_service: FederatedLearningService):
        gm = registered_service.get_global_model("test_discount")
        assert gm["ok"] is True
        assert len(gm["weights"]) > 0
        assert gm["version"] == "1.0.0"

    def test_all_model_types_have_default_epsilon(self):
        for model_type, config in FEDERATED_MODELS.items():
            assert "default_epsilon" in config, f"{model_type} 缺少 default_epsilon"
            assert config["default_epsilon"] > 0

    def test_register_custom_model_type(self, service: FederatedLearningService):
        result = service.register_model(
            model_id="custom_model",
            model_type="custom_type_not_in_registry",
            description="自定义模型",
            input_schema=["x1", "x2"],
            output_schema="y",
        )
        assert result["ok"] is True
        # 非预定义类型使用默认 epsilon=1.0
        assert result["model"]["default_epsilon"] == 1.0


# ─── 2. 训练轮次生命周期 ───


class TestTrainingRoundLifecycle:
    def test_create_training_round(self, registered_service: FederatedLearningService):
        result = registered_service.create_training_round(
            model_id="test_discount",
            min_participants=3,
        )
        assert result["ok"] is True
        r = result["round"]
        assert r["status"] == "waiting_for_participants"
        assert r["min_participants"] == 3
        assert r["current_round"] == 0

    def test_create_round_nonexistent_model(self, service: FederatedLearningService):
        result = service.create_training_round(model_id="nonexistent")
        assert result["ok"] is False

    def test_join_training_round(self, registered_service: FederatedLearningService):
        svc = registered_service
        round_result = svc.create_training_round("test_discount", min_participants=2)
        round_id = round_result["round"]["round_id"]

        j1 = svc.join_training_round(round_id, "store_1", 100)
        assert j1["ok"] is True
        assert j1["status"] == "waiting_for_participants"

        j2 = svc.join_training_round(round_id, "store_2", 200)
        assert j2["ok"] is True
        assert j2["status"] == "training"  # 达到最小参与者数

    def test_join_nonexistent_round(self, service: FederatedLearningService):
        result = service.join_training_round("fake_round", "store_1", 100)
        assert result["ok"] is False

    def test_join_duplicate_store(self, registered_service: FederatedLearningService):
        svc = registered_service
        r = svc.create_training_round("test_discount", min_participants=3)
        round_id = r["round"]["round_id"]

        svc.join_training_round(round_id, "store_1", 100)
        dup = svc.join_training_round(round_id, "store_1", 200)
        assert dup["ok"] is False
        assert "已加入" in dup["error"]

    def test_auto_start_training(self, registered_service: FederatedLearningService):
        svc = registered_service
        r = svc.create_training_round("test_discount", min_participants=2)
        round_id = r["round"]["round_id"]

        svc.join_training_round(round_id, "s1", 50)
        status = svc.get_round_status(round_id)
        assert status["round"]["status"] == "waiting_for_participants"

        svc.join_training_round(round_id, "s2", 60)
        status = svc.get_round_status(round_id)
        assert status["round"]["status"] == "training"
        assert status["round"]["current_round"] == 1

    def test_get_round_status(self, training_service: tuple):
        svc, round_id = training_service
        status = svc.get_round_status(round_id)
        assert status["ok"] is True
        assert status["round"]["participant_count"] == 3
        assert status["round"]["status"] == "training"

    def test_get_round_status_not_found(self, service: FederatedLearningService):
        result = service.get_round_status("nonexistent")
        assert result["ok"] is False

    def test_participating_stores_tracked(self, training_service: tuple):
        svc, _ = training_service
        model_info = svc.get_model_info("test_discount")
        stores = model_info["model"]["participating_stores"]
        assert set(stores) == {"store_a", "store_b", "store_c"}


# ─── 3. 梯度聚合 ───


class TestGradientAggregation:
    def test_submit_local_update(self, training_service: tuple):
        svc, round_id = training_service
        weight_count = svc._global_models["test_discount"]["weight_count"]
        weights = [0.1] * weight_count

        result = svc.submit_local_update(
            round_id=round_id,
            store_id="store_a",
            model_weights=weights,
            metrics={"accuracy": 0.85, "loss": 0.2},
            sample_count=100,
        )
        assert result["ok"] is True
        assert result["epsilon_used"] == 1.0
        assert result["updates_received"] == 1

    def test_submit_wrong_dimension(self, training_service: tuple):
        svc, round_id = training_service
        result = svc.submit_local_update(
            round_id=round_id,
            store_id="store_a",
            model_weights=[0.1, 0.2, 0.3],  # 维度不匹配
            metrics={},
            sample_count=10,
        )
        assert result["ok"] is False
        assert "维度不匹配" in result["error"]

    def test_submit_to_nonexistent_round(self, service: FederatedLearningService):
        result = service.submit_local_update(
            "fake_round", "store_a", [0.1], {}, 10
        )
        assert result["ok"] is False

    def test_submit_by_non_participant(self, training_service: tuple):
        svc, round_id = training_service
        weight_count = svc._global_models["test_discount"]["weight_count"]
        result = svc.submit_local_update(
            round_id=round_id,
            store_id="store_outsider",
            model_weights=[0.1] * weight_count,
            metrics={},
            sample_count=10,
        )
        assert result["ok"] is False
        assert "未加入" in result["error"]

    def test_fedavg_aggregation(self, training_service: tuple):
        svc, round_id = training_service
        weight_count = svc._global_models["test_discount"]["weight_count"]

        # Store A: 100 samples, weights all 1.0
        # Store B: 150 samples, weights all 2.0
        # Store C: 200 samples, weights all 3.0
        # FedAvg: (100*1.0 + 150*2.0 + 200*3.0) / 450 = 1000/450 ≈ 2.222
        # (但实际值会因差分隐私噪声偏离)
        svc.submit_local_update(
            round_id, "store_a",
            [1.0] * weight_count,
            {"accuracy": 0.80}, 100,
        )
        svc.submit_local_update(
            round_id, "store_b",
            [2.0] * weight_count,
            {"accuracy": 0.85}, 150,
        )
        svc.submit_local_update(
            round_id, "store_c",
            [3.0] * weight_count,
            {"accuracy": 0.90}, 200,
        )

        result = svc.aggregate_updates(round_id)
        assert result["ok"] is True
        assert result["new_version"] == "1.0.1"

        # 聚合后指标应是加权平均
        # accuracy: (100*0.80 + 150*0.85 + 200*0.90) / 450 = 387.5/450 ≈ 0.861
        expected_acc = (100 * 0.80 + 150 * 0.85 + 200 * 0.90) / 450
        assert abs(result["round_metrics"]["accuracy"] - expected_acc) < 0.01

        # 权重因为有差分隐私噪声，不是精确 2.222，但应在合理范围内
        weights = result["global_model_weights"]
        avg_weight = sum(weights) / len(weights)
        # 期望值约 2.222，允许较大偏差（噪声影响）
        assert 0.0 < avg_weight < 5.0  # 宽松检查

    def test_aggregate_empty_updates(self, training_service: tuple):
        svc, round_id = training_service
        # 不提交任何更新就聚合
        result = svc.aggregate_updates(round_id)
        assert result["ok"] is False
        assert "没有收到" in result["error"]

    def test_aggregate_nonexistent_round(self, service: FederatedLearningService):
        result = service.aggregate_updates("fake_round")
        assert result["ok"] is False

    def test_version_increments_on_aggregation(self, training_service: tuple):
        svc, round_id = training_service
        weight_count = svc._global_models["test_discount"]["weight_count"]

        for store in ["store_a", "store_b", "store_c"]:
            svc.submit_local_update(
                round_id, store,
                [0.5] * weight_count,
                {"accuracy": 0.80}, 100,
            )

        result = svc.aggregate_updates(round_id)
        assert result["new_version"] == "1.0.1"

        # 状态应恢复为 training（未达到目标）
        assert result["status"] == "training"

    def test_round_completes_on_target_reached(self, registered_service: FederatedLearningService):
        svc = registered_service
        r = svc.create_training_round(
            "test_discount", min_participants=2, target_metric="accuracy", target_value=0.80
        )
        round_id = r["round"]["round_id"]
        svc.join_training_round(round_id, "s1", 100)
        svc.join_training_round(round_id, "s2", 100)

        weight_count = svc._global_models["test_discount"]["weight_count"]
        svc.submit_local_update(round_id, "s1", [0.5] * weight_count, {"accuracy": 0.85}, 100)
        svc.submit_local_update(round_id, "s2", [0.6] * weight_count, {"accuracy": 0.90}, 100)

        result = svc.aggregate_updates(round_id)
        assert result["ok"] is True
        assert result["target_reached"] is True
        assert result["status"] == "completed"

    def test_round_completes_on_max_rounds(self, registered_service: FederatedLearningService):
        svc = registered_service
        r = svc.create_training_round(
            "test_discount", min_participants=2, max_rounds=1,
            target_metric="accuracy", target_value=0.99,  # 不可能达到
        )
        round_id = r["round"]["round_id"]
        svc.join_training_round(round_id, "s1", 50)
        svc.join_training_round(round_id, "s2", 50)

        weight_count = svc._global_models["test_discount"]["weight_count"]
        svc.submit_local_update(round_id, "s1", [0.1] * weight_count, {"accuracy": 0.5}, 50)
        svc.submit_local_update(round_id, "s2", [0.2] * weight_count, {"accuracy": 0.6}, 50)

        result = svc.aggregate_updates(round_id)
        assert result["status"] == "completed"
        assert result["target_reached"] is False

    def test_get_global_model(self, registered_service: FederatedLearningService):
        result = registered_service.get_global_model("test_discount")
        assert result["ok"] is True
        assert result["version"] == "1.0.0"
        assert len(result["weights"]) == result["weight_count"]

    def test_get_global_model_not_found(self, service: FederatedLearningService):
        result = service.get_global_model("nonexistent")
        assert result["ok"] is False


# ─── 4. 差分隐私 ───


class TestDifferentialPrivacy:
    def test_add_noise(self, service: FederatedLearningService):
        gradients = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = service.add_noise(gradients, epsilon=1.0, delta=1e-5)

        assert len(result["noised_gradients"]) == 5
        assert result["epsilon"] == 1.0
        assert result["delta"] == 1e-5
        assert result["noise_scale"] > 0
        assert result["gradient_count"] == 5

        # 噪声后的值应该和原始值不完全相同
        noised = result["noised_gradients"]
        diffs = [abs(noised[i] - gradients[i]) for i in range(5)]
        assert sum(diffs) > 0  # 至少有一些噪声

    def test_noise_scale_increases_with_lower_epsilon(
        self, service: FederatedLearningService
    ):
        gradients = [1.0] * 10
        r1 = service.add_noise(gradients, epsilon=2.0)
        r2 = service.add_noise(gradients, epsilon=0.5)
        # 更小的 epsilon 意味着更强的隐私（更大的噪声标准差）
        assert r2["noise_scale"] > r1["noise_scale"]

    def test_gaussian_mechanism_formula(self, service: FederatedLearningService):
        epsilon = 1.0
        delta = 1e-5
        sensitivity = 1.0
        expected_scale = sensitivity * math.sqrt(2.0 * math.log(1.25 / delta)) / epsilon

        result = service.add_noise([0.0], epsilon=epsilon, delta=delta)
        assert abs(result["noise_scale"] - expected_scale) < 1e-4

    def test_compute_privacy_budget(self, training_service: tuple):
        svc, round_id = training_service
        weight_count = svc._global_models["test_discount"]["weight_count"]

        # 提交一次，消耗 epsilon=1.0
        svc.submit_local_update(
            round_id, "store_a",
            [0.5] * weight_count,
            {"accuracy": 0.8}, 100,
        )

        budget = svc.compute_privacy_budget("test_discount", "store_a")
        assert budget["epsilon_spent"] == 1.0
        assert budget["epsilon_remaining"] == 9.0
        assert budget["max_budget"] == 10.0

    def test_privacy_budget_accumulates(self, registered_service: FederatedLearningService):
        svc = registered_service
        weight_count = svc._global_models["test_discount"]["weight_count"]

        # 创建多个轮次并提交
        for i in range(3):
            r = svc.create_training_round("test_discount", min_participants=1)
            round_id = r["round"]["round_id"]
            svc.join_training_round(round_id, "store_x", 100)
            svc.submit_local_update(
                round_id, "store_x",
                [0.5] * weight_count,
                {"accuracy": 0.8}, 100,
            )

        budget = svc.compute_privacy_budget("test_discount", "store_x")
        assert budget["epsilon_spent"] == 3.0  # 3 轮 × epsilon=1.0

    def test_check_privacy_compliance_ok(self, service: FederatedLearningService):
        result = service.check_privacy_compliance("fresh_store")
        assert result["compliant"] is True
        assert result["total_epsilon_spent"] == 0.0
        assert len(result["violations"]) == 0

    def test_check_privacy_compliance_exceeded(
        self, registered_service: FederatedLearningService
    ):
        svc = registered_service
        # 直接设置已消耗预算超过上限
        svc._privacy_budgets[("test_discount", "store_exhaust")] = 10.0

        result = svc.check_privacy_compliance("store_exhaust")
        assert result["compliant"] is False
        assert len(result["violations"]) > 0

    def test_submit_blocked_when_budget_exhausted(
        self, registered_service: FederatedLearningService
    ):
        svc = registered_service
        weight_count = svc._global_models["test_discount"]["weight_count"]

        # 耗尽预算
        svc._privacy_budgets[("test_discount", "store_broke")] = 10.0

        r = svc.create_training_round("test_discount", min_participants=1)
        round_id = r["round"]["round_id"]
        svc.join_training_round(round_id, "store_broke", 100)

        result = svc.submit_local_update(
            round_id, "store_broke",
            [0.5] * weight_count, {"accuracy": 0.8}, 100,
        )
        assert result["ok"] is False
        assert "隐私预算" in result["error"]


# ─── 5. 模型分发 ───


class TestModelDistribution:
    def test_distribute_model(self, training_service: tuple):
        svc, _ = training_service
        result = svc.distribute_model("test_discount")
        assert result["ok"] is True
        assert result["store_count"] == 3
        assert set(result["distributed_to"]) == {"store_a", "store_b", "store_c"}

    def test_distribute_to_specific_stores(self, training_service: tuple):
        svc, _ = training_service
        result = svc.distribute_model("test_discount", target_stores=["store_a"])
        assert result["ok"] is True
        assert result["store_count"] == 1
        assert result["distributed_to"] == ["store_a"]

    def test_distribute_nonexistent_model(self, service: FederatedLearningService):
        result = service.distribute_model("nonexistent")
        assert result["ok"] is False

    def test_distribute_no_target_stores(self, registered_service: FederatedLearningService):
        # 没有任何门店参与过
        result = registered_service.distribute_model("test_discount")
        assert result["ok"] is False
        assert "没有目标门店" in result["error"]

    def test_get_store_model_version(self, training_service: tuple):
        svc, _ = training_service
        svc.distribute_model("test_discount", target_stores=["store_a"])

        result = svc.get_store_model_version("store_a", "test_discount")
        assert result["ok"] is True
        assert result["installed_version"] == "1.0.0"
        assert result["is_latest"] is True

    def test_get_store_model_version_not_installed(
        self, service: FederatedLearningService
    ):
        result = service.get_store_model_version("unknown_store", "unknown_model")
        assert result["ok"] is False

    def test_version_stale_after_aggregation(self, training_service: tuple):
        svc, round_id = training_service
        weight_count = svc._global_models["test_discount"]["weight_count"]

        # 先分发 1.0.0 到 store_a
        svc.distribute_model("test_discount", target_stores=["store_a"])

        # 然后做一轮聚合，版本变成 1.0.1
        for store in ["store_a", "store_b", "store_c"]:
            svc.submit_local_update(
                round_id, store, [0.5] * weight_count, {"accuracy": 0.8}, 100
            )
        svc.aggregate_updates(round_id)

        # store_a 的版本应该过时了
        result = svc.get_store_model_version("store_a", "test_discount")
        assert result["is_latest"] is False
        assert result["installed_version"] == "1.0.0"
        assert result["global_version"] == "1.0.1"

    def test_rollback_model(self, registered_service: FederatedLearningService):
        svc = registered_service
        result = svc.rollback_model("test_discount", "0.9.0")
        assert result["ok"] is True
        assert result["from_version"] == "1.0.0"
        assert result["to_version"] == "0.9.0"

        # 确认版本已回滚
        gm = svc.get_global_model("test_discount")
        assert gm["version"] == "0.9.0"

    def test_rollback_nonexistent_model(self, service: FederatedLearningService):
        result = service.rollback_model("nonexistent", "1.0.0")
        assert result["ok"] is False


# ─── 6. 性能追踪 ───


class TestPerformanceTracking:
    def test_report_local_performance(self, service: FederatedLearningService):
        result = service.report_local_performance(
            "store_1", "model_1",
            {"accuracy": 0.88, "loss": 0.15},
        )
        assert result["ok"] is True
        assert result["total_reports"] == 1

    def test_multiple_reports(self, service: FederatedLearningService):
        service.report_local_performance("s1", "m1", {"accuracy": 0.80})
        service.report_local_performance("s1", "m1", {"accuracy": 0.85})
        result = service.report_local_performance("s1", "m1", {"accuracy": 0.90})
        assert result["total_reports"] == 3

    def test_get_federated_performance(self, service: FederatedLearningService):
        service.report_local_performance("s1", "m1", {"accuracy": 0.80, "loss": 0.3})
        service.report_local_performance("s2", "m1", {"accuracy": 0.90, "loss": 0.1})

        result = service.get_federated_performance("m1")
        assert result["ok"] is True
        assert result["store_count"] == 2
        # 平均 accuracy = 0.85
        assert abs(result["aggregated_metrics"]["accuracy"] - 0.85) < 0.01
        # 平均 loss = 0.2
        assert abs(result["aggregated_metrics"]["loss"] - 0.2) < 0.01

    def test_get_federated_performance_no_reports(
        self, service: FederatedLearningService
    ):
        result = service.get_federated_performance("nonexistent")
        assert result["ok"] is False

    def test_compare_local_vs_global(self, service: FederatedLearningService):
        # 第一次报告（本地训练初期）
        service.report_local_performance("s1", "m1", {"accuracy": 0.70, "loss": 0.5})
        # 第二次报告（联邦训练后）
        service.report_local_performance("s1", "m1", {"accuracy": 0.88, "loss": 0.15})

        result = service.compare_local_vs_global("s1", "m1")
        assert result["ok"] is True
        assert result["federated_better"] is True
        assert result["comparison"]["accuracy"]["delta"] > 0
        assert result["comparison"]["loss"]["delta"] < 0  # loss 降低

    def test_compare_needs_two_reports(self, service: FederatedLearningService):
        service.report_local_performance("s1", "m1", {"accuracy": 0.80})
        result = service.compare_local_vs_global("s1", "m1")
        assert result["ok"] is False
        assert result["reports_count"] == 1

    def test_compare_no_reports(self, service: FederatedLearningService):
        result = service.compare_local_vs_global("s1", "m1")
        assert result["ok"] is False
        assert result["reports_count"] == 0


# ─── 7. 多门店联合训练模拟 (端到端) ───


class TestMultiStoreSimulation:
    def test_full_federation_cycle(self, registered_service: FederatedLearningService):
        """完整联邦学习周期：注册 → 创建轮次 → 多店加入 → 训练提交 → 聚合 → 分发"""
        svc = registered_service
        model_id = "test_discount"
        weight_count = svc._global_models[model_id]["weight_count"]

        # 创建训练轮次
        round_result = svc.create_training_round(
            model_id, min_participants=3, max_rounds=3
        )
        round_id = round_result["round"]["round_id"]

        # 5家门店加入
        stores = {
            "store_hz_001": {"samples": 200, "quality": 0.8},
            "store_sh_002": {"samples": 350, "quality": 0.85},
            "store_bj_003": {"samples": 150, "quality": 0.75},
            "store_gz_004": {"samples": 280, "quality": 0.82},
            "store_cd_005": {"samples": 120, "quality": 0.78},
        }

        for store_id, info in stores.items():
            join_result = svc.join_training_round(
                round_id, store_id, info["samples"]
            )
            assert join_result["ok"] is True

        # 验证轮次已开始
        status = svc.get_round_status(round_id)
        assert status["round"]["status"] == "training"
        assert status["round"]["participant_count"] == 5

        # 每家门店提交本地更新
        for store_id, info in stores.items():
            # 模拟不同质量的权重
            base_weight = info["quality"]
            weights = [
                base_weight + (i * 0.01) for i in range(weight_count)
            ]
            svc.submit_local_update(
                round_id, store_id, weights,
                {"accuracy": info["quality"], "loss": 1.0 - info["quality"]},
                info["samples"],
            )

        # 聚合
        agg_result = svc.aggregate_updates(round_id)
        assert agg_result["ok"] is True
        assert agg_result["new_version"] == "1.0.1"
        assert "accuracy" in agg_result["round_metrics"]

        # 分发
        dist_result = svc.distribute_model(model_id)
        assert dist_result["ok"] is True
        assert dist_result["store_count"] == 5

        # 验证所有门店版本已更新
        for store_id in stores:
            ver = svc.get_store_model_version(store_id, model_id)
            assert ver["ok"] is True
            assert ver["installed_version"] == "1.0.1"
            assert ver["is_latest"] is True

    def test_multi_round_training(self, registered_service: FederatedLearningService):
        """多轮训练：验证跨轮次精度提升"""
        svc = registered_service
        model_id = "test_discount"
        weight_count = svc._global_models[model_id]["weight_count"]

        r = svc.create_training_round(
            model_id, min_participants=2, max_rounds=5,
            target_metric="accuracy", target_value=0.95,
        )
        round_id = r["round"]["round_id"]
        svc.join_training_round(round_id, "s1", 200)
        svc.join_training_round(round_id, "s2", 200)

        accuracies = []
        for round_num in range(3):
            # 模拟逐轮提升的精度
            acc1 = 0.70 + round_num * 0.05
            acc2 = 0.72 + round_num * 0.06

            svc.submit_local_update(
                round_id, "s1",
                [acc1] * weight_count, {"accuracy": acc1}, 200,
            )
            svc.submit_local_update(
                round_id, "s2",
                [acc2] * weight_count, {"accuracy": acc2}, 200,
            )

            agg = svc.aggregate_updates(round_id)
            assert agg["ok"] is True
            accuracies.append(agg["round_metrics"]["accuracy"])

            if agg["status"] == "completed":
                break

        # 验证精度逐轮提升
        for i in range(1, len(accuracies)):
            assert accuracies[i] > accuracies[i - 1]

    def test_privacy_budget_across_rounds(
        self, registered_service: FederatedLearningService
    ):
        """验证跨轮次隐私预算累积"""
        svc = registered_service
        model_id = "test_discount"
        weight_count = svc._global_models[model_id]["weight_count"]
        epsilon = svc._models[model_id]["default_epsilon"]  # 1.0

        total_rounds = 5
        for i in range(total_rounds):
            r = svc.create_training_round(model_id, min_participants=1)
            rid = r["round"]["round_id"]
            svc.join_training_round(rid, "store_privacy", 100)
            svc.submit_local_update(
                rid, "store_privacy",
                [0.5] * weight_count, {"accuracy": 0.8}, 100,
            )
            svc.aggregate_updates(rid)

        budget = svc.compute_privacy_budget(model_id, "store_privacy")
        assert budget["epsilon_spent"] == epsilon * total_rounds
        assert budget["epsilon_remaining"] == svc._max_privacy_budget - (epsilon * total_rounds)

    def test_heterogeneous_sample_counts(
        self, registered_service: FederatedLearningService
    ):
        """验证不同样本量下 FedAvg 加权正确性"""
        svc = registered_service
        model_id = "test_discount"
        weight_count = svc._global_models[model_id]["weight_count"]

        r = svc.create_training_round(model_id, min_participants=2)
        rid = r["round"]["round_id"]

        # 大店 1000 样本，小店 10 样本
        svc.join_training_round(rid, "big_store", 1000)
        svc.join_training_round(rid, "small_store", 10)

        svc.submit_local_update(
            rid, "big_store",
            [1.0] * weight_count, {"accuracy": 0.90}, 1000,
        )
        svc.submit_local_update(
            rid, "small_store",
            [5.0] * weight_count, {"accuracy": 0.60}, 10,
        )

        agg = svc.aggregate_updates(rid)
        # 聚合精度应接近大店（因为样本数权重大得多）
        # (1000*0.90 + 10*0.60) / 1010 ≈ 0.897
        expected = (1000 * 0.90 + 10 * 0.60) / 1010
        assert abs(agg["round_metrics"]["accuracy"] - expected) < 0.01
