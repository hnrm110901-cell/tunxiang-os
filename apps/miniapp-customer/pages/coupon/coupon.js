// 优惠券中心 — 可使用 / 可领取 / 已使用/过期
// API:
//   GET  /api/v1/member/coupons?customer_id=       我的优惠券（含状态过滤）
//   GET  /api/v1/growth/coupons/available           可领取的优惠券列表
//   POST /api/v1/growth/coupons/claim               领取优惠券 {coupon_id, customer_id}

var api = require('../../utils/api.js');

Page({
  data: {
    activeTab: 'available',

    // 可使用
    coupons: [],
    loading: false,

    // 可领取
    claimable: [],
    claimableLoading: false,

    // 已使用/过期
    historyList: [],
    historyLoading: false,
  },

  onLoad: function () {
    this._loadAvailable();
  },

  onShow: function () {
    if (this.data.activeTab === 'available') {
      this._loadAvailable();
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
    return { title: '屯象点餐 - 优惠券中心', path: '/pages/coupon/coupon' };
  },

  // ─── Tab切换 ───

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    this.setData({ activeTab: tab });
    this._reloadCurrentTab();
  },

  _reloadCurrentTab: function () {
    var tab = this.data.activeTab;
    if (tab === 'available') return this._loadAvailable();
    if (tab === 'claimable') return this._loadClaimable();
    if (tab === 'history') return this._loadHistory();
    return Promise.resolve();
  },

  // ─── 工具：格式化优惠券 ───

  _formatCoupon: function (c) {
    // 折扣展示
    var discountDisplay = '';
    if (c.type === 'reduction') {
      discountDisplay = String(Math.round((c.discount_value || 0) / 100));
    } else if (c.type === 'discount') {
      discountDisplay = ((c.discount_value || 0) / 10).toFixed(1).replace('.0', '');
    }

    // 门槛文案
    var thresholdText = '无门槛';
    if (c.threshold_amount && c.threshold_amount > 0) {
      thresholdText = '满' + Math.round(c.threshold_amount / 100) + '元可用';
    }

    // 到期时间
    var expireText = '';
    var expireSoon = false;
    if (c.expire_at) {
      var expireDate = new Date(c.expire_at);
      var now = new Date();
      var diffDays = Math.ceil((expireDate - now) / (1000 * 60 * 60 * 24));
      expireText = '有效期至 ' + c.expire_at.slice(0, 10);
      if (diffDays <= 3 && diffDays >= 0) expireSoon = true;
    }

    // 使用条件
    var condition = '';
    var scope = c.applicable_scope;
    if (scope === 'specific_dishes') condition = '限指定菜品';
    else if (scope === 'specific_category') condition = '限指定品类';
    else if (scope === 'specific_stores') condition = '限指定门店';

    // 左侧背景色类型
    var colorType = 'orange';
    if (c.type === 'discount') colorType = 'green';
    else if (c.type === 'gift') colorType = 'blue';

    return {
      id: c.id || c.coupon_id,
      name: c.name || c.coupon_name || '',
      type: c.type || 'reduction',
      status: c.status || 'available',
      discountDisplay: discountDisplay,
      thresholdText: thresholdText,
      expireText: expireText,
      expireSoon: expireSoon,
      condition: condition,
      colorType: colorType,
    };
  },

  // ─── 可使用优惠券 ───

  _loadAvailable: function () {
    var self = this;
    self.setData({ loading: true });
    var customerId = wx.getStorageSync('tx_customer_id') || '';
    return api.txRequest(
      '/api/v1/member/coupons?customer_id=' + encodeURIComponent(customerId) + '&status=available'
    ).then(function (data) {
      var items = (data.items || data || []).map(function (c) {
        return self._formatCoupon(c);
      });
      self.setData({ coupons: items, loading: false });
    }).catch(function () {
      // 降级到旧接口
      return api.fetchCoupons('available')
        .then(function (data) {
          var items = (data.items || data || []).map(function (c) {
            return self._formatCoupon(c);
          });
          self.setData({ coupons: items, loading: false });
        })
        .catch(function () {
          self.setData({ loading: false });
        });
    });
  },

  // 点击"去使用"
  useCoupon: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/menu/menu?coupon_id=' + encodeURIComponent(id) });
  },

  // ─── 可领取优惠券 ───

  _loadClaimable: function () {
    var self = this;
    var customerId = wx.getStorageSync('tx_customer_id') || '';
    self.setData({ claimableLoading: true });
    return api.txRequest('/api/v1/growth/coupons/available')
      .then(function (data) {
        // 标记已领取状态（后端返回字段 is_claimed / claimed_by_user）
        var items = (data.items || data || []).map(function (c) {
          var validText = '';
          if (c.valid_days) validText = '领取后' + c.valid_days + '天内有效';
          else if (c.expire_at) validText = '有效至 ' + c.expire_at.slice(0, 10);

          var thresholdText = '无门槛';
          if (c.threshold_amount && c.threshold_amount > 0) {
            thresholdText = '满' + Math.round(c.threshold_amount / 100) + '元可用';
          }

          var discountDisplay = '';
          if (c.type === 'reduction') {
            discountDisplay = String(Math.round((c.discount_value || 0) / 100));
          } else if (c.type === 'discount') {
            discountDisplay = ((c.discount_value || 0) / 10).toFixed(1).replace('.0', '');
          }

          var condition = '';
          if (c.applicable_scope === 'specific_dishes') condition = '限指定菜品';
          else if (c.applicable_scope === 'specific_category') condition = '限指定品类';
          else if (c.applicable_scope === 'specific_stores') condition = '限指定门店';

          var colorType = 'orange';
          if (c.type === 'discount') colorType = 'green';
          else if (c.type === 'gift') colorType = 'blue';

          return {
            id: c.id || c.coupon_id,
            name: c.name || c.coupon_name || '',
            type: c.type || 'reduction',
            discountDisplay: discountDisplay,
            thresholdText: thresholdText,
            validText: validText,
            condition: condition,
            colorType: colorType,
            claimed: !!(c.is_claimed || c.claimed_by_user),
          };
        });
        self.setData({ claimable: items, claimableLoading: false });
      })
      .catch(function () {
        self.setData({ claimableLoading: false });
      });
  },

  // 领取优惠券
  claimCoupon: function (e) {
    var self = this;
    var couponId = e.currentTarget.dataset.id;
    var customerId = wx.getStorageSync('tx_customer_id') || '';

    if (!customerId) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '领取中...' });
    api.txRequest('/api/v1/growth/coupons/claim', 'POST', {
      coupon_id: couponId,
      customer_id: customerId,
    }).then(function () {
      wx.hideLoading();
      wx.showToast({ title: '领取成功！', icon: 'success' });
      // 更新对应卡片状态
      var claimable = self.data.claimable.map(function (c) {
        if (c.id === couponId) return Object.assign({}, c, { claimed: true });
        return c;
      });
      self.setData({ claimable: claimable });
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({
        title: (err && err.message) || '领取失败',
        icon: 'none',
      });
    });
  },

  // ─── 已使用/过期 ───

  _loadHistory: function () {
    var self = this;
    var customerId = wx.getStorageSync('tx_customer_id') || '';
    self.setData({ historyLoading: true });
    return api.txRequest(
      '/api/v1/member/coupons?customer_id=' + encodeURIComponent(customerId) + '&status=used_or_expired'
    ).then(function (data) {
      var usedExpired = (data.items || data || []).map(function (c) {
        return self._formatCoupon(c);
      });
      self.setData({ historyList: usedExpired, historyLoading: false });
    }).catch(function () {
      // 降级：分别拉取 used 和 expired 再合并
      Promise.all([
        api.fetchCoupons('used'),
        api.fetchCoupons('expired'),
      ]).then(function (results) {
        var used = (results[0].items || results[0] || []).map(function (c) {
          return self._formatCoupon(Object.assign({}, c, { status: 'used' }));
        });
        var expired = (results[1].items || results[1] || []).map(function (c) {
          return self._formatCoupon(Object.assign({}, c, { status: 'expired' }));
        });
        self.setData({ historyList: used.concat(expired), historyLoading: false });
      }).catch(function () {
        self.setData({ historyLoading: false });
      });
    });
  },
});
