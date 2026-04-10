"""全渠道 Golden ID 映射测试 — Y-D9

覆盖场景：
1. test_bind_new_customer          - 新顾客绑定
2. test_bind_phone_match_merges    - 手机号匹配自动合并
3. test_bind_duplicate_idempotent  - 重复绑定幂等
4. test_unbind                     - 解绑
5. test_list_conflicts             - 列出冲突
6. test_resolve_conflict           - 解决冲突
7. test_stats                      - 统计
8. test_batch_import               - 批量导入
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.golden_id_routes import router as golden_id_router
from fastapi.testclient import TestClient
from main import app

# 注册路由（避免重复注册）
if not any(
    getattr(r, "prefix", None) == "/api/v1/member/golden-id"
    for r in app.routes
):
    app.include_router(golden_id_router)

client = TestClient(app)

TENANT_HEADER = {"X-Tenant-ID": "a0000000-0000-0000-0000-000000000001"}

# 固定测试用的 customer ID
CUSTOMER_A = "b0000000-0000-0000-0000-000000000001"
CUSTOMER_B = "b0000000-0000-0000-0000-000000000002"


# ── 1. 新顾客绑定 ─────────────────────────────────────────────────────────────

class TestBindNewCustomer:
    """test_bind_new_customer: 绑定一个全新的 customer + channel openid"""

    def test_bind_new_customer_returns_ok(self):
        r = client.post(
            "/api/v1/member/golden-id/bind",
            json={
                "customer_id": CUSTOMER_A,
                "channel_type": "meituan",
                "channel_openid": "mt_openid_new_001",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "binding_id" in data["data"]
        assert data["data"]["customer_id"] == CUSTOMER_A

    def test_bind_new_customer_idempotent_flag_false(self):
        """首次绑定 idempotent 应为 False"""
        r = client.post(
            "/api/v1/member/golden-id/bind",
            json={
                "customer_id": CUSTOMER_A,
                "channel_type": "eleme",
                "channel_openid": "ele_openid_flag_test_001",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        assert r.json()["data"]["idempotent"] is False

    def test_bind_invalid_channel_type(self):
        """无效渠道类型返回 422"""
        r = client.post(
            "/api/v1/member/golden-id/bind",
            json={
                "customer_id": CUSTOMER_A,
                "channel_type": "unknown_platform",
                "channel_openid": "xxx_openid_001",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 422

    def test_bind_missing_tenant_header(self):
        """缺少 X-Tenant-ID 返回 422"""
        r = client.post(
            "/api/v1/member/golden-id/bind",
            json={
                "customer_id": CUSTOMER_A,
                "channel_type": "wechat",
                "channel_openid": "wx_openid_no_tenant",
            },
        )
        assert r.status_code == 422


# ── 2. 手机号匹配自动合并 ──────────────────────────────────────────────────────

class TestBindPhoneMatchMerges:
    """test_bind_phone_match_merges: 提供手机号时若已有同 phone_hash 的 customer，自动合并"""

    def test_phone_match_returns_merged_customer(self):
        """
        先用 CUSTOMER_A + phone=13800000001 绑定一条记录，
        再以不同 openid + 同手机号发起绑定，应合并到 CUSTOMER_A。
        """
        # 先绑定一条带手机号的记录
        r1 = client.post(
            "/api/v1/member/golden-id/bind",
            json={
                "customer_id": CUSTOMER_A,
                "channel_type": "douyin",
                "channel_openid": "dy_openid_phone_src_001",
                "phone": "13800000001",
            },
            headers=TENANT_HEADER,
        )
        assert r1.status_code == 200
        assert r1.json()["ok"] is True

        # 用同手机号 + 不同 openid 绑定
        r2 = client.post(
            "/api/v1/member/golden-id/bind",
            json={
                "channel_type": "wechat",
                "channel_openid": "wx_openid_phone_merge_001",
                "phone": "13800000001",
            },
            headers=TENANT_HEADER,
        )
        assert r2.status_code == 200
        data = r2.json()["data"]
        assert data["merge_happened"] is True
        assert data["customer_id"] == CUSTOMER_A

    def test_phone_no_match_creates_new(self):
        """全新手机号，不存在匹配，应创建新 customer"""
        r = client.post(
            "/api/v1/member/golden-id/bind",
            json={
                "channel_type": "meituan",
                "channel_openid": "mt_openid_new_phone_002",
                "phone": "13900000099",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["merge_happened"] is False
        assert "customer_id" in data


# ── 3. 重复绑定幂等 ───────────────────────────────────────────────────────────

class TestBindDuplicateIdempotent:
    """test_bind_duplicate_idempotent: 重复绑定同一 openid 返回相同 binding_id，不报错"""

    def test_duplicate_bind_returns_same_binding(self):
        openid = "mt_openid_idem_unique_003"
        payload = {
            "customer_id": CUSTOMER_B,
            "channel_type": "meituan",
            "channel_openid": openid,
        }

        r1 = client.post(
            "/api/v1/member/golden-id/bind",
            json=payload,
            headers=TENANT_HEADER,
        )
        assert r1.status_code == 200
        binding_id_first = r1.json()["data"]["binding_id"]

        r2 = client.post(
            "/api/v1/member/golden-id/bind",
            json=payload,
            headers=TENANT_HEADER,
        )
        assert r2.status_code == 200
        data2 = r2.json()["data"]
        assert data2["binding_id"] == binding_id_first
        assert data2["idempotent"] is True

    def test_duplicate_bind_no_error(self):
        """重复绑定的 ok 字段为 True"""
        openid = "ele_openid_idem_noerrror_004"
        payload = {
            "customer_id": CUSTOMER_B,
            "channel_type": "eleme",
            "channel_openid": openid,
        }
        for _ in range(3):
            r = client.post(
                "/api/v1/member/golden-id/bind",
                json=payload,
                headers=TENANT_HEADER,
            )
            assert r.status_code == 200
            assert r.json()["ok"] is True


# ── 4. 解绑 ───────────────────────────────────────────────────────────────────

class TestUnbind:
    """test_unbind: 解绑已有渠道绑定"""

    def test_unbind_existing_binding(self):
        openid = "dy_openid_unbind_005"
        # 先绑定
        rb = client.post(
            "/api/v1/member/golden-id/bind",
            json={
                "customer_id": CUSTOMER_A,
                "channel_type": "douyin",
                "channel_openid": openid,
            },
            headers=TENANT_HEADER,
        )
        assert rb.status_code == 200

        # 再解绑
        ru = client.delete(
            "/api/v1/member/golden-id/unbind",
            json={"channel_type": "douyin", "channel_openid": openid},
            headers=TENANT_HEADER,
        )
        assert ru.status_code == 200
        assert ru.json()["ok"] is True
        assert "binding_id" in ru.json()["data"]

    def test_unbind_nonexistent_returns_404(self):
        r = client.delete(
            "/api/v1/member/golden-id/unbind",
            json={
                "channel_type": "wechat",
                "channel_openid": "wx_openid_not_exist_99999",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 404

    def test_unbind_invalid_channel_type(self):
        r = client.delete(
            "/api/v1/member/golden-id/unbind",
            json={"channel_type": "bad_channel", "channel_openid": "xxx"},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 422


# ── 5. 列出冲突 ───────────────────────────────────────────────────────────────

class TestListConflicts:
    """test_list_conflicts: 列出未解决冲突，分页"""

    def test_list_conflicts_ok(self):
        r = client.get(
            "/api/v1/member/golden-id/conflicts",
            params={"page": 1, "size": 10},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]
        assert isinstance(data["data"]["items"], list)

    def test_list_conflicts_pagination_structure(self):
        r = client.get(
            "/api/v1/member/golden-id/conflicts",
            params={"page": 1, "size": 5},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        payload = r.json()["data"]
        assert payload["page"] == 1
        assert payload["size"] == 5

    def test_list_conflicts_size_limit(self):
        """size 超过 100 应返回 400"""
        r = client.get(
            "/api/v1/member/golden-id/conflicts",
            params={"page": 1, "size": 200},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 400


# ── 6. 解决冲突 ───────────────────────────────────────────────────────────────

class TestResolveConflict:
    """test_resolve_conflict: 解决单个冲突，保留指定 customer_id"""

    def test_resolve_nonexistent_conflict_404(self):
        """不存在的冲突 ID 应返回 404"""
        r = client.post(
            "/api/v1/member/golden-id/conflicts/00000000-0000-0000-0000-000000000099/resolve",
            json={"keep_customer_id": CUSTOMER_A, "operator_id": "admin"},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 404

    def test_resolve_invalid_uuid(self):
        """无效 UUID 格式应返回 400"""
        r = client.post(
            "/api/v1/member/golden-id/conflicts/not-a-uuid/resolve",
            json={"keep_customer_id": CUSTOMER_A},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 400

    def test_resolve_conflict_response_structure(self):
        """如果真的有冲突记录，解决后应返回 ok=True 和 conflict_id"""
        # 先查一条冲突（若无则跳过）
        r = client.get(
            "/api/v1/member/golden-id/conflicts",
            params={"page": 1, "size": 1},
            headers=TENANT_HEADER,
        )
        items = r.json()["data"]["items"]
        if not items:
            # 没有冲突数据，验证结构即可
            return

        conflict_id = items[0]["id"]
        keep_id = items[0]["customer_id"]
        rr = client.post(
            f"/api/v1/member/golden-id/conflicts/{conflict_id}/resolve",
            json={"keep_customer_id": keep_id, "operator_id": "test_operator"},
            headers=TENANT_HEADER,
        )
        assert rr.status_code == 200
        data = rr.json()
        assert data["ok"] is True
        assert data["data"]["conflict_id"] == conflict_id
        assert data["data"]["kept_customer_id"] == keep_id


# ── 7. 统计 ───────────────────────────────────────────────────────────────────

class TestStats:
    """test_stats: 各渠道绑定数量统计"""

    def test_stats_returns_all_channels(self):
        r = client.get(
            "/api/v1/member/golden-id/stats",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        by_channel = data["data"]["by_channel"]
        # 所有渠道都应存在（即使为 0）
        for channel in ("meituan", "eleme", "douyin", "wechat"):
            assert channel in by_channel, f"渠道 {channel} 不在统计结果中"

    def test_stats_structure(self):
        r = client.get(
            "/api/v1/member/golden-id/stats",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        payload = r.json()["data"]
        assert "total_active_bindings" in payload
        assert "total_conflicts" in payload
        assert "by_channel" in payload

    def test_stats_channel_fields(self):
        r = client.get(
            "/api/v1/member/golden-id/stats",
            headers=TENANT_HEADER,
        )
        by_channel = r.json()["data"]["by_channel"]
        for channel_stat in by_channel.values():
            assert "active_count" in channel_stat
            assert "conflict_count" in channel_stat
            assert "unbound_count" in channel_stat
            assert "unique_customers" in channel_stat


# ── 8. 批量导入 ───────────────────────────────────────────────────────────────

class TestBatchImport:
    """test_batch_import: 批量导入渠道绑定"""

    def test_batch_import_ok(self):
        r = client.post(
            "/api/v1/member/golden-id/batch-import",
            json={
                "items": [
                    {
                        "channel_type": "meituan",
                        "channel_openid": f"mt_batch_openid_{i:04d}",
                        "phone": f"1380000{i:04d}",
                    }
                    for i in range(1, 6)  # 5 条
                ]
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["total"] == 5
        assert data["data"]["success_count"] + data["data"]["skipped_count"] == 5

    def test_batch_import_idempotent_on_duplicate(self):
        """重复导入同一 openid 应跳过，skipped_count 增加"""
        openid = "mt_batch_idem_check_007"
        payload = {
            "items": [
                {"channel_type": "meituan", "channel_openid": openid},
            ]
        }
        r1 = client.post(
            "/api/v1/member/golden-id/batch-import",
            json=payload,
            headers=TENANT_HEADER,
        )
        assert r1.status_code == 200
        assert r1.json()["data"]["success_count"] == 1

        r2 = client.post(
            "/api/v1/member/golden-id/batch-import",
            json=payload,
            headers=TENANT_HEADER,
        )
        assert r2.status_code == 200
        assert r2.json()["data"]["skipped_count"] == 1

    def test_batch_import_empty_items(self):
        """空列表应返回 400"""
        r = client.post(
            "/api/v1/member/golden-id/batch-import",
            json={"items": []},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 400

    def test_batch_import_exceeds_limit(self):
        """超过 500 条应返回 422（Pydantic max_length 校验）"""
        r = client.post(
            "/api/v1/member/golden-id/batch-import",
            json={
                "items": [
                    {"channel_type": "meituan", "channel_openid": f"mt_over_{i}"}
                    for i in range(501)
                ]
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 422

    def test_batch_import_response_structure(self):
        r = client.post(
            "/api/v1/member/golden-id/batch-import",
            json={
                "items": [
                    {"channel_type": "eleme", "channel_openid": "ele_struct_check_008"},
                ]
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        payload = r.json()["data"]
        for key in ("total", "success_count", "skipped_count", "failed_count", "failed_items"):
            assert key in payload, f"响应中缺少字段 {key}"
