"""会员Golden ID -- 全渠道统一画像

合并7个来源的会员数据：堂食/外卖/小程序/企微/预订/宴会/储值
基于手机号统一识别，构建跨渠道客户画像。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from collections import defaultdict

import structlog

logger = structlog.get_logger()


# ─── 内存存储（生产环境替换为数据库） ───

_golden_profiles: dict[str, dict] = {}       # member_id → profile
_phone_to_member: dict[str, str] = {}         # phone → member_id
_touchpoints: dict[str, list[dict]] = {}      # member_id → [touchpoint_events]


def _gen_member_id() -> str:
    return f"GID{uuid.uuid4().hex[:12].upper()}"


class MemberGoldenIDService:
    """会员Golden ID -- 全渠道统一画像

    合并7个来源的会员数据：堂食/外卖/小程序/企微/预订/宴会/储值
    """

    DATA_SOURCES = [
        "dine_in", "meituan", "eleme", "douyin", "miniapp",
        "wecom", "reservation", "banquet", "stored_value",
    ]

    # RFM分层阈值
    RFM_THRESHOLDS = {
        'recency_days': {'active': 30, 'warm': 90, 'cold': 180},
        'frequency': {'high': 10, 'medium': 4, 'low': 1},
        'monetary_fen': {'high': 500000, 'medium': 100000, 'low': 0},  # 5000元 / 1000元
    }

    # 生命周期阶段
    LIFECYCLE_STAGES = ['new', 'growing', 'mature', 'declining', 'dormant', 'lost']

    def __init__(self, brand_id: str):
        self.brand_id = brand_id

    def merge_profiles(self, phone: str, profiles: list[dict]) -> dict:
        """合并多源会员数据 → 生成统一Golden ID

        Args:
            phone: 手机号（统一标识）
            profiles: 各渠道的用户数据列表
                [{source, name?, gender?, birthday?, address?, email?,
                  total_spend_fen?, visit_count?, preferred_dishes?, tags?,
                  last_visit?, registered_at?}]

        Returns:
            {member_id, phone, merged_profile, source_count, conflicts}
        """
        if not phone or len(phone) < 11:
            raise ValueError(f"无效手机号: {phone}")

        # 检查是否已有Golden ID
        existing_member_id = _phone_to_member.get(phone)

        if existing_member_id and existing_member_id in _golden_profiles:
            member_id = existing_member_id
            existing = _golden_profiles[member_id]
        else:
            member_id = _gen_member_id()
            existing = None

        # 合并策略：latest update wins for basic info, aggregate for spend/visits
        merged = {
            'member_id': member_id,
            'brand_id': self.brand_id,
            'phone': phone,
            'name': None,
            'gender': None,
            'birthday': None,
            'address': None,
            'email': None,
            'total_spend_fen': 0,
            'visit_count': 0,
            'preferred_dishes': [],
            'tags': set(),
            'sources': set(),
            'last_visit': None,
            'first_registered_at': None,
            'spend_by_channel': {},
            'visit_by_channel': {},
        }

        # 如果有现有数据，先加载
        if existing:
            merged['name'] = existing.get('name')
            merged['gender'] = existing.get('gender')
            merged['birthday'] = existing.get('birthday')
            merged['address'] = existing.get('address')
            merged['email'] = existing.get('email')
            merged['total_spend_fen'] = existing.get('total_spend_fen', 0)
            merged['visit_count'] = existing.get('visit_count', 0)
            merged['preferred_dishes'] = existing.get('preferred_dishes', [])
            merged['tags'] = set(existing.get('tags', []))
            merged['sources'] = set(existing.get('sources', []))
            merged['last_visit'] = existing.get('last_visit')
            merged['first_registered_at'] = existing.get('first_registered_at')
            merged['spend_by_channel'] = existing.get('spend_by_channel', {})
            merged['visit_by_channel'] = existing.get('visit_by_channel', {})

        conflicts: list[dict] = []
        latest_update_time: Optional[str] = None

        # 按渠道合并
        for profile in profiles:
            source = profile.get('source', 'unknown')
            merged['sources'].add(source)

            # 基本信息：latest update wins
            registered = profile.get('registered_at') or profile.get('last_visit')
            if registered:
                if latest_update_time is None or registered > latest_update_time:
                    latest_update_time = registered

                    # 合并基本信息（有值就覆盖）
                    for field in ('name', 'gender', 'birthday', 'address', 'email'):
                        new_val = profile.get(field)
                        old_val = merged.get(field)
                        if new_val:
                            if old_val and old_val != new_val:
                                conflicts.append({
                                    'field': field,
                                    'old_value': old_val,
                                    'new_value': new_val,
                                    'source': source,
                                    'resolution': 'latest_wins',
                                })
                            merged[field] = new_val

            # 消费金额：累加
            spend = profile.get('total_spend_fen', 0)
            if spend > 0:
                merged['total_spend_fen'] += spend
                merged['spend_by_channel'][source] = (
                    merged['spend_by_channel'].get(source, 0) + spend
                )

            # 访问次数：累加
            visits = profile.get('visit_count', 0)
            if visits > 0:
                merged['visit_count'] += visits
                merged['visit_by_channel'][source] = (
                    merged['visit_by_channel'].get(source, 0) + visits
                )

            # 偏好菜品：合并去重
            dishes = profile.get('preferred_dishes', [])
            for d in dishes:
                if d not in merged['preferred_dishes']:
                    merged['preferred_dishes'].append(d)

            # 标签：合并
            tags = profile.get('tags', [])
            merged['tags'].update(tags)

            # 最后访问时间
            last_visit = profile.get('last_visit')
            if last_visit:
                if merged['last_visit'] is None or last_visit > merged['last_visit']:
                    merged['last_visit'] = last_visit

            # 首次注册时间
            reg_at = profile.get('registered_at')
            if reg_at:
                if merged['first_registered_at'] is None or reg_at < merged['first_registered_at']:
                    merged['first_registered_at'] = reg_at

        # 计算RFM和生命周期
        rfm = self._calculate_rfm(merged)
        lifecycle = self._determine_lifecycle(merged, rfm)

        # 转换set为list以便序列化
        merged['tags'] = list(merged['tags'])
        merged['sources'] = list(merged['sources'])
        merged['rfm'] = rfm
        merged['lifecycle'] = lifecycle
        merged['updated_at'] = datetime.now(timezone.utc).isoformat()

        # 存储
        _golden_profiles[member_id] = merged
        _phone_to_member[phone] = member_id

        logger.info(
            "golden_id_merged",
            member_id=member_id,
            phone=phone[-4:],  # 只记录末四位
            source_count=len(merged['sources']),
            total_spend_fen=merged['total_spend_fen'],
            visit_count=merged['visit_count'],
            conflicts=len(conflicts),
        )

        return {
            'member_id': member_id,
            'phone': phone,
            'merged_profile': merged,
            'source_count': len(merged['sources']),
            'conflicts': conflicts,
        }

    def get_golden_profile(self, member_id: str) -> dict:
        """获取统一会员画像

        Returns:
            {basic, spend_by_channel, preferred_dishes, rfm, lifecycle, touchpoints}
        """
        if member_id not in _golden_profiles:
            raise ValueError(f"会员不存在: {member_id}")

        profile = _golden_profiles[member_id]

        # 重新计算RFM（可能数据已更新）
        rfm = self._calculate_rfm(profile)
        lifecycle = self._determine_lifecycle(profile, rfm)

        return {
            'member_id': profile['member_id'],
            'brand_id': profile.get('brand_id', ''),
            'phone': profile['phone'],
            'basic': {
                'name': profile.get('name'),
                'gender': profile.get('gender'),
                'birthday': profile.get('birthday'),
                'address': profile.get('address'),
                'email': profile.get('email'),
            },
            'total_spend_fen': profile.get('total_spend_fen', 0),
            'visit_count': profile.get('visit_count', 0),
            'spend_by_channel': profile.get('spend_by_channel', {}),
            'visit_by_channel': profile.get('visit_by_channel', {}),
            'preferred_dishes': profile.get('preferred_dishes', []),
            'tags': profile.get('tags', []),
            'sources': profile.get('sources', []),
            'rfm': rfm,
            'lifecycle': lifecycle,
            'first_registered_at': profile.get('first_registered_at'),
            'last_visit': profile.get('last_visit'),
            'updated_at': profile.get('updated_at'),
        }

    def enrich_from_order(self, member_id: str, order_data: dict) -> dict:
        """从订单数据自动充实会员画像

        Args:
            order_data: {order_id, order_no, channel, total_fen, items, order_time}
                items: [{name, quantity, price_fen}]

        Returns:
            {member_id, updated_fields, new_spend_total, new_visit_count}
        """
        if member_id not in _golden_profiles:
            raise ValueError(f"会员不存在: {member_id}")

        profile = _golden_profiles[member_id]
        updated_fields: list[str] = []

        # 更新消费总额
        order_total = order_data.get('total_fen', 0)
        if order_total > 0:
            profile['total_spend_fen'] += order_total
            updated_fields.append('total_spend_fen')

        # 更新渠道消费
        channel = order_data.get('channel', 'dine_in')
        if channel:
            if 'spend_by_channel' not in profile:
                profile['spend_by_channel'] = {}
            profile['spend_by_channel'][channel] = (
                profile['spend_by_channel'].get(channel, 0) + order_total
            )
            updated_fields.append('spend_by_channel')

        # 更新到访次数
        profile['visit_count'] = profile.get('visit_count', 0) + 1
        updated_fields.append('visit_count')
        if channel:
            if 'visit_by_channel' not in profile:
                profile['visit_by_channel'] = {}
            profile['visit_by_channel'][channel] = (
                profile['visit_by_channel'].get(channel, 0) + 1
            )

        # 更新菜品偏好
        items = order_data.get('items', [])
        for item in items:
            name = item.get('name', '')
            if name and name not in profile.get('preferred_dishes', []):
                if 'preferred_dishes' not in profile:
                    profile['preferred_dishes'] = []
                profile['preferred_dishes'].append(name)
                updated_fields.append('preferred_dishes')

        # 更新最后访问时间
        order_time = order_data.get('order_time', datetime.now(timezone.utc).isoformat())
        profile['last_visit'] = order_time
        updated_fields.append('last_visit')

        # 添加渠道源
        if 'sources' not in profile:
            profile['sources'] = []
        if channel not in profile['sources']:
            profile['sources'].append(channel)

        # 记录触点
        touchpoint = {
            'event_type': 'order',
            'channel': channel,
            'order_id': order_data.get('order_id', ''),
            'order_no': order_data.get('order_no', ''),
            'amount_fen': order_total,
            'items': [i.get('name', '') for i in items],
            'timestamp': order_time,
        }
        if member_id not in _touchpoints:
            _touchpoints[member_id] = []
        _touchpoints[member_id].append(touchpoint)

        profile['updated_at'] = datetime.now(timezone.utc).isoformat()

        logger.info(
            "profile_enriched",
            member_id=member_id,
            channel=channel,
            order_total_fen=order_total,
            updated_fields=updated_fields,
        )

        return {
            'member_id': member_id,
            'updated_fields': list(set(updated_fields)),
            'new_spend_total_fen': profile['total_spend_fen'],
            'new_visit_count': profile['visit_count'],
        }

    def get_cross_channel_journey(self, member_id: str) -> list[dict]:
        """获取跨渠道客户旅程时间线

        Returns:
            [{timestamp, channel, event_type, details}] 按时间排序
        """
        if member_id not in _golden_profiles:
            raise ValueError(f"会员不存在: {member_id}")

        events = _touchpoints.get(member_id, [])

        # 按时间排序
        sorted_events = sorted(events, key=lambda e: e.get('timestamp', ''))

        journey: list[dict] = []
        for evt in sorted_events:
            journey.append({
                'timestamp': evt.get('timestamp', ''),
                'channel': evt.get('channel', ''),
                'event_type': evt.get('event_type', ''),
                'order_no': evt.get('order_no', ''),
                'amount_fen': evt.get('amount_fen', 0),
                'items': evt.get('items', []),
                'details': {
                    k: v for k, v in evt.items()
                    if k not in ('timestamp', 'channel', 'event_type')
                },
            })

        return journey

    def calculate_ltv(self, member_id: str) -> dict:
        """预测会员终身价值 (LTV)

        基于历史消费模式预测:
        LTV = ARPU * 预期活跃月数 * 留存率

        Returns:
            {member_id, historical_spend_fen, avg_order_fen, frequency_per_month,
             predicted_active_months, retention_rate, predicted_ltv_fen}
        """
        if member_id not in _golden_profiles:
            raise ValueError(f"会员不存在: {member_id}")

        profile = _golden_profiles[member_id]

        total_spend = profile.get('total_spend_fen', 0)
        visit_count = profile.get('visit_count', 0)
        first_reg = profile.get('first_registered_at')
        last_visit = profile.get('last_visit')

        # 平均客单价
        avg_order_fen = total_spend // visit_count if visit_count > 0 else 0

        # 计算活跃月数
        months_active = 1
        if first_reg and last_visit:
            try:
                first_dt = datetime.fromisoformat(first_reg) if isinstance(first_reg, str) else first_reg
                last_dt = datetime.fromisoformat(last_visit) if isinstance(last_visit, str) else last_visit
                delta = last_dt - first_dt
                months_active = max(1, delta.days / 30)
            except (ValueError, TypeError):
                months_active = 1

        # 月均消费频次
        frequency_per_month = round(visit_count / months_active, 2)

        # 留存率估算（基于RFM）
        rfm = self._calculate_rfm(profile)
        if rfm['recency_level'] == 'active':
            retention_rate = 0.85
        elif rfm['recency_level'] == 'warm':
            retention_rate = 0.60
        elif rfm['recency_level'] == 'cold':
            retention_rate = 0.30
        else:
            retention_rate = 0.10

        # 预期活跃月数
        predicted_active_months = round(1 / (1 - retention_rate)) if retention_rate < 1 else 36

        # 月均消费金额
        monthly_spend = avg_order_fen * frequency_per_month

        # LTV = 月均消费 * 预期活跃月数
        predicted_ltv_fen = round(monthly_spend * predicted_active_months)

        return {
            'member_id': member_id,
            'historical_spend_fen': total_spend,
            'visit_count': visit_count,
            'avg_order_fen': avg_order_fen,
            'months_active': round(months_active, 1),
            'frequency_per_month': frequency_per_month,
            'retention_rate': retention_rate,
            'predicted_active_months': predicted_active_months,
            'monthly_spend_fen': round(monthly_spend),
            'predicted_ltv_fen': predicted_ltv_fen,
        }

    def detect_duplicate(self, phone: str, name: Optional[str] = None) -> list[dict]:
        """检测潜在重复会员

        匹配策略:
        1. 完全手机号匹配
        2. 相同姓名 + 相近手机号

        Returns:
            [{member_id, phone, name, match_type, confidence}]
        """
        duplicates: list[dict] = []

        # 1. 精确手机号匹配
        if phone in _phone_to_member:
            mid = _phone_to_member[phone]
            profile = _golden_profiles.get(mid, {})
            duplicates.append({
                'member_id': mid,
                'phone': phone,
                'name': profile.get('name', ''),
                'match_type': 'exact_phone',
                'confidence': 1.0,
                'total_spend_fen': profile.get('total_spend_fen', 0),
                'visit_count': profile.get('visit_count', 0),
            })

        # 2. 相近手机号匹配（末8位相同）
        phone_suffix = phone[-8:] if len(phone) >= 8 else phone
        for stored_phone, mid in _phone_to_member.items():
            if stored_phone == phone:
                continue
            if stored_phone.endswith(phone_suffix):
                profile = _golden_profiles.get(mid, {})
                duplicates.append({
                    'member_id': mid,
                    'phone': stored_phone,
                    'name': profile.get('name', ''),
                    'match_type': 'similar_phone',
                    'confidence': 0.7,
                    'total_spend_fen': profile.get('total_spend_fen', 0),
                    'visit_count': profile.get('visit_count', 0),
                })

        # 3. 同名匹配
        if name:
            for mid, profile in _golden_profiles.items():
                if profile.get('name') == name and profile.get('phone') != phone:
                    already = any(d['member_id'] == mid for d in duplicates)
                    if not already:
                        duplicates.append({
                            'member_id': mid,
                            'phone': profile.get('phone', ''),
                            'name': name,
                            'match_type': 'same_name',
                            'confidence': 0.4,
                            'total_spend_fen': profile.get('total_spend_fen', 0),
                            'visit_count': profile.get('visit_count', 0),
                        })

        return sorted(duplicates, key=lambda d: d['confidence'], reverse=True)

    # ─── 内部方法 ───

    def _calculate_rfm(self, profile: dict) -> dict:
        """计算RFM评分"""
        now = datetime.now(timezone.utc)

        # R: Recency
        last_visit = profile.get('last_visit')
        recency_days = 999
        if last_visit:
            try:
                last_dt = datetime.fromisoformat(last_visit) if isinstance(last_visit, str) else last_visit
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                recency_days = (now - last_dt).days
            except (ValueError, TypeError):
                recency_days = 999

        thresholds = self.RFM_THRESHOLDS
        if recency_days <= thresholds['recency_days']['active']:
            recency_level = 'active'
            recency_score = 5
        elif recency_days <= thresholds['recency_days']['warm']:
            recency_level = 'warm'
            recency_score = 3
        elif recency_days <= thresholds['recency_days']['cold']:
            recency_level = 'cold'
            recency_score = 2
        else:
            recency_level = 'lost'
            recency_score = 1

        # F: Frequency
        visit_count = profile.get('visit_count', 0)
        if visit_count >= thresholds['frequency']['high']:
            frequency_level = 'high'
            frequency_score = 5
        elif visit_count >= thresholds['frequency']['medium']:
            frequency_level = 'medium'
            frequency_score = 3
        else:
            frequency_level = 'low'
            frequency_score = 1

        # M: Monetary
        total_spend = profile.get('total_spend_fen', 0)
        if total_spend >= thresholds['monetary_fen']['high']:
            monetary_level = 'high'
            monetary_score = 5
        elif total_spend >= thresholds['monetary_fen']['medium']:
            monetary_level = 'medium'
            monetary_score = 3
        else:
            monetary_level = 'low'
            monetary_score = 1

        # 综合评分
        total_score = recency_score + frequency_score + monetary_score

        # 会员等级
        if total_score >= 13:
            tier = 'diamond'
        elif total_score >= 10:
            tier = 'gold'
        elif total_score >= 7:
            tier = 'silver'
        else:
            tier = 'bronze'

        return {
            'recency_days': recency_days,
            'recency_level': recency_level,
            'recency_score': recency_score,
            'frequency': visit_count,
            'frequency_level': frequency_level,
            'frequency_score': frequency_score,
            'monetary_fen': total_spend,
            'monetary_level': monetary_level,
            'monetary_score': monetary_score,
            'total_score': total_score,
            'tier': tier,
        }

    def _determine_lifecycle(self, profile: dict, rfm: dict) -> str:
        """判定会员生命周期阶段"""
        visit_count = profile.get('visit_count', 0)
        recency_level = rfm.get('recency_level', 'lost')

        if visit_count <= 1:
            return 'new'
        elif visit_count <= 3 and recency_level == 'active':
            return 'growing'
        elif visit_count > 3 and recency_level == 'active':
            return 'mature'
        elif recency_level == 'warm':
            return 'declining'
        elif recency_level == 'cold':
            return 'dormant'
        else:
            return 'lost'

    @staticmethod
    def clear_all_data():
        """清除所有内存数据（测试用）"""
        _golden_profiles.clear()
        _phone_to_member.clear()
        _touchpoints.clear()
