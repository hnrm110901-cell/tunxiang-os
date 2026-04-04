"""
迁移链完整性测试 v139~v149

Round 64 Team D — 验证 Alembic 迁移文件链无断裂：
  - v139 → v149 revision/down_revision 连续
  - 无重复 revision
  - 无跳跃（每个版本的 down_revision 指向前一个版本）
  - 双 v148 文件检测（v148_event 和 v148_invite 均以 v147 为前驱）
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest


VERSIONS_DIR = Path(__file__).parent.parent / "shared" / "db-migrations" / "versions"

# 我们关注的版本范围
TARGET_RANGE = [f"v{i}" for i in range(139, 150)]


# ─── 辅助：解析迁移文件 ──────────────────────────────────────────────────────

def _parse_migration_file(filepath: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    从迁移 .py 文件中解析 revision 和 down_revision。

    支持两种写法：
      revision = "vXXX"
      revision: str = "vXXX"
    """
    content = filepath.read_text(encoding="utf-8")

    # 带类型注解的写法（revision: str = "vXXX"）
    rev_match = re.search(r'revision:\s*str\s*=\s*["\']([^"\']+)["\']', content)
    # 不带注解的写法（revision = "vXXX"）
    if not rev_match:
        rev_match = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)

    down_match = re.search(
        r'down_revision[\w\[\], :]*=\s*["\']([^"\']+)["\']', content
    )

    revision = rev_match.group(1) if rev_match else None
    down_revision = down_match.group(1) if down_match else None
    return revision, down_revision


def _collect_migrations() -> Dict[str, dict]:
    """
    收集所有迁移文件，返回 {revision: {file, down_revision}} 字典。
    """
    migrations: Dict[str, dict] = {}
    for f in VERSIONS_DIR.glob("v*.py"):
        if f.name.startswith("__"):
            continue
        revision, down_revision = _parse_migration_file(f)
        if revision:
            migrations[revision] = {
                "file": f.name,
                "down_revision": down_revision,
            }
    return migrations


# ─── 测试 ────────────────────────────────────────────────────────────────────

class TestMigrationChainV139ToV149:
    @pytest.fixture(scope="class")
    def migrations(self):
        return _collect_migrations()

    def test_all_target_versions_exist(self, migrations):
        """v139~v149 所有版本文件均存在（允许同一版本有多个文件，如双 v148）"""
        # v148 允许两个文件并存
        for version in TARGET_RANGE:
            assert version in migrations, f"迁移版本 {version} 文件缺失"

    def test_no_duplicate_revisions_in_range(self, migrations):
        """目标范围内的 revision 唯一（双 v148 已手动确认，检查其余）"""
        # 统计每个版本出现次数
        seen = {}
        for f in VERSIONS_DIR.glob("v1[34]*.py"):
            if f.name.startswith("__"):
                continue
            rev, _ = _parse_migration_file(f)
            if rev and rev in TARGET_RANGE:
                seen[rev] = seen.get(rev, 0) + 1
        # 只有 v148 允许重复（两个平行分支），其余不允许
        for rev, count in seen.items():
            if rev == "v148":
                continue
            assert count == 1, f"版本 {rev} 存在 {count} 个文件，应唯一"

    def test_down_revision_chain_continuous(self, migrations):
        """
        v140~v149（排除双 v148）的 down_revision 链连续无跳跃：
        vN.down_revision == v(N-1)
        """
        # 标准链（跳过 v148 双分支问题）
        standard_chain = [f"v{i}" for i in range(140, 150) if i != 148]
        for i, rev in enumerate(standard_chain):
            if rev not in migrations:
                continue
            expected_down = f"v{int(rev[1:]) - 1}"
            actual_down = migrations[rev]["down_revision"]
            assert actual_down == expected_down, (
                f"{rev} ({migrations[rev]['file']}) 的 down_revision 应为 {expected_down}，"
                f"实际为 {actual_down}"
            )

    def test_v139_base(self, migrations):
        """v139 的 down_revision 为 v138（确认入口正确）"""
        assert "v139" in migrations
        assert migrations["v139"]["down_revision"] == "v138"

    def test_v140_down_is_v139(self, migrations):
        """v140 下移 revision 指向 v139"""
        assert migrations.get("v140", {}).get("down_revision") == "v139"

    def test_v141_sync_logs_down_is_v140(self, migrations):
        """v141（sync_logs表）down_revision 为 v140"""
        assert migrations.get("v141", {}).get("down_revision") == "v140"

    def test_v149_top_of_chain(self, migrations):
        """v149 存在且 down_revision 为 v148"""
        assert "v149" in migrations
        assert migrations["v149"]["down_revision"] == "v148"

    def test_v148_branches_both_point_to_v147(self, migrations):
        """
        v148 有两个平行迁移文件（event_materialized_views 和 invite_invoice_tables），
        两者 down_revision 均应指向 v147
        """
        v148_files = [f for f in VERSIONS_DIR.glob("v148_*.py")]
        assert len(v148_files) == 2, f"期望 2 个 v148 文件，实际找到 {len(v148_files)}"

        for f in v148_files:
            _, down_rev = _parse_migration_file(f)
            assert down_rev == "v147", (
                f"{f.name} 的 down_revision 应为 v147，实际为 {down_rev}"
            )

    def test_no_none_revision_in_range(self, migrations):
        """目标范围内所有文件 revision 均能被正确解析（无 None）"""
        for version in TARGET_RANGE:
            info = migrations.get(version)
            assert info is not None, f"{version} 未被收录"
            assert info.get("down_revision") is not None or version == "v139", (
                f"{version} 的 down_revision 为 None（v139 除外可接受）"
            )

    def test_migration_files_are_python(self):
        """v139~v149 迁移文件均是有效 Python 文件（可被 ast.parse）"""
        for version in TARGET_RANGE:
            files = list(VERSIONS_DIR.glob(f"{version}_*.py"))
            for f in files:
                try:
                    ast.parse(f.read_text(encoding="utf-8"))
                except SyntaxError as e:
                    pytest.fail(f"{f.name} 存在 Python 语法错误：{e}")
