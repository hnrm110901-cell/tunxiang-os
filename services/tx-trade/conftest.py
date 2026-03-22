"""conftest.py — 将项目根目录和 src 目录加入 Python path"""
import sys
import os

# 项目根目录（shared/ 所在位置）
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(os.path.dirname(__file__), "src")

for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)
