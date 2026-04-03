"""models.py — SQLite 本地同步状态模型（aiosqlite，非 SQLAlchemy）

两张表：
  sync_watermarks   — 各表的上次同步时间戳（上传/下载双向水位）
  local_change_log  — 本地写操作的变更日志，用于断网缓冲推送
"""

SYNC_WATERMARKS_DDL = """
CREATE TABLE IF NOT EXISTS sync_watermarks (
    table_name   TEXT PRIMARY KEY,
    last_sync_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00',
    upload_at    TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00',
    record_count INTEGER DEFAULT 0
)
"""

LOCAL_CHANGE_LOG_DDL = """
CREATE TABLE IF NOT EXISTS local_change_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT    NOT NULL,
    record_id  TEXT    NOT NULL,
    operation  TEXT    NOT NULL,
    payload    TEXT    NOT NULL,
    created_at TEXT    DEFAULT (datetime('now', 'utc')),
    synced     INTEGER DEFAULT 0
)
"""

LOCAL_CHANGE_LOG_IDX = """
CREATE INDEX IF NOT EXISTS idx_change_log_synced
    ON local_change_log (synced, created_at)
"""
