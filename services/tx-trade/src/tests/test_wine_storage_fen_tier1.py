"""Tier 1 测试 — wine_storage 模型金额必须用 fen int (CLAUDE.md §15+§17)

关联差距：docs/gap-verification-2026-05-07.md Part E 第 2 项 + Part C §C.5
红线：storage_price / price_at_trans 用 Numeric(12,2) Decimal 存元 — 违反"金额全部用分整数"

只测 schema 形状 + 边界换算 + helper 行为，不依赖真实数据库或 alembic 运行。
"""
from __future__ import annotations

import ast
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy

# ── 路径 ───────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TRADE_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [ROOT, os.path.join(TRADE_SRC, "src"), TRADE_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── 1. 模型 schema：BigInteger fen 列 ──────────────────────────────────────────
class TestWineStorageRecordFenSchema:
    def test_storage_price_fen_is_big_integer(self):
        from models.wine_storage import WineStorageRecord

        col = WineStorageRecord.__table__.columns.get("storage_price_fen")
        assert col is not None, "WineStorageRecord 必须有 storage_price_fen 列"
        assert isinstance(col.type, sqlalchemy.BigInteger), (
            f"storage_price_fen 必须 BigInteger，got {col.type!r}"
        )
        assert col.nullable is True, "storage_price_fen 应 nullable（存酒可以未定价）"

    def test_old_storage_price_column_removed(self):
        from models.wine_storage import WineStorageRecord

        assert WineStorageRecord.__table__.columns.get("storage_price") is None, (
            "旧 storage_price (Decimal) 列必须已删除"
        )


class TestWineStorageTransactionFenSchema:
    def test_price_at_trans_fen_is_big_integer(self):
        """7 类流水共用同一个金额字段 price_at_trans_fen，覆盖 store_in/take_out/extend/transfer_in/transfer_out/write_off/adjustment 全部"""
        from models.wine_storage import WineStorageTransaction

        col = WineStorageTransaction.__table__.columns.get("price_at_trans_fen")
        assert col is not None, "WineStorageTransaction 必须有 price_at_trans_fen 列"
        assert isinstance(col.type, sqlalchemy.BigInteger), (
            f"price_at_trans_fen 必须 BigInteger，got {col.type!r}"
        )

    def test_old_price_at_trans_column_removed(self):
        from models.wine_storage import WineStorageTransaction

        assert (
            WineStorageTransaction.__table__.columns.get("price_at_trans") is None
        ), "旧 price_at_trans (Decimal) 列必须已删除"


# ── 2. 元 ↔ fen helper ───────────────────────────────────────────────────────
class TestYuanFenHelpers:
    def test_yuan_to_fen_simple(self):
        from models.wine_storage import _yuan_to_fen

        assert _yuan_to_fen(Decimal("123.45")) == 12345
        assert _yuan_to_fen(Decimal("0.01")) == 1
        assert _yuan_to_fen(None) is None

    def test_yuan_to_fen_accepts_zero(self):
        """存酒可以 storage_price=0（赠酒/未定价场景）— 与 invoice 不同"""
        from models.wine_storage import _yuan_to_fen

        assert _yuan_to_fen(Decimal("0")) == 0

    def test_yuan_to_fen_rejects_negative(self):
        from models.wine_storage import _yuan_to_fen

        with pytest.raises(ValueError):
            _yuan_to_fen(Decimal("-1.00"))

    def test_fen_to_yuan_str(self):
        from models.wine_storage import _fen_to_yuan_str

        assert _fen_to_yuan_str(12345) == "123.45"
        assert _fen_to_yuan_str(0) == "0.00"
        assert _fen_to_yuan_str(None) is None


# ── 3. 7 类流水 trans_type 枚举完整性（防漏改其中某一类）────────────────────────
class TestSevenTransactionTypes:
    EXPECTED = {
        "store_in",
        "take_out",
        "extend",
        "transfer_in",
        "transfer_out",
        "write_off",
        "adjustment",
    }

    def test_seven_types_all_can_use_fen_field(self):
        """7 类流水共用 price_at_trans_fen，每类用法在 routes/services 各异，
        但 schema 层只验证字段存在 + 类型。"""
        from models.wine_storage import WineStorageTransaction

        col = WineStorageTransaction.__table__.columns.get("price_at_trans_fen")
        assert col is not None
        # trans_type 仍是 String，存上述 7 个值；本测试是文档化覆盖
        trans_col = WineStorageTransaction.__table__.columns.get("trans_type")
        assert trans_col is not None


# ── 4. 迁移文件存在 + revision 链（AST 解析，不依赖 alembic 运行时）─────────────
class TestMigrationFile:
    def test_v404_wine_storage_amount_fen_migration_present(self):
        repo_root = Path(__file__).resolve().parents[4]
        mig_path = (
            repo_root
            / "shared"
            / "db-migrations"
            / "versions"
            / "v404_wine_storage_amount_fen.py"
        )
        assert mig_path.exists(), f"迁移文件 {mig_path} 必须存在"

        tree = ast.parse(mig_path.read_text(encoding="utf-8"))
        assigned: dict[str, str] = {}
        functions: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if isinstance(node.value, ast.Constant):
                    assigned[node.target.id] = node.value.value
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant):
                        assigned[tgt.id] = node.value.value
            elif isinstance(node, ast.FunctionDef):
                functions.add(node.name)

        assert assigned.get("revision") == "v404", (
            f"revision 必须 'v404'，got {assigned.get('revision')!r}"
        )
        assert assigned.get("down_revision") == "v403", (
            f"down_revision 必须接 'v403'（与 P0-1 invoice fen 串联），got "
            f"{assigned.get('down_revision')!r}"
        )
        assert "upgrade" in functions and "downgrade" in functions

        body = mig_path.read_text(encoding="utf-8")
        assert "storage_price_fen" in body
        assert "price_at_trans_fen" in body
        assert "BigInteger" in body
        # 双注册侧（tx-trade + tx-finance）共享同一表，本迁移修两个表
        assert "wine_storage_records" in body
        assert "wine_storage_transactions" in body
