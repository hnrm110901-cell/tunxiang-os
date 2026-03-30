// Points Mall -- redeem points for dishes, coupons, merchandise
// Inspired by: Starbucks Stars + KFC V-Gold

var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // Categories
    categories: [
      { key: 'all', label: '全部' },
      { key: 'dish', label: '菜品' },
      { key: 'coupon', label: '优惠券' },
      { key: 'merchandise', label: '周边' },
    ],
    activeCategory: 'all',
    // Points balance
    pointsBalance: 0,
    // Mall items
    items: [],
    loading: true,
    page: 1,
    hasMore: false,
    // Achievements
    achievements: [],
    earnedCount: 0,
    totalCount: 0,
    showAchievements: false,
    // Redemption
    showRedeemConfirm: false,
    redeemItem: null,
  },

  onLoad: function () {
    this._loadPoints();
    this._loadItems();
  },

  onShow: function () {
    this._loadPoints();
  },

  onPullDownRefresh: function () {
    var self = this;
    self.setData({ page: 1, items: [] });
    Promise.all([self._loadPoints(), self._loadItems()])
      .then(function () { wx.stopPullDownRefresh(); })
      .catch(function () { wx.stopPullDownRefresh(); });
  },

  onReachBottom: function () {
    if (this.data.hasMore) {
      this.setData({ page: this.data.page + 1 });
      this._loadItems();
    }
  },

  onShareAppMessage: function () {
    return { title: '积分商城 - 屯象点餐', path: '/pages/points-mall/points-mall' };
  },

  // ─── Data loading ───

  _loadPoints: function () {
    var self = this;
    return api.fetchMemberProfile()
      .then(function (data) {
        self.setData({ pointsBalance: data.points_balance || 0 });
      })
      .catch(function () {});
  },

  _loadItems: function () {
    var self = this;
    self.setData({ loading: true });
    var cat = self.data.activeCategory === 'all' ? '' : self.data.activeCategory;

    return api.fetchMallItems(cat, self.data.page)
      .then(function (data) {
        var newItems = (data.items || []).map(function (item) {
          return {
            id: item.item_id || item.id,
            name: item.name,
            category: item.category,
            pointsCost: item.points_cost,
            stock: item.stock || item.stock_remaining || 0,
            imageUrl: item.image_url || '',
            description: item.description || '',
          };
        });
        var merged = self.data.page > 1 ? self.data.items.concat(newItems) : newItems;
        self.setData({
          items: merged,
          hasMore: newItems.length >= 20,
          loading: false,
        });
      })
      .catch(function () {
        self.setData({ loading: false });
      });
  },

  // ─── Category switch ───

  switchCategory: function (e) {
    this.setData({
      activeCategory: e.currentTarget.dataset.key,
      page: 1,
      items: [],
    });
    this._loadItems();
  },

  // ─── Redeem ───

  onTapRedeem: function (e) {
    var item = e.currentTarget.dataset.item;
    this.setData({ showRedeemConfirm: true, redeemItem: item });
  },

  closeRedeemConfirm: function () {
    this.setData({ showRedeemConfirm: false, redeemItem: null });
  },

  confirmRedeem: function () {
    var self = this;
    var item = self.data.redeemItem;
    if (!item) return;

    if (self.data.pointsBalance < item.pointsCost) {
      wx.showToast({ title: '积分不足', icon: 'none' });
      return;
    }

    api.redeemMallItem(item.id)
      .then(function () {
        wx.showToast({ title: '兑换成功', icon: 'success' });
        self.setData({ showRedeemConfirm: false, redeemItem: null });
        self._loadPoints();
        self._loadItems();
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '兑换失败', icon: 'none' });
      });
  },

  // ─── Achievements ───

  toggleAchievements: function () {
    var self = this;
    if (!self.data.showAchievements && self.data.achievements.length === 0) {
      api.fetchAchievements()
        .then(function (data) {
          self.setData({
            achievements: data.achievements || [],
            earnedCount: data.earned_count || 0,
            totalCount: data.total_count || 0,
            showAchievements: true,
          });
        })
        .catch(function () {
          self.setData({ showAchievements: true });
        });
    } else {
      self.setData({ showAchievements: !self.data.showAchievements });
    }
  },
});
