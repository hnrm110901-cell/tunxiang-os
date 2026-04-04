// 积分商城 — 商品详情页
var api = require('../../utils/api.js');

// Mock商品详情
var MOCK_DETAIL = {
  id: 'mock-1',
  name: '满50减10优惠券',
  category: 'coupon',
  categoryLabel: '优惠券',
  pointsCost: 200,
  originalPrice: 10,
  stock: 99,
  exchangedCount: 156,
  images: ['/assets/dish-placeholder.png', '/assets/dish-placeholder.png', '/assets/dish-placeholder.png'],
  description: '全场消费满50元即可使用，不与其他优惠叠加。每人限兑3张，有效期30天。',
  richContent: '',
  usageRules: [
    '兑换后30天内有效',
    '每人限兑3张',
    '不与其他优惠活动同时使用',
    '仅限堂食消费使用',
    '酒水饮料不参与优惠',
  ],
};

var CATEGORY_MAP = {
  coupon: '优惠券',
  dish: '菜品',
  merchandise: '周边',
  experience: '体验',
};

Page({
  data: {
    itemId: '',
    detail: {},
    images: [],
    usageRules: [],
    pointsBalance: 0,
    canRedeem: false,
    pageLoading: true,
    showUsage: true,
    showConfirm: false,
  },

  onLoad: function (options) {
    var id = options.id || '';
    this.setData({ itemId: id });
    this._loadDetail(id);
    this._loadPoints();
  },

  onShareAppMessage: function () {
    return {
      title: this.data.detail.name || '积分商城好物',
      path: '/pages/points-mall-detail/points-mall-detail?id=' + this.data.itemId,
    };
  },

  // ─── 数据加载 ───

  _loadDetail: function (id) {
    var self = this;
    api.txRequest('/api/v1/points-mall/items/' + encodeURIComponent(id))
      .then(function (data) {
        var detail = {
          id: data.item_id || data.id,
          name: data.name || '',
          category: data.category || '',
          categoryLabel: CATEGORY_MAP[data.category] || data.category || '',
          pointsCost: data.points_cost || 0,
          originalPrice: data.original_price || 0,
          stock: data.stock || data.stock_remaining || 0,
          exchangedCount: data.exchanged_count || data.redeemed_count || 0,
          description: data.description || '',
          richContent: data.rich_content || '',
        };
        var images = data.images || data.image_urls || [];
        if (images.length === 0 && data.image_url) {
          images = [data.image_url, data.image_url, data.image_url];
        }
        if (images.length === 0) {
          images = ['/assets/dish-placeholder.png'];
        }
        var rules = data.usage_rules || data.usage || [];
        if (typeof rules === 'string') {
          rules = rules.split('\n').filter(function (r) { return r.trim(); });
        }
        if (rules.length === 0) {
          rules = ['兑换后30天内有效', '详情以门店实际为准'];
        }
        self.setData({
          detail: detail,
          images: images,
          usageRules: rules,
          pageLoading: false,
        });
        self._checkCanRedeem();
      })
      .catch(function () {
        // 降级Mock
        self.setData({
          detail: MOCK_DETAIL,
          images: MOCK_DETAIL.images,
          usageRules: MOCK_DETAIL.usageRules,
          pageLoading: false,
        });
        self._checkCanRedeem();
      });
  },

  _loadPoints: function () {
    var self = this;
    return api.fetchMemberProfile()
      .then(function (data) {
        self.setData({ pointsBalance: data.points_balance || 0 });
        self._checkCanRedeem();
      })
      .catch(function () {
        self.setData({ pointsBalance: 2580 });
        self._checkCanRedeem();
      });
  },

  _checkCanRedeem: function () {
    var d = this.data.detail;
    if (!d || !d.pointsCost) return;
    this.setData({
      canRedeem: this.data.pointsBalance >= d.pointsCost && d.stock > 0,
    });
  },

  // ─── 交互 ───

  toggleUsage: function () {
    this.setData({ showUsage: !this.data.showUsage });
  },

  onTapRedeem: function () {
    if (!this.data.canRedeem) return;
    this.setData({ showConfirm: true });
  },

  closeConfirm: function () {
    this.setData({ showConfirm: false });
  },

  doRedeem: function () {
    var self = this;
    var detail = self.data.detail;
    if (!detail || !detail.id) return;

    wx.showLoading({ title: '兑换中...' });
    api.redeemMallItem(detail.id, 1)
      .then(function () {
        wx.hideLoading();
        wx.showToast({ title: '兑换成功！', icon: 'success' });
        self.setData({ showConfirm: false });
        // 刷新数据
        self._loadDetail(self.data.itemId);
        self._loadPoints();
      })
      .catch(function (err) {
        wx.hideLoading();
        wx.showToast({
          title: (err && err.message) || '兑换失败，请稍后重试',
          icon: 'none',
        });
      });
  },
});
