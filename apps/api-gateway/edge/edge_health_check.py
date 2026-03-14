#!/usr/bin/env python3
"""
屯象OS 边缘节点健康检查 CLI

运维人员现场排障工具。单次运行，打印所有子系统状态，
返回码 0=全部 OK，1=有警告，2=有严重问题。

用法
----
  python3 edge_health_check.py              # 完整检查
  python3 edge_health_check.py --json       # JSON 输出（供脚本解析）
  python3 edge_health_check.py --quick      # 仅检查注册和网络（< 1s）
  python3 edge_health_check.py --fix        # 尝试自动修复（重启失败服务）

检查项
------
  1. 节点注册状态         state_file.json 是否存在且包含 node_id
  2. API 连通性           GET /api/v1/health（5s 超时）
  3. Shokz 回调守护进程   GET http://localhost:9781/health
  4. 蓝牙适配器           hciconfig hci0
  5. 本地模型完整性       调用 edge_model_manager
  6. 离线队列积压         调用 edge_business_queue.stats()
  7. 磁盘空间             /var/lib/zhilian-edge
  8. CPU 温度             /sys/class/thermal/thermal_zone0/temp
  9. systemd 服务状态     zhilian-edge-node / zhilian-edge-shokz
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("zhilian-health")

_STATE_DIR = Path(os.getenv("EDGE_STATE_DIR", "/var/lib/zhilian-edge"))
_STATE_FILE = _STATE_DIR / "node_state.json"
_API_BASE_URL = os.getenv("EDGE_API_BASE_URL", "").rstrip("/")
_SHOKZ_PORT = int(os.getenv("EDGE_SHOKZ_CALLBACK_PORT", "9781"))

EMOJI_OK = "✅"
EMOJI_WARN = "⚠️ "
EMOJI_ERR = "❌"
EMOJI_INFO = "ℹ️ "


class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass
class CheckResult:
    name: str
    severity: Severity
    message: str
    detail: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class HealthReport:
    timestamp: float = field(default_factory=time.time)
    node_id: Optional[str] = None
    store_id: Optional[str] = None
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def overall(self) -> Severity:
        if any(c.severity == Severity.ERROR for c in self.checks):
            return Severity.ERROR
        if any(c.severity == Severity.WARN for c in self.checks):
            return Severity.WARN
        return Severity.OK

    def exit_code(self) -> int:
        return {Severity.OK: 0, Severity.WARN: 1, Severity.ERROR: 2}[self.overall]


# ------------------------------------------------------------------ #
#  Helper
# ------------------------------------------------------------------ #

def _timed(fn, *args, **kw):
    t0 = time.monotonic()
    result = fn(*args, **kw)
    ms = (time.monotonic() - t0) * 1000
    return result, ms


def _http_get(url: str, timeout: float = 5.0, headers: Optional[Dict] = None) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ------------------------------------------------------------------ #
#  单项检查函数
# ------------------------------------------------------------------ #

def check_registration() -> CheckResult:
    t0 = time.monotonic()
    if not _STATE_FILE.exists():
        return CheckResult(
            "节点注册", Severity.ERROR,
            "state 文件不存在，节点尚未注册",
            detail=str(_STATE_FILE),
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return CheckResult(
            "节点注册", Severity.ERROR,
            f"state 文件损坏: {exc}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    node_id = data.get("node_id", "")
    if not node_id:
        return CheckResult(
            "节点注册", Severity.ERROR,
            "state 文件中无 node_id，需重新注册",
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    has_secret = bool(data.get("device_secret"))
    sev = Severity.OK if has_secret else Severity.WARN
    msg = f"node_id={node_id[:16]}… device_secret={'已设置' if has_secret else '⚠️ 缺失'}"
    return CheckResult(
        "节点注册", sev, msg,
        duration_ms=(time.monotonic() - t0) * 1000,
    )


def check_api_connectivity() -> CheckResult:
    if not _API_BASE_URL:
        return CheckResult("API连通性", Severity.WARN, "EDGE_API_BASE_URL 未配置")
    url = f"{_API_BASE_URL}/api/v1/health"
    t0 = time.monotonic()
    try:
        data = _http_get(url, timeout=5.0)
        ms = (time.monotonic() - t0) * 1000
        status = data.get("status", "unknown")
        sev = Severity.OK if status in ("ok", "healthy") else Severity.WARN
        return CheckResult("API连通性", sev, f"status={status} latency={ms:.0f}ms", duration_ms=ms)
    except Exception as exc:
        ms = (time.monotonic() - t0) * 1000
        return CheckResult("API连通性", Severity.ERROR, f"请求失败: {exc}", duration_ms=ms)


def check_shokz_daemon() -> CheckResult:
    url = f"http://127.0.0.1:{_SHOKZ_PORT}/health"
    t0 = time.monotonic()
    try:
        data = _http_get(url, timeout=3.0)
        ms = (time.monotonic() - t0) * 1000
        devices = data.get("devices", 0)
        bt = data.get("bluetooth", {})
        bt_ok = bt.get("dbus_available", False)
        bt_connected = len([d for d in bt.get("devices", []) if d.get("connected")])
        sev = Severity.OK
        detail = f"已注册设备={devices} BT={bt.get('audio_backend','?')} 已连接={bt_connected}"
        if not bt_ok:
            sev = Severity.WARN
            detail += " | 蓝牙D-Bus不可用（模拟模式）"
        return CheckResult("Shokz守护进程", sev, f"运行中 latency={ms:.0f}ms", detail=detail, duration_ms=ms)
    except Exception as exc:
        ms = (time.monotonic() - t0) * 1000
        return CheckResult("Shokz守护进程", Severity.ERROR, f"守护进程未响应: {exc}", duration_ms=ms)


def check_bluetooth() -> CheckResult:
    t0 = time.monotonic()
    if not shutil.which("hciconfig"):
        return CheckResult(
            "蓝牙适配器", Severity.WARN,
            "hciconfig 未安装（apt install bluez）",
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    try:
        result = subprocess.run(
            ["hciconfig", "hci0"],
            capture_output=True, text=True, timeout=3
        )
        ms = (time.monotonic() - t0) * 1000
        if result.returncode != 0:
            return CheckResult("蓝牙适配器", Severity.ERROR, "hci0 不存在或未启用", detail=result.stderr, duration_ms=ms)
        up = "UP RUNNING" in result.stdout
        sev = Severity.OK if up else Severity.WARN
        return CheckResult("蓝牙适配器", sev, "UP RUNNING" if up else "适配器未启动", duration_ms=ms)
    except subprocess.TimeoutExpired:
        return CheckResult("蓝牙适配器", Severity.WARN, "hciconfig 超时", duration_ms=(time.monotonic() - t0) * 1000)


def check_models() -> CheckResult:
    t0 = time.monotonic()
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from edge_model_manager import EdgeModelManager  # type: ignore
        mgr = EdgeModelManager()
        summary = mgr.status_summary()
        ms = (time.monotonic() - t0) * 1000
        ok = summary["ok"]
        total = summary["total"]
        missing = summary["missing"]
        corrupted = summary["corrupted"]
        if corrupted > 0:
            sev = Severity.ERROR
            msg = f"{corrupted} 个模型损坏需重新下载"
        elif missing > 0:
            sev = Severity.WARN
            msg = f"{missing}/{total} 个模型未下载"
        else:
            sev = Severity.OK
            msg = f"全部 {total} 个模型已就绪"
        return CheckResult("本地AI模型", sev, msg, duration_ms=ms)
    except ImportError:
        return CheckResult("本地AI模型", Severity.WARN, "edge_model_manager 未找到", duration_ms=(time.monotonic() - t0) * 1000)
    except Exception as exc:
        return CheckResult("本地AI模型", Severity.WARN, f"检查失败: {exc}", duration_ms=(time.monotonic() - t0) * 1000)


def check_business_queue() -> CheckResult:
    t0 = time.monotonic()
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from edge_business_queue import BusinessEventQueue  # type: ignore
        q = BusinessEventQueue()
        stats = q.stats()
        ms = (time.monotonic() - t0) * 1000
        pending = stats["pending"]
        failed = stats["failed"]
        age = stats["oldest_pending_age_seconds"]
        if failed > 0 or (pending > 0 and age > 3600):
            sev = Severity.WARN
        else:
            sev = Severity.OK
        msg = f"pending={pending} failed={failed}" + (f" oldest={age}s" if age else "")
        return CheckResult("离线业务队列", sev, msg, duration_ms=ms)
    except Exception as exc:
        return CheckResult("离线业务队列", Severity.WARN, f"检查失败: {exc}", duration_ms=(time.monotonic() - t0) * 1000)


def check_disk() -> CheckResult:
    t0 = time.monotonic()
    try:
        stats = os.statvfs(str(_STATE_DIR))
        total = stats.f_blocks * stats.f_frsize / (1024 ** 3)
        avail = stats.f_bavail * stats.f_frsize / (1024 ** 3)
        used_pct = (1 - avail / total) * 100 if total > 0 else 0
        ms = (time.monotonic() - t0) * 1000
        if used_pct > 90:
            sev = Severity.ERROR
        elif used_pct > 80:
            sev = Severity.WARN
        else:
            sev = Severity.OK
        return CheckResult(
            "磁盘空间", sev,
            f"已用 {used_pct:.1f}% 剩余 {avail:.1f}GB",
            duration_ms=ms,
        )
    except Exception as exc:
        return CheckResult("磁盘空间", Severity.WARN, f"检查失败: {exc}", duration_ms=(time.monotonic() - t0) * 1000)


def check_temperature() -> CheckResult:
    t0 = time.monotonic()
    candidates = [
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/class/hwmon/hwmon0/temp1_input"),
    ]
    for path in candidates:
        if path.exists():
            try:
                raw = path.read_text().strip()
                temp = float(raw) / 1000.0
                ms = (time.monotonic() - t0) * 1000
                if temp > 80:
                    sev = Severity.ERROR
                elif temp > 70:
                    sev = Severity.WARN
                else:
                    sev = Severity.OK
                return CheckResult("CPU温度", sev, f"{temp:.1f}°C", duration_ms=ms)
            except Exception:
                continue
    return CheckResult("CPU温度", Severity.WARN, "无法读取温度传感器", duration_ms=(time.monotonic() - t0) * 1000)


def check_systemd_service(service_name: str) -> CheckResult:
    t0 = time.monotonic()
    if not shutil.which("systemctl"):
        return CheckResult(f"systemd/{service_name}", Severity.WARN, "systemctl 不可用（非 systemd 系统）")
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=3
        )
        ms = (time.monotonic() - t0) * 1000
        active = result.stdout.strip() == "active"
        sev = Severity.OK if active else Severity.ERROR
        return CheckResult(f"systemd/{service_name}", sev, result.stdout.strip(), duration_ms=ms)
    except Exception as exc:
        return CheckResult(f"systemd/{service_name}", Severity.WARN, str(exc), duration_ms=(time.monotonic() - t0) * 1000)


# ------------------------------------------------------------------ #
#  自动修复
# ------------------------------------------------------------------ #

def _try_fix(report: HealthReport) -> None:
    for check in report.checks:
        if check.severity != Severity.ERROR:
            continue
        if check.name.startswith("systemd/"):
            service = check.name.split("/", 1)[1]
            print(f"  → 尝试重启 {service} …")
            try:
                subprocess.run(["systemctl", "restart", service], timeout=10, check=True)
                print(f"    {EMOJI_OK} 重启成功")
            except Exception as exc:
                print(f"    {EMOJI_ERR} 重启失败: {exc}")


# ------------------------------------------------------------------ #
#  主检查流程
# ------------------------------------------------------------------ #

def run_checks(quick: bool = False) -> HealthReport:
    report = HealthReport()

    # 读取 node_id 用于报告
    if _STATE_FILE.exists():
        try:
            data = json.loads(_STATE_FILE.read_text())
            report.node_id = data.get("node_id")
            report.store_id = data.get("store_id")
        except Exception:
            pass

    # 快速检查
    report.checks.append(check_registration())
    report.checks.append(check_api_connectivity())

    if quick:
        return report

    # 完整检查
    report.checks.append(check_shokz_daemon())
    report.checks.append(check_bluetooth())
    report.checks.append(check_models())
    report.checks.append(check_business_queue())
    report.checks.append(check_disk())
    report.checks.append(check_temperature())
    report.checks.append(check_systemd_service("zhilian-edge-node.service"))
    report.checks.append(check_systemd_service("zhilian-edge-shokz.service"))

    return report


# ------------------------------------------------------------------ #
#  输出格式
# ------------------------------------------------------------------ #

def _print_report(report: HealthReport) -> None:
    overall_emoji = {Severity.OK: EMOJI_OK, Severity.WARN: EMOJI_WARN, Severity.ERROR: EMOJI_ERR}
    print()
    print("=" * 60)
    print(f"  屯象OS 边缘节点健康报告  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if report.node_id:
        print(f"  NodeID : {report.node_id[:20]}…")
    if report.store_id:
        print(f"  StoreID: {report.store_id}")
    print("=" * 60)
    for c in report.checks:
        emoji = overall_emoji[c.severity]
        dur = f"({c.duration_ms:.0f}ms)" if c.duration_ms > 0 else ""
        print(f"  {emoji} {c.name:<20} {c.message}  {dur}")
        if c.detail:
            print(f"     {EMOJI_INFO} {c.detail}")
    print("-" * 60)
    overall = report.overall
    print(f"  综合状态: {overall_emoji[overall]} {overall.upper()}")
    print("=" * 60)
    print()


# ------------------------------------------------------------------ #
#  CLI 入口
# ------------------------------------------------------------------ #

def main() -> int:
    logging.basicConfig(level="WARNING", format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="屯象OS 边缘节点健康检查")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--quick", action="store_true", help="仅快速检查（注册+网络）")
    parser.add_argument("--fix", action="store_true", help="尝试自动修复失败项")
    args = parser.parse_args()

    report = run_checks(quick=args.quick)

    if args.json:
        output = {
            "timestamp": report.timestamp,
            "node_id": report.node_id,
            "store_id": report.store_id,
            "overall": report.overall,
            "checks": [asdict(c) for c in report.checks],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
        if args.fix and report.overall != Severity.OK:
            print("  尝试自动修复…")
            _try_fix(report)
            print("  修复完成，重新检查：")
            report = run_checks(quick=args.quick)
            _print_report(report)

    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
