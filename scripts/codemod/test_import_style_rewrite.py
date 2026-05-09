#!/usr/bin/env python3
"""scripts/codemod/test_import_style_rewrite.py — #298 Phase 1 scanner

Detect (and in Phase 2 rewrite) test-file import styles to unify on full-path form.

# 病灶（来自 issue #298）

测试文件以两种风格混用 import 同一磁盘模块：

  - 裸 from-import： from services.cashier_engine import ...
                    from api.routes import ...
                    from models.tables import ...
  - 裸 import：     import api.cashier_routes as _cashier_mod   (#318 follow-up 补抓)
                    import services.payment_service
  - 全路径：        from services.tx_trade.src.services.cashier_engine import ...
                    import services.tx_trade.src.api.foo as _full

两种都通过 conftest.py 的 namespace package 魔法 resolve 到同一 .py 文件，但 sys.modules
key 不同 → SQLAlchemy 共享 metadata 时 "Table 'X' is already defined" → PR #287 加
extend_existing band-aid 兜住。本 codemod 走 issue #298 选项 B：所有裸 import → 全路径，
统一后移除 band-aid。

# 执行阶段

  - Phase 1 (本 PR)：扫描 + 生成 baseline 报告。无文件修改。
  - Phase 2 (后续 stacked PR)：--apply 入口实际改写，≤ 20 文件/PR + Tier 1 Gate 全绿/PR。
  - Phase 3：所有 stacked PR merged 后移除 services/tx-trade/src/models/tables.py 的
    extend_existing=True band-aid (PR #287)，验 Tier 1 Gate 仍 green。

# 用法

  python3 scripts/codemod/test_import_style_rewrite.py
  python3 scripts/codemod/test_import_style_rewrite.py --out docs/codemod/baseline.md
  python3 scripts/codemod/test_import_style_rewrite.py --apply --service tx-trade   # Phase 2

# 启发式

裸 import：from <NS>.<SINGLE_TOKEN> import ...   其中 NS ∈ {services, api, models, repositories}
全路径：    from services.<svc>.src.<subpkg>.<rest> import ...

测试文件来源：services/<svc-with-dash>/{src/tests,tests}/**/test_*.py 或 *_test.py 或 conftest.py

每个裸 import 提议改写：
  from <NS>.<X> import ... → from services.<svc-with-underscore>.src.<NS>.<X> import ...
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# ─── 启发式常量 ──────────────────────────────────────────────────────────────

# 需要改写的裸命名空间（conftest.py 通过 namespace package magic 让其可解析）
BARE_NAMESPACES = ("services", "api", "models", "repositories", "schemas", "core")

# 全路径形态：services.<svc>.src.<subpkg>(.x.y.z)
FULL_PATH_RE = re.compile(r"^services\.[a-z][a-z0-9_]*\.src\.[a-z][a-z0-9_]*(\.[A-Za-z_][\w]*)*$")

# 测试文件目录候选（按服务分组）
TEST_DIR_PATTERNS = ("services/*/src/tests", "services/*/tests")


# ─── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImportSite:
    rel_path: str
    line: int
    style: str          # "bare" | "full-path"
    namespace: str      # bare 时记录顶层 NS，full-path 留空
    module: str         # 原始 module 路径
    proposed: str       # 改写后路径（full-path 形态）


# ─── 解析逻辑 ────────────────────────────────────────────────────────────────


def detect_service_module(rel_path: Path) -> str | None:
    """从相对路径推断服务模块名（dash → underscore）。

    services/tx-trade/src/tests/test_X.py → "tx_trade"
    services/tx-trade/tests/test_X.py     → "tx_trade"
    """
    parts = rel_path.parts
    if len(parts) < 3 or parts[0] != "services":
        return None
    return parts[1].replace("-", "_")


def classify_module(module: str) -> tuple[str, str]:
    """对 from <module> import ... 的 module 字符串分类。

    返回 (style, namespace)：
      - ("bare", "services") / ("bare", "api") / ...：需要改写
      - ("full-path", ""):                          已对齐
      - ("other", ""):                              第三方/标准库/相对 import 等，不动
    """
    if not module:
        return "other", ""
    if FULL_PATH_RE.match(module):
        return "full-path", ""
    parts = module.split(".")
    if parts[0] in BARE_NAMESPACES and len(parts) >= 2:
        # 排除 services.<svc>.src... 这种（已被 FULL_PATH_RE 捕获）
        # 也排除 services.<svc> 单层（不合理，但保守跳过）
        if parts[0] == "services" and len(parts) >= 3 and parts[2] == "src":
            return "other", ""
        return "bare", parts[0]
    return "other", ""


def propose_rewrite(module: str, namespace: str, service: str) -> str:
    """裸 'services.cashier_engine' + service='tx_trade'
       → 'services.tx_trade.src.services.cashier_engine'

    裸 'api.cashier_routes' + service='tx_trade'
       → 'services.tx_trade.src.api.cashier_routes'
    """
    parts = module.split(".", 1)
    rest = parts[1] if len(parts) > 1 else ""
    return f"services.{service}.src.{namespace}.{rest}".rstrip(".")


def scan_file(path: Path, repo_root: Path, service: str) -> list[ImportSite]:
    """扫描单个 .py 文件，返回 (file, line, style, ns, module, proposed) 列表。

    抓两种 import 形式：
      - `from <ns>.<x> import y`        → ast.ImportFrom
      - `import <ns>.<x> [as foo]`      → ast.Import (#318 follow-up)
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    rel = str(path.relative_to(repo_root))
    sites: list[ImportSite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is None or node.level != 0:
                continue  # 相对 import 跳过（from ..X import）
            style, ns = classify_module(node.module)
            if style == "other":
                continue
            proposed = node.module if style == "full-path" else propose_rewrite(
                node.module, ns, service
            )
            sites.append(
                ImportSite(
                    rel_path=rel,
                    line=node.lineno,
                    style=style,
                    namespace=ns,
                    module=node.module,
                    proposed=proposed,
                )
            )
        elif isinstance(node, ast.Import):
            # `import a.b.c [as foo]` — 每 alias 独立
            for alias in node.names:
                style, ns = classify_module(alias.name)
                if style == "other":
                    continue
                proposed = alias.name if style == "full-path" else propose_rewrite(
                    alias.name, ns, service
                )
                sites.append(
                    ImportSite(
                        rel_path=rel,
                        line=node.lineno,
                        style=style,
                        namespace=ns,
                        module=alias.name,
                        proposed=proposed,
                    )
                )
    return sites


def scan_repo(root: Path) -> list[ImportSite]:
    sites: list[ImportSite] = []
    for pattern in TEST_DIR_PATTERNS:
        for test_dir in root.glob(pattern):
            if not test_dir.is_dir():
                continue
            for py in test_dir.rglob("*.py"):
                rel = py.relative_to(root)
                svc = detect_service_module(rel)
                if svc is None:
                    continue
                sites.extend(scan_file(py, root, svc))
    sites.sort(key=lambda s: (s.rel_path, s.line))
    return sites


# ─── 输出 ────────────────────────────────────────────────────────────────────


def render_report(sites: list[ImportSite]) -> str:
    by_service: dict[str, list[ImportSite]] = defaultdict(list)
    for s in sites:
        parts = s.rel_path.split("/")
        svc = parts[1].replace("-", "_") if len(parts) >= 2 else "unknown"
        by_service[svc].append(s)

    lines: list[str] = []
    lines.append("# Test-file import 风格扫描报告（#298 Phase 1 baseline）")
    lines.append("")
    lines.append(
        "> 自动生成。重生成：`python3 scripts/codemod/test_import_style_rewrite.py --out <path>`"
    )
    lines.append("")

    bare_total = sum(1 for s in sites if s.style == "bare")
    full_total = sum(1 for s in sites if s.style == "full-path")
    lines.append("## 全局统计")
    lines.append("")
    lines.append(f"- 总扫描 import 站点：**{len(sites)}**")
    lines.append(f"- 裸 import（待改）：**{bare_total}**")
    lines.append(f"- 全路径 import（已对齐）：**{full_total}**")
    lines.append("")

    # NS 分布
    ns_counts: dict[str, int] = defaultdict(int)
    for s in sites:
        if s.style == "bare":
            ns_counts[s.namespace] += 1
    if ns_counts:
        lines.append("### 裸 import 顶层 NS 分布")
        lines.append("")
        lines.append("| NS | 站点 |")
        lines.append("|----|------|")
        for ns, c in sorted(ns_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| `{ns}` | {c} |")
        lines.append("")

    # 混用文件 — 高危（SQLAlchemy 双重注册真凶，PR #287 band-aid 触发点）
    by_file_styles: dict[str, set[str]] = defaultdict(set)
    for s in sites:
        by_file_styles[s.rel_path].add(s.style)
    mixed_files = sorted(f for f, styles in by_file_styles.items() if len(styles) > 1)
    lines.append("## 混用文件（高危 — SQLAlchemy 双重注册真凶）")
    lines.append("")
    if mixed_files:
        lines.append(f"**{len(mixed_files)} 文件**同时含裸 + 全路径 import，是 PR #287 `extend_existing=True` band-aid 的触发点。Phase 2 stacked PR **优先改这几个文件**。")
        lines.append("")
        lines.append("| 文件 | 裸/全路径 站点数 |")
        lines.append("|------|------------------|")
        for f in mixed_files:
            file_sites = [s for s in sites if s.rel_path == f]
            bare_n = sum(1 for s in file_sites if s.style == "bare")
            full_n = sum(1 for s in file_sites if s.style == "full-path")
            lines.append(f"| `{f}` | {bare_n} 裸 / {full_n} 全路径 |")
        lines.append("")
    else:
        lines.append("✅ 当前无混用文件（band-aid 移除后无回归风险）")
        lines.append("")

    # 按服务
    for svc in sorted(by_service):
        items = by_service[svc]
        bare = sum(1 for s in items if s.style == "bare")
        full = sum(1 for s in items if s.style == "full-path")
        files_total = len({s.rel_path for s in items})
        bare_files = {s.rel_path for s in items if s.style == "bare"}
        full_files = {s.rel_path for s in items if s.style == "full-path"}
        files_mixed = len(bare_files & full_files)
        lines.append(
            f"## `{svc}` — {bare} 裸 / {full} 全路径 / {files_total} 文件（{files_mixed} 混用）"
        )
        lines.append("")
        lines.append("| 文件 | 行 | 风格 | 当前 | 提议改写 |")
        lines.append("|------|-----|------|------|---------|")
        for s in items:
            short = s.rel_path.split("/")[-1]
            if s.style == "bare":
                lines.append(
                    f"| `{short}` | {s.line} | bare/{s.namespace} | `{s.module}` | `{s.proposed}` |"
                )
            else:
                lines.append(f"| `{short}` | {s.line} | full | `{s.module}` | _(已对齐)_ |")
        lines.append("")
    return "\n".join(lines) + "\n"


# ─── CLI ────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="#298 import 风格扫描 + (Phase 2) 改写")
    parser.add_argument("--root", default=".", type=Path, help="repo 根目录（默认 cwd）")
    parser.add_argument("--out", default=None, type=Path, help="报告输出 md 路径（默认 stdout）")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="(Phase 2) 实际改写文件 — 必须配 --service 或 --files 缩窄范围",
    )
    parser.add_argument(
        "--service",
        default=None,
        help="(Phase 2) 限定改写到单服务（disk 名，如 tx-trade）",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="(Phase 2) 限定改写到特定 rel_path 文件列表",
    )
    return parser.parse_args(argv)


def filter_sites(
    sites: list[ImportSite],
    service: str | None,
    files: list[str] | None,
) -> list[ImportSite]:
    """按 --service / --files 缩窄站点列表。"""
    if files:
        files_set = set(files)
        return [s for s in sites if s.rel_path in files_set]
    if service:
        prefix = f"services/{service}/"
        return [s for s in sites if s.rel_path.startswith(prefix)]
    return sites


def apply_rewrites_to_file(path: Path, sites_in_file: list[ImportSite]) -> int:
    """对单个文件做字符串级 import 改写（保留注释/空行/缩进）。

    支持两种形式（#318 follow-up）：
      - `from <module> import ...`     → `from <proposed> import ...`
      - `import <module> [as foo]`     → `import <proposed> [as foo]`

    只处理 bare 站点。返回 changed line 数。
    """
    bare_sites = [s for s in sites_in_file if s.style == "bare"]
    if not bare_sites:
        return 0
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = 0
    for s in bare_sites:
        idx = s.line - 1
        if not (0 <= idx < len(lines)):
            continue
        # from-import 形式优先（更高熵的 token "from "）
        from_old = f"from {s.module} import"
        from_new = f"from {s.proposed} import"
        if from_old in lines[idx]:
            lines[idx] = lines[idx].replace(from_old, from_new, 1)
            changed += 1
            continue
        # import 形式 — `import X` 后必须跟空白或 `as`/EOL 防止误匹配
        # （e.g. `import api.foo` 不能匹配到 `import api.foo_bar`）
        import_old_prefix = f"import {s.module}"
        line_text = lines[idx]
        ix = line_text.find(import_old_prefix)
        if ix >= 0:
            after_idx = ix + len(import_old_prefix)
            after_char = line_text[after_idx : after_idx + 1]
            if after_char in ("", " ", "\t", "\n", ";"):
                lines[idx] = (
                    line_text[:ix] + f"import {s.proposed}" + line_text[after_idx:]
                )
                changed += 1
    if changed > 0:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


def apply_rewrites(
    root: Path,
    sites: list[ImportSite],
    service: str | None,
    files: list[str] | None,
) -> tuple[int, int]:
    """批量改写。返回 (files_changed, sites_rewritten)。"""
    targeted = filter_sites(sites, service, files)
    if not targeted:
        return 0, 0
    by_file: dict[str, list[ImportSite]] = defaultdict(list)
    for s in targeted:
        by_file[s.rel_path].append(s)
    files_changed = 0
    sites_rewritten = 0
    for rel, file_sites in sorted(by_file.items()):
        path = root / rel
        n = apply_rewrites_to_file(path, file_sites)
        if n > 0:
            files_changed += 1
            sites_rewritten += n
            print(f"  改写 {rel}：{n} 处", file=sys.stderr)
    return files_changed, sites_rewritten


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    sites = scan_repo(root)

    if args.apply:
        if not args.service and not args.files:
            print(
                "ERROR: --apply 必须指定 --service <name> 或 --files <p1> <p2>...，"
                "防止误改全仓（Phase 2 stacked PR 模式 ≤ 20 文件/PR）。",
                file=sys.stderr,
            )
            return 2
        files_changed, sites_rewritten = apply_rewrites(
            root, sites, args.service, args.files
        )
        print(
            f"\n✅ 改写完毕：{files_changed} 文件 / {sites_rewritten} 处 import",
            file=sys.stderr,
        )
        if files_changed == 0:
            print("（filter 未命中任何 bare 站点，无改动）", file=sys.stderr)
        return 0

    report = render_report(sites)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        bare = sum(1 for s in sites if s.style == "bare")
        full = sum(1 for s in sites if s.style == "full-path")
        print(
            f"扫描 {len(sites)} 站点（{bare} 裸 / {full} 全路径）→ {args.out}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(report)

    return 1 if any(s.style == "bare" for s in sites) else 0


if __name__ == "__main__":
    raise SystemExit(main())
