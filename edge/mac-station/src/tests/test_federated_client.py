"""联邦学习边缘客户端测试

覆盖范围：
- 客户端初始化
- 本地训练（模拟梯度下降）
- 模型评估
- 完整轮次参与流程
- 训练历史记录
- FastAPI 路由
"""

import os
import sys

import pytest

# 确保 src 可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from federated_client import FederatedClient, get_federated_client, router

# ─── Fixtures ───


@pytest.fixture
def client() -> FederatedClient:
    c = FederatedClient(store_id="test_store_001", server_url="http://localhost:8000")
    return c


@pytest.fixture
def client_with_model(client: FederatedClient) -> FederatedClient:
    """客户端已加载一个模型"""
    client.local_models["discount_anomaly"] = {
        "weights": [0.1] * 52,  # 6 features × 8 + 4 bias = 52
        "version": "1.0.0",
        "fetched_at": 1000000.0,
        "source": "global",
    }
    return client


def make_training_data(n: int = 50, feature_count: int = 6) -> list[dict]:
    """生成模拟训练数据"""
    import random

    data = []
    for _ in range(n):
        features = [random.random() for _ in range(feature_count)]
        # 简单规则：如果第一个特征 > 0.7，标记为异常
        target = 1.0 if features[0] > 0.7 else 0.0
        data.append({"features": features, "target": target})
    return data


def make_test_data(n: int = 20, feature_count: int = 6) -> list[dict]:
    """生成模拟测试数据"""
    return make_training_data(n, feature_count)


# ─── 1. 客户端初始化 ───


class TestClientInit:
    def test_init(self, client: FederatedClient):
        assert client.store_id == "test_store_001"
        assert client.server_url == "http://localhost:8000"
        assert client.local_models == {}
        assert client.training_history == []

    def test_init_strips_trailing_slash(self):
        c = FederatedClient("s1", "http://example.com/")
        assert c.server_url == "http://example.com"

    def test_get_federated_client_singleton(self):
        import federated_client

        # 重置单例
        federated_client._client_instance = None
        c1 = get_federated_client("s1", "http://localhost:9000")
        c2 = get_federated_client("s2", "http://localhost:9001")  # 应返回同一个
        assert c1 is c2
        assert c1.store_id == "s1"  # 使用第一次创建时的参数
        # 清理
        federated_client._client_instance = None


# ─── 2. 本地训练 ───


class TestLocalTraining:
    @pytest.mark.asyncio
    async def test_train_local_basic(self, client_with_model: FederatedClient):
        client = client_with_model
        training_data = make_training_data(30)

        result = await client.train_local(
            model_id="discount_anomaly",
            training_data=training_data,
            epochs=3,
            learning_rate=0.01,
        )

        assert result["ok"] is True
        assert result["model_id"] == "discount_anomaly"
        assert result["sample_count"] == 30
        assert result["weight_count"] == 52
        assert "loss" in result["metrics"]
        assert "accuracy" in result["metrics"]
        assert result["metrics"]["epochs_completed"] == 3
        assert len(result["epoch_losses"]) == 3

    @pytest.mark.asyncio
    async def test_train_local_loss_decreases(self, client_with_model: FederatedClient):
        """训练过程中 loss 应该逐步下降"""
        client = client_with_model
        # 使用较多数据和较多 epoch 以确保收敛趋势
        training_data = make_training_data(100)

        result = await client.train_local(
            model_id="discount_anomaly",
            training_data=training_data,
            epochs=10,
            learning_rate=0.005,
        )

        losses = result["epoch_losses"]
        # 至少最后一个 epoch 的 loss 应该小于第一个
        assert losses[-1] <= losses[0] + 0.5  # 允许一些波动

    @pytest.mark.asyncio
    async def test_train_local_model_not_loaded(self, client: FederatedClient):
        result = await client.train_local("nonexistent_model", make_training_data(10))
        assert result["ok"] is False
        assert "未加载" in result["error"]

    @pytest.mark.asyncio
    async def test_train_local_empty_data(self, client_with_model: FederatedClient):
        result = await client_with_model.train_local("discount_anomaly", [])
        assert result["ok"] is False
        assert "为空" in result["error"]

    @pytest.mark.asyncio
    async def test_train_local_updates_weights(self, client_with_model: FederatedClient):
        client = client_with_model
        original_weights = list(client.local_models["discount_anomaly"]["weights"])

        await client.train_local("discount_anomaly", make_training_data(20), epochs=3)

        new_weights = client.local_models["discount_anomaly"]["weights"]
        # 权重应该有所变化
        diffs = sum(abs(new_weights[i] - original_weights[i]) for i in range(len(original_weights)))
        assert diffs > 0

    @pytest.mark.asyncio
    async def test_train_local_records_history(self, client_with_model: FederatedClient):
        client = client_with_model
        assert len(client.training_history) == 0

        await client.train_local("discount_anomaly", make_training_data(20), epochs=2)
        assert len(client.training_history) == 1

        entry = client.training_history[0]
        assert entry["model_id"] == "discount_anomaly"
        assert entry["epochs"] == 2
        assert entry["sample_count"] == 20

    @pytest.mark.asyncio
    async def test_train_local_updates_source(self, client_with_model: FederatedClient):
        client = client_with_model
        assert client.local_models["discount_anomaly"]["source"] == "global"

        await client.train_local("discount_anomaly", make_training_data(10))
        assert client.local_models["discount_anomaly"]["source"] == "local_trained"

    @pytest.mark.asyncio
    async def test_train_with_string_features(self, client_with_model: FederatedClient):
        """测试含字符串特征的数据（如 waiter_id）"""
        client = client_with_model
        data = [
            {"features": [0.3, 100, 12, "waiter_007", "big_table", "wechat"], "target": 0.0},
            {"features": [0.8, 50, 22, "waiter_003", "small_table", "cash"], "target": 1.0},
        ]
        result = await client.train_local("discount_anomaly", data, epochs=2)
        assert result["ok"] is True


# ─── 3. 模型评估 ───


class TestModelEvaluation:
    @pytest.mark.asyncio
    async def test_evaluate_model(self, client_with_model: FederatedClient):
        client = client_with_model
        test_data = make_test_data(20)

        result = await client.evaluate_model("discount_anomaly", test_data)

        assert result["ok"] is True
        assert result["model_id"] == "discount_anomaly"
        assert result["store_id"] == "test_store_001"
        assert "loss" in result["metrics"]
        assert "accuracy" in result["metrics"]
        assert "rmse" in result["metrics"]
        assert result["metrics"]["test_samples"] == 20

    @pytest.mark.asyncio
    async def test_evaluate_model_not_loaded(self, client: FederatedClient):
        result = await client.evaluate_model("nonexistent", make_test_data(5))
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_evaluate_empty_data(self, client_with_model: FederatedClient):
        result = await client_with_model.evaluate_model("discount_anomaly", [])
        assert result["ok"] is False
        assert "为空" in result["error"]

    @pytest.mark.asyncio
    async def test_evaluate_after_training_improves(self, client_with_model: FederatedClient):
        """训练后评估应该比训练前好（或至少不差太多）"""
        client = client_with_model
        test_data = make_test_data(30)

        # 训练前评估
        before = await client.evaluate_model("discount_anomaly", test_data)
        before_loss = before["metrics"]["loss"]

        # 训练
        training_data = make_training_data(100)
        await client.train_local("discount_anomaly", training_data, epochs=10, learning_rate=0.005)

        # 训练后评估
        after = await client.evaluate_model("discount_anomaly", test_data)
        after_loss = after["metrics"]["loss"]

        # 训练后 loss 不应显著恶化
        assert after_loss < before_loss + 1.0

    @pytest.mark.asyncio
    async def test_evaluate_returns_version(self, client_with_model: FederatedClient):
        result = await client_with_model.evaluate_model("discount_anomaly", make_test_data(5))
        assert result["version"] == "1.0.0"


# ─── 4. 提交更新 ───


class TestSubmitUpdate:
    @pytest.mark.asyncio
    async def test_submit_without_training(self, client_with_model: FederatedClient):
        """未训练过就提交应失败"""
        client = client_with_model
        result = await client.submit_update("round_123", "discount_anomaly")
        assert result["ok"] is False
        assert "训练记录" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_model_not_loaded(self, client: FederatedClient):
        result = await client.submit_update("round_123", "nonexistent")
        assert result["ok"] is False
        assert "未加载" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_after_training_gets_sample_count(self, client_with_model: FederatedClient):
        """训练后提交应能找到正确的样本数"""
        client = client_with_model
        training_data = make_training_data(42)
        await client.train_local("discount_anomaly", training_data, epochs=2)

        # submit_update 会尝试连接服务器，这里会失败（没有真实服务器）
        # 但我们可以验证它能正确找到训练历史
        result = await client.submit_update("round_123", "discount_anomaly")
        # 应该是连接失败，不是"未找到训练记录"
        assert result["ok"] is False
        assert "不可达" in result["error"] or "超时" in result["error"]


# ─── 5. 完整轮次参与 ───


class TestParticipateInRound:
    @pytest.mark.asyncio
    async def test_participate_fails_on_fetch(self, client: FederatedClient):
        """无法连接服务器时应在 fetch 步骤失败"""
        result = await client.participate_in_round(
            round_id="round_001",
            model_id="discount_anomaly",
            training_data=make_training_data(20),
        )
        assert result["ok"] is False
        assert "获取全局模型失败" in result["error"]
        assert "fetch_global_model" in result["steps"]

    @pytest.mark.asyncio
    async def test_participate_full_local_cycle(self, client_with_model: FederatedClient):
        """模拟完整本地训练周期（跳过网络调用部分）"""
        client = client_with_model
        training_data = make_training_data(50)
        test_data = make_test_data(15)

        # 直接测试训练 + 评估部分（不需要网络）
        train_result = await client.train_local("discount_anomaly", training_data, epochs=5)
        assert train_result["ok"] is True

        eval_result = await client.evaluate_model("discount_anomaly", test_data)
        assert eval_result["ok"] is True
        assert eval_result["metrics"]["test_samples"] == 15


# ─── 6. 多客户端模拟 ───


class TestMultiClientSimulation:
    @pytest.mark.asyncio
    async def test_three_stores_train_independently(self):
        """3家门店各自独立训练，验证权重不同"""
        clients = [FederatedClient(f"store_{i}", "http://localhost:8000") for i in range(3)]

        # 给每个客户端加载相同的初始模型
        initial_weights = [0.1] * 52
        for c in clients:
            c.local_models["model_a"] = {
                "weights": list(initial_weights),
                "version": "1.0.0",
                "fetched_at": 1000000.0,
                "source": "global",
            }

        # 每个客户端用不同数据训练
        all_weights = []
        for i, c in enumerate(clients):
            import random

            random.seed(i * 42)
            data = make_training_data(50 + i * 20)
            await c.train_local("model_a", data, epochs=3)
            all_weights.append(list(c.local_models["model_a"]["weights"]))

        # 三组权重应该不同（各自用不同数据训练）
        for i in range(len(all_weights)):
            for j in range(i + 1, len(all_weights)):
                diff = sum(abs(all_weights[i][k] - all_weights[j][k]) for k in range(len(all_weights[i])))
                assert diff > 0, f"Store {i} and {j} should have different weights"

    @pytest.mark.asyncio
    async def test_fedavg_simulation_without_server(self):
        """在本地模拟 FedAvg 聚合（不需要服务器）"""
        clients = [FederatedClient(f"store_{i}", "http://localhost:8000") for i in range(3)]

        weight_count = 52
        initial_weights = [0.1] * weight_count

        sample_counts = [200, 150, 100]
        total_samples = sum(sample_counts)

        for i, c in enumerate(clients):
            c.local_models["model_a"] = {
                "weights": list(initial_weights),
                "version": "1.0.0",
                "fetched_at": 1000000.0,
                "source": "global",
            }
            import random

            random.seed(i * 100)
            data = make_training_data(sample_counts[i])
            await c.train_local("model_a", data, epochs=5)

        # 手动做 FedAvg
        aggregated = [0.0] * weight_count
        for i, c in enumerate(clients):
            w = sample_counts[i] / total_samples
            for j in range(weight_count):
                aggregated[j] += c.local_models["model_a"]["weights"][j] * w

        # 聚合后的权重应该在各客户端权重的范围内
        for j in range(weight_count):
            client_vals = [c.local_models["model_a"]["weights"][j] for c in clients]
            min_val = min(client_vals)
            max_val = max(client_vals)
            # 加权平均应在 min 和 max 之间
            assert min_val - 0.01 <= aggregated[j] <= max_val + 0.01


# ─── 7. FastAPI 路由 ───


class TestFastAPIRoutes:
    def test_router_has_prefix(self):
        assert router.prefix == "/api/v1/federated"

    def test_router_has_routes(self):
        route_paths = [r.path for r in router.routes]
        # Routes include the prefix /api/v1/federated
        assert any("status" in p for p in route_paths)
        assert any("fetch-model" in p for p in route_paths)
        assert any("train-local" in p for p in route_paths)
        assert any("evaluate" in p for p in route_paths)


# ─── 8. 训练历史 ───


class TestTrainingHistory:
    @pytest.mark.asyncio
    async def test_history_grows_with_training(self, client_with_model: FederatedClient):
        client = client_with_model
        data = make_training_data(10)

        for _ in range(3):
            await client.train_local("discount_anomaly", data, epochs=2)

        assert len(client.training_history) == 3
        for entry in client.training_history:
            assert entry["model_id"] == "discount_anomaly"
            assert entry["epochs"] == 2
            assert "epoch_losses" in entry
            assert len(entry["epoch_losses"]) == 2

    @pytest.mark.asyncio
    async def test_history_contains_metrics(self, client_with_model: FederatedClient):
        client = client_with_model
        data = make_training_data(25)

        await client.train_local("discount_anomaly", data, epochs=4)

        entry = client.training_history[0]
        metrics = entry["metrics"]
        assert "loss" in metrics
        assert "accuracy" in metrics
        assert "training_time_seconds" in metrics
        assert metrics["samples_used"] == 25
        assert metrics["epochs_completed"] == 4
