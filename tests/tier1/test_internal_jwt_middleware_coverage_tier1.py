"""所有服务 InternalJwtMiddleware 挂载覆盖度 Tier 1 测试

审计 S-02 闭环 part 3：PR #202 给 tx-trade 挂载示范，本 PR 完成剩 21 服务批量
挂载。本测试静态扫描所有 services/*/src/main.py 验证：
  1. import InternalJwtMiddleware
  2. 调用 app.add_middleware(InternalJwtMiddleware)

不实际启动服务（每个 main.py import 大量业务 router 太重）；运行时验证
留给 staging 部署 + 24h 监控。

S-02 完成度：
  - 70% (PR #202)：middleware 实现 + tx-trade 示范
  - 100% (本 PR)：全部 22 服务挂载（gateway 不挂，因为它是签发方）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 必须挂 InternalJwtMiddleware 的服务（22 个）
# gateway 不挂（它是 mint JWT 的签发方，不验证自己签的）
EXPECTED_SERVICES = (
    "tunxiang-api",
    "tx-agent",
    "tx-analytics",
    "tx-brain",
    "tx-civic",
    "tx-devforge",
    "tx-expense",
    "tx-finance",
    "tx-forge",
    "tx-growth",
    "tx-indonesia",
    "tx-intel",
    "tx-malaysia",
    "tx-member",
    "tx-menu",
    "tx-ops",
    "tx-org",
    "tx-pay",
    "tx-predict",
    "tx-supply",
    "tx-trade",  # PR #202 已挂
    "tx-vietnam",
)

GATEWAY_EXEMPT = "gateway"  # 签发方，不验证


def _read_main_py(service: str) -> str:
    main_py = _REPO_ROOT / "services" / service / "src" / "main.py"
    if not main_py.exists():
        pytest.skip(f"{service}/src/main.py 不存在")
    return main_py.read_text(encoding="utf-8")


class TestServiceMounting:
    """每个服务必须 import + add_middleware InternalJwtMiddleware"""

    @pytest.mark.parametrize("service", EXPECTED_SERVICES)
    def test_imports_internal_jwt_middleware(self, service):
        content = _read_main_py(service)
        assert (
            "from shared.security.src.internal_jwt_middleware import InternalJwtMiddleware"
            in content
        ), f"{service}/src/main.py 必须 import InternalJwtMiddleware"

    @pytest.mark.parametrize("service", EXPECTED_SERVICES)
    def test_calls_add_middleware(self, service):
        content = _read_main_py(service)
        # 匹配 app.add_middleware(InternalJwtMiddleware) 调用（允许多空格）
        pattern = re.compile(
            r"app\.add_middleware\s*\(\s*InternalJwtMiddleware\s*\)"
        )
        assert pattern.search(content), (
            f"{service}/src/main.py 必须调 app.add_middleware(InternalJwtMiddleware)"
        )

    @pytest.mark.parametrize("service", EXPECTED_SERVICES)
    def test_mounted_only_once(self, service):
        """重复挂载会让 middleware chain 多次校验同一 token，浪费且语义混淆。"""
        content = _read_main_py(service)
        count = content.count("app.add_middleware(InternalJwtMiddleware)")
        assert count == 1, (
            f"{service}/src/main.py InternalJwtMiddleware 挂载次数={count}（应为 1）"
        )


class TestGatewayExempt:
    """gateway 不应挂 InternalJwtMiddleware（它是签发方，不验自己签的）"""

    def test_gateway_does_not_mount(self):
        # gateway 用 InternalJwtMiddleware 验自己签的会循环
        # gateway 在 proxy.py 里 mint JWT 给下游，自己不需要 verify
        main_py = _REPO_ROOT / "services" / GATEWAY_EXEMPT / "src" / "main.py"
        if not main_py.exists():
            pytest.skip("gateway/src/main.py 不存在")
        content = main_py.read_text(encoding="utf-8")
        assert "InternalJwtMiddleware" not in content, (
            "gateway 是 mint 签发方，不应该挂 InternalJwtMiddleware（会循环验自己）"
        )


class TestMountingPosition:
    """挂载位置约束：在 CORSMiddleware 之前（CORS preflight 不被 JWT 拦截）

    starlette middleware 顺序：app.add_middleware 调用顺序 = 外到内反向
    （后 add 的先执行）。InternalJwtMiddleware 后 add → 先执行 → 业务路由前
    已注入 state。CORS 通常先 add → 最外层 → preflight 不被 JWT 拦。

    本测试验证：InternalJwtMiddleware 出现在 main.py 中**晚于** CORS
    （即 add 顺序：CORS 先，InternalJwt 后）。
    """

    @pytest.mark.parametrize("service", EXPECTED_SERVICES)
    def test_mounted_after_cors(self, service):
        content = _read_main_py(service)

        # 严格检查"CORSMiddleware add_middleware 调用"是否存在
        # （仅 import CORSMiddleware 不算，必须真挂）
        cors_call_re = re.compile(
            r"app\.add_middleware\s*\(\s*\n?\s*CORSMiddleware",
            re.MULTILINE,
        )
        m = cors_call_re.search(content)
        if not m:
            # 真没挂 CORS：无 preflight 顺序约束，跳过本测试
            pytest.skip(f"{service} 没挂 CORSMiddleware，无 preflight 顺序约束")

        cors_pos = m.start()
        ijm_pos = content.find("app.add_middleware(InternalJwtMiddleware)")
        assert ijm_pos > cors_pos, (
            f"{service}: InternalJwtMiddleware 应在 CORSMiddleware 之后 add（"
            f"FastAPI 后 add 的在内层 → CORS 在外层先 see preflight → "
            f"OPTIONS 直接返 200 不被 JWT 校验）。"
            f"当前 cors_pos={cors_pos} ijm_pos={ijm_pos}"
        )


class TestRolloutDocSync:
    """rollout doc 必须与实际挂载状态一致"""

    def test_doc_lists_all_22_services(self):
        doc = _REPO_ROOT / "docs" / "security" / "internal-jwt-rollout.md"
        assert doc.exists(), "internal-jwt-rollout.md 必须存在"
        content = doc.read_text(encoding="utf-8")
        # 每个 EXPECTED_SERVICES 都应在文档中提及
        missing = [s for s in EXPECTED_SERVICES if s not in content]
        assert not missing, f"rollout doc 漏掉这些服务：{missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
