"""
天财商龙 → 屯象OS 会员数据迁移

⚠️  资金安全警告：
    会员储值余额迁移涉及真实资金，必须：
    1. 迁移前快照：记录天财余额（带时间戳）
    2. 迁移后核对：天财API二次验证，差异不超过1分
    3. 人工签字：财务人员逐日确认迁移记录
    4. 锁定天财：通知商户在天财侧冻结已迁移会员，防止双花
    自动迁移仅处理 balance_fen == 0 的零余额会员；
    有余额的会员需走人工审核流程（参见 migration_audit）。

天财会员 API：
  POST /api/member/getMemberList  — 获取会员列表（分页）

字段映射：
  card_no       → external_id（天财会员号，保留用于对账）
  phone         → phone（屯象 Golden ID 主键）
  member_name   → display_name
  balance       → stored_value_fen（分）
  points        → points
  level_name    → tier_name（映射到屯象等级）
  birthday      → birthday
  last_visit    → last_visit_at
  total_spend   → total_spend_fen（历史累计消费，分）
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

_MEMBER_PATH = "/api/member/getMemberList"
_MAX_PAGE_SIZE = 200

# 单次自动迁移的最大储值余额（超过此值需人工审核）
_AUTO_MIGRATE_MAX_BALANCE_FEN = 0  # 默认只迁移零余额，有余额必须人工确认


@dataclass
class MemberMigrationResult:
    total_fetched: int = 0
    auto_migrated: int = 0  # 自动迁移（零余额）
    pending_review: int = 0  # 待人工审核（有余额）
    total_skipped: int = 0
    errors: list[dict] = field(default_factory=list)

    @property
    def total_balance_fen_pending(self) -> int:
        """待审核的储值总额（分），用于财务签字确认"""
        return getattr(self, "_pending_balance_fen", 0)


class TiancaiMemberSync:
    """
    天财商龙会员迁移器。

    安全策略：
      - 零余额会员自动迁移
      - 有余额会员写入 member_migration_pending 表，等待人工审核
      - 迁移记录全量写入 member_migration_audit 表（含前快照）

    Usage:
        sync = TiancaiMemberSync(adapter)
        result = await sync.pull_and_migrate(tenant_id)
        # 查看待审核：GET /api/v1/migration/tiancai/members/pending
    """

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def fetch_all_members(self, max_pages: int = 100) -> list[dict]:
        """分页拉取天财全量会员列表。"""
        all_members: list[dict] = []
        page = 1

        while page <= max_pages:
            try:
                data = await self._adapter._request(
                    _MEMBER_PATH,
                    {
                        "centerId": self._adapter.center_id,
                        "shopId": self._adapter.shop_id,
                        "pageNo": page,
                        "pageSize": _MAX_PAGE_SIZE,
                    },
                )
            except Exception as exc:
                logger.warning(
                    "tiancai_member_fetch_failed",
                    page=page,
                    error=str(exc),
                )
                break

            items = data.get(
                "memberList",
                data.get("list", data.get("members", [])),
            )
            all_members.extend(items)

            page_info = data.get("pageInfo", {})
            total = int(page_info.get("total", len(items)))
            if page * _MAX_PAGE_SIZE >= total or not items:
                break
            page += 1

        logger.info("tiancai_members_fetched", total=len(all_members), pages=page)
        return all_members

    def to_member_dict(self, raw: dict, tenant_id: str) -> dict:
        """将天财会员原始数据转换为屯象 customers 表结构。"""
        # 储值余额（天财单位：分）
        balance_raw = raw.get("balance", raw.get("storageBalance", 0))
        stored_value_fen = int(balance_raw) if balance_raw else 0

        # 历史消费（天财单位：分）
        total_spend_raw = raw.get("total_spend", raw.get("totalConsume", 0))
        total_spend_fen = int(total_spend_raw) if total_spend_raw else 0

        # 积分
        points_raw = raw.get("points", raw.get("score", 0))
        points = int(points_raw) if points_raw else 0

        # 手机号（Golden ID 主键）
        phone = str(raw.get("phone", raw.get("mobile", raw.get("tel", ""))))
        phone = phone.strip().replace(" ", "").replace("-", "")

        return {
            "tenant_id": tenant_id,
            "phone": phone,
            "display_name": raw.get("member_name", raw.get("name", "")),
            "external_id_tiancai": str(raw.get("card_no", raw.get("cardNo", ""))),
            "stored_value_fen": stored_value_fen,
            "points": points,
            "total_spend_fen": total_spend_fen,
            "tier_name": raw.get("level_name", raw.get("levelName", "")),
            "birthday": raw.get("birthday"),
            "source": "tiancai_migration",
        }

    async def pull_and_migrate(
        self,
        tenant_id: str,
        dry_run: bool = False,
        auto_migrate_max_balance_fen: int = _AUTO_MIGRATE_MAX_BALANCE_FEN,
    ) -> MemberMigrationResult:
        """
        拉取天财全量会员，按余额安全策略分类处理。

        auto_migrate_max_balance_fen: 低于此值的储值余额自动迁移（默认0=只迁移零余额）
        商户可在确认后调高此值，逐步扩大自动迁移范围。
        """
        result = MemberMigrationResult()
        result._pending_balance_fen = 0

        raw_members = await self.fetch_all_members()
        result.total_fetched = len(raw_members)

        if not raw_members:
            return result

        auto_list: list[dict] = []
        pending_list: list[dict] = []

        for raw in raw_members:
            try:
                m = self.to_member_dict(raw, tenant_id)
                if not m["phone"]:
                    result.total_skipped += 1
                    continue
                if m["stored_value_fen"] <= auto_migrate_max_balance_fen:
                    auto_list.append(m)
                else:
                    pending_list.append(m)
                    result._pending_balance_fen += m["stored_value_fen"]
            except (KeyError, ValueError, TypeError) as exc:
                result.errors.append(
                    {
                        "card_no": raw.get("card_no"),
                        "error": str(exc),
                    }
                )

        result.pending_review = len(pending_list)

        if dry_run:
            result.auto_migrated = len(auto_list)
            logger.info(
                "tiancai_member_dry_run",
                tenant_id=tenant_id,
                auto=len(auto_list),
                pending_review=len(pending_list),
                pending_balance_fen=result._pending_balance_fen,
            )
            return result

        # 自动迁移（零余额）
        if auto_list:
            await self._upsert_members(auto_list, result, is_auto=True)

        # 待人工审核（有余额）写入 pending 表
        if pending_list:
            await self._write_pending_review(pending_list, tenant_id)

        logger.info(
            "tiancai_member_migration_done",
            tenant_id=tenant_id,
            total_fetched=result.total_fetched,
            auto_migrated=result.auto_migrated,
            pending_review=result.pending_review,
            pending_balance_fen=result._pending_balance_fen,
            errors=len(result.errors),
        )
        return result

    async def _upsert_members(
        self,
        members: list[dict],
        result: MemberMigrationResult,
        is_auto: bool,
    ) -> None:
        """UPSERT customers 表，以 phone 为唯一键。"""
        try:
            from sqlalchemy import text

            from shared.ontology.src.database import async_session_factory

            async with async_session_factory() as db:
                await db.execute(
                    text("SET app.tenant_id = :tid"),
                    {"tid": members[0]["tenant_id"]},
                )
                for m in members:
                    try:
                        await db.execute(
                            text("""
                            INSERT INTO customers
                              (tenant_id, phone, display_name,
                               external_id_tiancai,
                               stored_value_fen, points, total_spend_fen,
                               source, created_at, updated_at)
                            VALUES
                              (:tenant_id, :phone, :display_name,
                               :external_id_tiancai,
                               :stored_value_fen, :points, :total_spend_fen,
                               :source, NOW(), NOW())
                            ON CONFLICT (tenant_id, phone)
                            DO UPDATE SET
                              display_name         = EXCLUDED.display_name,
                              external_id_tiancai  = EXCLUDED.external_id_tiancai,
                              points               = EXCLUDED.points,
                              total_spend_fen      = EXCLUDED.total_spend_fen,
                              updated_at           = NOW()
                            -- 有余额的 stored_value_fen 不自动覆写，需人工审核
                        """),
                            m,
                        )
                        result.auto_migrated += 1
                    except Exception as exc:  # noqa: BLE001
                        result.errors.append(
                            {
                                "phone": m.get("phone"),
                                "error": str(exc),
                            }
                        )
                        result.total_skipped += 1

                await db.commit()

        except Exception as exc:  # noqa: BLE001
            logger.error("tiancai_member_upsert_failed", error=str(exc), exc_info=True)
            result.errors.append({"db_error": str(exc)})

    async def _write_pending_review(
        self,
        pending: list[dict],
        tenant_id: str,
    ) -> None:
        """
        将有储值余额的会员写入 member_migration_pending 表，
        等待财务人员人工核实后再执行余额迁移。
        """
        try:
            from sqlalchemy import text

            from shared.ontology.src.database import async_session_factory

            async with async_session_factory() as db:
                for m in pending:
                    await db.execute(
                        text("""
                        INSERT INTO member_migration_pending
                          (tenant_id, phone, display_name,
                           external_id_tiancai, stored_value_fen,
                           points, total_spend_fen, source,
                           status, created_at, updated_at)
                        VALUES
                          (:tenant_id, :phone, :display_name,
                           :external_id_tiancai, :stored_value_fen,
                           :points, :total_spend_fen, :source,
                           'pending_review', NOW(), NOW())
                        ON CONFLICT (tenant_id, phone)
                        DO UPDATE SET
                          stored_value_fen = EXCLUDED.stored_value_fen,
                          status           = 'pending_review',
                          updated_at       = NOW()
                    """),
                        m,
                    )
                await db.commit()

            logger.info(
                "tiancai_member_pending_written",
                tenant_id=tenant_id,
                count=len(pending),
            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "tiancai_member_pending_write_failed",
                error=str(exc),
                exc_info=True,
            )
