#!/usr/bin/env python3
"""
屯象OS 适配器 7 维评分卡（Sprint F / F1）

对 shared/adapters/ 下的所有适配器自动打分，输出 markdown 表 + JSON。

7 维度（每维 0-5，总分 35）：
  1. contract       契约完整度   是否实现 BaseAdapter / 覆盖核心方法 / DTO 完备
  2. error_handling 错误处理     无 broad except / 错误码映射 / 超时重试
  3. testing        测试覆盖     test_*.py 数量 / src 文件数 比例
  4. rls            RLS / 租户   tenant_id 出现频次（按文件密度）
  5. idempotency    幂等性       idempotency_key / unique_key / dedup
  6. events         事件发射     emit_event / event_types 引用
  7. docs           文档         README 长度 + 字段映射段

门禁线：总分 ≥ 22 才能上生产。

用法：
    python3 scripts/score_adapters.py                 # 全扫描
    python3 scripts/score_adapters.py --adapter pinzhi
    python3 scripts/score_adapters.py --json out.json
    python3 scripts/score_adapters.py --markdown -    # 输出到 stdout

说明：客观维度（testing/rls/idempotency/events/docs）完全自动；契约完整度
和错误处理为"自动估算"，最终需要人工 review，会在 notes 字段里标注。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADAPTERS_DIR = ROOT / "shared" / "adapters"

# 14 个目录形适配器（不包含 base 与 config / tests / 单文件 legacy adapter）
ADAPTERS = [
    "aoqiwei",
    "base",
    "douyin",
    "eleme",
    "erp",
    "keruyun",
    "logistics",
    "meituan-saas",
    "nuonuo",
    "pinzhi",
    "tiancai-shanglong",
    "weishenghuo",
    "xiaohongshu",
    "yiding",
]

PASS_THRESHOLD = 22


@dataclass
class AdapterScore:
    name: str
    src_files: int = 0
    src_lines: int = 0
    test_files: int = 0
    contract: int = 0
    error_handling: int = 0
    testing: int = 0
    rls: int = 0
    idempotency: int = 0
    events: int = 0
    docs: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.contract
            + self.error_handling
            + self.testing
            + self.rls
            + self.idempotency
            + self.events
            + self.docs
        )

    @property
    def passed(self) -> bool:
        return self.total >= PASS_THRESHOLD


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _iter_py(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [p for p in path.rglob("*.py") if p.is_file()]


def score_contract(src_files: list[Path]) -> tuple[int, str]:
    """契约完整度（自动估算）：
      +1 src 中至少有 adapter.py
      +1 import 了 BaseAdapter 或 Protocol
      +1 至少 1 个 class 继承 BaseAdapter / 有 @abstractmethod 实现
      +1 src 文件 >= 3（覆盖多个域）
      +1 src 文件 >= 6（深度覆盖）
    """
    score = 0
    has_adapter = any(p.name == "adapter.py" for p in src_files)
    if has_adapter:
        score += 1

    base_text = "\n".join(_read_text(p) for p in src_files)
    if re.search(r"BaseAdapter|Protocol\b|ABC\b", base_text):
        score += 1
    if re.search(r"class\s+\w+Adapter\s*\(", base_text):
        score += 1
    if len(src_files) >= 3:
        score += 1
    if len(src_files) >= 6:
        score += 1

    note = "auto-estimate; needs manual confirm of method coverage"
    return score, note


def score_error_handling(src_files: list[Path]) -> tuple[int, str]:
    """错误处理（自动估算）：
      +5 起步，扣分项：
        -1 每出现 broad `except Exception` 一处（最多扣 3）
      +1 引用了 retry / backoff / tenacity
      +1 引用了 timeout
      +1 自定义 error_code / APIError / 错误码映射
    起步分 2，最高 5。
    """
    text = "\n".join(_read_text(p) for p in src_files)
    broad = len(re.findall(r"except\s+Exception", text))
    base = 2
    base -= min(broad, 3)
    base = max(base, 0)
    if re.search(r"tenacity|retry|backoff", text):
        base += 1
    if re.search(r"timeout", text, re.IGNORECASE):
        base += 1
    if re.search(r"APIError|ErrorCode|error_code|raise_for_status", text):
        base += 1
    return min(base, 5), f"broad_except={broad}; auto-estimate"


def score_testing(src_files: list[Path], test_files: list[Path]) -> tuple[int, str]:
    """测试覆盖（自动）：按 test:src 比例：
      0   无 test
      1   ratio < 0.2
      2   ratio < 0.4
      3   ratio < 0.6
      4   ratio < 0.8
      5   ratio >= 0.8
    """
    if not src_files:
        return 0, "no src"
    ratio = len(test_files) / max(len(src_files), 1)
    if not test_files:
        return 0, "no tests"
    score = 1
    for thr, s in [(0.2, 1), (0.4, 2), (0.6, 3), (0.8, 4), (10, 5)]:
        if ratio < thr:
            score = s
            break
    return score, f"test_files={len(test_files)} src_files={len(src_files)} ratio={ratio:.2f}"


def score_rls(src_files: list[Path]) -> tuple[int, str]:
    """RLS / 租户隔离：tenant_id 出现密度（出现次数 / src 文件数）"""
    text = "\n".join(_read_text(p) for p in src_files)
    hits = len(re.findall(r"tenant_id", text))
    if not src_files:
        return 0, "no src"
    density = hits / max(len(src_files), 1)
    if hits == 0:
        return 0, "no tenant_id"
    if density < 1:
        return 1, f"hits={hits} density={density:.1f}"
    if density < 2:
        return 2, f"hits={hits} density={density:.1f}"
    if density < 4:
        return 3, f"hits={hits} density={density:.1f}"
    if density < 6:
        return 4, f"hits={hits} density={density:.1f}"
    return 5, f"hits={hits} density={density:.1f}"


def score_idempotency(src_files: list[Path]) -> tuple[int, str]:
    """幂等性：idempotency / unique_key / dedup / nonce"""
    text = "\n".join(_read_text(p) for p in src_files)
    keywords = [
        r"idempoten",
        r"unique_key",
        r"unique_id",
        r"dedup",
        r"nonce",
        r"on_conflict",
    ]
    hits = sum(len(re.findall(kw, text, re.IGNORECASE)) for kw in keywords)
    if hits == 0:
        return 0, "no idempotency markers"
    if hits == 1:
        return 1, f"hits={hits}"
    if hits <= 3:
        return 2, f"hits={hits}"
    if hits <= 5:
        return 3, f"hits={hits}"
    if hits <= 10:
        return 4, f"hits={hits}"
    return 5, f"hits={hits}"


def score_events(src_files: list[Path]) -> tuple[int, str]:
    """事件发射：emit_event / event_types 引用"""
    text = "\n".join(_read_text(p) for p in src_files)
    emit = len(re.findall(r"emit_event", text))
    types = len(re.findall(r"event_types|EventType", text))
    total = emit + types
    if total == 0:
        return 0, "no emit_event"
    if total == 1:
        return 1, f"emit={emit} types={types}"
    if total <= 3:
        return 2, f"emit={emit} types={types}"
    if total <= 5:
        return 3, f"emit={emit} types={types}"
    if total <= 10:
        return 4, f"emit={emit} types={types}"
    return 5, f"emit={emit} types={types}"


def score_docs(adapter_dir: Path) -> tuple[int, str]:
    """文档：README 行数 + 字段映射段 + 已知 corner case 段"""
    readme = adapter_dir / "README.md"
    if not readme.exists():
        return 0, "no README"
    txt = _read_text(readme)
    lines = len(txt.splitlines())
    score = 0
    if lines >= 10:
        score += 1
    if lines >= 100:
        score += 1
    if lines >= 250:
        score += 1
    if re.search(r"字段映射|field\s*map|mapping", txt, re.IGNORECASE):
        score += 1
    if re.search(r"corner|已知问题|known\s*issue|caveat|注意事项", txt, re.IGNORECASE):
        score += 1
    return min(score, 5), f"lines={lines}"


def score_adapter(name: str) -> AdapterScore:
    adir = ADAPTERS_DIR / name
    src_dir = adir / "src"
    test_dir = adir / "tests"
    src_files = _iter_py(src_dir)
    test_files = [p for p in _iter_py(test_dir) if p.name.startswith("test_")]
    src_lines = sum(len(_read_text(p).splitlines()) for p in src_files)

    s = AdapterScore(name=name, src_files=len(src_files), src_lines=src_lines, test_files=len(test_files))

    s.contract, n1 = score_contract(src_files)
    s.error_handling, n2 = score_error_handling(src_files)
    s.testing, n3 = score_testing(src_files, test_files)
    s.rls, n4 = score_rls(src_files)
    s.idempotency, n5 = score_idempotency(src_files)
    s.events, n6 = score_events(src_files)
    s.docs, n7 = score_docs(adir)

    s.notes = [
        f"contract: {n1}",
        f"errors: {n2}",
        f"tests: {n3}",
        f"rls: {n4}",
        f"idempotency: {n5}",
        f"events: {n6}",
        f"docs: {n7}",
    ]
    return s


def render_markdown(scores: list[AdapterScore]) -> str:
    lines = []
    lines.append("| Adapter | Contract | Errors | Tests | RLS | Idempot | Events | Docs | Total | Pass(>=22) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for s in scores:
        lines.append(
            f"| {s.name} | {s.contract} | {s.error_handling} | {s.testing} | {s.rls} | "
            f"{s.idempotency} | {s.events} | {s.docs} | **{s.total}** | "
            f"{'PASS' if s.passed else 'FAIL'} |"
        )
    passed = sum(1 for s in scores if s.passed)
    lines.append("")
    lines.append(f"**汇总**：{passed} / {len(scores)} 适配器达标（门禁线 {PASS_THRESHOLD}/35）")
    return "\n".join(lines)


def render_json(scores: list[AdapterScore]) -> str:
    return json.dumps(
        {
            "threshold": PASS_THRESHOLD,
            "total_adapters": len(scores),
            "passed": sum(1 for s in scores if s.passed),
            "scores": [
                {**asdict(s), "total": s.total, "passed": s.passed}
                for s in scores
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="14 适配器 7 维评分")
    parser.add_argument("--adapter", help="只评一个（按目录名）")
    parser.add_argument("--json", help="JSON 输出路径（- 输出 stdout）")
    parser.add_argument("--markdown", help="Markdown 输出路径（- 输出 stdout）")
    args = parser.parse_args()

    targets = [args.adapter] if args.adapter else ADAPTERS
    missing = [t for t in targets if not (ADAPTERS_DIR / t).exists()]
    if missing:
        print(f"[warn] 缺失适配器目录: {missing}", file=sys.stderr)
        targets = [t for t in targets if t not in missing]

    scores = [score_adapter(t) for t in targets]

    md = render_markdown(scores)
    js = render_json(scores)

    if args.markdown == "-":
        print(md)
    elif args.markdown:
        Path(args.markdown).write_text(md, encoding="utf-8")
        print(f"[ok] markdown -> {args.markdown}", file=sys.stderr)

    if args.json == "-":
        print(js)
    elif args.json:
        Path(args.json).write_text(js, encoding="utf-8")
        print(f"[ok] json -> {args.json}", file=sys.stderr)

    if not args.markdown and not args.json:
        # 默认双输出 stdout
        print(md)
        print()
        print(js)

    # exit code = 失败适配器数（CI 可读）
    return sum(1 for s in scores if not s.passed)


if __name__ == "__main__":
    sys.exit(main())
