#!/usr/bin/env python3
"""
LLM 网关烟测脚本

用途：
  - 运维在首次部署 / API Key 轮换 / provider 升级后，手动跑一遍三级降级链路是否正常
  - 不在自动化 CI 中运行（会真实消耗 API token）

用法：
    export ANTHROPIC_API_KEY=sk-ant-...
    # 可选：
    export DEEPSEEK_API_KEY=sk-...
    export OPENAI_API_KEY=sk-...
    export LLM_PROVIDER_PRIORITY=claude,deepseek,openai   # 默认即如此

    python scripts/smoke_test_llm_gateway.py

预期：
  - Claude 有 Key → Claude 优先返回
  - Claude 无 Key / 失败 → 自动降级 DeepSeek
  - DeepSeek 也失败 → 降级 OpenAI
  - 全失败 → 抛 LLMAllProvidersFailedError

输出每一级 provider 的 status / 耗时 / token，并验证 prompt_audit_logs 表是否写入一条。

注意：该脚本真实调用外部 API，每次约消耗 0.001~0.01 USD。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# 将仓库根加入 sys.path，保证脚本可独立运行
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_MESSAGE = "请用一句话总结餐饮行业的三大成本。"


async def _run_once() -> None:
    # 延迟导入，依赖 src/core/config 已加载环境变量
    from src.services.llm_gateway.factory import get_llm_gateway, reset_gateway

    reset_gateway()
    gateway = get_llm_gateway()

    print("=" * 60)
    print(" LLM 网关烟测")
    print("=" * 60)
    print(f"Provider 链：{[p.name for p in gateway.providers]}")
    print(f"请求：{TEST_MESSAGE}")
    print("-" * 60)

    t0 = time.perf_counter()
    try:
        resp = await gateway.chat(
            messages=[{"role": "user", "content": TEST_MESSAGE}],
            system="你是餐饮成本专家。",
            temperature=0.3,
            max_tokens=200,
            user_id="smoke_test",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] 全链失败：{type(e).__name__}: {e}")
        sys.exit(2)

    elapsed = (time.perf_counter() - t0) * 1000
    print(f"[OK] provider={resp.get('provider')}  耗时={elapsed:.0f}ms")
    print(f"     token={resp.get('usage')}")
    print(f"     回答：{resp.get('content', '')[:200]}")

    # 审计日志校验
    await _verify_audit_log()


async def _verify_audit_log() -> None:
    """best-effort：查询最新一条 prompt_audit_logs"""
    try:
        from sqlalchemy import desc, select

        from src.core.database import AsyncSessionLocal
        from src.models.prompt_audit_log import PromptAuditLog
    except Exception as e:  # noqa: BLE001
        print(f"[SKIP] 审计表或 DB 会话不可用：{e}")
        return

    try:
        async with AsyncSessionLocal() as sess:
            res = await sess.execute(
                select(PromptAuditLog).order_by(desc(PromptAuditLog.created_at)).limit(1)
            )
            row = res.scalar_one_or_none()
            if row:
                print(f"[OK] prompt_audit_logs 已写入 id={row.id}  provider={getattr(row, 'provider', None)}")
            else:
                print("[WARN] prompt_audit_logs 尚无记录，请检查 DB 连接 / 权限")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 查询审计日志失败：{e}")


def main() -> None:
    # 至少需要一个 provider key
    if not any(
        os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    ):
        print("[FAIL] 未检测到任何 provider 的 API Key，请设置 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY")
        sys.exit(1)

    try:
        asyncio.run(_run_once())
    except KeyboardInterrupt:
        print("已中断")
        sys.exit(130)


if __name__ == "__main__":
    main()
