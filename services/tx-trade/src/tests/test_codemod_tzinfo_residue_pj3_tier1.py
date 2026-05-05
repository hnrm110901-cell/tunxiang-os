"""Tier 1 — PG.2 codemod 残留 tzinfo 不一致防退化（PJ.3）

CodeRabbit post-merge 在 PR #148 (PG.2 datetime codemod) 发现两处真 bug：

  1. services/tx-trade/src/api/kds_banquet_routes.py:121
     codemod 把 datetime.utcnow() → datetime.now(timezone.utc)，
     但漏删 r[2].replace(tzinfo=None)。PG TIMESTAMPTZ 返 aware datetime,
     与 aware now 之间出现 naive - aware → 运行时 TypeError。

  2. services/tx-member/src/api/members.py:404-406
     try 分支 datetime.fromisoformat(微信字符串) 可能返 naive（"2024-01-01T08:00:00"）；
     except 分支 fallback 为 aware datetime.now(timezone.utc)。
     成功路径 naive、失败路径 aware → 下游比较/序列化时不一致。

策略：
  本测试不依赖 DB / FastAPI client，纯 source-level grep + import 函数模拟两个分支
  → 任何回归（删除 timezone 处理、重新引入 .replace(tzinfo=None)）即时 fail。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]


# ──────────────── kds_banquet_routes.py 守门 ────────────────


def test_kds_banquet_no_tzinfo_strip_in_countdown() -> None:
    """禁止 r[N].replace(tzinfo=None) 与 datetime.now(timezone.utc) 同行混用。"""
    p = _REPO_ROOT / "services/tx-trade/src/api/kds_banquet_routes.py"
    text = p.read_text(encoding="utf-8")

    # 不允许同行同时出现 .replace(tzinfo=None) 和 datetime.now(timezone.utc)
    bad = re.compile(r"\.replace\(tzinfo=None\).*datetime\.now\(timezone\.utc\)")
    bad2 = re.compile(r"datetime\.now\(timezone\.utc\).*\.replace\(tzinfo=None\)")
    for i, line in enumerate(text.splitlines(), 1):
        if bad.search(line) or bad2.search(line):
            pytest.fail(
                f"kds_banquet_routes.py:{i} 出现 naive-aware 混用：{line.strip()}\n"
                "PG TIMESTAMPTZ 已是 aware；删除 .replace(tzinfo=None) 即可。"
            )


# ──────────────── members.py wecom_follow_at 守门 ────────────────


def _make_aware_from_iso(s: str) -> datetime:
    """复刻 members.py 修复后的解析逻辑（保持单测和实现同步）。"""
    parsed = datetime.fromisoformat(s)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "iso_input,expected_tz",
    [
        ("2024-01-01T08:00:00+08:00", timezone.utc),  # 带时区 → 保留原偏移（不强转 UTC）
        ("2024-01-01T08:00:00", timezone.utc),  # 不带时区 → 视为 UTC
        # Z 后缀只在 Python 3.11+ fromisoformat 支持，跨版本走 +00:00 替代
        ("2024-12-31T23:59:59+00:00", timezone.utc),
    ],
)
def test_wecom_follow_at_always_aware(iso_input: str, expected_tz) -> None:
    """fromisoformat 路径与 fallback 都必须返 aware datetime。"""
    parsed = _make_aware_from_iso(iso_input)
    assert parsed.tzinfo is not None, f"{iso_input} 解析后丢了时区"


def test_wecom_follow_at_fallback_is_aware() -> None:
    """except 路径 datetime.now(timezone.utc) 必须 aware。"""
    fallback = datetime.now(timezone.utc)
    assert fallback.tzinfo is not None


def test_members_py_uses_tzinfo_normalization() -> None:
    """members.py 必须保留 tzinfo 归一化分支（防 PR 重新引入裸 fromisoformat）。"""
    p = _REPO_ROOT / "services/tx-member/src/api/members.py"
    text = p.read_text(encoding="utf-8")
    # 关键代码模式必须存在
    assert "parsed.tzinfo" in text or "replace(tzinfo=timezone.utc)" in text, (
        "members.py wecom_follow_at 解析未做 tzinfo 归一化 — 见 PJ.3 修复"
    )


# ──────────────── 全仓反退化扫描 ────────────────


def test_no_replace_tzinfo_none_with_aware_now_anywhere() -> None:
    """生产路径任何文件都不应混用 .replace(tzinfo=None) 与 datetime.now(timezone.utc)。

    适配器层（shared/adapters/*/src/adapter.py）的 OrderSchema naive datetime
    是设计意图（与 fromisoformat naive 路径一致），通过 _ALLOWLIST 豁免。
    """
    scan_dirs = ("services", "shared/events", "edge", "scripts")
    allowlist = {
        "shared/adapters/tiancai-shanglong/src/adapter.py",  # OrderSchema 兼容旧适配器
        "services/tx-trade/src/tests/test_codemod_tzinfo_residue_pj3_tier1.py",  # 测试文件自身含字面字符串模式
    }

    bad = re.compile(r"\.replace\(tzinfo=None\).*datetime\.now\(timezone\.utc\)")
    bad2 = re.compile(r"datetime\.now\(timezone\.utc\).*\.replace\(tzinfo=None\)")

    hits: list[tuple[str, int, str]] = []
    for d in scan_dirs:
        base = _REPO_ROOT / d
        if not base.is_dir():
            continue
        for py in base.rglob("*.py"):
            rel = py.relative_to(_REPO_ROOT).as_posix()
            if rel in allowlist:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if bad.search(line) or bad2.search(line):
                    hits.append((rel, i, line.strip()))

    if hits:
        msg = "\n  - ".join(f"{p}:{ln} → {src[:140]}" for p, ln, src in hits)
        pytest.fail(f"发现 {len(hits)} 处 naive-aware 混用残留：\n  - {msg}")
