"""[Tier1] Order(sales_channel=) → order_type / sales_channel_id 修复红测试

关联决策：DEVLOG 决策 79（5/9 上午）— scan_order_service 暴露 Order(sales_channel=...)
TypeError，深扒发现 cashier_engine.py 4 处同款（POS 收银核心路径）。

红线（防止徐记海鲜收银台 500）：
  1. 普通堂食开台 (POST /orders → engine.open_table) 不能 TypeError
  2. 零售订单 (engine.create_retail_order) 不能 TypeError
  3. 预订单 (engine.create_pre_order) 不能 TypeError
  4. 订单序列化前端 (.sales_channel 读字段) 必须改 .sales_channel_id

本套件通过 AST 静态扫源码 + Order 实体契约，覆盖 cashier_engine.py 4 处全清零。
不做 DB mock — 静态保证比 mock 更稳，AST 失败即生产真崩。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from shared.ontology.src.entities import Order
from shared.ontology.src.sales_channel import DEFAULT_CHANNELS

_SERVICES_DIR = Path(__file__).resolve().parents[1] / "services"
CASHIER_ENGINE_PATH = _SERVICES_DIR / "cashier_engine.py"
ORDER_SERVICE_PATH = _SERVICES_DIR / "order_service.py"
GUARDED_FILES = [CASHIER_ENGINE_PATH, ORDER_SERVICE_PATH]


# ─── 1. Order 实体契约 ────────────────────────────────────────────────


class TestOrderEntityContract:
    def test_order_has_sales_channel_id_not_legacy_sales_channel(self) -> None:
        """Order 类只有 sales_channel_id（FK 到 SalesChannel 配置表），无 sales_channel。"""
        assert hasattr(Order, "sales_channel_id"), "sales_channel_id 列丢失"
        assert not hasattr(Order, "sales_channel"), (
            "Order.sales_channel 仍存在 — 实体未完成重命名（应只剩 sales_channel_id）"
        )

    def test_order_has_order_type_field(self) -> None:
        """Order 类有 order_type 字段（dine_in/takeaway/delivery/retail/catering/banquet）。"""
        assert hasattr(Order, "order_type"), "order_type 字段缺失"


# ─── 2. cashier_engine.py 源码 AST 静态扫 ───────────────────────────


def _parse(path: Path) -> ast.Module:
    src = path.read_text(encoding="utf-8")
    return ast.parse(src, filename=str(path))


def _find_order_constructor_kwargs(tree: ast.Module) -> list[tuple[int, list[str]]]:
    """所有 Order(...) 构造调用的 kwarg 名列表 + 行号。"""
    results: list[tuple[int, list[str]]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Order"
        ):
            kwargs = [kw.arg for kw in node.keywords if kw.arg is not None]
            results.append((node.lineno, kwargs))
    return results


def _find_dot_sales_channel_reads(tree: ast.Module) -> list[int]:
    """所有 .sales_channel（非 _id 后缀）属性访问的行号。"""
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "sales_channel":
            lines.append(node.lineno)
    return lines


class TestOrderInstantiationSourceClean:
    """守门 cashier_engine.py + order_service.py — 不能用旧 sales_channel= kwarg / 属性读。"""

    @pytest.mark.parametrize("path", GUARDED_FILES, ids=lambda p: p.name)
    def test_no_sales_channel_kwarg_in_order_constructor(self, path: Path) -> None:
        """守门文件任何 Order(...) 调用都不能含 sales_channel= kwarg。"""
        tree = _parse(path)
        offenders = [
            (lineno, kwargs)
            for lineno, kwargs in _find_order_constructor_kwargs(tree)
            if "sales_channel" in kwargs
        ]
        assert not offenders, (
            f"{path.name} 仍有 Order(sales_channel=...) 调用，runtime TypeError "
            f"(收银/零售/预订单/创建订单全炸): {offenders}"
        )

    @pytest.mark.parametrize("path", GUARDED_FILES, ids=lambda p: p.name)
    def test_no_legacy_sales_channel_attribute_read(self, path: Path) -> None:
        """守门文件不能读 .sales_channel — 必须用 .sales_channel_id。"""
        tree = _parse(path)
        offenders = _find_dot_sales_channel_reads(tree)
        assert not offenders, (
            f"{path.name} 仍有 .sales_channel 属性读取（前端会拿到 None / "
            f"AttributeError），行号: {offenders}"
        )


# ─── 3. SalesChannel 配置 pre-seeded ──────────────────────────────


class TestSalesChannelPreSeeded:
    """cashier_engine.py:1475/1615 改 sales_channel_id 必须用配置表已 seed 的 channel_id。"""

    @pytest.fixture
    def channel_ids(self) -> set[str]:
        return {ch.channel_id for ch in DEFAULT_CHANNELS}

    def test_ch_dine_in_seeded(self, channel_ids: set[str]) -> None:
        """ch_dine_in 必须 pre-seeded（cashier_engine create_pre_order 用）。"""
        assert "ch_dine_in" in channel_ids

    def test_ch_retail_seeded(self, channel_ids: set[str]) -> None:
        """ch_retail 必须 pre-seeded（cashier_engine create_retail_order 用）。"""
        assert "ch_retail" in channel_ids
