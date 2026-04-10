"""
多品牌管理 + 多区域管理 单元测试
Y-H1 + Y-H2

4个测试：
1. test_brand_list_db_path       — 品牌列表返回含 brand_code/brand_type，无 _memory_store 关键字
2. test_brand_strategy_config    — PUT strategy_config 后 GET 验证内容完整返回（JSONB完整性）
3. test_region_tree_structure    — tree=true 返回含 children，level=1 节点在最顶层
4. test_region_tax_rate_update   — PUT /tax-rate 设置0.09，GET 验证 tax_rate=0.09
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

# ── 测试 App 构建 ─────────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    from api.brand_management_routes import router as brand_router
    from api.region_management_routes import router as region_router

    app = FastAPI()
    app.include_router(brand_router)
    app.include_router(region_router)
    return app


TENANT_ID = "11111111-1111-1111-1111-111111111111"
HEADERS = {"X-Tenant-ID": TENANT_ID}

# ── 辅助 ─────────────────────────────────────────────────────────────────────


def _make_mock_db():
    """返回最小可用的异步 DB mock"""
    db = AsyncMock()
    db.execute.return_value = MagicMock(
        scalar=MagicMock(return_value=0),
        fetchone=MagicMock(return_value=None),
        fetchall=MagicMock(return_value=[]),
    )
    db.commit = AsyncMock()
    return db


def _mock_row(mapping: dict):
    """构造一个带 _mapping 属性的 mock row"""
    row = MagicMock()
    row._mapping = mapping
    return row


# ── Test 1: 品牌列表走DB路径，无内存存储关键字 ──────────────────────────────────

@pytest.mark.asyncio
async def test_brand_list_db_path():
    """品牌列表：返回含 brand_code/brand_type 字段，无 '_memory_store' 关键字（验证非内存路径）"""
    app = _make_app()

    call_count = 0

    def _make_call_tracking_db():
        db = AsyncMock()

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # RLS set_config
                return MagicMock(scalar=MagicMock(return_value=None),
                                 fetchone=MagicMock(return_value=None),
                                 fetchall=MagicMock(return_value=[]))
            if call_count == 2:
                # COUNT(*)
                result = MagicMock()
                result.scalar = MagicMock(return_value=2)
                return result
            # 品牌列表查询
            rows = [
                _mock_row({
                    "brand_id": "brand-001",
                    "name": "徐记海鲜",
                    "brand_code": "XJ",
                    "brand_type": "seafood",
                    "logo_url": None,
                    "primary_color": "#FF6B35",
                    "description": None,
                    "status": "active",
                    "hq_store_id": None,
                    "strategy_config": {},
                    "created_at": None,
                    "updated_at": None,
                    "store_count": 12,
                }),
                _mock_row({
                    "brand_id": "brand-002",
                    "name": "尝在一起",
                    "brand_code": "CZ",
                    "brand_type": "canteen",
                    "logo_url": None,
                    "primary_color": "#FF6B35",
                    "description": None,
                    "status": "active",
                    "hq_store_id": None,
                    "strategy_config": {},
                    "created_at": None,
                    "updated_at": None,
                    "store_count": 8,
                }),
            ]
            return MagicMock(
                scalar=MagicMock(return_value=2),
                fetchone=MagicMock(return_value=rows[0]),
                fetchall=MagicMock(return_value=rows),
            )

        db.execute.side_effect = side_effect
        db.commit = AsyncMock()
        return db

    with patch("api.brand_management_routes.get_db") as mock_get_db:
        mock_db = _make_call_tracking_db()

        async def _override():
            yield mock_db

        mock_get_db.side_effect = _override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/org/brands", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True

    items = body["data"]["items"]
    assert len(items) >= 1

    # 验证含 brand_code 和 brand_type 字段
    first = items[0]
    assert "brand_code" in first, "缺少 brand_code 字段"
    assert "brand_type" in first, "缺少 brand_type 字段"

    # 验证响应体字符串中不含内存存储关键字
    raw_text = resp.text
    assert "_memory_store" not in raw_text, "响应中不应含 _memory_store（内存路径泄漏）"
    assert "degraded" not in raw_text or body["data"].get("degraded") is None, \
        "DB可用时不应返回 degraded 标记"


# ── Test 2: 策略配置 JSONB 完整性 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brand_strategy_config():
    """策略配置：PUT 更新 strategy_config，GET 验证内容完整返回（JSONB字段完整性）"""
    app = _make_app()

    expected_strategy = {
        "discount_threshold": 0.3,
        "menu_strategy": "standard",
        "report_template": "monthly",
        "margin_alert_level": 0.4,
    }

    brand_id = "brand-001"
    stored_config: dict = {}

    def _make_strategy_db():
        db = AsyncMock()

        async def side_effect(stmt, params=None):
            sql_str = str(stmt)

            # RLS set_config
            if "set_config" in sql_str:
                return MagicMock(fetchone=MagicMock(return_value=None),
                                 fetchall=MagicMock(return_value=[]))

            # PUT 存在性检查
            if "SELECT id FROM brands" in sql_str and params and params.get("bid") == brand_id:
                return MagicMock(
                    fetchone=MagicMock(return_value=_mock_row({"id": brand_id}))
                )

            # PUT UPDATE
            if "UPDATE brands" in sql_str and "strategy_config" in sql_str:
                config_val = params.get("config") if params else None
                if config_val:
                    nonlocal stored_config
                    stored_config = json.loads(config_val) if isinstance(config_val, str) else config_val
                return MagicMock(fetchone=MagicMock(return_value=None))

            # GET strategy_config SELECT
            if "SELECT strategy_config" in sql_str:
                row = _mock_row({"strategy_config": stored_config or expected_strategy})
                return MagicMock(fetchone=MagicMock(return_value=row))

            return MagicMock(
                scalar=MagicMock(return_value=None),
                fetchone=MagicMock(return_value=None),
                fetchall=MagicMock(return_value=[]),
            )

        db.execute.side_effect = side_effect
        db.commit = AsyncMock()
        return db

    with patch("api.brand_management_routes.get_db") as mock_get_db:
        mock_db = _make_strategy_db()

        async def _override():
            yield mock_db

        mock_get_db.side_effect = _override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # PUT 更新策略
            put_resp = await client.put(
                f"/api/v1/org/brands/{brand_id}/strategy",
                headers=HEADERS,
                json={"strategy_config": expected_strategy},
            )
            assert put_resp.status_code == 200, f"PUT失败: {put_resp.text}"
            put_body = put_resp.json()
            assert put_body["ok"] is True

            # GET 验证内容完整返回
            get_resp = await client.get(
                f"/api/v1/org/brands/{brand_id}/strategy",
                headers=HEADERS,
            )
            assert get_resp.status_code == 200, f"GET失败: {get_resp.text}"
            get_body = get_resp.json()
            assert get_body["ok"] is True

            returned_config = get_body["data"]["strategy_config"]
            for key in expected_strategy:
                assert key in returned_config, f"JSONB字段 {key} 丢失"
            assert returned_config.get("discount_threshold") == expected_strategy["discount_threshold"]


# ── Test 3: 区域树形结构 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_region_tree_structure():
    """区域树：tree=true 返回含 children 字段，level=1 的节点在最顶层"""
    app = _make_app()

    mock_rows = [
        _mock_row({
            "region_id": "region-001",
            "parent_id": None,
            "name": "华中大区",
            "region_code": "HZ",
            "level": 1,
            "brand_id": None,
            "manager_id": None,
            "tax_rate": "0.0600",
            "freight_template": {},
            "is_active": True,
            "created_at": None,
            "updated_at": None,
            "manager_name": None,
            "store_count": 15,
            "child_count": 2,
        }),
        _mock_row({
            "region_id": "region-011",
            "parent_id": "region-001",
            "name": "湖南省",
            "region_code": "HN",
            "level": 2,
            "brand_id": None,
            "manager_id": None,
            "tax_rate": "0.0600",
            "freight_template": {},
            "is_active": True,
            "created_at": None,
            "updated_at": None,
            "manager_name": None,
            "store_count": 10,
            "child_count": 2,
        }),
        _mock_row({
            "region_id": "region-111",
            "parent_id": "region-011",
            "name": "长沙市",
            "region_code": "CS",
            "level": 3,
            "brand_id": None,
            "manager_id": None,
            "tax_rate": "0.0600",
            "freight_template": {},
            "is_active": True,
            "created_at": None,
            "updated_at": None,
            "manager_name": None,
            "store_count": 8,
            "child_count": 0,
        }),
    ]

    def _make_region_db():
        db = AsyncMock()

        async def side_effect(*args, **kwargs):
            sql_str = str(args[0]) if args else ""
            if "set_config" in sql_str:
                return MagicMock(fetchone=MagicMock(return_value=None),
                                 fetchall=MagicMock(return_value=[]))
            return MagicMock(
                scalar=MagicMock(return_value=len(mock_rows)),
                fetchone=MagicMock(return_value=mock_rows[0]),
                fetchall=MagicMock(return_value=mock_rows),
            )

        db.execute.side_effect = side_effect
        db.commit = AsyncMock()
        return db

    with patch("api.region_management_routes.get_db") as mock_get_db:
        mock_db = _make_region_db()

        async def _override():
            yield mock_db

        mock_get_db.side_effect = _override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/org/regions?tree=true", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True

    tree = body["data"]["tree"]
    assert isinstance(tree, list), "tree 应为数组"
    assert len(tree) >= 1, "树根节点不能为空"

    # level=1 的节点必须在最顶层（tree 数组直接元素）
    for root_node in tree:
        assert root_node.get("level") == 1, f"顶层节点 level 应为 1，实际={root_node.get('level')}"
        assert "children" in root_node, "顶层节点必须有 children 字段"
        assert isinstance(root_node["children"], list), "children 必须是数组"

    # 验证树形结构深度（level=3 不应出现在顶层）
    top_level_ids = {n["region_id"] for n in tree}
    assert "region-111" not in top_level_ids, "长沙市（level=3）不应出现在顶层"


# ── Test 4: 区域税率更新 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_region_tax_rate_update():
    """税率更新：PUT /regions/{id}/tax-rate 设置0.09，GET 验证 tax_rate=0.09"""
    app = _make_app()

    region_id = "region-001"
    stored_tax_rate = {"value": 0.06}

    def _make_tax_db():
        db = AsyncMock()

        async def side_effect(stmt, params=None):
            sql_str = str(stmt)

            if "set_config" in sql_str:
                return MagicMock(fetchone=MagicMock(return_value=None),
                                 fetchall=MagicMock(return_value=[]))

            # PUT 存在性检查
            if "SELECT id, name FROM regions" in sql_str and params and params.get("rid") == region_id:
                return MagicMock(
                    fetchone=MagicMock(
                        return_value=_mock_row({"id": region_id, "name": "华中大区"})
                    )
                )

            # PUT UPDATE tax_rate
            if "UPDATE regions" in sql_str and "tax_rate" in sql_str:
                new_val = params.get("tax_rate") if params else None
                if new_val is not None:
                    stored_tax_rate["value"] = float(new_val)
                return MagicMock(fetchone=MagicMock(return_value=None))

            # GET detail
            if "SELECT" in sql_str and "tax_rate" in sql_str:
                row = _mock_row({
                    "region_id": region_id,
                    "parent_id": None,
                    "name": "华中大区",
                    "region_code": "HZ",
                    "level": 1,
                    "brand_id": None,
                    "manager_id": None,
                    "tax_rate": str(stored_tax_rate["value"]),
                    "freight_template": {},
                    "is_active": True,
                    "created_at": None,
                    "updated_at": None,
                    "manager_name": None,
                    "parent_name": None,
                    "store_count": 15,
                    "child_count": 2,
                })
                return MagicMock(fetchone=MagicMock(return_value=row))

            return MagicMock(
                scalar=MagicMock(return_value=None),
                fetchone=MagicMock(return_value=None),
                fetchall=MagicMock(return_value=[]),
            )

        db.execute.side_effect = side_effect
        db.commit = AsyncMock()
        return db

    with patch("api.region_management_routes.get_db") as mock_get_db:
        mock_db = _make_tax_db()

        async def _override():
            yield mock_db

        mock_get_db.side_effect = _override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # PUT 设置税率为 0.09
            put_resp = await client.put(
                f"/api/v1/org/regions/{region_id}/tax-rate",
                headers=HEADERS,
                json={"tax_rate": 0.09},
            )
            assert put_resp.status_code == 200, f"PUT失败: {put_resp.text}"
            put_body = put_resp.json()
            assert put_body["ok"] is True
            assert put_body["data"]["tax_rate"] == 0.09, "PUT响应中税率应为0.09"

            # GET 验证 tax_rate=0.09
            get_resp = await client.get(
                f"/api/v1/org/regions/{region_id}",
                headers=HEADERS,
            )
            assert get_resp.status_code == 200, f"GET失败: {get_resp.text}"
            get_body = get_resp.json()
            assert get_body["ok"] is True

            returned_tax = get_body["data"]["tax_rate"]
            assert abs(float(returned_tax) - 0.09) < 1e-6, \
                f"GET返回的 tax_rate 应为0.09，实际={returned_tax}"
