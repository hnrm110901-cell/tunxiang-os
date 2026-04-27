"""迁移链完整性测试 — v139 → v153

测试范围：
  - v151 / v152 / v153 新迁移文件的 revision 和 down_revision 字段正确性
  - v139 → v153 完整迁移链无间隙（v149 已知删除，跳过）
  - v150 的 down_revision 指向 v148（v149 被删除，链接绕过）
  - 所有版本文件均能成功 import，无语法错误

技术约束：
  - 不连接任何真实数据库
  - 不调用 op.execute()，仅验证 Python 模块结构
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────
# 辅助：动态 import 版本模块
# ─────────────────────────────────────────────────────────────────


def _import_version(version_label: str):
    """根据版本标签（如 'v151'）动态导入对应的迁移模块。

    搜索策略：先尝试 shared.db_migrations.versions.{file}，
    若失败则从文件系统扫描，找到包含该 version_label 的 .py 文件后 import。
    """
    import importlib.util
    import os

    versions_dir = os.path.join(os.path.dirname(__file__), "..", "versions")
    versions_dir = os.path.normpath(versions_dir)

    for fname in os.listdir(versions_dir):
        if fname.startswith(version_label + "_") and fname.endswith(".py"):
            fpath = os.path.join(versions_dir, fname)
            module_name = f"_migration_{version_label}"
            spec = importlib.util.spec_from_file_location(module_name, fpath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    raise ImportError(f"找不到版本 {version_label} 的迁移文件，目录：{versions_dir}")


# ─────────────────────────────────────────────────────────────────
# D3-A：Round 62-66 新迁移文件 revision 链正确性
# ─────────────────────────────────────────────────────────────────


def test_v151_revision_chain():
    """v151 的 down_revision 应为 v150。"""
    m = _import_version("v151")
    assert m.revision == "v151", f"v151.revision 应为 'v151'，实际: {m.revision}"
    assert m.down_revision == "v150", f"v151.down_revision 应为 'v150'，实际: {m.down_revision}"


def test_v152_revision_chain():
    """v152 的 down_revision 应为 v151。"""
    m = _import_version("v152")
    assert m.revision == "v152", f"v152.revision 应为 'v152'，实际: {m.revision}"
    assert m.down_revision == "v151", f"v152.down_revision 应为 'v151'，实际: {m.down_revision}"


def test_v153_revision_chain():
    """v153 的 down_revision 应为 v152。"""
    m = _import_version("v153")
    assert m.revision == "v153", f"v153.revision 应为 'v153'，实际: {m.revision}"
    assert m.down_revision == "v152", f"v153.down_revision 应为 'v152'，实际: {m.down_revision}"


# ─────────────────────────────────────────────────────────────────
# D3-B：v139 → v153 完整迁移链连续性
# ─────────────────────────────────────────────────────────────────

# v149 已知被删除，v150 直接指向 v148
# 链：v139→v140→v141→v142→v143→v144→v145→v146→v147→v148→v150→v151→v152→v153
_EXPECTED_CHAIN = [
    ("v139", "v138"),
    ("v140", "v139"),
    ("v141", "v140"),
    ("v142", "v141"),
    ("v143", "v142"),
    ("v144", "v143"),
    ("v145", "v144"),
    ("v146", "v145"),
    ("v147", "v146"),
    ("v148", "v147"),
    ("v150", "v148"),  # v149 已删除，v150 跳接 v148
    ("v151", "v150"),
    ("v152", "v151"),
    ("v153", "v152"),
]


def test_migration_chain_no_gaps():
    """验证 v139 到 v153 迁移链无间隙（v149 除外，已知删除）。

    对每个版本验证：
      1. 文件能被成功 import（无语法错误）
      2. revision 字段与预期一致
      3. down_revision 字段指向正确的前一个版本
    """
    errors = []
    for revision, expected_down in _EXPECTED_CHAIN:
        try:
            m = _import_version(revision)
        except ImportError as e:
            errors.append(f"{revision}: 文件找不到 — {e}")
            continue
        except Exception as e:
            errors.append(f"{revision}: import 失败 — {type(e).__name__}: {e}")
            continue

        # 检查 revision 字段
        actual_rev = getattr(m, "revision", None)
        if actual_rev != revision:
            errors.append(f"{revision}: revision 字段不匹配，期望 '{revision}' 实际 '{actual_rev}'")

        # 检查 down_revision 字段（可能是 str 或 Union[str, None]）
        actual_down = getattr(m, "down_revision", "MISSING")
        if actual_down != expected_down:
            errors.append(f"{revision}: down_revision 不匹配，期望 '{expected_down}' 实际 '{actual_down}'")

    assert not errors, "迁移链验证失败：\n" + "\n".join(errors)


def test_no_v149_file():
    """确认 v149 迁移文件确实不存在（已知删除，不应误建）。"""
    import os

    versions_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "versions"))
    v149_files = [f for f in os.listdir(versions_dir) if f.startswith("v149") and f.endswith(".py")]
    assert len(v149_files) == 0, f"v149 迁移文件不应存在，但发现: {v149_files}"


# ─────────────────────────────────────────────────────────────────
# D3-C：v151 结构验证（有 upgrade / downgrade 函数）
# ─────────────────────────────────────────────────────────────────


def test_v151_has_upgrade_and_downgrade():
    """v151 迁移文件应定义 upgrade() 和 downgrade() 函数。"""
    m = _import_version("v151")
    assert callable(getattr(m, "upgrade", None)), "v151 缺少 upgrade() 函数"
    assert callable(getattr(m, "downgrade", None)), "v151 缺少 downgrade() 函数"


def test_v152_has_upgrade_and_downgrade():
    """v152 迁移文件应定义 upgrade() 和 downgrade() 函数。"""
    m = _import_version("v152")
    assert callable(getattr(m, "upgrade", None)), "v152 缺少 upgrade() 函数"
    assert callable(getattr(m, "downgrade", None)), "v152 缺少 downgrade() 函数"


def test_v153_has_upgrade_and_downgrade():
    """v153 迁移文件应定义 upgrade() 和 downgrade() 函数。"""
    m = _import_version("v153")
    assert callable(getattr(m, "upgrade", None)), "v153 缺少 upgrade() 函数"
    assert callable(getattr(m, "downgrade", None)), "v153 缺少 downgrade() 函数"


# ─────────────────────────────────────────────────────────────────
# D3-D：v150 跳过 v149 的链接验证
# ─────────────────────────────────────────────────────────────────


def test_v150_jumps_over_v149():
    """v149 被删除，v150.down_revision 应直接指向 v148（不是 v149）。"""
    m = _import_version("v150")
    assert m.down_revision == "v148", f"v150.down_revision 应为 'v148'（v149 已删除），实际: {m.down_revision}"
