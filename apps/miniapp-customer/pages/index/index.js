// 首页 — 门店信息 + 快捷入口 + 附近门店
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    storeName: '',
    storeAddress: '',
    tableNo: '',
    // 快捷入口
    quickEntries: [
      { icon: '🍽️', label: '扫码点餐', route: '/pages/menu/menu' },
      { icon: '🎫', label: '排队取号', route: '/pages/queue/queue' },
      { icon: '📅', label: '预订', route: '/pages/reservation/reservation' },
      { icon: '🎁', label: '优惠券', route: '/pages/coupon/coupon' },
    ],
    // 附近门店列表
    nearbyStores: [],
    loadingStores: false,
    // 当前排队信息
    currentQueue: null,
    // 当前预订
    currentBooking: null,
  },

  onLoad: function (options) {
    if (options.table) {
      this.setData({ tableNo: options.table });
    }
    if (options.store_name) {
      this.setData({ storeName: decodeURIComponent(options.store_name) });
    }
    if (options.coupon_id) {
      // 从优惠券跳入，直接去点餐
      wx.switchTab({ url: '/pages/menu/menu' });
    }
  },

  onShow: function () {
    this._loadStoreInfo();
    this._loadNearbyStores();
  },

  onPullDownRefresh: function () {
    var self = this;
    Promise.all([this._loadStoreInfo(), this._loadNearbyStores()])
      .then(function () { wx.stopPullDownRefresh(); })
      .catch(function () { wx.stopPullDownRefresh(); });
  },

  onShareAppMessage: function () {
    return {
      title: this.data.storeName || '屯象点餐',
      path: '/pages/index/index?store_id=' + app.globalData.storeId,
    };
  },

  _loadStoreInfo: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    if (!storeId) return Promise.resolve();

    return api.fetchStoreDetail(storeId)
      .then(function (data) {
        self.setData({
          storeName: data.name || '屯象点餐',
          storeAddress: data.address || '',
        });
      })
      .catch(function (err) {
        console.warn('加载门店信息失败', err);
      });
  },

  _loadNearbyStores: function () {
    var self = this;
    self.setData({ loadingStores: true });

    return new Promise(function (resolve) {
      wx.getLocation({
        type: 'gcj02',
        success: function (loc) {
          api.fetchNearbyStores(loc.latitude, loc.longitude)
            .then(function (data) {
              var stores = (data.items || []).map(function (s) {
                return {
                  id: s.id,
                  name: s.name,
                  address: s.address || '',
                  distance: s.distance ? (s.distance < 1000 ? s.distance + 'm' : (s.distance / 1000).toFixed(1) + 'km') : '',
                  queueWaiting: s.queue_waiting || 0,
                  businessHours: s.business_hours || '',
                };
              });
              self.setData({ nearbyStores: stores, loadingStores: false });
              resolve();
            })
            .catch(function () {
              self.setData({ loadingStores: false });
              resolve();
            });
        },
        fail: function () {
          self.setData({ loadingStores: false });
          resolve();
        },
      });
    });
  },

  // ─── 事件 ───

  goToEntry: function (e) {
    var route = e.currentTarget.dataset.route;
    if (route) {
      // tabBar 页面用 switchTab，其他用 navigateTo
      if (route === '/pages/menu/menu') {
        wx.switchTab({ url: route });
      } else {
        wx.navigateTo({ url: route });
      }
    }
  },

  goToStore: function (e) {
    var storeId = e.currentTarget.dataset.id;
    app.globalData.storeId = storeId;
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  goToQueue: function () {
    wx.navigateTo({ url: '/pages/queue/queue' });
  },

  goToReservation: function () {
    wx.navigateTo({ url: '/pages/reservation/reservation' });
  },
});
