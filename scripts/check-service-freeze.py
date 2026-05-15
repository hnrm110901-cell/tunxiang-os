"""
check-service-freeze.py — 服务冻结令执行器 (屯象OS 治理四件套 §6 之一)

用法:
    python scripts/check-service-freeze.py                    # 检查 git status 待提交文件
    python scripts/check-service-freeze.py --staged           # 仅检查 staged (供 pre-commit hook)
    python scripts/check-service-freeze.py --diff main        # 检查 PR diff vs main

退出码:
    0  无违规
    1  发现违规 (新建 services/tx-*/ 文件)
    2  policy 文件缺失或格式错

集成:
    Git pre-commit (可选, 用户手动 install):
        ln -s $PWD/scripts/check-service-freeze.py .git/hooks/pre-commit

    CI (建议加进 .github/workflows/):
        python scripts/check-service-freeze.py --diff origin/main

战略源: 屯象OS 架构与代码升级优化战略开发计划 2026-05-12 §1 + §6
Policy SoT: .omc/policy/service-freeze.yml
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML 未安装. pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)


def _load_policy(policy_path: Path) -> dict:
    if not policy_path.exists():
        print(
            f"ERROR: policy 文件不存在: {policy_path}\n"
            f"  期望路径: .omc/policy/service-freeze.yml",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        return yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"ERROR: policy YAML 格式错: {e}", file=sys.stderr)
        sys.exit(2)


def _git_changed_files(mode: str, base_ref: str | None) -> list[str]:
    """获取待检查文件列表.

    mode 'staged': git diff --cached --name-only --diff-filter=AR (新增 + 重命名)
    mode 'all':    git status --porcelain (含 untracked / A / R 状态)
    mode 'diff':   git diff --name-only --diff-filter=AR {base_ref}...HEAD
                   三点 (merge-base..HEAD) 防 base_ref 已超过 PR base 时反向 diff 漏
    """
    if mode == "staged":
        cmd = [
            "git", "diff", "--cached",
            "--name-only", "--diff-filter=AR",
        ]
    elif mode == "diff":
        if not base_ref:
            print("ERROR: --diff 需要 base_ref 参数", file=sys.stderr)
            sys.exit(2)
        # 三点 a...b = git_merge_base(a,b)..b, 防 a 已超过 PR base 时漏抓 PR 内 commit 的新文件
        cmd = [
            "git", "diff", f"{base_ref}...HEAD",
            "--name-only", "--diff-filter=AR",
        ]
    else:  # all
        cmd = ["git", "status", "--porcelain"]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"ERROR: git 调用失败: {e}", file=sys.stderr)
        sys.exit(2)

    if mode == "all":
        # parse `git status --porcelain`:
        # status 码白名单: ?? (untracked) / A (added) / R (renamed)
        # 含 modified 形式 'AM' (staged add + unstaged modify) / 'RM' / 'AD'
        files: list[str] = []
        capture_codes = {"A", "R"}  # M (modify) 不算"新文件", policy 只拦新增
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            status = line[:2]
            path_field = line[3:].strip().strip('"')
            # rename 格式: 'R  old_path -> new_path', 取 new_path
            if " -> " in path_field:
                path_field = path_field.split(" -> ", 1)[1].strip().strip('"')
            # 'XY' 任一字符在白名单, 或整段 == '??'
            if status == "??" or set(status) & capture_codes:
                files.append(path_field)
        return files

    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]


def _check_violations(
    files: list[str],
    forbidden_patterns: list[str],
    allowed_services: list[str],
) -> list[tuple[str, str]]:
    """返回 [(file_path, violated_pattern)] 列表."""
    violations: list[tuple[str, str]] = []
    for f in files:
        for pat in forbidden_patterns:
            if fnmatch.fnmatch(f, pat):
                # 提取服务名 (services/tx-X/...)
                parts = f.split("/")
                if len(parts) >= 2 and parts[0] == "services":
                    svc_name = parts[1]
                    if svc_name in allowed_services:
                        # 已存在服务的同名文件不算违规 (例如改 main.py)
                        continue
                violations.append((f, pat))
                break
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="屯象OS 服务冻结令执行器 (战略 §6 治理四件套之一)",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--staged", action="store_true",
        help="仅检查 staged 文件 (供 pre-commit hook)",
    )
    mode_group.add_argument(
        "--diff", metavar="BASE_REF",
        help="检查 BASE_REF..HEAD diff 新增文件 (供 CI)",
    )
    parser.add_argument(
        "--repo-root", metavar="PATH",
        help="仓库根目录 (默认: 脚本父目录的父目录)",
    )
    args = parser.parse_args(argv)

    # Resolve repo root
    script_dir = Path(__file__).resolve().parent
    repo_root = (
        Path(args.repo_root).resolve() if args.repo_root else script_dir.parent
    )

    policy_path = repo_root / ".omc" / "policy" / "service-freeze.yml"
    policy = _load_policy(policy_path)

    if not policy.get("policy", {}).get("forbid_new_service_dir", False):
        # policy 已禁用, exit 0
        return 0

    forbidden = policy["policy"].get("forbidden_patterns", [])
    allowed = policy["policy"].get("allowed_services", [])

    # mode 选择
    if args.staged:
        mode = "staged"
        base_ref = None
    elif args.diff:
        mode = "diff"
        base_ref = args.diff
    else:
        mode = "all"
        base_ref = None

    # 切到 repo_root 跑 git
    import os
    cwd_orig = os.getcwd()
    try:
        os.chdir(repo_root)
        files = _git_changed_files(mode, base_ref)
    finally:
        os.chdir(cwd_orig)

    violations = _check_violations(files, forbidden, allowed)

    if not violations:
        print(
            f"[service-freeze] ✅ 无违规 ({len(files)} 文件检查 / mode={mode})",
            file=sys.stderr,
        )
        return 0

    # 报错并列出违规
    print(
        f"\n[service-freeze] ❌ 发现 {len(violations)} 个违规 — "
        f"屯象OS 服务冻结令禁止新建 services/tx-* 服务\n",
        file=sys.stderr,
    )
    for f, pat in violations:
        print(f"  {f} (匹配 {pat})", file=sys.stderr)
    print(
        f"\n  战略源: 屯象OS 架构与代码升级优化战略开发计划 2026-05-12 §1\n"
        f"  Policy: .omc/policy/service-freeze.yml\n"
        f"  例外申请: 架构守门会 (每两周一次), 需创始人 + Tech Lead 双批\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
