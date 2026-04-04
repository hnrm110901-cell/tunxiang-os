// 我的卡包 — 可使用 / 已使用 / 已过期
// API:
//   GET /api/v1/member/coupons?customer_id=&status=  我的优惠券列表

var api = require('../../utils/api.js');

Page({
  data: {
    activeTab: 'unused',

    // 可使用
    unusedList: [],
    unusedCount: 0,
    loading: false,

    // 已使用
    usedList: [],
    usedLoading: false,

    // 已过期
    expiredList: [],
    expiredLoading: false,

    // 展开详情
    expandedId: ''
  },

  onLoad: function () {
    this._loadUnused();
  },

  onShow: function () {
    if (this.data.activeTab === 'unused') {
      this._loadUnused();
    }
  },

  onPullDownRefresh: function () {
    var self = this;
    self._reloadCurrentTab().then(function () {
      wx.stopPullDownRefresh();
    }).catch(function () {
      wx.stopPullDownRefresh();
    });
  },

  onShareAppMessage: function () {
    return { title: '我的卡包 - 屯象点餐', path: '/pages/my-coupons/my-coupons' };
  },

  // ─── Tab切换 ───

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    this.setData({ activeTab: tab, expandedId: '' });
    this._reloadCurrentTab();
  },

  _reloadCurrentTab: function () {
    var tab = this.data.activeTab;
    if (tab === 'unused') return this._loadUnused();
    if (tab === 'used') return this._loadUsed();
    if (tab === 'expired') return this._loadExpired();
    return Promise.resolve();
  },

  // ─── 展开/折叠 ───

  toggleExpand: function (e) {
    var id = e.currentTarget.dataset.id;
    this.setData({
      expandedId: this.data.expandedId === id ? '' : id
    });
  },

  // ─── 格式化 ───

  _formatCoupon: function (c) {
    var couponType = c.coupon_type || c.type || 'reduction';
    var faceValue = '';
    if (couponType === 'reduction' || couponType === 'cash') {
      faceValue = String(Math.round((c.cash_amount_fen || c.discount_value || 0) / 100));
    } else if (couponType === 'discount') {
      faceValue = ((c.discount_rate || c.discount_value || 0) / 10).toFixed(1).replace('.0', '');
    }

    var thresholdText = '无门槛';
    if ((c.min_order_fen || c.threshold_amount) > 0) {
      thresholdText = '满' + Math.round((c.min_order_fen || c.threshold_amount) / 100) + '元可用';
    }

    var expireText = '';
    var expireSoon = false;
    if (c.expire_at) {
      var expireDate = new Date(c.expire_at);
      var now = new Date();
      var diffDays = Math.ceil((expireDate - now) / (1000 * 60 * 60 * 24));
      expireText = '有效期至 ' + c.expire_at.slice(0, 10);
      if (diffDays <= 3 && diffDays >= 0) expireSoon = true;
    } else if (c.end_date) {
      expireText = '有效期至 ' + c.end_date.slice(0, 10);
    }

    var condition = '';
    var scope = c.applicable_scope;
    if (scope === 'specific_dishes') condition = '限指定菜品';
    else if (scope === 'specific_category') condition = '限指定品类';
    else if (scope === 'specific_stores') condition = '限指定门店';

    var storeText = '';
    if (c.applicable_stores && c.applicable_stores.length > 0) {
      storeText = '适用门店: ' + c.applicable_stores.join('、');
    }

    return {
      id: c.id || c.coupon_id || c.customer_coupon_id || '',
      couponId: c.coupon_id || c.id || '',
      name: c.name || c.coupon_name || '',
      couponType: couponType,
      faceValue: faceValue,
      thresholdText: thresholdText,
      expireText: expireText,
      expireSoon: expireSoon,
      condition: condition,
      storeText: storeText,
      ruleText: c.rule_text || c.description || '',
      applicableDishes: c.applicable_dishes || '',
      couponCode: c.coupon_code || '',
      status: c.status || 'unused'
    };
  },

  // ─── 加载数据 ───

  _loadUnused: function () {
    var self = this;
    self.setData({ loading: true });
    var customerId = wx.getStorageSync('tx_customer_id') || '';

    return api.txRequest(
      '/api/v1/member/coupons?customer_id=' + encodeURIComponent(customerId) + '&status=available'
    ).then(function (data) {
      var items = (data.items || data || []).map(function (c) {
        return self._formatCoupon(c);
      });
      self.setData({ unusedList: items, unusedCount: items.length, loading: false });
    }).catch(function () {
      // 降级Mock
      var mock = self._getMockUnused();
      self.setData({ unusedList: mock, unusedCount: mock.length, loading: false });
    });
  },

  _loadUsed: function () {
    var self = this;
    self.setData({ usedLoading: true });
    var customerId = wx.getStorageSync('tx_customer_id') || '';

    return api.txRequest(
      '/api/v1/member/coupons?customer_id=' + encodeURIComponent(customerId) + '&status=used'
    ).then(function (data) {
      var items = (data.items || data || []).map(function (c) {
        return self._formatCoupon(c);
      });
      self.setData({ usedList: items, usedLoading: false });
    }).catch(function () {
      self.setData({ usedList: [], usedLoading: false });
    });
  },

  _loadExpired: function () {
    var self = this;
    self.setData({ expiredLoading: true });
    var customerId = wx.getStorageSync('tx_customer_id') || '';

    return api.txRequest(
      '/api/v1/member/coupons?customer_id=' + encodeURIComponent(customerId) + '&status=expired'
    ).then(function (data) {
      var items = (data.items || data || []).map(function (c) {
        return self._formatCoupon(c);
      });
      self.setData({ expiredList: items, expiredLoading: false });
    }).catch(function () {
      self.setData({ expiredList: [], expiredLoading: false });
    });
  },

  // ─── 操作 ───

  onUse: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: '/pages/coupon-use/coupon-use?id=' + encodeURIComponent(id)
    });
  },

  goToCouponCenter: function () {
    wx.navigateTo({ url: '/pages/coupon-center/coupon-center' });
  },

  // ─── Mock ───

  _getMockUnused: function () {
    return [
      {
        id: 'mock-u1',
        couponId: 'mock-u1',
        name: '满100减20',
        couponType: 'reduction',
        faceValue: '20',
        thresholdText: '满100元可用',
        expireText: '有效期至 2026-04-30',
        expireSoon: false,
        condition: '',
        storeText: '',
        ruleText: '本券可在所有门店使用，不可与其他优惠叠加使用',
        applicableDishes: '',
        couponCode: 'TX20260402A1',
        status: 'unused'
      },
      {
        id: 'mock-u2',
        couponId: 'mock-u2',
        name: '8.5折体验券',
        couponType: 'discount',
        faceValue: '8.5',
        thresholdText: '满50元可用',
        expireText: '有效期至 2026-04-05',
        expireSoon: true,
        condition: '限指定菜品',
        storeText: '',
        ruleText: '仅限招牌菜系列使用',
        applicableDishes: '剁椒鱼头、湘味小炒肉、口味虾',
        couponCode: 'TX20260402B2',
        status: 'unused'
      }
    ];
  }
});
