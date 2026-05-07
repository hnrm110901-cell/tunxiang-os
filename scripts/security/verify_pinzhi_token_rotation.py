#!/usr/bin/env python3
"""品智 17 个 Token 轮换 e2e 探测脚本（Python 版）

对应 docs/runbooks/s01-pinzhi-token-rotation.md §5.1
取代旧 .sh 版（独立 review 发现：bash 版用 /api/shop/info 端点不存在 + 缺签名）。

本脚本调用真实的 PinzhiAdapter 签名 + /pinzhi/organizations.do 端点（adapter.py:170）
来验证 token 是否被品智服务器接受。

用法：
    python3 scripts/security/verify_pinzhi_token_rotation.py
    PINZHI_VERIFY_BRAND=czyz python3 scripts/security/verify_pinzhi_token_rotation.py
    PINZHI_VERIFY_TIMEOUT=10 python3 scripts/security/verify_pinzhi_token_rotation.py

退出码：
    0 — 17/17 OK
    1 — 至少 1 个 fail
    2 — 前置依赖缺失（httpx 未装 / merchants.py 缺）
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 仓库根加 sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import httpx
except ImportError:
    print("ERROR: 缺依赖 httpx (pip install httpx)", file=sys.stderr)
    sys.exit(2)

try:
    from shared.adapters.pinzhi_pos.src.merchants import MERCHANT_CONFIG
    from shared.adapters.pinzhi_pos.src.signature import generate_sign
except ImportError as exc:
    print(f"ERROR: 加载 pinzhi 模块失败 — {exc}", file=sys.stderr)
    sys.exit(2)

TIMEOUT = float(os.environ.get("PINZHI_VERIFY_TIMEOUT", "5"))
BRAND_FILTER = os.environ.get("PINZHI_VERIFY_BRAND", "")


async def probe_token(
    client: httpx.AsyncClient,
    brand: str,
    base_url: str,
    label: str,
    env_var: str,
    ognid: str | None,
) -> tuple[str, str]:
    """探测单个 token；返回 (status, message)"""
    token = os.environ.get(env_var, "").strip()
    if not token:
        return ("FAIL", f"env {env_var} 未设置")

    # 调用 /pinzhi/organizations.do（adapter.py:170 实际使用的端点）
    params: dict[str, str] = {}
    if ognid and ognid != "API":
        params["ognid"] = ognid
    params["sign"] = generate_sign(token, params)

    url = f"{base_url}/pinzhi/organizations.do"
    try:
        resp = await client.get(url, params=params, timeout=TIMEOUT)
    except httpx.TimeoutException:
        return ("FAIL", f"timeout {TIMEOUT}s")
    except (httpx.ConnectError, httpx.HTTPError) as exc:
        return ("FAIL", f"http error: {exc}")

    code = resp.status_code
    if code != 200:
        return ("FAIL", f"HTTP {code}")

    # 品智成功响应：success=0；token 错误响应：success!=0 + msg="token已过期"等
    try:
        body = resp.json()
    except ValueError:
        return ("SKIP", f"HTTP 200 但响应非 JSON（{resp.text[:80]}）")

    success = body.get("success")
    if success == 0 or success is None:
        return ("OK", "200 OK")

    msg = body.get("msg", "未知")
    return ("FAIL", f"业务错误 success={success} msg={msg!r}")


async def main() -> int:
    # 构建 17 个 token 探测列表
    targets: list[tuple[str, str, str, str, str | None]] = []
    for brand_key, brand_cfg in MERCHANT_CONFIG.items():
        if BRAND_FILTER and BRAND_FILTER != brand_key:
            continue
        base_url = brand_cfg["pinzhi_base_url"]
        # API 主令牌（一个）
        targets.append((brand_key, base_url, "API主令牌", brand_cfg["api_token_env"], None))
        # 各店 token
        for store_id, store_cfg in brand_cfg["stores"].items():
            targets.append(
                (brand_key, base_url, store_cfg["name"], store_cfg["token_env"], store_id)
            )

    print(f"=== 品智 17 token 轮换 e2e 探测（Python） ===")
    print(f"目标 {len(targets)} 个；超时 {TIMEOUT}s/个；过滤 brand={BRAND_FILTER or 'all'}")
    print()

    ok_count = 0
    fail_count = 0
    skip_count = 0

    async with httpx.AsyncClient() as client:
        for brand, base_url, label, env_var, ognid in targets:
            status, msg = await probe_token(client, brand, base_url, label, env_var, ognid)
            sym = {"OK": "✓", "FAIL": "✗", "SKIP": "~"}[status]
            line = f"{sym} [{brand}/{ognid or 'API'} {label}] {msg}"
            if status == "OK":
                ok_count += 1
                print(line)
            elif status == "FAIL":
                fail_count += 1
                print(line, file=sys.stderr)
            else:
                skip_count += 1
                print(line, file=sys.stderr)

    print()
    print(f"=== 总结 ===")
    print(f"  ✓ OK:    {ok_count}")
    print(f"  ✗ FAIL:  {fail_count}")
    print(f"  ~ SKIP:  {skip_count}")
    print()

    if fail_count > 0:
        print(f"❌ FAIL — {fail_count} 个 token 验证失败", file=sys.stderr)
        return 1

    expected = len(targets)
    if ok_count < expected:
        print(
            f"⚠️  仅 {ok_count}/{expected} OK（其余 {skip_count} skip） — 需手工复核",
            file=sys.stderr,
        )
        return 1

    print("✅ 全部探测 OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
