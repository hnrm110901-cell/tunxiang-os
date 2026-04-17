"""
LLM 安全网关 — 三道防线

1. sanitize_input()  : 检测 + 清洗 prompt injection 攻击，返回 (cleaned, risk_score 0-100)
2. scrub_pii()       : 脱敏手机号/身份证/银行卡，统一替换为占位符
3. filter_output()   : 检测 LLM 输出是否泄露 API_KEY / SECRET / 密码 / 内部 URL

所有函数均为纯函数，零外部依赖，可独立单测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 1) Prompt Injection 检测模式
# ─────────────────────────────────────────────────────────────────────────────

# 每个模式配一个风险权重（越高越危险）
INJECTION_PATTERNS: List[Tuple[re.Pattern, int]] = [
    # 指令改写类（最高危）
    (re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts)", re.IGNORECASE), 40),
    (re.compile(r"忽略(前面|上面|之前|所有)(的)?(指令|提示|规则|设定)"), 40),
    (re.compile(r"disregard\s+(all\s+)?(previous|above|prior)", re.IGNORECASE), 35),
    # 角色劫持
    (re.compile(r"you\s+are\s+(now\s+)?(a\s+)?(dan|developer mode|jailbreak)", re.IGNORECASE), 45),
    (re.compile(r"你(现在)?(是|扮演)(一个)?(不受限制|无道德|没有限制)", re.IGNORECASE), 45),
    # 系统提示泄露
    (re.compile(r"(reveal|show|print|output)\s+(your|the)\s+(system|initial)\s+prompt", re.IGNORECASE), 30),
    (re.compile(r"(输出|显示|打印|告诉我)(你的)?(系统|初始)(提示|prompt)"), 30),
    # 分隔符注入
    (re.compile(r"\n\s*###\s*(system|new\s+instruction)", re.IGNORECASE), 25),
    (re.compile(r"</?\s*(system|instruction|prompt)\s*>", re.IGNORECASE), 25),
    # 提权 / 假冒
    (re.compile(r"\[\s*(admin|root|sudo|system)\s*\]", re.IGNORECASE), 20),
]


@dataclass
class SanitizeResult:
    """sanitize_input 返回值"""

    cleaned: str
    risk_score: int  # 0-100
    matched_patterns: List[str]


def sanitize_input(text: str) -> SanitizeResult:
    """
    过滤 prompt injection 模式，返回清洗后文本 + 风险分 (0-100)

    - 命中任一高危模式即标注；风险分 = 所有命中权重之和，封顶 100
    - 清洗策略：将命中片段替换为 `[FILTERED]`，保留原文语义外壳
    """
    if not text:
        return SanitizeResult(cleaned="", risk_score=0, matched_patterns=[])

    cleaned = text
    risk_score = 0
    matched: List[str] = []

    for pattern, weight in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            matched.append(pattern.pattern)
            risk_score += weight
            cleaned = pattern.sub("[FILTERED]", cleaned)

    return SanitizeResult(
        cleaned=cleaned,
        risk_score=min(risk_score, 100),
        matched_patterns=matched,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2) PII 脱敏（中国大陆常见 PII）
# ─────────────────────────────────────────────────────────────────────────────

# 手机号：11位，1开头
PII_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 身份证：18位（或17位+X）
PII_IDCARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
# 银行卡：13-19位连续数字（粗筛）
PII_BANK = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
# 邮箱
PII_EMAIL = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def scrub_pii(text: str) -> str:
    """脱敏手机号/身份证/银行卡/邮箱。顺序敏感：先身份证→银行卡→手机→邮箱"""
    if not text:
        return text
    # 身份证要先于银行卡（18 位）匹配
    text = PII_IDCARD.sub("[IDCARD]", text)
    text = PII_BANK.sub("[BANK]", text)
    text = PII_PHONE.sub("[PHONE]", text)
    text = PII_EMAIL.sub("[EMAIL]", text)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# 3) 输出敏感词过滤
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_LEAK_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("API_KEY", re.compile(r"(api[_-]?key|apikey)\s*[:=]\s*[A-Za-z0-9_\-]{16,}", re.IGNORECASE)),
    ("SECRET", re.compile(r"(secret|token|password)\s*[:=]\s*\S{8,}", re.IGNORECASE)),
    ("PASSWORD_CN", re.compile(r"密码[:：]\s*\S{6,}")),
    ("INTERNAL_URL", re.compile(r"https?://(?:10|172\.1[6-9]|172\.2\d|172\.3[0-1]|192\.168)\.\d+\.\d+", re.IGNORECASE)),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----")),
    ("AWS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
]


@dataclass
class FilterResult:
    """filter_output 返回值"""

    safe_text: str
    flags: List[str]  # 命中的泄露类型


def filter_output(text: str) -> FilterResult:
    """
    检测 LLM 输出是否含敏感信息，命中则替换为占位符并记录 flag
    """
    if not text:
        return FilterResult(safe_text="", flags=[])

    safe = text
    flags: List[str] = []
    for flag_name, pattern in OUTPUT_LEAK_PATTERNS:
        if pattern.search(safe):
            flags.append(flag_name)
            safe = pattern.sub(f"[REDACTED:{flag_name}]", safe)

    return FilterResult(safe_text=safe, flags=flags)
