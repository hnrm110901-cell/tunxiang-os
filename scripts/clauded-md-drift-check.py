#!/usr/bin/env python3
"""
CLAUDE.md drift-check script.

Detects when CLAUDE.md is > 10% out of sync with on-disk reality:
  - Services: real services/ subdirs vs. declared in CLAUDE.md
  - Migrations: latest v<NNN> on disk vs. highest vNNN mentioned in CLAUDE.md

Exit codes:
  0 — drift within threshold (ok)
  1 — drift exceeded threshold (alert)

Output: JSON report to stdout + drift-YYYY-MM-DD.md written to docs/service-health/
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).parent.parent
    claude_md_path = repo_root / "CLAUDE.md"
    services_dir = repo_root / "services"
    migrations_dir = repo_root / "shared" / "db-migrations" / "versions"

    if not claude_md_path.exists():
        print(json.dumps({"error": "CLAUDE.md not found"}, ensure_ascii=False))
        sys.exit(1)

    claude_md = claude_md_path.read_text(encoding="utf-8")

    # --- Services drift ---
    real_services: list[str] = sorted(
        p.name
        for p in services_dir.iterdir()
        if p.is_dir() and (p.name.startswith("tx-") or p.name in ("gateway", "mcp-server"))
    )

    declared_services: set[str] = set(
        re.findall(r"(?:services/)?(tx-[\w-]+|gateway|mcp-server)(?:/|:|\s)", claude_md)
    )
    # Also capture bare service names mentioned in tables
    declared_services.update(
        m for m in re.findall(r"\b(tx-[\w-]+|gateway|mcp-server)\b", claude_md)
        if m in set(real_services)
    )

    missing_from_claude = sorted(set(real_services) - declared_services)
    extra_in_claude = sorted(
        declared_services - set(real_services)
        - {"tx-ontology", "tunxiang-api"}  # known decom / planned services
    )
    svc_drift_pct = (len(missing_from_claude) + len(extra_in_claude)) / max(len(real_services), 1) * 100

    # --- Migration drift ---
    real_max_ver = 0
    if migrations_dir.exists():
        for f in migrations_dir.glob("v*.py"):
            m = re.match(r"^v(\d+)", f.name)
            if m:
                real_max_ver = max(real_max_ver, int(m.group(1)))

    declared_ver_nums = [int(v) for v in re.findall(r"\bv(\d{3,4})\b", claude_md)]
    declared_max_ver = max(declared_ver_nums, default=0)

    mig_drift_pct = (
        abs(real_max_ver - declared_max_ver) / max(real_max_ver, 1) * 100
        if real_max_ver > 0
        else 0.0
    )

    # --- Build report ---
    threshold = 10.0
    triggered = svc_drift_pct > threshold or mig_drift_pct > threshold

    report: dict = {
        "checked_at": datetime.now().isoformat(),
        "threshold_pct": threshold,
        "status": "DRIFT_EXCEEDED" if triggered else "ok",
        "services_real_count": len(real_services),
        "services_drift_pct": round(svc_drift_pct, 2),
        "services_missing_from_claude": missing_from_claude[:10],
        "services_extra_in_claude": extra_in_claude[:10],
        "migration_real_max": real_max_ver,
        "migration_claude_md_max": declared_max_ver,
        "migration_drift_pct": round(mig_drift_pct, 2),
    }

    # --- Write markdown report to docs/service-health/ ---
    out_dir = repo_root / "docs" / "service-health"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"drift-{datetime.now().strftime('%Y-%m-%d')}.md"

    status_badge = "DRIFT EXCEEDED" if triggered else "ok"
    md_lines = [
        f"# CLAUDE.md Drift Check — {datetime.now().date()}",
        "",
        f"**Threshold**: {threshold}%",
        f"**Status**: {status_badge}",
        "",
        "```json",
        json.dumps(report, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    if triggered:
        md_lines += [
            "## Action Required",
            "",
        ]
        if svc_drift_pct > threshold:
            md_lines += [
                f"- Services drift {svc_drift_pct:.1f}% > {threshold}%",
                f"  - Missing from CLAUDE.md: {', '.join(missing_from_claude) or 'none'}",
                f"  - Extra in CLAUDE.md: {', '.join(extra_in_claude) or 'none'}",
                "",
            ]
        if mig_drift_pct > threshold:
            md_lines += [
                f"- Migration drift {mig_drift_pct:.1f}% > {threshold}%",
                f"  - Real max: v{real_max_ver}, CLAUDE.md max: v{declared_max_ver}",
                "",
            ]

    out_path.write_text("\n".join(md_lines), encoding="utf-8")

    # --- Stdout JSON ---
    print(json.dumps(report, indent=2, ensure_ascii=False))

    sys.exit(1 if triggered else 0)


if __name__ == "__main__":
    main()
