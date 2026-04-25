"""v296 — api_idempotency_cache：HTTP 路由级幂等 replay cache（A1-R3 / Tier1）

§19 审查 R-A1-3 阻塞修复：apps/web-pos R-补2-1 (commit 48aba740) 客户端 replay
携带 X-Idempotency-Key header，但 tx-trade 服务端没有任何路由级 replay cache。
3s soft abort + retry 场景下：第一次请求服务端仍在跑 settle/payment（已扣会员
储值或调起第三方支付），客户端 retry 第二次到服务端 → 服务端无 cache 拦截
→ 第二次同样处理 → **saga 双扣 / 储值双扣 / 第三方支付双扣**。

设计要点：
  1. 表 api_idempotency_cache：
       - 主键 (tenant_id, idempotency_key, route_path) — 同一 key 可在不同
         路由上独立计算（settle/payments 不互相串）
       - request_hash — SHA256(method+path+body)，检测同 key 不同 body 攻击
       - response_status / response_body(JSONB) — 第一次成功响应 snapshot
       - expires_at — TTL 默认 24h（足够覆盖 POS 离线队列回放窗口）
       - state — 'processing' / 'completed' 用于配合 PG advisory_lock 拦截
         首次请求处理中的并发同 key 重复请求

  2. 索引：
       - idx_api_idem_cleanup — WHERE expires_at < NOW() 部分索引，支持
         Sweeper 定期 GC 过期记录（建议 10 min cron 由 sync-engine 触发）

  3. RLS：
       - tenant_id 列 + 标准 RLS 策略（沿用 trade_audit_logs 模式）
       - app.tenant_id 必须设置才能 SELECT/INSERT；防止跨租户 cache 污染

  4. PG advisory_xact_lock：
       - 应用层在路由开始时 SELECT pg_advisory_xact_lock(hash(tenant_id|key|route))
       - 同 key 并发请求自动串行；首次完成后第二次直接读 cache 命中
       - lock 在事务 commit/rollback 时自动释放，无需显式 unlock

向前兼容：
  - 表新增不影响现有路由；只有路由代码主动读写时才生效
  - 客户端 R-补2-1 已部署但服务端无 cache 时退化为"无幂等"（双扣风险）
    → 本迁移 + 路由 wiring 闭环风险

Revision ID: v296
Revises: v295
Create Date: 2026-04-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v296"
down_revision: Union[str, None] = "v295"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "api_idempotency_cache" in existing_tables:
        # 已存在（可能其他迁移先建过）— inspect-and-skip
        return

    op.execute(
        """
        CREATE TABLE api_idempotency_cache (
            tenant_id        UUID         NOT NULL,
            idempotency_key  VARCHAR(128) NOT NULL,
            route_path       VARCHAR(128) NOT NULL,
            request_hash     CHAR(64)     NOT NULL,
            response_status  SMALLINT     NOT NULL DEFAULT 200,
            response_body    JSONB,
            state            VARCHAR(16)  NOT NULL DEFAULT 'completed'
                CHECK (state IN ('processing', 'completed', 'failed')),
            store_id         UUID,
            user_id          UUID,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            expires_at       TIMESTAMPTZ  NOT NULL,
            PRIMARY KEY (tenant_id, idempotency_key, route_path)
        )
        """
    )

    # ── RLS 启用 + 策略（与 trade_audit_logs / scan_pay_transactions 同模式）
    op.execute("ALTER TABLE api_idempotency_cache ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY api_idempotency_cache_tenant_isolation
        ON api_idempotency_cache
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )

    # ── 索引：过期清理（部分索引，体积只占活跃 entry 的 ~5%）
    op.execute(
        """
        CREATE INDEX idx_api_idem_expired
        ON api_idempotency_cache (expires_at)
        WHERE expires_at < NOW()
        """
    )

    # ── 索引：route_path + state 用于排查"哪些 key 卡在 processing"运维场景
    op.execute(
        """
        CREATE INDEX idx_api_idem_route_state
        ON api_idempotency_cache (tenant_id, route_path, state, created_at DESC)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "api_idempotency_cache" not in set(inspector.get_table_names()):
        return
    op.execute("DROP TABLE api_idempotency_cache CASCADE")
