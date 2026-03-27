"""桌台管理器 — 增强版状态机

States: free -> occupied -> settling -> cleaning -> free
        free -> reserved -> occupied -> ...
        any -> disabled

金额统一存分（fen），展示时 /100 转元。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from .state_machine import TABLE_STATES, TABLE_TRANSITIONS, can_table_transition

logger = structlog.get_logger()


class TableManager:
    """桌台管理器 — 增强版状态机

    States: free -> occupied -> settling -> cleaning -> free
            free -> reserved -> occupied -> ...
            any -> disabled
    """

    # 状态映射到 state_machine.py 的状态
    STATUS_MAP = {
        "free": "empty",
        "occupied": "dining",
        "settling": "pending_checkout",
        "cleaning": "pending_cleanup",
        "reserved": "reserved",
        "disabled": "maintenance",
    }

    # 反向映射
    STATUS_REVERSE = {v: k for k, v in STATUS_MAP.items()}

    def __init__(self) -> None:
        # 内存桌台状态存储（生产环境应用数据库）
        self._tables: dict[str, dict[str, dict]] = {}  # store_id -> {table_no -> table_data}

    def _get_store_tables(self, store_id: str) -> dict[str, dict]:
        if store_id not in self._tables:
            self._tables[store_id] = {}
        return self._tables[store_id]

    def _get_table(self, store_id: str, table_no: str) -> dict:
        tables = self._get_store_tables(store_id)
        if table_no not in tables:
            raise ValueError(f"桌台不存在: {store_id}/{table_no}")
        return tables[table_no]

    def init_tables(self, store_id: str, table_configs: list[dict]) -> list[dict]:
        """初始化门店桌台

        Args:
            store_id: 门店ID
            table_configs: [{table_no, zone, capacity, min_consume_fen}]

        Returns:
            初始化后的桌台列表
        """
        tables = self._get_store_tables(store_id)
        results = []

        for cfg in table_configs:
            table_no = cfg["table_no"]
            table_data = {
                "table_no": table_no,
                "zone": cfg.get("zone", "大厅"),
                "capacity": cfg.get("capacity", 4),
                "min_consume_fen": cfg.get("min_consume_fen", 0),
                "status": "free",
                "order_id": None,
                "guest_count": 0,
                "open_time": None,
                "waiter_id": None,
                "merged_with": [],      # 并桌的其他桌号
                "is_main_table": True,   # 并桌时的主桌
            }
            tables[table_no] = table_data
            results.append(dict(table_data))

        logger.info("tables_initialized", store_id=store_id, count=len(table_configs))
        return results

    def get_table_map(self, store_id: str) -> list[dict]:
        """获取门店桌台全景图

        Returns:
            [{table_no, zone, capacity, status, order_id,
              guest_count, open_time, duration_min, amount_fen}]
        """
        tables = self._get_store_tables(store_id)
        now = datetime.now(timezone.utc)
        result = []

        for table_no, table in tables.items():
            entry = dict(table)
            # 计算就餐时长
            if table["open_time"]:
                delta = now - table["open_time"]
                entry["duration_min"] = int(delta.total_seconds() / 60)
            else:
                entry["duration_min"] = 0
            result.append(entry)

        return sorted(result, key=lambda x: x["table_no"])

    def open_table(
        self,
        store_id: str,
        table_no: str,
        guest_count: int,
        waiter_id: str,
        order_id: Optional[str] = None,
    ) -> dict:
        """开台

        Args:
            store_id: 门店ID
            table_no: 桌号
            guest_count: 就餐人数
            waiter_id: 服务员ID
            order_id: 关联订单ID

        Returns:
            更新后的桌台状态
        """
        table = self._get_table(store_id, table_no)

        if table["status"] not in ("free", "reserved"):
            raise ValueError(
                f"桌台{table_no}当前状态为{table['status']}，无法开台（需free或reserved）"
            )

        now = datetime.now(timezone.utc)
        table["status"] = "occupied"
        table["guest_count"] = guest_count
        table["waiter_id"] = waiter_id
        table["open_time"] = now
        table["order_id"] = order_id or str(uuid.uuid4())

        logger.info(
            "table_opened",
            store_id=store_id,
            table_no=table_no,
            guest_count=guest_count,
            waiter_id=waiter_id,
        )

        return dict(table)

    def release_table(self, store_id: str, table_no: str) -> dict:
        """释放桌台 — 清台完成后回到free"""
        table = self._get_table(store_id, table_no)

        if table["status"] not in ("cleaning", "occupied", "settling"):
            raise ValueError(
                f"桌台{table_no}当前状态为{table['status']}，无法释放"
            )

        duration_min = 0
        if table["open_time"]:
            delta = datetime.now(timezone.utc) - table["open_time"]
            duration_min = int(delta.total_seconds() / 60)

        table["status"] = "free"
        table["order_id"] = None
        table["guest_count"] = 0
        table["open_time"] = None
        table["waiter_id"] = None
        table["merged_with"] = []
        table["is_main_table"] = True

        logger.info("table_released", store_id=store_id, table_no=table_no, duration_min=duration_min)

        return {**dict(table), "duration_min": duration_min}

    def reserve_table(
        self,
        store_id: str,
        table_no: str,
        reservation_id: str,
        guest_name: Optional[str] = None,
        reserved_time: Optional[str] = None,
    ) -> dict:
        """预留桌台"""
        table = self._get_table(store_id, table_no)

        if table["status"] != "free":
            raise ValueError(f"桌台{table_no}当前状态为{table['status']}，无法预留（需free）")

        table["status"] = "reserved"
        table["order_id"] = reservation_id

        logger.info(
            "table_reserved",
            store_id=store_id,
            table_no=table_no,
            reservation_id=reservation_id,
        )

        return dict(table)

    def start_cleaning(self, store_id: str, table_no: str) -> dict:
        """开始清台"""
        table = self._get_table(store_id, table_no)

        if table["status"] not in ("occupied", "settling"):
            raise ValueError(
                f"桌台{table_no}当前状态为{table['status']}，无法清台（需occupied或settling）"
            )

        table["status"] = "cleaning"

        logger.info("table_cleaning_started", store_id=store_id, table_no=table_no)
        return dict(table)

    def start_settling(self, store_id: str, table_no: str) -> dict:
        """开始结账"""
        table = self._get_table(store_id, table_no)

        if table["status"] != "occupied":
            raise ValueError(
                f"桌台{table_no}当前状态为{table['status']}，无法结账（需occupied）"
            )

        table["status"] = "settling"

        logger.info("table_settling_started", store_id=store_id, table_no=table_no)
        return dict(table)

    def disable_table(self, store_id: str, table_no: str, reason: str) -> dict:
        """停用桌台"""
        table = self._get_table(store_id, table_no)

        if table["status"] == "occupied":
            raise ValueError(f"桌台{table_no}正在使用中，无法停用（请先结账释放）")

        table["status"] = "disabled"
        table["_disable_reason"] = reason

        logger.info("table_disabled", store_id=store_id, table_no=table_no, reason=reason)
        return dict(table)

    def enable_table(self, store_id: str, table_no: str) -> dict:
        """启用已停用的桌台"""
        table = self._get_table(store_id, table_no)

        if table["status"] != "disabled":
            raise ValueError(f"桌台{table_no}当前状态为{table['status']}，非停用状态")

        table["status"] = "free"
        table.pop("_disable_reason", None)

        logger.info("table_enabled", store_id=store_id, table_no=table_no)
        return dict(table)

    def merge_tables(
        self,
        store_id: str,
        table_nos: list[str],
        main_table_no: str,
    ) -> dict:
        """并桌

        将多张桌台合并为一组，以 main_table_no 为主桌。
        所有桌台必须为 free 或 occupied 状态。

        Args:
            store_id: 门店ID
            table_nos: 要合并的桌号列表（含主桌）
            main_table_no: 主桌号

        Returns:
            合并后的主桌状态
        """
        if main_table_no not in table_nos:
            raise ValueError(f"主桌{main_table_no}不在合并列表中")

        if len(table_nos) < 2:
            raise ValueError("并桌至少需要2张桌台")

        tables_data = []
        for tn in table_nos:
            t = self._get_table(store_id, tn)
            if t["status"] not in ("free", "occupied"):
                raise ValueError(f"桌台{tn}状态为{t['status']}，无法并桌")
            tables_data.append(t)

        main_table = self._get_table(store_id, main_table_no)
        other_nos = [tn for tn in table_nos if tn != main_table_no]

        # 合并容量
        total_capacity = sum(t["capacity"] for t in tables_data)
        total_guests = sum(t["guest_count"] for t in tables_data)

        # 更新主桌
        main_table["capacity"] = total_capacity
        main_table["guest_count"] = total_guests
        main_table["merged_with"] = other_nos
        main_table["is_main_table"] = True

        # 标记副桌
        for tn in other_nos:
            t = self._get_table(store_id, tn)
            t["status"] = "occupied"
            t["is_main_table"] = False
            t["merged_with"] = [main_table_no]
            t["order_id"] = main_table.get("order_id")

        logger.info(
            "tables_merged",
            store_id=store_id,
            main_table=main_table_no,
            merged=other_nos,
            total_capacity=total_capacity,
        )

        return dict(main_table)

    def transfer_table(
        self,
        store_id: str,
        from_table: str,
        to_table: str,
    ) -> dict:
        """换桌

        将顾客从 from_table 转移到 to_table。
        from_table 必须为 occupied，to_table 必须为 free。
        """
        from_t = self._get_table(store_id, from_table)
        to_t = self._get_table(store_id, to_table)

        if from_t["status"] != "occupied":
            raise ValueError(f"源桌{from_table}状态为{from_t['status']}，需为occupied")

        if to_t["status"] != "free":
            raise ValueError(f"目标桌{to_table}状态为{to_t['status']}，需为free")

        # 转移所有状态
        to_t["status"] = "occupied"
        to_t["order_id"] = from_t["order_id"]
        to_t["guest_count"] = from_t["guest_count"]
        to_t["open_time"] = from_t["open_time"]
        to_t["waiter_id"] = from_t["waiter_id"]

        # 释放源桌
        from_t["status"] = "free"
        from_t["order_id"] = None
        from_t["guest_count"] = 0
        from_t["open_time"] = None
        from_t["waiter_id"] = None

        logger.info(
            "table_transferred",
            store_id=store_id,
            from_table=from_table,
            to_table=to_table,
        )

        return {
            "from_table": dict(from_t),
            "to_table": dict(to_t),
        }

    def get_table_stats(self, store_id: str) -> dict:
        """桌台统计

        Returns:
            {total, free, occupied, reserved, cleaning, disabled,
             settling, turnover_rate, avg_duration_min}
        """
        tables = self._get_store_tables(store_id)
        now = datetime.now(timezone.utc)

        stats = {
            "total": 0,
            "free": 0,
            "occupied": 0,
            "reserved": 0,
            "cleaning": 0,
            "settling": 0,
            "disabled": 0,
        }

        durations: list[int] = []

        for table in tables.values():
            stats["total"] += 1
            status = table["status"]
            if status in stats:
                stats[status] += 1

            if table["open_time"] and status == "occupied":
                delta = now - table["open_time"]
                durations.append(int(delta.total_seconds() / 60))

        # 翻台率 = occupied / (total - disabled) — 简化计算
        usable = stats["total"] - stats["disabled"]
        stats["occupancy_rate"] = round(
            stats["occupied"] / usable if usable > 0 else 0.0, 4
        )
        stats["avg_duration_min"] = (
            round(sum(durations) / len(durations), 1) if durations else 0
        )

        return stats
