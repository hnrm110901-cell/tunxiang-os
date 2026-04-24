"""屯象OS Skill CLI 工具 — tunxiang skill <command>"""

from __future__ import annotations

import argparse
import sys

from .ontology import OntologyRegistry
from .registry import SkillRegistry


def validate_cmd(args: argparse.Namespace) -> None:
    """tunxiang skill validate — 验证 Ontology 一致性"""
    registry = SkillRegistry([args.dir])
    registry.scan()
    onto = OntologyRegistry(registry)
    issues = onto.validate()

    if issues:
        print("⚠️  Ontology验证发现问题：")
        for issue in issues:
            print(f"  {issue}")
        sys.exit(1)
    else:
        print(f"✅ Ontology验证通过，共 {len(registry.list_skills())} 个Skill")


def list_cmd(args: argparse.Namespace) -> None:
    """tunxiang skill list — 列出所有已注册 Skill"""
    registry = SkillRegistry([args.dir])
    registry.scan()
    skills = registry.list_skills()

    if not skills:
        print("（未找到任何 Skill）")
        return

    for skill in skills:
        print(f"  [{skill.meta.category}] {skill.meta.name} v{skill.meta.version} — {skill.meta.display_name}")


def report_cmd(args: argparse.Namespace) -> None:
    """tunxiang skill report — 生成 Ontology 报告"""
    registry = SkillRegistry([args.dir])
    registry.scan()
    onto = OntologyRegistry(registry)
    report = onto.generate_report()
    print(report)


def route_cmd(args: argparse.Namespace) -> None:
    """tunxiang skill route <event_type> — 查询哪些 Skill 会处理该事件"""
    from .router import SkillRouter

    registry = SkillRegistry([args.dir])
    registry.scan()
    router = SkillRouter(registry)
    matches = router.route(event_type=args.event_type, payload={})

    if not matches:
        print(f"（没有 Skill 声明处理事件: {args.event_type}）")
        return

    print(f"事件 '{args.event_type}' 将被以下 Skill 处理（按 priority 降序）：")
    for match in matches:
        print(
            f"  [{match.priority:3d}] {match.skill.meta.name}"
            f" — condition: {match.trigger.condition}"
            f"  ({match.trigger.description})"
        )


def main() -> None:
    """CLI 入口"""
    parser = argparse.ArgumentParser(
        description="屯象OS Skill 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dir",
        default=".",
        metavar="DIR",
        help="Skill 根目录（默认当前目录，递归扫描所有 SKILL.yaml）",
    )

    subparsers = parser.add_subparsers(title="子命令", dest="command")

    # validate
    val_parser = subparsers.add_parser("validate", help="验证 Ontology 一致性")
    val_parser.set_defaults(func=validate_cmd)

    # list
    list_parser = subparsers.add_parser("list", help="列出所有已注册 Skill")
    list_parser.set_defaults(func=list_cmd)

    # report
    report_parser = subparsers.add_parser("report", help="生成 Ontology 报告")
    report_parser.set_defaults(func=report_cmd)

    # route
    route_parser = subparsers.add_parser("route", help="查询事件路由")
    route_parser.add_argument("event_type", help="事件类型，如 order.paid")
    route_parser.set_defaults(func=route_cmd)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
