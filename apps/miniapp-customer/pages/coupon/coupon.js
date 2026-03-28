// 优惠券页 — 可用券列表 + 核销
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    filter: 'available',
    coupons: [],
    emptyText: '暂无可用优惠券',
    loading: false,
  },

  onLoad: function () {
    this.loadCoupons();
  },

  onShow: function () {
    this.loadCoupons();
  },

  onPullDownRefresh: function () {
    var self = this;
    this.loadCoupons().then(function () {
      wx.stopPullDownRefresh();
    });
  },

  onShareAppMessage: function () {
    return { title: '屯象点餐 - 优惠券', path: '/pages/coupon/coupon' };
  },

  setFilter: function (e) {
    var filter = e.currentTarget.dataset.filter;
    var emptyMap = {
      available: '暂无可用优惠券',
      used: '暂无已使用的优惠券',
      expired: '暂无已过期的优惠券',
    };
    this.setData({ filter: filter, emptyText: emptyMap[filter] });
    this.loadCoupons();
  },

  loadCoupons: function () {
    var self = this;
    self.setData({ loading: true });

    return api.fetchCoupons(self.data.filter)
      .then(function (data) {
        var coupons = (data.items || []).map(function (c) {
          return self.formatCoupon(c);
        });
        self.setData({ coupons: coupons, loading: false });
      })
      .catch(function (err) {
        console.error('loadCoupons failed', err);
        self.setData({ loading: false });
      });
  },

  formatCoupon: function (coupon) {
    // 门槛文案
    var thresholdText = '无门槛';
    if (coupon.threshold_amount && coupon.threshold_amount > 0) {
      thresholdText = '满' + (coupon.threshold_amount / 100) + '元可用';
    }

    // 有效期文案
    var expireText = '';
    if (coupon.expire_at) {
      expireText = '有效期至 ' + coupon.expire_at.slice(0, 10);
    }

    // 使用条件
    var condition = '';
    if (coupon.applicable_scope === 'specific_dishes') {
      condition = '限指定菜品使用';
    } else if (coupon.applicable_scope === 'specific_category') {
      condition = '限指定品类使用';
    } else if (coupon.applicable_scope === 'specific_stores') {
      condition = '限指定门店使用';
    }

    // 折扣值展示
    var discountValue = '';
    if (coupon.type === 'reduction') {
      discountValue = String(coupon.discount_value / 100);
    } else if (coupon.type === 'discount') {
      discountValue = String(coupon.discount_value / 10);
    }

    return {
      id: coupon.id,
      name: coupon.name,
      type: coupon.type,
      status: coupon.status,
      thresholdText: thresholdText,
      expireText: expireText,
      condition: condition,
      discountValue: discountValue,
    };
  },

  useCoupon: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.switchTab({ url: '/pages/menu/menu' });
  },
});
