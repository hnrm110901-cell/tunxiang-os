"""tx-agent prompt 模块

存放各 Skill Agent 的系统提示（含 Prompt Cache 稳定前缀）。

Sprint D4a 起接入 Anthropic Prompt Cache：
  - 系统身份 + 领域 schema（稳定 ≥1024 tokens）放 cache 层
  - 用户 query（短小易变）放 messages 层
  - 目标 cache_hit_ratio ≥ 0.75
"""
