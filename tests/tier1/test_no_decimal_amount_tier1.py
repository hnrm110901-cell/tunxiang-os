"""Tier1 CI 守门测试 — 禁止新增 Numeric 金额字段违规

策略：
  1. 运行 AST 扫描器扫描 services/ 目录
  2. 当前已知违规存入 KNOWN_BASELINE（白名单）
  3. 断言：扫描结果 ⊆ KNOWN_BASELINE （新增违规直接 FAIL）
  4. P0-1/P0-2 修复 PR 合并后，从 KNOWN_BASELINE 中删除对应条目，CI 守门生效

如何递减 baseline：
  - 修复了某字段（改为 Integer）后，在 KNOWN_BASELINE 中删除该 tuple
  - 确认 pytest 仍绿后提交 PR

注意：KNOWN_BASELINE 内条目格式为 (relative_file_path, line, column_name)
  relative_file_path 相对于 services/ 父目录（即 services/tx-trade/... 形式）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 scripts/audit 在 sys.path 上
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNER_DIR = _REPO_ROOT / "scripts" / "audit"
if str(_SCANNER_DIR) not in sys.path:
    sys.path.insert(0, str(_SCANNER_DIR))

from scan_decimal_amount_columns import scan_directory  # noqa: E402

# ─── KNOWN_BASELINE ───────────────────────────────────────────────────────────
# 格式：(file_relative_to_repo_root, line, column_name)
# 如何递减：P0-X 修复 PR 合并后删除对应行，CI 自动升级为严格守门。
#
# 待 P0-1 修复（tx-trade discount_audit_log）：删除以下 3 条
#   services/tx-trade/src/models/discount_audit_log.py:43 original_amount
#   services/tx-trade/src/models/discount_audit_log.py:44 final_amount
#   services/tx-trade/src/models/discount_audit_log.py:45 discount_amount
#
# 待 P0-2 修复（tx-trade wine_storage）：删除以下 2 条
#   services/tx-trade/src/models/wine_storage.py:61 storage_price
#   services/tx-trade/src/models/wine_storage.py:92 price_at_trans
#
# 其余条目待后续专项 PR 修复后逐步递减。
KNOWN_BASELINE: frozenset[tuple[str, int, str]] = frozenset(
    [
        # ── tx-expense ──────────────────────────────────────────────────
        ("services/tx-expense/src/models/travel.py", 117, "total_mileage_km"),
        # ── tx-finance ──────────────────────────────────────────────────
        ("services/tx-finance/src/models/cost_snapshot.py", 56, "raw_material_cost"),
        ("services/tx-finance/src/models/cost_snapshot.py", 57, "labor_cost_allocated"),
        ("services/tx-finance/src/models/cost_snapshot.py", 59, "total_cost"),
        ("services/tx-finance/src/models/cost_snapshot.py", 62, "selling_price"),
        ("services/tx-finance/src/models/invoice.py", 66, "amount"),
        ("services/tx-finance/src/models/invoice.py", 67, "tax_amount"),
        ("services/tx-finance/src/models/voucher.py", 110, "total_amount"),
        # ── tx-member ───────────────────────────────────────────────────
        ("services/tx-member/src/models/stored_value_account.py", 85, "balance"),
        ("services/tx-member/src/models/stored_value_account.py", 91, "gift_balance"),
        ("services/tx-member/src/models/stored_value_account.py", 99, "total_recharged"),
        ("services/tx-member/src/models/stored_value_account.py", 105, "total_consumed"),
        ("services/tx-member/src/models/stored_value_account.py", 151, "amount"),
        ("services/tx-member/src/models/stored_value_account.py", 156, "gift_amount"),
        ("services/tx-member/src/models/stored_value_account.py", 164, "balance_before"),
        ("services/tx-member/src/models/stored_value_account.py", 169, "balance_after"),
        ("services/tx-member/src/models/stored_value_account.py", 174, "gift_balance_before"),
        ("services/tx-member/src/models/stored_value_account.py", 180, "gift_balance_after"),
        # ── tx-trade ────────────────────────────────────────────────────
        ("services/tx-trade/src/models/banquet_contract.py", 39, "deposit_ratio"),
        ("services/tx-trade/src/models/chef_performance_daily.py", 22, "dish_amount"),
        # 待 P0-1 修复后删除：
        ("services/tx-trade/src/models/discount_audit_log.py", 43, "original_amount"),
        ("services/tx-trade/src/models/discount_audit_log.py", 44, "final_amount"),
        ("services/tx-trade/src/models/discount_audit_log.py", 45, "discount_amount"),
        # 待 P0-2 修复后删除：
        ("services/tx-trade/src/models/wine_storage.py", 61, "storage_price"),
        ("services/tx-trade/src/models/wine_storage.py", 92, "price_at_trans"),
    ]
)


# ─── 测试 ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def scan_results() -> frozenset[tuple[str, int, str]]:
    """扫描 services/ 并返回 (file, line, column_name) 集合。"""
    services_root = _REPO_ROOT / "services"
    if not services_root.exists():
        pytest.skip(f"services 目录不存在: {services_root}")

    violations = scan_directory(services_root)
    return frozenset((v.file, v.line, v.column_name) for v in violations)


def test_no_new_decimal_amount_violations(scan_results: frozenset) -> None:
    """CI 守门：扫描结果必须是 KNOWN_BASELINE 的子集，禁止新增违规。

    如何修复失败：
      1. 确认新增违规确实需要修复（改为 Integer 类型）
      2. 如果是误报，在扫描脚本白名单中添加例外规则
      3. 禁止直接把新违规加入 KNOWN_BASELINE 而不修复业务代码
    """
    new_violations = scan_results - KNOWN_BASELINE

    assert not new_violations, (
        f"\n\n[Tier1 违规] 发现 {len(new_violations)} 个新增 Numeric 金额字段违规！\n"
        + "\n".join(
            f"  {file}:{line} {col}"
            for file, line, col in sorted(new_violations)
        )
        + "\n\n修复方法：将字段类型改为 Integer（单位：分/fen）。"
        + "\n详见：docs/audit/decimal-amount-violations-2026-05-07.md"
    )


def test_baseline_is_current_reality(scan_results: frozenset) -> None:
    """辅助测试：检测 KNOWN_BASELINE 中已被修复的条目（提醒删除 baseline 行）。

    此测试仅警告，不阻断 CI（用 xfail 会掩盖信息，改为 warning 打印）。
    当 P0-1/P0-2 PR 修复后，对应条目将不再出现在扫描结果，
    此时 baseline 中存在"幽灵条目"，需手动清理。
    """
    fixed_but_in_baseline = KNOWN_BASELINE - scan_results
    if fixed_but_in_baseline:
        # 打印提示，但不 fail —— 鼓励清理 baseline
        fixed_list = "\n".join(
            f"  {file}:{line} {col}"
            for file, line, col in sorted(fixed_but_in_baseline)
        )
        pytest.warns(
            UserWarning,
            match=".*",
        ) if False else None  # noqa: SIM210
        print(
            f"\n[INFO] {len(fixed_but_in_baseline)} 个 baseline 条目已被修复，"
            f"请从 KNOWN_BASELINE 中删除：\n{fixed_list}\n"
        )
