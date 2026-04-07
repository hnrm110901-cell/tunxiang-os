"""
TC-P2-14 — CRM三级分销体系测试

测试用例：
1. test_generate_referral_code       — 生成推荐码：6字符/唯一/大写字母+数字
2. test_bind_three_level_chain       — 绑定三级链路：A→B→C→D，验证D的level1/2/3
3. test_reward_calculation           — 奖励计算：D消费10000分，C/B/A分别获得正确积分
4. test_abuse_detection              — 防刷检测：同member_id重复绑定，幂等返回不报错
5. test_referral_stats               — 统计接口：字段存在且为数值类型
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from fastapi.testclient import TestClient
import re
import sys
import os

# 确保测试可以导入服务模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# 构建一个轻量级 FastAPI 测试应用，只挂载三级分销路由
from fastapi import FastAPI
from src.api.distribution_routes import router as distribution_router

_test_app = FastAPI()
_test_app.include_router(distribution_router)

TENANT_HEADER = {"X-Tenant-ID": "test-tenant-001"}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(_test_app)


def _post(client: TestClient, path: str, json: dict | None = None) -> dict:
    resp = client.post(path, json=json or {}, headers=TENANT_HEADER)
    assert resp.status_code == 200, f"POST {path} returned {resp.status_code}: {resp.text}"
    return resp.json()


def _get(client: TestClient, path: str, params: dict | None = None) -> dict:
    resp = client.get(path, params=params or {}, headers=TENANT_HEADER)
    assert resp.status_code == 200, f"GET {path} returned {resp.status_code}: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# 1. 生成推荐码
# ---------------------------------------------------------------------------

def test_generate_referral_code() -> None:
    """推荐码必须满足：长度6字符 / 仅大写字母+数字 / TX前缀 / 两次生成结果唯一"""
    client = _client()

    result1 = _post(client, "/api/v1/growth/referral/links", {
        "member_id": "mem-gen-001",
        "channel": "wechat",
    })
    assert result1["ok"] is True
    code1: str = result1["data"]["referral_code"]

    # 格式校验：TX + 4位大写字母/数字 = 6字符
    assert len(code1) == 6, f"推荐码长度应为6，实际为 {len(code1)}"
    assert re.fullmatch(r"[A-Z0-9]{6}", code1), f"推荐码格式非法：{code1}"
    assert code1.startswith("TX"), f"推荐码应以TX开头，实际：{code1}"

    # 唯一性：同一会员再次生成得到不同的码
    result2 = _post(client, "/api/v1/growth/referral/links", {
        "member_id": "mem-gen-002",
        "channel": "wechat",
    })
    assert result2["ok"] is True
    code2: str = result2["data"]["referral_code"]
    assert code1 != code2, "两次生成的推荐码不应相同"

    # 推荐码存储在 data 中，包含必要字段
    data = result1["data"]
    assert data["member_id"] == "mem-gen-001"
    assert data["channel"] == "wechat"
    assert data["is_active"] is True
    assert data["click_count"] == 0
    assert data["convert_count"] == 0


# ---------------------------------------------------------------------------
# 2. 绑定三级链路（A推荐B→B推荐C→C推荐D）
# ---------------------------------------------------------------------------

def test_bind_three_level_chain() -> None:
    """
    构建三级链路：
      A（mem-chain-a）生成推荐码 → B（mem-chain-b）用A的码注册
      B 生成推荐码 → C（mem-chain-c）用B的码注册
      C 生成推荐码 → D（mem-chain-d）用C的码注册

    验证D的推荐关系：
      level1_id = C（直接推荐人）
      level2_id = B（二级推荐人）
      level3_id = A（三级推荐人）
    """
    client = _client()

    # Step1: A 生成推荐码
    r_a = _post(client, "/api/v1/growth/referral/links", {"member_id": "mem-chain-a"})
    code_a = r_a["data"]["referral_code"]

    # Step2: B 通过 A 的码绑定
    r_bind_b = _post(client, "/api/v1/growth/referral/bind", {
        "referee_id": "mem-chain-b",
        "referral_code": code_a,
    })
    assert r_bind_b["ok"] is True
    rel_b = r_bind_b["data"]["relationship"]
    assert rel_b["referee_id"] == "mem-chain-b"
    assert rel_b["level1_id"] == "mem-chain-a"
    assert rel_b["level2_id"] is None  # B 没有二级上线
    assert rel_b["level3_id"] is None

    # Step3: B 生成推荐码
    r_b = _post(client, "/api/v1/growth/referral/links", {"member_id": "mem-chain-b"})
    code_b = r_b["data"]["referral_code"]

    # Step4: C 通过 B 的码绑定
    r_bind_c = _post(client, "/api/v1/growth/referral/bind", {
        "referee_id": "mem-chain-c",
        "referral_code": code_b,
    })
    assert r_bind_c["ok"] is True
    rel_c = r_bind_c["data"]["relationship"]
    assert rel_c["level1_id"] == "mem-chain-b"  # 直接推荐人是B
    assert rel_c["level2_id"] == "mem-chain-a"  # 二级是A
    assert rel_c["level3_id"] is None

    # Step5: C 生成推荐码
    r_c = _post(client, "/api/v1/growth/referral/links", {"member_id": "mem-chain-c"})
    code_c = r_c["data"]["referral_code"]

    # Step6: D 通过 C 的码绑定
    r_bind_d = _post(client, "/api/v1/growth/referral/bind", {
        "referee_id": "mem-chain-d",
        "referral_code": code_c,
    })
    assert r_bind_d["ok"] is True
    rel_d = r_bind_d["data"]["relationship"]

    # 核心断言：D 的三级推荐关系
    assert rel_d["referee_id"] == "mem-chain-d"
    assert rel_d["level1_id"] == "mem-chain-c", (
        f"D的level1应为C，实际为 {rel_d['level1_id']}"
    )
    assert rel_d["level2_id"] == "mem-chain-b", (
        f"D的level2应为B，实际为 {rel_d['level2_id']}"
    )
    assert rel_d["level3_id"] == "mem-chain-a", (
        f"D的level3应为A，实际为 {rel_d['level3_id']}"
    )


# ---------------------------------------------------------------------------
# 3. 奖励计算
# ---------------------------------------------------------------------------

def test_reward_calculation() -> None:
    """
    D 消费 10000 分（首单）应触发三级奖励：
    - C（一级，level1）：10000 × 3% = 300 分
    - B（二级，level2）：10000 × 1.5% = 150 分
    - A（三级，level3）：10000 × 0.5% = 50 分
    """
    client = _client()

    # 先建立三级链路（复用 mem-calc-* 系列避免与其他测试冲突）
    r_a = _post(client, "/api/v1/growth/referral/links", {"member_id": "mem-calc-a"})
    code_a = r_a["data"]["referral_code"]
    _post(client, "/api/v1/growth/referral/bind", {"referee_id": "mem-calc-b", "referral_code": code_a})

    r_b = _post(client, "/api/v1/growth/referral/links", {"member_id": "mem-calc-b"})
    code_b = r_b["data"]["referral_code"]
    _post(client, "/api/v1/growth/referral/bind", {"referee_id": "mem-calc-c", "referral_code": code_b})

    r_c = _post(client, "/api/v1/growth/referral/links", {"member_id": "mem-calc-c"})
    code_c = r_c["data"]["referral_code"]
    _post(client, "/api/v1/growth/referral/bind", {"referee_id": "mem-calc-d", "referral_code": code_c})

    # 触发奖励计算：D 消费 10000 分
    result = _post(client, "/api/v1/growth/referral/rewards/calculate", {
        "order_id": "ord-test-001",
        "member_id": "mem-calc-d",
        "order_amount_fen": 10000,
    })
    assert result["ok"] is True
    data = result["data"]

    rewards = data["rewards"]
    assert len(rewards) == 3, f"应生成3条奖励，实际为 {len(rewards)}"

    # 按 reward_level 排序，方便断言
    rewards_by_level = {r["reward_level"]: r for r in rewards}

    # 一级奖励：C → 10000 × 3% = 300
    r1 = rewards_by_level[1]
    assert r1["member_id"] == "mem-calc-c", f"一级获奖人应为C，实际 {r1['member_id']}"
    assert r1["reward_value_fen"] == 300, f"一级奖励应为300分，实际 {r1['reward_value_fen']}"
    assert r1["status"] == "pending"

    # 二级奖励：B → 10000 × 1.5% = 150
    r2 = rewards_by_level[2]
    assert r2["member_id"] == "mem-calc-b", f"二级获奖人应为B，实际 {r2['member_id']}"
    assert r2["reward_value_fen"] == 150, f"二级奖励应为150分，实际 {r2['reward_value_fen']}"

    # 三级奖励：A → 10000 × 0.5% = 50
    r3 = rewards_by_level[3]
    assert r3["member_id"] == "mem-calc-a", f"三级获奖人应为A，实际 {r3['member_id']}"
    assert r3["reward_value_fen"] == 50, f"三级奖励应为50分，实际 {r3['reward_value_fen']}"

    # 奖励总计
    assert data["total_reward_fen"] == 500, f"奖励总额应为500，实际 {data['total_reward_fen']}"


# ---------------------------------------------------------------------------
# 4. 防刷检测：同member_id重复绑定应幂等
# ---------------------------------------------------------------------------

def test_abuse_detection() -> None:
    """
    同一 referee_id 重复调用 /bind 应幂等：
    - 第一次绑定：正常创建关系，idempotent=False
    - 第二次绑定（同码）：返回已有关系，idempotent=True，不创建重复记录
    - detect-abuse 接口应检测到 DUPLICATE_BIND 标志
    """
    client = _client()

    # 生成推荐码
    r_link = _post(client, "/api/v1/growth/referral/links", {"member_id": "mem-abuse-a"})
    code = r_link["data"]["referral_code"]

    # 第一次绑定
    r1 = _post(client, "/api/v1/growth/referral/bind", {
        "referee_id": "mem-abuse-b",
        "referral_code": code,
    })
    assert r1["ok"] is True
    assert r1["data"]["idempotent"] is False

    # 第二次绑定（相同 referee_id + 相同码）
    r2 = _post(client, "/api/v1/growth/referral/bind", {
        "referee_id": "mem-abuse-b",
        "referral_code": code,
    })
    assert r2["ok"] is True, "重复绑定应幂等返回，不应报错"
    assert r2["data"]["idempotent"] is True, "第二次绑定应返回 idempotent=True"

    # 两次绑定的关系记录应一致（相同 level1_id）
    rel1 = r1["data"]["relationship"]
    rel2 = r2["data"]["relationship"]
    assert rel1["level1_id"] == rel2["level1_id"]

    # 异常检测接口应标记 DUPLICATE_BIND
    abuse_result = _post(client, "/api/v1/growth/referral/detect-abuse", {
        "referee_id": "mem-abuse-b",
        "referral_code": code,
    })
    assert abuse_result["ok"] is True
    abuse_data = abuse_result["data"]
    assert abuse_data["is_abuse"] is True, "重复绑定应被标记为异常"
    assert "DUPLICATE_BIND" in abuse_data["flags"], (
        f"异常标志应包含 DUPLICATE_BIND，实际：{abuse_data['flags']}"
    )


# ---------------------------------------------------------------------------
# 5. 统计接口
# ---------------------------------------------------------------------------

def test_referral_stats() -> None:
    """
    统计接口返回字段必须存在且为数值类型：
    - participant_count
    - three_level_chain_count
    - this_month_issued_fen
    - pending_reward_fen
    """
    client = _client()

    result = _get(client, "/api/v1/growth/referral/stats")
    assert result["ok"] is True, f"统计接口返回 ok=False：{result}"

    data = result["data"]
    numeric_fields = [
        "participant_count",
        "three_level_chain_count",
        "this_month_issued_fen",
        "pending_reward_fen",
        "total_click_count",
        "total_convert_count",
    ]

    for field in numeric_fields:
        assert field in data, f"统计接口缺少字段：{field}"
        value = data[field]
        assert isinstance(value, (int, float)), (
            f"字段 {field} 应为数值类型，实际为 {type(value).__name__}（值：{value}）"
        )
        assert value >= 0, f"字段 {field} 不应为负数，实际：{value}"
