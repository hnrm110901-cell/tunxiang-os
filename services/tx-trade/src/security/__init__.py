"""tx-trade 安全模块

本模块提供 tx-trade 内部使用的轻量 RBAC 装饰器与审计日志上下文提取工具。
设计约束：
  - 不直接依赖 shared/security（避免循环 import）
  - 复用 gateway/src/middleware/auth_middleware 写入 request.state 的字段
    （user_id / tenant_id / role / mfa_verified），与全局认证链路一致
  - 装饰器语义遵循 gateway/src/middleware/rbac.py：
      require_role(*roles)        — 401 AUTH_MISSING / 403 ROLE_FORBIDDEN
      require_mfa(*roles)         — require_role 之上叠加 MFA 校验
"""
