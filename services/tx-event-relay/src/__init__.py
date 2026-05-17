"""tx-event-relay — 真 Outbox relay worker (W3 P0 issue #757).

战略 plan §4 举措 3 "真 Outbox": 独立 worker 异步 polling trade_event_outbox 表,
shadow mode 期间仅 log + metrics, W11 follow-up 切真路径投递到 events 表 + Redis Stream.

端口 :8020 (创始人 Q2 决议, base.yml 8000-8019 全占).
"""
