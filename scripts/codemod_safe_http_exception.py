#!/usr/bin/env python3
"""One-shot codemod: HTTPException(status_code=N, detail=str(e)) → safe_http_exception

P2.5 Phase 2: 消除 detail=str(e) 异常信息泄漏到 API caller。

替换规则（保持 except 语义不变）：

  Before:
      except XxxError as e:
          raise HTTPException(status_code=400, detail=str(e))

  After:
      except XxxError as e:
          raise safe_http_exception(400, "请求参数无效", e) from e

支持：
  - 任意 except 子句（ValueError / LookupError / *NotFoundError / *Error 等）
  - 任意变量名（as e / as exc / as err）— 替换捕获的变量名
  - 任意 status_code（400 / 403 / 404 / 409 / ...）— 用 _GENERIC_MESSAGES 映射

后置清理：
  - 自动添加 `from shared.security.src.error_handler import safe_http_exception` import
  - 不删除 HTTPException import（可能仍在其他 raise 语句使用，留人工 review）

用法：
  python3 scripts/codemod_safe_http_exception.py file1.py file2.py ...
  python3 scripts/codemod_safe_http_exception.py --dry-run file1.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 与 shared/security/src/error_handler.py:_GENERIC_MESSAGES 完全一致
GENERIC_MESSAGES: dict[int, str] = {
    400: "请求参数无效",
    401: "认证失败",
    403: "权限不足",
    404: "资源不存在",
    409: "操作冲突",
    422: "请求格式错误",
    429: "请求过于频繁",
    500: "服务器内部错误",
    502: "上游服务不可用",
    503: "服务暂时不可用",
    504: "上游服务超时",
}

# 形如（含可选的 ` from <var>` 显式异常链）：
#   raise HTTPException(status_code=N, detail=str(e))
#   raise HTTPException(status_code=N, detail=str(e)) from e
# 捕获 status_code 数字 + 变量名（与 except 中的 as 名字一致）+ 可选 from
HTTPEXC_DETAIL_RE = re.compile(
    r"raise\s+HTTPException\s*\(\s*"
    r"status_code\s*=\s*(?P<code>\d+)\s*,\s*"
    r"detail\s*=\s*str\(\s*(?P<var>[a-zA-Z_][a-zA-Z0-9_]*)\s*\)\s*"
    r"\)"
    r"(?:\s+from\s+\w+)?"
)

# 检测已有 import：from shared.security.src.error_handler import ...
SAFE_HTTP_IMPORT_RE = re.compile(
    r"from\s+shared\.security\.src\.error_handler\s+import\s+[^\n]*safe_http_exception"
)

# 检测同 module 内任何 from shared.security.src.error_handler import 行（决定 merge 还是新增）
ERR_HANDLER_IMPORT_RE = re.compile(
    r"^(?P<indent>\s*)from\s+shared\.security\.src\.error_handler\s+import\s+(?P<names>[^\n()]+)$",
    re.MULTILINE,
)

# 用于决定 import 插入位置：找到最后一行 from / import
LAST_IMPORT_RE = re.compile(r"^(?:from|import)\s+\S+", re.MULTILINE)


def _replacement(match: re.Match[str]) -> str:
    """生成替换字符串。"""
    code = int(match.group("code"))
    var = match.group("var")
    msg = GENERIC_MESSAGES.get(code, f"HTTP {code} 错误")
    return f'raise safe_http_exception({code}, "{msg}", {var}) from {var}'


def transform(src: str) -> tuple[str, int, bool]:
    """对源文件内容做 codemod。

    Returns:
        (new_src, replace_count, import_added)
    """
    new_src, count = HTTPEXC_DETAIL_RE.subn(_replacement, src)
    if count == 0:
        return new_src, 0, False

    # 添加 safe_http_exception import（如已存在则不重复）
    if SAFE_HTTP_IMPORT_RE.search(new_src):
        return new_src, count, False

    # 优先合并到现有的 from shared.security.src.error_handler import ... 行
    err_import = ERR_HANDLER_IMPORT_RE.search(new_src)
    if err_import:
        names = err_import.group("names").strip()
        parts = [p.strip() for p in names.split(",") if p.strip()]
        if "safe_http_exception" not in parts:
            parts.append("safe_http_exception")
            parts = sorted(set(parts))
            new_line = (
                f"{err_import.group('indent')}from shared.security.src.error_handler "
                f"import {', '.join(parts)}"
            )
            new_src = (
                new_src[: err_import.start()] + new_line + new_src[err_import.end() :]
            )
        return new_src, count, True

    # 没有现有 error_handler import，插到最后一个 import 之后
    last_import = None
    for m in LAST_IMPORT_RE.finditer(new_src):
        last_import = m
    if last_import is None:
        # 没有任何 import — 这种情况几乎不应发生（每个 routes.py 都有 fastapi import）
        sys.stderr.write("warn: no import found, prepending\n")
        return (
            "from shared.security.src.error_handler import safe_http_exception\n\n"
            + new_src
        ), count, True

    # 找该 import 行尾换行；若是多行 from x import (...) 形式，需跳到闭合 `)` 之后
    line_end = new_src.find("\n", last_import.end())
    if line_end == -1:
        line_end = len(new_src)
    # 检测 last_import 行是否以未闭合的 `(` 结尾（multiline import 形式）
    last_import_line = new_src[last_import.start() : line_end]
    open_parens = last_import_line.count("(") - last_import_line.count(")")
    if open_parens > 0:
        # 向后找闭合 `)` 后的换行
        depth = open_parens
        i = line_end
        while i < len(new_src) and depth > 0:
            ch = new_src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        # 跳到 `)` 后下一个换行
        line_end = new_src.find("\n", i)
        if line_end == -1:
            line_end = len(new_src)
    insert_text = (
        "\nfrom shared.security.src.error_handler import safe_http_exception"
    )
    new_src = new_src[: line_end] + insert_text + new_src[line_end:]
    return new_src, count, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help="Files to codemod")
    parser.add_argument("--dry-run", action="store_true", help="Show diff stats only")
    args = parser.parse_args()

    total_files = 0
    total_replaces = 0
    total_imports = 0
    skipped: list[str] = []

    for path_str in args.files:
        path = Path(path_str)
        if not path.is_file():
            sys.stderr.write(f"skip: {path} not a file\n")
            skipped.append(path_str)
            continue
        src = path.read_text(encoding="utf-8")
        new_src, count, import_added = transform(src)
        if count == 0:
            continue
        total_files += 1
        total_replaces += count
        if import_added:
            total_imports += 1
        if args.dry_run:
            print(f"[dry] {path}: {count} replace, import_added={import_added}")
        else:
            path.write_text(new_src, encoding="utf-8")
            print(f"{path}: {count} replace, import_added={import_added}")

    print(
        f"\n=== Summary ===\n"
        f"Files changed:    {total_files}\n"
        f"Total replaces:   {total_replaces}\n"
        f"Imports added:    {total_imports}\n"
        f"Skipped:          {len(skipped)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
