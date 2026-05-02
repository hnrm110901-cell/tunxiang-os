"""预警引擎 - 规则评估、告警触发、生命周期管理"""
from __future__ import annotations
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional
import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Alert, AlertRule, AlertSeverity, AlertStatus, AlertStats
log = structlog.get_logger(__name__)

# 物化视图白名单 — 仅允许从此列表查询
_KNOWN_MVS = frozenset({
    "mv_store_pnl", "mv_member_clv", "mv_inventory_bom",
    "mv_discount_health", "mv_daily_settlement", "mv_channel_margin",
    "mv_safety_compliance", "mv_energy_efficiency",
})

# 条件处理函数 — 显式映射，替代字符串模糊匹配
def _cond_dev_decrease_gt_threshold(cv, bv, t):
    """偏差为负且绝对值 > 阈值（如营收下降超10%）"""
    if bv and bv != 0:
        dev = (cv - bv) / abs(bv) * 100
        return dev < 0 and abs(dev) > t
    return False

def _cond_dev_abs_gt_threshold(cv, bv, t):
    """偏差绝对值 > 阈值（如成本率变化超5%）"""
    if bv and bv != 0:
        dev = (cv - bv) / abs(bv) * 100
        return abs(dev) > t
    return False

def _cond_dev_lt_neg_threshold(cv, bv, t):
    """偏差 < -阈值（如利润率低于目标）"""
    if bv and bv != 0:
        dev = (cv - bv) / abs(bv) * 100
        return dev < -t
    return False

def _cond_dev_gt_threshold(cv, bv, t):
    """偏差 > 阈值（如损耗率上升超阈值）"""
    if bv and bv != 0:
        dev = (cv - bv) / abs(bv) * 100
        return dev > 0 and dev > t
    return False

def _cond_current_lt_baseline_times(cv, bv, t):
    """当前值 < 基线×系数（如坪效低于基准）"""
    if bv is not None:
        return cv < bv * t
    return False

def _cond_current_lt_threshold(cv, _bv, t):
    """当前值 < 绝对阈值"""
    return cv < t

def _cond_current_le_threshold(cv, _bv, t):
    """当前值 <= 绝对阈值"""
    return cv <= t

def _cond_current_gt_threshold(cv, _bv, t):
    """当前值 > 绝对阈值"""
    return cv > t

def _cond_current_ge_threshold(cv, _bv, t):
    """当前值 >= 绝对阈值"""
    return cv >= t

# 条件ID → 处理函数的显式映射（使用精确子串匹配，顺序很重要）
_CONDITION_HANDLERS: dict[str, callable] = {
    "decrease_pct > threshold":        _cond_dev_decrease_gt_threshold,
    "decrease_pp > threshold":         _cond_dev_decrease_gt_threshold,
    "abs(deviation_pct) > threshold":  _cond_dev_abs_gt_threshold,
    "abs(z_score) > threshold":        _cond_dev_abs_gt_threshold,
    "margin < target - threshold":     _cond_dev_lt_neg_threshold,
    "price_increase_pct > threshold":  _cond_dev_gt_threshold,
    "revenue_per_sqm < baseline":      _cond_current_lt_baseline_times,
    "avg_7day < baseline_avg":         _cond_current_lt_baseline_times,
}


class AlertEngine:
    def __init__(self, rules=None):
        from .rules_registry import DEFAULT_ALERT_RULES
        self.rules = rules or DEFAULT_ALERT_RULES
        self._cooldown_tracker: OrderedDict = OrderedDict()
        self._alerts_cache: OrderedDict = OrderedDict()
        self._cache_max_size = 500
        self._cache_ttl_seconds = 1800  # 30 minutes
        self._cooldown_max_entries = 10000

    def _cache_put(self, alert_id: str, alert) -> None:
        """写入缓存（LRU 淘汰 + TTL）"""
        self._alerts_cache[alert_id] = (alert, time.monotonic())
        self._alerts_cache.move_to_end(alert_id)
        if len(self._alerts_cache) > self._cache_max_size:
            self._alerts_cache.popitem(last=False)
            log.debug("alert_cache_evicted", reason="size_limit")

    def _cache_get(self, alert_id: str):
        """读取缓存（自动清理过期条目）"""
        entry = self._alerts_cache.get(alert_id)
        if entry is None:
            return None
        alert, ts = entry
        if time.monotonic() - ts > self._cache_ttl_seconds:
            del self._alerts_cache[alert_id]
            return None
        self._alerts_cache.move_to_end(alert_id)
        return alert

    def _cooldown_put(self, key: tuple, ts: datetime) -> None:
        """写入冷却追踪器（LRU 淘汰）"""
        self._cooldown_tracker[key] = ts
        self._cooldown_tracker.move_to_end(key)
        if len(self._cooldown_tracker) > self._cooldown_max_entries:
            self._cooldown_tracker.popitem(last=False)

    async def evaluate(self, db, tenant_id, store_id=None):
        """评估所有启用规则，返回新触发的告警列表"""
        new_alerts = []
        for rule in [r for r in self.rules if r.enabled]:
            ck = (tenant_id, rule.rule_id, store_id or "")
            last = self._cooldown_tracker.get(ck)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < rule.cooldown_minutes * 60:
                continue
            try:
                alert = await self._evaluate_rule(db, rule, tenant_id, store_id)
                if alert:
                    new_alerts.append(alert)
                    self._cooldown_put(ck, datetime.now(timezone.utc))
                    self._cache_put(alert.alert_id, alert)
            except (OperationalError, SQLAlchemyError) as exc:
                log.warning("alert_rule_eval_failed", rule_id=rule.rule_id, error=str(exc))
        return new_alerts

    async def _evaluate_rule(self, db, rule, tenant_id, store_id):
        """评估单条规则"""
        current_val, baseline_val = await self._fetch_metrics(db, rule, tenant_id, store_id)
        if current_val is None:
            return None
        if not self._check_condition(rule, current_val, baseline_val):
            return None
        deviation_pct = None
        if baseline_val is not None and baseline_val != 0:
            deviation_pct = round((current_val - baseline_val) / abs(baseline_val) * 100, 1)
        alert_id = str(uuid.uuid4())
        alert = Alert(alert_id=alert_id, rule_id=rule.rule_id, tenant_id=tenant_id,
            store_id=store_id, severity=rule.severity, status=AlertStatus.FIRED,
            title=rule.name, description=f"{rule.name}: current={current_val}",
            metric_name=rule.metric_field, metric_value=current_val,
            baseline_value=baseline_val, deviation_pct=deviation_pct,
            fired_at=datetime.now(timezone.utc).isoformat())
        alert.compute_sla_deadline()
        log.info("alert_fired", alert_id=alert_id, rule_id=rule.rule_id,
            severity=rule.severity.value, domain=rule.domain)
        return alert

    async def _fetch_metrics(self, db, rule, tenant_id, store_id):
        """从物化视图查询指标（白名单校验）"""
        mv_map = {"sales":"mv_store_pnl","cost":"mv_store_pnl","finance":"mv_store_pnl",
            "store":"mv_store_pnl","member":"mv_member_clv","supply":"mv_inventory_bom","dish":"mv_discount_health"}
        mv = mv_map.get(rule.domain, "mv_store_pnl")
        # 白名单校验
        if mv not in _KNOWN_MVS:
            log.error("alert_unknown_mv", mv=mv, rule_id=rule.rule_id)
            return None, None
        params = {"tenant_id": tenant_id}
        sf = ""
        if store_id:
            sf = "AND store_id = :store_id"
            params["store_id"] = store_id
        try:
            # SELECT * 在此处是合理的：不同规则查询不同 metric_field，无法预知列名
            result = await db.execute(
                text(f"SELECT * FROM {mv} WHERE tenant_id = :tenant_id {sf} LIMIT 1"), params)
            row = result.mappings().first()
            if not row:
                return None, None
            cv = float(row[rule.metric_field]) if rule.metric_field in row and row[rule.metric_field] is not None else None
            bv = float(row.get(f"{rule.metric_field}_baseline")) if f"{rule.metric_field}_baseline" in row and row[f"{rule.metric_field}_baseline"] is not None else None
            return cv, bv
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("alert_fetch_failed", mv=mv, rule_id=rule.rule_id, error=str(exc))
            return None, None

    @staticmethod
    def _check_condition(rule, current, baseline):
        """评估条件表达式（精确子串匹配 + 通用比较回退）"""
        t = rule.threshold
        cond = rule.condition

        # Tier 1: 精确子串匹配（偏差类条件，依赖 baseline）
        for pattern, handler in _CONDITION_HANDLERS.items():
            if pattern in cond:
                return handler(current, baseline, t)

        # Tier 2: 通用比较运算符回退（不依赖 baseline）
        if ">=" in cond:
            return current >= t
        if "<=" in cond:
            return current <= t
        if ">" in cond:
            return current > t
        if "<" in cond:
            return current < t

        log.warning("alert_unknown_condition", condition=cond, rule_id=rule.rule_id)
        return False

    async def fire(self, db, rule, metric_value, baseline, tenant_id, store_id=None):
        """手动触发告警"""
        ck = (tenant_id, rule.rule_id, store_id or "")
        last = self._cooldown_tracker.get(ck)
        if last and (datetime.now(timezone.utc) - last).total_seconds() < rule.cooldown_minutes * 60:
            return Alert(alert_id="", rule_id=rule.rule_id, tenant_id=tenant_id, store_id=store_id,
                severity=rule.severity, status=AlertStatus.IGNORED, title=rule.name,
                description="cooldown", metric_name=rule.metric_field,
                metric_value=metric_value, baseline_value=baseline)
        dev = None
        if baseline is not None and baseline != 0:
            dev = round((metric_value - baseline) / abs(baseline) * 100, 1)
        aid = str(uuid.uuid4())
        alert = Alert(alert_id=aid, rule_id=rule.rule_id, tenant_id=tenant_id, store_id=store_id,
            severity=rule.severity, status=AlertStatus.FIRED, title=rule.name,
            description=rule.description, metric_name=rule.metric_field,
            metric_value=metric_value, baseline_value=baseline, deviation_pct=dev,
            fired_at=datetime.now(timezone.utc).isoformat())
        alert.compute_sla_deadline()
        await self._persist_alert(db, alert)
        self._cache_put(aid, alert)
        self._cooldown_put(ck, datetime.now(timezone.utc))
        return alert

    async def _load_alert(self, db, alert_id, tenant_id=None):
        """加载告警（cache优先，tenant_id可选过滤）"""
        cached = self._cache_get(alert_id)
        if cached is not None:
            if tenant_id and cached.tenant_id != tenant_id:
                return None
            return cached
        try:
            params = {"aid": alert_id}
            where = "alert_id = :aid"
            if tenant_id:
                where += " AND tenant_id = :tenant_id"
                params["tenant_id"] = tenant_id
            r = await db.execute(text(f"""SELECT alert_id, rule_id, tenant_id, store_id,
                severity, status, title, description, metric_name, metric_value,
                baseline_value, deviation_pct, fired_at, acknowledged_at, acknowledged_by,
                assigned_to, resolved_at, resolved_by, closed_at, sla_deadline, sla_breached,
                handler_notes, resolution_notes, resolution_type, meta
                FROM alerts WHERE {where}"""), params)
            row = r.mappings().first()
            if row:
                a = Alert.from_row(dict(row))
                self._cache_put(alert_id, a)
                return a
        except (OperationalError, SQLAlchemyError) as exc:
            log.error("alert_load_failed", alert_id=alert_id, error=str(exc))
        return None

    async def _persist_alert(self, db, alert):
        row = alert.to_row()
        try:
            await db.execute(text("""INSERT INTO alerts (alert_id, rule_id, tenant_id, store_id,
                severity, status, title, description, metric_name, metric_value,
                baseline_value, deviation_pct, fired_at, acknowledged_at, acknowledged_by,
                assigned_to, resolved_at, resolved_by, closed_at, sla_deadline, sla_breached,
                handler_notes, resolution_notes, resolution_type, meta)
                VALUES (:alert_id, :rule_id, :tenant_id, :store_id,
                :severity, :status, :title, :description, :metric_name, :metric_value,
                :baseline_value, :deviation_pct, :fired_at, :acknowledged_at, :acknowledged_by,
                :assigned_to, :resolved_at, :resolved_by, :closed_at, :sla_deadline, :sla_breached,
                :handler_notes, :resolution_notes, :resolution_type, :meta)"""),
                {"alert_id": alert.alert_id, **row})
            await db.commit()
        except (OperationalError, SQLAlchemyError) as exc:
            log.error("alert_persist_failed", alert_id=alert.alert_id, error=str(exc))
            await db.rollback()

    async def _update_alert_status(self, db, alert):
        try:
            await db.execute(text("""UPDATE alerts SET status=:s,severity=:sv,acknowledged_at=:aa,
                acknowledged_by=:ab,assigned_to=:at,resolved_at=:ra,resolved_by=:rb,
                closed_at=:ca,sla_deadline=:sd,sla_breached=:sb,handler_notes=:hn,
                resolution_notes=:rn,resolution_type=:rt,updated_at=NOW()
                WHERE alert_id=:aid AND tenant_id=:tenant_id"""),
                {"aid":alert.alert_id,"tenant_id":alert.tenant_id,"s":alert.status.value,"sv":alert.severity.value,
                 "aa":alert.acknowledged_at,"ab":alert.acknowledged_by,"at":alert.assigned_to,
                 "ra":alert.resolved_at,"rb":alert.resolved_by,"ca":alert.closed_at,
                 "sd":alert.sla_deadline,"sb":alert.sla_breached,"hn":alert.handler_notes,
                 "rn":alert.resolution_notes,"rt":alert.resolution_type})
            await db.commit()
        except (OperationalError, SQLAlchemyError) as exc:
            log.error("alert_update_failed", alert_id=alert.alert_id, error=str(exc))
            await db.rollback()

    async def acknowledge(self, db, alert_id, user_id):
        a = await self._load_alert(db, alert_id)
        if not a or a.status not in (AlertStatus.FIRED, AlertStatus.ACKNOWLEDGED):
            return None
        a.mark_acknowledged(user_id)
        await self._update_alert_status(db, a)
        self._cache_put(alert_id, a)
        return a

    async def process(self, db, alert_id):
        a = await self._load_alert(db, alert_id)
        if not a: return None
        a.mark_processing()
        await self._update_alert_status(db, a)
        self._cache_put(alert_id, a)
        return a

    async def resolve(self, db, alert_id, user_id, notes, resolution_type="fixed"):
        a = await self._load_alert(db, alert_id)
        if not a or a.status in (AlertStatus.CLOSED, AlertStatus.IGNORED):
            return None
        a.mark_resolved(user_id, notes, resolution_type)
        await self._update_alert_status(db, a)
        self._cache_put(alert_id, a)
        return a

    async def close(self, db, alert_id):
        a = await self._load_alert(db, alert_id)
        if not a or a.status != AlertStatus.RESOLVED:
            return None
        a.mark_closed()
        await self._update_alert_status(db, a)
        self._cache_put(alert_id, a)
        return a

    async def ignore(self, db, alert_id, notes):
        a = await self._load_alert(db, alert_id)
        if not a: return None
        a.mark_ignored(notes)
        await self._update_alert_status(db, a)
        self._cache_put(alert_id, a)
        return a

    async def escalate(self, db, alert_id):
        a = await self._load_alert(db, alert_id)
        if not a: return None
        a.check_sla()
        if a.sla_breached:
            new_sev = {AlertSeverity.P1_IMPORTANT: AlertSeverity.P0_CRITICAL,
                       AlertSeverity.P2_NORMAL: AlertSeverity.P1_IMPORTANT}.get(a.severity, a.severity)
            a.severity = new_sev
            a.compute_sla_deadline()
            a.sla_breached = False
            await self._update_alert_status(db, a)
            self._cache_put(alert_id, a)
        return a

    async def get_active_alerts(self, db, tenant_id, severity=None, domain=None, store_id=None, limit=50, offset=0):
        conds = ["tenant_id = :tenant_id", "status IN ('fired','acknowledged','processing')"]
        params = {"tenant_id":tenant_id,"limit":limit,"offset":offset}
        if severity:
            conds.append("severity = :severity"); params["severity"] = severity
        if store_id:
            conds.append("store_id = :store_id"); params["store_id"] = store_id
        if domain:
            conds.append("rule_id LIKE :dp"); params["dp"] = f"{domain}%"
        where = " AND ".join(conds)
        try:
            r = await db.execute(text(f"""SELECT alert_id, rule_id, tenant_id, store_id,
                severity, status, title, description, metric_name, metric_value,
                baseline_value, deviation_pct, fired_at, acknowledged_at, acknowledged_by,
                assigned_to, resolved_at, resolved_by, closed_at, sla_deadline, sla_breached,
                handler_notes, resolution_notes, resolution_type, meta
                FROM alerts WHERE {where} ORDER BY severity ASC, fired_at DESC LIMIT :limit OFFSET :offset"""), params)
            return [Alert.from_row(dict(row)) for row in r.mappings().all()]
        except (OperationalError, SQLAlchemyError) as exc:
            log.error("alert_get_active_failed", error=str(exc))
            return []

    async def get_alert(self, db, alert_id):
        return await self._load_alert(db, alert_id)

    async def get_stats(self, db, tenant_id, store_id=None):
        sf = "AND store_id = :store_id" if store_id else ""
        params = {"tenant_id":tenant_id}
        if store_id: params["store_id"] = store_id
        try:
            r = await db.execute(text(f"""SELECT
                COUNT(*)::INT AS total,
                COUNT(*) FILTER (WHERE sla_breached=TRUE)::INT AS sla_breached,
                severity, status
                FROM alerts WHERE tenant_id=:tenant_id {sf}
                GROUP BY severity, status"""), params)
            rows = r.mappings().all()
            s = AlertStats()
            sev_total = {}
            st_total = {}
            for row in rows:
                cnt = 1
                sv = row["severity"]; st = row["status"]
                sev_total[sv] = sev_total.get(sv, 0) + cnt
                st_total[st] = st_total.get(st, 0) + cnt
            s.total = sum(sev_total.values())
            s.sla_breached_count = rows[0]["sla_breached"] if rows else 0
            s.by_severity = sev_total
            s.by_status = st_total
            return s
        except (OperationalError, SQLAlchemyError) as exc:
            log.error("alert_stats_failed", error=str(exc))
            return AlertStats()
