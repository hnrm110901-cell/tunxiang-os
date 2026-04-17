"""
D10 多打卡方式服务 — Should-Fix P1

支持五种打卡方式：
  - GPS：Haversine 距离<200m 验证
  - WiFi：SSID 白名单匹配
  - Face：人脸识别（SDK 预留接入点，当前 mock 通过）
  - QRCode：动态码 30 秒 TTL
  - Manual：店长代打卡，标记 needs_approval=True

所有打卡写入 AttendancePunch；GPS/WIFI 验证失败将 verified=False 并保留证据。
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.attendance_punch import AttendancePunch, PunchDirection, PunchMethod

logger = structlog.get_logger()


# 默认 GPS 半径阈值（米）
DEFAULT_GPS_RADIUS_METERS = 200
# 二维码 TTL（秒）
QRCODE_TTL_SECONDS = 30


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine 公式计算两个经纬度点之间的距离（米）

    纯算法实现，不引入外部库。
    """
    R = 6_371_000.0  # 地球半径（米）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class AttendancePunchService:
    """多方式打卡服务"""

    # ───────────── 验证器（可单独测试）─────────────

    def verify_gps(
        self,
        employee_lat: float,
        employee_lng: float,
        store_lat: float,
        store_lng: float,
        radius_meters: int = DEFAULT_GPS_RADIUS_METERS,
    ) -> Dict[str, Any]:
        """GPS 位置校验"""
        distance = haversine_meters(employee_lat, employee_lng, store_lat, store_lng)
        ok = distance <= radius_meters
        return {
            "verified": ok,
            "distance_meters": round(distance, 2),
            "radius_meters": radius_meters,
        }

    def verify_wifi(self, ssid: str, allowed_ssids: list[str]) -> Dict[str, Any]:
        ok = bool(ssid) and ssid in (allowed_ssids or [])
        return {"verified": ok, "ssid": ssid}

    def verify_face(self, face_token: Optional[str]) -> Dict[str, Any]:
        """人脸识别 — SDK 接入点预留。当前 mock：只要存在 face_token 即视为通过。

        TODO(真实接入)：替换为 face_sdk.verify(face_token, employee_id)
        """
        ok = bool(face_token)
        return {"verified": ok, "face_score": 0.95 if ok else 0.0, "mock": True}

    def verify_qrcode(self, code: str, issued_at_epoch: Optional[float]) -> Dict[str, Any]:
        if not code or not issued_at_epoch:
            return {"verified": False, "reason": "missing_code_or_timestamp"}
        age = time.time() - float(issued_at_epoch)
        if age < 0 or age > QRCODE_TTL_SECONDS:
            return {"verified": False, "reason": "expired", "age_seconds": round(age, 2)}
        return {"verified": True, "age_seconds": round(age, 2)}

    # ───────────── 主入口 ─────────────

    async def punch(
        self,
        employee_id: str,
        store_id: str,
        method: PunchMethod,
        direction: PunchDirection,
        payload: Dict[str, Any],
        db: AsyncSession,
        shift_id: Optional[str] = None,
    ) -> AttendancePunch:
        """统一打卡入口"""
        verified = False
        remark: Optional[str] = None
        needs_approval = False
        lat = payload.get("lat")
        lng = payload.get("lng")

        if method == PunchMethod.GPS:
            store_lat = payload.get("store_lat")
            store_lng = payload.get("store_lng")
            if lat is None or lng is None or store_lat is None or store_lng is None:
                raise ValueError("GPS 打卡缺少坐标")
            v = self.verify_gps(
                float(lat), float(lng), float(store_lat), float(store_lng),
                radius_meters=int(payload.get("radius_meters", DEFAULT_GPS_RADIUS_METERS)),
            )
            verified = v["verified"]
            remark = f"distance={v['distance_meters']}m"

        elif method == PunchMethod.WIFI:
            v = self.verify_wifi(payload.get("ssid", ""), payload.get("allowed_ssids", []))
            verified = v["verified"]
            remark = f"ssid={v['ssid']}"

        elif method == PunchMethod.FACE:
            v = self.verify_face(payload.get("face_token"))
            verified = v["verified"]
            remark = f"face_score={v.get('face_score')}"

        elif method == PunchMethod.QRCODE:
            v = self.verify_qrcode(payload.get("code"), payload.get("issued_at_epoch"))
            verified = v["verified"]
            remark = v.get("reason") or f"age={v.get('age_seconds')}s"

        elif method == PunchMethod.MANUAL:
            # 店长代打卡：默认未校验，需要二级审批
            verified = False
            needs_approval = True
            remark = f"manual_by={payload.get('operator_id', 'unknown')}"

        else:
            raise ValueError(f"不支持的打卡方式: {method}")

        punch = AttendancePunch(
            id=uuid.uuid4(),
            employee_id=employee_id,
            store_id=store_id,
            punch_at=datetime.utcnow(),
            direction=direction.value,
            method=method.value,
            payload_json=payload,
            location_lat=lat,
            location_lng=lng,
            verified=verified,
            verify_remark=remark,
            shift_id=uuid.UUID(shift_id) if shift_id else None,
            needs_approval=needs_approval,
        )
        db.add(punch)
        await db.commit()
        await db.refresh(punch)
        logger.info(
            "attendance.punched",
            emp=employee_id,
            method=method.value,
            verified=verified,
            direction=direction.value,
        )
        return punch

    async def punch_in(
        self,
        employee_id: str,
        store_id: str,
        method: PunchMethod,
        payload: Dict[str, Any],
        db: AsyncSession,
        shift_id: Optional[str] = None,
    ) -> AttendancePunch:
        return await self.punch(
            employee_id, store_id, method, PunchDirection.IN, payload, db, shift_id
        )

    async def punch_out(
        self,
        employee_id: str,
        store_id: str,
        method: PunchMethod,
        payload: Dict[str, Any],
        db: AsyncSession,
        shift_id: Optional[str] = None,
    ) -> AttendancePunch:
        return await self.punch(
            employee_id, store_id, method, PunchDirection.OUT, payload, db, shift_id
        )

    async def list_punches(
        self,
        employee_id: Optional[str],
        store_id: Optional[str],
        db: AsyncSession,
        limit: int = 100,
    ) -> list[AttendancePunch]:
        stmt = select(AttendancePunch).order_by(AttendancePunch.punch_at.desc()).limit(limit)
        if employee_id:
            stmt = stmt.where(AttendancePunch.employee_id == employee_id)
        if store_id:
            stmt = stmt.where(AttendancePunch.store_id == store_id)
        return list((await db.execute(stmt)).scalars().all())


attendance_punch_service = AttendancePunchService()
