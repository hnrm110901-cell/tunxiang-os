#!/usr/bin/env python3
"""
屯象OS 边缘节点批量 SSH 并行部署工具

适用场景
--------
1. 第一批 5~30 家门店同时部署（有线网络或 WiFi 已预配置）
2. 升级现有边缘节点（推送新版脚本 + 重启服务）
3. 批量健康检查（--action=check）

输入格式（CSV，--hosts-file）
-----------------------------
  store_id,host_or_ip,ssh_user,ssh_port,store_name
  S001,192.168.10.101,pi,22,尝在一起旗舰店
  S002,192.168.10.102,pi,22,徐记海鲜总店
  S003,zhilian-edge-003.local,pi,22,最黔线3号店

用法
----
  python3 scripts/batch_deploy_edge.py \\
    --hosts-file  stores.csv \\
    --api-url     https://api.zlsjos.cn \\
    --token       bootstrap-token \\
    --ssh-key     ~/.ssh/zhilian_edge_key \\
    --action      deploy      # deploy | upgrade | check | restart

  # 仅检查
  python3 scripts/batch_deploy_edge.py --hosts-file stores.csv --action check

  # 升级（推送最新脚本并重启服务）
  python3 scripts/batch_deploy_edge.py --hosts-file stores.csv --action upgrade \\
    --api-url https://api.zlsjos.cn --token new-bootstrap-token
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("zhilian-batch-deploy")

SCRIPT_DIR = Path(__file__).parent
APP_DIR = SCRIPT_DIR.parent
EDGE_DIR = APP_DIR / "edge"

# 最大并发 SSH 连接数（避免目标路由器崩溃）
_MAX_WORKERS = 8
# SSH 单次命令超时（秒）
_SSH_TIMEOUT = 120


class Action(str, Enum):
    DEPLOY = "deploy"    # 全新安装
    UPGRADE = "upgrade"  # 推送脚本 + 重启
    CHECK = "check"      # 仅运行 health_check
    RESTART = "restart"  # 仅重启服务


@dataclass
class StoreTarget:
    store_id: str
    host: str
    ssh_user: str = "pi"
    ssh_port: int = 22
    store_name: str = ""


@dataclass
class DeployResult:
    store_id: str
    store_name: str
    host: str
    success: bool
    message: str
    detail: str = ""
    duration_seconds: float = 0.0


def _ssh_cmd(
    target: StoreTarget,
    command: str,
    ssh_key: Optional[str] = None,
    timeout: int = _SSH_TIMEOUT,
) -> Tuple[int, str, str]:
    """在远端执行单条命令，返回 (returncode, stdout, stderr)。"""
    ssh_args = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes",
        "-p", str(target.ssh_port),
    ]
    if ssh_key:
        ssh_args += ["-i", ssh_key]
    ssh_args += [f"{target.ssh_user}@{target.host}", command]
    try:
        result = subprocess.run(
            ssh_args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"SSH 超时（>{timeout}s）"
    except Exception as exc:
        return -2, "", str(exc)


def _scp_file(
    local_path: Path,
    target: StoreTarget,
    remote_path: str,
    ssh_key: Optional[str] = None,
) -> bool:
    """将本地文件推送到远端。"""
    scp_args = [
        "scp",
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-P", str(target.ssh_port),
    ]
    if ssh_key:
        scp_args += ["-i", ssh_key]
    scp_args += [str(local_path), f"{target.ssh_user}@{target.host}:{remote_path}"]
    try:
        result = subprocess.run(scp_args, capture_output=True, timeout=60)
        return result.returncode == 0
    except Exception:
        return False


# ------------------------------------------------------------------ #
#  部署逻辑
# ------------------------------------------------------------------ #

def deploy_store(
    target: StoreTarget,
    api_url: str,
    bootstrap_token: str,
    ssh_key: Optional[str],
    action: Action,
) -> DeployResult:
    t0 = time.time()
    store_label = f"{target.store_id}({target.store_name or target.host})"
    logger.info("[%s] 开始 action=%s", store_label, action)

    if action == Action.CHECK:
        return _action_check(target, ssh_key, t0)

    if action == Action.RESTART:
        return _action_restart(target, ssh_key, t0)

    if action == Action.UPGRADE:
        return _action_upgrade(target, api_url, bootstrap_token, ssh_key, t0)

    # DEPLOY
    return _action_deploy(target, api_url, bootstrap_token, ssh_key, t0)


def _action_check(target: StoreTarget, ssh_key: Optional[str], t0: float) -> DeployResult:
    rc, out, err = _ssh_cmd(
        target,
        "python3 /opt/zhilian-edge/edge_health_check.py --json 2>/dev/null || "
        "echo '{\"overall\":\"error\",\"checks\":[]}'",
        ssh_key,
        timeout=30,
    )
    elapsed = time.time() - t0
    if rc != 0:
        return DeployResult(target.store_id, target.store_name, target.host,
                            False, f"SSH 失败 rc={rc}", err, elapsed)
    try:
        data = json.loads(out)
        overall = data.get("overall", "error")
        checks = data.get("checks", [])
        problems = [c["name"] for c in checks if c.get("severity") != "ok"]
        detail = "异常项：" + "、".join(problems) if problems else "全部正常"
        ok = overall == "ok"
        return DeployResult(target.store_id, target.store_name, target.host,
                            ok, f"健康状态={overall}", detail, elapsed)
    except Exception as exc:
        return DeployResult(target.store_id, target.store_name, target.host,
                            False, "解析响应失败", str(exc), elapsed)


def _action_restart(target: StoreTarget, ssh_key: Optional[str], t0: float) -> DeployResult:
    rc, out, err = _ssh_cmd(
        target,
        "sudo systemctl restart zhilian-edge-node.service zhilian-edge-shokz.service && "
        "systemctl is-active zhilian-edge-node.service",
        ssh_key,
    )
    elapsed = time.time() - t0
    ok = rc == 0 and "active" in out
    return DeployResult(target.store_id, target.store_name, target.host,
                        ok, "服务已重启" if ok else f"重启失败 rc={rc}", err, elapsed)


def _action_upgrade(
    target: StoreTarget,
    api_url: str,
    bootstrap_token: str,
    ssh_key: Optional[str],
    t0: float,
) -> DeployResult:
    """推送最新 edge 脚本，更新 bootstrap token，重启服务。"""
    edge_files = [
        EDGE_DIR / "edge_node_agent.py",
        EDGE_DIR / "shokz_callback_daemon.py",
        EDGE_DIR / "shokz_bluetooth_manager.py",
        EDGE_DIR / "edge_model_manager.py",
        EDGE_DIR / "edge_business_queue.py",
        EDGE_DIR / "edge_health_check.py",
    ]
    for f in edge_files:
        if not f.exists():
            continue
        ok = _scp_file(f, target, f"/opt/zhilian-edge/{f.name}", ssh_key)
        if not ok:
            return DeployResult(target.store_id, target.store_name, target.host,
                                False, f"推送 {f.name} 失败", "", time.time() - t0)

    # 更新 bootstrap token（如果提供）
    if bootstrap_token:
        rc, _, err = _ssh_cmd(
            target,
            f"sudo sed -i 's|EDGE_API_TOKEN=.*|EDGE_API_TOKEN={bootstrap_token}|' "
            f"/etc/zhilian-edge/edge-node.env && "
            f"sudo sed -i 's|EDGE_API_BASE_URL=.*|EDGE_API_BASE_URL={api_url}|' "
            f"/etc/zhilian-edge/edge-node.env",
            ssh_key,
        )
        if rc != 0:
            return DeployResult(target.store_id, target.store_name, target.host,
                                False, "更新 token 失败", err, time.time() - t0)

    return _action_restart(target, ssh_key, t0)


def _action_deploy(
    target: StoreTarget,
    api_url: str,
    bootstrap_token: str,
    ssh_key: Optional[str],
    t0: float,
) -> DeployResult:
    """将安装脚本推送到远端并执行。"""
    install_script = SCRIPT_DIR / "install_raspberry_pi_edge.sh"
    if not install_script.exists():
        return DeployResult(target.store_id, target.store_name, target.host,
                            False, "安装脚本不存在", str(install_script), 0.0)

    # 推送安装脚本
    ok = _scp_file(install_script, target, "/tmp/install_edge.sh", ssh_key)
    if not ok:
        return DeployResult(target.store_id, target.store_name, target.host,
                            False, "推送安装脚本失败", "", time.time() - t0)

    # 推送 edge 目录文件
    edge_files = list(EDGE_DIR.glob("*.py")) + list(EDGE_DIR.glob("*.sh")) + list(EDGE_DIR.glob("*.service"))
    for f in edge_files:
        _scp_file(f, target, f"/tmp/{f.name}", ssh_key)

    # 远端执行安装
    install_cmd = (
        f"chmod +x /tmp/install_edge.sh && "
        f"sudo EDGE_API_BASE_URL={api_url} "
        f"EDGE_API_TOKEN={bootstrap_token} "
        f"EDGE_STORE_ID={target.store_id} "
        f"EDGE_DEVICE_NAME={target.store_id}-rpi5 "
        f"bash /tmp/install_edge.sh 2>&1 | tail -20"
    )
    rc, out, err = _ssh_cmd(target, install_cmd, ssh_key, timeout=180)
    elapsed = time.time() - t0
    ok = rc == 0
    return DeployResult(
        target.store_id, target.store_name, target.host,
        ok,
        "安装成功" if ok else f"安装失败 rc={rc}",
        out or err,
        elapsed,
    )


# ------------------------------------------------------------------ #
#  并行调度
# ------------------------------------------------------------------ #

def batch_deploy(
    targets: List[StoreTarget],
    api_url: str,
    bootstrap_token: str,
    ssh_key: Optional[str],
    action: Action,
    max_workers: int = _MAX_WORKERS,
) -> List[DeployResult]:
    results: List[DeployResult] = []
    lock = threading.Lock()
    semaphore = threading.Semaphore(max_workers)

    def worker(t: StoreTarget) -> None:
        with semaphore:
            r = deploy_store(t, api_url, bootstrap_token, ssh_key, action)
            with lock:
                results.append(r)
                _print_result(r)

    threads = [threading.Thread(target=worker, args=(t,), daemon=True) for t in targets]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    return results


def _print_result(r: DeployResult) -> None:
    sym = "✅" if r.success else "❌"
    label = f"{r.store_id:<10} {r.store_name:<12} {r.host:<20}"
    print(f"  {sym} {label} {r.message}  ({r.duration_seconds:.1f}s)")
    if r.detail and not r.success:
        for line in r.detail.splitlines()[:5]:
            print(f"       {line}")


# ------------------------------------------------------------------ #
#  CSV 解析
# ------------------------------------------------------------------ #

def load_targets(csv_file: str) -> List[StoreTarget]:
    targets = []
    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            targets.append(StoreTarget(
                store_id=row.get("store_id", "").strip(),
                host=row.get("host_or_ip", "").strip(),
                ssh_user=row.get("ssh_user", "pi").strip(),
                ssh_port=int(row.get("ssh_port", "22").strip()),
                store_name=row.get("store_name", "").strip(),
            ))
    return [t for t in targets if t.store_id and t.host]


# ------------------------------------------------------------------ #
#  CLI
# ------------------------------------------------------------------ #

def main() -> int:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="屯象OS 边缘节点批量部署工具")
    parser.add_argument("--hosts-file", required=True, help="门店 CSV 文件")
    parser.add_argument("--api-url", default="", help="API Gateway 地址")
    parser.add_argument("--token", default="", help="Bootstrap Token")
    parser.add_argument("--ssh-key", default=None, help="SSH 私钥路径")
    parser.add_argument("--action", default="deploy",
                        choices=[a.value for a in Action],
                        help="操作类型 deploy|upgrade|check|restart")
    parser.add_argument("--workers", type=int, default=_MAX_WORKERS,
                        help=f"最大并发数（默认 {_MAX_WORKERS}）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印目标，不执行")
    args = parser.parse_args()

    if not shutil.which("ssh"):
        print("错误: ssh 命令不可用", file=sys.stderr)
        return 1

    targets = load_targets(args.hosts_file)
    if not targets:
        print("错误: hosts-file 中无有效目标", file=sys.stderr)
        return 1

    action = Action(args.action)
    print()
    print("=" * 60)
    print(f"  屯象OS 边缘节点批量{action.value}  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标门店: {len(targets)} 家  并发: {args.workers}")
    if args.api_url:
        print(f"  API Gateway: {args.api_url}")
    print("=" * 60)

    if args.dry_run:
        for t in targets:
            print(f"  [DRY] {t.store_id:<10} {t.host:<20} {t.store_name}")
        return 0

    start_time = time.time()
    results = batch_deploy(
        targets,
        api_url=args.api_url,
        bootstrap_token=args.token,
        ssh_key=args.ssh_key,
        action=action,
        max_workers=args.workers,
    )
    elapsed = time.time() - start_time

    # 汇总
    success = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    print()
    print("-" * 60)
    print(f"  完成: {len(success)}/{len(results)} 成功  总耗时: {elapsed:.1f}s")
    if failed:
        print("  失败门店:")
        for r in failed:
            print(f"    ❌ {r.store_id} {r.store_name}: {r.message}")
    print("=" * 60)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
