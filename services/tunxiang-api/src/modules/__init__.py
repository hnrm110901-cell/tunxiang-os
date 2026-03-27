"""模块层 — 只做 import re-export，不写新逻辑

每个子目录对应一个未来可独立部署的微服务边界：
  trade/   — 交易履约 (原 tx-trade + tx-menu + tx-member + tx-finance)
  ops/     — 组织运营 (原 tx-org + tx-supply + tx-ops)
  brain/   — AI智能   (原 tx-agent + tx-analytics + tx-growth + tx-intel)
  gateway/ — 网关认证 (原 gateway)
"""
