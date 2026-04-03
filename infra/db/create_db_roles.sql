-- 等保三级：数据库层三权分立
-- 执行环境：PostgreSQL 16，使用超级用户执行一次
-- 警告：三个账号的密码必须由不同人员保管（实体隔离），不可存储在同一密码库

-- ──────────────────────────────────────────────────────────────────
-- 1. 业务服务连接用户（txos_service）
--    职责：读写业务表，可 INSERT 审计日志，不可 DELETE/UPDATE 审计日志
-- ──────────────────────────────────────────────────────────────────
CREATE ROLE txos_service LOGIN PASSWORD 'CHANGE_ME_SERVICE_PWD';

-- 授予业务表完整 CRUD 权限
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA public
    TO txos_service;

-- 审计日志：只允许 INSERT（写入），不允许修改或删除
REVOKE UPDATE, DELETE ON audit_logs FROM txos_service;

-- 确保未来新建表也自动继承权限
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO txos_service;

-- ──────────────────────────────────────────────────────────────────
-- 2. 审计管理员连接用户（txos_auditor）
--    职责：只读审计日志，不可访问任何业务表
--    对应角色：audit_admin
-- ──────────────────────────────────────────────────────────────────
CREATE ROLE txos_auditor LOGIN PASSWORD 'CHANGE_ME_AUDITOR_PWD';

-- 先撤销 public 模式下所有权限（防止继承）
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM txos_auditor;
REVOKE ALL ON SCHEMA public FROM txos_auditor;

-- 仅授予 audit_logs 只读权限
GRANT USAGE ON SCHEMA public TO txos_auditor;
GRANT SELECT ON audit_logs TO txos_auditor;

-- 若有 model_call_logs 等日志表，审计员也可只读
GRANT SELECT ON model_call_logs TO txos_auditor;

-- ──────────────────────────────────────────────────────────────────
-- 3. 数据库管理员连接用户（txos_dba）
--    职责：DDL 权限（建表/改表/维护），不可查看 audit_logs 内容
--    对应角色：system_admin（数据库层面）
-- ──────────────────────────────────────────────────────────────────
CREATE ROLE txos_dba LOGIN PASSWORD 'CHANGE_ME_DBA_PWD';

GRANT ALL PRIVILEGES ON DATABASE tunxiang_os TO txos_dba;

-- 三权分立核心约束：DBA 不可读取审计日志内容
REVOKE SELECT ON audit_logs FROM txos_dba;
REVOKE SELECT ON model_call_logs FROM txos_dba;

-- ──────────────────────────────────────────────────────────────────
-- 说明
-- ──────────────────────────────────────────────────────────────────
-- txos_service  → 业务代码使用，读写业务数据，只写审计
-- txos_auditor  → 审计团队使用，只读审计日志
-- txos_dba      → 运维/DBA使用，维护数据库结构，不可读日志内容
--
-- 三个账号的密码必须：
--   1. 由不同人员（或不同保险箱）保管
--   2. 替换上方 CHANGE_ME_*_PWD 为高强度随机密码
--   3. 通过环境变量注入（TXOS_SERVICE_DB_URL / TXOS_AUDITOR_DB_URL / TXOS_DBA_DB_URL）
--   4. 不得出现在任何代码仓库中
