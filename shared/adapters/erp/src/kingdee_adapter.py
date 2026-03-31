"""金蝶 K3/Cloud ERP 适配器

认证：HMAC-SHA256 签名（App ID + App Secret + 时间戳 + 随机数）
凭证推送：POST /ierp/api/v2/gl/vouchers/save
科目同步：GET  /ierp/api/v2/bd/account/getAll

环境变量：
  KINGDEE_APP_ID       — 金蝶开放平台 App ID
  KINGDEE_APP_SECRET   — 金蝶开放平台 App Secret
  KINGDEE_BASE_URL     — 金蝶 Cloud 实例地址，如 https://xxx.kingdeecloud.com
  KINGDEE_ENTITY_ID    — 账套 ID（金蝶多账套场景必填）
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

import httpx
import structlog

from .base import (
    ERPAccount,
    ERPAdapter,
    ERPPushResult,
    ERPType,
    ERPVoucher,
    PushStatus,
)

log = structlog.get_logger(__name__)

# 金蝶标准科目表（K3 Cloud 默认科目编码，租户可在 tenant_config 中覆盖）
_KINGDEE_DEFAULT_ACCOUNTS: list[dict[str, Any]] = [
    {"code": "1001", "name": "库存现金",     "account_type": "资产"},
    {"code": "1002", "name": "银行存款",     "account_type": "资产"},
    {"code": "1012.01", "name": "微信收款",  "account_type": "资产"},
    {"code": "1012.02", "name": "支付宝收款","account_type": "资产"},
    {"code": "1122", "name": "应收账款",     "account_type": "资产"},
    {"code": "1403", "name": "原材料",       "account_type": "资产"},
    {"code": "1405", "name": "库存商品",     "account_type": "资产"},
    {"code": "1406", "name": "在途物资",     "account_type": "资产"},
    {"code": "2202", "name": "应付账款",     "account_type": "负债"},
    {"code": "2211", "name": "应付职工薪酬", "account_type": "负债"},
    {"code": "5001", "name": "主营业务收入", "account_type": "收入"},
    {"code": "5401", "name": "主营业务成本", "account_type": "费用"},
    {"code": "5602", "name": "管理费用",     "account_type": "费用"},
]


class KingdeeAdapter(ERPAdapter):
    """金蝶 K3/Cloud 适配器

    复用 kingdee_bridge.py 中已验证的签名逻辑，扩展为完整的适配器接口。
    签名算法：HMAC-SHA256(app_secret, app_id + timestamp + nonce + body_sha256)
    """

    def __init__(self) -> None:
        self._app_id = os.environ["KINGDEE_APP_ID"]
        self._app_secret = os.environ["KINGDEE_APP_SECRET"]
        self._base_url = os.environ["KINGDEE_BASE_URL"].rstrip("/")
        # 账套 ID（可选，单账套场景可不配）
        self._entity_id = os.environ.get("KINGDEE_ENTITY_ID", "")
        self._client = httpx.AsyncClient(timeout=30)

    # ─── 签名工具 ─────────────────────────────────────────────────────────

    def _sign(self, timestamp: str, nonce: str, body: str) -> str:
        """生成金蝶 Cloud Open API 签名

        签名字符串 = app_id + timestamp + nonce + SHA256(body)
        签名算法   = HMAC-SHA256(app_secret, 签名字符串)
        """
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        sign_str = self._app_id + timestamp + nonce + body_hash
        return hmac.new(
            self._app_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _build_headers(self, body: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex[:16]
        return {
            "Content-Type": "application/json",
            "X-App-Id": self._app_id,
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Sign": self._sign(timestamp, nonce, body),
            "X-Entity-Id": self._entity_id,
        }

    # ─── 内部请求 ─────────────────────────────────────────────────────────

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False)
        headers = self._build_headers(body)
        url = f"{self._base_url}{path}"
        log.debug("kingdee.request", url=url, payload_size=len(body))
        resp = await self._client.post(url, content=body, headers=headers)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        # 金蝶 Cloud API 以 data.Result.Result 表示成功
        result_flag = (
            data.get("Result", {}).get("Result", False)
            if isinstance(data.get("Result"), dict)
            else data.get("success", False)
        )
        if not result_flag:
            error_msg = (
                data.get("Result", {}).get("Message", "")
                or data.get("Message", "未知错误")
            )
            raise RuntimeError(f"金蝶API业务错误: {error_msg}")
        return data

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        body = ""
        headers = self._build_headers(body)
        resp = await self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ─── 凭证格式转换 ─────────────────────────────────────────────────────

    def _to_kingdee_payload(self, voucher: ERPVoucher) -> dict[str, Any]:
        """将屯象统一凭证格式转换为金蝶 Cloud 凭证接口格式"""
        entries = []
        for idx, entry in enumerate(voucher.entries, start=1):
            entries.append({
                "FEntryID": idx,
                "FAccountID": {"FNumber": entry.account_code},
                "FDEBIT": entry.debit_fen / 100,   # 分 → 元
                "FCREDIT": entry.credit_fen / 100,
                "FEXPLANATION": entry.summary,
            })

        return {
            "Model": {
                "FVoucherGroupID": {"FNumber": voucher.voucher_type.value},
                "FDate": voucher.business_date.isoformat(),
                "FAttachments": 0,
                "FNote": voucher.memo or f"屯象OS自动生成: {voucher.source_type}#{voucher.source_id}",
                "FBillEntry": entries,
                # 屯象内部 ID 写入备注扩展字段（便于对账）
                "FDescription": voucher.voucher_id,
            }
        }

    # ─── 接口实现 ─────────────────────────────────────────────────────────

    async def push_voucher(self, voucher: ERPVoucher) -> ERPPushResult:
        """推送凭证到金蝶 Cloud

        Raises:
            httpx.HTTPError: 网络/HTTP 错误
            RuntimeError: 金蝶 API 业务错误
        """
        log.info(
            "kingdee.push_voucher",
            voucher_id=voucher.voucher_id,
            source_type=voucher.source_type,
            total_fen=voucher.total_fen,
        )
        payload = self._to_kingdee_payload(voucher)
        raw = await self._post("/ierp/api/v2/gl/vouchers/save", payload)

        erp_voucher_id = (
            str(raw.get("Result", {}).get("Id", ""))
            or raw.get("data", {}).get("VoucherId", "")
        )

        log.info(
            "kingdee.push_voucher.ok",
            voucher_id=voucher.voucher_id,
            erp_voucher_id=erp_voucher_id,
        )
        return ERPPushResult(
            voucher_id=voucher.voucher_id,
            erp_voucher_id=erp_voucher_id or None,
            status=PushStatus.SUCCESS,
            erp_type=ERPType.KINGDEE,
            raw_response=raw,
        )

    async def sync_chart_of_accounts(self) -> list[ERPAccount]:
        """从金蝶同步科目表；拉取失败时降级返回内置默认科目表"""
        log.info("kingdee.sync_chart_of_accounts")
        try:
            raw = await self._get(
                "/ierp/api/v2/bd/account/getAll",
                params={"EntityId": self._entity_id} if self._entity_id else None,
            )
            items = raw.get("data", raw.get("Result", {}).get("FacilityList", []))
            if not isinstance(items, list):
                items = []
            accounts = []
            for item in items:
                accounts.append(ERPAccount(
                    code=str(item.get("FNumber", item.get("code", ""))),
                    name=str(item.get("FName", item.get("name", ""))),
                    account_type=str(item.get("FAccountType", "资产")),
                    parent_code=item.get("FParentNumber") or None,
                    is_leaf=bool(item.get("FIsLeaf", True)),
                    extra=item,
                ))
            log.info("kingdee.sync_chart_of_accounts.ok", count=len(accounts))
            return accounts
        except httpx.HTTPError as exc:
            log.warning(
                "kingdee.sync_chart_of_accounts.fallback",
                error=str(exc),
                reason="HTTP错误，返回内置默认科目表",
            )
            return [
                ERPAccount(
                    code=a["code"],
                    name=a["name"],
                    account_type=a["account_type"],
                )
                for a in _KINGDEE_DEFAULT_ACCOUNTS
            ]

    async def health_check(self) -> bool:
        """探测金蝶 Cloud 连通性（HEAD 请求，不消耗配额）"""
        try:
            url = f"{self._base_url}/ierp/api/v2/ping"
            body = ""
            headers = self._build_headers(body)
            resp = await self._client.head(url, headers=headers)
            ok = resp.status_code < 500
            log.info("kingdee.health_check", ok=ok, status_code=resp.status_code)
            return ok
        except httpx.HTTPError as exc:
            log.warning("kingdee.health_check.failed", error=str(exc))
            return False

    async def close(self) -> None:
        await self._client.aclose()
