"""积分批次 FIFO 消费 + 过期清理（纯函数）

设计原则：
  - 积分按批次发行（每次 earn 创建一条 batch）
  - 消费时优先扣除最早的批次（FIFO）→ 让"老积分"先用掉，减少过期损失
  - 清理时按 earned_at 升序处理，明细可审计
  - 全部纯函数，无 DB 依赖；批次列表通过引用就地修改

batch dict 形态约定：
    {
      "batch_id":         str,
      "earned_at":        datetime,
      "expiry_date":      datetime,
      "remaining_points": int,    # >=0
      "cleared":          bool,   # True 表示已被过期清零
    }

为什么独立于 points_expiry.py：
  原 points_expiry.py 用模块级内存 dict 管理批次，难做单元测试和注入。
  本模块只接受批次列表参数，可被 service 层用任意持久化策略调用
  （内存 / DB / 事件回放）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

DEFAULT_VALIDITY_DAYS = 365  # 12 个月


def clear_expired_batches_fifo(
    batches: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    """按 FIFO（earned_at 升序）清零所有已过期且仍有余额的批次。

    就地修改 batches 列表中的字典：
      - remaining_points → 0
      - cleared → True

    Args:
        batches: 批次列表
        now:     当前时间（UTC，便于测试注入）

    Returns:
        {
          "cleared_count":  int,
          "cleared_points": int,
          "details": [{"batch_id", "cleared_points", "expiry_date"}, ...],
        }
    """
    # FIFO：earned_at 升序
    sorted_batches = sorted(batches, key=lambda b: b.get("earned_at"))

    cleared_count = 0
    cleared_points = 0
    details: list[dict[str, Any]] = []

    for batch in sorted_batches:
        if batch.get("cleared"):
            continue
        remaining = int(batch.get("remaining_points", 0) or 0)
        if remaining <= 0:
            continue
        expiry_date = batch.get("expiry_date")
        if expiry_date is None:
            continue
        if not isinstance(expiry_date, datetime):
            # 容错：字符串解析
            try:
                expiry_date = datetime.fromisoformat(str(expiry_date))
            except ValueError:
                continue
        if now < expiry_date:
            continue

        batch["remaining_points"] = 0
        batch["cleared"] = True
        cleared_count += 1
        cleared_points += remaining
        details.append(
            {
                "batch_id": batch.get("batch_id"),
                "cleared_points": remaining,
                "expiry_date": expiry_date.isoformat(),
            }
        )

    return {
        "cleared_count": cleared_count,
        "cleared_points": cleared_points,
        "details": details,
    }


def consume_points_fifo(
    batches: list[dict[str, Any]],
    points_to_spend: int,
) -> dict[str, Any]:
    """按 FIFO 顺序扣减积分（最早批次先扣）。

    全或无：余额不足时整体回滚（抛 ValueError），不留半状态。

    Args:
        batches: 批次列表
        points_to_spend: 拟扣减积分（正整数）

    Returns:
        {
          "spent": int,
          "consumed_from": [
              {"batch_id": str, "points": int},  # 每个批次实扣
              ...
          ],
        }

    Raises:
        ValueError("insufficient_points") 余额不足时
        ValueError("invalid_amount")     points_to_spend <= 0 时
    """
    if not isinstance(points_to_spend, int) or points_to_spend <= 0:
        raise ValueError("invalid_amount")

    # 仅看可消费批次（未清零、有余额）
    valid = [
        b
        for b in batches
        if not b.get("cleared") and int(b.get("remaining_points", 0) or 0) > 0
    ]
    available = sum(int(b.get("remaining_points", 0) or 0) for b in valid)
    if available < points_to_spend:
        raise ValueError("insufficient_points")

    # FIFO 排序
    sorted_valid = sorted(valid, key=lambda b: b.get("earned_at"))

    # 先 plan 再 commit，避免半状态
    plan: list[tuple[dict[str, Any], int]] = []
    remaining_to_spend = points_to_spend
    for batch in sorted_valid:
        if remaining_to_spend <= 0:
            break
        rem = int(batch.get("remaining_points", 0) or 0)
        take = min(rem, remaining_to_spend)
        plan.append((batch, take))
        remaining_to_spend -= take

    # commit
    consumed_from = []
    for batch, take in plan:
        batch["remaining_points"] = int(batch["remaining_points"]) - take
        consumed_from.append({"batch_id": batch.get("batch_id"), "points": take})

    return {
        "spent": points_to_spend,
        "consumed_from": consumed_from,
    }
