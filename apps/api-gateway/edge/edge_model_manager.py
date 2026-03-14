#!/usr/bin/env python3
"""
边缘节点本地 AI 模型管理器

职责
----
1. 维护一份「期望模型清单」（从云端 API 拉取，或本地 JSON 兜底）
2. 检查本地磁盘是否已缓存对应版本；如未缓存，按优先级下载
3. 验证 SHA-256 校验和，防止断点下载导致模型损坏
4. 支持 --check / --sync / --list / --remove 等 CLI 子命令，方便运维操作
5. 定期运行（通过 edge_node_agent 调用或单独 cron）

支持的模型类型
--------------
  asr     Whisper Tiny  (ARM64 ONNX, ~75MB)
  intent  DistilBERT    (餐饮意图, ~67MB)
  tts     PaddleSpeech  (仅元数据，实际通过系统命令调用)
  decision LightGBM     (~4MB)

目录结构
--------
  /var/lib/zhilian-edge/models/
    manifest.json           <- 期望版本清单（从云端同步）
    asr/whisper-tiny/
      model.onnx
      model.sha256
    intent/distilbert-zh/
      model.onnx
      model.sha256
    decision/cost-lgb/
      model.lgb
      model.sha256
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("zhilian-model-manager")

# 默认模型基目录
_DEFAULT_MODEL_DIR = Path(os.getenv("EDGE_STATE_DIR", "/var/lib/zhilian-edge")) / "models"

# 云端 manifest 拉取端点（edge agent 注册后可获得此 URL）
_CLOUD_MANIFEST_URL = os.getenv(
    "EDGE_MODEL_MANIFEST_URL", ""
)

# 下载超时（秒）
_DOWNLOAD_TIMEOUT = 120

# 本地兜底 manifest（保证首次启动时即使没有网络也有模型描述）
_BUILTIN_MANIFEST: List[Dict] = [
    {
        "model_id": "whisper-tiny-zh",
        "model_type": "asr",
        "version": "v1.0",
        "filename": "model.onnx",
        "size_mb": 75.0,
        "sha256": "",  # 留空=跳过校验
        "download_url": "",  # 留空=不自动下载，手动放置
        "priority": 1,      # 1=最高优先下载
        "description": "Whisper Tiny ONNX for ARM64, 中文 ASR",
    },
    {
        "model_id": "distilbert-zh-intent",
        "model_type": "intent",
        "version": "v1.0",
        "filename": "model.onnx",
        "size_mb": 67.0,
        "sha256": "",
        "download_url": "",
        "priority": 2,
        "description": "餐饮场景中文意图识别 DistilBERT ONNX",
    },
    {
        "model_id": "cost-lgb-v1",
        "model_type": "decision",
        "version": "v1.0",
        "filename": "model.lgb",
        "size_mb": 4.0,
        "sha256": "",
        "download_url": "",
        "priority": 3,
        "description": "成本率决策 LightGBM",
    },
]


@dataclass
class ModelEntry:
    model_id: str
    model_type: str       # asr | intent | tts | decision
    version: str
    filename: str
    size_mb: float
    sha256: str           # 留空=跳过校验
    download_url: str     # 留空=不自动下载
    priority: int         # 小数值=高优先级
    description: str
    # 运行时填充
    local_path: str = ""
    status: str = "unknown"  # unknown | ok | missing | corrupted | downloading


class EdgeModelManager:
    def __init__(self, model_dir: Path = _DEFAULT_MODEL_DIR) -> None:
        self.model_dir = model_dir
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_file = self.model_dir / "manifest.json"
        self._manifest: List[ModelEntry] = []
        self._load_manifest()

    # ------------------------------------------------------------------ #
    #  Manifest 加载与同步
    # ------------------------------------------------------------------ #

    def _load_manifest(self) -> None:
        """优先读本地 manifest.json，找不到时用内置清单。"""
        if self._manifest_file.exists():
            try:
                raw = json.loads(self._manifest_file.read_text(encoding="utf-8"))
                self._manifest = [ModelEntry(**item) for item in raw]
                logger.info("manifest loaded from disk: %d models", len(self._manifest))
                return
            except Exception as exc:
                logger.warning("manifest load failed: %s, falling back to builtin", exc)
        self._manifest = [ModelEntry(**m) for m in _BUILTIN_MANIFEST]
        logger.info("using builtin manifest: %d models", len(self._manifest))

    def _save_manifest(self) -> None:
        data = [asdict(m) for m in self._manifest]
        self._manifest_file.write_text(
            json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8"
        )

    def sync_manifest_from_cloud(self, api_base_url: str, node_id: str, device_secret: str) -> bool:
        """从云端拉取最新模型清单（边缘节点注册后调用）。"""
        url = f"{api_base_url}/api/v1/hardware/edge-node/{node_id}/model-manifest"
        req = urllib.request.Request(
            url,
            headers={
                "X-Edge-Node-Secret": device_secret,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            if not models:
                return False
            self._manifest = [ModelEntry(**m) for m in models]
            self._save_manifest()
            logger.info("manifest synced from cloud: %d models", len(self._manifest))
            return True
        except Exception as exc:
            logger.warning("sync_manifest_from_cloud failed: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    #  本地路径计算
    # ------------------------------------------------------------------ #

    def _model_dir_for(self, entry: ModelEntry) -> Path:
        return self.model_dir / entry.model_type / entry.model_id

    def _model_file_for(self, entry: ModelEntry) -> Path:
        return self._model_dir_for(entry) / entry.filename

    def _sha256_file_for(self, entry: ModelEntry) -> Path:
        return self._model_dir_for(entry) / "model.sha256"

    # ------------------------------------------------------------------ #
    #  状态检查
    # ------------------------------------------------------------------ #

    def check(self) -> List[ModelEntry]:
        """检查所有模型的本地状态，返回带状态的 ModelEntry 列表。"""
        for entry in self._manifest:
            model_file = self._model_file_for(entry)
            entry.local_path = str(model_file)
            if not model_file.exists():
                entry.status = "missing"
                continue
            if entry.sha256 and not self._verify_sha256(model_file, entry.sha256):
                entry.status = "corrupted"
                continue
            entry.status = "ok"
        return self._manifest

    def _verify_sha256(self, path: Path, expected: str) -> bool:
        if not expected:
            return True
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        actual = h.hexdigest()
        ok = actual == expected
        if not ok:
            logger.warning("sha256 mismatch for %s: expected=%s actual=%s", path, expected[:16], actual[:16])
        return ok

    # ------------------------------------------------------------------ #
    #  下载
    # ------------------------------------------------------------------ #

    def sync(self) -> Dict[str, str]:
        """下载所有 missing/corrupted 模型，按优先级顺序。返回 {model_id: result}。"""
        results: Dict[str, str] = {}
        entries = sorted(self.check(), key=lambda e: e.priority)
        for entry in entries:
            if entry.status == "ok":
                results[entry.model_id] = "ok"
                continue
            if not entry.download_url:
                results[entry.model_id] = "no_url"
                logger.info("model %s has no download_url, skipping", entry.model_id)
                continue
            ok = self._download(entry)
            results[entry.model_id] = "downloaded" if ok else "failed"
        return results

    def _download(self, entry: ModelEntry) -> bool:
        model_dir = self._model_dir_for(entry)
        model_dir.mkdir(parents=True, exist_ok=True)
        model_file = self._model_file_for(entry)
        tmp_file = model_file.with_suffix(".tmp")
        entry.status = "downloading"
        logger.info("downloading model %s (%.1fMB) …", entry.model_id, entry.size_mb)
        try:
            start = time.time()
            urllib.request.urlretrieve(entry.download_url, str(tmp_file))
            elapsed = time.time() - start
            # 校验
            if entry.sha256 and not self._verify_sha256(tmp_file, entry.sha256):
                tmp_file.unlink(missing_ok=True)
                entry.status = "corrupted"
                logger.error("model %s download corrupted", entry.model_id)
                return False
            tmp_file.rename(model_file)
            # 写入 sha256 文件
            if entry.sha256:
                self._sha256_file_for(entry).write_text(entry.sha256, encoding="utf-8")
            entry.status = "ok"
            logger.info(
                "model %s downloaded ok size=%.1fMB elapsed=%.1fs",
                entry.model_id, entry.size_mb, elapsed,
            )
            return True
        except Exception as exc:
            tmp_file.unlink(missing_ok=True)
            entry.status = "failed"
            logger.error("download model %s failed: %s", entry.model_id, exc)
            return False

    # ------------------------------------------------------------------ #
    #  删除（磁盘清理）
    # ------------------------------------------------------------------ #

    def remove(self, model_id: str) -> bool:
        for entry in self._manifest:
            if entry.model_id == model_id:
                model_file = self._model_file_for(entry)
                if model_file.exists():
                    model_file.unlink()
                    logger.info("removed model file %s", model_file)
                sha_file = self._sha256_file_for(entry)
                if sha_file.exists():
                    sha_file.unlink()
                return True
        return False

    # ------------------------------------------------------------------ #
    #  状态摘要（供 edge_node_agent 上报给云端）
    # ------------------------------------------------------------------ #

    def status_summary(self) -> Dict:
        entries = self.check()
        return {
            "total": len(entries),
            "ok": sum(1 for e in entries if e.status == "ok"),
            "missing": sum(1 for e in entries if e.status == "missing"),
            "corrupted": sum(1 for e in entries if e.status == "corrupted"),
            "models": [
                {
                    "model_id": e.model_id,
                    "model_type": e.model_type,
                    "version": e.version,
                    "status": e.status,
                    "size_mb": e.size_mb,
                }
                for e in entries
            ],
        }


# ------------------------------------------------------------------ #
#  CLI 入口
# ------------------------------------------------------------------ #

def _cli() -> int:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="屯象OS 边缘节点本地模型管理器")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出所有模型及其状态")
    sub.add_parser("check", help="检查本地模型完整性")
    sub.add_parser("sync", help="下载缺失或损坏的模型")

    rm_p = sub.add_parser("remove", help="删除指定模型的本地文件")
    rm_p.add_argument("model_id", help="模型ID")

    sub.add_parser("status", help="输出 JSON 状态摘要（供 edge agent 调用）")

    args = parser.parse_args()

    mgr = EdgeModelManager()

    if args.cmd == "list" or args.cmd == "check" or args.cmd is None:
        entries = mgr.check()
        print(f"{'ID':<30} {'TYPE':<10} {'VER':<8} {'STATUS':<12} {'SIZE(MB)':<10}")
        print("-" * 72)
        for e in entries:
            print(f"{e.model_id:<30} {e.model_type:<10} {e.version:<8} {e.status:<12} {e.size_mb:<10.1f}")
        missing = [e for e in entries if e.status != "ok"]
        if missing:
            print(f"\n⚠️  {len(missing)} 个模型需要同步，运行 `sync` 命令下载。")
        return 0

    if args.cmd == "sync":
        results = mgr.sync()
        for mid, result in results.items():
            symbol = "✅" if result in ("ok", "downloaded") else "❌"
            print(f"{symbol} {mid}: {result}")
        return 0

    if args.cmd == "remove":
        ok = mgr.remove(args.model_id)
        print("已删除" if ok else f"未找到模型 {args.model_id}")
        return 0 if ok else 1

    if args.cmd == "status":
        import json as _json
        print(_json.dumps(mgr.status_summary(), ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
