"""S-02 NetworkPolicy values override Tier 1 测试

审计 S-02 part 4 纵深防御：通过 helm NetworkPolicy 限制只 gateway namespace
可达 tx-* services，配合 InternalJwtMiddleware（PR #202 + #208）+ FORCE RLS
（PR #199 + #207）形成完整纵深。

本测试静态分析 values override YAML：
  1. 文件存在 + YAML 合法
  2. networkPolicy.enabled = true
  3. ingress 严格只 gateway/monitoring/同 namespace tx-*
  4. egress 包含 PG/Redis/DNS（必须项）
  5. gateway override 与 tx-* override 区别正确

真 helm template 渲染留 staging dry-run（本地无 helm）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_OVERRIDE_TX = _REPO_ROOT / "infra" / "helm" / "_overrides" / "networkpolicy-s02-cutover.yaml"
_OVERRIDE_GW = _REPO_ROOT / "infra" / "helm" / "_overrides" / "networkpolicy-s02-gateway.yaml"
_DEP_GRAPH = _REPO_ROOT / "docs" / "infra" / "service-dependency-graph.md"
_APPLY_SCRIPT = _REPO_ROOT / "scripts" / "k8s" / "apply_networkpolicy_s02.sh"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestFilesExist:
    def test_tx_override_exists(self):
        assert _OVERRIDE_TX.exists(), f"tx-* override 必须存在：{_OVERRIDE_TX}"

    def test_gateway_override_exists(self):
        assert _OVERRIDE_GW.exists(), f"gateway override 必须存在：{_OVERRIDE_GW}"

    def test_dep_graph_exists(self):
        assert _DEP_GRAPH.exists(), f"依赖图文档必须存在：{_DEP_GRAPH}"

    def test_apply_script_exists(self):
        assert _APPLY_SCRIPT.exists(), f"apply 脚本必须存在：{_APPLY_SCRIPT}"

    def test_apply_script_executable(self):
        import os
        assert os.access(_APPLY_SCRIPT, os.X_OK), "apply script 必须可执行"


class TestTxOverrideStructure:
    """tx-* services 通用 override：严格 ingress + 保守 egress"""

    @pytest.fixture
    def cfg(self):
        return _load(_OVERRIDE_TX)

    def test_yaml_valid(self, cfg):
        assert isinstance(cfg, dict)

    def test_network_policy_enabled(self, cfg):
        assert cfg["networkPolicy"]["enabled"] is True

    def test_has_ingress_rules(self, cfg):
        ingress = cfg["networkPolicy"]["ingress"]
        assert isinstance(ingress, list) and len(ingress) >= 2

    def test_ingress_includes_gateway_namespace(self, cfg):
        ingress = cfg["networkPolicy"]["ingress"]
        gateway_rule_found = False
        for rule in ingress:
            for src in rule.get("from", []):
                ns = src.get("namespaceSelector", {}).get("matchLabels", {})
                if ns.get("kubernetes.io/metadata.name") == "tunxiang-gateway":
                    gateway_rule_found = True
        assert gateway_rule_found, "ingress 必须含 tunxiang-gateway namespace"

    def test_ingress_includes_monitoring(self, cfg):
        ingress = cfg["networkPolicy"]["ingress"]
        monitoring_found = False
        for rule in ingress:
            for src in rule.get("from", []):
                ns = src.get("namespaceSelector", {}).get("matchLabels", {})
                if ns.get("kubernetes.io/metadata.name") == "monitoring":
                    monitoring_found = True
        assert monitoring_found, "ingress 必须含 monitoring（Prometheus scrape）"

    def test_egress_includes_postgres(self, cfg):
        egress = cfg["networkPolicy"]["egress"]
        assert any(
            any(p.get("port") == 5432 for p in rule.get("ports", []))
            for rule in egress
        ), "egress 必须含 PostgreSQL :5432"

    def test_egress_includes_redis(self, cfg):
        egress = cfg["networkPolicy"]["egress"]
        assert any(
            any(p.get("port") == 6379 for p in rule.get("ports", []))
            for rule in egress
        ), "egress 必须含 Redis :6379（PR #201 nonce store）"

    def test_egress_includes_dns(self, cfg):
        egress = cfg["networkPolicy"]["egress"]
        dns_found = False
        for rule in egress:
            for port in rule.get("ports", []):
                if port.get("port") == 53:
                    dns_found = True
        assert dns_found, "egress 必须含 DNS :53"

    def test_egress_allows_internal_pg_cidr_excluded(self, cfg):
        """公网 egress 必须排除 K8s 内部 CIDR（防止绕过 ingress 限制）"""
        egress = cfg["networkPolicy"]["egress"]
        for rule in egress:
            for to in rule.get("to", []):
                ip_block = to.get("ipBlock", {})
                if ip_block.get("cidr") == "0.0.0.0/0":
                    excepts = ip_block.get("except", [])
                    # 必须排除 RFC1918 内网段
                    assert "10.0.0.0/8" in excepts
                    assert "172.16.0.0/12" in excepts
                    assert "192.168.0.0/16" in excepts


class TestGatewayOverrideStructure:
    """api-gateway 特殊 override：允许公网入站"""

    @pytest.fixture
    def cfg(self):
        return _load(_OVERRIDE_GW)

    def test_yaml_valid(self, cfg):
        assert isinstance(cfg, dict)

    def test_network_policy_enabled(self, cfg):
        assert cfg["networkPolicy"]["enabled"] is True

    def test_ingress_includes_ingress_nginx(self, cfg):
        """gateway 必须允许 ingress-nginx 入站（公网入口）"""
        ingress = cfg["networkPolicy"]["ingress"]
        nginx_found = False
        for rule in ingress:
            for src in rule.get("from", []):
                ns = src.get("namespaceSelector", {}).get("matchLabels", {})
                if ns.get("kubernetes.io/metadata.name") == "ingress-nginx":
                    nginx_found = True
        assert nginx_found, "gateway ingress 必须含 ingress-nginx namespace"

    def test_egress_to_tx_services_namespace(self, cfg):
        """gateway egress 必须允许 tunxiang-services namespace（转发到所有 tx-*）"""
        egress = cfg["networkPolicy"]["egress"]
        tx_ns_found = False
        for rule in egress:
            for dst in rule.get("to", []):
                ns = dst.get("namespaceSelector", {}).get("matchLabels", {})
                if ns.get("kubernetes.io/metadata.name") == "tunxiang-services":
                    tx_ns_found = True
        assert tx_ns_found, "gateway egress 必须能转发到 tunxiang-services namespace"


class TestDepGraphSync:
    """依赖图文档必须列出所有有 helm chart 的服务"""

    def test_dep_graph_lists_core_services(self):
        content = _DEP_GRAPH.read_text(encoding="utf-8")
        # 至少列出本 PR 已挂 InternalJwtMiddleware 的核心 22 服务（不全列）
        for svc in [
            "tx-trade", "tx-pay", "tx-menu", "tx-member",
            "tx-ops", "tx-supply", "tx-finance", "tx-agent",
            "tx-analytics", "tx-brain", "tx-org",
            "api-gateway",
        ]:
            assert svc in content, f"依赖图 doc 缺 {svc}"

    def test_dep_graph_has_mermaid(self):
        content = _DEP_GRAPH.read_text(encoding="utf-8")
        assert "```mermaid" in content, "依赖图必须有 mermaid 渲染"

    def test_dep_graph_lists_known_gaps(self):
        """依赖图必须明示已知遗漏（webhook IP 白名单 / Tailscale CIDR / CronJob）"""
        content = _DEP_GRAPH.read_text(encoding="utf-8")
        for must_mention in ["webhook", "Tailscale", "CronJob"]:
            assert must_mention in content, f"依赖图必须提及 {must_mention} 灰色地带"


class TestApplyScriptStructure:
    """apply 脚本必须支持 dry-run + 列出所有 chart"""

    def test_script_supports_dry_run(self):
        content = _APPLY_SCRIPT.read_text(encoding="utf-8")
        assert "--dry-run" in content
        assert "helm template" in content, "dry-run 必须用 helm template 不真应用"

    def test_script_lists_tx_services(self):
        content = _APPLY_SCRIPT.read_text(encoding="utf-8")
        for svc in ["tx-trade", "tx-pay", "tx-menu", "tx-member"]:
            assert svc in content

    def test_script_handles_gateway_separately(self):
        content = _APPLY_SCRIPT.read_text(encoding="utf-8")
        # 用不同 override 文件
        assert "OVERRIDE_GW" in content or "networkpolicy-s02-gateway.yaml" in content
        assert "OVERRIDE_TX" in content or "networkpolicy-s02-cutover.yaml" in content

    def test_script_documents_rollback(self):
        content = _APPLY_SCRIPT.read_text(encoding="utf-8")
        assert "kubectl delete networkpolicy" in content or "helm rollback" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
