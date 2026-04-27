#!/usr/bin/env python3
"""屯象OS Forge 资源发现器（DevForge 应用中心 Day-1 引导）。

扫描整个仓库，输出 5 类资源（backend_service / frontend_app / edge_image /
adapter / data_asset）的清单 JSON，可选地推送到 tx-devforge。

使用：
    # 仅 dry-run（输出到 stdout）
    python scripts/forge_register_resources.py --dry-run

    # 写文件
    python scripts/forge_register_resources.py --output resources.json

    # 推送到后端
    python scripts/forge_register_resources.py --push --tenant-id <UUID>

    # 仅处理某一类
    python scripts/forge_register_resources.py --dry-run --type backend_service
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_RESOURCE_TYPES = {
    "backend_service",
    "frontend_app",
    "edge_image",
    "adapter",
    "data_asset",
}

EXCLUDED_DIR_NAMES = {
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".next",
}

# adapter/ 下不算具体适配器的辅助目录
ADAPTER_NON_VENDOR_DIRS = {"base", "config", "tests", "__pycache__"}

# 已知微服务的中文显示名（与 CLAUDE.md 第五节一致）
SERVICE_DISPLAY_NAMES = {
    "gateway": "API Gateway",
    "tx-trade": "交易履约",
    "tx-menu": "菜品菜单",
    "tx-member": "会员 CDP",
    "tx-growth": "增长营销",
    "tx-ops": "运营流程",
    "tx-supply": "供应链",
    "tx-finance": "财务结算",
    "tx-agent": "Agent OS",
    "tx-analytics": "经营分析",
    "tx-brain": "AI 智能决策中枢",
    "tx-intel": "商业智能",
    "tx-org": "组织人事",
    "tx-civic": "城市监管平台",
    "tx-pay": "聚合支付",
    "tx-expense": "费用报销",
    "tx-predict": "预测引擎",
    "tx-forge": "Forge 开发者市场",
    "tx-devforge": "DevForge 研运平台",
    "mcp-server": "MCP Protocol Server",
    "tunxiang-api": "遗留 API 兼容层",
}

EDGE_DISPLAY_NAMES = {
    "mac-station": "Mac mini 门店本地 API",
    "coreml-bridge": "Core ML 桥接（Swift HTTP）",
    "sync-engine": "本地↔云端 增量同步",
    "mac-mini": "Mac mini 工具集",
}

ADAPTER_DISPLAY_NAMES = {
    "pinzhi": "品智 POS 适配器",
    "aoqiwei": "奥琦玮适配器",
    "keruyun": "客如云适配器",
    "yiding": "易订货适配器",
    "weishenghuo": "微生活适配器",
    "meituan-saas": "美团 SaaS 适配器",
    "douyin": "抖音生活服务适配器",
    "eleme": "饿了么适配器",
    "xiaohongshu": "小红书适配器",
    "tiancai-shanglong": "天财商龙适配器",
    "nuonuo": "诺诺发票适配器",
    "erp": "ERP 适配器",
    "logistics": "物流适配器",
}


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class Resource:
    """单个资源记录（与 ApplicationCreate 字段一一对应）。"""

    code: str
    name: str
    resource_type: str
    repo_path: str
    owner: str | None = None
    tech_stack: str | None = None
    description: str | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

logger = logging.getLogger("forge.register")


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def read_text_safe(path: Path) -> str | None:
    """读取文本文件，文件不存在时返回 None。"""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        logger.debug("无法解码 %s（非 UTF-8）", path)
        return None
    except OSError as exc:
        logger.debug("读取 %s 失败：%s", path, exc)
        return None


def read_json_safe(path: Path) -> dict[str, Any] | None:
    text = read_text_safe(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.debug("解析 %s JSON 失败：%s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def git_last_committer(path: Path) -> str | None:
    """git log -1 --format=%ae -- <path>。失败返回 None。"""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ae", "--", str(path)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("未找到 git 可执行文件")
        return None
    except subprocess.TimeoutExpired:
        logger.debug("git log 超时：%s", path)
        return None
    except subprocess.SubprocessError as exc:
        logger.debug("git log 失败 %s: %s", path, exc)
        return None

    if result.returncode != 0:
        return None
    email = result.stdout.strip()
    return email or None


# ---------------------------------------------------------------------------
# CODEOWNERS 解析
# ---------------------------------------------------------------------------


def load_codeowners() -> list[tuple[str, str]]:
    """读取 CODEOWNERS，返回 (pattern, owner) 列表（按文件顺序）。"""
    candidates = [
        REPO_ROOT / ".github" / "CODEOWNERS",
        REPO_ROOT / "CODEOWNERS",
        REPO_ROOT / "docs" / "CODEOWNERS",
    ]
    rules: list[tuple[str, str]] = []
    for path in candidates:
        text = read_text_safe(path)
        if text is None:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pattern, *owners = parts
            owner = ", ".join(o for o in owners if o)
            rules.append((pattern, owner))
        if rules:
            logger.debug("从 %s 载入 %d 条 CODEOWNERS 规则", path, len(rules))
            break
    return rules


def codeowners_match(rules: list[tuple[str, str]], rel_path: str) -> str | None:
    """简易 CODEOWNERS 匹配：最后一条匹配生效（GitHub 规则）。"""
    if not rules:
        return None
    matched: str | None = None
    candidate = rel_path.lstrip("/")
    for pattern, owner in rules:
        pat = pattern.lstrip("/")
        # 极简匹配：完全相等、前缀匹配（pattern 以 / 结尾或不含通配符）、glob 转正则
        if pat.endswith("/"):
            if candidate.startswith(pat):
                matched = owner
        elif "*" in pat or "?" in pat:
            regex = "^" + re.escape(pat).replace(r"\*", ".*").replace(r"\?", ".") + "$"
            if re.match(regex, candidate) or re.match(regex, candidate + "/"):
                matched = owner
        else:
            if candidate == pat or candidate.startswith(pat + "/"):
                matched = owner
    return matched


# ---------------------------------------------------------------------------
# Owner 解析（CODEOWNERS 优先，git 兜底）
# ---------------------------------------------------------------------------


class OwnerResolver:
    def __init__(self) -> None:
        self.rules = load_codeowners()
        self.codeowners_hits = 0
        self.git_hits = 0
        self.misses = 0

    def resolve(self, abs_path: Path) -> str | None:
        rel = abs_path.relative_to(REPO_ROOT).as_posix()
        owner = codeowners_match(self.rules, rel)
        if owner:
            self.codeowners_hits += 1
            return owner
        owner = git_last_committer(abs_path)
        if owner:
            self.git_hits += 1
            return owner
        self.misses += 1
        return None

    def total(self) -> int:
        return self.codeowners_hits + self.git_hits + self.misses

    def success_rate(self) -> float:
        total = self.total()
        if total == 0:
            return 0.0
        return (self.codeowners_hits + self.git_hits) / total


# ---------------------------------------------------------------------------
# 扫描器
# ---------------------------------------------------------------------------


def is_excluded(path: Path) -> bool:
    return path.name in EXCLUDED_DIR_NAMES


def detect_service_port(dockerfile_text: str | None) -> int | None:
    if not dockerfile_text:
        return None
    match = re.search(r"--port[\"',\s]+([0-9]{4,5})", dockerfile_text)
    if match:
        return int(match.group(1))
    expose = re.search(r"^EXPOSE\s+([0-9]{4,5})", dockerfile_text, re.MULTILINE)
    if expose:
        return int(expose.group(1))
    return None


def has_alembic(service_dir: Path) -> bool:
    return (service_dir / "alembic.ini").exists() or (service_dir / "migrations").is_dir()


def scan_backend_services(owner_resolver: OwnerResolver) -> list[Resource]:
    services_dir = REPO_ROOT / "services"
    resources: list[Resource] = []
    if not services_dir.is_dir():
        logger.warning("services/ 不存在")
        return resources

    for entry in sorted(services_dir.iterdir()):
        if not entry.is_dir() or is_excluded(entry):
            continue
        code = entry.name
        dockerfile_text = read_text_safe(entry / "Dockerfile")
        port = detect_service_port(dockerfile_text)
        display_name = SERVICE_DISPLAY_NAMES.get(code)
        if display_name:
            name = f"{code} · {display_name}"
        else:
            name = code

        # 描述：尝试从 README 第一段截取
        readme = read_text_safe(entry / "README.md") or ""
        description: str | None = None
        if readme:
            for line in readme.splitlines():
                line = line.strip().lstrip("#").strip()
                if line and not line.startswith("!["):
                    description = line[:240]
                    break

        metadata: dict[str, Any] = {
            "has_dockerfile": dockerfile_text is not None,
            "alembic": has_alembic(entry),
        }
        if port is not None:
            metadata["port"] = port
        # 计算 src 下 .py 文件数（粗略代码量）
        src_dir = entry / "src"
        if src_dir.is_dir():
            metadata["py_files"] = sum(
                1
                for p in src_dir.rglob("*.py")
                if not any(part in EXCLUDED_DIR_NAMES for part in p.parts)
            )

        resources.append(
            Resource(
                code=code,
                name=name,
                resource_type="backend_service",
                repo_path=f"services/{code}",
                owner=owner_resolver.resolve(entry),
                tech_stack="python",
                description=description,
                metadata_json=metadata,
            )
        )
    return resources


def detect_frontend_tech(app_dir: Path, package_data: dict[str, Any] | None) -> str:
    """根据目录类型 + package.json + 配置文件推断 tech_stack。"""
    name = app_dir.name
    if name.startswith("android-"):
        return "kotlin"
    if name.startswith("ios-"):
        return "swift"
    if name.startswith("windows-"):
        return "electron"
    if name.startswith("miniapp-"):
        return "wechat-miniapp"

    if (app_dir / "vite.config.ts").exists() or (app_dir / "vite.config.js").exists():
        return "vite"
    if (app_dir / "next.config.ts").exists() or (app_dir / "next.config.js").exists():
        return "next"

    if package_data:
        deps: dict[str, Any] = {}
        deps.update(package_data.get("dependencies") or {})
        deps.update(package_data.get("devDependencies") or {})
        if "vite" in deps:
            return "vite"
        if "next" in deps:
            return "next"
        if "react" in deps:
            return "react"

    return "unknown"


def scan_frontend_apps(owner_resolver: OwnerResolver) -> list[Resource]:
    apps_dir = REPO_ROOT / "apps"
    resources: list[Resource] = []
    if not apps_dir.is_dir():
        logger.warning("apps/ 不存在")
        return resources

    web_prefixes = ("web-", "miniapp-", "h5-", "android-", "ios-", "windows-")
    for entry in sorted(apps_dir.iterdir()):
        if not entry.is_dir() or is_excluded(entry):
            continue
        if not entry.name.startswith(web_prefixes):
            logger.debug("跳过非已知前缀的 app：%s", entry.name)
            continue

        code = entry.name
        package_data = read_json_safe(entry / "package.json")
        pkg_name = (package_data or {}).get("name") if package_data else None
        name = pkg_name if isinstance(pkg_name, str) and pkg_name else code

        tech = detect_frontend_tech(entry, package_data)

        description: str | None = None
        if package_data:
            desc = package_data.get("description")
            if isinstance(desc, str) and desc:
                description = desc[:240]
        if description is None:
            readme = read_text_safe(entry / "README.md") or ""
            for line in readme.splitlines():
                line = line.strip().lstrip("#").strip()
                if line and not line.startswith("!["):
                    description = line[:240]
                    break

        metadata: dict[str, Any] = {
            "has_package_json": package_data is not None,
            "has_dockerfile": (entry / "Dockerfile").exists(),
        }
        if package_data and isinstance(package_data.get("version"), str):
            metadata["version"] = package_data["version"]
        if (entry / "build.gradle.kts").exists():
            metadata["gradle"] = True
        if (entry / "Package.swift").exists():
            metadata["swift_package"] = True
        if (entry / "app.json").exists() and code.startswith("miniapp-"):
            metadata["miniapp_appjson"] = True

        resources.append(
            Resource(
                code=code,
                name=name,
                resource_type="frontend_app",
                repo_path=f"apps/{code}",
                owner=owner_resolver.resolve(entry),
                tech_stack=tech,
                description=description,
                metadata_json=metadata,
            )
        )
    return resources


def scan_edge_images(owner_resolver: OwnerResolver) -> list[Resource]:
    edge_dir = REPO_ROOT / "edge"
    resources: list[Resource] = []
    if not edge_dir.is_dir():
        logger.warning("edge/ 不存在")
        return resources

    for entry in sorted(edge_dir.iterdir()):
        if not entry.is_dir() or is_excluded(entry):
            continue
        code = f"edge-{entry.name}"
        display = EDGE_DISPLAY_NAMES.get(entry.name, entry.name)
        name = f"{entry.name} · {display}"

        tech: str
        if (entry / "Package.swift").exists():
            tech = "swift"
        elif (entry / "requirements.txt").exists() or (entry / "pyproject.toml").exists():
            tech = "python"
        else:
            tech = "unknown"

        description: str | None = None
        readme = read_text_safe(entry / "README.md") or ""
        for line in readme.splitlines():
            line = line.strip().lstrip("#").strip()
            if line and not line.startswith("!["):
                description = line[:240]
                break

        metadata: dict[str, Any] = {
            "has_dockerfile": (entry / "Dockerfile").exists(),
            "has_requirements": (entry / "requirements.txt").exists(),
            "has_swift_package": (entry / "Package.swift").exists(),
        }

        resources.append(
            Resource(
                code=code,
                name=name,
                resource_type="edge_image",
                repo_path=f"edge/{entry.name}",
                owner=owner_resolver.resolve(entry),
                tech_stack=tech,
                description=description,
                metadata_json=metadata,
            )
        )
    return resources


def scan_adapters(owner_resolver: OwnerResolver) -> list[Resource]:
    adapter_dir = REPO_ROOT / "shared" / "adapters"
    resources: list[Resource] = []
    if not adapter_dir.is_dir():
        logger.warning("shared/adapters/ 不存在")
        return resources

    for entry in sorted(adapter_dir.iterdir()):
        if not entry.is_dir() or is_excluded(entry):
            continue
        if entry.name in ADAPTER_NON_VENDOR_DIRS:
            continue
        code = f"adapter-{entry.name}"
        display = ADAPTER_DISPLAY_NAMES.get(entry.name, f"{entry.name} 适配器")
        name = f"{entry.name} · {display}"

        # 计算适配器规模
        py_files = [
            p
            for p in entry.rglob("*.py")
            if not any(part in EXCLUDED_DIR_NAMES for part in p.parts)
        ]
        metadata: dict[str, Any] = {
            "py_files": len(py_files),
            "has_tests": (entry / "tests").is_dir(),
        }

        description: str | None = None
        readme = read_text_safe(entry / "README.md") or ""
        for line in readme.splitlines():
            line = line.strip().lstrip("#").strip()
            if line and not line.startswith("!["):
                description = line[:240]
                break

        resources.append(
            Resource(
                code=code,
                name=name,
                resource_type="adapter",
                repo_path=f"shared/adapters/{entry.name}",
                owner=owner_resolver.resolve(entry),
                tech_stack="python",
                description=description,
                metadata_json=metadata,
            )
        )
    return resources


_VERSION_RE = re.compile(r"^v(\d+)_")


def scan_data_assets(owner_resolver: OwnerResolver) -> list[Resource]:
    versions_dir = REPO_ROOT / "shared" / "db-migrations" / "versions"
    resources: list[Resource] = []
    if not versions_dir.is_dir():
        logger.warning("shared/db-migrations/versions/ 不存在")
        return resources

    all_files = [
        p
        for p in versions_dir.iterdir()
        if p.is_file() and p.suffix == ".py" and not p.name.startswith("_")
    ]
    versioned: list[tuple[int, str]] = []
    for path in all_files:
        match = _VERSION_RE.match(path.name)
        if match:
            versioned.append((int(match.group(1)), path.stem))

    latest_name: str | None = None
    if versioned:
        versioned.sort()
        latest_name = versioned[-1][1]

    metadata: dict[str, Any] = {
        "migration_count": len(all_files),
        "v_prefixed_count": len(versioned),
    }
    if latest_name is not None:
        metadata["latest_version"] = latest_name

    resources.append(
        Resource(
            code="db-migrations",
            name="屯象主库迁移",
            resource_type="data_asset",
            repo_path="shared/db-migrations",
            owner=owner_resolver.resolve(versions_dir),
            tech_stack="alembic",
            description="屯象 OS 主库 Alembic 迁移合集（含 RLS / 物化视图 / 事件总线）",
            metadata_json=metadata,
        )
    )
    return resources


# ---------------------------------------------------------------------------
# 推送（Day-2 用）
# ---------------------------------------------------------------------------


def http_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
    timeout: float,
) -> tuple[int, dict[str, Any] | str]:
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 — 受控的本地/内网地址
        url=url, data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        status = exc.code
    except urllib.error.URLError as exc:
        return 0, f"URLError: {exc}"
    except TimeoutError as exc:
        return 0, f"Timeout: {exc}"
    except OSError as exc:
        return 0, f"OSError: {exc}"

    parsed: dict[str, Any] | str
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = raw
    return status, parsed


def _lookup_application_id(
    base_url: str,
    headers: dict[str, str],
    code: str,
    timeout: float,
) -> tuple[str | None, Any]:
    """409 后用 code 反查现存 application_id（PATCH 需要 UUID 而非 code）。"""

    lookup_url = f"{base_url}?code={urllib.parse.quote(code)}&size=1"
    status, payload = http_request("GET", lookup_url, headers, None, timeout)
    if status != 200 or not isinstance(payload, dict):
        return None, payload
    data = payload.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        return None, payload
    first = items[0] if isinstance(items, list) else None
    if not isinstance(first, dict):
        return None, payload
    app_id = first.get("id")
    return (str(app_id) if app_id else None), payload


def push_resources(
    resources: list[Resource],
    api_base: str,
    tenant_id: str,
    timeout: float,
) -> dict[str, Any]:
    create_url = f"{api_base.rstrip('/')}/api/v1/devforge/applications"
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-ID": tenant_id,
    }

    created = 0
    updated = 0
    failed: list[dict[str, Any]] = []

    for res in resources:
        body = asdict(res)
        status, payload = http_request("POST", create_url, headers, body, timeout)
        if status in (200, 201):
            created += 1
            continue
        if status == 409:
            app_id, lookup_payload = _lookup_application_id(
                create_url, headers, res.code, timeout
            )
            if app_id is None:
                failed.append(
                    {
                        "code": res.code,
                        "status": status,
                        "body": payload,
                        "lookup_failed": True,
                        "lookup_payload": lookup_payload,
                    }
                )
                continue
            patch_url = f"{create_url}/{app_id}"
            update_body = {
                "name": res.name,
                "resource_type": res.resource_type,
                "owner": res.owner,
                "repo_path": res.repo_path,
                "tech_stack": res.tech_stack,
                "description": res.description,
                "metadata_json": res.metadata_json,
            }
            patch_status, patch_payload = http_request(
                "PATCH", patch_url, headers, update_body, timeout
            )
            if patch_status in (200, 204):
                updated += 1
            else:
                failed.append(
                    {
                        "code": res.code,
                        "application_id": app_id,
                        "status": patch_status,
                        "body": patch_payload,
                    }
                )
            continue
        failed.append({"code": res.code, "status": status, "body": payload})

    return {"created": created, "updated": updated, "failed": failed}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def collect_resources(
    type_filter: str | None,
    owner_resolver: OwnerResolver,
) -> list[Resource]:
    scanners: dict[str, Any] = {
        "backend_service": scan_backend_services,
        "frontend_app": scan_frontend_apps,
        "edge_image": scan_edge_images,
        "adapter": scan_adapters,
        "data_asset": scan_data_assets,
    }

    types = [type_filter] if type_filter else list(scanners.keys())
    out: list[Resource] = []
    for t in types:
        scan = scanners[t]
        items = scan(owner_resolver)
        logger.info("扫描 %s：%d 条", t, len(items))
        out.extend(items)
    return out


def build_payload(resources: list[Resource]) -> dict[str, Any]:
    summary: dict[str, int] = {t: 0 for t in VALID_RESOURCE_TYPES}
    for res in resources:
        summary[res.resource_type] = summary.get(res.resource_type, 0) + 1
    summary["total"] = len(resources)

    return {
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_root": str(REPO_ROOT),
        "resources": [asdict(r) for r in resources],
        "summary": summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="屯象 OS Forge 资源发现器（DevForge 应用中心 Day-1）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="仅输出 JSON 到 stdout，不写文件、不推送",
    )
    mode.add_argument(
        "--push",
        action="store_true",
        help="将资源推送到 tx-devforge",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出 JSON 到文件（与 --dry-run 互斥语义不冲突）",
    )
    parser.add_argument(
        "--api-base",
        default="http://localhost:8017",
        help="tx-devforge 基址（默认 http://localhost:8017，8015/8016 被 tx-expense/tx-pay 占用）",
    )
    parser.add_argument("--tenant-id", help="X-Tenant-ID（推送时必填）")
    parser.add_argument(
        "--type",
        dest="type_filter",
        choices=sorted(VALID_RESOURCE_TYPES),
        default=None,
        help="只处理某一类资源",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="单次 HTTP 推送超时秒数（默认 10）",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)

    if args.push and not args.tenant_id:
        logger.error("--push 需要 --tenant-id")
        return 2

    owner_resolver = OwnerResolver()
    resources = collect_resources(args.type_filter, owner_resolver)

    payload = build_payload(resources)

    rendered = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.output is not None:
        try:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            logger.error("写出 %s 失败：%s", args.output, exc)
            return 3
        logger.info("已写入 %s（%d 条资源）", args.output, len(resources))
    elif args.dry_run or not args.push:
        # 默认行为也输出到 stdout
        sys.stdout.write(rendered + "\n")

    rate = owner_resolver.success_rate() * 100
    logger.info(
        "Owner 推断：CODEOWNERS=%d, git=%d, 缺失=%d，命中率 %.1f%%",
        owner_resolver.codeowners_hits,
        owner_resolver.git_hits,
        owner_resolver.misses,
        rate,
    )
    logger.info("摘要：%s", payload["summary"])

    if args.push:
        logger.info(
            "开始推送 %d 条资源到 %s（tenant=%s）",
            len(resources),
            args.api_base,
            args.tenant_id,
        )
        result = push_resources(
            resources, args.api_base, args.tenant_id, args.timeout
        )
        logger.info(
            "推送结果：created=%d, updated=%d, failed=%d",
            result["created"],
            result["updated"],
            len(result["failed"]),
        )
        if result["failed"]:
            for item in result["failed"]:
                logger.warning("失败 %s：status=%s, body=%s",
                               item["code"], item["status"], item["body"])
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
