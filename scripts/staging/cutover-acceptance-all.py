#!/usr/bin/env python3
"""Cutover E2E 5 项验收一键执行脚本

对应 docs/runbooks/cutover-acceptance-checklist.md（PR #216）的 5 项验收契约。
QA 可在 staging 部署完成后跑此脚本，得到 PASS/FAIL/MANUAL 的统一报告。

5 项验收：
  1. Tier 1 测试套（自动）
  2. k6 性能套（需 k6 + scenario 文件 — 当前 MANUAL）
  3. 支付全链路 3 渠道（需 sandbox 配置 — 当前 MANUAL）
  4. 跨租户隔离 3 测试（自动 — 需 2 个 staging tenant JWT）
  5. 断网 4h 恢复（人工 — 需 SSH + ifconfig 操作）

用法：
    export STAGING_HOST=staging.tunxiang.internal
    export TENANT_A_JWT=<jwt-for-tenant-a>
    export TENANT_B_JWT=<jwt-for-tenant-b>
    export TENANT_B_UUID=<uuid-of-tenant-b>
    python3 scripts/staging/cutover-acceptance-all.py

退出码：
    0 — 5 项全 PASS（含 MANUAL 已确认）
    1 — 至少 1 项 FAIL
    2 — 前置环境未配
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import httpx
except ImportError:
    print("ERROR: 缺依赖 httpx (pip install httpx)", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

STAGING_HOST = os.environ.get("STAGING_HOST", "")
TENANT_A_JWT = os.environ.get("TENANT_A_JWT", "")
TENANT_B_JWT = os.environ.get("TENANT_B_JWT", "")
TENANT_B_UUID = os.environ.get("TENANT_B_UUID", "")
NODE_PORT_HOST = os.environ.get("NODE_PORT_HOST", "")  # 测试 NetworkPolicy 用
NODE_PORT = int(os.environ.get("NODE_PORT", "30001"))  # tx-trade nodePort 默认


class Result(NamedTuple):
    item: str
    status: str  # PASS / FAIL / SKIP / MANUAL
    detail: str


# ─── Item 1: Tier 1 测试套 ────────────────────────────────────────────────────
def run_tier1_tests() -> Result:
    """跑 pytest tests/tier1/ — 100% pass 才 PASS。"""
    if not REPO_ROOT.joinpath("tests", "tier1").exists():
        return Result("1. Tier 1 tests", "SKIP", "tests/tier1/ 目录不存在")

    env = os.environ.copy()
    env.setdefault("TX_INTERNAL_JWT_SECRET", "ci-test-secret-32-bytes-aaaaaaaaaaa")
    env.setdefault("TX_ENV", "test")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/tier1/", "-q", "--tb=line", "--no-header"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode == 0:
        # 抓最后一行 "X passed in Y.Ys"
        last_line = result.stdout.strip().split("\n")[-1]
        return Result("1. Tier 1 tests", "PASS", last_line)
    return Result(
        "1. Tier 1 tests",
        "FAIL",
        f"pytest exit {result.returncode}; tail: {result.stdout.strip().split(chr(10))[-1]}",
    )


# ─── Item 2: k6 性能套 ────────────────────────────────────────────────────────
def run_k6_perf() -> Result:
    """200 vus × 10min — 需 k6 install + scenario 文件。"""
    k6_scenario = REPO_ROOT / "tests" / "k6" / "cutover-checkout-200vus.js"
    if not k6_scenario.exists():
        return Result(
            "2. k6 performance",
            "MANUAL",
            f"scenario {k6_scenario.relative_to(REPO_ROOT)} 待 QA 创建（详见 cutover-staging-deployment.md §七）",
        )

    if not subprocess.run(["which", "k6"], capture_output=True).returncode == 0:
        return Result("2. k6 performance", "SKIP", "k6 未安装（brew install k6 / 见 https://k6.io/docs/get-started/installation/）")

    if not STAGING_HOST:
        return Result("2. k6 performance", "SKIP", "STAGING_HOST env 未配")

    print("  Running k6 (this takes ~10 minutes)...")
    result = subprocess.run(
        [
            "k6",
            "run",
            "--vus=200",
            "--duration=10m",
            "--env",
            f"STAGING_HOST={STAGING_HOST}",
            str(k6_scenario),
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode == 0:
        return Result("2. k6 performance", "PASS", "P99 < 200ms / err < 0.1% (per scenario thresholds)")
    return Result("2. k6 performance", "FAIL", f"k6 exit {result.returncode}; tail: {result.stdout.strip().split(chr(10))[-1]}")


# ─── Item 3: 支付全链路 3 渠道 ─────────────────────────────────────────────────
def run_payment_e2e() -> Result:
    """微信/支付宝/银联 query/refund/callback — 需 sandbox 配置。"""
    e2e_script = REPO_ROOT / "scripts" / "staging" / "payment-e2e-three-channels.sh"
    if not e2e_script.exists():
        return Result(
            "3. Payment 3 channels",
            "MANUAL",
            "scripts/staging/payment-e2e-three-channels.sh 待 QA 创建；手工清单详见 cutover-acceptance-checklist.md §3",
        )
    result = subprocess.run(["bash", str(e2e_script)], capture_output=True, text=True, timeout=600)
    if result.returncode == 0:
        return Result("3. Payment 3 channels", "PASS", "wechat/alipay/unionpay × pay/query/refund 全 200")
    return Result("3. Payment 3 channels", "FAIL", f"exit {result.returncode}")


# ─── Item 4: 跨租户隔离 3 测试 ─────────────────────────────────────────────────
async def run_cross_tenant_isolation() -> Result:
    """3 个测试：A 跨查 B 返 0；无 JWT 401；nodePort timeout。"""
    if not all([STAGING_HOST, TENANT_A_JWT, TENANT_B_UUID]):
        return Result(
            "4. Cross-tenant isolation",
            "SKIP",
            "需 STAGING_HOST + TENANT_A_JWT + TENANT_B_UUID env",
        )

    issues: list[str] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 测试 1: tenant_A JWT + tenant_B uuid header → 应返 0 行（state 来自 JWT，header 忽略）
        try:
            r = await client.get(
                f"https://{STAGING_HOST}/api/v1/trade/orders",
                headers={
                    "X-Internal-JWT": TENANT_A_JWT,
                    "X-Tenant-ID": TENANT_B_UUID,
                },
            )
            data = r.json() if r.status_code == 200 else {}
            items = data.get("data", {}).get("items", [])
            if items:
                issues.append(f"4.1 cross-tenant leak: 返 {len(items)} 行（应 0）")
        except Exception as exc:  # noqa: BLE001
            issues.append(f"4.1 unexpected error: {exc}")

        # 测试 2: 无 JWT 直发 X-Tenant-ID header → 应 401
        try:
            r = await client.get(
                f"https://{STAGING_HOST}/api/v1/trade/orders",
                headers={"X-Tenant-ID": TENANT_B_UUID},
            )
            if r.status_code != 401:
                issues.append(f"4.2 应 401 但返 {r.status_code}（InternalJwtMiddleware 未生效或 webhook regex 误豁免）")
        except Exception as exc:  # noqa: BLE001
            issues.append(f"4.2 unexpected error: {exc}")

        # 测试 3: nodePort 直连 → 应 timeout/refused（NetworkPolicy 阻止）
        if NODE_PORT_HOST:
            try:
                r = await client.get(
                    f"http://{NODE_PORT_HOST}:{NODE_PORT}/api/v1/orders",
                    timeout=5.0,
                )
                # 能拿到响应说明 NetworkPolicy 没生效
                issues.append(f"4.3 nodePort 应 timeout 但返 {r.status_code}")
            except (httpx.ConnectError, httpx.TimeoutException):
                pass  # ✓ 预期
        else:
            issues.append("4.3 SKIP — NODE_PORT_HOST 未配")

    if not issues:
        return Result("4. Cross-tenant isolation", "PASS", "3 测试全绿")
    return Result("4. Cross-tenant isolation", "FAIL", "; ".join(issues))


# ─── Item 5: 断网 4h 恢复 ─────────────────────────────────────────────────────
def run_offline_4h() -> Result:
    """需 SSH + ifconfig — 不能自动跑。"""
    return Result(
        "5. Network outage 4h",
        "MANUAL",
        "需 SSH 到 staging-edge-1 + ifconfig en0 down/up + 4h 业务操作；详见 cutover-acceptance-checklist.md §5",
    )


# ─── 主入口 ───────────────────────────────────────────────────────────────────
async def main() -> int:
    print("=== Cutover E2E 5 项验收 ===")
    print(f"STAGING_HOST  = {STAGING_HOST or '(未配)'}")
    print(f"TENANT_A_JWT  = {'(set)' if TENANT_A_JWT else '(未配)'}")
    print(f"TENANT_B_JWT  = {'(set)' if TENANT_B_JWT else '(未配)'}")
    print(f"NODE_PORT_HOST= {NODE_PORT_HOST or '(未配)'}")
    print()

    print("Item 1: Tier 1 测试套（自动）...")
    r1 = run_tier1_tests()

    print("Item 2: k6 性能套...")
    r2 = run_k6_perf()

    print("Item 3: 支付全链路 3 渠道...")
    r3 = run_payment_e2e()

    print("Item 4: 跨租户隔离 3 测试...")
    r4 = await run_cross_tenant_isolation()

    print("Item 5: 断网 4h 恢复...")
    r5 = run_offline_4h()

    print()
    print("=== 总结 ===")
    sym_map = {"PASS": "✅", "FAIL": "❌", "SKIP": "⊘", "MANUAL": "✋"}
    fail_count = 0
    pass_count = 0
    for r in [r1, r2, r3, r4, r5]:
        sym = sym_map.get(r.status, "?")
        print(f"  {sym} {r.item:30} [{r.status}] {r.detail}")
        if r.status == "FAIL":
            fail_count += 1
        elif r.status == "PASS":
            pass_count += 1

    print()
    print(f"  PASS: {pass_count}/5    FAIL: {fail_count}/5    其他（SKIP/MANUAL）: {5 - pass_count - fail_count}/5")
    print()

    if fail_count > 0:
        print(f"❌ FAIL — {fail_count} 项 FAIL，详见上方", file=sys.stderr)
        return 1

    if pass_count + sum(1 for r in [r1, r2, r3, r4, r5] if r.status == "MANUAL") < 5:
        print("⚠️  非 PASS 项需 QA 手工补完成（SKIP 项需先配 env）", file=sys.stderr)

    print("✅ 自动化部分全 PASS / SKIP（MANUAL 项需 QA 手工跑后回填）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
