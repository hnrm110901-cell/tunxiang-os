"""腾讯云 COS 文件上传服务

环境变量:
  COS_SECRET_ID   -- 腾讯云 SecretId
  COS_SECRET_KEY  -- 腾讯云 SecretKey
  COS_REGION      -- 存储桶区域（默认 ap-changsha）
  COS_BUCKET      -- 存储桶名称（如 tunxiang-1234567890）

当 COS_SECRET_ID 未配置时自动进入 Mock 模式，返回本地伪路径。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import structlog

logger = structlog.get_logger(__name__)

# ─── 文件类型白名单 ───

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
DOCUMENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
}
VIDEO_TYPES = {"video/mp4", "video/quicktime"}
AUDIO_TYPES = {"audio/mpeg", "audio/mp4", "audio/wav"}
ALL_ALLOWED_TYPES = IMAGE_TYPES | DOCUMENT_TYPES | VIDEO_TYPES | AUDIO_TYPES

# ─── 上传大小限制（字节） ───

IMAGE_MAX_SIZE = 10 * 1024 * 1024      # 10 MB
FILE_MAX_SIZE = 50 * 1024 * 1024       # 50 MB

# ─── 合法 folder 白名单 ───

ALLOWED_FOLDERS = {
    "dishes",
    "avatars",
    "reviews",
    "invoices",
    "training",
    "menu",
    "store",
    "employee",
    "general",
    "contracts",
}


class COSUploadError(Exception):
    """COS 上传异常"""


class COSUploadService:
    """腾讯云 COS 文件上传服务 -- 自动降级 Mock"""

    def __init__(self) -> None:
        self._secret_id = os.getenv("COS_SECRET_ID", "")
        self._secret_key = os.getenv("COS_SECRET_KEY", "")
        self._region = os.getenv("COS_REGION", "ap-changsha")
        self._bucket = os.getenv("COS_BUCKET", "")
        self._is_mock = not (self._secret_id and self._secret_key and self._bucket)

        if self._is_mock:
            logger.warning("cos_upload_mock_mode", reason="COS_SECRET_ID/COS_SECRET_KEY/COS_BUCKET 未配置")
        else:
            logger.info(
                "cos_upload_initialized",
                region=self._region,
                bucket=self._bucket,
            )

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    @property
    def _host(self) -> str:
        return f"{self._bucket}.cos.{self._region}.myqcloud.com"

    @property
    def _base_url(self) -> str:
        return f"https://{self._host}"

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 公共方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        folder: str,
    ) -> dict[str, Any]:
        """上传文件 -> 返回 {url, key, size}

        Args:
            file_bytes: 文件二进制内容
            filename: 原始文件名
            content_type: MIME 类型
            folder: 存储目录（dishes/avatars/reviews/invoices/training/...）

        Raises:
            COSUploadError: 文件类型不允许、大小超限、上传失败
        """
        self._validate_folder(folder)
        self._validate_content_type(content_type)
        self._validate_file_size(file_bytes, content_type)

        key = self._generate_key(folder, filename)

        if self._is_mock:
            return self._mock_upload_result(key, filename, len(file_bytes))

        return await self._do_upload(file_bytes, key, content_type)

    async def upload_base64(
        self,
        base64_data: str,
        filename: str,
        folder: str,
        content_type: str = "image/png",
    ) -> dict[str, Any]:
        """Base64 上传

        Args:
            base64_data: Base64 编码字符串（可带 data:image/png;base64, 前缀）
            filename: 文件名
            folder: 存储目录
            content_type: MIME 类型

        Raises:
            COSUploadError: 解码失败、类型不允许
        """
        # 剥离 data URI 前缀
        if "," in base64_data and base64_data.startswith("data:"):
            header, base64_data = base64_data.split(",", 1)
            # 从 header 中提取 content_type
            if ":" in header and ";" in header:
                content_type = header.split(":")[1].split(";")[0]

        try:
            file_bytes = base64.b64decode(base64_data)
        except (ValueError, base64.binascii.Error) as exc:
            raise COSUploadError(f"Base64 解码失败: {exc}") from exc

        return await self.upload_file(file_bytes, filename, content_type, folder)

    async def get_presigned_url(self, key: str, expires: int = 3600) -> str:
        """获取预签名 URL（私有读场景）

        Args:
            key: 文件在 COS 中的 key
            expires: 过期时间（秒），默认 1 小时

        Returns:
            预签名 URL 字符串
        """
        if self._is_mock:
            return f"/mock/uploads/{key}?sign=mock&expires={expires}"

        now = int(time.time())
        sign_time = f"{now};{now + expires}"

        # 构建签名
        string_to_sign = self._build_presign_string(key, sign_time)
        signature = self._hmac_sha1(
            self._hmac_sha1(self._secret_key, sign_time),
            string_to_sign,
        )

        params = (
            f"q-sign-algorithm=sha1"
            f"&q-ak={self._secret_id}"
            f"&q-sign-time={sign_time}"
            f"&q-key-time={sign_time}"
            f"&q-header-list="
            f"&q-url-param-list="
            f"&q-signature={signature}"
        )
        return f"{self._base_url}/{quote(key, safe='/')}?{params}"

    async def delete_file(self, key: str) -> bool:
        """删除文件

        Args:
            key: 文件在 COS 中的 key

        Returns:
            是否删除成功
        """
        if self._is_mock:
            logger.info("cos_delete_mock", key=key)
            return True

        try:
            import httpx

            url = f"{self._base_url}/{quote(key, safe='/')}"
            headers = self._build_auth_headers("DELETE", key)

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.delete(url, headers=headers)

            if resp.status_code in (200, 204):
                logger.info("cos_file_deleted", key=key)
                return True

            logger.error(
                "cos_delete_failed",
                key=key,
                status=resp.status_code,
                body=resp.text[:500],
            )
            return False

        except ImportError:
            logger.error("cos_delete_httpx_not_installed")
            return False

    def get_thumbnail_url(self, url: str, width: int = 200, height: int = 200) -> str:
        """生成缩略图 URL（COS 数据万象）

        Args:
            url: 原图 URL
            width: 缩略图宽度
            height: 缩略图高度

        Returns:
            带数据万象处理参数的 URL
        """
        if self._is_mock or not url:
            return url

        separator = "&" if "?" in url else "?"
        return f"{url}{separator}imageMogr2/thumbnail/{width}x{height}"

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 内部方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _validate_folder(folder: str) -> None:
        if folder not in ALLOWED_FOLDERS:
            raise COSUploadError(
                f"不允许的目录: {folder}，合法值: {', '.join(sorted(ALLOWED_FOLDERS))}"
            )

    @staticmethod
    def _validate_content_type(content_type: str) -> None:
        if content_type not in ALL_ALLOWED_TYPES:
            raise COSUploadError(
                f"不允许的文件类型: {content_type}"
            )

    @staticmethod
    def _validate_file_size(file_bytes: bytes, content_type: str) -> None:
        size = len(file_bytes)
        if content_type in IMAGE_TYPES:
            if size > IMAGE_MAX_SIZE:
                raise COSUploadError(
                    f"图片大小超限: {size / 1024 / 1024:.1f}MB，上限 {IMAGE_MAX_SIZE / 1024 / 1024:.0f}MB"
                )
        elif size > FILE_MAX_SIZE:
            raise COSUploadError(
                f"文件大小超限: {size / 1024 / 1024:.1f}MB，上限 {FILE_MAX_SIZE / 1024 / 1024:.0f}MB"
            )

    @staticmethod
    def _generate_key(folder: str, filename: str) -> str:
        """生成唯一存储 key: {folder}/{date}/{uuid}_{filename}"""
        date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
        unique_id = uuid.uuid4().hex[:12]
        # 只保留文件名中安全的字符
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")
        if not safe_name:
            safe_name = "file"
        return f"{folder}/{date_prefix}/{unique_id}_{safe_name}"

    def _mock_upload_result(self, key: str, filename: str, size: int) -> dict[str, Any]:
        logger.info("cos_upload_mock", key=key, filename=filename, size=size)
        return {
            "url": f"/mock/uploads/{key}",
            "key": key,
            "size": size,
        }

    async def _do_upload(
        self,
        file_bytes: bytes,
        key: str,
        content_type: str,
    ) -> dict[str, Any]:
        """执行真实 COS 上传（PUT Object）"""
        try:
            import httpx
        except ImportError as exc:
            raise COSUploadError("httpx 未安装，请执行 pip install httpx") from exc

        url = f"{self._base_url}/{quote(key, safe='/')}"
        headers = self._build_auth_headers("PUT", key, content_type=content_type)
        headers["Content-Type"] = content_type

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.put(url, content=file_bytes, headers=headers)

            if resp.status_code == 200:
                file_url = f"{self._base_url}/{quote(key, safe='/')}"
                logger.info("cos_upload_success", key=key, size=len(file_bytes))
                return {
                    "url": file_url,
                    "key": key,
                    "size": len(file_bytes),
                }

            raise COSUploadError(
                f"COS 上传失败: HTTP {resp.status_code}, {resp.text[:500]}"
            )

        except httpx.HTTPError as exc:
            raise COSUploadError(f"COS 请求异常: {exc}") from exc

    def _build_auth_headers(
        self,
        method: str,
        key: str,
        content_type: str | None = None,
    ) -> dict[str, str]:
        """构建 COS 请求签名 Authorization header"""
        now = int(time.time())
        sign_time = f"{now};{now + 600}"
        key_time = sign_time

        # SignKey
        sign_key = self._hmac_sha1(self._secret_key, key_time)

        # HttpString
        http_string = f"{method.lower()}\n/{key}\n\n\n"

        # StringToSign
        sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
        string_to_sign = f"sha1\n{sign_time}\n{sha1_http}\n"

        # Signature
        signature = self._hmac_sha1(sign_key, string_to_sign)

        authorization = (
            f"q-sign-algorithm=sha1"
            f"&q-ak={self._secret_id}"
            f"&q-sign-time={sign_time}"
            f"&q-key-time={key_time}"
            f"&q-header-list="
            f"&q-url-param-list="
            f"&q-signature={signature}"
        )

        headers: dict[str, str] = {"Authorization": authorization}
        return headers

    def _build_presign_string(self, key: str, sign_time: str) -> str:
        """构建预签名字符串"""
        http_string = f"get\n/{key}\n\n\n"
        sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
        return f"sha1\n{sign_time}\n{sha1_http}\n"

    @staticmethod
    def _hmac_sha1(key: str, msg: str) -> str:
        return hmac.new(key.encode(), msg.encode(), hashlib.sha1).hexdigest()


# ─── 单例 ───

_instance: COSUploadService | None = None


def get_cos_upload_service() -> COSUploadService:
    """获取 COS 上传服务单例"""
    global _instance  # noqa: PLW0603
    if _instance is None:
        _instance = COSUploadService()
    return _instance
