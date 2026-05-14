"""doc_number 健康度 admin API（issue #592）.

只读 endpoint:
  GET /api/v1/doc-number/fallback-stats
    返回当前进程 Counter snapshot, 按 (service, doc_type) 分组。
    用于 web-admin doc-number-rules 仪表板 + on-pod sanity check。

注意（issue #592 / handoff）:
  - 指标本身是进程级、跨租户聚合的；endpoint 暴露的也是跨租户总数 → 仅 admin 角色可读
    (cross-tenant 暴露 fallback 数仍泄漏运营信息)。
  - 通过 X-Internal-Role header gate（gateway proxy.py L142 注入；客户端
    伪造的 X-Internal-Role 被 gateway _STRIP 剥掉 L130，攻击不可达）；
    不在此处做完整 OIDC/JWT 解析。
  - 历史趋势 / Prometheus 告警接入：见 docs/operations/doc-number-fallback-runbook.md
    + tx-supply /metrics endpoint（已经由 prometheus_fastapi_instrumentator 暴露）。
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, status

from ..metrics import doc_number_fallback_null_total

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/doc-number", tags=["doc-number-admin"])

_ALLOWED_ROLES = frozenset({"admin", "ops"})


def _require_admin(x_internal_role: Optional[str]) -> None:
    """gateway proxy.py L142 注入 X-Internal-Role；客户端伪造被 _STRIP 剥掉.

    跨租户聚合数据，admin/ops 才能看；普通租户用户拒绝。
    用 X-Internal-Role 而非 X-Role：后者不在 gateway _STRIP 列表，
    客户端可伪造直达 tx-supply（绕过 gateway 时也可伪造），存在安全漏洞。
    """
    role = (x_internal_role or "").strip().lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="doc-number fallback stats 需要 admin/ops 角色",
        )


@router.get("/fallback-stats")
async def get_doc_number_fallback_stats(
    x_internal_role: Optional[str] = Header(default=None, alias="X-Internal-Role"),
) -> dict:
    """返回 doc_number infra fallback Counter 的进程级 snapshot.

    Response:
        {
          "ok": true,
          "data": {
            "total": int,                                    # 跨 service/doc_type 累计
            "by_service": {"inventory_io": int, ...},        # service 维度聚合
            "by_doc_type": {"inventory_io": int, "waste": int, ...},  # doc_type 维度聚合
            "by_combo": [                                    # 完整 (service, doc_type) 明细
              {"service": "inventory_io", "doc_type": "waste", "value": 12}, ...
            ]
          }
        }

    数据范围:
        - 进程级（pod 重启清零）；告警 + 历史趋势走 Prometheus scrape。
        - 跨租户聚合（counter 无 tenant_id 标签防 cardinality 爆炸）。

    Auth:
        - X-Internal-Role: admin / ops（gateway proxy 注入；客户端不可伪造）。
    """
    _require_admin(x_internal_role)

    by_combo: list[dict] = []
    by_service: dict[str, float] = {}
    by_doc_type: dict[str, float] = {}
    total = 0.0

    # prometheus_client Counter 每个 child 产出 2 个 sample:
    #   <metric>_total (值) / <metric>_created (创建时间戳).
    # 只取 _total，跳 _created；不读私有属性 (_name 等) 避免主版本升级断裂.
    for metric_family in doc_number_fallback_null_total.collect():
        for sample in metric_family.samples:
            if not sample.name.endswith("_total"):
                continue
            service = sample.labels.get("service", "unknown")
            doc_type = sample.labels.get("doc_type", "unknown")
            value = float(sample.value)
            by_combo.append(
                {"service": service, "doc_type": doc_type, "value": value}
            )
            by_service[service] = by_service.get(service, 0.0) + value
            by_doc_type[doc_type] = by_doc_type.get(doc_type, 0.0) + value
            total += value

    by_combo.sort(key=lambda r: (r["service"], r["doc_type"]))

    return {
        "ok": True,
        "data": {
            "total": total,
            "by_service": by_service,
            "by_doc_type": by_doc_type,
            "by_combo": by_combo,
            "note": (
                "进程级 Counter snapshot（pod 重启清零）。历史趋势 / 告警走 Prometheus；"
                "运维处置流程见 docs/operations/doc-number-fallback-runbook.md。"
            ),
        },
    }
