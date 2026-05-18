#!/usr/bin/env python3
"""Phase D (#820) — Prometheus port drift audit script.

Cross-check infra/monitoring/prometheus/prometheus.yml `targets: ["svc:PORT"]`
vs services/<svc>/Dockerfile `--port PORT` 真实 EXPOSE/CMD 端口。

mismatch → exit 1 + print diff (CI fails the gate).

服务名映射:
  prometheus job: tunxiang-<svc> | target: <svc>:PORT
  Dockerfile path: services/<svc>/Dockerfile (横线连接, 与 helm chart 名一致)

例外:
  - tx-predict: prometheus.yml 标 8019 (CLAUDE.md §5), Dockerfile bug 8013 → 已知 #820-P,
    脚本对 tx-predict 期待 8019 (authoritative source = CLAUDE.md §5)
  - mcp-server: 无 Dockerfile (stdio MCP), prometheus.yml 也不 scrape, 不参与 audit
  - redis/postgresql/prometheus 等基础设施: prometheus.yml 含 job 但不属于本仓库 service, skip
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMETHEUS_YML = REPO_ROOT / "infra" / "monitoring" / "prometheus" / "prometheus.yml"
SERVICES_DIR = REPO_ROOT / "services"

# 基础设施 job (不是本仓库 service)
INFRA_JOBS = {"redis", "postgresql", "prometheus"}

# 已知 Dockerfile bug, prometheus.yml 跟 CLAUDE.md §5 (authoritative)
# key = service name, value = (prom_expected_port, dockerfile_expected_port, follow_up)
KNOWN_DOCKERFILE_BUGS = {
    "tx-predict": (8019, 8013, "#820-P: Dockerfile EXPOSE 8013 与 tx-forge 冲突, 应改 8019"),
}


def parse_prometheus_targets() -> dict[str, int]:
    """从 prometheus.yml 解析 {service_name: port}.

    service_name 是去 `tunxiang-` 前缀后的本仓库 service 名 (eg. "tx-trade"),
    不含基础设施 job (redis/postgresql/prometheus)。
    """
    with open(PROMETHEUS_YML) as f:
        config = yaml.safe_load(f)

    result: dict[str, int] = {}
    for job in config.get("scrape_configs", []):
        job_name = job.get("job_name", "")
        # 去 tunxiang- 前缀
        if job_name.startswith("tunxiang-"):
            svc_name = job_name[len("tunxiang-"):]
            # gateway 特殊: prometheus job 是 tunxiang-gateway 但 helm chart 是 api-gateway,
            # service path 是 services/gateway. 这里保留 prom job 名映射到 services/gateway
        elif job_name in INFRA_JOBS:
            continue
        else:
            # 其他 (eg. 未来加的) — print warning 不 fail
            print(f"WARN: unknown job_name '{job_name}', skip", file=sys.stderr)
            continue

        # 取 first target port
        static = job.get("static_configs", [{}])[0]
        targets = static.get("targets", [])
        if not targets:
            continue
        target = targets[0]
        # target format: "service:port"
        m = re.match(r"^([^:]+):(\d+)$", target)
        if not m:
            print(f"WARN: cannot parse target '{target}' for {job_name}", file=sys.stderr)
            continue
        port = int(m.group(2))
        result[svc_name] = port

    return result


def parse_dockerfile_port(dockerfile: Path) -> int | None:
    """从 Dockerfile 解析 CMD ... --port PORT 或 EXPOSE PORT (取后者优先 CMD)."""
    if not dockerfile.exists():
        return None

    text = dockerfile.read_text()

    # 优先 CMD --port
    cmd_match = re.search(r'CMD\s*\[.*?"--port",\s*"(\d+)"', text, re.DOTALL)
    if cmd_match:
        return int(cmd_match.group(1))

    # fallback EXPOSE
    expose_match = re.search(r"^\s*EXPOSE\s+(\d+)", text, re.MULTILINE)
    if expose_match:
        return int(expose_match.group(1))

    return None


def main() -> int:
    """主入口: 跑 audit, mismatch return 1."""
    prom_ports = parse_prometheus_targets()
    print(f"Parsed {len(prom_ports)} backend service(s) from prometheus.yml")

    mismatches: list[str] = []
    missing_dockerfile: list[str] = []
    known_bugs: list[str] = []

    for svc, prom_port in sorted(prom_ports.items()):
        dockerfile = SERVICES_DIR / svc / "Dockerfile"
        docker_port = parse_dockerfile_port(dockerfile)

        if docker_port is None:
            # mcp-server 等无 Dockerfile, 本来就不该出现在 prom_ports 但保险
            missing_dockerfile.append(svc)
            continue

        if svc in KNOWN_DOCKERFILE_BUGS:
            expected_prom, expected_docker, follow_up = KNOWN_DOCKERFILE_BUGS[svc]
            if prom_port != expected_prom:
                mismatches.append(
                    f"  {svc}: prom_port={prom_port} expected_prom={expected_prom} ({follow_up})"
                )
            if docker_port != expected_docker:
                known_bugs.append(
                    f"  {svc}: docker_port={docker_port} expected_docker={expected_docker} ({follow_up}) — UNEXPECTED FIX, please update KNOWN_DOCKERFILE_BUGS"
                )
            else:
                known_bugs.append(
                    f"  {svc}: known bug present (docker={docker_port} prom={prom_port}); {follow_up}"
                )
            continue

        if prom_port != docker_port:
            mismatches.append(
                f"  {svc}: prom_port={prom_port} dockerfile_port={docker_port}"
            )

    print()
    if known_bugs:
        print("Known Dockerfile bugs (tracked via follow-up):")
        for line in known_bugs:
            print(line)
        print()

    if missing_dockerfile:
        print("Services in prometheus.yml without Dockerfile (review):")
        for svc in missing_dockerfile:
            print(f"  {svc}")
        print()

    if mismatches:
        print("DRIFT DETECTED — prometheus.yml vs Dockerfile mismatch:")
        for line in mismatches:
            print(line)
        return 1

    print(f"OK — all {len(prom_ports)} services aligned (prometheus.yml ↔ Dockerfile)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
