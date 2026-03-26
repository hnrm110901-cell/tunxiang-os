"""联邦学习服务 — 跨商户集体智能 (U3.2)

在保护商户数据隐私的前提下，实现跨商户的模型协同训练。
每家门店的 Mac mini 在本地训练模型，只上传加密梯度/模型参数，
云端聚合后下发更新模型。

核心流程：
    注册模型 → 创建训练轮次 → 门店加入 → 本地训练 → 提交梯度
    → 差分隐私加噪 → FedAvg 聚合 → 分发新模型 → 效果追踪
"""
import math
import random
import time
import uuid
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# ─── 联邦模型定义 ───

FEDERATED_MODELS: dict[str, dict[str, Any]] = {
    "discount_anomaly": {
        "description": "折扣异常检测模型 — 识别异常打折行为",
        "input_features": [
            "discount_rate", "order_amount", "time_of_day",
            "waiter_id", "table_type", "payment_method",
        ],
        "output": "anomaly_score (0-1)",
        "default_epsilon": 1.0,
    },
    "dish_time_prediction": {
        "description": "出餐时间预测模型 — 预估菜品出餐时间",
        "input_features": [
            "dish_id", "order_count", "kitchen_load",
            "time_of_day", "day_of_week", "staff_count",
        ],
        "output": "predicted_minutes",
        "default_epsilon": 2.0,
    },
    "traffic_forecast": {
        "description": "客流量预测模型 — 预测门店客流",
        "input_features": [
            "day_of_week", "weather", "temperature",
            "holiday_flag", "nearby_events", "historical_avg",
        ],
        "output": "predicted_customers",
        "default_epsilon": 2.0,
    },
    "waste_prediction": {
        "description": "损耗预测模型 — 预测食材损耗量",
        "input_features": [
            "ingredient_id", "stock_quantity", "daily_usage",
            "storage_temp", "days_since_intake", "season",
        ],
        "output": "predicted_waste_kg",
        "default_epsilon": 1.5,
    },
    "price_optimization": {
        "description": "定价优化模型 — 最优菜品定价",
        "input_features": [
            "dish_id", "cost_price", "competitor_price",
            "demand_elasticity", "time_slot", "customer_segment",
        ],
        "output": "optimal_price_fen",
        "default_epsilon": 1.0,
    },
    "customer_churn": {
        "description": "客户流失预测模型 — 识别即将流失的会员",
        "input_features": [
            "days_since_last_visit", "visit_frequency", "avg_spend",
            "rfm_segment", "complaint_count", "loyalty_points",
        ],
        "output": "churn_probability (0-1)",
        "default_epsilon": 0.5,
    },
}


class FederatedLearningService:
    """联邦学习服务 — 跨商户集体智能

    在保护商户数据隐私的前提下，实现跨商户的模型协同训练。
    每家门店的 Mac mini 在本地训练模型，只上传加密梯度/模型参数，
    云端聚合后下发更新模型。
    """

    def __init__(self) -> None:
        # 模型注册表: {model_id: model_info}
        self._models: dict[str, dict[str, Any]] = {}
        # 训练轮次: {round_id: round_info}
        self._rounds: dict[str, dict[str, Any]] = {}
        # 全局模型权重: {model_id: {version: str, weights: list[float]}}
        self._global_models: dict[str, dict[str, Any]] = {}
        # 隐私预算追踪: {(model_id, store_id): cumulative_epsilon}
        self._privacy_budgets: dict[tuple[str, str], float] = {}
        # 门店模型版本: {(store_id, model_id): version}
        self._store_model_versions: dict[tuple[str, str], str] = {}
        # 性能报告: {(store_id, model_id): [metrics_entries]}
        self._performance_reports: dict[tuple[str, str], list[dict[str, Any]]] = {}
        # 最大隐私预算
        self._max_privacy_budget: float = 10.0

    # ─── 1. Model Registry (模型注册表) ───

    def register_model(
        self,
        model_id: str,
        model_type: str,
        description: str,
        input_schema: list[str],
        output_schema: str,
        version: str = "1.0.0",
    ) -> dict[str, Any]:
        """注册联邦学习模型

        Args:
            model_id: 模型唯一 ID
            model_type: 模型类型 (如 discount_anomaly, dish_time_prediction)
            description: 模型描述
            input_schema: 输入特征列表
            output_schema: 输出描述
            version: 初始版本号

        Returns:
            注册结果，含模型元信息
        """
        if model_id in self._models:
            logger.warning("model_already_registered", model_id=model_id)
            return {
                "ok": False,
                "error": f"模型 {model_id} 已注册",
                "model_id": model_id,
            }

        # 获取默认 epsilon（如果是预定义模型类型）
        default_epsilon = 1.0
        if model_type in FEDERATED_MODELS:
            default_epsilon = FEDERATED_MODELS[model_type]["default_epsilon"]

        model_info = {
            "model_id": model_id,
            "model_type": model_type,
            "description": description,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "version": version,
            "default_epsilon": default_epsilon,
            "created_at": time.time(),
            "updated_at": time.time(),
            "total_rounds": 0,
            "participating_stores": [],
        }
        self._models[model_id] = model_info

        # 初始化全局模型 — 模拟权重（基于输入特征数量）
        weight_count = len(input_schema) * 8 + 4  # 简单全连接层模拟
        initial_weights = [random.gauss(0, 0.1) for _ in range(weight_count)]
        self._global_models[model_id] = {
            "version": version,
            "weights": initial_weights,
            "weight_count": weight_count,
            "updated_at": time.time(),
        }

        logger.info(
            "model_registered",
            model_id=model_id,
            model_type=model_type,
            weight_count=weight_count,
        )
        return {"ok": True, "model": model_info}

    def list_models(self) -> list[dict[str, Any]]:
        """列出所有已注册模型"""
        return list(self._models.values())

    def get_model_info(self, model_id: str) -> dict[str, Any]:
        """获取模型详情

        Args:
            model_id: 模型 ID

        Returns:
            模型元信息，不存在则返回 error
        """
        if model_id not in self._models:
            return {"ok": False, "error": f"模型 {model_id} 不存在"}
        return {"ok": True, "model": self._models[model_id]}

    # ─── 2. Training Round Management (训练轮次管理) ───

    def create_training_round(
        self,
        model_id: str,
        min_participants: int = 3,
        max_rounds: int = 10,
        target_metric: str = "accuracy",
        target_value: float = 0.85,
    ) -> dict[str, Any]:
        """创建新的训练轮次

        Args:
            model_id: 要训练的模型 ID
            min_participants: 最少参与门店数
            max_rounds: 最大聚合轮次
            target_metric: 目标指标名
            target_value: 目标指标值

        Returns:
            轮次信息，含 round_id 和状态
        """
        if model_id not in self._models:
            return {"ok": False, "error": f"模型 {model_id} 不存在"}

        round_id = f"round_{uuid.uuid4().hex[:12]}"
        round_info = {
            "round_id": round_id,
            "model_id": model_id,
            "status": "waiting_for_participants",  # waiting → training → aggregating → completed
            "min_participants": min_participants,
            "max_rounds": max_rounds,
            "current_round": 0,
            "target_metric": target_metric,
            "target_value": target_value,
            "participants": {},  # {store_id: {joined_at, sample_count, status}}
            "updates": {},  # {store_id: {weights, metrics, sample_count}}
            "round_history": [],  # [{round_num, metrics, timestamp}]
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._rounds[round_id] = round_info
        self._models[model_id]["total_rounds"] += 1

        logger.info(
            "training_round_created",
            round_id=round_id,
            model_id=model_id,
            min_participants=min_participants,
        )
        return {"ok": True, "round": round_info}

    def join_training_round(
        self,
        round_id: str,
        store_id: str,
        local_sample_count: int,
    ) -> dict[str, Any]:
        """门店加入训练轮次

        Args:
            round_id: 轮次 ID
            store_id: 门店 ID
            local_sample_count: 本地训练样本数量

        Returns:
            加入结果
        """
        if round_id not in self._rounds:
            return {"ok": False, "error": f"训练轮次 {round_id} 不存在"}

        round_info = self._rounds[round_id]

        if round_info["status"] not in ("waiting_for_participants", "training"):
            return {
                "ok": False,
                "error": f"轮次状态 {round_info['status']} 不允许加入",
            }

        if store_id in round_info["participants"]:
            return {"ok": False, "error": f"门店 {store_id} 已加入此轮次"}

        round_info["participants"][store_id] = {
            "joined_at": time.time(),
            "sample_count": local_sample_count,
            "status": "joined",
        }

        # 更新模型的参与门店列表
        model_id = round_info["model_id"]
        if store_id not in self._models[model_id]["participating_stores"]:
            self._models[model_id]["participating_stores"].append(store_id)

        # 当参与者达到最小数量时，自动切换到训练状态
        if len(round_info["participants"]) >= round_info["min_participants"]:
            if round_info["status"] == "waiting_for_participants":
                round_info["status"] = "training"
                round_info["current_round"] = 1
                logger.info(
                    "training_round_started",
                    round_id=round_id,
                    participant_count=len(round_info["participants"]),
                )

        round_info["updated_at"] = time.time()

        logger.info(
            "store_joined_round",
            round_id=round_id,
            store_id=store_id,
            sample_count=local_sample_count,
        )
        return {
            "ok": True,
            "round_id": round_id,
            "store_id": store_id,
            "status": round_info["status"],
            "participant_count": len(round_info["participants"]),
        }

    def get_round_status(self, round_id: str) -> dict[str, Any]:
        """查询训练轮次状态

        Args:
            round_id: 轮次 ID

        Returns:
            轮次详情
        """
        if round_id not in self._rounds:
            return {"ok": False, "error": f"训练轮次 {round_id} 不存在"}

        round_info = self._rounds[round_id]
        return {
            "ok": True,
            "round": {
                "round_id": round_info["round_id"],
                "model_id": round_info["model_id"],
                "status": round_info["status"],
                "current_round": round_info["current_round"],
                "max_rounds": round_info["max_rounds"],
                "participant_count": len(round_info["participants"]),
                "updates_received": len(round_info["updates"]),
                "round_history": round_info["round_history"],
            },
        }

    # ─── 3. Gradient Aggregation (梯度聚合) ───

    def submit_local_update(
        self,
        round_id: str,
        store_id: str,
        model_weights: list[float],
        metrics: dict[str, float],
        sample_count: int,
    ) -> dict[str, Any]:
        """提交本地模型更新

        门店在本地训练后提交更新的模型权重。
        服务端会自动在存储前添加差分隐私噪声。

        Args:
            round_id: 轮次 ID
            store_id: 门店 ID
            model_weights: 更新后的模型权重（扁平浮点数组）
            metrics: 本地训练指标 (如 {"accuracy": 0.87, "loss": 0.23})
            sample_count: 本次训练使用的样本数

        Returns:
            提交结果
        """
        if round_id not in self._rounds:
            return {"ok": False, "error": f"训练轮次 {round_id} 不存在"}

        round_info = self._rounds[round_id]

        if round_info["status"] != "training":
            return {
                "ok": False,
                "error": f"轮次状态 {round_info['status']} 不接受更新提交",
            }

        if store_id not in round_info["participants"]:
            return {"ok": False, "error": f"门店 {store_id} 未加入此轮次"}

        model_id = round_info["model_id"]

        # 检查权重维度
        expected_count = self._global_models[model_id]["weight_count"]
        if len(model_weights) != expected_count:
            return {
                "ok": False,
                "error": f"权重维度不匹配: 期望 {expected_count}, 收到 {len(model_weights)}",
            }

        # 检查隐私预算
        compliance = self.check_privacy_compliance(store_id)
        if not compliance["compliant"]:
            return {
                "ok": False,
                "error": f"门店 {store_id} 隐私预算已耗尽",
            }

        # 添加差分隐私噪声
        epsilon = self._models[model_id].get("default_epsilon", 1.0)
        noised = self.add_noise(model_weights, epsilon=epsilon)
        noised_weights = noised["noised_gradients"]

        # 记录隐私消耗
        budget_key = (model_id, store_id)
        current_budget = self._privacy_budgets.get(budget_key, 0.0)
        self._privacy_budgets[budget_key] = current_budget + epsilon

        # 存储更新
        round_info["updates"][store_id] = {
            "weights": noised_weights,
            "metrics": metrics,
            "sample_count": sample_count,
            "submitted_at": time.time(),
            "epsilon_used": epsilon,
        }
        round_info["participants"][store_id]["status"] = "submitted"
        round_info["updated_at"] = time.time()

        logger.info(
            "local_update_submitted",
            round_id=round_id,
            store_id=store_id,
            sample_count=sample_count,
            epsilon_used=epsilon,
            updates_received=len(round_info["updates"]),
            total_participants=len(round_info["participants"]),
        )

        return {
            "ok": True,
            "round_id": round_id,
            "store_id": store_id,
            "epsilon_used": epsilon,
            "cumulative_epsilon": self._privacy_budgets[budget_key],
            "updates_received": len(round_info["updates"]),
            "total_participants": len(round_info["participants"]),
        }

    def aggregate_updates(self, round_id: str) -> dict[str, Any]:
        """聚合本轮所有门店的模型更新 (FedAvg)

        使用 Federated Averaging: 按门店样本数加权平均模型权重。

        Args:
            round_id: 轮次 ID

        Returns:
            聚合结果，含全局模型权重和本轮指标
        """
        if round_id not in self._rounds:
            return {"ok": False, "error": f"训练轮次 {round_id} 不存在"}

        round_info = self._rounds[round_id]

        if not round_info["updates"]:
            return {"ok": False, "error": "没有收到任何更新，无法聚合"}

        round_info["status"] = "aggregating"
        model_id = round_info["model_id"]
        weight_count = self._global_models[model_id]["weight_count"]

        # ─── FedAvg: 按样本数加权平均 ───
        total_samples = sum(
            u["sample_count"] for u in round_info["updates"].values()
        )

        if total_samples == 0:
            return {"ok": False, "error": "所有参与者样本数为 0"}

        # 初始化聚合权重
        aggregated_weights: list[float] = [0.0] * weight_count

        for store_id, update in round_info["updates"].items():
            weight_factor = update["sample_count"] / total_samples
            for i in range(weight_count):
                aggregated_weights[i] += update["weights"][i] * weight_factor

        # 计算与旧全局模型的差异
        old_weights = self._global_models[model_id]["weights"]
        weight_delta = sum(
            abs(aggregated_weights[i] - old_weights[i])
            for i in range(weight_count)
        ) / weight_count

        # 聚合指标（各门店指标的加权平均）
        all_metric_keys: set[str] = set()
        for update in round_info["updates"].values():
            all_metric_keys.update(update["metrics"].keys())

        aggregated_metrics: dict[str, float] = {}
        for key in all_metric_keys:
            weighted_sum = 0.0
            for update in round_info["updates"].values():
                if key in update["metrics"]:
                    w = update["sample_count"] / total_samples
                    weighted_sum += update["metrics"][key] * w
            aggregated_metrics[key] = round(weighted_sum, 6)

        # 更新全局模型
        old_version = self._global_models[model_id]["version"]
        version_parts = old_version.split(".")
        new_patch = int(version_parts[2]) + 1
        new_version = f"{version_parts[0]}.{version_parts[1]}.{new_patch}"

        self._global_models[model_id] = {
            "version": new_version,
            "weights": aggregated_weights,
            "weight_count": weight_count,
            "updated_at": time.time(),
        }
        self._models[model_id]["version"] = new_version
        self._models[model_id]["updated_at"] = time.time()

        # 记录轮次历史
        round_record = {
            "round_num": round_info["current_round"],
            "participants": len(round_info["updates"]),
            "total_samples": total_samples,
            "metrics": aggregated_metrics,
            "weight_delta": round(weight_delta, 6),
            "new_version": new_version,
            "timestamp": time.time(),
        }
        round_info["round_history"].append(round_record)

        # 检查是否达到目标或最大轮次
        target_metric = round_info["target_metric"]
        target_value = round_info["target_value"]
        target_reached = False
        if target_metric in aggregated_metrics:
            target_reached = aggregated_metrics[target_metric] >= target_value

        if target_reached or round_info["current_round"] >= round_info["max_rounds"]:
            round_info["status"] = "completed"
            logger.info(
                "training_round_completed",
                round_id=round_id,
                final_round=round_info["current_round"],
                target_reached=target_reached,
                final_metrics=aggregated_metrics,
            )
        else:
            # 准备下一轮
            round_info["status"] = "training"
            round_info["current_round"] += 1
            round_info["updates"] = {}  # 清空本轮更新
            # 重置参与者状态
            for store_id in round_info["participants"]:
                round_info["participants"][store_id]["status"] = "joined"

        round_info["updated_at"] = time.time()

        logger.info(
            "updates_aggregated",
            round_id=round_id,
            model_id=model_id,
            participant_count=len(round_info["updates"]) or round_record["participants"],
            total_samples=total_samples,
            weight_delta=round(weight_delta, 6),
            new_version=new_version,
        )

        return {
            "ok": True,
            "round_id": round_id,
            "model_id": model_id,
            "new_version": new_version,
            "global_model_weights": aggregated_weights,
            "improvement_delta": round(weight_delta, 6),
            "round_metrics": aggregated_metrics,
            "round_record": round_record,
            "status": round_info["status"],
            "target_reached": target_reached,
        }

    def get_global_model(self, model_id: str) -> dict[str, Any]:
        """获取最新全局模型权重

        Args:
            model_id: 模型 ID

        Returns:
            全局模型权重及版本信息
        """
        if model_id not in self._global_models:
            return {"ok": False, "error": f"模型 {model_id} 不存在"}

        gm = self._global_models[model_id]
        return {
            "ok": True,
            "model_id": model_id,
            "version": gm["version"],
            "weights": gm["weights"],
            "weight_count": gm["weight_count"],
            "updated_at": gm["updated_at"],
        }

    # ─── 4. Differential Privacy (差分隐私) ───

    def add_noise(
        self,
        gradients: list[float],
        epsilon: float = 1.0,
        delta: float = 1e-5,
    ) -> dict[str, Any]:
        """添加差分隐私噪声 (高斯机制)

        噪声标准差 = sensitivity * sqrt(2 * ln(1.25 / delta)) / epsilon
        假设梯度 L2 灵敏度 (sensitivity) = 1.0。

        Args:
            gradients: 原始梯度/权重列表
            epsilon: 隐私参数，越小隐私越强（噪声越大）
            delta: 隐私松弛参数

        Returns:
            加噪后的梯度及噪声统计
        """
        sensitivity = 1.0
        noise_scale = sensitivity * math.sqrt(2.0 * math.log(1.25 / delta)) / epsilon

        noised = []
        noise_values = []
        for g in gradients:
            noise = random.gauss(0, noise_scale)
            noise_values.append(noise)
            noised.append(g + noise)

        noise_l2 = math.sqrt(sum(n * n for n in noise_values))
        noise_mean = sum(abs(n) for n in noise_values) / len(noise_values) if noise_values else 0.0

        return {
            "noised_gradients": noised,
            "noise_scale": round(noise_scale, 6),
            "noise_l2_norm": round(noise_l2, 6),
            "noise_mean_abs": round(noise_mean, 6),
            "epsilon": epsilon,
            "delta": delta,
            "gradient_count": len(gradients),
        }

    def compute_privacy_budget(
        self,
        model_id: str,
        store_id: str,
    ) -> dict[str, Any]:
        """计算门店在某模型上的累计隐私消耗

        Args:
            model_id: 模型 ID
            store_id: 门店 ID

        Returns:
            已消耗的 epsilon 及剩余预算
        """
        budget_key = (model_id, store_id)
        spent = self._privacy_budgets.get(budget_key, 0.0)
        remaining = max(0.0, self._max_privacy_budget - spent)

        return {
            "model_id": model_id,
            "store_id": store_id,
            "epsilon_spent": round(spent, 4),
            "epsilon_remaining": round(remaining, 4),
            "max_budget": self._max_privacy_budget,
            "budget_utilization_pct": round(spent / self._max_privacy_budget * 100, 1),
        }

    def check_privacy_compliance(self, store_id: str) -> dict[str, Any]:
        """检查门店是否仍有隐私预算可用

        聚合该门店在所有模型上的隐私消耗。

        Args:
            store_id: 门店 ID

        Returns:
            合规状态及各模型消耗详情
        """
        model_budgets: dict[str, float] = {}
        for (mid, sid), spent in self._privacy_budgets.items():
            if sid == store_id:
                model_budgets[mid] = spent

        # 对每个模型检查是否超预算
        violations: list[str] = []
        for mid, spent in model_budgets.items():
            if spent >= self._max_privacy_budget:
                violations.append(
                    f"模型 {mid}: 已消耗 {spent:.2f} >= 上限 {self._max_privacy_budget}"
                )

        compliant = len(violations) == 0
        total_spent = sum(model_budgets.values())

        return {
            "store_id": store_id,
            "compliant": compliant,
            "total_epsilon_spent": round(total_spent, 4),
            "model_budgets": {
                mid: round(spent, 4) for mid, spent in model_budgets.items()
            },
            "violations": violations,
            "max_budget_per_model": self._max_privacy_budget,
        }

    # ─── 5. Model Distribution (模型分发) ───

    def distribute_model(
        self,
        model_id: str,
        target_stores: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """分发全局模型到门店

        Args:
            model_id: 模型 ID
            target_stores: 目标门店列表，None 表示所有参与门店

        Returns:
            分发结果
        """
        if model_id not in self._global_models:
            return {"ok": False, "error": f"模型 {model_id} 不存在"}

        if model_id not in self._models:
            return {"ok": False, "error": f"模型 {model_id} 未注册"}

        gm = self._global_models[model_id]
        version = gm["version"]

        # 确定目标门店
        if target_stores is None:
            target_stores = self._models[model_id].get("participating_stores", [])

        if not target_stores:
            return {"ok": False, "error": "没有目标门店可分发"}

        distributed_to: list[str] = []
        for store_id in target_stores:
            self._store_model_versions[(store_id, model_id)] = version
            distributed_to.append(store_id)

        logger.info(
            "model_distributed",
            model_id=model_id,
            version=version,
            store_count=len(distributed_to),
        )

        return {
            "ok": True,
            "model_id": model_id,
            "version": version,
            "distributed_to": distributed_to,
            "store_count": len(distributed_to),
            "distributed_at": time.time(),
        }

    def get_store_model_version(
        self,
        store_id: str,
        model_id: str,
    ) -> dict[str, Any]:
        """查询门店上的模型版本

        Args:
            store_id: 门店 ID
            model_id: 模型 ID

        Returns:
            门店当前模型版本信息
        """
        version_key = (store_id, model_id)
        version = self._store_model_versions.get(version_key)

        if version is None:
            return {
                "ok": False,
                "error": f"门店 {store_id} 未安装模型 {model_id}",
            }

        global_version = self._global_models.get(model_id, {}).get("version")
        is_latest = version == global_version

        return {
            "ok": True,
            "store_id": store_id,
            "model_id": model_id,
            "installed_version": version,
            "global_version": global_version,
            "is_latest": is_latest,
        }

    def rollback_model(
        self,
        model_id: str,
        version: str,
    ) -> dict[str, Any]:
        """回滚模型到指定版本

        注意：此方法在内存存储模式下仅更新版本号标记，
        实际生产中应从版本存储中恢复对应权重。

        Args:
            model_id: 模型 ID
            version: 要回滚到的版本号

        Returns:
            回滚结果
        """
        if model_id not in self._global_models:
            return {"ok": False, "error": f"模型 {model_id} 不存在"}

        old_version = self._global_models[model_id]["version"]
        self._global_models[model_id]["version"] = version
        self._global_models[model_id]["updated_at"] = time.time()
        self._models[model_id]["version"] = version
        self._models[model_id]["updated_at"] = time.time()

        logger.info(
            "model_rolled_back",
            model_id=model_id,
            from_version=old_version,
            to_version=version,
        )

        return {
            "ok": True,
            "model_id": model_id,
            "from_version": old_version,
            "to_version": version,
            "rolled_back_at": time.time(),
        }

    # ─── 6. Performance Tracking (效果追踪) ───

    def report_local_performance(
        self,
        store_id: str,
        model_id: str,
        metrics: dict[str, float],
    ) -> dict[str, Any]:
        """门店上报模型在本地数据上的表现

        Args:
            store_id: 门店 ID
            model_id: 模型 ID
            metrics: 性能指标 (如 {"accuracy": 0.88, "loss": 0.15, "f1": 0.85})

        Returns:
            上报确认
        """
        report_key = (store_id, model_id)
        if report_key not in self._performance_reports:
            self._performance_reports[report_key] = []

        entry = {
            "metrics": metrics,
            "reported_at": time.time(),
            "version": self._store_model_versions.get(
                (store_id, model_id), "unknown"
            ),
        }
        self._performance_reports[report_key].append(entry)

        logger.info(
            "performance_reported",
            store_id=store_id,
            model_id=model_id,
            metrics=metrics,
        )

        return {
            "ok": True,
            "store_id": store_id,
            "model_id": model_id,
            "entry": entry,
            "total_reports": len(self._performance_reports[report_key]),
        }

    def get_federated_performance(
        self,
        model_id: str,
    ) -> dict[str, Any]:
        """聚合所有门店的模型性能

        Args:
            model_id: 模型 ID

        Returns:
            跨门店聚合性能指标
        """
        # 收集所有门店对该模型的最新报告
        store_metrics: dict[str, dict[str, float]] = {}
        for (sid, mid), reports in self._performance_reports.items():
            if mid == model_id and reports:
                latest = reports[-1]
                store_metrics[sid] = latest["metrics"]

        if not store_metrics:
            return {
                "ok": False,
                "error": f"模型 {model_id} 暂无性能报告",
            }

        # 聚合所有指标（取平均）
        all_keys: set[str] = set()
        for m in store_metrics.values():
            all_keys.update(m.keys())

        aggregated: dict[str, float] = {}
        per_store: dict[str, dict[str, float]] = {}

        for key in all_keys:
            values = [
                m[key] for m in store_metrics.values() if key in m
            ]
            if values:
                aggregated[key] = round(sum(values) / len(values), 6)

        for sid, m in store_metrics.items():
            per_store[sid] = m

        return {
            "ok": True,
            "model_id": model_id,
            "store_count": len(store_metrics),
            "aggregated_metrics": aggregated,
            "per_store_metrics": per_store,
        }

    def compare_local_vs_global(
        self,
        store_id: str,
        model_id: str,
    ) -> dict[str, Any]:
        """对比门店本地模型 vs 联邦全局模型的表现

        通过该门店最早的报告（本地训练初期）和最新报告（联邦训练后）对比。

        Args:
            store_id: 门店 ID
            model_id: 模型 ID

        Returns:
            对比结果，含各指标的 delta
        """
        report_key = (store_id, model_id)
        reports = self._performance_reports.get(report_key, [])

        if len(reports) < 2:
            return {
                "ok": False,
                "error": "需要至少两次性能报告才能对比",
                "reports_count": len(reports),
            }

        first_report = reports[0]
        latest_report = reports[-1]

        comparison: dict[str, dict[str, Any]] = {}
        all_keys = set(first_report["metrics"].keys()) | set(
            latest_report["metrics"].keys()
        )

        for key in all_keys:
            local_val = first_report["metrics"].get(key, 0.0)
            global_val = latest_report["metrics"].get(key, 0.0)
            delta = global_val - local_val
            pct_change = (delta / local_val * 100) if local_val != 0 else 0.0
            comparison[key] = {
                "local_only": round(local_val, 6),
                "federated": round(global_val, 6),
                "delta": round(delta, 6),
                "improvement_pct": round(pct_change, 2),
            }

        # 判断联邦模型是否优于本地
        improvements = sum(
            1 for v in comparison.values()
            if v["delta"] > 0 and "loss" not in v  # loss 越低越好
        )
        degradations = sum(
            1 for v in comparison.values()
            if v["delta"] < 0 and "loss" not in v
        )
        # 对 loss 类指标，delta < 0 才是改善
        for key, v in comparison.items():
            if "loss" in key:
                if v["delta"] < 0:
                    improvements += 1
                elif v["delta"] > 0:
                    degradations += 1

        federated_better = improvements > degradations

        return {
            "ok": True,
            "store_id": store_id,
            "model_id": model_id,
            "local_version": first_report.get("version", "unknown"),
            "federated_version": latest_report.get("version", "unknown"),
            "comparison": comparison,
            "federated_better": federated_better,
            "improvements": improvements,
            "degradations": degradations,
        }
