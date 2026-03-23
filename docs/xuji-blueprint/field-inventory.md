# 蓝图字段清单 — 215+ 业务字段

> 从 wireframe-fields-v1.md 提取，按实体分组

## 字段统计

| 实体 | 字段数 | 已入 Ontology |
|------|--------|-------------|
| Order（含行/折扣/退菜/支付/券/挂账） | ~70 | 基础+23扩展 |
| Table（含卡片/详情/筛选/统计） | ~35 | 基础 |
| Dish（含分类/称重/时价） | ~25 | 基础 |
| KDS（含汇总/任务卡/异常/日志） | ~25 | 无独立模型 |
| Store（含筛选/指标/排行/预警/整改） | ~30 | 基础+6扩展 |
| 日清日结（含巡航/节点/检查/盘点） | ~30 | tx-ops 模型 |
| **合计** | **~215** | **~50 已实现** |

## 待扩展字段清单（按优先级）

### P0 — 收银必需
- Order: room_flag, customer_level, customer_tag, open_time
- OrderItem: taste_value, cook_method, served_flag, discount_flag, approval_status
- Table: min_spend, reservation_flag, reservation_time, dish_progress, pending_checkout_flag, vip_flag

### P1 — 运营必需
- KDS: ticket_id, priority_level, elapsed_time, station_name, chef_name, abnormal_type
- Store: shift_code, network_status, sync_status
- 日清日结: planned_start_time, planned_end_time, actual_start/end, check_score

### P2 — 分析增强
- Order: coupon_*, corporate_*, benefit_*
- Store: rank_*, alert_*, rectification task fields
- Dish: current_price, estimated_wait_time, taste_options, cook_method_options
