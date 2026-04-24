"""用友云 YonBIP/NC ERP 适配器

认证：OAuth2 Client Credentials Flow
凭证推送：POST /api/v1/gl/vouchers
科目同步：GET  /api/v1/bd/account/list

环境变量：
  YONYOU_CLIENT_ID      — 用友开放平台 Client ID
  YONYOU_CLIENT_SECRET  — 用友开放平台 Client Secret
  YONYOU_BASE_URL       — 用友云实例地址，如 https://xxx.yonbip.com
  YONYOU_TENANT_CODE    — 用友账套编码（多账套场景）

离线缓冲机制：
  推送失败时写入本地队列文件（JSON Lines）
  路径：YONYOU_QUEUE_PATH（默认 /tmp/yonyou_push_queue.jsonl）
  通过 drain_queue() 方法批量重试
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
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


class YonyouAdapter(ERPAdapter):
    """用友云 YonBIP/NC 适配器

    OAuth2 认证 + 凭证推送 + 离线缓冲重试。
    """

    def __init__(self) -> None:
        self._client_id = os.environ["YONYOU_CLIENT_ID"]
        self._client_secret = os.environ["YONYOU_CLIENT_SECRET"]
        self._base_url = os.environ["YONYOU_BASE_URL"].rstrip("/")
        self._tenant_code = os.environ.get("YONYOU_TENANT_CODE", "")
        # 离线队列路径（推送失败时写入，待后续重试）
        default_queue_path = str(Path(tempfile.gettempdir()) / "yonyou_push_queue.jsonl")
        queue_path = os.environ.get("YONYOU_QUEUE_PATH", default_queue_path)
        self._queue_path = Path(queue_path)

        self._client = httpx.AsyncClient(timeout=30)
        # Token 缓存
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ─── OAuth2 ───────────────────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """获取 OAuth2 Access Token，缓存有效期内复用"""
        if self._access_token and time.time() < self._token_expires_at - 300:
            return self._access_token

        url = f"{self._base_url}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "gl:write bd:read",
        }
        log.debug("yonyou.oauth2.token_request", url=url)
        resp = await self._client.post(url, data=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        token = data.get("access_token")
        if not token:
            raise ValueError(f"用友OAuth2未返回access_token: {data}")

        self._access_token = token
        expires_in = int(data.get("expires_in", 7200))
        self._token_expires_at = time.time() + expires_in
        log.info("yonyou.oauth2.token_ok", expires_in=expires_in)
        return self._access_token

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Tenant-Code": self._tenant_code,
            "X-Request-Id": uuid.uuid4().hex,
        }

    # ─── 内部请求 ─────────────────────────────────────────────────────────

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self._get_access_token()
        url = f"{self._base_url}{path}"
        body = json.dumps(payload, ensure_ascii=False)
        headers = self._auth_headers(token)
        log.debug("yonyou.request", url=url)
        resp = await self._client.post(url, content=body, headers=headers)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        # 用友云 API：code=0 或 "0" 表示成功
        code = str(data.get("code", data.get("status", "-1")))
        if code not in ("0", "200", "success"):
            msg = data.get("message", data.get("msg", "未知错误"))
            raise RuntimeError(f"用友API业务错误 [{code}]: {msg}")
        return data

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self._get_access_token()
        url = f"{self._base_url}{path}"
        headers = self._auth_headers(token)
        resp = await self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ─── 凭证格式转换 ─────────────────────────────────────────────────────

    def _to_yonyou_payload(self, voucher: ERPVoucher) -> dict[str, Any]:
        """将屯象统一凭证格式转换为用友云凭证接口格式"""
        entries = []
        for entry in voucher.entries:
            entries.append(
                {
                    "accountCode": entry.account_code,
                    "accountName": entry.account_name,
                    "debitAmount": entry.debit_fen / 100,  # 分 → 元
                    "creditAmount": entry.credit_fen / 100,
                    "explanation": entry.summary,
                    "currencyCode": "CNY",
                }
            )

        return {
            "voucherType": voucher.voucher_type.value,
            "voucherDate": voucher.business_date.isoformat(),
            "entries": entries,
            "memo": voucher.memo or f"屯象OS自动生成: {voucher.source_type}#{voucher.source_id}",
            "sourceSystem": "TunxiangOS",
            "sourceVoucherId": voucher.voucher_id,
            "tenantCode": self._tenant_code,
        }

    # ─── 离线队列 ─────────────────────────────────────────────────────────

    def _enqueue(self, voucher: ERPVoucher, error: str) -> None:
        """推送失败时将凭证序列化到本地 JSON Lines 文件（原子追加）"""
        record = {
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
            "voucher": voucher.model_dump(mode="json"),
        }
        try:
            with self._queue_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.warning(
                "yonyou.push.queued",
                voucher_id=voucher.voucher_id,
                queue_path=str(self._queue_path),
                error=error,
            )
        except OSError as write_exc:
            # 写队列失败是次要错误，记录日志但不影响主流程
            log.error(
                "yonyou.push.queue_write_failed",
                voucher_id=voucher.voucher_id,
                error=str(write_exc),
            )

    def queue_size(self) -> int:
        """返回当前待重试队列条目数"""
        if not self._queue_path.exists():
            return 0
        with self._queue_path.open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    async def drain_queue(self) -> list[ERPPushResult]:
        """批量消费离线队列，推送成功的条目从队列中移除

        Returns:
            每条条目的推送结果列表
        """
        if not self._queue_path.exists():
            return []

        log.info("yonyou.drain_queue.start", queue_path=str(self._queue_path))
        results: list[ERPPushResult] = []
        remaining_lines: list[str] = []

        with self._queue_path.open("r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        for line in lines:
            try:
                record = json.loads(line)
                voucher = ERPVoucher.model_validate(record["voucher"])
                result = await self._do_push(voucher)
                results.append(result)
                if result.status == PushStatus.SUCCESS:
                    log.info("yonyou.drain_queue.ok", voucher_id=voucher.voucher_id)
                else:
                    remaining_lines.append(line)
            except (json.JSONDecodeError, ValueError) as exc:
                log.error("yonyou.drain_queue.parse_error", error=str(exc), line=line[:100])
                remaining_lines.append(line)
            except httpx.HTTPError as exc:
                log.warning("yonyou.drain_queue.http_error", error=str(exc))
                remaining_lines.append(line)

        # 将未成功的条目写回队列
        with self._queue_path.open("w", encoding="utf-8") as f:
            for line in remaining_lines:
                f.write(line + "\n")

        log.info(
            "yonyou.drain_queue.done",
            total=len(lines),
            success=len(lines) - len(remaining_lines),
            remaining=len(remaining_lines),
        )
        return results

    # ─── 核心推送（内部，供 push_voucher 和 drain_queue 复用）─────────────

    async def _do_push(self, voucher: ERPVoucher) -> ERPPushResult:
        payload = self._to_yonyou_payload(voucher)
        raw = await self._post("/api/v1/gl/vouchers", payload)
        erp_voucher_id = str(raw.get("data", {}).get("voucherId", "") or raw.get("data", {}).get("id", "")) or None
        return ERPPushResult(
            voucher_id=voucher.voucher_id,
            erp_voucher_id=erp_voucher_id,
            status=PushStatus.SUCCESS,
            erp_type=ERPType.YONYOU,
            raw_response=raw,
        )

    # ─── 接口实现 ─────────────────────────────────────────────────────────

    async def push_voucher(self, voucher: ERPVoucher) -> ERPPushResult:
        """推送凭证到用友云；失败时写入本地队列并返回 QUEUED 状态

        不抛出异常：推送失败属于预期的可恢复场景，
        调用方通过 result.status == PushStatus.QUEUED 感知。
        """
        log.info(
            "yonyou.push_voucher",
            voucher_id=voucher.voucher_id,
            source_type=voucher.source_type,
            total_fen=voucher.total_fen,
        )
        try:
            result = await self._do_push(voucher)
            log.info("yonyou.push_voucher.ok", voucher_id=voucher.voucher_id)
            return result
        except httpx.HTTPError as exc:
            error_msg = f"HTTP错误: {exc}"
            self._enqueue(voucher, error_msg)
            return ERPPushResult(
                voucher_id=voucher.voucher_id,
                status=PushStatus.QUEUED,
                erp_type=ERPType.YONYOU,
                error_message=error_msg,
            )
        except RuntimeError as exc:
            error_msg = str(exc)
            self._enqueue(voucher, error_msg)
            return ERPPushResult(
                voucher_id=voucher.voucher_id,
                status=PushStatus.QUEUED,
                erp_type=ERPType.YONYOU,
                error_message=error_msg,
            )

    async def sync_chart_of_accounts(self) -> list[ERPAccount]:
        """从用友云同步科目表"""
        log.info("yonyou.sync_chart_of_accounts")
        raw = await self._get(
            "/api/v1/bd/account/list",
            params={"tenantCode": self._tenant_code, "pageSize": 500},
        )
        items = raw.get("data", {})
        if isinstance(items, dict):
            items = items.get("list", items.get("records", []))
        if not isinstance(items, list):
            items = []

        accounts = []
        for item in items:
            accounts.append(
                ERPAccount(
                    code=str(item.get("accountCode", item.get("code", ""))),
                    name=str(item.get("accountName", item.get("name", ""))),
                    account_type=str(item.get("accountType", "资产")),
                    parent_code=item.get("parentCode") or None,
                    is_leaf=bool(item.get("isLeaf", True)),
                    currency=item.get("currencyCode", "CNY"),
                    extra=item,
                )
            )
        log.info("yonyou.sync_chart_of_accounts.ok", count=len(accounts))
        return accounts

    async def health_check(self) -> bool:
        """探测用友云连通性（获取 Token 作为检测手段）"""
        try:
            await self._get_access_token()
            log.info("yonyou.health_check", ok=True)
            return True
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("yonyou.health_check.failed", error=str(exc))
            return False

    async def close(self) -> None:
        await self._client.aclose()
