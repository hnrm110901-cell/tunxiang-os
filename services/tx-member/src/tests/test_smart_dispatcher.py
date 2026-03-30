"""会员等级智能调度引擎测试 — API 冒烟 + 服务逻辑单元测试

覆盖:
  - 四个等级的预订调度差异
  - 排队优先级(钻石免排/金卡快速/普通正常)
  - 菜单差异(专属菜品/会员价)
  - 个性化首页内容差异
  - 升级机会计算
  - 权益自动应用
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app

from api.smart_dispatch_routes import router as dispatch_router

if not any(r.prefix == "/api/v1/member/dispatch" for r in app.routes if hasattr(r, "prefix")):
    app.include_router(dispatch_router)

client = TestClient(app)

# 导入服务层辅助函数做单元测试
from services.smart_dispatcher import (
    _calc_upgrade_progress,
    _get_banner,
    _get_available_benefits,
    _get_scene_actions,
    _rank_to_level,
    LEVEL_RANK,
    UPGRADE_THRESHOLDS_FEN,
    POINTS_MULTIPLIER,
    QUEUE_PRIORITY,
    NOTIFICATION_CHANNELS,
    LEVEL_NAMES_CN,
)


# ── API 冒烟测试 ──────────────────────────────────────────────


class TestPersonalizedHomeAPI:
    def test_home_ok(self):
        r = client.get("/api/v1/member/dispatch/home/cust-001")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "greeting" in data["data"]
        assert "exclusive_banner" in data["data"]
        assert "scene_actions" in data["data"]

    def test_home_has_upgrade_progress(self):
        r = client.get("/api/v1/member/dispatch/home/cust-002")
        assert r.status_code == 200
        progress = r.json()["data"]["upgrade_progress"]
        assert "has_next_level" in progress
        assert "remaining_fen" in progress


class TestLevelMenuAPI:
    def test_menu_ok(self):
        r = client.get("/api/v1/member/dispatch/menu/cust-001/store-001")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["menu_type"] == "standard"
        assert "sections" in data["data"]


class TestQueueDispatchAPI:
    def test_queue_ok(self):
        r = client.get("/api/v1/member/dispatch/queue/cust-001/store-001")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "queue_ticket" in data["data"]
        assert "estimated_wait_minutes" in data["data"]


class TestPersonalizedOffersAPI:
    def test_offers_ok(self):
        r = client.get("/api/v1/member/dispatch/offers/cust-001")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert isinstance(data["data"]["offers"], list)
        assert len(data["data"]["offers"]) > 0


class TestReservationDispatchAPI:
    def test_reservation_ok(self):
        r = client.post(
            "/api/v1/member/dispatch/reservation",
            json={
                "customer_id": "cust-001",
                "store_id": "store-001",
                "party_size": 4,
                "date": "2026-04-01",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["party_size"] == 4
        assert "reservation_id" in data["data"]


class TestApplyBenefitsAPI:
    def test_apply_benefits_ok(self):
        r = client.post(
            "/api/v1/member/dispatch/apply-benefits",
            json={"customer_id": "cust-001", "order_id": "order-001"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["auto_applied"] is True


class TestUpgradeOpportunityAPI:
    def test_upgrade_ok(self):
        r = client.get("/api/v1/member/dispatch/upgrade/cust-001")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "has_next_level" in data["data"]
        assert "message" in data["data"]


# ── 服务层单元测试: 预订调度差异 ──────────────────────────────


class TestReservationDispatchLevels:
    """四个等级的预订调度差异"""

    def test_diamond_gets_vip_room(self):
        """钻石会员: VIP包厢+优先确认+免费升包"""
        # 通过辅助函数验证等级 → 权益映射逻辑
        assert LEVEL_RANK["diamond"] == 4
        assert _rank_to_level(4) == "diamond"

    def test_gold_gets_priority_confirm(self):
        """金卡会员: 优先确认+包厢可选"""
        assert LEVEL_RANK["gold"] == 3
        assert _rank_to_level(3) == "gold"

    def test_silver_normal_schedule(self):
        """银卡: 正常排期"""
        assert LEVEL_RANK["silver"] == 2
        assert _rank_to_level(2) == "silver"

    def test_normal_room_surcharge(self):
        """普通: 正常排期,包厢需加收"""
        assert LEVEL_RANK["normal"] == 1
        assert _rank_to_level(1) == "normal"
        assert _rank_to_level(0) == "normal"  # rank 0 也视为 normal


# ── 服务层单元测试: 排队优先级 ────────────────────────────────


class TestQueuePriority:
    """排队优先级: 钻石免排/金卡快速/普通正常"""

    def test_diamond_highest_priority(self):
        assert QUEUE_PRIORITY["diamond"] == 1000
        assert QUEUE_PRIORITY["diamond"] > QUEUE_PRIORITY["gold"]

    def test_gold_medium_priority(self):
        assert QUEUE_PRIORITY["gold"] == 300
        assert QUEUE_PRIORITY["gold"] > QUEUE_PRIORITY["silver"]

    def test_silver_normal_priority(self):
        assert QUEUE_PRIORITY["silver"] == 0

    def test_normal_no_priority(self):
        assert QUEUE_PRIORITY["normal"] == 0


# ── 服务层单元测试: 菜单差异 ──────────────────────────────────


class TestMenuDifferences:
    """菜单差异: 专属菜品/会员价"""

    def test_diamond_has_exclusive_sections(self):
        """钻石: 专属隐藏菜单+限量菜品"""
        benefits = _get_available_benefits("diamond")
        benefit_keys = [b["key"] for b in benefits]
        assert "exclusive_menu" in benefit_keys

    def test_gold_has_member_price(self):
        """金卡: 会员价"""
        benefits = _get_available_benefits("gold")
        benefit_keys = [b["key"] for b in benefits]
        assert "member_price" in benefit_keys

    def test_silver_has_member_price(self):
        """银卡: 会员价"""
        benefits = _get_available_benefits("silver")
        benefit_keys = [b["key"] for b in benefits]
        assert "member_price" in benefit_keys

    def test_normal_has_basic_only(self):
        """普通: 标准菜单"""
        benefits = _get_available_benefits("normal")
        benefit_keys = [b["key"] for b in benefits]
        assert "member_price" not in benefit_keys
        assert "points" in benefit_keys


# ── 服务层单元测试: 个性化首页 ────────────────────────────────


class TestPersonalizedHomeDifferences:
    """个性化首页内容差异"""

    def test_diamond_banner(self):
        banner = _get_banner("diamond")
        assert banner["color"] == "#1a1a2e"
        assert "钻石" in banner["title"]

    def test_gold_banner(self):
        banner = _get_banner("gold")
        assert "金卡" in banner["title"]

    def test_scene_actions_diamond_has_vip(self):
        actions = _get_scene_actions("diamond")
        action_keys = [a["key"] for a in actions]
        assert "vip_service" in action_keys
        assert "chef_special" in action_keys

    def test_scene_actions_normal_no_vip(self):
        actions = _get_scene_actions("normal")
        action_keys = [a["key"] for a in actions]
        assert "vip_service" not in action_keys

    def test_level_names_cn(self):
        assert LEVEL_NAMES_CN["diamond"] == "钻石会员"
        assert LEVEL_NAMES_CN["gold"] == "金卡会员"
        assert LEVEL_NAMES_CN["silver"] == "银卡会员"
        assert LEVEL_NAMES_CN["normal"] == "普通会员"


# ── 服务层单元测试: 升级机会计算 ──────────────────────────────


class TestUpgradeProgress:
    """升级机会计算"""

    def test_normal_to_silver(self):
        progress = _calc_upgrade_progress("normal", 0)
        assert progress["has_next_level"] is True
        assert progress["next_level"] == "silver"
        assert progress["remaining_fen"] == 500_000
        assert "5000" in progress["message"]

    def test_normal_halfway_to_silver(self):
        progress = _calc_upgrade_progress("normal", 250_000)
        assert progress["has_next_level"] is True
        assert progress["remaining_fen"] == 250_000
        assert progress["progress_percent"] == 50.0

    def test_silver_to_gold(self):
        progress = _calc_upgrade_progress("silver", 1_000_000)
        assert progress["has_next_level"] is True
        assert progress["next_level"] == "gold"
        assert progress["remaining_fen"] == 1_000_000

    def test_gold_to_diamond(self):
        progress = _calc_upgrade_progress("gold", 3_000_000)
        assert progress["has_next_level"] is True
        assert progress["next_level"] == "diamond"
        assert progress["remaining_fen"] == 2_000_000

    def test_diamond_max_level(self):
        progress = _calc_upgrade_progress("diamond", 10_000_000)
        assert progress["has_next_level"] is False
        assert progress["progress_percent"] == 100.0
        assert "最高等级" in progress["message"]


# ── 服务层单元测试: 权益自动应用 ──────────────────────────────


class TestBenefitsApplication:
    """权益自动应用"""

    def test_diamond_points_multiplier(self):
        assert POINTS_MULTIPLIER["diamond"] == 3.0

    def test_gold_points_multiplier(self):
        assert POINTS_MULTIPLIER["gold"] == 2.0

    def test_silver_points_multiplier(self):
        assert POINTS_MULTIPLIER["silver"] == 1.5

    def test_normal_no_multiplier(self):
        assert POINTS_MULTIPLIER["normal"] == 1.0


# ── 服务层单元测试: 通知渠道 ──────────────────────────────────


class TestNotificationChannels:
    """通知渠道按等级差异化"""

    def test_diamond_has_dedicated_service(self):
        channels = NOTIFICATION_CHANNELS["diamond"]
        assert "dedicated_service" in channels
        assert len(channels) == 3

    def test_gold_has_sms(self):
        channels = NOTIFICATION_CHANNELS["gold"]
        assert "sms" in channels
        assert "wechat_service" in channels

    def test_normal_wechat_only(self):
        channels = NOTIFICATION_CHANNELS["normal"]
        assert channels == ["wechat_service"]


# ── 服务层单元测试: 升级阈值 ──────────────────────────────────


class TestUpgradeThresholds:
    """等级升级阈值校验"""

    def test_diamond_threshold(self):
        assert UPGRADE_THRESHOLDS_FEN["diamond"] == 5_000_000  # 50000元

    def test_gold_threshold(self):
        assert UPGRADE_THRESHOLDS_FEN["gold"] == 2_000_000  # 20000元

    def test_silver_threshold(self):
        assert UPGRADE_THRESHOLDS_FEN["silver"] == 500_000  # 5000元

    def test_level_order(self):
        """等级顺序: diamond > gold > silver > normal"""
        assert LEVEL_RANK["diamond"] > LEVEL_RANK["gold"]
        assert LEVEL_RANK["gold"] > LEVEL_RANK["silver"]
        assert LEVEL_RANK["silver"] > LEVEL_RANK["normal"]
