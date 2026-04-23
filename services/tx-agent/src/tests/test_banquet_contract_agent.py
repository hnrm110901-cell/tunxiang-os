"""Tier 2 测试 — 宴会合同管家 Agent（Track R2-C / Sprint R2）

验收：覆盖 5 个 action + 3 条硬约束落地 + 决策留痕。

关联实现：
  services/tx-agent/src/agents/skills/banquet_contract_agent.py
  services/tx-trade/src/services/banquet_contract_service.py
  services/tx-trade/src/services/banquet_eo_ticket_service.py

测试策略：
  - 直接构造 BanquetContractAgent，注入 InMemory Repo + 真实 Service
  - R1 HTTP API 用 fake client（async method .get_lead / .dispatch）
  - Agent 的 PDF 生成器复用 tx-trade 的 placeholder 实现
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TX_AGENT_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TX_TRADE_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "tx-trade", "src")
)
TX_TRADE_PKG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "tx-trade")
)
# tx-agent 的 src 已被 pytest 作为顶层 `src` 包注册；我们需要把 tx-trade 的
# service/repo 以独立包名 `txtrade_src` 加载，避免与 tx-agent 的 `src` 冲突。
# 做法：将 tx-trade/src 的 __init__.py 显式当作一个新包 `txtrade_src` 注册，
# 然后把其子模块/子包也按相对路径导入。
for p in [TX_AGENT_SRC, ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

import importlib
import importlib.util
import types


def _register_package(alias: str, src_dir: str) -> types.ModuleType:
    """把 tx-trade/src 注册为 `alias` 包（支持相对 import）。"""
    if alias in sys.modules:
        return sys.modules[alias]
    init_file = os.path.join(src_dir, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        alias,
        init_file,
        submodule_search_locations=[src_dir],
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _register_submodule(
    pkg_alias: str, sub_path: str, sub_name: str
) -> types.ModuleType:
    """在 `pkg_alias` 包下注册子模块；sub_path 相对 pkg 根目录。"""
    full_alias = f"{pkg_alias}.{sub_name}"
    if full_alias in sys.modules:
        return sys.modules[full_alias]
    # 若 sub_path 是目录（子包）
    if os.path.isdir(sub_path):
        init_file = os.path.join(sub_path, "__init__.py")
        spec = importlib.util.spec_from_file_location(
            full_alias,
            init_file,
            submodule_search_locations=[sub_path],
        )
    else:
        spec = importlib.util.spec_from_file_location(full_alias, sub_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_alias] = mod
    # 挂到父包命名空间，使相对 import 生效
    parent = sys.modules[pkg_alias]
    setattr(parent, sub_name, mod)
    spec.loader.exec_module(mod)
    return mod


# 注册 tx-trade/src 为 `txtrade_src` 包
_register_package("txtrade_src", TX_TRADE_SRC)
# 注册子包 `txtrade_src.repositories` + `txtrade_src.services`
_register_submodule(
    "txtrade_src",
    os.path.join(TX_TRADE_SRC, "repositories"),
    "repositories",
)
_register_submodule(
    "txtrade_src",
    os.path.join(TX_TRADE_SRC, "services"),
    "services",
)
# 注册具体模块
_register_submodule(
    "txtrade_src.repositories",
    os.path.join(TX_TRADE_SRC, "repositories", "banquet_contract_repo.py"),
    "banquet_contract_repo",
)
_register_submodule(
    "txtrade_src.services",
    os.path.join(TX_TRADE_SRC, "services", "banquet_contract_service.py"),
    "banquet_contract_service",
)
_register_submodule(
    "txtrade_src.services",
    os.path.join(TX_TRADE_SRC, "services", "banquet_eo_ticket_service.py"),
    "banquet_eo_ticket_service",
)
_register_submodule(
    "txtrade_src.services",
    os.path.join(TX_TRADE_SRC, "services", "banquet_pdf_generator.py"),
    "banquet_pdf_generator",
)

from txtrade_src.repositories.banquet_contract_repo import (  # type: ignore  # noqa: E402,E501
    InMemoryBanquetContractRepository,
)
from txtrade_src.services.banquet_contract_service import (  # type: ignore  # noqa: E402,E501
    BanquetContractService,
)
from txtrade_src.services.banquet_eo_ticket_service import (  # type: ignore  # noqa: E402,E501
    BanquetEOTicketService,
)

# Agent._generate_contract 内部通过 importlib.import_module 加载 PDF 生成器；
# 把它以 `services.banquet_pdf_generator` 的别名再挂一次，适配 Agent 的
# _import_tx_trade 搜索路径。
_pdf_mod = sys.modules["txtrade_src.services.banquet_pdf_generator"]
import services as _agent_services_pkg  # tx-agent 顶层 services 包  # noqa: E402

_agent_services_pkg.banquet_pdf_generator = _pdf_mod
sys.modules["services.banquet_pdf_generator"] = _pdf_mod

from agents.skills.banquet_contract_agent import (  # noqa: E402
    DISTRICT_MANAGER_THRESHOLD_FEN,
    STORE_MANAGER_THRESHOLD_FEN,
    BanquetContractAgent,
)

# InMemoryBanquetContractRepository / BanquetContractService / BanquetEOTicketService
# 已在上方通过 importlib 加载 — 保留 alias 引用。

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000010")
STORE_ID = uuid.UUID("11111111-1111-1111-1111-111111111110")


# ─────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────


class FakeLeadApiClient:
    """模拟 R1 HTTP GET /api/v1/banquet-leads/{id}。"""

    def __init__(self, lead_payloads: dict[uuid.UUID, dict[str, Any]]) -> None:
        self._payloads = lead_payloads
        self.calls: list[uuid.UUID] = []

    async def get_lead(
        self, *, tenant_id: uuid.UUID, lead_id: uuid.UUID
    ) -> dict[str, Any]:
        self.calls.append(lead_id)
        return self._payloads.get(lead_id, {})


class FakeTaskApiClient:
    """模拟 R1 HTTP POST /api/v1/tasks/dispatch。"""

    def __init__(self) -> None:
        self.dispatched: list[dict[str, Any]] = []

    async def dispatch(
        self,
        *,
        tenant_id: uuid.UUID,
        task_type: str,
        assignee_employee_id: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        item = {
            "tenant_id": tenant_id,
            "task_type": task_type,
            "assignee_employee_id": assignee_employee_id,
            "payload": payload,
            "task_id": str(uuid.uuid4()),
        }
        self.dispatched.append(item)
        return item


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def repo() -> InMemoryBanquetContractRepository:
    return InMemoryBanquetContractRepository()


@pytest.fixture
def emitted() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def contract_service(
    repo: InMemoryBanquetContractRepository, emitted: list[dict[str, Any]]
) -> BanquetContractService:
    async def _fake_emit(**kwargs: Any) -> str:
        emitted.append(kwargs)
        return str(uuid.uuid4())

    return BanquetContractService(repo=repo, emit_event=_fake_emit)


@pytest.fixture
def eo_service(
    repo: InMemoryBanquetContractRepository,
) -> BanquetEOTicketService:
    return BanquetEOTicketService(repo=repo)


@pytest.fixture
def lead_api() -> FakeLeadApiClient:
    lead_id = uuid.uuid4()
    return FakeLeadApiClient(
        {
            lead_id: {
                "lead_id": str(lead_id),
                "customer_id": str(uuid.uuid4()),
                "dish_bom": [
                    {
                        "ingredient": "龙虾",
                        "batch_id": "B-2026",
                        "remaining_hours": 48,
                    },
                    {
                        "ingredient": "鲍鱼",
                        "batch_id": "B-2027",
                        "remaining_hours": 36,
                    },
                ],
            }
        }
    )


@pytest.fixture
def task_api() -> FakeTaskApiClient:
    return FakeTaskApiClient()


@pytest.fixture
def agent(
    contract_service: BanquetContractService,
    eo_service: BanquetEOTicketService,
    lead_api: FakeLeadApiClient,
    task_api: FakeTaskApiClient,
) -> BanquetContractAgent:
    return BanquetContractAgent(
        tenant_id=str(TENANT_A),
        store_id=str(STORE_ID),
        contract_service=contract_service,
        eo_service=eo_service,
        lead_api_client=lead_api,
        task_api_client=task_api,
    )


# ─────────────────────────────────────────────────────────────────────────
# 1. generate_contract
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_contract_reads_r1_lead(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
) -> None:
    """Agent 生成合同前会调 R1 HTTP GET /banquet-leads/{id} 读线索。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 20,
            "total_amount_fen": 2_000_000,
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    assert result.success, result.error
    assert result.data["contract_id"]
    assert result.data["pdf_url"].startswith("https://fake-s3.banquet-contracts")
    assert result.data["deposit_fen"] == 600_000
    # R1 API 被调用一次
    assert len(lead_api.calls) == 1
    assert lead_api.calls[0] == lead_id


@pytest.mark.asyncio
async def test_generate_contract_writes_event(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
    emitted: list[dict[str, Any]],
) -> None:
    """generate_contract → BanquetContractService 写 CONTRACT_GENERATED 事件。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 15,
            "total_amount_fen": 1_500_000,
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    assert result.success, result.error
    assert any(
        e["event_type"].value == "banquet.contract_generated" for e in emitted
    )


# ─────────────────────────────────────────────────────────────────────────
# 2. split_eo
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_split_eo_creates_5_department_tickets(
    agent: BanquetContractAgent,
    contract_service: BanquetContractService,
    lead_api: FakeLeadApiClient,
) -> None:
    """split_eo 一次生成 5 部门工单（kitchen/hall/purchase/finance/marketing）。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    gen_result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 20,
            "total_amount_fen": 2_000_000,
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    contract_id = uuid.UUID(gen_result.data["contract_id"])

    split_result = await agent.run(
        "split_eo",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
        },
    )
    assert split_result.success, split_result.error
    assert split_result.data["ticket_count"] == 5
    assert set(split_result.data["departments"]) == {
        "kitchen",
        "hall",
        "purchase",
        "finance",
        "marketing",
    }


# ─────────────────────────────────────────────────────────────────────────
# 3. route_approval
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_approval_auto_passes_small_banquet(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
) -> None:
    """金额 < 10W 且非婚宴 → auto_passed=True + status=signed。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    gen_result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "birthday",  # 非婚宴
            "tables": 3,
            "total_amount_fen": 80_000,  # 800 元 < 10W
            "deposit_ratio": Decimal("0.20"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    contract_id = uuid.UUID(gen_result.data["contract_id"])
    route_result = await agent.run(
        "route_approval",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
            "total_amount_fen": 80_000,
            "banquet_type": "birthday",
        },
    )
    assert route_result.success, route_result.error
    assert route_result.data["auto_passed"] is True
    assert route_result.data["final_status"] == "signed"


@pytest.mark.asyncio
async def test_route_approval_routes_to_store_manager_for_wedding_or_over_10w(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
) -> None:
    """婚宴 或 金额 >= 10W → 路由到店长审批。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    gen_result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 15,
            "total_amount_fen": 1_200_000,  # 12W
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    contract_id = uuid.UUID(gen_result.data["contract_id"])
    # 首次路由 — 不带 approval_action
    route = await agent.run(
        "route_approval",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
            "total_amount_fen": 1_200_000,  # > 10W
            "banquet_type": "wedding",
        },
    )
    assert route.success, route.error
    assert route.data["auto_passed"] is False
    assert route.data["next_role"] == "store_manager"
    assert route.data["final_status"] == "pending_approval"
    # 阈值确认
    assert STORE_MANAGER_THRESHOLD_FEN == 1_000_000


@pytest.mark.asyncio
async def test_route_approval_routes_to_district_manager_over_50w(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
) -> None:
    """金额 ≥ 50W → 店长审 + 区经追加审批。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    gen_result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 30,
            "total_amount_fen": 5_500_000,  # 55W > 50W
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    contract_id = uuid.UUID(gen_result.data["contract_id"])
    route = await agent.run(
        "route_approval",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
            "total_amount_fen": 5_500_000,
            "banquet_type": "wedding",
        },
    )
    assert route.success, route.error
    assert route.data["auto_passed"] is False
    assert route.data["next_role"] == "store_manager"

    # 店长先审批
    store_approval = await agent.run(
        "route_approval",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
            "total_amount_fen": 5_500_000,
            "banquet_type": "wedding",
            "approver_id": uuid.uuid4(),
            "approval_action": "approve",
        },
    )
    assert store_approval.success, store_approval.error
    assert store_approval.data["next_role"] == "district_manager"
    assert DISTRICT_MANAGER_THRESHOLD_FEN == 5_000_000

    # 区经审批 → 最终签约
    district_approval = await agent.run(
        "route_approval",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
            "total_amount_fen": 5_500_000,
            "banquet_type": "wedding",
            "approver_id": uuid.uuid4(),
            "approval_action": "approve",
        },
    )
    assert district_approval.success, district_approval.error
    assert district_approval.data["next_role"] is None
    assert district_approval.data["final_status"] == "signed"


# ─────────────────────────────────────────────────────────────────────────
# 4. lock_schedule — FIFO 先到先得
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lock_schedule_first_come_first_served(
    agent: BanquetContractAgent,
    contract_service: BanquetContractService,
    lead_api: FakeLeadApiClient,
) -> None:
    """同档期两个合同，先付订金者获得档期，后者进 FIFO 候补队列。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    sched = date(2026, 10, 1)

    # 创建两个合同
    c1_result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 20,
            "total_amount_fen": 2_000_000,
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": sched,
        },
    )
    c1_id = uuid.UUID(c1_result.data["contract_id"])

    # C1 先锁 — 由 lock_schedule 自动签
    lock1 = await agent.run(
        "lock_schedule",
        {
            "tenant_id": TENANT_A,
            "contract_id": c1_id,
            "scheduled_date": sched,
            "store_id": STORE_ID,
            "deposit_paid_fen": 600_000,
        },
    )
    assert lock1.success
    assert lock1.data["locked"] is True

    # C2 紧跟着创建并尝试锁 — 因为 C1 已锁 → C2 进候补
    c2_result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 15,
            "total_amount_fen": 1_600_000,
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": sched,
        },
    )
    c2_id = uuid.UUID(c2_result.data["contract_id"])

    lock2 = await agent.run(
        "lock_schedule",
        {
            "tenant_id": TENANT_A,
            "contract_id": c2_id,
            "scheduled_date": sched,
            "store_id": STORE_ID,
            "deposit_paid_fen": 500_000,
        },
    )
    assert lock2.success
    assert lock2.data["locked"] is False
    # 候补队列含 C1（已锁）
    assert str(c1_id) in lock2.data["queued_contract_ids"]


# ─────────────────────────────────────────────────────────────────────────
# 5. progress_reminder — 分阶段推送
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_progress_reminder_dispatches_4_tier_tasks(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
    task_api: FakeTaskApiClient,
) -> None:
    """T-7d/T-3d/T-1d/T-2h 四级各向 5 部门工单派任务。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    gen_result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 20,
            "total_amount_fen": 2_000_000,
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    contract_id = uuid.UUID(gen_result.data["contract_id"])
    await agent.run(
        "split_eo",
        {"tenant_id": TENANT_A, "contract_id": contract_id},
    )

    for stage in ("T-7d", "T-3d", "T-1d", "T-2h"):
        r = await agent.run(
            "progress_reminder",
            {
                "tenant_id": TENANT_A,
                "contract_id": contract_id,
                "reminder_stage": stage,
            },
        )
        assert r.success, r.error
        assert len(r.data["notified_ticket_ids"]) == 5, (
            f"{stage} 应向 5 部门推送"
        )
    # 共 4 × 5 = 20 条任务
    assert len(task_api.dispatched) == 20
    types = {d["task_type"] for d in task_api.dispatched}
    assert types == {"banquet_stage"}
    stages = {d["payload"]["reminder_stage"] for d in task_api.dispatched}
    assert stages == {"T-7d", "T-3d", "T-1d", "T-2h"}


# ─────────────────────────────────────────────────────────────────────────
# 6. 硬约束校验（margin + safety）
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_constraint_scope_margin_and_safety_enforced(
    agent: BanquetContractAgent,
) -> None:
    """constraint_scope = {'margin', 'safety'}，experience 豁免。"""
    assert BanquetContractAgent.constraint_scope == {"margin", "safety"}


@pytest.mark.asyncio
async def test_constraint_passes_with_normal_price_and_safe_batches(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
) -> None:
    """正常定价（毛利 45%）+ 食材批次 48h/36h 全部远离过期 → 三条约束全过。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    result = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 20,
            "total_amount_fen": 2_000_000,
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    assert result.success
    assert result.constraints_passed is True
    detail = result.constraints_detail
    assert "margin" in detail["scopes_checked"]
    # safety 有批次数据 → 也被校验
    assert "safety" in detail["scopes_checked"]


# ─────────────────────────────────────────────────────────────────────────
# 7. 决策留痕
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_log_written_for_every_action(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
) -> None:
    """每个 action 都会在 agent.decision_log 写一条留痕。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    gen = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "birthday",
            "tables": 3,
            "total_amount_fen": 80_000,
            "deposit_ratio": Decimal("0.20"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    assert gen.success
    contract_id = uuid.UUID(gen.data["contract_id"])
    await agent.run(
        "split_eo",
        {"tenant_id": TENANT_A, "contract_id": contract_id},
    )
    await agent.run(
        "route_approval",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
            "total_amount_fen": 80_000,
            "banquet_type": "birthday",
        },
    )
    # 至少 generate + split_eo + route_approval 共 3 条
    assert len(agent.decision_log) >= 3
    actions = [log["action"] for log in agent.decision_log]
    assert "generate_contract" in actions
    assert "split_eo" in actions
    assert "route_approval" in actions
    # 每条都有 decision_id + tenant_id + output_action
    for log in agent.decision_log:
        assert "decision_id" in log
        assert log["tenant_id"] == str(TENANT_A)
        assert log["agent_id"] == "banquet_contract_agent"
        assert "output_action" in log
        assert log["inference_layer"] == "cloud"


# ─────────────────────────────────────────────────────────────────────────
# 8. 豁免与审批链顺序
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_approval_rejects_writes_status_back_to_draft(
    agent: BanquetContractAgent,
    lead_api: FakeLeadApiClient,
) -> None:
    """审批驳回 → 合同退回 draft，status 字段可追溯。"""
    lead_id = next(iter(lead_api._payloads.keys()))
    gen = await agent.run(
        "generate_contract",
        {
            "tenant_id": TENANT_A,
            "lead_id": lead_id,
            "customer_id": uuid.uuid4(),
            "banquet_type": "wedding",
            "tables": 15,
            "total_amount_fen": 1_200_000,
            "deposit_ratio": Decimal("0.30"),
            "scheduled_date": date(2026, 10, 1),
        },
    )
    contract_id = uuid.UUID(gen.data["contract_id"])
    await agent.run(
        "route_approval",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
            "total_amount_fen": 1_200_000,
            "banquet_type": "wedding",
        },
    )
    reject = await agent.run(
        "route_approval",
        {
            "tenant_id": TENANT_A,
            "contract_id": contract_id,
            "total_amount_fen": 1_200_000,
            "banquet_type": "wedding",
            "approver_id": uuid.uuid4(),
            "approval_action": "reject",
            "notes": "客户未提供身份材料",
        },
    )
    assert reject.success
    assert reject.data["final_status"] == "draft"
