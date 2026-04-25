"""Tier 1 — PR-2 (R-A4-7) tx-trade 启动门禁：生产环境拒绝 TX_AUTH_ENABLED=false

§19 复审独立审查发现 (Sprint A4 R-A4-7)：
  rbac.py 的 _dev_bypass() 在 TX_AUTH_ENABLED=false 时短路通过且不写任何
  deny 审计。生产环境若**任何一次**配置漂移误设此值（k8s ConfigMap 误改、
  helm values 误覆盖、migration 脚本临时设置忘恢复），所有 RBAC 检查全部
  失效且不留任何痕迹 — 与 R-补2-1 请求重放同等级的安全风险。

修复策略：
  1. 在 main.py lifespan 早期调用 assert_no_dev_bypass_in_production()
  2. 识别"生产"用项目约定 TUNXIANG_ENV=prod（gitops/prod/*/values-override.yaml
     已采纳）。其他环境 (dev/test/uat/pilot/edge) 允许 dev_bypass。
  3. 抛 DevBypassInProductionError → k8s 容器启动失败 → readiness probe 失败
     → 运维强制修复配置才能恢复服务。fail loud > fail silent。
"""
from __future__ import annotations

import os

import pytest

# 这个测试文件本身不应触发 dev_bypass — 它只是测**门禁函数**自身的逻辑。
# 设置 TX_AUTH_ENABLED=true 是基线，单测内部用 monkeypatch 改值。
os.environ.setdefault("TX_AUTH_ENABLED", "true")

from src.security.rbac import (  # noqa: E402
    DevBypassInProductionError,
    assert_no_dev_bypass_in_production,
)


# ──────────────────────────────────────────────────────────────────────────
# 场景 1：生产环境 + dev_bypass 必须 raise
# ──────────────────────────────────────────────────────────────────────────


def test_prod_plus_dev_bypass_raises(monkeypatch):
    """TUNXIANG_ENV=prod + TX_AUTH_ENABLED=false → DevBypassInProductionError。

    这是核心防线：生产 ConfigMap 误改 / helm values 漂移 / migration 临时改
    后忘恢复等场景，门禁必须 fail-loud 让容器启动失败。
    """
    monkeypatch.setenv("TUNXIANG_ENV", "prod")
    monkeypatch.setenv("TX_AUTH_ENABLED", "false")

    with pytest.raises(DevBypassInProductionError) as ei:
        assert_no_dev_bypass_in_production()
    # 错误信息必须包含具体的 env 名 + auth 值，方便运维 grep
    msg = str(ei.value)
    assert "production" in msg.lower()
    assert "TUNXIANG_ENV='prod'" in msg
    assert "TX_AUTH_ENABLED='false'" in msg


# ──────────────────────────────────────────────────────────────────────────
# 场景 2：生产环境 + RBAC 启用 → 正常通过
# ──────────────────────────────────────────────────────────────────────────


def test_prod_plus_auth_enabled_passes(monkeypatch):
    """TUNXIANG_ENV=prod + TX_AUTH_ENABLED=true → 正常通过（生产基线）。"""
    monkeypatch.setenv("TUNXIANG_ENV", "prod")
    monkeypatch.setenv("TX_AUTH_ENABLED", "true")

    # 不抛 = 通过
    assert_no_dev_bypass_in_production()


def test_prod_with_default_auth_passes(monkeypatch):
    """TUNXIANG_ENV=prod + TX_AUTH_ENABLED 未设置 → 默认 true → 通过。"""
    monkeypatch.setenv("TUNXIANG_ENV", "prod")
    monkeypatch.delenv("TX_AUTH_ENABLED", raising=False)

    assert_no_dev_bypass_in_production()


# ──────────────────────────────────────────────────────────────────────────
# 场景 3：非生产环境允许 dev_bypass（单测 / staging 不受门禁影响）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "env_value",
    [
        "dev",
        "test",
        "uat",
        "pilot",
        "edge",
        "",  # 未设置等价于 dev（默认值）
        "staging",  # 项目未约定但常见手填 — 不应误伤
        "local",  # 同上
    ],
)
def test_non_production_allows_dev_bypass(monkeypatch, env_value):
    """所有非 prod 环境（dev/test/uat/pilot/edge/未设置/手填）都允许 dev_bypass。

    防御性：若运维误把 TUNXIANG_ENV 设为非约定值（staging/local 等），
    门禁 fail-open（允许）而不是 fail-close（拒绝），避免单测和 staging
    被误伤。"prod" 是唯一明确的拒绝触发条件。
    """
    if env_value:
        monkeypatch.setenv("TUNXIANG_ENV", env_value)
    else:
        monkeypatch.delenv("TUNXIANG_ENV", raising=False)
    monkeypatch.setenv("TX_AUTH_ENABLED", "false")

    # 不抛 = 通过
    assert_no_dev_bypass_in_production()


# ──────────────────────────────────────────────────────────────────────────
# 场景 4：大小写无关（防 PROD / Prod 等手填变体）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("prod_variant", ["prod", "PROD", "Prod", "prOD", " prod ", "prod\n"])
def test_prod_variants_case_insensitive_and_trimmed(monkeypatch, prod_variant):
    """TUNXIANG_ENV 大小写 + 空白处理：所有 prod 变体都应触发门禁。

    防御 helm values 编辑器误加空格 / 换行；CI/CD 模板宏展开多余字符等。
    """
    monkeypatch.setenv("TUNXIANG_ENV", prod_variant)
    monkeypatch.setenv("TX_AUTH_ENABLED", "false")

    with pytest.raises(DevBypassInProductionError):
        assert_no_dev_bypass_in_production()


# ──────────────────────────────────────────────────────────────────────────
# 场景 5：TX_AUTH_ENABLED 大小写无关（_dev_bypass 已经处理，验证门禁不破）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("auth_disabled_variant", ["false", "FALSE", "False", "fAlSe"])
def test_prod_plus_auth_disabled_case_variants_raises(monkeypatch, auth_disabled_variant):
    """TX_AUTH_ENABLED 各种 false 大小写变体在生产都触发门禁（依赖 _dev_bypass 大小写归一）。"""
    monkeypatch.setenv("TUNXIANG_ENV", "prod")
    monkeypatch.setenv("TX_AUTH_ENABLED", auth_disabled_variant)

    with pytest.raises(DevBypassInProductionError):
        assert_no_dev_bypass_in_production()


# ──────────────────────────────────────────────────────────────────────────
# 场景 6：TX_AUTH_ENABLED=true 的各种变体在生产都通过
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "auth_enabled_value",
    ["true", "TRUE", "True", "1", "yes", "anything-not-false"],
)
def test_prod_plus_anything_not_false_passes(monkeypatch, auth_enabled_value):
    """_dev_bypass 仅当值精确等于 'false'（lower 后）才返回 True。
    其他任何值（true / 1 / yes / 乱码）都视为启用 RBAC，门禁通过。

    防御方向：宁可让"配置怪值"通过门禁，也不能在生产因为奇怪字符串误拒。
    生产代码路径正确启用 RBAC 是安全的（最坏退化为已认证用户被拒，可重启修复）。
    """
    monkeypatch.setenv("TUNXIANG_ENV", "prod")
    monkeypatch.setenv("TX_AUTH_ENABLED", auth_enabled_value)

    assert_no_dev_bypass_in_production()
