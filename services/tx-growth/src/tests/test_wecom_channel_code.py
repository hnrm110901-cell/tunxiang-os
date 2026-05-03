"""
WC-1 渠道活码测试
测试：创建渠道活码 / 查询列表 / 扫码事件处理 / 群发任务创建
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.wecom_channel_code_routes import get_db, router

app = FastAPI()
app.include_router(router)
# Override get_db to return None — service falls back to in-memory mode
app.dependency_overrides[get_db] = lambda: None
client = TestClient(app)

# 测试用的 Header 常量
_TENANT_ID = "test-tenant-001"


# ─── Test 1: 创建渠道活码 ─────────────────────────────────────────────────────


class TestCreateChannelCode:
    """test_create_channel_code — 创建渠道活码成功"""

    def test_create_channel_code_returns_200(self):
        resp = client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={
                "merchant_code": "M001",
                "channel_name": "海报-店门口-2026Q2",
                "qrcode_url": "https://qyapi.weixin.qq.com/qr/test001",
                "auto_tags": ["新客", "扫码引流"],
                "auto_reply": "欢迎光临！回复1查看今日特价菜品。",
                "group_id": "grp-test-001",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["merchant_code"] == "M001"
        assert data["data"]["channel_name"] == "海报-店门口-2026Q2"
        assert data["data"]["auto_tags"] == ["新客", "扫码引流"]
        assert data["data"]["auto_reply"] == "欢迎光临！回复1查看今日特价菜品。"
        assert data["data"]["group_id"] == "grp-test-001"
        assert data["data"]["scan_count"] == 0
        assert data["data"]["is_active"] is True
        assert "id" in data["data"]

    def test_create_channel_code_minimal_fields(self):
        """仅必填字段创建渠道活码"""
        resp = client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={
                "merchant_code": "M002",
                "channel_name": "朋友圈广告",
                "qrcode_url": "https://qyapi.weixin.qq.com/qr/test002",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["auto_tags"] == []
        assert data["data"]["auto_reply"] == ""
        assert data["data"]["group_id"] is None

    def test_create_channel_code_missing_required_returns_422(self):
        """缺少必填字段时返回 422"""
        resp = client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={"merchant_code": "M003"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 422


# ─── Test 2: 查询渠道活码列表 ──────────────────────────────────────────────────


class TestListChannelCodes:
    """test_list_channel_codes — 查询渠道活码列表"""

    def setup_method(self):
        """清空并创建测试数据（通过 TestClient 先创建几条记录）"""
        # 先创建几条记录用于列表测试
        client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={
                "merchant_code": "M001",
                "channel_name": "渠道A",
                "qrcode_url": "https://qyapi.weixin.qq.com/qr/a",
                "auto_tags": ["tagA"],
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={
                "merchant_code": "M002",
                "channel_name": "渠道B",
                "qrcode_url": "https://qyapi.weixin.qq.com/qr/b",
                "auto_tags": ["tagB"],
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )

    def test_list_channel_codes_returns_200(self):
        resp = client.get(
            "/api/v1/growth/wecom/channel-codes",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "total" in data["data"]
        assert len(data["data"]["items"]) > 0

    def test_list_channel_codes_pagination(self):
        resp = client.get(
            "/api/v1/growth/wecom/channel-codes?page=1&size=10",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["page"] == 1
        assert data["data"]["size"] == 10
        assert len(data["data"]["items"]) <= 10

    def test_list_channel_codes_filter_by_merchant(self):
        resp = client.get(
            "/api/v1/growth/wecom/channel-codes?merchant_code=M001",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        data = resp.json()
        for item in data["data"]["items"]:
            assert item["merchant_code"] == "M001"

    def test_get_channel_code_detail(self):
        """获取渠道活码详情"""
        # 先创建一个，然后获取其 ID
        create_resp = client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={
                "merchant_code": "M003",
                "channel_name": "详情渠道",
                "qrcode_url": "https://qyapi.weixin.qq.com/qr/detail",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        channel_id = create_resp.json()["data"]["id"]

        resp = client.get(
            f"/api/v1/growth/wecom/channel-codes/{channel_id}",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["id"] == channel_id
        assert data["data"]["channel_name"] == "详情渠道"

    def test_get_channel_code_detail_not_found(self):
        """不存在的渠道活码返回 404"""
        resp = client.get(
            "/api/v1/growth/wecom/channel-codes/nonexistent-id",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 404


# ─── Test 3: 扫码事件处理 ─────────────────────────────────────────────────────


class TestHandleScan:
    """test_handle_scan — 扫码事件处理"""

    def test_handle_scan_returns_200(self):
        """处理扫码事件成功，返回动作列表"""
        # 先创建一个带自动动作的渠道活码
        create_resp = client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={
                "merchant_code": "M001",
                "channel_name": "扫码测试渠道",
                "qrcode_url": "https://qyapi.weixin.qq.com/qr/scan-test",
                "auto_tags": ["新客", "扫码引流"],
                "auto_reply": "欢迎光临！",
                "group_id": "grp-test",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        channel_id = create_resp.json()["data"]["id"]

        resp = client.post(
            f"/api/v1/growth/wecom/channel-codes/{channel_id}/handle-scan",
            json={"external_userid": "external-user-001"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["success"] is True
        # 服务中企微 API 调用会因缺少凭证而静默失败，但动作列表仍返回尝试的 action
        assert "actions" in data["data"]

    def test_handle_scan_increments_scan_count(self):
        """扫码后 scan_count 递增"""
        create_resp = client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={
                "merchant_code": "M001",
                "channel_name": "计数测试渠道",
                "qrcode_url": "https://qyapi.weixin.qq.com/qr/count-test",
                "auto_tags": ["新客"],
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        channel_id = create_resp.json()["data"]["id"]
        assert create_resp.json()["data"]["scan_count"] == 0

        # 扫码两次
        client.post(
            f"/api/v1/growth/wecom/channel-codes/{channel_id}/handle-scan",
            json={"external_userid": "user-001"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        client.post(
            f"/api/v1/growth/wecom/channel-codes/{channel_id}/handle-scan",
            json={"external_userid": "user-002"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )

        # 检查统计
        stats_resp = client.get(
            f"/api/v1/growth/wecom/channel-codes/{channel_id}/stats",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        stats = stats_resp.json()["data"]
        assert stats["total_scans"] == 2
        assert stats["unique_users"] == 2

    def test_handle_scan_channel_not_found(self):
        """不存在的渠道活码扫码返回 400"""
        resp = client.post(
            "/api/v1/growth/wecom/channel-codes/nonexistent-id/handle-scan",
            json={"external_userid": "external-user-001"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 400

    def test_get_channel_stats(self):
        """获取渠道扫码统计"""
        create_resp = client.post(
            "/api/v1/growth/wecom/channel-codes",
            json={
                "merchant_code": "M001",
                "channel_name": "统计测试渠道",
                "qrcode_url": "https://qyapi.weixin.qq.com/qr/stats-test",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        channel_id = create_resp.json()["data"]["id"]

        # 扫码一次
        client.post(
            f"/api/v1/growth/wecom/channel-codes/{channel_id}/handle-scan",
            json={"external_userid": "user-stats-1"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )

        stats_resp = client.get(
            f"/api/v1/growth/wecom/channel-codes/{channel_id}/stats",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert stats_resp.status_code == 200
        data = stats_resp.json()["data"]
        assert data["channel_name"] == "统计测试渠道"
        assert data["total_scans"] >= 1


# ─── Test 4: 群发任务创建（通过 wecom_scrm_agent_routes） ────────────────────


class TestMassSendTask:
    """test_mass_send_task — 群发任务创建"""

    def test_mass_send_text_returns_200(self):
        """创建文本群发任务成功"""
        from ..api.wecom_scrm_agent_routes import router as scrm_router

        app2 = FastAPI()
        app2.include_router(scrm_router)
        client2 = TestClient(app2)

        resp = client2.post(
            "/api/v1/growth/scrm-agent/mass-send",
            json={
                "group_ids": ["grp-001", "grp-002"],
                "content": {"type": "text", "text": {"content": "今日特价：清蒸鲈鱼仅售¥68"}},
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "task_id" in data["data"]
        assert data["data"]["group_count"] == 2
        assert data["data"]["status"] in ("pending", "sending")

    def test_mass_send_with_tag_filter(self):
        """创建带标签筛选的群发任务"""
        from ..api.wecom_scrm_agent_routes import router as scrm_router

        app2 = FastAPI()
        app2.include_router(scrm_router)
        client2 = TestClient(app2)

        resp = client2.post(
            "/api/v1/growth/scrm-agent/mass-send",
            json={
                "tag_filter": {"include": ["vip", "高频"]},
                "content": {"type": "text", "text": {"content": "VIP专享：满200减30"}},
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["tag_filter_applied"] is True

    def test_mass_send_scheduled(self):
        """创建定时群发任务"""
        from ..api.wecom_scrm_agent_routes import router as scrm_router

        app2 = FastAPI()
        app2.include_router(scrm_router)
        client2 = TestClient(app2)

        from datetime import datetime, timedelta

        future_time = (datetime.now() + timedelta(hours=2)).isoformat()

        resp = client2.post(
            "/api/v1/growth/scrm-agent/mass-send",
            json={
                "group_ids": ["grp-001"],
                "content": {"type": "text", "text": {"content": "定时消息测试"}},
                "send_at": future_time,
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["status"] == "scheduled"
        assert "send_at" in data["data"]

    def test_list_mass_tasks(self):
        """查询群发任务列表"""
        from ..api.wecom_scrm_agent_routes import router as scrm_router

        app2 = FastAPI()
        app2.include_router(scrm_router)
        client2 = TestClient(app2)

        # 先创建几个任务
        for i in range(3):
            client2.post(
                "/api/v1/growth/scrm-agent/mass-send",
                json={
                    "group_ids": [f"grp-{i}"],
                    "content": {"type": "text", "text": {"content": f"测试消息{i}"}},
                },
                headers={"X-Tenant-ID": _TENANT_ID},
            )

        resp = client2.get(
            "/api/v1/growth/scrm-agent/mass-tasks?page=1&size=10",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]["items"]) > 0
        assert data["data"]["total"] >= 3
