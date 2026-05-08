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

# 疑似金额的字段名关键词（正则）— 扩展自 PR #264 verifier 反馈：
# overhead/payable/receivable/refund/rebate/commission/payment/salary/wage/bonus/
# allocated/expense/payroll/owed/due/reimburse 都是常见金额字段名
AMOUNT_PATTERN = re.compile(
    r"(amount|price|cost|balance|total|fee|charge|discount|deposit|tax|net|gross|"
    r"sum|premium|overhead|allocated|payable|receivable|refund|rebate|commission|"
    r"payment|salary|wage|bonus|expense|payroll|owed|due|reimburse|profit|revenue|"
    r"income|payout|cashback)",
    re.IGNORECASE,
)

# 白名单 1：物理单位后缀（不可能是金额，任意 scale / type 跳过）
# 例：total_mileage_km Numeric(10,2) 是 GPS 公里数，邻位 total_cost_fen 是真钱
UNIT_SUFFIX_PATTERN = re.compile(
    r"_(?:km|kg|count|qty|pieces|seconds|minutes|hours|days|ms)$",
    re.IGNORECASE,
)

# 白名单 2：比率词作后缀（_rate / _ratio / _pct / _percent，严格 end-of-name）
# 例：food_cost_rate / deposit_ratio Numeric(5,2) 表达 "30.00%" 格式比率，
# 邻位 deposit_fen / total_cost_fen 才是真钱
RATIO_SUFFIX_PATTERN = re.compile(
    r"_(?:rate|ratio|pct|percent)$",
    re.IGNORECASE,
)

# 白名单 3：margin 词（毛利率 / 利润率），允许 _before / _after 等时间维度变体
# 例：gross_margin / gross_margin_before / profit_margin —— 创始人 5/8 决策：
# margin 在屯象OS Ontology 中专指比率，非金额；shared/ontology/ §18 冻结但可在
# 扫描器侧通过启发式豁免，不需修 entities.py
MARGIN_TOKEN_PATTERN = re.compile(
    r"(?:^|_)margin(?:_\w+)?$",
    re.IGNORECASE,
)

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


def _should_skip_rate_field(column_name: str, scale: int | None) -> bool:  # noqa: ARG001
    """单位 / 比率 / 毛利率字段白名单（PR #B-3 收紧）：

    任一命中即跳过（不再依赖 scale 阈值）：
    1. UNIT_SUFFIX：`_km / _kg / _count / _qty / _pieces / _seconds / ...` 物理单位
    2. RATIO_SUFFIX：`_rate / _ratio / _pct / _percent` 严格 end-of-name 后缀
    3. MARGIN_TOKEN：`margin` 词，含 `_margin / _margin_before / _margin_after / ...` 变体

    设计变更（vs PR #264）：
      - 旧规则要求 `scale >= 4` 才豁免 rate token，把 Numeric(5,2) 表达"30.00%"
        格式的真比率（deposit_ratio / food_cost_rate）误报为 high 金额违规
      - 新规则按命名清晰度豁免：`_rate$` / `_ratio$` / `_margin*` 后缀语义明确即跳过
      - margin token 加入：创始人 5/8 决策，shared/ontology/ §18 冻结的
        4 处 *_margin 应在扫描器侧豁免（不修 entities.py）

    Trade-off（reviewer 注意）：
      - 接受小概率 false-negative：理论上 `total_rate_amount` 这种"中含 rate token
        但实为金额"命名会被错跳；实际 codebase 不存在此命名风格
      - `tax_rate Numeric(5,4)` 等真税率原 scale>=4 规则覆盖，新规则后缀匹配仍
        覆盖，无 regression

    `scale` 参数保留签名兼容（调用方继续传），不参与新逻辑。
    """
    if UNIT_SUFFIX_PATTERN.search(column_name):
        return True
    if RATIO_SUFFIX_PATTERN.search(column_name):
        return True
    if MARGIN_TOKEN_PATTERN.search(column_name):
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

    def visit_Call(self, node: ast.Call) -> None:
        """处理 Table() 内的字面列名：Column("amount", Numeric(10, 2), ...)。

        verifier #264 反馈：原版只走 visit_Assign，无法捕获 SQLAlchemy Core
        Table() / __table_args__ 中以位置参数形式定义的列。
        """
        func = node.func
        func_name: str | None = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr

        if func_name == "Column" and len(node.args) >= 2:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                column_name = first_arg.value
                # 在第 2+ 位置参数中找 Numeric(...)
                numeric_call: ast.Call | None = None
                for arg in node.args[1:]:
                    if _is_numeric_call(arg):
                        numeric_call = arg  # type: ignore[assignment]
                        break
                if numeric_call is not None:
                    precision, scale = _extract_numeric_args(numeric_call)
                    if AMOUNT_PATTERN.search(column_name) and not _should_skip_rate_field(
                        column_name, scale
                    ):
                        type_args = (
                            f"Numeric({precision}, {scale})"
                            if precision is not None
                            else "Numeric(...)"
                        )
                        self.violations.append(
                            Violation(
                                file=self.source_path,
                                line=node.lineno,
                                column_name=column_name,
                                type_args=type_args,
                                severity=_severity(scale),
                            )
                        )
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
    """递归扫描 services/ 与 shared/ 下的 .py 文件，返回所有违规。

    verifier #264 反馈：原版用 `glob("*/src/models/*.py")` 非递归，漏扫：
    - 深路径（services/tx-brain/src/ontology/models.py）
    - shared/ontology/ 模型
    - SQLAlchemy Core Table() 写法（services/*/src/services/*.py 中的 delivery_ops_service）
    """
    all_violations: list[Violation] = []
    seen: set[tuple[str, int, str]] = set()  # 去重 (file, line, column_name)

    # 递归扫 .py 全文件，但限定在与 ORM 相关的目录下
    candidate_globs = [
        "**/src/models/*.py",          # 标准 ORM 模型目录
        "**/src/models/**/*.py",       # 嵌套目录
        "**/src/services/*.py",        # SQLAlchemy Core Table() 出现位置
        "**/src/services/**/*.py",
        "**/src/ontology/**/*.py",     # tx-brain/src/ontology
        # PR #264 round-2 反馈：shared/ontology/src/entities.py 等扁平 ORM 文件
        "**/ontology/**/*.py",         # 含 shared/ontology/src/{entities,extensions}/*
        "**/entities*.py",             # 显式覆盖 entities.py 命名约定
    ]
    parent_root = root.parent if root.parent != root else root
    for pattern in candidate_globs:
        for model_file in sorted(root.rglob(pattern.split("/", 1)[1] if pattern.startswith("**/") else pattern)):
            try:
                violations = scan_file(model_file, parent_root)
            except ValueError:
                # path.relative_to 失败时（root.parent 为 / 等极端情况）兜底
                violations = scan_file(model_file, model_file.parent)
            for v in violations:
                key = (v.file, v.line, v.column_name)
                if key in seen:
                    continue
                seen.add(key)
                all_violations.append(v)

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
    lines.append("**白名单（不报警）：**")
    lines.append("")
    lines.append("- 物理单位后缀：`_km` / `_kg` / `_count` / `_qty` / `_pieces` / `_seconds` / `_minutes` / `_hours` / `_days` / `_ms`")
    lines.append("- 比率后缀：`_rate` / `_ratio` / `_pct` / `_percent`（严格 end-of-name）")
    lines.append("- 毛利率/利润率 token：`margin` 词（含 `_margin` / `_margin_before` / `_margin_after` 等变体）")

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
