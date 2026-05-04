"""Tier 1 — 反退化：禁止 datetime.utcnow() 重新潜入生产路径

PG.2 第二轮 codemod 把项目内余下 17 个 datetime.utcnow() 全部替换为
datetime.now(timezone.utc)。本测试守门，防止后续 PR 再次引入。

为什么：
  - Python 3.12 已 deprecate datetime.utcnow()（返回 naive datetime）
  - tx-trade 路径中 naive datetime 与 v147 events.recorded_at(TIMESTAMPTZ)
    比较时会被隐式当作本地时区，跨时区门店将得到错误的事件窗口
  - JSONB 序列化丢时区导致跨服务对账不一致

扫描范围：
  - services/         所有 .py（业务源码）
  - shared/adapters/  所有 .py（旧系统入站）
  - shared/events/    所有 .py（事件总线核心）
  - edge/             所有 .py（边缘服务）

允许出现的位置（白名单）：
  - 测试文件本身（test_no_utcnow_regression_tier1.py — 字面字符串）
  - scripts/codemod_utcnow.py（codemod 模板，正则字面量）
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

_SCAN_DIRS = (
    "services",
    "shared/adapters",
    "shared/events",
    "edge",
)

_ALLOWLIST = {
    # 测试文件自身（含本文件的字面字符串）
    "services/tx-trade/src/tests/test_no_utcnow_regression_tier1.py",
    # PJ.3 守门测试 docstring 含字面 datetime.utcnow() 字符串描述场景
    "services/tx-trade/src/tests/test_codemod_tzinfo_residue_pj3_tier1.py",
}


def _scan_one_dir(rel_dir: str) -> list[tuple[Path, int, str]]:
    """返回 (path, line_no, line) 三元组列表 — 命中即违例。"""
    base = _REPO_ROOT / rel_dir
    if not base.is_dir():
        return []

    hits: list[tuple[Path, int, str]] = []
    for py in base.rglob("*.py"):
        rel = py.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWLIST:
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "datetime.utcnow()" not in text:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if "datetime.utcnow()" in line:
                hits.append((py, i, line.strip()))
    return hits


@pytest.mark.parametrize("rel_dir", _SCAN_DIRS)
def test_no_datetime_utcnow_in_production_paths(rel_dir: str) -> None:
    """生产路径不得再出现 datetime.utcnow()（已 deprecated）。"""
    hits = _scan_one_dir(rel_dir)
    if hits:
        msg_lines = [f"{p.relative_to(_REPO_ROOT)}:{ln} → {src}" for p, ln, src in hits]
        pytest.fail(
            f"在 {rel_dir}/ 发现 {len(hits)} 处 datetime.utcnow() 残留 — "
            f"请用 datetime.now(timezone.utc) 替换：\n  - " + "\n  - ".join(msg_lines)
        )


def test_codemod_script_self_documented() -> None:
    """codemod 工具脚本必须存在 — 后续清理直接调用它。"""
    script = _REPO_ROOT / "scripts" / "codemod_utcnow.py"
    assert script.is_file(), f"codemod 脚本缺失：{script}"
