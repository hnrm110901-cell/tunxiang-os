"""Alembic 迁移链完整性 Tier 1 测试 — 全量静态扫描

测试范围（Tier 1：DB schema integrity）：
  1. 无重复 revision ID（alembic 拒绝加载重复 ID）
  2. 无 dangling down_revision（每个引用都能在 versions/ 找到对应 revision）
  3. 唯一 head（多 head 让 `alembic upgrade head` 拒绝执行）
  4. 单一 root（`down_revision=None` 只允许一个）

技术约束：
  - 不连接任何真实数据库
  - 不 import 迁移模块（504 文件 import 开销过大）
  - 仅做正则扫描验证 revision/down_revision 字段
  - 跳过 .py.disabled 文件

为什么是 Tier 1：
  - 任一项失败 = `alembic upgrade head` 在新 DB 上跑不通
  - 直接阻塞 CI 真 PG 反测、demo 环境部署、生产新机房启动
"""

from __future__ import annotations

import collections
import os
import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).parent.parent / "versions"

_REV_RE = re.compile(r'^revision(?:\s*:\s*str)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_DOWN_RE = re.compile(
    r'^down_revision[^=\n]*=\s*(.+?)(?=\n[a-z_]+\s*[:=]|\nbranch_labels|\ndepends_on|\Z)',
    re.MULTILINE | re.DOTALL,
)


def _scan_versions():
    """扫描所有 versions/*.py 文件，返回 {revision: [(down_revisions, file_path)]}。

    重复 revision 用 list 容纳（不直接合并，便于报错）。
    """
    versions: dict[str, list[tuple[list[str], str]]] = collections.defaultdict(list)
    for entry in sorted(os.listdir(VERSIONS_DIR)):
        if not entry.endswith(".py") or entry.endswith(".disabled"):
            continue
        path = VERSIONS_DIR / entry
        src = path.read_text()
        rev_m = _REV_RE.search(src)
        if not rev_m:
            continue
        rev = rev_m.group(1)
        down_match = _DOWN_RE.search(src)
        downs: list[str] = []
        if down_match:
            body = down_match.group(1).strip()
            if not body.startswith("None"):
                downs = re.findall(r'["\']([^"\']+)["\']', body)
        versions[rev].append((downs, str(path)))
    return versions


def test_no_duplicate_revision_ids():
    """没有两个文件声明同一个 revision ID。

    alembic 加载阶段会因 dup ID 抛 `Multiple revisions are present` 并拒绝运行。
    """
    versions = _scan_versions()
    dups = {rev: [p for _, p in entries] for rev, entries in versions.items() if len(entries) > 1}
    assert not dups, "存在重复 revision ID:\n" + "\n".join(
        f"  {rev}: {[os.path.basename(p) for p in paths]}" for rev, paths in dups.items()
    )


def test_no_dangling_down_revisions():
    """每个 down_revision 字符串都能在所有 revision 集合中找到。

    dangling 让 alembic 在 walk 链路时抛 `ResolutionError: Can't locate revision`。
    """
    versions = _scan_versions()
    all_revs = set(versions.keys())
    dangling: list[str] = []
    for rev, entries in versions.items():
        for downs, path in entries:
            for d in downs:
                if d not in all_revs:
                    dangling.append(f"  {rev} ({os.path.basename(path)}) -> {d!r}")
    assert not dangling, "存在 dangling down_revision:\n" + "\n".join(dangling)


def test_single_head():
    """链路只有一个 head（alembic upgrade head 才能确定地走到唯一终点）。

    多 head 通常是历史合并未完成；用 merge migration（多元素 down_revision tuple）
    收敛到单 head 是 alembic 标准做法（参考 v397/v398）。
    """
    versions = _scan_versions()
    children: dict[str, list[str]] = collections.defaultdict(list)
    for rev, entries in versions.items():
        for downs, _ in entries:
            for d in downs:
                children[d].append(rev)
    heads = sorted([rev for rev in versions if not children.get(rev)])
    assert len(heads) == 1, f"期望 1 个 head，实际 {len(heads)}: {heads}"


def test_single_root():
    """链路只有一个 root（down_revision=None 只允许一个）。

    多 root 通常是误删迁移导致的孤立子链。
    """
    versions = _scan_versions()
    roots = sorted(
        [
            rev
            for rev, entries in versions.items()
            if all(not downs for downs, _ in entries)
        ]
    )
    assert len(roots) == 1, f"期望 1 个 root，实际 {len(roots)}: {roots}"
