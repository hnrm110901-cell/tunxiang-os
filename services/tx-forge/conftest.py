"""conftest.py — 本地测试路径配置

策略：
  1. ROOT 加入 path → shared.ontology 等
  2. SRC_DIR 加入 path → src.api / src.services 等裸 import
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(os.path.dirname(__file__), "src")

for p in [ROOT, SRC_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
