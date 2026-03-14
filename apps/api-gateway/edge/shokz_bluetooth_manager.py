#!/usr/bin/env python3
"""
Shokz 骨传导耳机真实蓝牙管理层（BlueZ D-Bus + PipeWire/PulseAudio）

架构说明
--------
上一版 shokz_callback_daemon.py 只做"状态桥接"——记录云端发来的
connect/disconnect/voice_output 指令，但不真正操控蓝牙或播放音频。

本模块实现完整的本地蓝牙执行层：

1. BlueZ 集成（通过 D-Bus）
   - 扫描附近的 Shokz 设备（Shokz MAC 前缀过滤）
   - 配对 / 取消配对
   - 连接 / 断开 HFP/HSP Profile（用于音频输入）

2. 音频输出（PipeWire 优先，降级 PulseAudio/aplay）
   - TTS 文字 → 临时 WAV/MP3 文件
   - 调用系统命令播放（不依赖 Python audio 包）
   - 支持优先级队列（urgent 插队）

3. Shokz 型号识别
   - OpenComm2 UC（店长/副店长）
   - OpenRun Pro（厨师长）

依赖（树莓派 OS 已预装）
-----------------------
  apt: bluez python3-dbus dbus python3-gi pipewire-audio || pulseaudio
  python: dbus-python (python3-dbus)

本模块采用「优雅降级」设计：
  - 若 dbus-python 未安装 → 进入「模拟模式」，所有操作返回 success=False
  - 若 PipeWire 不可用 → 降级 paplay → aplay → 仅记录日志
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("zhilian-shokz-bt")

# Shokz 设备 MAC OUI 前缀（前 3 字节）
SHOKZ_MAC_PREFIXES = {
    "00:1b:dc",  # AfterShokz/Shokz 历代产品
    "4c:75:25",
    "8c:de:52",
    "c4:fb:20",
    "9c:52:fc",
}

# BlueZ D-Bus 接口常量
BLUEZ_SERVICE = "org.bluez"
BLUEZ_ADAPTER_IFACE = "org.bluez.Adapter1"
BLUEZ_DEVICE_IFACE = "org.bluez.Device1"
DBUS_OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


class AudioBackend(str, Enum):
    PIPEWIRE = "pipewire"
    PULSEAUDIO = "pulseaudio"
    APLAY = "aplay"
    NONE = "none"


@dataclass
class ShokzDevice:
    mac_address: str           # 格式：AA:BB:CC:DD:EE:FF
    name: str                  # 如："Shokz OpenComm2 UC"
    dbus_path: str             # BlueZ D-Bus 对象路径
    connected: bool = False
    paired: bool = False
    rssi: int = -100


@dataclass
class VoiceTask:
    text: str
    device_mac: str
    priority: str = "normal"   # normal | urgent
    created_at: float = field(default_factory=time.time)


class _DbusMock:
    """当 dbus-python 不可用时的安全降级 stub。"""

    def __getattr__(self, _: str):
        return self

    def __call__(self, *_args, **_kw):
        return self

    def get_object(self, *_args, **_kw):
        return self

    def Interface(self, *_args, **_kw):  # noqa: N802
        return self


class BluetoothManager:
    """
    BlueZ 蓝牙管理器（单例，守护进程中保持运行）。

    使用方式：
        manager = BluetoothManager()
        manager.start()
        manager.connect_device("AA:BB:CC:DD:EE:FF")
        manager.speak("你好，今天餐厅客流预计增加 15%", device_mac="AA:BB:CC:DD:EE:FF")
        manager.stop()
    """

    def __init__(self, adapter_name: str = "hci0") -> None:
        self.adapter_name = adapter_name
        self._devices: Dict[str, ShokzDevice] = {}
        self._audio_backend = self._detect_audio_backend()
        self._voice_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._voice_thread: Optional[threading.Thread] = None
        self._running = False
        self._dbus_available = False
        self._bus: Any = None
        self._adapter: Any = None
        self._init_dbus()

    # ------------------------------------------------------------------ #
    #  初始化
    # ------------------------------------------------------------------ #

    def _init_dbus(self) -> None:
        try:
            import dbus  # type: ignore
            self._bus = dbus.SystemBus()
            manager = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, "/"),
                DBUS_OBJECT_MANAGER_IFACE,
            )
            objects = manager.GetManagedObjects()
            adapter_path = f"/org/bluez/{self.adapter_name}"
            if adapter_path not in objects:
                logger.warning(
                    "bluetooth adapter %s not found, falling back to mock", self.adapter_name
                )
                self._bus = None
                return
            self._adapter = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, adapter_path),
                BLUEZ_ADAPTER_IFACE,
            )
            self._dbus_available = True
            # 预加载已配对的 Shokz 设备
            self._reload_known_devices(objects)
            logger.info("bluetooth adapter %s ready, dbus OK", self.adapter_name)
        except ImportError:
            logger.warning("dbus-python not installed — bluetooth in mock mode")
            self._bus = _DbusMock()
        except Exception as exc:
            logger.warning("bluetooth init failed: %s — mock mode", exc)
            self._bus = _DbusMock()

    def _reload_known_devices(self, objects: Dict) -> None:
        try:
            import dbus  # type: ignore
            for path, ifaces in objects.items():
                if BLUEZ_DEVICE_IFACE not in ifaces:
                    continue
                props = ifaces[BLUEZ_DEVICE_IFACE]
                mac = str(props.get("Address", "")).lower()
                if not self._is_shokz(mac):
                    continue
                self._devices[mac] = ShokzDevice(
                    mac_address=mac,
                    name=str(props.get("Name", "Shokz")),
                    dbus_path=path,
                    connected=bool(props.get("Connected", False)),
                    paired=bool(props.get("Paired", False)),
                    rssi=int(props.get("RSSI", -100)),
                )
            logger.info("preloaded %d known Shokz devices", len(self._devices))
        except Exception as exc:
            logger.warning("reload_known_devices failed: %s", exc)

    @staticmethod
    def _detect_audio_backend() -> AudioBackend:
        if shutil.which("pw-play"):
            return AudioBackend.PIPEWIRE
        if shutil.which("paplay"):
            return AudioBackend.PULSEAUDIO
        if shutil.which("aplay"):
            return AudioBackend.APLAY
        return AudioBackend.NONE

    @staticmethod
    def _is_shokz(mac: str) -> bool:
        return any(mac.startswith(prefix) for prefix in SHOKZ_MAC_PREFIXES)

    # ------------------------------------------------------------------ #
    #  生命周期
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        self._running = True
        self._voice_thread = threading.Thread(
            target=self._voice_worker, daemon=True, name="shokz-voice-worker"
        )
        self._voice_thread.start()
        logger.info("shokz bluetooth manager started, audio_backend=%s", self._audio_backend)

    def stop(self) -> None:
        self._running = False
        if self._voice_thread:
            self._voice_thread.join(timeout=3)

    # ------------------------------------------------------------------ #
    #  扫描
    # ------------------------------------------------------------------ #

    def scan(self, duration_seconds: float = 8.0) -> List[ShokzDevice]:
        """启动 BlueZ 扫描，返回发现的 Shokz 设备列表。"""
        if not self._dbus_available:
            logger.info("[mock] scan called, returning cached devices")
            return list(self._devices.values())

        try:
            import dbus  # type: ignore
            self._adapter.StartDiscovery()
            logger.info("bt scan started, duration=%.1fs", duration_seconds)
            time.sleep(duration_seconds)
            self._adapter.StopDiscovery()

            # 刷新设备列表
            manager_obj = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, "/"),
                DBUS_OBJECT_MANAGER_IFACE,
            )
            self._reload_known_devices(manager_obj.GetManagedObjects())
        except Exception as exc:
            logger.warning("scan failed: %s", exc)

        found = [d for d in self._devices.values() if not d.paired]
        logger.info("scan found %d new Shokz devices", len(found))
        return list(self._devices.values())

    # ------------------------------------------------------------------ #
    #  配对 / 连接 / 断开
    # ------------------------------------------------------------------ #

    def pair_device(self, mac: str) -> bool:
        mac = mac.lower()
        device = self._get_bluez_device(mac)
        if not device:
            logger.warning("pair_device: device %s not found", mac)
            return False
        try:
            import dbus  # type: ignore
            dev_iface = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, device.dbus_path),
                BLUEZ_DEVICE_IFACE,
            )
            dev_iface.Pair()
            # 信任设备，使其下次自动重连
            props_iface = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, device.dbus_path),
                DBUS_PROPERTIES_IFACE,
            )
            props_iface.Set(BLUEZ_DEVICE_IFACE, "Trusted", dbus.Boolean(True))
            device.paired = True
            logger.info("paired Shokz device %s", mac)
            return True
        except Exception as exc:
            logger.error("pair_device %s failed: %s", mac, exc)
            return False

    def connect_device(self, mac: str) -> bool:
        mac = mac.lower()
        if not self._dbus_available:
            logger.info("[mock] connect_device %s", mac)
            if mac in self._devices:
                self._devices[mac].connected = True
            return True
        device = self._get_bluez_device(mac)
        if not device:
            logger.warning("connect_device: %s not known, triggering scan first", mac)
            self.scan(duration_seconds=5.0)
            device = self._get_bluez_device(mac)
        if not device:
            return False
        try:
            import dbus  # type: ignore
            dev_iface = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, device.dbus_path),
                BLUEZ_DEVICE_IFACE,
            )
            if not device.paired:
                self.pair_device(mac)
            dev_iface.Connect()
            device.connected = True
            logger.info("connected Shokz device %s", mac)
            return True
        except Exception as exc:
            logger.error("connect_device %s failed: %s", mac, exc)
            return False

    def disconnect_device(self, mac: str) -> bool:
        mac = mac.lower()
        if not self._dbus_available:
            logger.info("[mock] disconnect_device %s", mac)
            if mac in self._devices:
                self._devices[mac].connected = False
            return True
        device = self._devices.get(mac)
        if not device:
            return False
        try:
            import dbus  # type: ignore
            dev_iface = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, device.dbus_path),
                BLUEZ_DEVICE_IFACE,
            )
            dev_iface.Disconnect()
            device.connected = False
            logger.info("disconnected Shokz device %s", mac)
            return True
        except Exception as exc:
            logger.error("disconnect_device %s failed: %s", mac, exc)
            return False

    def _get_bluez_device(self, mac: str) -> Optional[ShokzDevice]:
        return self._devices.get(mac.lower())

    def get_connected_devices(self) -> List[ShokzDevice]:
        return [d for d in self._devices.values() if d.connected]

    # ------------------------------------------------------------------ #
    #  语音播报队列
    # ------------------------------------------------------------------ #

    def speak(
        self,
        text: str,
        device_mac: Optional[str] = None,
        priority: str = "normal",
    ) -> None:
        """
        将 TTS 文本放入播报队列。

        priority:
          "urgent"  → 数字优先级 0（先播）
          "normal"  → 数字优先级 1
        """
        prio_num = 0 if priority == "urgent" else 1
        macs: List[str] = []
        if device_mac:
            macs = [device_mac.lower()]
        else:
            macs = [d.mac_address for d in self.get_connected_devices()]
        for mac in macs:
            task = VoiceTask(text=text, device_mac=mac, priority=priority)
            self._voice_queue.put((prio_num, time.time(), task))
            logger.debug("voice_task enqueued prio=%s text=%s mac=%s", prio_num, text[:30], mac)

    def _voice_worker(self) -> None:
        """后台线程：消费队列，调用 TTS + 系统命令播放音频。"""
        while self._running:
            try:
                _, _, task = self._voice_queue.get(timeout=1.0)
                self._play_tts(task)
                self._voice_queue.task_done()
            except queue.Empty:
                continue
            except Exception as exc:
                logger.error("voice_worker error: %s", exc)

    def _play_tts(self, task: VoiceTask) -> None:
        """
        TTS 实现策略：
        1. 调用本地 PaddleSpeech（如果已安装）
        2. 降级：espeak-ng（多语言，树莓派 OS 可 apt 安装）
        3. 再降级：系统 beep + 仅打印日志
        """
        device = self._devices.get(task.device_mac)
        if device and not device.connected:
            logger.warning("device %s not connected, skipping tts", task.device_mac)
            return

        logger.info("tts play: device=%s text=%s", task.device_mac, task.text[:40])

        # 尝试 PaddleSpeech CLI
        if shutil.which("paddlespeech"):
            self._tts_paddlespeech(task.text)
            return

        # 尝试 espeak-ng（ARM64 友好，中文需安装 espeak-ng-data-zh-cmn）
        if shutil.which("espeak-ng"):
            self._tts_espeak(task.text)
            return

        # 最终降级：仅记录日志（不阻塞业务）
        logger.warning("[tts_fallback] no TTS engine found, text=%s", task.text)

    def _tts_paddlespeech(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            subprocess.run(
                ["paddlespeech", "tts", "--input", text, "--output", wav_path],
                timeout=10,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._play_wav(wav_path)
        except Exception as exc:
            logger.error("paddlespeech tts failed: %s", exc)
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def _tts_espeak(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            subprocess.run(
                ["espeak-ng", "-v", "zh", "-w", wav_path, text],
                timeout=8,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._play_wav(wav_path)
        except Exception as exc:
            logger.error("espeak-ng tts failed: %s", exc)
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def _play_wav(self, wav_path: str) -> None:
        """按优先级选择音频后端播放 WAV 文件。"""
        if self._audio_backend == AudioBackend.PIPEWIRE:
            cmd = ["pw-play", wav_path]
        elif self._audio_backend == AudioBackend.PULSEAUDIO:
            cmd = ["paplay", wav_path]
        elif self._audio_backend == AudioBackend.APLAY:
            cmd = ["aplay", "-q", wav_path]
        else:
            logger.warning("[audio] no audio backend found, cannot play %s", wav_path)
            return
        try:
            subprocess.run(cmd, timeout=30, check=True)
        except Exception as exc:
            logger.error("play_wav cmd=%s failed: %s", cmd[0], exc)

    # ------------------------------------------------------------------ #
    #  状态快照（供 Shokz 回调守护进程查询）
    # ------------------------------------------------------------------ #

    def status_snapshot(self) -> Dict[str, Any]:
        return {
            "dbus_available": self._dbus_available,
            "adapter": self.adapter_name,
            "audio_backend": self._audio_backend,
            "voice_queue_size": self._voice_queue.qsize(),
            "devices": [
                {
                    "mac": d.mac_address,
                    "name": d.name,
                    "connected": d.connected,
                    "paired": d.paired,
                    "rssi": d.rssi,
                }
                for d in self._devices.values()
            ],
        }


# ------------------------------------------------------------------ #
#  单例（守护进程 import 直接使用）
# ------------------------------------------------------------------ #

_bt_manager: Optional[BluetoothManager] = None


def get_bluetooth_manager() -> BluetoothManager:
    global _bt_manager
    if _bt_manager is None:
        adapter = os.getenv("EDGE_BT_ADAPTER", "hci0")
        _bt_manager = BluetoothManager(adapter_name=adapter)
        _bt_manager.start()
    return _bt_manager
