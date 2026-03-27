"""Sprint 9-10 Tests — Neo4j Ontology + Cost Truth + Reasoning Engines

Covers:
- Neo4j ontology: create nodes/relationships, query paths, find neighbors
- CDC sync simulation: PG change → graph update
- BOM cost calculation (剁椒鱼头 full BOM expansion)
- Cost anomaly detection
- Price change simulation (鲈鱼涨价20% → 哪些菜受影响)
- Causal chain reasoning ("酸菜鱼毛利下降" → 根因链)
- Multi-factor attribution
- Store comparison analysis
- Auto-insight generation
"""

import pytest
from datetime import datetime

from ..ontology.schema import (
    NODE_LABELS,
    RELATIONSHIP_TYPES,
    validate_node_label,
    validate_node_properties,
    validate_relationship_type,
)
from ..ontology.models import NodeModel, RelationshipModel, BOMEntry, DishCostBreakdown
from ..ontology.repository import OntologyRepository
from ..ontology.bootstrap import OntologyBootstrap, SEED_BOM, SEED_DISHES
from ..ontology.data_sync import PGToNeo4jSync
from ..ontology.reasoning import CausalReasoningEngine
from ..services.cost_truth_engine import CostTruthEngine
from ..services.reasoning_engine import ReasoningEngine


# ─── Fixtures ───


@pytest.fixture
def repo() -> OntologyRepository:
    """Fresh in-memory repository."""
    return OntologyRepository(mode="memory")


@pytest.fixture
def seeded_repo() -> OntologyRepository:
    """Repository pre-seeded with restaurant data."""
    repo = OntologyRepository(mode="memory")
    bootstrap = OntologyBootstrap(repo)
    bootstrap.bootstrap_all()
    return repo


@pytest.fixture
def sync(seeded_repo: OntologyRepository) -> PGToNeo4jSync:
    """PG→Neo4j sync engine with registered tables."""
    sync = PGToNeo4jSync(seeded_repo, mode="memory")
    sync.register_table_sync(
        table_name="dishes",
        node_label="Dish",
        field_mapping={"id": "id", "name": "name", "price_fen": "price_fen", "tenant_id": "tenant_id"},
        id_field="id",
    )
    sync.register_table_sync(
        table_name="ingredients",
        node_label="Ingredient",
        field_mapping={
            "id": "id", "name": "name", "unit": "unit",
            "price_per_kg_fen": "price_per_kg_fen", "tenant_id": "tenant_id",
        },
        id_field="id",
    )
    sync.register_table_sync(
        table_name="stores",
        node_label="Store",
        field_mapping={"id": "id", "name": "name", "tenant_id": "tenant_id"},
        id_field="id",
    )
    return sync


@pytest.fixture
def causal_engine(seeded_repo: OntologyRepository) -> CausalReasoningEngine:
    return CausalReasoningEngine(seeded_repo)


@pytest.fixture
def cost_engine(seeded_repo: OntologyRepository) -> CostTruthEngine:
    return CostTruthEngine(seeded_repo)


@pytest.fixture
def reasoning_engine(seeded_repo: OntologyRepository) -> ReasoningEngine:
    return ReasoningEngine(seeded_repo)


# ═══════════════════════════════════════════════════════════
# 1. Schema Validation Tests
# ═══════════════════════════════════════════════════════════


class TestSchema:
    def test_node_labels_count(self) -> None:
        assert len(NODE_LABELS) == 11

    def test_relationship_types_count(self) -> None:
        assert len(RELATIONSHIP_TYPES) == 15

    def test_validate_valid_label(self) -> None:
        assert validate_node_label("Store") is True
        assert validate_node_label("Dish") is True
        assert validate_node_label("Ingredient") is True

    def test_validate_invalid_label(self) -> None:
        assert validate_node_label("FakeLabel") is False

    def test_validate_valid_relationship(self) -> None:
        assert validate_relationship_type("SERVES") is True
        assert validate_relationship_type("USES_INGREDIENT") is True
        assert validate_relationship_type("CAUSES") is True

    def test_validate_invalid_relationship(self) -> None:
        assert validate_relationship_type("FAKE_REL") is False

    def test_validate_node_properties_valid(self) -> None:
        missing = validate_node_properties("Store", {"name": "Test", "tenant_id": "t1"})
        assert missing == []

    def test_validate_node_properties_missing(self) -> None:
        missing = validate_node_properties("Store", {"name": "Test"})
        assert "tenant_id" in missing

    def test_validate_dish_properties(self) -> None:
        missing = validate_node_properties("Dish", {"name": "鱼", "tenant_id": "t1"})
        assert "price_fen" in missing


# ═══════════════════════════════════════════════════════════
# 2. Repository CRUD Tests
# ═══════════════════════════════════════════════════════════


class TestRepository:
    def test_create_node(self, repo: OntologyRepository) -> None:
        result = repo.create_node("Store", {
            "id": "s1", "name": "Test Store", "tenant_id": "t1",
        })
        assert result["ok"] is True
        assert result["node_id"] == "s1"

    def test_create_node_invalid_label(self, repo: OntologyRepository) -> None:
        with pytest.raises(ValueError, match="Invalid node label"):
            repo.create_node("FakeLabel", {"name": "x"})

    def test_create_node_missing_props(self, repo: OntologyRepository) -> None:
        with pytest.raises(ValueError, match="Missing required"):
            repo.create_node("Store", {"name": "x"})

    def test_get_node(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "Test", "tenant_id": "t1"})
        result = repo.get_node("Store", "s1")
        assert result["ok"] is True
        assert result["node"]["properties"]["name"] == "Test"

    def test_get_node_not_found(self, repo: OntologyRepository) -> None:
        result = repo.get_node("Store", "nonexistent")
        assert result["ok"] is False

    def test_update_node(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "Old", "tenant_id": "t1"})
        result = repo.update_node("Store", "s1", {"name": "New"})
        assert result["ok"] is True
        assert result["node"]["properties"]["name"] == "New"

    def test_delete_node(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "Test", "tenant_id": "t1"})
        result = repo.delete_node("Store", "s1")
        assert result["ok"] is True
        assert repo.get_node("Store", "s1")["ok"] is False

    def test_create_relationship(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "S1", "tenant_id": "t1"})
        repo.create_node("Dish", {"id": "d1", "name": "D1", "tenant_id": "t1", "price_fen": 100})
        result = repo.create_relationship("Store", "s1", "SERVES", "Dish", "d1")
        assert result["ok"] is True
        assert result["relationship"]["rel_type"] == "SERVES"

    def test_create_relationship_invalid_type(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "S1", "tenant_id": "t1"})
        repo.create_node("Dish", {"id": "d1", "name": "D1", "tenant_id": "t1", "price_fen": 100})
        with pytest.raises(ValueError, match="Invalid relationship type"):
            repo.create_relationship("Store", "s1", "FAKE_REL", "Dish", "d1")

    def test_get_relationships(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "S1", "tenant_id": "t1"})
        repo.create_node("Dish", {"id": "d1", "name": "D1", "tenant_id": "t1", "price_fen": 100})
        repo.create_node("Dish", {"id": "d2", "name": "D2", "tenant_id": "t1", "price_fen": 200})
        repo.create_relationship("Store", "s1", "SERVES", "Dish", "d1")
        repo.create_relationship("Store", "s1", "SERVES", "Dish", "d2")

        rels = repo.get_relationships("Store", "s1", rel_type="SERVES")
        assert len(rels) == 2

    def test_get_relationships_direction(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "S1", "tenant_id": "t1"})
        repo.create_node("Dish", {"id": "d1", "name": "D1", "tenant_id": "t1", "price_fen": 100})
        repo.create_relationship("Store", "s1", "SERVES", "Dish", "d1")

        out_rels = repo.get_relationships("Store", "s1", direction="out")
        assert len(out_rels) == 1

        in_rels = repo.get_relationships("Store", "s1", direction="in")
        assert len(in_rels) == 0

    def test_delete_relationship(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "S1", "tenant_id": "t1"})
        repo.create_node("Dish", {"id": "d1", "name": "D1", "tenant_id": "t1", "price_fen": 100})
        result = repo.create_relationship("Store", "s1", "SERVES", "Dish", "d1")
        rel_id = result["rel_id"]

        del_result = repo.delete_relationship(rel_id)
        assert del_result["ok"] is True
        assert len(repo.get_relationships("Store", "s1")) == 0

    def test_delete_node_cascades_relationships(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "S1", "tenant_id": "t1"})
        repo.create_node("Dish", {"id": "d1", "name": "D1", "tenant_id": "t1", "price_fen": 100})
        repo.create_relationship("Store", "s1", "SERVES", "Dish", "d1")

        result = repo.delete_node("Store", "s1")
        assert result["deleted_relationships"] >= 1
        assert repo.relationship_count() == 0

    def test_node_count(self, repo: OntologyRepository) -> None:
        repo.create_node("Store", {"id": "s1", "name": "S1", "tenant_id": "t1"})
        repo.create_node("Store", {"id": "s2", "name": "S2", "tenant_id": "t1"})
        repo.create_node("Dish", {"id": "d1", "name": "D1", "tenant_id": "t1", "price_fen": 100})

        assert repo.node_count() == 3
        assert repo.node_count("Store") == 2
        assert repo.node_count("Dish") == 1


# ═══════════════════════════════════════════════════════════
# 3. Graph Query Tests
# ═══════════════════════════════════════════════════════════


class TestGraphQueries:
    def test_query_path(self, seeded_repo: OntologyRepository) -> None:
        """Store → Dish → Ingredient path."""
        path = seeded_repo.query_path("Store", "store-001", "Ingredient", "ing-luyu")
        assert len(path) > 0
        # Path should go Store→Dish→Ingredient
        assert path[0]["node"]["id"] == "store-001"
        assert path[-1]["node"]["id"] == "ing-luyu"

    def test_query_path_not_found(self, seeded_repo: OntologyRepository) -> None:
        path = seeded_repo.query_path("Store", "store-001", "Region", "nonexistent")
        assert len(path) == 0

    def test_query_path_same_node(self, seeded_repo: OntologyRepository) -> None:
        path = seeded_repo.query_path("Store", "store-001", "Store", "store-001")
        assert len(path) == 1

    def test_query_neighbors_depth1(self, seeded_repo: OntologyRepository) -> None:
        result = seeded_repo.query_neighbors("Store", "store-001", depth=1)
        assert result["total_count"] > 0
        # Store-001 connects to brand, region, and dishes
        neighbor_labels = {n["label"] for n in result["neighbors"]}
        assert "Brand" in neighbor_labels or "Dish" in neighbor_labels

    def test_query_neighbors_depth2(self, seeded_repo: OntologyRepository) -> None:
        result = seeded_repo.query_neighbors("Store", "store-001", depth=2)
        # Depth 2 should reach ingredients through dishes
        neighbor_labels = {n["label"] for n in result["neighbors"]}
        assert "Ingredient" in neighbor_labels

    def test_find_nodes_by_label(self, seeded_repo: OntologyRepository) -> None:
        stores = seeded_repo.find_nodes("Store")
        assert len(stores) == 2

    def test_find_nodes_with_filter(self, seeded_repo: OntologyRepository) -> None:
        dishes = seeded_repo.find_nodes("Dish", filters={"name": "剁椒鱼头"})
        assert len(dishes) == 1
        assert dishes[0]["properties"]["name"] == "剁椒鱼头"

    def test_find_nodes_no_match(self, seeded_repo: OntologyRepository) -> None:
        result = seeded_repo.find_nodes("Dish", filters={"name": "不存在的菜"})
        assert len(result) == 0

    def test_aggregate(self, seeded_repo: OntologyRepository) -> None:
        # Aggregate dish prices by category
        result = seeded_repo.aggregate("Dish", "category_id", "price_fen", "avg")
        assert len(result) > 0
        # All seed dishes are in cat-hot
        for item in result:
            if item["group"] == "cat-hot":
                assert item["value"] > 0


# ═══════════════════════════════════════════════════════════
# 4. Bootstrap / Seed Data Tests
# ═══════════════════════════════════════════════════════════


class TestBootstrap:
    def test_bootstrap_creates_all_entities(self, seeded_repo: OntologyRepository) -> None:
        assert seeded_repo.node_count("Store") == 2
        assert seeded_repo.node_count("Brand") == 1
        assert seeded_repo.node_count("Dish") == 3
        assert seeded_repo.node_count("Ingredient") == 14
        assert seeded_repo.node_count("Supplier") == 4
        assert seeded_repo.node_count("Category") == 4
        assert seeded_repo.node_count("Region") == 2
        assert seeded_repo.node_count("Employee") == 3

    def test_bom_relationships_created(self, seeded_repo: OntologyRepository) -> None:
        # 剁椒鱼头 has 6 ingredients
        rels = seeded_repo.get_relationships("Dish", "dish-djyt", rel_type="USES_INGREDIENT", direction="out")
        assert len(rels) == 6

        # 小炒黄牛肉 has 4 ingredients
        rels = seeded_repo.get_relationships("Dish", "dish-xchnr", rel_type="USES_INGREDIENT", direction="out")
        assert len(rels) == 4

        # 酸菜鱼 has 5 ingredients
        rels = seeded_repo.get_relationships("Dish", "dish-scy", rel_type="USES_INGREDIENT", direction="out")
        assert len(rels) == 5

    def test_store_serves_dishes(self, seeded_repo: OntologyRepository) -> None:
        rels = seeded_repo.get_relationships("Store", "store-001", rel_type="SERVES", direction="out")
        assert len(rels) == 3  # All 3 dishes

    def test_ingredient_supplied_by(self, seeded_repo: OntologyRepository) -> None:
        rels = seeded_repo.get_relationships("Ingredient", "ing-luyu", rel_type="SUPPLIED_BY", direction="out")
        assert len(rels) == 1
        assert rels[0]["to_node_id"] == "sup-fish"

    def test_employee_works_at_store(self, seeded_repo: OntologyRepository) -> None:
        rels = seeded_repo.get_relationships("Employee", "emp-001", rel_type="WORKS_AT", direction="out")
        assert len(rels) == 1
        assert rels[0]["to_node_id"] == "store-001"
        assert rels[0]["properties"]["role"] == "head_chef"


# ═══════════════════════════════════════════════════════════
# 5. CDC Sync Tests
# ═══════════════════════════════════════════════════════════


class TestCDCSync:
    def test_register_table(self, sync: PGToNeo4jSync) -> None:
        status = sync.get_sync_status()
        assert "dishes" in status["registered_tables"]
        assert "ingredients" in status["registered_tables"]

    def test_insert_sync(self, sync: PGToNeo4jSync) -> None:
        """Simulate PG INSERT → Neo4j node creation."""
        result = sync.process_change(
            table="dishes",
            operation="INSERT",
            old_data=None,
            new_data={
                "id": "dish-new",
                "name": "毛氏红烧肉",
                "price_fen": 8800,
                "tenant_id": "tenant-001",
            },
        )
        assert result["ok"] is True
        assert result["status"] == "synced"

        # Verify node was created
        node = sync.repo.get_node("Dish", "dish-new")
        assert node["ok"] is True
        assert node["node"]["properties"]["name"] == "毛氏红烧肉"

    def test_update_sync(self, sync: PGToNeo4jSync) -> None:
        """Simulate PG UPDATE → Neo4j node update."""
        result = sync.process_change(
            table="dishes",
            operation="UPDATE",
            old_data={"id": "dish-djyt", "price_fen": 12800},
            new_data={"id": "dish-djyt", "name": "剁椒鱼头", "price_fen": 13800, "tenant_id": "tenant-001"},
        )
        assert result["ok"] is True

        # Verify price was updated
        node = sync.repo.get_node("Dish", "dish-djyt")
        assert node["ok"] is True
        assert node["node"]["properties"]["price_fen"] == 13800

    def test_delete_sync(self, sync: PGToNeo4jSync) -> None:
        """Simulate PG DELETE → Neo4j node deletion."""
        # First insert a node to delete
        sync.process_change(
            table="dishes",
            operation="INSERT",
            old_data=None,
            new_data={
                "id": "dish-temp",
                "name": "临时菜",
                "price_fen": 1000,
                "tenant_id": "tenant-001",
            },
        )

        result = sync.process_change(
            table="dishes",
            operation="DELETE",
            old_data={"id": "dish-temp"},
            new_data=None,
        )
        assert result["ok"] is True

        # Verify deletion
        node = sync.repo.get_node("Dish", "dish-temp")
        assert node["ok"] is False

    def test_batch_sync(self, sync: PGToNeo4jSync) -> None:
        changes = [
            {
                "table": "ingredients",
                "operation": "INSERT",
                "new_data": {
                    "id": "ing-new1",
                    "name": "香菜",
                    "unit": "kg",
                    "price_per_kg_fen": 600,
                    "tenant_id": "tenant-001",
                },
            },
            {
                "table": "ingredients",
                "operation": "INSERT",
                "new_data": {
                    "id": "ing-new2",
                    "name": "芹菜",
                    "unit": "kg",
                    "price_per_kg_fen": 500,
                    "tenant_id": "tenant-001",
                },
            },
        ]
        result = sync.sync_batch(changes)
        assert result["ok"] is True
        assert result["synced"] == 2
        assert result["failed"] == 0

    def test_sync_unregistered_table(self, sync: PGToNeo4jSync) -> None:
        result = sync.process_change(
            table="unknown_table",
            operation="INSERT",
            old_data=None,
            new_data={"id": "x"},
        )
        assert result["ok"] is False

    def test_sync_status(self, sync: PGToNeo4jSync) -> None:
        sync.process_change(
            table="dishes",
            operation="INSERT",
            old_data=None,
            new_data={
                "id": "dish-status-test",
                "name": "测试菜",
                "price_fen": 1000,
                "tenant_id": "tenant-001",
            },
        )
        status = sync.get_sync_status()
        assert status["total_synced"] >= 1
        assert status["last_sync_at"] is not None

    def test_sync_lag(self, sync: PGToNeo4jSync) -> None:
        sync.process_change(
            table="dishes",
            operation="INSERT",
            old_data=None,
            new_data={
                "id": "dish-lag-test",
                "name": "延迟测试",
                "price_fen": 1000,
                "tenant_id": "tenant-001",
            },
        )
        lag = sync.get_sync_lag()
        assert lag["ok"] is True
        assert lag["lag_seconds"] < 5.0  # Within target
        assert lag["within_target"] is True

    def test_rebuild_full(self, sync: PGToNeo4jSync) -> None:
        result = sync.rebuild_full("dishes")
        assert result["ok"] is True
        assert result["node_label"] == "Dish"


# ═══════════════════════════════════════════════════════════
# 6. BOM Cost Calculation Tests
# ═══════════════════════════════════════════════════════════


class TestCostTruth:
    def test_calculate_duojiao_yutou_cost(self, cost_engine: CostTruthEngine) -> None:
        """剁椒鱼头 full BOM expansion test.

        BOM:
        - 鲈鱼 1.2kg × 38元/kg ÷ 0.65出成率 = 70.15元
        - 剁椒 200g × 24元/kg ÷ 0.95 = 5.05元
        - 姜 50g × 12元/kg ÷ 0.90 = 0.67元
        - 蒜 30g × 16元/kg ÷ 0.90 = 0.53元
        - 豆豉 20g × 30元/kg ÷ 1.0 = 0.60元
        - 葱花 30g × 8元/kg ÷ 0.85 = 0.28元
        Total material ≈ 77.28元
        + processing 3元 + energy 0.8元 = ~81元
        Selling 128元, margin ≈ 37%
        """
        result = cost_engine.calculate_dish_cost("dish-djyt")
        assert result["ok"] is True
        assert result["dish_name"] == "剁椒鱼头"

        # Should have 6 BOM entries
        assert len(result["bom_entries"]) == 6

        # Material cost should be substantial (all in fen)
        material_cost = result["total_material_cost_fen"]
        assert material_cost > 5000  # > 50元
        assert material_cost < 12000  # < 120元

        # Total cost includes processing + energy
        total = result["total_cost_fen"]
        assert total > material_cost

        # Margin should be reasonable
        margin = result["margin_rate"]
        assert 0.2 < margin < 0.7

        # vs_selling_price
        assert result["vs_selling_price"]["selling_price_fen"] == 12800
        assert result["vs_selling_price"]["profit_fen"] > 0

    def test_calculate_xiaocha_huangniurou_cost(self, cost_engine: CostTruthEngine) -> None:
        """小炒黄牛肉 cost test."""
        result = cost_engine.calculate_dish_cost("dish-xchnr")
        assert result["ok"] is True
        assert len(result["bom_entries"]) == 4

        # 黄牛肉 is the primary cost driver (300g × 85元/kg / 0.8)
        bom = {e["ingredient_name"]: e for e in result["bom_entries"]}
        assert "黄牛肉" in bom
        assert bom["黄牛肉"]["cost_fen"] > bom["辣椒"]["cost_fen"]

    def test_calculate_suancaiyu_cost(self, cost_engine: CostTruthEngine) -> None:
        """酸菜鱼 cost test."""
        result = cost_engine.calculate_dish_cost("dish-scy")
        assert result["ok"] is True
        assert len(result["bom_entries"]) == 5
        assert result["margin_rate"] > 0

    def test_dish_not_found(self, cost_engine: CostTruthEngine) -> None:
        result = cost_engine.calculate_dish_cost("nonexistent")
        assert result["ok"] is False

    def test_calculate_order_cost(
        self, cost_engine: CostTruthEngine, seeded_repo: OntologyRepository
    ) -> None:
        """Order cost = sum of dish costs × quantities."""
        # Create an order
        seeded_repo.create_node("Order", {
            "id": "order-001",
            "tenant_id": "tenant-001",
            "store_id": "store-001",
            "total_fen": 27400,  # 剁椒鱼头128 + 小炒黄牛肉68 + 酸菜鱼78 = 274元
        })
        seeded_repo.create_relationship(
            "Order", "order-001", "CONTAINS", "Dish", "dish-djyt",
            {"quantity": 1, "price_fen": 12800},
        )
        seeded_repo.create_relationship(
            "Order", "order-001", "CONTAINS", "Dish", "dish-xchnr",
            {"quantity": 1, "price_fen": 6800},
        )
        seeded_repo.create_relationship(
            "Order", "order-001", "CONTAINS", "Dish", "dish-scy",
            {"quantity": 1, "price_fen": 7800},
        )

        result = cost_engine.calculate_order_cost("order-001")
        assert result["ok"] is True
        assert len(result["items"]) == 3
        assert result["total_cost_fen"] > 0
        assert result["profit_fen"] > 0
        assert 0.2 < result["margin_rate"] < 0.8

    def test_store_daily_cost(self, cost_engine: CostTruthEngine) -> None:
        result = cost_engine.calculate_store_daily_cost("store-001", "2026-03-27")
        assert result["ok"] is True
        assert result["food_cost_fen"] > 0
        assert result["waste_cost_fen"] > 0
        assert result["overhead_cost_fen"] > 0
        assert result["daily_margin_rate"] > 0
        assert len(result["dish_costs"]) == 3

    def test_cost_trend(self, cost_engine: CostTruthEngine) -> None:
        trend = cost_engine.get_cost_trend("dish-djyt", days=7)
        assert len(trend) == 8  # 7 historical + today
        # Costs should vary due to ingredient price changes
        costs = [t["total_cost_fen"] for t in trend]
        assert all(c > 0 for c in costs)

    def test_detect_cost_anomaly(self, cost_engine: CostTruthEngine) -> None:
        """Should detect 鲈鱼 price spike (+20%) and 酸菜 (+40%)."""
        anomalies = cost_engine.detect_cost_anomaly("store-001", "2026-03-27")
        assert len(anomalies) > 0

        # Should find ingredient price spikes
        spike_anomalies = [a for a in anomalies if a["type"] == "cost_spike"]
        assert len(spike_anomalies) > 0

        # 酸菜 (+40%) should be detected
        ingredient_names = [a["ingredient_name"] for a in spike_anomalies]
        assert "酸菜" in ingredient_names

        # 鲈鱼 (+20%) should be detected
        assert "鲈鱼" in ingredient_names

    def test_simulate_luyu_price_increase(self, cost_engine: CostTruthEngine) -> None:
        """鲈鱼涨价20% → 哪些菜受影响？

        鲈鱼 current: 38元/kg → new: 45.6元/kg
        Affected: 剁椒鱼头 (uses 1.2kg)
        """
        new_price = int(3800 * 1.2)  # 20% increase
        result = cost_engine.simulate_price_change("ing-luyu", new_price)

        assert result["ok"] is True
        assert result["ingredient_name"] == "鲈鱼"
        assert result["price_change_pct"] == pytest.approx(20.0, abs=0.1)
        assert result["total_affected"] >= 1

        # 剁椒鱼头 should be affected
        affected_names = [d["dish_name"] for d in result["affected_dishes"]]
        assert "剁椒鱼头" in affected_names

        # Check margin impact
        djyt = [d for d in result["affected_dishes"] if d["dish_name"] == "剁椒鱼头"][0]
        assert djyt["cost_change_fen"] > 0
        assert djyt["new_margin"] < djyt["old_margin"]

    def test_simulate_suancai_price_increase(self, cost_engine: CostTruthEngine) -> None:
        """酸菜涨价 → 酸菜鱼受影响。"""
        new_price = int(1800 * 1.4)  # 40% increase
        result = cost_engine.simulate_price_change("ing-suancai", new_price)
        assert result["ok"] is True

        affected_names = [d["dish_name"] for d in result["affected_dishes"]]
        assert "酸菜鱼" in affected_names

    def test_top_cost_drivers(self, cost_engine: CostTruthEngine) -> None:
        drivers = cost_engine.get_top_cost_drivers("store-001", top_n=5)
        assert len(drivers) > 0
        assert drivers[0]["rank"] == 1
        assert drivers[0]["daily_cost_fen"] > 0

        # 鲈鱼 or 黄牛肉 should be top drivers (high price × high usage)
        top_names = [d["ingredient_name"] for d in drivers[:3]]
        assert any(name in top_names for name in ["鲈鱼", "黄牛肉", "草鱼"])


# ═══════════════════════════════════════════════════════════
# 7. Causal Reasoning Tests
# ═══════════════════════════════════════════════════════════


class TestCausalReasoning:
    def test_trace_cause_margin_decline(self, causal_engine: CausalReasoningEngine) -> None:
        """酸菜鱼毛利下降 → should find ingredient price increase as cause."""
        chain = causal_engine.trace_cause("Dish", "dish-scy", "margin", "decline")
        assert len(chain) > 0

        # Should find ingredient cost change (酸菜 +40%)
        patterns = [c["pattern"] for c in chain]
        assert "ingredient_price_up" in patterns

        # Evidence should mention 酸菜
        cost_cause = [c for c in chain if c["pattern"] == "ingredient_price_up"][0]
        assert "酸菜" in cost_cause["evidence"]
        assert cost_cause["confidence"] > 0.5

    def test_trace_cause_with_discount(self, causal_engine: CausalReasoningEngine) -> None:
        """酸菜鱼 has discount_rate=15%, should detect discount excess."""
        chain = causal_engine.trace_cause("Dish", "dish-scy", "margin", "decline")
        patterns = [c["pattern"] for c in chain]
        assert "discount_excess" in patterns

    def test_find_root_cause_store(self, causal_engine: CausalReasoningEngine) -> None:
        """Store-level root cause analysis."""
        result = causal_engine.find_root_cause("store-001", "margin", "last_week")
        assert result["ok"] is True
        assert result["store_id"] == "store-001"
        assert len(result["root_causes"]) > 0

        # Root causes should be sorted by confidence
        confidences = [c["confidence"] for c in result["root_causes"]]
        assert confidences == sorted(confidences, reverse=True)

    def test_predict_impact(self, causal_engine: CausalReasoningEngine) -> None:
        """If 鲈鱼 price goes up 20%, predict impact on dishes."""
        cause = {
            "type": "ingredient_price_change",
            "entity_id": "ing-luyu",
            "change_pct": 20.0,
        }
        affected = [
            {"entity_type": "Dish", "entity_id": "dish-djyt"},
        ]

        result = causal_engine.predict_impact(cause, affected)
        assert result["ok"] is True
        assert result["total_affected"] >= 1
        assert result["impacts"][0]["entity_name"] == "剁椒鱼头"

    def test_suggest_actions(self, causal_engine: CausalReasoningEngine) -> None:
        root_cause = {
            "pattern": "ingredient_price_up",
            "cause": "食材价格上涨",
            "confidence": 0.85,
        }
        actions = causal_engine.suggest_actions(root_cause)
        assert len(actions) > 0
        assert any(a["urgency"] == "high" for a in actions)

    def test_suggest_actions_seasonal(self, causal_engine: CausalReasoningEngine) -> None:
        root_cause = {
            "pattern": "seasonal_shortage",
            "cause": "季节性短缺",
            "confidence": 0.80,
        }
        actions = causal_engine.suggest_actions(root_cause)
        assert len(actions) > 0
        assert any("储备" in a["description"] for a in actions)

    def test_get_causal_graph(self, causal_engine: CausalReasoningEngine) -> None:
        result = causal_engine.get_causal_graph("Dish", "dish-scy", depth=2)
        assert result["ok"] is True
        assert result["node_count"] > 0
        # Should include ingredient nodes connected via USES_INGREDIENT
        assert result["edge_count"] > 0


# ═══════════════════════════════════════════════════════════
# 8. Multi-Factor Attribution Tests
# ═══════════════════════════════════════════════════════════


class TestMultiFactorAttribution:
    def test_analyze_metric_change(self, reasoning_engine: ReasoningEngine) -> None:
        """Decompose store margin change into contributing factors."""
        result = reasoning_engine.analyze_metric_change(
            "store-001", "margin", "上周", "本周"
        )
        assert result["ok"] is True
        assert result["metric"] == "margin"
        assert len(result["factors"]) > 0
        assert result["total_change_pct"] != 0  # store-001 has margin decline

        # Should have a top factor
        assert result["top_factor"] is not None

    def test_multi_factor_attribution(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.multi_factor_attribution(
            store_id="store-001",
            target_metric="margin",
            candidate_factors=["food_cost", "discount_rate", "waste_rate"],
            period="last_week",
        )
        assert result["ok"] is True
        assert len(result["attributions"]) == 3
        assert result["primary_driver"] is not None

        # Each attribution should have required fields
        for attr in result["attributions"]:
            assert "factor" in attr
            assert "contribution_pct" in attr
            assert "confidence" in attr
            assert "direction" in attr

    def test_attribution_sorted_by_contribution(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.multi_factor_attribution(
            store_id="store-001",
            target_metric="margin",
            candidate_factors=["food_cost", "discount_rate", "waste_rate", "labor_cost"],
        )
        contributions = [abs(a["contribution_pct"]) for a in result["attributions"]]
        assert contributions == sorted(contributions, reverse=True)


# ═══════════════════════════════════════════════════════════
# 9. Store Comparison Tests
# ═══════════════════════════════════════════════════════════


class TestStoreComparison:
    def test_compare_two_stores(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.compare_stores(
            store_ids=["store-001", "store-002"],
            metrics=["margin"],
        )
        assert result["ok"] is True
        assert len(result["comparisons"]) == 1

        comparison = result["comparisons"][0]
        assert comparison["metric"] == "margin"
        assert len(comparison["rankings"]) == 2
        assert comparison["best"] is not None
        assert comparison["worst"] is not None
        assert comparison["explanation"] != ""

    def test_compare_stores_multiple_metrics(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.compare_stores(
            store_ids=["store-001", "store-002"],
            metrics=["margin", "waste_rate"],
        )
        assert result["ok"] is True
        assert len(result["comparisons"]) == 2

    def test_compare_stores_insufficient(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.compare_stores(
            store_ids=["store-001"],
            metrics=["margin"],
        )
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════
# 10. Auto-Insight Generation Tests
# ═══════════════════════════════════════════════════════════


class TestAutoInsight:
    def test_generate_insights_store001(self, reasoning_engine: ReasoningEngine) -> None:
        """Store-001 has: margin decline, traffic decline, high waste, high discount."""
        result = reasoning_engine.generate_insight("store-001", "last_week")
        assert result["ok"] is True
        assert result["store_name"] == "尝在一起·五一广场店"
        assert len(result["insights"]) > 0
        assert len(result["insights"]) <= 5

        types = [i["type"] for i in result["insights"]]
        # Should detect margin change (58% vs 62%)
        assert "margin_change" in types
        # Should detect traffic decline (-8%)
        assert "traffic_change" in types
        # Should detect high waste (6.5%)
        assert "waste_alert" in types

    def test_generate_insights_store002(self, reasoning_engine: ReasoningEngine) -> None:
        """Store-002 is healthier: should have fewer/lower priority insights."""
        result = reasoning_engine.generate_insight("store-002", "last_week")
        assert result["ok"] is True
        # Store-002 has less issues
        high_priority = [i for i in result["insights"] if i["priority"] == "high"]
        # Store-002 still has cost anomaly from ingredient prices
        assert len(result["insights"]) > 0

    def test_insights_sorted_by_priority(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.generate_insight("store-001")
        priorities = [i["priority"] for i in result["insights"]]
        priority_order = {"high": 0, "medium": 1, "low": 2}
        numeric = [priority_order.get(p, 2) for p in priorities]
        assert numeric == sorted(numeric)

    def test_insights_have_actions(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.generate_insight("store-001")
        for insight in result["insights"]:
            assert "action" in insight
            assert len(insight["action"]) > 0

    def test_ingredient_price_insight(self, reasoning_engine: ReasoningEngine) -> None:
        """Should detect 酸菜+40% and 鲈鱼+20% as cost anomaly."""
        result = reasoning_engine.generate_insight("store-001")
        cost_insights = [i for i in result["insights"] if i["type"] == "cost_anomaly"]
        assert len(cost_insights) > 0
        assert "酸菜" in cost_insights[0]["description"] or "鲈鱼" in cost_insights[0]["description"]


# ═══════════════════════════════════════════════════════════
# 11. "Why" Question Answering Tests
# ═══════════════════════════════════════════════════════════


class TestWhyQA:
    def test_answer_why_revenue(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.answer_why(
            "为什么上周营收下降了？", store_id="store-001"
        )
        assert result["ok"] is True
        assert result["metric"] == "revenue"
        assert result["direction"] == "decline"
        assert len(result["answer"]) > 0
        assert result["analysis"]["ok"] is True

    def test_answer_why_margin(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.answer_why(
            "为什么毛利率降低了？", store_id="store-001"
        )
        assert result["ok"] is True
        assert result["metric"] == "margin"

    def test_answer_why_traffic(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.answer_why(
            "客流量为什么减少了？", store_id="store-001"
        )
        assert result["ok"] is True
        assert result["metric"] == "traffic"

    def test_answer_why_unknown_metric(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.answer_why("为什么天气不好？")
        assert result["ok"] is False

    def test_answer_why_no_store(self, reasoning_engine: ReasoningEngine) -> None:
        """Should pick first available store if none specified."""
        result = reasoning_engine.answer_why("为什么毛利下降了？")
        assert result["ok"] is True
        assert result["store_id"] is not None


# ═══════════════════════════════════════════════════════════
# 12. Trend Prediction Tests
# ═══════════════════════════════════════════════════════════


class TestTrendPrediction:
    def test_predict_margin_trend(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.predict_trend("store-001", "margin", days_ahead=7)
        assert result["ok"] is True
        assert len(result["predictions"]) == 7

        for pred in result["predictions"]:
            assert "date" in pred
            assert "predicted_value" in pred
            assert 0 < pred["confidence"] <= 1.0

    def test_prediction_confidence_decays(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.predict_trend("store-001", "margin", days_ahead=7)
        confidences = [p["confidence"] for p in result["predictions"]]
        # Later predictions should have lower confidence
        assert confidences[0] > confidences[-1]

    def test_predict_store_not_found(self, reasoning_engine: ReasoningEngine) -> None:
        result = reasoning_engine.predict_trend("nonexistent", "margin")
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════
# 13. Integration Tests
# ═══════════════════════════════════════════════════════════


class TestIntegration:
    def test_full_chain_dish_to_supplier(self, seeded_repo: OntologyRepository) -> None:
        """Trace: 剁椒鱼头 → 鲈鱼 → 湘江水产."""
        # Dish → Ingredient
        bom_rels = seeded_repo.get_relationships(
            "Dish", "dish-djyt", rel_type="USES_INGREDIENT", direction="out"
        )
        luyu_rel = [r for r in bom_rels if r["to_node_id"] == "ing-luyu"]
        assert len(luyu_rel) == 1
        assert luyu_rel[0]["properties"]["quantity_g"] == 1200.0

        # Ingredient → Supplier
        sup_rels = seeded_repo.get_relationships(
            "Ingredient", "ing-luyu", rel_type="SUPPLIED_BY", direction="out"
        )
        assert len(sup_rels) == 1
        assert sup_rels[0]["to_node_id"] == "sup-fish"

        # Verify supplier
        supplier = seeded_repo.get_node("Supplier", "sup-fish")
        assert supplier["ok"] is True
        assert supplier["node"]["properties"]["name"] == "湘江水产"

    def test_cost_then_reasoning_chain(
        self,
        cost_engine: CostTruthEngine,
        causal_engine: CausalReasoningEngine,
        seeded_repo: OntologyRepository,
    ) -> None:
        """
        1. Calculate dish cost
        2. If margin low, trace cause
        3. Get suggested actions
        """
        # Step 1: Cost
        cost = cost_engine.calculate_dish_cost("dish-scy")
        assert cost["ok"] is True

        # Step 2: Trace cause
        chain = causal_engine.trace_cause("Dish", "dish-scy", "margin", "decline")
        assert len(chain) > 0

        # Step 3: Actions
        top_cause = chain[0]
        actions = causal_engine.suggest_actions(top_cause)
        assert len(actions) > 0

    def test_sync_then_cost_calculation(
        self, sync: PGToNeo4jSync, cost_engine: CostTruthEngine
    ) -> None:
        """Sync a new dish, then calculate its cost."""
        # Create dish
        sync.process_change(
            table="dishes",
            operation="INSERT",
            old_data=None,
            new_data={
                "id": "dish-int-test",
                "name": "农家小炒肉",
                "price_fen": 5800,
                "tenant_id": "tenant-001",
            },
        )

        # Add BOM via repo (simulating BOM sync)
        sync.repo.create_relationship(
            "Dish", "dish-int-test", "USES_INGREDIENT", "Ingredient", "ing-huangniurou",
            {"quantity_g": 250.0, "unit": "g", "yield_rate": 0.85},
        )
        sync.repo.create_relationship(
            "Dish", "dish-int-test", "USES_INGREDIENT", "Ingredient", "ing-lajiao",
            {"quantity_g": 80.0, "unit": "g", "yield_rate": 0.90},
        )

        # Calculate cost
        result = cost_engine.calculate_dish_cost("dish-int-test")
        assert result["ok"] is True
        assert result["dish_name"] == "农家小炒肉"
        assert len(result["bom_entries"]) == 2
        assert result["total_cost_fen"] > 0
        assert result["margin_rate"] > 0

    def test_store_full_analysis_pipeline(
        self,
        cost_engine: CostTruthEngine,
        reasoning_engine: ReasoningEngine,
        causal_engine: CausalReasoningEngine,
    ) -> None:
        """Full analysis pipeline for a store:
        1. Daily cost
        2. Anomaly detection
        3. Root cause analysis
        4. Generate insights
        5. Answer "why" question
        """
        store_id = "store-001"
        date = "2026-03-27"

        # 1. Daily cost
        daily_cost = cost_engine.calculate_store_daily_cost(store_id, date)
        assert daily_cost["ok"] is True
        assert daily_cost["food_cost_fen"] > 0

        # 2. Anomalies
        anomalies = cost_engine.detect_cost_anomaly(store_id, date)
        assert len(anomalies) > 0

        # 3. Root cause
        root_cause = causal_engine.find_root_cause(store_id, "margin", "last_week")
        assert root_cause["ok"] is True
        assert len(root_cause["root_causes"]) > 0

        # 4. Insights
        insights = reasoning_engine.generate_insight(store_id)
        assert insights["ok"] is True
        assert len(insights["insights"]) > 0

        # 5. Why question
        answer = reasoning_engine.answer_why("为什么毛利率下降了？", store_id=store_id)
        assert answer["ok"] is True
        assert len(answer["answer"]) > 0
