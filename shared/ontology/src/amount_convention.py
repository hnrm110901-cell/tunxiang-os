"""金额单位公约 — 全系统统一存分(fen)

规则：
1. 数据库: INTEGER, 单位=分
2. API入参出参: 整数, 单位=分
3. 变量命名: 后缀_fen (amount_fen, total_fen)
4. 前端显示: fen / 100 显示元
5. V1代码迁入: Numeric(10,2) → Integer, 所有值 *100

示例：
  ¥168.00 → 16800 (fen)
  ¥0.01 → 1 (fen)
  ¥99999.99 → 9999999 (fen)
"""


def yuan_to_fen(yuan: float) -> int:
    """元转分 — 用于V1数据迁移"""
    return round(yuan * 100)


def fen_to_yuan(fen: int) -> float:
    """分转元 — 用于显示"""
    return fen / 100


def format_amount(fen: int) -> str:
    """格式化金额显示"""
    yuan = fen / 100
    if yuan >= 10000:
        return f"¥{yuan:,.2f}"
    return f"¥{yuan:.2f}"


def validate_fen(value: int, field_name: str = "amount") -> int:
    """校验分值合法性"""
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be integer (fen), got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative: {value}")
    return value
