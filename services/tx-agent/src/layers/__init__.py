"""屯象OS AI Agent 八层架构

L0  终端交互层      → apps/ (React Web App + 各终端壳层)
L1  场景会话层      → layers/scene_session.py
L2  Agent 编排层    → layers/orchestrator.py + specialists/
L3  Tool/MCP 网关层  → layers/tool_gateway.py
L4  交易与业务域服务  → services/ (tx-trade, tx-menu, etc.)
L5  状态机与规则引擎  → layers/state_machines.py
L6  数据与智能底座   → agents/event_bus.py + agents/memory_bus.py
L7  基础设施与设备   → edge/ + infra/
"""
