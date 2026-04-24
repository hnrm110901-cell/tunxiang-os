"""v266 — agent_memories 记忆进化升级（Phase M1）

ALTER agent_memories 新增列：
  scope          TEXT DEFAULT 'store'   — 记忆作用域（tenant/store/user）
  category       TEXT                   — 记忆分类（cost_focus/menu_habit/report_style 等）
  embedding      vector(1536)           — pgvector 向量嵌入（替代 embedding_id 外部引用）
  importance     FLOAT DEFAULT 0.5      — 重要性权重 0-1
  valid_from     TIMESTAMPTZ            — 生效起始时间
  valid_until    TIMESTAMPTZ            — 失效时间（NULL=永久有效）
  source_event   TEXT                   — 产生此记忆的事件类型
  source_detail  JSONB                  — 事件详情
  user_id        UUID                   — 用户级记忆归属（NULL=门店级）

新增索引：
  idx_agent_memories_scope      — (tenant_id, store_id, user_id)
  idx_agent_memories_category   — (memory_type, category)
  idx_agent_memories_embedding  — IVFFlat 向量余弦索引
  idx_agent_memories_valid      — (valid_from, valid_until) 部分索引

Revision ID: v266_mem_evo
Revises: v263_kiosk_voice_count (v265_mv_roi was never merged to main)
Create Date: 2026-04-23
"""

from alembic import op

revision = "v266_mem_evo"
down_revision = "v263"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0. 启用 pgvector 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 1. 新增列
    op.execute("""
        ALTER TABLE agent_memories
            ADD COLUMN IF NOT EXISTS scope          TEXT DEFAULT 'store',
            ADD COLUMN IF NOT EXISTS category       TEXT,
            ADD COLUMN IF NOT EXISTS embedding      vector(1536),
            ADD COLUMN IF NOT EXISTS importance     FLOAT DEFAULT 0.5,
            ADD COLUMN IF NOT EXISTS valid_from     TIMESTAMPTZ DEFAULT NOW(),
            ADD COLUMN IF NOT EXISTS valid_until    TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS source_event   TEXT,
            ADD COLUMN IF NOT EXISTS source_detail  JSONB,
            ADD COLUMN IF NOT EXISTS user_id        UUID
    """)

    # 2. 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_memories_scope
            ON agent_memories (tenant_id, store_id, user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_memories_category
            ON agent_memories (memory_type, category)
    """)
    # IVFFlat 向量索引（仅对非空 embedding 行生效）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_memories_embedding
            ON agent_memories
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_memories_valid
            ON agent_memories (valid_from, valid_until)
            WHERE NOT is_deleted
    """)

    # 3. 列注释
    op.execute("""
        COMMENT ON COLUMN agent_memories.scope IS
            '记忆作用域：tenant=品牌级 / store=门店级 / user=用户级';
        COMMENT ON COLUMN agent_memories.category IS
            '记忆分类：cost_focus / menu_habit / report_style 等';
        COMMENT ON COLUMN agent_memories.embedding IS
            'pgvector 1536 维向量嵌入，用于语义搜索';
        COMMENT ON COLUMN agent_memories.importance IS
            '重要性权重 0-1，用于记忆衰减与检索排序';
        COMMENT ON COLUMN agent_memories.valid_from IS
            '记忆生效起始时间';
        COMMENT ON COLUMN agent_memories.valid_until IS
            '记忆失效时间，NULL 表示永久有效';
        COMMENT ON COLUMN agent_memories.source_event IS
            '产生此记忆的事件类型';
        COMMENT ON COLUMN agent_memories.source_detail IS
            '产生此记忆的事件详情';
        COMMENT ON COLUMN agent_memories.user_id IS
            '用户级记忆归属，NULL 表示门店级';
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_memories_valid")
    op.execute("DROP INDEX IF EXISTS idx_agent_memories_embedding")
    op.execute("DROP INDEX IF EXISTS idx_agent_memories_category")
    op.execute("DROP INDEX IF EXISTS idx_agent_memories_scope")
    op.execute("""
        ALTER TABLE agent_memories
            DROP COLUMN IF EXISTS user_id,
            DROP COLUMN IF EXISTS source_detail,
            DROP COLUMN IF EXISTS source_event,
            DROP COLUMN IF EXISTS valid_until,
            DROP COLUMN IF EXISTS valid_from,
            DROP COLUMN IF EXISTS importance,
            DROP COLUMN IF EXISTS embedding,
            DROP COLUMN IF EXISTS category,
            DROP COLUMN IF EXISTS scope
    """)
