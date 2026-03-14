#!/usr/bin/env python3
"""
边缘节点离线业务事件队列

背景
----
现有 edge_node_agent.py 中已实现「状态上报」的 SQLite 重试队列，
但仅用于心跳状态 —— 不覆盖餐厅业务场景的离线缓冲需求：

  • 店长语音录入订单（离线时）
  • POS 数据变更推送云端失败
  • 库存盘点结果上报失败
  • 会员积分操作记录

本模块实现通用的「离线业务事件队列」：

1. 入队（enqueue）：本地 SQLite 持久化，立即返回成功
2. 刷新（flush）：联网后批量上报云端，成功后删除
3. 过期清理（purge）：超过 N 天的旧事件自动清理
4. CLI 子命令：list / purge / stats

SQLite 表结构
-------------
  business_events (
    id          INTEGER PK AUTOINCREMENT,
    event_type  TEXT NOT NULL,     -- order_sync | inventory_sync | member_sync | voice_cmd
    store_id    TEXT NOT NULL,
    payload     TEXT NOT NULL,     -- JSON
    source      TEXT,              -- 来源：pos | voice | manual
    created_at  INTEGER NOT NULL,  -- Unix 时间戳（秒）
    attempts    INTEGER DEFAULT 0,
    last_error  TEXT,
    status      TEXT DEFAULT 'pending'  -- pending | flushed | failed
  )

云端上报端点
------------
  POST /api/v1/hardware/edge-node/{node_id}/business-events
  Body: { "events": [{"event_type":..., "store_id":..., "payload":..., ...}] }
  Response: { "success": true, "accepted": N }
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("zhilian-biz-queue")

_DEFAULT_STATE_DIR = Path(os.getenv("EDGE_STATE_DIR", "/var/lib/zhilian-edge"))
_DEFAULT_DB_FILE = _DEFAULT_STATE_DIR / "business_events.db"

# 最大重试次数（超过后标记 failed，不再重试）
_MAX_ATTEMPTS = 10
# 批量刷新每批最大条数
_FLUSH_BATCH_SIZE = 50
# 自动清理超过 N 天的 flushed/failed 事件
_PURGE_DAYS = 30
# 单次刷新上报超时（秒）
_FLUSH_TIMEOUT = 20


class BusinessEventQueue:
    def __init__(
        self,
        db_file: Path = _DEFAULT_DB_FILE,
        node_id: Optional[str] = None,
        api_base_url: str = "",
        device_secret: str = "",
    ) -> None:
        self.db_file = db_file
        self.node_id = node_id or os.getenv("EDGE_NODE_ID", "")
        self.api_base_url = api_base_url or os.getenv("EDGE_API_BASE_URL", "").rstrip("/")
        self.device_secret = device_secret or os.getenv("EDGE_DEVICE_SECRET", "")
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------ #
    #  DB 初始化
    # ------------------------------------------------------------------ #

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS business_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    store_id   TEXT NOT NULL,
                    payload    TEXT NOT NULL,
                    source     TEXT,
                    created_at INTEGER NOT NULL,
                    attempts   INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    status     TEXT NOT NULL DEFAULT 'pending'
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status_created ON business_events(status, created_at)"
            )
            conn.commit()

    # ------------------------------------------------------------------ #
    #  入队（离线 / 联网均可调用）
    # ------------------------------------------------------------------ #

    def enqueue(
        self,
        event_type: str,
        store_id: str,
        payload: Dict[str, Any],
        source: Optional[str] = None,
    ) -> int:
        """
        将业务事件入队，返回事件 ID。

        event_type 建议值：
          order_sync        POS 订单数据同步
          inventory_sync    库存盘点结果上报
          member_sync       会员积分/消费记录
          voice_cmd         语音指令记录
          alert_ack         告警确认
        """
        with sqlite3.connect(self.db_file) as conn:
            cur = conn.execute(
                """
                INSERT INTO business_events (event_type, store_id, payload, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_type, store_id, json.dumps(payload, ensure_ascii=True), source, int(time.time())),
            )
            conn.commit()
            event_id = cur.lastrowid
        logger.debug("event enqueued id=%s type=%s store=%s", event_id, event_type, store_id)
        return event_id or 0

    # ------------------------------------------------------------------ #
    #  刷新（联网后调用）
    # ------------------------------------------------------------------ #

    def flush(self) -> Tuple[int, int]:
        """
        将 pending 事件批量上报云端。
        返回 (flushed_count, failed_count)。
        """
        if not self.api_base_url or not self.node_id:
            logger.warning("flush skipped: api_base_url or node_id not set")
            return 0, 0

        flushed = failed = 0
        while True:
            batch = self._get_pending_batch(_FLUSH_BATCH_SIZE)
            if not batch:
                break
            ok = self._post_batch(batch)
            ids = [row["id"] for row in batch]
            if ok:
                self._mark_flushed(ids)
                flushed += len(ids)
                logger.info("flushed %d events to cloud", len(ids))
            else:
                self._mark_retry(ids)
                failed += len(ids)
                logger.warning("flush failed for %d events, will retry", len(ids))
                break  # 网络异常时停止继续尝试

        return flushed, failed

    def _get_pending_batch(self, limit: int) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, event_type, store_id, payload, source, created_at, attempts
                FROM business_events
                WHERE status = 'pending' AND attempts < ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (_MAX_ATTEMPTS, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _post_batch(self, batch: List[Dict[str, Any]]) -> bool:
        url = f"{self.api_base_url}/api/v1/hardware/edge-node/{self.node_id}/business-events"
        events = []
        for row in batch:
            try:
                payload = json.loads(row["payload"])
            except Exception:
                payload = {}
            events.append({
                "event_type": row["event_type"],
                "store_id": row["store_id"],
                "payload": payload,
                "source": row["source"],
                "created_at": row["created_at"],
            })
        body = json.dumps({"events": events}, ensure_ascii=True).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Edge-Node-Secret": self.device_secret,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_FLUSH_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                return True
            logger.warning("cloud rejected events: %s", data)
            return False
        except urllib.error.URLError as exc:
            logger.warning("network error during flush: %s", exc)
            return False
        except Exception as exc:
            logger.error("flush post error: %s", exc)
            return False

    def _mark_flushed(self, ids: List[int]) -> None:
        placeholders = ",".join("?" * len(ids))
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                f"UPDATE business_events SET status='flushed' WHERE id IN ({placeholders})", ids
            )
            conn.commit()

    def _mark_retry(self, ids: List[int]) -> None:
        placeholders = ",".join("?" * len(ids))
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                f"""
                UPDATE business_events
                SET attempts = attempts + 1,
                    last_error = 'network_error',
                    status = CASE WHEN attempts + 1 >= {_MAX_ATTEMPTS} THEN 'failed' ELSE 'pending' END
                WHERE id IN ({placeholders})
                """,
                ids,
            )
            conn.commit()

    # ------------------------------------------------------------------ #
    #  清理
    # ------------------------------------------------------------------ #

    def purge(self, days: int = _PURGE_DAYS) -> int:
        """删除超过 N 天的已完成/失败事件，返回删除行数。"""
        cutoff = int(time.time()) - days * 86400
        with sqlite3.connect(self.db_file) as conn:
            cur = conn.execute(
                "DELETE FROM business_events WHERE status IN ('flushed','failed') AND created_at < ?",
                (cutoff,),
            )
            conn.commit()
        deleted = cur.rowcount
        if deleted:
            logger.info("purged %d old events (older than %d days)", deleted, days)
        return deleted

    # ------------------------------------------------------------------ #
    #  统计
    # ------------------------------------------------------------------ #

    def stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM business_events GROUP BY status"
            ).fetchall()
        status_counts = {row[0]: row[1] for row in rows}
        with sqlite3.connect(self.db_file) as conn:
            oldest = conn.execute(
                "SELECT MIN(created_at) FROM business_events WHERE status='pending'"
            ).fetchone()[0]
        return {
            "pending": status_counts.get("pending", 0),
            "flushed": status_counts.get("flushed", 0),
            "failed": status_counts.get("failed", 0),
            "oldest_pending_age_seconds": int(time.time()) - oldest if oldest else 0,
        }

    def list_pending(self, limit: int = 20) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, event_type, store_id, source, created_at, attempts
                FROM business_events WHERE status='pending'
                ORDER BY created_at ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


# ------------------------------------------------------------------ #
#  CLI 入口
# ------------------------------------------------------------------ #

def _cli() -> int:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="屯象OS 边缘节点离线业务事件队列")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("stats", help="显示队列统计信息")

    lp = sub.add_parser("list", help="列出待上报事件")
    lp.add_argument("--limit", type=int, default=20)

    pp = sub.add_parser("purge", help="清理过期已完成事件")
    pp.add_argument("--days", type=int, default=_PURGE_DAYS)

    fp = sub.add_parser("flush", help="立即将 pending 事件上报云端")

    ep = sub.add_parser("enqueue", help="手动入队测试事件")
    ep.add_argument("event_type")
    ep.add_argument("store_id")
    ep.add_argument("--payload", default="{}")

    args = parser.parse_args()

    # 从 env 读取连接信息
    q = BusinessEventQueue(
        node_id=os.getenv("EDGE_NODE_ID", ""),
        api_base_url=os.getenv("EDGE_API_BASE_URL", ""),
        device_secret=os.getenv("EDGE_DEVICE_SECRET", ""),
    )

    if args.cmd == "stats" or args.cmd is None:
        s = q.stats()
        print(f"Pending : {s['pending']}")
        print(f"Flushed : {s['flushed']}")
        print(f"Failed  : {s['failed']}")
        if s["oldest_pending_age_seconds"]:
            print(f"Oldest pending : {s['oldest_pending_age_seconds']}s ago")
        return 0

    if args.cmd == "list":
        rows = q.list_pending(args.limit)
        if not rows:
            print("no pending events")
            return 0
        print(f"{'ID':<6} {'TYPE':<20} {'STORE':<12} {'AGE(s)':<10} {'ATTEMPTS'}")
        for row in rows:
            age = int(time.time()) - row["created_at"]
            print(f"{row['id']:<6} {row['event_type']:<20} {row['store_id']:<12} {age:<10} {row['attempts']}")
        return 0

    if args.cmd == "purge":
        n = q.purge(args.days)
        print(f"purged {n} events")
        return 0

    if args.cmd == "flush":
        flushed, failed = q.flush()
        print(f"flushed={flushed} failed={failed}")
        return 0 if failed == 0 else 1

    if args.cmd == "enqueue":
        try:
            payload = json.loads(args.payload)
        except Exception:
            payload = {"raw": args.payload}
        eid = q.enqueue(args.event_type, args.store_id, payload, source="cli")
        print(f"enqueued event id={eid}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
