"""Verify all 73 Agent actions are callable"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "tx-agent", "src"))
from agents.skills import ALL_SKILL_AGENTS

total = ok = 0
for cls in ALL_SKILL_AGENTS:
    a = cls(tenant_id="test")
    for act in a.get_supported_actions():
        r = asyncio.run(a.execute(act, {}))
        total += 1
        if r.success or "Unsupported" not in (r.error or ""):
            ok += 1
print(f"Agent actions: {ok}/{total} ({round(ok/total*100)}%)")
assert ok == total, f"FAIL: {ok}/{total}"
