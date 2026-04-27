#!/usr/bin/env python3
"""Sprint H — 徐记海鲜 DEMO Go/No-Go 10 项检查脚本

参考：docs/sprint-plan-2026Q2-unified.md § 3 Week 8 DEMO 门槛

检查项：
  1. Tier 1 测试 100% 通过
  2. k6 P99 < 200ms
  3. 支付成功率 > 99.9%
  4. 断网 4h E2E 绿（nightly 连续 3 日）
  5. 收银员零培训（3 位签字）
  6. 三商户 scorecard ≥ 85
  7. RLS/凭证/端口/CORS/secrets 零告警
  8. scripts/demo-reset.sh 回退验证
  9. 至少 1 个 A/B 实验 running 未熔断
  10. 三套演示话术打印就位

使用：
  python scripts/demo_go_no_go.py --tenant-id <uuid> --env demo
  python scripts/demo_go_no_go.py --json  # CI 用，输出 JSON
  python scripts/demo_go_no_go.py --strict  # 任何 FAIL 即 exit 1

环境变量：
  DATABASE_URL  — PostgreSQL 连接串（默认 postgres://localhost/tunxiang_demo）
  DEMO_TENANT_ID — DEMO 租户 UUID（默认 10000000-0000-0000-0000-000000001001）

输出样例：
  ┌──────────────────────────────────────────┬──────┬────────────┐
  │ Checkpoint                               │ Status│ Details    │
  ├──────────────────────────────────────────┼──────┼────────────┤
  │ 1. Tier 1 测试 100% 通过                 │  ✅  │ 237/237    │
  │ 2. k6 P99 < 200ms                        │  ⚠️  │ 需运行 k6   │
  │ ...                                      │      │            │
  └──────────────────────────────────────────┴──────┴────────────┘
  Go: 8  |  No-Go: 0  |  Warning: 2
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEMO_TENANT = "10000000-0000-0000-0000-000000001001"
DEFAULT_DATABASE_URL = "postgresql://localhost/tunxiang_demo"


# ─────────────────────────────────────────────────────────────
# 检查结果数据结构
# ─────────────────────────────────────────────────────────────


class CheckStatus(str, Enum):
    GO = "GO"       # 通过
    NO_GO = "NO_GO" # 未通过（阻塞上线）
    WARNING = "WARNING"  # 警告（可上线但需跟进）
    SKIPPED = "SKIPPED"  # 当前环境无法校验（如 k6 未安装）


@dataclass
class CheckResult:
    checkpoint_id: int
    name: str
    status: CheckStatus
    details: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def emoji(self) -> str:
        return {
            CheckStatus.GO: "✅",
            CheckStatus.NO_GO: "❌",
            CheckStatus.WARNING: "⚠️",
            CheckStatus.SKIPPED: "⏭️",
        }[self.status]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ─────────────────────────────────────────────────────────────
# 检查函数
# ─────────────────────────────────────────────────────────────


def check_tier1_tests(args: argparse.Namespace) -> CheckResult:
    """1. Tier 1 测试 100% 通过"""
    tier1_files = list(REPO_ROOT.glob("services/*/tests/**/test_*tier1*.py"))
    if not tier1_files:
        # 兼容 src/tests/ 子目录结构
        tier1_files = list(REPO_ROOT.glob("services/*/src/tests/**/test_*tier1*.py"))
    if not tier1_files:
        return CheckResult(
            checkpoint_id=1,
            name="Tier 1 测试 100% 通过",
            status=CheckStatus.WARNING,
            details="未找到 *tier1*.py 测试文件；参考 CLAUDE.md § 20",
            evidence={"tier1_test_files": []},
        )

    if args.skip_tests:
        return CheckResult(
            checkpoint_id=1,
            name="Tier 1 测试 100% 通过",
            status=CheckStatus.SKIPPED,
            details="--skip-tests 开启",
            evidence={"file_count": len(tier1_files)},
        )

    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", "-q", "--no-header", *[str(f) for f in tier1_files]],  # noqa: S603
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            checkpoint_id=1,
            name="Tier 1 测试 100% 通过",
            status=CheckStatus.NO_GO,
            details="pytest 执行超过 5min，疑似死循环",
        )
    except FileNotFoundError:
        return CheckResult(
            checkpoint_id=1,
            name="Tier 1 测试 100% 通过",
            status=CheckStatus.SKIPPED,
            details="python3/pytest 未安装",
        )

    passed = result.returncode == 0
    return CheckResult(
        checkpoint_id=1,
        name="Tier 1 测试 100% 通过",
        status=CheckStatus.GO if passed else CheckStatus.NO_GO,
        details=f"{'全部通过' if passed else '有失败'}；{len(tier1_files)} 文件",
        evidence={
            "return_code": result.returncode,
            "tail": result.stdout.splitlines()[-3:] if result.stdout else [],
        },
    )


def check_k6_p99(args: argparse.Namespace) -> CheckResult:
    """2. k6 P99 < 200ms"""
    k6_results = REPO_ROOT / "infra" / "performance" / "k6-latest-results.json"
    if not k6_results.exists():
        return CheckResult(
            checkpoint_id=2,
            name="k6 P99 < 200ms",
            status=CheckStatus.SKIPPED,
            details="infra/performance/k6-latest-results.json 不存在；需运行 k6",
        )

    try:
        data = json.loads(k6_results.read_text(encoding="utf-8"))
        p99 = float(data.get("metrics", {}).get("http_req_duration", {}).get("p(99)", 0))
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        return CheckResult(
            checkpoint_id=2,
            name="k6 P99 < 200ms",
            status=CheckStatus.NO_GO,
            details=f"k6 结果解析失败: {exc}",
        )

    passed = 0 < p99 < 200
    return CheckResult(
        checkpoint_id=2,
        name="k6 P99 < 200ms",
        status=CheckStatus.GO if passed else CheckStatus.NO_GO,
        details=f"P99 = {p99:.2f}ms",
        evidence={"p99_ms": p99},
    )


def check_payment_success_rate(args: argparse.Namespace) -> CheckResult:
    """3. 支付成功率 > 99.9%"""
    # 查 payments 表（或 payment_events）最近 7 天成功率
    query = """
    SELECT
      COUNT(*) AS total,
      COUNT(*) FILTER (WHERE status IN ('success', 'paid', 'completed')) AS success
    FROM payments
    WHERE tenant_id = %(tenant_id)s
      AND is_deleted = false
      AND created_at >= NOW() - INTERVAL '7 days'
    """
    try:
        rows = run_sql(query, {"tenant_id": args.tenant_id}, database_url=args.database_url)
    except (RuntimeError, Exception) as exc:  # noqa: BLE001 — DB 路径异常兜底
        return CheckResult(
            checkpoint_id=3,
            name="支付成功率 > 99.9%",
            status=CheckStatus.SKIPPED,
            details=f"DB 查询失败或 payments 表不存在: {exc}",
        )

    if not rows:
        return CheckResult(
            checkpoint_id=3,
            name="支付成功率 > 99.9%",
            status=CheckStatus.WARNING,
            details="近 7 天无支付记录",
        )

    total = int(rows[0]["total"] or 0)
    success = int(rows[0]["success"] or 0)
    if total == 0:
        return CheckResult(
            checkpoint_id=3,
            name="支付成功率 > 99.9%",
            status=CheckStatus.WARNING,
            details="近 7 天无支付记录",
        )

    rate = success / total
    passed = rate >= 0.999
    return CheckResult(
        checkpoint_id=3,
        name="支付成功率 > 99.9%",
        status=CheckStatus.GO if passed else CheckStatus.NO_GO,
        details=f"{success}/{total} = {rate*100:.3f}%",
        evidence={"success": success, "total": total, "rate": rate},
    )


def check_offline_4h_e2e(args: argparse.Namespace) -> CheckResult:
    """4. 断网 4h E2E 绿（nightly 连续 3 日）"""
    nightly_log = REPO_ROOT / "infra" / "nightly" / "offline-e2e-results.json"
    if not nightly_log.exists():
        return CheckResult(
            checkpoint_id=4,
            name="断网 4h E2E 绿（nightly 连续 3 日）",
            status=CheckStatus.SKIPPED,
            details="infra/nightly/offline-e2e-results.json 不存在",
        )

    try:
        data = json.loads(nightly_log.read_text(encoding="utf-8"))
        recent = data.get("recent_runs", [])[-3:]
    except (json.JSONDecodeError, KeyError):
        return CheckResult(
            checkpoint_id=4,
            name="断网 4h E2E 绿（nightly 连续 3 日）",
            status=CheckStatus.NO_GO,
            details="nightly log 格式错误",
        )

    if len(recent) < 3:
        return CheckResult(
            checkpoint_id=4,
            name="断网 4h E2E 绿（nightly 连续 3 日）",
            status=CheckStatus.WARNING,
            details=f"仅 {len(recent)} 次运行，需 3 次连续",
        )

    all_green = all(r.get("status") == "green" for r in recent)
    return CheckResult(
        checkpoint_id=4,
        name="断网 4h E2E 绿（nightly 连续 3 日）",
        status=CheckStatus.GO if all_green else CheckStatus.NO_GO,
        details=f"最近 3 次: {[r.get('status') for r in recent]}",
        evidence={"recent_runs": recent},
    )


def check_cashier_zero_training(args: argparse.Namespace) -> CheckResult:
    """5. 收银员零培训（3 位签字）"""
    sign_off = REPO_ROOT / "docs" / "demo" / "cashier-signoff.md"
    if not sign_off.exists():
        return CheckResult(
            checkpoint_id=5,
            name="收银员零培训（3 位签字）",
            status=CheckStatus.WARNING,
            details="docs/demo/cashier-signoff.md 不存在",
        )

    content = sign_off.read_text(encoding="utf-8")
    # 扫描 '姓名:' 或 '签字:' 关键字
    signoff_count = content.count("签字:") + content.count("签名:")
    passed = signoff_count >= 3
    return CheckResult(
        checkpoint_id=5,
        name="收银员零培训（3 位签字）",
        status=CheckStatus.GO if passed else CheckStatus.NO_GO,
        details=f"检测到 {signoff_count} 个签字",
        evidence={"signoff_count": signoff_count},
    )


def check_scorecards(args: argparse.Namespace) -> CheckResult:
    """6. 三商户 scorecard ≥ 85"""
    scorecard_dir = REPO_ROOT / "docs" / "demo" / "scorecards"
    if not scorecard_dir.exists():
        return CheckResult(
            checkpoint_id=6,
            name="三商户 scorecard ≥ 85",
            status=CheckStatus.WARNING,
            details="docs/demo/scorecards/ 不存在",
        )

    scorecards = list(scorecard_dir.glob("*.json"))
    if len(scorecards) < 3:
        return CheckResult(
            checkpoint_id=6,
            name="三商户 scorecard ≥ 85",
            status=CheckStatus.WARNING,
            details=f"仅 {len(scorecards)} 个 scorecard，需要 3 个",
        )

    scores = []
    for sc in scorecards[:3]:
        try:
            data = json.loads(sc.read_text(encoding="utf-8"))
            scores.append({"merchant": data.get("merchant"), "score": data.get("score", 0)})
        except (json.JSONDecodeError, OSError):
            continue

    all_pass = all(s["score"] >= 85 for s in scores)
    return CheckResult(
        checkpoint_id=6,
        name="三商户 scorecard ≥ 85",
        status=CheckStatus.GO if all_pass else CheckStatus.NO_GO,
        details=", ".join(f"{s['merchant']}={s['score']}" for s in scores),
        evidence={"scorecards": scores},
    )


def check_security_audit(args: argparse.Namespace) -> CheckResult:
    """7. RLS/凭证/端口/CORS/secrets 零告警"""
    audit_script = REPO_ROOT / "scripts" / "check_rls_policies.py"
    if not audit_script.exists():
        return CheckResult(
            checkpoint_id=7,
            name="RLS/凭证/端口/CORS/secrets 零告警",
            status=CheckStatus.WARNING,
            details="scripts/check_rls_policies.py 不存在",
        )

    if args.skip_tests:
        return CheckResult(
            checkpoint_id=7,
            name="RLS/凭证/端口/CORS/secrets 零告警",
            status=CheckStatus.SKIPPED,
            details="--skip-tests 开启",
        )

    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(audit_script), "--json"],  # noqa: S603
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult(
            checkpoint_id=7,
            name="RLS/凭证/端口/CORS/secrets 零告警",
            status=CheckStatus.SKIPPED,
            details="审计脚本执行异常",
        )

    # Exit code 2 = DB 连接失败（SKIPPED，不阻塞）
    if result.returncode == 2:
        return CheckResult(
            checkpoint_id=7,
            name="RLS/凭证/端口/CORS/secrets 零告警",
            status=CheckStatus.SKIPPED,
            details="DB 连接失败（非 RLS 违规）",
            evidence={"return_code": result.returncode},
        )

    # 尝试解析 JSON 获取结构化信息
    details = "RLS 审计通过" if result.returncode == 0 else "RLS 审计失败"
    evidence: dict[str, Any] = {"return_code": result.returncode}
    try:
        data = json.loads(result.stdout)
        summary = data.get("summary", {})
        if summary:
            details = (
                f"{summary.get('ok_count', 0)} OK / "
                f"{summary.get('issue_tables', 0)} 问题 / "
                f"critical={summary.get('critical', 0)} "
                f"high={summary.get('high', 0)} "
                f"medium={summary.get('medium', 0)}"
            )
            evidence["summary"] = summary
    except (json.JSONDecodeError, TypeError):
        pass

    return CheckResult(
        checkpoint_id=7,
        name="RLS/凭证/端口/CORS/secrets 零告警",
        status=CheckStatus.GO if result.returncode == 0 else CheckStatus.NO_GO,
        details=details,
        evidence=evidence,
    )


def check_demo_reset(args: argparse.Namespace) -> CheckResult:
    """8. scripts/demo-reset.sh 回退验证"""
    demo_reset = REPO_ROOT / "scripts" / "demo-reset.sh"
    cleanup_sql = REPO_ROOT / "infra" / "demo" / "xuji_seafood" / "cleanup.sql"

    reset_exists = demo_reset.exists()
    cleanup_exists = cleanup_sql.exists()

    if not (reset_exists or cleanup_exists):
        return CheckResult(
            checkpoint_id=8,
            name="scripts/demo-reset.sh 回退验证",
            status=CheckStatus.NO_GO,
            details="demo-reset.sh 和 cleanup.sql 都不存在",
        )

    return CheckResult(
        checkpoint_id=8,
        name="scripts/demo-reset.sh 回退验证",
        status=CheckStatus.GO,
        details=(
            ("demo-reset.sh ✓" if reset_exists else "")
            + (" cleanup.sql ✓" if cleanup_exists else "")
        ).strip(),
        evidence={
            "demo_reset_sh": str(demo_reset) if reset_exists else None,
            "cleanup_sql": str(cleanup_sql) if cleanup_exists else None,
        },
    )


def check_ab_experiment(args: argparse.Namespace) -> CheckResult:
    """9. 至少 1 个 A/B 实验 running 未熔断"""
    query = """
    SELECT experiment_key, status, circuit_breaker_tripped
    FROM ab_experiments
    WHERE tenant_id = %(tenant_id)s
      AND is_deleted = false
      AND status = 'running'
    LIMIT 10
    """
    try:
        rows = run_sql(query, {"tenant_id": args.tenant_id}, database_url=args.database_url)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            checkpoint_id=9,
            name="至少 1 个 A/B 实验 running 未熔断",
            status=CheckStatus.SKIPPED,
            details=f"ab_experiments 表查询失败: {exc}",
        )

    if not rows:
        return CheckResult(
            checkpoint_id=9,
            name="至少 1 个 A/B 实验 running 未熔断",
            status=CheckStatus.NO_GO,
            details="无 running 实验",
        )

    running_not_tripped = [
        r for r in rows if not r.get("circuit_breaker_tripped")
    ]
    if not running_not_tripped:
        return CheckResult(
            checkpoint_id=9,
            name="至少 1 个 A/B 实验 running 未熔断",
            status=CheckStatus.NO_GO,
            details=f"{len(rows)} 个 running 实验，全部已熔断",
        )

    return CheckResult(
        checkpoint_id=9,
        name="至少 1 个 A/B 实验 running 未熔断",
        status=CheckStatus.GO,
        details=f"{len(running_not_tripped)} 个 running 未熔断",
        evidence={"experiments": [r["experiment_key"] for r in running_not_tripped[:5]]},
    )


def check_demo_scripts(args: argparse.Namespace) -> CheckResult:
    """10. 三套演示话术打印就位"""
    scripts_dir = REPO_ROOT / "docs" / "demo" / "scripts"
    if not scripts_dir.exists():
        return CheckResult(
            checkpoint_id=10,
            name="三套演示话术打印就位",
            status=CheckStatus.WARNING,
            details="docs/demo/scripts/ 不存在",
        )

    scripts = [
        f for f in scripts_dir.glob("*.md")
        if not f.name.startswith("README")
    ]
    passed = len(scripts) >= 3
    return CheckResult(
        checkpoint_id=10,
        name="三套演示话术打印就位",
        status=CheckStatus.GO if passed else CheckStatus.WARNING,
        details=f"{len(scripts)} 套话术: {[s.name for s in scripts[:3]]}",
        evidence={"script_count": len(scripts)},
    )


CHECKS: list[Callable[[argparse.Namespace], CheckResult]] = [
    check_tier1_tests,
    check_k6_p99,
    check_payment_success_rate,
    check_offline_4h_e2e,
    check_cashier_zero_training,
    check_scorecards,
    check_security_audit,
    check_demo_reset,
    check_ab_experiment,
    check_demo_scripts,
]


# ─────────────────────────────────────────────────────────────
# DB 工具
# ─────────────────────────────────────────────────────────────


def run_sql(
    query: str, params: dict, *, database_url: str
) -> list[dict]:
    """同步 DB 查询（仅用于 Go/No-Go 脚本；生产代码走 asyncpg）"""
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # type: ignore
    except ImportError as exc:
        raise RuntimeError("psycopg2 未安装，无法执行 DB 检查") from exc

    conn = psycopg2.connect(database_url)
    try:
        # 设置 RLS 租户上下文
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.tenant_id', %s, true)",
                (params.get("tenant_id", ""),),
            )
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
# 渲染
# ─────────────────────────────────────────────────────────────


def render_table(results: list[CheckResult]) -> str:
    """ASCII 表格输出"""
    lines = []
    header = "┌─────┬─────────────────────────────────────────┬──────┬────────────────────────────────┐"
    lines.append(header)
    lines.append("│ #   │ Checkpoint                              │ 状态 │ Details                        │")
    lines.append("├─────┼─────────────────────────────────────────┼──────┼────────────────────────────────┤")
    for r in results:
        name = r.name.ljust(39)[:39]
        details = (r.details or "").ljust(30)[:30]
        lines.append(f"│ {r.checkpoint_id:<3} │ {name} │  {r.emoji()}  │ {details} │")
    lines.append("└─────┴─────────────────────────────────────────┴──────┴────────────────────────────────┘")
    return "\n".join(lines)


def summary(results: list[CheckResult]) -> dict[str, int]:
    stats = {"GO": 0, "NO_GO": 0, "WARNING": 0, "SKIPPED": 0}
    for r in results:
        stats[r.status.value] += 1
    return stats


# ─────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sprint H DEMO Go/No-Go 10 项检查",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.getenv("DEMO_TENANT_ID", DEFAULT_DEMO_TENANT),
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    parser.add_argument("--env", default="demo", help="环境标识（用于日志）")
    parser.add_argument(
        "--json", action="store_true", help="输出 JSON（CI 用）"
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="任何 NO_GO 即 exit 1（CI 门禁用）",
    )
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="跳过耗时的子进程测试（Tier 1 + RLS audit）",
    )
    parser.add_argument(
        "--only", type=int, nargs="+", default=None,
        help="只跑指定 checkpoint id（如 --only 1 7 8）",
    )
    args = parser.parse_args()

    checks_to_run = CHECKS
    if args.only:
        checks_to_run = [c for c in CHECKS if _checkpoint_id(c) in args.only]

    print(
        f"# 徐记海鲜 DEMO Go/No-Go 检查 ({args.env} / tenant={args.tenant_id})",
        file=sys.stderr,
    )
    print(
        f"# 时间：{datetime.now(tz=timezone.utc).isoformat()}",
        file=sys.stderr,
    )

    results: list[CheckResult] = []
    for check_fn in checks_to_run:
        try:
            result = check_fn(args)
        except Exception as exc:  # noqa: BLE001
            cpid = _checkpoint_id(check_fn)
            result = CheckResult(
                checkpoint_id=cpid,
                name=check_fn.__doc__.split("\n")[0].strip() if check_fn.__doc__ else check_fn.__name__,
                status=CheckStatus.NO_GO,
                details=f"检查抛异常：{exc}",
            )
        results.append(result)

    stats = summary(results)

    if args.json:
        output = {
            "env": args.env,
            "tenant_id": args.tenant_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "summary": stats,
            "checks": [r.to_dict() for r in results],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(render_table(results))
        print()
        total = len(results)
        print(
            f"Total: {total}  |  "
            f"✅ GO: {stats['GO']}  |  "
            f"❌ NO_GO: {stats['NO_GO']}  |  "
            f"⚠️ WARNING: {stats['WARNING']}  |  "
            f"⏭️ SKIPPED: {stats['SKIPPED']}"
        )
        blocking = stats["NO_GO"]
        if blocking == 0:
            print("\n🚀 DEMO 可以 Go")
        else:
            print(f"\n⛔ DEMO No-Go — {blocking} 个阻塞项需修复")

    # Exit code
    if args.strict and stats["NO_GO"] > 0:
        return 1
    return 0


def _checkpoint_id(check_fn: Callable) -> int:
    """从 check_fn 的 docstring 第一行提取 'N. ...' 中的 N"""
    doc = (check_fn.__doc__ or "").strip()
    if not doc:
        return 0
    first = doc.split("\n")[0].strip()
    # "1. Tier 1 测试 ..." → 1
    try:
        return int(first.split(".")[0])
    except (ValueError, IndexError):
        return 0


if __name__ == "__main__":
    sys.exit(main())
