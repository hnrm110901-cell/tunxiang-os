"""scripts/ci/check_prometheus_ports.py 单测 (Phase D #820)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch


def _load_module():
    """动态 load check_prometheus_ports.py 而不走包 import (脚本不是 package)."""
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "ci" / "check_prometheus_ports.py"
    spec = importlib.util.spec_from_file_location("check_prometheus_ports", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_prometheus_ports"] = module
    spec.loader.exec_module(module)
    return module


def test_parse_dockerfile_port_cmd_form(tmp_path: Path) -> None:
    """Dockerfile CMD --port 8001 → 8001."""
    mod = _load_module()
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        'FROM python:3.11\n'
        'CMD ["uvicorn", "services.tx_trade.src.main:app", "--host", "0.0.0.0", "--port", "8001"]\n'
    )
    assert mod.parse_dockerfile_port(dockerfile) == 8001


def test_parse_dockerfile_port_expose_fallback(tmp_path: Path) -> None:
    """无 CMD --port, EXPOSE 8013 fallback → 8013."""
    mod = _load_module()
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        'FROM python:3.11\n'
        'EXPOSE 8013\n'
        'CMD ["uvicorn", "src.main:app"]\n'
    )
    assert mod.parse_dockerfile_port(dockerfile) == 8013


def test_parse_dockerfile_port_missing(tmp_path: Path) -> None:
    """无 Dockerfile → None."""
    mod = _load_module()
    assert mod.parse_dockerfile_port(tmp_path / "no_such_file") is None


def test_parse_prometheus_targets_strips_tunxiang_prefix(tmp_path: Path) -> None:
    """tunxiang-tx-trade → tx-trade in dict."""
    mod = _load_module()
    yml = tmp_path / "p.yml"
    yml.write_text(
        """global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'tunxiang-tx-trade'
    static_configs:
      - targets: ['tx-trade:8001']
    metrics_path: '/metrics'
  - job_name: 'tunxiang-gateway'
    static_configs:
      - targets: ['gateway:8000']
    metrics_path: '/metrics'
  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']
"""
    )
    with patch.object(mod, "PROMETHEUS_YML", yml):
        result = mod.parse_prometheus_targets()

    # tunxiang- 前缀剥, redis (infra) 不收
    assert result == {"tx-trade": 8001, "gateway": 8000}


def test_main_real_repo_state_returns_zero() -> None:
    """端到端: 真 repo state 跑 main() 当前应 0 (Phase B 修完所有 mismatch).

    保护: 任何 PR 改 prometheus.yml 端口与 Dockerfile drift 时本测试会本地 fail.
    """
    mod = _load_module()
    rc = mod.main()
    assert rc == 0, "prometheus.yml 与 Dockerfile 真实 drift, 跑 scripts/ci/check_prometheus_ports.py 看详情"


def test_known_dockerfile_bugs_register_contains_tx_predict() -> None:
    """tx-predict 已知 bug 留在 register 防 silently 移除."""
    mod = _load_module()
    assert "tx-predict" in mod.KNOWN_DOCKERFILE_BUGS
    expected_prom, expected_docker, follow_up = mod.KNOWN_DOCKERFILE_BUGS["tx-predict"]
    assert expected_prom == 8019
    assert expected_docker == 8013
    assert "#820-P" in follow_up
