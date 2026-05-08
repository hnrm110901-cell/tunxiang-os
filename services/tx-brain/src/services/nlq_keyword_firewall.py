"""NLQ SQL 危险关键字防火墙 — Tier 1 安全前置。

S4-02 Issue #289 / Tier 1：read-only + RLS 不可绕 + 危险关键字防火墙

职责（纯函数，无 DB 副作用）：
  1. 拒绝写入关键字 — DROP / DELETE / UPDATE / INSERT / TRUNCATE / GRANT / REVOKE /
     CREATE / ALTER / EXECUTE / CALL / COPY / VACUUM
  2. 拒绝 SECURITY DEFINER（绕 RLS 标准技巧）
  3. 拒绝多语句（SELECT 1; DROP TABLE x —— 注入入口）
  4. 拒绝注释攻击（-- / 块注释 包裹 ; 后跟写入语句）
  5. 拒绝非 SELECT/WITH 起首语句（SHOW / EXPLAIN / SET 等 utility 一律拒）

设计：
- 先 strip 注释（行 + 块），让"注释藏 ;"暴露成多语句
- 再按 ; split 检多语句
- 再 word-boundary regex 检禁用关键字
- 最后必须以 SELECT/WITH 开头（去除注释后）

边界：
- 不解析 SQL AST（不依赖 sqlparse），用正则 + 字符串处理足以覆盖 LLM 误输出场景
- 字符串字面量内的写入关键字也会触发（如 SELECT 'DROP' AS x）— 这是 false-positive，
  接受这个保守边界；S4-02 阶段 LLM 不会主动生成含字面量的查询
"""

from __future__ import annotations

import re

# 写入关键字（按 word boundary 匹配，避免误伤 vacuum_status / dropped 等列名）
_FORBIDDEN_KEYWORDS = (
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "CREATE",
    "ALTER",
    "EXECUTE",
    "CALL",
    "COPY",
    "VACUUM",
)

# 短语类（不能用单 word boundary 匹配）
_FORBIDDEN_PHRASES = ("SECURITY DEFINER",)

_FORBIDDEN_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(_FORBIDDEN_KEYWORDS) + r")\b",
    flags=re.IGNORECASE,
)
_FORBIDDEN_PHRASE_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _FORBIDDEN_PHRASES) + r")\b",
    flags=re.IGNORECASE,
)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*", re.MULTILINE)


class UnsafeSqlError(ValueError):
    """SQL 触发 NLQ 沙箱安全规则。"""

    def __init__(self, message: str, *, violation: str) -> None:
        super().__init__(message)
        self.violation = violation


def _strip_comments(sql: str) -> str:
    """删 SQL 块注释 (/* */) 与行注释 (--)，统一替换为空格保留 token 边界。"""
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _LINE_COMMENT.sub(" ", sql)
    return sql


def assert_safe_sql(sql: str) -> None:
    """Tier 1 NLQ SQL 防火墙 — 只允许只读 SELECT / WITH，其余一律拒。

    Raises:
        UnsafeSqlError: SQL 触发任一安全规则。属性 .violation 标识具体类型
            （empty / multi_statement / 关键字大写 / SECURITY DEFINER / not_select）。
    """
    if not sql or not sql.strip():
        raise UnsafeSqlError("SQL 为空或仅含空白", violation="empty")

    stripped = _strip_comments(sql)

    # 多语句检测（注释剥离后 ; 后还有非空 token）
    parts = [p.strip() for p in stripped.split(";") if p.strip()]
    if len(parts) > 1:
        raise UnsafeSqlError(
            f"多语句拒绝，共 {len(parts)} 段（注入风险）",
            violation="multi_statement",
        )

    # 短语类（SECURITY DEFINER）— 先于 keyword 检测，给出更精准的 violation 类型
    # （CREATE FUNCTION ... SECURITY DEFINER 既含 CREATE 又含 SECURITY DEFINER；
    # 报告 SECURITY DEFINER 比 CREATE 更利于使用方理解风险）
    phrase_match = _FORBIDDEN_PHRASE_RE.search(stripped)
    if phrase_match:
        phrase = phrase_match.group(1).upper()
        raise UnsafeSqlError(f"禁用短语 SECURITY DEFINER（绕 RLS 标准技巧）", violation=phrase)

    # 写入关键字
    keyword_match = _FORBIDDEN_KEYWORD_RE.search(stripped)
    if keyword_match:
        kw = keyword_match.group(1).upper()
        raise UnsafeSqlError(f"禁用写入关键字: {kw}", violation=kw)

    # 必须以 SELECT 或 WITH 开头（去除注释后 lstrip）
    head = stripped.lstrip().upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        raise UnsafeSqlError(
            "NLQ 沙箱仅放行 SELECT / WITH 起首语句",
            violation="not_select",
        )
