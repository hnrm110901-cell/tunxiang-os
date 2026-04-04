"""SQL 注入防护 -- 检测可疑输入

纯 Python 实现，零外部依赖。用于中间件层面对请求参数做快速扫描，
配合参数化查询形成双重防线。

注意：这是**辅助检测层**，不能替代参数化查询（prepared statements）。
SQLAlchemy 已经默认参数化，此模块用于拦截明显的攻击尝试并记录审计日志。
"""

import re
from typing import List

# ---------------------------------------------------------------------------
# 可疑 SQL 注入模式（编译后缓存，大小写不敏感）
# ---------------------------------------------------------------------------

_SUSPICIOUS_PATTERNS: List[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"""(?:'|")\s*(?:OR|AND)\s+\d+\s*=\s*\d+""",   # ' OR 1=1
        r""";\s*(?:DROP|DELETE|UPDATE|INSERT|ALTER)\s""", # SQL 命令注入
        r"""UNION\s+(?:ALL\s+)?SELECT""",                # UNION 注入
        r"""--\s*$""",                                    # SQL 行注释尾部
        r"""/\*[\s\S]*?\*/""",                           # 块注释
        r"""(?:'|")\s*;\s*""",                           # 引号 + 分号
        r"""EXEC(?:UTE)?\s""",                           # EXECUTE
        r"""xp_\w+""",                                   # SQL Server 扩展存储过程
        r"""SLEEP\s*\(""",                               # 时间盲注
        r"""BENCHMARK\s*\(""",                           # MySQL 时间盲注
        r"""WAITFOR\s+DELAY""",                          # SQL Server 时间盲注
        r"""LOAD_FILE\s*\(""",                           # 文件读取
        r"""INTO\s+(?:OUT|DUMP)FILE""",                  # 文件写入
        r"""INFORMATION_SCHEMA""",                       # 信息泄露
        r"""(?:CHAR|CHR|CONCAT)\s*\(""",                 # 编码绕过函数
    ]
]

# LIKE 查询中需要转义的特殊字符
_LIKE_SPECIAL = str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"})


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def check_sql_injection(value: str) -> bool:
    """检测输入是否包含 SQL 注入特征。

    Returns:
        True 表示检测到可疑注入模式，应拒绝该输入。
    """
    if not isinstance(value, str):
        return False
    for pattern in _SUSPICIOUS_PATTERNS:
        if pattern.search(value):
            return True
    return False


def sanitize_for_like(value: str) -> str:
    """转义 LIKE 查询特殊字符（%, _, \\）。

    用于安全地将用户输入嵌入 LIKE 模式：
        ``WHERE name LIKE :pattern``
        ``pattern = f"%{sanitize_for_like(user_input)}%"``
    """
    if not isinstance(value, str):
        raise ValueError("expected str")
    return value.translate(_LIKE_SPECIAL)
