"""scan_decimal_amount_columns.py — Tier1 审计：检测疑似金额字段使用 Numeric(M,N)

目标：扫描 services/*/src/models/*.py，找出用 Numeric(M, N) 但字段名疑似金额的列。
规范：金额字段必须使用 Integer（分/fen），不得使用 Numeric/Decimal 类型。

用法：
    python scripts/audit/scan_decimal_amount_columns.py [--root services] [--output json|md]

返回码：
    0 — 无违规
    1 — 发现违规
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# ─── 启发式规则 ────────────────────────────────────────────────────────────────

# 疑似金额的字段名关键词（正则）
AMOUNT_PATTERN = re.compile(
    r"(amount|price|cost|balance|total|fee|charge|discount|deposit|tax|net|gross|sum|premium)",
    re.IGNORECASE,
)

# 白名单：字段名含 rate 且 scale <= 4 的百分比字段不报警
RATE_PATTERN = re.compile(r"rate", re.IGNORECASE)

# 只对 scale = 2 的报 high，其他报 warning
HIGH_SEVERITY_SCALE = 2


# ─── 数据结构 ──────────────────────────────────────────────────────────────────


@dataclass
class Violation:
    file: str
    line: int
    column_name: str
    type_args: str
    severity: str  # "high" | "warning"

    def to_dict(self) -> dict:
        return asdict(self)


# ─── AST 解析 ──────────────────────────────────────────────────────────────────


def _extract_numeric_args(call_node: ast.Call) -> tuple[int | None, int | None]:
    """从 Numeric(M, N) 调用节点提取 precision 和 scale。
    只处理位置参数为整数字面量的情况。
    """
    precision: int | None = None
    scale: int | None = None

    args = call_node.args
    if len(args) >= 1 and isinstance(args[0], ast.Constant) and isinstance(args[0].value, int):
        precision = args[0].value
    if len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, int):
        scale = args[1].value

    # 也支持 keyword: Numeric(precision=10, scale=2)
    for kw in call_node.keywords:
        if kw.arg == "precision" and isinstance(kw.value, ast.Constant):
            precision = kw.value.value
        if kw.arg == "scale" and isinstance(kw.value, ast.Constant):
            scale = kw.value.value

    return precision, scale


def _is_numeric_call(node: ast.expr) -> bool:
    """判断节点是否为 Numeric(...) 调用（忽略模块前缀）。"""
    if isinstance(node, ast.Call):
        func = node.func
        # Numeric(...)
        if isinstance(func, ast.Name) and func.id == "Numeric":
            return True
        # sqlalchemy.Numeric(...) / sa.Numeric(...)
        if isinstance(func, ast.Attribute) and func.attr == "Numeric":
            return True
    return False


def _find_numeric_in_args(call_node: ast.Call) -> ast.Call | None:
    """在 mapped_column(...) 或 Column(...) 的参数中找 Numeric(...) 调用。"""
    for arg in call_node.args:
        if _is_numeric_call(arg):
            return arg  # type: ignore[return-value]
    for kw in call_node.keywords:
        if _is_numeric_call(kw.value):
            return kw.value  # type: ignore[return-value]
    return None


def _severity(scale: int | None) -> str:
    if scale == HIGH_SEVERITY_SCALE:
        return "high"
    return "warning"


def _should_skip_rate_field(column_name: str, scale: int | None) -> bool:
    """税率/百分比字段白名单：字段名含 rate 且 scale <= 4 则跳过。"""
    if RATE_PATTERN.search(column_name) and scale is not None and scale <= 4:
        return True
    return False


class _ViolationVisitor(ast.NodeVisitor):
    """遍历 AST，收集违规 mapped_column / Column 定义。"""

    def __init__(self, source_path: str) -> None:
        self.source_path = source_path
        self.violations: list[Violation] = []

    # 处理赋值语句，如：
    #   amount: Mapped[int] = mapped_column(Numeric(10, 2), ...)
    #   amount = Column(Numeric(10, 2), ...)
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_assignment_target(node.target, node.value, node.lineno)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_assignment_target(target, node.value, node.lineno)
        self.generic_visit(node)

    def _check_assignment_target(
        self,
        target: ast.expr,
        value: ast.expr | None,
        lineno: int,
    ) -> None:
        if value is None:
            return
        if not isinstance(target, ast.Name):
            return

        column_name = target.id

        # value 必须是 mapped_column(...) 或 Column(...) 调用
        if not isinstance(value, ast.Call):
            return
        func = value.func
        func_name: str | None = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr

        if func_name not in ("mapped_column", "Column"):
            return

        # 在参数中寻找 Numeric(...)
        numeric_call = _find_numeric_in_args(value)
        if numeric_call is None:
            return

        precision, scale = _extract_numeric_args(numeric_call)

        # 字段名是否疑似金额
        if not AMOUNT_PATTERN.search(column_name):
            return

        # 白名单：rate 字段
        if _should_skip_rate_field(column_name, scale):
            return

        type_args = f"Numeric({precision}, {scale})" if precision is not None else "Numeric(...)"
        sev = _severity(scale)

        self.violations.append(
            Violation(
                file=self.source_path,
                line=lineno,
                column_name=column_name,
                type_args=type_args,
                severity=sev,
            )
        )


def scan_file(path: Path, root: Path) -> list[Violation]:
    """解析单个 Python 文件，返回违规列表。"""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    relative = str(path.relative_to(root))
    visitor = _ViolationVisitor(source_path=relative)
    visitor.visit(tree)
    return visitor.violations


def scan_directory(root: Path) -> list[Violation]:
    """扫描 root/*/src/models/*.py，返回所有违规，按 file+line 排序。"""
    all_violations: list[Violation] = []

    # 匹配 services/*/src/models/*.py（递归）
    pattern = "*/src/models/*.py"
    for model_file in sorted(root.glob(pattern)):
        violations = scan_file(model_file, root.parent)
        all_violations.extend(violations)

    all_violations.sort(key=lambda v: (v.file, v.line))
    return all_violations


# ─── 输出格式 ──────────────────────────────────────────────────────────────────


def _output_json(violations: list[Violation]) -> str:
    data = {"violations": [v.to_dict() for v in violations]}
    return json.dumps(data, ensure_ascii=False, indent=2)


def _output_md(violations: list[Violation], root_label: str) -> str:
    lines: list[str] = []
    lines.append("# Decimal 金额违规扫描报告")
    lines.append("")
    lines.append(f"**扫描根目录：** `{root_label}`  ")
    lines.append(f"**违规总数：** {len(violations)}  ")
    lines.append("")

    if not violations:
        lines.append("> 未发现违规。")
        return "\n".join(lines)

    # 按服务分组
    by_service: dict[str, list[Violation]] = {}
    for v in violations:
        # file 格式：services/tx-trade/src/models/xxx.py  ->  tx-trade
        parts = Path(v.file).parts
        service = parts[1] if len(parts) > 1 else "unknown"
        by_service.setdefault(service, []).append(v)

    for service, svs in sorted(by_service.items()):
        lines.append(f"## {service} ({len(svs)} 处)")
        lines.append("")
        lines.append("| 文件 | 行 | 字段名 | 类型 | 严重度 |")
        lines.append("|------|-----|--------|------|--------|")
        for sv in svs:
            short_file = Path(sv.file).name
            lines.append(f"| `{short_file}` | {sv.line} | `{sv.column_name}` | `{sv.type_args}` | **{sv.severity}** |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 规范说明")
    lines.append("")
    lines.append("根据 CLAUDE.md §15/§17：**金额字段必须使用 `Integer`（单位：分），不得使用 `Numeric`/`Decimal` 类型。**")
    lines.append("")
    lines.append("- `high`：`Numeric(M, 2)` — 明显的人民币元/角格式，必须修为 `Integer`")
    lines.append("- `warning`：`Numeric(M, N≠2)` — 疑似金额但 scale 异常，需人工核查")
    lines.append("")
    lines.append("**白名单（不报警）：** 字段名含 `rate` 且 scale ≤ 4 的百分比字段（如 `tax_rate Numeric(5,4)`）。")

    return "\n".join(lines)


# ─── CLI ───────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="扫描 services/*/src/models/*.py 中疑似金额字段使用 Numeric(M,N) 的违规点"
    )
    parser.add_argument(
        "--root",
        default="services",
        help="扫描根目录（默认: services）",
    )
    parser.add_argument(
        "--output",
        choices=["json", "md"],
        default="json",
        help="输出格式：json（默认）或 md",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 支持绝对路径和相对路径（相对于 CWD）
    root_path = Path(args.root)
    if not root_path.is_absolute():
        root_path = Path.cwd() / root_path

    if not root_path.exists():
        print(f"ERROR: 目录不存在: {root_path}", file=sys.stderr)
        return 2

    violations = scan_directory(root_path)

    if args.output == "md":
        print(_output_md(violations, args.root))
    else:
        print(_output_json(violations))

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
