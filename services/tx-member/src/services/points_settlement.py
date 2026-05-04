"""跨店积分结算 — 月度计算门店间应付金额（fund flow）

核心架构决策（与创始人达成共识）：

  会计原则：积分负债归属"产生积分的门店"。
  当会员在 A 店产生 N 积分，A 店账上即增加 N 积分对应的 RMB 负债。
  当该会员在 B 店把 N 积分抵了 M 分（fen）现金，发生两件事：
    1. B 店以折扣形式让出了 M 分的销售额；
    2. A 店的 N 积分负债被核销（不再欠会员）。
  因此 B 店实际上"代 A 店"履行了对会员的兑现义务。
  → 月度结算时，B 店向 A 店追讨该 M 分（B 店付，A 店收）。

  当一笔抵现来自多个发行店（消费 300 积分，分别在 A/B 店产生 200/100），
  按发行店的剩余积分余额加权分配。最大债权人吃整数除法的余数（防止泄漏）。

模块定位：
  纯函数；不持有状态；不直连 DB。
  入参：当月 (tenant_id 范围内) 的 earn/spend 流水列表。
  出参：每店净头寸 + 跨店转账 ledger。

调用方：services/tx-member 月结作业（cron）+ tx-finance 应付凭证生成。

金额单位：分（fen，整数）。
"""

from __future__ import annotations

from typing import Any


def settle_cross_store(events: list[dict[str, Any]]) -> dict[str, Any]:
    """对一段周期（通常为月）的积分流水做跨店结算。

    Args:
        events: 流水事件列表，每条形如：
            {
              "direction": "earn" | "spend",
              "store_id":  str,                # 发生门店
              "points":    int,                # 积分（正整数）
              "amount_fen": int,               # earn 时为对应消费金额；spend 时为抵扣金额
              "card_id":   str (可选),         # 会员卡（精细化结算时按卡聚合，本版不要求）
            }

    Returns:
        {
          "per_store": {
              store_id: {
                  "earned_points": int,    # 当月该店产生的总积分
                  "spent_points":  int,    # 当月该店核销的总积分
                  "net_points":    int,    # 净（earned - spent，可为负）
                  "spent_offset_fen": int, # 当月该店因积分抵现让出的总金额
              }
          },
          "transfers": [
              {
                  "from_store_id": str,    # 付款方（消费门店）
                  "to_store_id":   str,    # 收款方（积分发行门店）
                  "amount_fen":    int,    # 应付金额（分，整数）
                  "rationale":     str,    # 计算依据（人话）
              }
          ],
          "warnings": list[str],           # 数据异常告警（如：有消耗但无任何发行）
        }

    设计要点：
      - 结算粒度：周期内所有 earn 视作"积分发行池"，所有 spend 视作"消费"。
      - 分配规则：每笔 spend 按当时各店发行余额加权分摊（pro-rata）。
        本版采用简化全量加权（按整周期总发行量），与会计期匹配。
      - 同店内自消化（A 产生 + A 消费）不产生跨店转账。
      - 余数：整数除法的余数分配给当前最大债权人，确保 sum(transfers)
        严格等于跨店消耗金额（防止 1 分钱"消失"）。
    """
    per_store: dict[str, dict[str, int]] = {}
    warnings: list[str] = []

    def _ensure(store_id: str) -> dict[str, int]:
        if store_id not in per_store:
            per_store[store_id] = {
                "earned_points": 0,
                "spent_points": 0,
                "spent_offset_fen": 0,
            }
        return per_store[store_id]

    # 第一遍：聚合每店总发行 / 总消耗
    for ev in events:
        direction = ev.get("direction")
        store_id = ev.get("store_id")
        points = int(ev.get("points", 0) or 0)
        amount_fen = int(ev.get("amount_fen", 0) or 0)
        if not store_id or points <= 0:
            continue
        s = _ensure(store_id)
        if direction == "earn":
            s["earned_points"] += points
        elif direction == "spend":
            s["spent_points"] += points
            s["spent_offset_fen"] += amount_fen

    # 第二遍：构建跨店转账
    transfers: list[dict[str, Any]] = []

    total_earned_by_store = {sid: s["earned_points"] for sid, s in per_store.items() if s["earned_points"] > 0}
    grand_total_earned = sum(total_earned_by_store.values())

    # 没有任何发行，但有消耗 → 数据异常告警，跳过结算
    has_spend = any(s["spent_offset_fen"] > 0 for s in per_store.values())
    if has_spend and grand_total_earned == 0:
        warnings.append("spend_without_any_earn")
    elif has_spend:
        # 对每个有抵现的消费门店，按发行店权重分配应付
        for spend_store_id, s in per_store.items():
            if s["spent_offset_fen"] <= 0:
                continue
            spend_amount = s["spent_offset_fen"]

            # 按发行店权重分配
            allocations: list[tuple[str, int]] = []
            assigned_total = 0
            # 先按权重做整数分配，余数最后给最大债权人
            for issue_store_id, earned in total_earned_by_store.items():
                # 同店内自消化不算跨店转账
                if issue_store_id == spend_store_id:
                    continue
                # 应付 = spend_amount * (earned / grand_total_earned)
                # 用整数算：(spend_amount * earned) // grand_total_earned
                portion = (spend_amount * earned) // grand_total_earned
                if portion > 0:
                    allocations.append((issue_store_id, portion))
                    assigned_total += portion

            # 计算跨店净需分配额（spend_amount 减去同店自消化部分）
            self_share = (spend_amount * total_earned_by_store.get(spend_store_id, 0)) // grand_total_earned
            cross_store_target = spend_amount - self_share

            # 处理余数：把（cross_store_target - assigned_total）分给最大债权人
            residual = cross_store_target - assigned_total
            if residual != 0 and allocations:
                # 找当前分配额最大的债权人，把余数加上去
                max_idx = max(range(len(allocations)), key=lambda i: allocations[i][1])
                store, amt = allocations[max_idx]
                allocations[max_idx] = (store, amt + residual)

            # 写入 transfers
            for to_store_id, amount_fen in allocations:
                if amount_fen <= 0:
                    continue
                transfers.append(
                    {
                        "from_store_id": spend_store_id,
                        "to_store_id": to_store_id,
                        "amount_fen": amount_fen,
                        "rationale": (
                            f"按发行权重 {total_earned_by_store[to_store_id]}/{grand_total_earned} 分摊 "
                            f"店 {spend_store_id} 当期跨店抵现 {cross_store_target} 分"
                        ),
                    }
                )

    # 补 net_points 字段
    for s in per_store.values():
        s["net_points"] = s["earned_points"] - s["spent_points"]

    return {
        "per_store": per_store,
        "transfers": transfers,
        "warnings": warnings,
    }
