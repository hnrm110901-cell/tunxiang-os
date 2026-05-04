"""conftest.py — 本地测试路径配置

容器路径：/app/services/tx_pay/src/  PYTHONPATH=/app
本地路径：services/tx-pay/src/       (目录名含 dash)

策略：
  1. ROOT 加入 path   → shared.* 等跨服务包
  2. SVC_DIR 加入 path → from src.api.xxx import 等
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SVC_DIR = os.path.dirname(__file__)       # services/tx-pay/
SRC_DIR = os.path.join(SVC_DIR, "src")    # services/tx-pay/src/

for p in [ROOT, SVC_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
