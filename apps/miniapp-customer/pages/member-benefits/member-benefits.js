// 会员权益页 — 等级权益展示 / 等级对比 / 积分获取方式
// API:
//   GET /api/v1/member/tiers               等级配置列表
//   GET /api/v1/member/profile?customer_id= 当前会员信息（含积分/等级）

var api = require('../../utils/api.js');

// ─── 默认等级配置（API 失败时降级）───

var MOCK_TIERS = [
  { level: 1, name: '普通会员', icon: '⭐', discount: '无', multiplier: 1, birthday: 10, delivery: '≥50元', min_points: 0 },
  { level: 2, name: '银卡会员', icon: '🥈', discount: '9.5折', multiplier: 1.2, birthday: 30, delivery: '≥30元', min_points: 500 },
  { level: 3, name: '金卡会员', icon: '🥇', discount: '9折', multiplier: 1.5, birthday: 88, delivery: '免费', min_points: 2000 },
  { level: 4, name: '黑金会员', icon: '💎', discount: '8.8折', multiplier: 2.0, birthday: 288, delivery: '免费', min_points: 8000 },
];

var MOCK_EARN_METHODS = [
  { id: 'e1', icon: '🍽️', name: '消费得积分', desc: '每消费1元得10积分', points: 10, action: 'spend' },
  { id: 'e2', icon: '✍️', name: '评价有礼', desc: '完成评价得50积分', points: 50, action: 'review' },
  { id: 'e3', icon: '👥', name: '邀请好友', desc: '每成功邀请得200积分', points: 200, action: 'invite' },
  { id: 'e4', icon: '📱', name: '签到打卡', desc: '每日签到得5积分', points: 5, action: 'checkin' },
];

Page({
  data: {
    // 会员基础信息
    nickname: '会员',
    avatarUrl: '',
    points: 0,
    currentLevel: 'normal',   // level key

    // 等级相关
    tier: MOCK_TIERS[0],
    nextTier: MOCK_TIERS[1],
    allTiers: MOCK_TIERS,
    pointsGap: 500,
    progressPct: 0,
    tierClass: 'tier-normal',

    // 本月专属权益
    benefits: [],

    // 获取积分的途径
    earnMethods: MOCK_EARN_METHODS,

    // 加载状态
    loading: true,
  },

  onLoad: function () {
    this._loadAll();
  },

  onShow: function () {
    // 每次显示时刷新积分（可能在其他页面签到/消费后变化）
    this._loadProfile();
  },

  onPullDownRefresh: function () {
    var self = this;
    Promise.all([self._loadProfile(), self._loadTiers()])
      .then(function () { wx.stopPullDownRefresh(); })
      .catch(function () { wx.stopPullDownRefresh(); });
  },

  onShareAppMessage: function () {
    return { title: '会员权益中心 - 屯象点餐', path: '/pages/member-benefits/member-benefits' };
  },

  // ─── 数据加载 ───

  _loadAll: function () {
    var self = this;
    Promise.all([self._loadProfile(), self._loadTiers()])
      .then(function () { self.setData({ loading: false }); })
      .catch(function () { self.setData({ loading: false }); });
  },

  _loadProfile: function () {
    var self = this;
    var customerId = wx.getStorageSync('tx_customer_id') || '';
    var url = '/api/v1/member/profile' + (customerId ? '?customer_id=' + encodeURIComponent(customerId) : '');

    return api.txRequest(url)
      .then(function (data) {
        var points = data.points_balance || data.points || 0;
        self.setData({
          nickname: data.nickname || data.phone || '会员',
          avatarUrl: data.avatar_url || '',
          points: points,
        });
        // 用当前等级配置重新计算进度
        self._calcTierStatus(self.data.allTiers, points);
        // 更新缓存，供其他页面读取
        wx.setStorageSync('tx_points', points);
      })
      .catch(function () {
        // 降级：尝试从 fetchMemberProfile（旧接口）读取
        return api.fetchMemberProfile()
          .then(function (data) {
            var points = data.points_balance || 0;
            self.setData({
              nickname: data.nickname || data.phone || '会员',
              avatarUrl: data.avatar_url || '',
              points: points,
            });
            self._calcTierStatus(self.data.allTiers, points);
            wx.setStorageSync('tx_points', points);
          })
          .catch(function () {
            // 最终降级：使用本地缓存
            var cachedPoints = wx.getStorageSync('tx_points') || 0;
            self.setData({ points: cachedPoints });
            self._calcTierStatus(self.data.allTiers, cachedPoints);
          });
      });
  },

  _loadTiers: function () {
    var self = this;
    return api.txRequest('/api/v1/member/tiers')
      .then(function (data) {
        var tiers = data.tiers || data || [];
        if (!Array.isArray(tiers) || tiers.length === 0) {
          tiers = MOCK_TIERS;
        }
        // 标准化字段名
        tiers = tiers.map(function (t, idx) {
          return {
            level: t.level || idx + 1,
            name: t.name || t.tier_name || '',
            icon: t.icon || ['⭐','🥈','🥇','💎'][idx] || '⭐',
            discount: t.discount || t.discount_text || '无',
            multiplier: t.multiplier || t.points_multiplier || 1,
            birthday: t.birthday_bonus || t.birthday || 0,
            delivery: t.free_delivery || t.delivery_threshold || '无',
            min_points: t.min_points || t.points_threshold || 0,
          };
        });
        self.setData({ allTiers: tiers });
        self._calcTierStatus(tiers, self.data.points);
        self._buildBenefits(tiers);
      })
      .catch(function () {
        self.setData({ allTiers: MOCK_TIERS });
        self._calcTierStatus(MOCK_TIERS, self.data.points);
        self._buildBenefits(MOCK_TIERS);
      });
  },

  // ─── 计算等级进度 ───

  _calcTierStatus: function (tiers, currentPoints) {
    if (!tiers || tiers.length === 0) return;

    var currentTier = tiers[0];
    var nextTier = null;
    var currentIdx = 0;

    for (var i = 0; i < tiers.length; i++) {
      if (currentPoints >= (tiers[i].min_points || 0)) {
        currentTier = tiers[i];
        nextTier = tiers[i + 1] || null;
        currentIdx = i;
      }
    }

    var gap = 0;
    var pct = 100;
    if (nextTier) {
      gap = nextTier.min_points - currentPoints;
      var range = nextTier.min_points - (currentTier.min_points || 0);
      var earned = Math.max(0, currentPoints - (currentTier.min_points || 0));
      pct = range > 0 ? Math.min(100, Math.floor(earned / range * 100)) : 0;
    }

    // 等级对应的样式 class
    var tierClassMap = ['tier-normal', 'tier-silver', 'tier-gold', 'tier-black'];
    var tierClass = tierClassMap[Math.min(currentTier.level - 1, tierClassMap.length - 1)] || 'tier-normal';

    this.setData({
      tier: currentTier,
      nextTier: nextTier,
      pointsGap: gap,
      progressPct: pct,
      tierClass: tierClass,
    });
  },

  // ─── 构建本月权益（从等级配置推导）───

  _buildBenefits: function (tiers) {
    var tier = this.data.tier;
    var benefits = [
      {
        id: 'b-discount',
        icon: '🏷️',
        name: '消费折扣',
        value: tier.discount !== '无' ? tier.discount : '暂无',
        used: false,
      },
      {
        id: 'b-multiplier',
        icon: '⚡',
        name: '积分倍率',
        value: tier.multiplier + '倍积分',
        used: false,
      },
      {
        id: 'b-birthday',
        icon: '🎂',
        name: '生日礼遇',
        value: tier.birthday > 0 ? '¥' + tier.birthday + '红包' : '暂无',
        used: false,
      },
      {
        id: 'b-delivery',
        icon: '🚚',
        name: '免配送费',
        value: tier.delivery,
        used: false,
      },
    ];
    this.setData({ benefits: benefits });
  },

  // ─── 跳转获取积分的途径 ───

  goEarn: function (e) {
    var action = e.currentTarget.dataset.action;
    var routes = {
      review: '/pages/review/review?from=earn_points',
      invite: '/pages/invite/invite',
      checkin: '/pages/checkin/checkin',
    };
    var route = routes[action];
    if (route) {
      wx.navigateTo({ url: route });
    } else if (action === 'spend') {
      wx.showToast({ title: '消费即可自动获得积分', icon: 'none' });
    }
  },

  // ─── 跳转至积分商城 ───

  goPointsMall: function () {
    wx.navigateTo({ url: '/pages/points-mall/points-mall' });
  },

  // ─── 跳转至签到 ───

  goCheckin: function () {
    wx.navigateTo({ url: '/pages/checkin/checkin' });
  },
});
