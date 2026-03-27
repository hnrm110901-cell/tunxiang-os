"""排队叫号服务 — V1迁入并增强

排队全流程：取号→等位→叫号→到店→过号→入座
支持美团排队对接 + 等位时间预估 + 桌台联动

所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 内存存储（生产环境替换为 DB Repository） ───

_queues: dict[str, dict] = {}
_queue_counters: dict[str, dict[str, int]] = {}  # store_id -> {prefix: last_number}
_queue_history: dict[str, list[dict]] = {}  # store_id -> [queue records]


def _gen_id() -> str:
    return uuid.uuid4().hex[:12].upper()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ─── 排队号前缀规则 ───
# A系列：1-4人小桌  B系列：5-8人中桌  C系列：9+人大桌

def _size_prefix(party_size: int) -> str:
    if party_size <= 4:
        return "A"
    elif party_size <= 8:
        return "B"
    else:
        return "C"


SIZE_CATEGORY_LABELS = {
    "A": "小桌(1-4人)",
    "B": "中桌(5-8人)",
    "C": "大桌(9人以上)",
}

QUEUE_STATUS = ["waiting", "called", "arrived", "seated", "skipped", "cancelled"]

# 各桌型平均用餐时长（分钟），用于等位时间预估
AVG_DINING_DURATION = {
    "A": 45,  # 小桌平均45分钟
    "B": 60,  # 中桌平均60分钟
    "C": 90,  # 大桌平均90分钟
}

# 各桌型典型门店桌数配置
DEFAULT_TABLE_COUNTS = {
    "A": 15,  # 小桌15张
    "B": 8,   # 中桌8张
    "C": 4,   # 大桌4张
}


class QueueService:
    """排队叫号服务 — V1迁入并增强

    排队全流程：取号→等位→叫号→到店→过号→入座
    支持美团排队对接+等位时间预估
    """

    def __init__(self, tenant_id: str, store_id: str):
        self.tenant_id = tenant_id
        self.store_id = store_id

    # ─── 取号 ───

    def take_number(
        self,
        store_id: str,
        customer_name: str,
        phone: str,
        party_size: int,
        source: str = "walk_in",
        vip_priority: bool = False,
        reservation_id: Optional[str] = None,
    ) -> dict:
        """取排队号

        Args:
            store_id: 门店ID
            customer_name: 顾客姓名
            phone: 手机号
            party_size: 就餐人数
            source: 来源 walk_in/meituan/reservation/wechat
            vip_priority: VIP优先排队
            reservation_id: 关联预订ID（预订到店后转排队）

        Returns:
            {queue_id, queue_number, estimated_wait_min, ahead_count, ...}
        """
        if party_size <= 0:
            raise ValueError("party_size must be positive")
        if source not in ("walk_in", "meituan", "reservation", "wechat"):
            raise ValueError(f"Invalid source: {source}")

        prefix = _size_prefix(party_size)

        # 获取当日计数器
        counter_key = f"{store_id}:{_today_str()}"
        if counter_key not in _queue_counters:
            _queue_counters[counter_key] = {"A": 0, "B": 0, "C": 0}
        _queue_counters[counter_key][prefix] += 1
        seq = _queue_counters[counter_key][prefix]
        queue_number = f"{prefix}{seq:03d}"

        # 计算前面等待人数
        ahead_count = self._count_waiting(store_id, prefix)

        # 估算等位时间
        est = self._calculate_wait_time(store_id, prefix, ahead_count)

        queue_id = f"Q-{_gen_id()}"
        now = _now_iso()

        # VIP 优先：插入到等待队列前面（设置较早的优先级时间戳）
        priority_ts = now
        if vip_priority:
            # VIP 的优先级时间设为比最早等待者还早1秒
            earliest = self._get_earliest_waiting_ts(store_id, prefix)
            if earliest:
                dt = datetime.fromisoformat(earliest) - timedelta(seconds=1)
                priority_ts = dt.isoformat()

        record = {
            "queue_id": queue_id,
            "tenant_id": self.tenant_id,
            "store_id": store_id,
            "queue_number": queue_number,
            "prefix": prefix,
            "seq": seq,
            "customer_name": customer_name,
            "phone": phone,
            "party_size": party_size,
            "source": source,
            "vip_priority": vip_priority,
            "reservation_id": reservation_id,
            "status": "waiting",
            "priority_ts": priority_ts,
            "taken_at": now,
            "called_at": None,
            "arrived_at": None,
            "seated_at": None,
            "skipped_at": None,
            "cancelled_at": None,
            "table_no": None,
            "skip_reason": None,
            "cancel_reason": None,
            "notification_count": 0,
            "date": _today_str(),
        }

        _queues[queue_id] = record

        # 加入历史记录
        history_key = f"{store_id}:{_today_str()}"
        if history_key not in _queue_history:
            _queue_history[history_key] = []
        _queue_history[history_key].append(record)

        logger.info(
            "queue_number_taken",
            queue_id=queue_id,
            queue_number=queue_number,
            party_size=party_size,
            source=source,
            vip=vip_priority,
        )

        return {
            "queue_id": queue_id,
            "queue_number": queue_number,
            "party_size": party_size,
            "size_category": SIZE_CATEGORY_LABELS[prefix],
            "estimated_wait_min": est["estimated_wait_min"],
            "ahead_count": ahead_count if not vip_priority else 0,
            "taken_at": now,
            "source": source,
            "vip_priority": vip_priority,
        }

    # ─── 叫号 ───

    def call_number(self, queue_id: str) -> dict:
        """叫号 — 变更状态为called，发送通知

        Args:
            queue_id: 排队ID

        Returns:
            {queue_id, queue_number, called_at, notification_sent}
        """
        record = _queues.get(queue_id)
        if not record:
            raise ValueError(f"Queue record not found: {queue_id}")
        if record["status"] != "waiting":
            raise ValueError(
                f"Cannot call queue {queue_id}: current status is '{record['status']}', expected 'waiting'"
            )

        now = _now_iso()
        record["status"] = "called"
        record["called_at"] = now
        record["notification_count"] = 1

        # 模拟发送 SMS/微信通知
        notification_sent = self._send_notification(
            record["phone"],
            record["customer_name"],
            record["queue_number"],
            record["store_id"],
        )

        logger.info(
            "queue_number_called",
            queue_id=queue_id,
            queue_number=record["queue_number"],
            notification_sent=notification_sent,
        )

        return {
            "queue_id": queue_id,
            "queue_number": record["queue_number"],
            "customer_name": record["customer_name"],
            "party_size": record["party_size"],
            "called_at": now,
            "notification_sent": notification_sent,
            "auto_skip_at": (
                datetime.fromisoformat(now) + timedelta(minutes=10)
            ).isoformat(),
        }

    # ─── 顾客到店 ───

    def customer_arrived(self, queue_id: str) -> dict:
        """顾客到店确认

        Args:
            queue_id: 排队ID

        Returns:
            {queue_id, queue_number, arrived_at, wait_duration_min}
        """
        record = _queues.get(queue_id)
        if not record:
            raise ValueError(f"Queue record not found: {queue_id}")
        if record["status"] not in ("waiting", "called"):
            raise ValueError(
                f"Cannot mark arrived for queue {queue_id}: "
                f"current status is '{record['status']}', expected 'waiting' or 'called'"
            )

        now = _now_iso()
        record["status"] = "arrived"
        record["arrived_at"] = now

        # 计算实际等待时间
        taken_dt = datetime.fromisoformat(record["taken_at"])
        arrived_dt = datetime.fromisoformat(now)
        wait_duration_min = int((arrived_dt - taken_dt).total_seconds() / 60)

        logger.info(
            "queue_customer_arrived",
            queue_id=queue_id,
            queue_number=record["queue_number"],
            wait_min=wait_duration_min,
        )

        return {
            "queue_id": queue_id,
            "queue_number": record["queue_number"],
            "customer_name": record["customer_name"],
            "party_size": record["party_size"],
            "arrived_at": now,
            "wait_duration_min": wait_duration_min,
        }

    # ─── 入座 ───

    def seat_customer(self, queue_id: str, table_no: str) -> dict:
        """安排入座 — 关联桌台，触发开台

        Args:
            queue_id: 排队ID
            table_no: 分配的桌号

        Returns:
            {queue_id, queue_number, table_no, seated_at, total_wait_min}
        """
        record = _queues.get(queue_id)
        if not record:
            raise ValueError(f"Queue record not found: {queue_id}")
        if record["status"] not in ("waiting", "called", "arrived"):
            raise ValueError(
                f"Cannot seat queue {queue_id}: "
                f"current status is '{record['status']}', expected 'waiting', 'called', or 'arrived'"
            )

        now = _now_iso()
        record["status"] = "seated"
        record["seated_at"] = now
        record["table_no"] = table_no

        # 计算总等待时间
        taken_dt = datetime.fromisoformat(record["taken_at"])
        seated_dt = datetime.fromisoformat(now)
        total_wait_min = int((seated_dt - taken_dt).total_seconds() / 60)

        logger.info(
            "queue_customer_seated",
            queue_id=queue_id,
            queue_number=record["queue_number"],
            table_no=table_no,
            total_wait_min=total_wait_min,
        )

        return {
            "queue_id": queue_id,
            "queue_number": record["queue_number"],
            "customer_name": record["customer_name"],
            "party_size": record["party_size"],
            "table_no": table_no,
            "seated_at": now,
            "total_wait_min": total_wait_min,
            "reservation_id": record.get("reservation_id"),
        }

    # ─── 过号 ───

    def skip_customer(self, queue_id: str, reason: str = "no_show") -> dict:
        """过号 — 叫号后超时未到或主动跳过

        Args:
            queue_id: 排队ID
            reason: 过号原因 no_show/timeout/manual

        Returns:
            {queue_id, queue_number, skipped_at, reason}
        """
        record = _queues.get(queue_id)
        if not record:
            raise ValueError(f"Queue record not found: {queue_id}")
        if record["status"] not in ("waiting", "called"):
            raise ValueError(
                f"Cannot skip queue {queue_id}: "
                f"current status is '{record['status']}', expected 'waiting' or 'called'"
            )

        now = _now_iso()
        record["status"] = "skipped"
        record["skipped_at"] = now
        record["skip_reason"] = reason

        logger.info(
            "queue_customer_skipped",
            queue_id=queue_id,
            queue_number=record["queue_number"],
            reason=reason,
        )

        return {
            "queue_id": queue_id,
            "queue_number": record["queue_number"],
            "customer_name": record["customer_name"],
            "skipped_at": now,
            "reason": reason,
        }

    # ─── 取消排队 ───

    def cancel_queue(self, queue_id: str, reason: str = "") -> dict:
        """取消排队

        Args:
            queue_id: 排队ID
            reason: 取消原因

        Returns:
            {queue_id, queue_number, cancelled_at, reason}
        """
        record = _queues.get(queue_id)
        if not record:
            raise ValueError(f"Queue record not found: {queue_id}")
        if record["status"] in ("seated", "skipped", "cancelled"):
            raise ValueError(
                f"Cannot cancel queue {queue_id}: already in terminal status '{record['status']}'"
            )

        now = _now_iso()
        record["status"] = "cancelled"
        record["cancelled_at"] = now
        record["cancel_reason"] = reason

        logger.info(
            "queue_cancelled",
            queue_id=queue_id,
            queue_number=record["queue_number"],
            reason=reason,
        )

        return {
            "queue_id": queue_id,
            "queue_number": record["queue_number"],
            "customer_name": record["customer_name"],
            "cancelled_at": now,
            "reason": reason,
        }

    # ─── 排队看板 ───

    def get_queue_board(self, store_id: str) -> dict:
        """获取排队看板 — 当前各桌型等待/叫号/平均等位

        Returns:
            {total_waiting, total_called, groups: [{size_category, prefix, count, avg_wait_min}]}
        """
        today = _today_str()
        all_records = [
            q for q in _queues.values()
            if q["store_id"] == store_id and q["date"] == today
        ]

        waiting = [q for q in all_records if q["status"] == "waiting"]
        called = [q for q in all_records if q["status"] == "called"]
        seated_today = [q for q in all_records if q["status"] == "seated"]

        # 按桌型分组
        groups = []
        for prefix in ["A", "B", "C"]:
            prefix_waiting = [q for q in waiting if q["prefix"] == prefix]
            prefix_called = [q for q in called if q["prefix"] == prefix]

            # 计算该桌型平均等位时间
            avg_wait = self._calculate_wait_time(store_id, prefix, len(prefix_waiting))

            groups.append({
                "prefix": prefix,
                "size_category": SIZE_CATEGORY_LABELS[prefix],
                "waiting_count": len(prefix_waiting),
                "called_count": len(prefix_called),
                "avg_wait_min": avg_wait["estimated_wait_min"],
                "next_queue_numbers": [
                    q["queue_number"] for q in sorted(
                        prefix_waiting, key=lambda x: x["priority_ts"]
                    )[:3]
                ],
            })

        return {
            "store_id": store_id,
            "date": today,
            "total_waiting": len(waiting),
            "total_called": len(called),
            "total_seated_today": len(seated_today),
            "total_today": len(all_records),
            "groups": groups,
            "updated_at": _now_iso(),
        }

    # ─── 等位时间预估 ───

    def estimate_wait_time(self, store_id: str, party_size: int) -> dict:
        """预估等位时间

        基于：当前排队长度 + 可用桌数 + 平均用餐时长

        Args:
            store_id: 门店ID
            party_size: 就餐人数

        Returns:
            {estimated_wait_min, ahead_count, available_tables, size_category}
        """
        if party_size <= 0:
            raise ValueError("party_size must be positive")

        prefix = _size_prefix(party_size)
        ahead_count = self._count_waiting(store_id, prefix)
        result = self._calculate_wait_time(store_id, prefix, ahead_count)

        return {
            "store_id": store_id,
            "party_size": party_size,
            "size_category": SIZE_CATEGORY_LABELS[prefix],
            "prefix": prefix,
            "ahead_count": ahead_count,
            "estimated_wait_min": result["estimated_wait_min"],
            "available_tables": result["available_tables"],
            "avg_dining_min": AVG_DINING_DURATION[prefix],
        }

    # ─── 排队历史 ───

    def get_queue_history(
        self,
        store_id: str,
        date: str,
        page: int = 1,
        size: int = 50,
    ) -> dict:
        """获取排队历史记录

        Args:
            store_id: 门店ID
            date: 日期 YYYY-MM-DD
            page: 页码
            size: 每页条数

        Returns:
            {items: [...], total, page, size, stats: {...}}
        """
        history_key = f"{store_id}:{date}"
        records = _queue_history.get(history_key, [])

        # 统计
        total = len(records)
        seated = [r for r in records if r["status"] == "seated"]
        skipped = [r for r in records if r["status"] == "skipped"]
        cancelled = [r for r in records if r["status"] == "cancelled"]

        # 计算平均等位时间（已入座的）
        wait_times = []
        for r in seated:
            if r.get("seated_at") and r.get("taken_at"):
                taken = datetime.fromisoformat(r["taken_at"])
                seated_dt = datetime.fromisoformat(r["seated_at"])
                wait_times.append(int((seated_dt - taken).total_seconds() / 60))

        avg_wait_min = sum(wait_times) // len(wait_times) if wait_times else 0

        # 分页
        start = (page - 1) * size
        end = start + size
        page_items = records[start:end]

        stats = {
            "total": total,
            "seated": len(seated),
            "skipped": len(skipped),
            "cancelled": len(cancelled),
            "avg_wait_min": avg_wait_min,
            "abandon_rate_pct": round(
                (len(skipped) + len(cancelled)) / max(1, total) * 100, 1
            ),
        }

        return {
            "items": page_items,
            "total": total,
            "page": page,
            "size": size,
            "stats": stats,
        }

    # ─── 美团排队同步 ───

    def sync_meituan_queue(self, store_id: str, meituan_data: list[dict]) -> dict:
        """导入美团线上排队数据

        Args:
            store_id: 门店ID
            meituan_data: 美团排队记录列表
                [{"customer_name": "张三", "phone": "138...", "party_size": 4,
                  "meituan_queue_no": "MT001", "taken_at": "2026-03-27T12:00:00"}, ...]

        Returns:
            {synced_count, skipped_count, queue_ids}
        """
        synced = []
        skipped = 0

        for item in meituan_data:
            # 检查是否已同步（按手机号+日期去重）
            existing = [
                q for q in _queues.values()
                if q["store_id"] == store_id
                and q["phone"] == item.get("phone", "")
                and q["date"] == _today_str()
                and q["source"] == "meituan"
            ]
            if existing:
                skipped += 1
                continue

            result = self.take_number(
                store_id=store_id,
                customer_name=item.get("customer_name", "美团顾客"),
                phone=item.get("phone", ""),
                party_size=item.get("party_size", 2),
                source="meituan",
                vip_priority=False,
            )
            synced.append(result["queue_id"])

        logger.info(
            "meituan_queue_synced",
            store_id=store_id,
            synced=len(synced),
            skipped=skipped,
        )

        return {
            "store_id": store_id,
            "synced_count": len(synced),
            "skipped_count": skipped,
            "queue_ids": synced,
        }

    # ─── 自动叫号（取下一位） ───

    def call_next(self, store_id: str, prefix: str = "") -> Optional[dict]:
        """自动叫号 — 取队列中优先级最高的等待者

        Args:
            store_id: 门店ID
            prefix: 可选桌型前缀筛选 A/B/C

        Returns:
            叫号结果 or None（无等待者）
        """
        today = _today_str()
        waiting = [
            q for q in _queues.values()
            if q["store_id"] == store_id
            and q["date"] == today
            and q["status"] == "waiting"
        ]
        if prefix:
            waiting = [q for q in waiting if q["prefix"] == prefix]

        if not waiting:
            return None

        # 按优先级时间排序（VIP的priority_ts更早）
        waiting.sort(key=lambda q: q["priority_ts"])
        next_item = waiting[0]

        return self.call_number(next_item["queue_id"])

    # ─── 内部辅助方法 ───

    def _count_waiting(self, store_id: str, prefix: str) -> int:
        """统计某桌型当前等待人数"""
        today = _today_str()
        return len([
            q for q in _queues.values()
            if q["store_id"] == store_id
            and q["date"] == today
            and q["prefix"] == prefix
            and q["status"] == "waiting"
        ])

    def _get_earliest_waiting_ts(self, store_id: str, prefix: str) -> Optional[str]:
        """获取某桌型最早等待者的priority_ts"""
        today = _today_str()
        waiting = [
            q for q in _queues.values()
            if q["store_id"] == store_id
            and q["date"] == today
            and q["prefix"] == prefix
            and q["status"] == "waiting"
        ]
        if not waiting:
            return None
        waiting.sort(key=lambda q: q["priority_ts"])
        return waiting[0]["priority_ts"]

    def _calculate_wait_time(
        self, store_id: str, prefix: str, ahead_count: int
    ) -> dict:
        """计算预估等位时间

        算法：
        - 可用桌数 = 该桌型总桌数（默认配置）
        - 每轮翻台释放一批桌
        - 等待时间 = (前面等待组数 / 可用桌数) * 平均用餐时长
        """
        table_count = DEFAULT_TABLE_COUNTS.get(prefix, 10)
        avg_dining = AVG_DINING_DURATION.get(prefix, 60)

        if table_count == 0:
            estimated_min = ahead_count * 15
        else:
            # 前面多少轮才能排到
            rounds = ahead_count / table_count
            estimated_min = int(rounds * avg_dining)

        return {
            "estimated_wait_min": max(0, estimated_min),
            "available_tables": table_count,
            "ahead_count": ahead_count,
        }

    def _send_notification(
        self, phone: str, customer_name: str, queue_number: str, store_id: str
    ) -> bool:
        """发送叫号通知（SMS/微信模板消息）

        生产环境对接短信网关和微信模板消息接口。
        当前为模拟实现。
        """
        logger.info(
            "queue_notification_sent",
            phone=phone,
            customer_name=customer_name,
            queue_number=queue_number,
            store_id=store_id,
            message=f"【排队叫号】{customer_name}您好，您的排队号 {queue_number} 已到号，请尽快到店入座。超过10分钟将自动过号。",
        )
        return True


# ─── 模块级便捷函数（兼容 reservation_flow.py 的调用风格） ───

def take_queue_number(store_id: str, customer_name: str, phone: str,
                      party_size: int, tenant_id: str = "default") -> dict:
    """便捷函数：快速取号"""
    svc = QueueService(tenant_id=tenant_id, store_id=store_id)
    return svc.take_number(store_id, customer_name, phone, party_size)


def get_store_queue_board(store_id: str, tenant_id: str = "default") -> dict:
    """便捷函数：获取门店排队看板"""
    svc = QueueService(tenant_id=tenant_id, store_id=store_id)
    return svc.get_queue_board(store_id)
