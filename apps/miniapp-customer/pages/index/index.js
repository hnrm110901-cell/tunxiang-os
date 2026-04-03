// 首页 — 到店点餐/外卖/大厨到家 Tab + 进行中订单悬浮卡片 + 猜你喜欢 + 快捷入口 + 附近门店
// 参考: 瑞幸咖啡 + 麦当劳

var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // ─── 顶部Tab: 到店点餐 / 外卖 / 大厨到家 ───
    modes: [
      { key: 'dine_in', label: '到店点餐' },
      { key: 'takeaway', label: '外卖' },
      { key: 'chef_home', label: '大厨到家' },
    ],
    activeMode: 'dine_in',

    // ─── 门店信息 ───
    storeName: '',
    storeAddress: '',
    tableNo: '',

    // ─── 快捷入口 (4宫格) ───
    quickEntries: [
      { icon: '/assets/icon-scan.png', label: '扫码点餐', route: '/pages/scan-order/index', type: 'navigate' },
      { icon: '/assets/icon-queue.png', label: '排队取号', route: '/pages/queue/queue', type: 'navigate' },
      { icon: '/assets/icon-booking.png', label: '预订', route: '/pages/reservation/reservation', type: 'navigate' },
      { icon: '/assets/icon-member.png', label: '我的会员卡', route: '/pages/member/member', type: 'tab' },
    ],

    // ─── 猜你喜欢 AI推荐 (4宫格) ───
    recommendations: [],
    loadingRecommendations: false,

    // ─── 进行中订单悬浮卡片 ───
    activeOrder: null, // { id, orderNo, status, statusText, currentDish, estimatedMinutes, progress }

    // ─── 附近门店 (GPS距离排序) ───
    nearbyStores: [],
    loadingStores: false,

    // ─── 当前排队/预订 ───
    currentQueue: null,
    currentBooking: null,
  },

  onLoad: function (options) {
    if (options.table) {
      this.setData({ tableNo: options.table });
    }
    if (options.store_name) {
      this.setData({ storeName: decodeURIComponent(options.store_name) });
    }
    if (options.mode) {
      this.setData({ activeMode: options.mode });
    }
    if (options.coupon_id) {
      wx.switchTab({ url: '/pages/menu/menu' });
    }
  },

  onShow: function () {
    this._loadStoreInfo();
    this._loadNearbyStores();
    this._loadRecommendations();
    this._checkActiveOrder();
  },

  onPullDownRefresh: function () {
    var self = this;
    Promise.all([
      this._loadStoreInfo(),
      this._loadNearbyStores(),
      this._loadRecommendations(),
      this._checkActiveOrder(),
    ]).then(function () {
      wx.stopPullDownRefresh();
    }).catch(function () {
      wx.stopPullDownRefresh();
    });
  },

  onShareAppMessage: function () {
    return {
      title: this.data.storeName || '屯象点餐',
      path: '/pages/index/index?store_id=' + app.globalData.storeId,
    };
  },

  onShareTimeline: function () {
    return {
      title: this.data.storeName || '屯象点餐 - 扫码下单',
    };
  },

  // ─── Tab 切换 ───

  switchMode: function (e) {
    var mode = e.currentTarget.dataset.mode;
    this.setData({ activeMode: mode });
    if (mode === 'chef_home') {
      wx.navigateTo({ url: '/pages/chef-at-home/index' });
    }
  },

  // ─── 数据加载 ───

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
                  imageUrl: s.image_url || '',
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

  _loadRecommendations: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    if (!storeId) return Promise.resolve();

    self.setData({ loadingRecommendations: true });
    return api.fetchRecommendations(storeId)
      .then(function (data) {
        var items = (data.items || data || []).slice(0, 4);
        self.setData({
          recommendations: items,
          loadingRecommendations: false,
        });
      })
      .catch(function () {
        self.setData({ loadingRecommendations: false });
      });
  },

  _checkActiveOrder: function () {
    var self = this;
    return api.fetchMyOrders(1, 5)
      .then(function (data) {
        var items = data.items || [];
        var active = null;
        var statusTextMap = {
          paid: '已接单',
          accepted: '已接单',
          cooking: '制作中',
          plating: '出餐中',
          ready: '可取餐',
        };
        var progressMap = {
          paid: 1,
          accepted: 1,
          cooking: 2,
          plating: 3,
          ready: 4,
        };
        for (var i = 0; i < items.length; i++) {
          var o = items[i];
          if (statusTextMap[o.status]) {
            active = {
              id: o.id || o.order_id,
              orderNo: o.order_no || '',
              status: o.status,
              statusText: statusTextMap[o.status],
              currentDish: o.current_dish || '',
              estimatedMinutes: o.estimated_minutes || 15,
              progress: progressMap[o.status] || 1,
            };
            break;
          }
        }
        self.setData({ activeOrder: active });
      })
      .catch(function () {});
  },

  // ─── 事件 ───

  goToEntry: function (e) {
    var route = e.currentTarget.dataset.route;
    var type = e.currentTarget.dataset.type;
    if (!route) return;

    if (type === 'tab') {
      wx.switchTab({ url: route });
    } else {
      wx.navigateTo({ url: route });
    }
  },

  goToStore: function (e) {
    var storeId = e.currentTarget.dataset.id;
    app.globalData.storeId = storeId;
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  goToActiveOrder: function () {
    var order = this.data.activeOrder;
    if (order) {
      wx.navigateTo({
        url: '/pages/order-track/order-track?order_id=' + order.id,
      });
    }
  },

  goToChefHome: function () {
    wx.navigateTo({ url: '/pages/chef-at-home/index' });
  },

  goToMenu: function () {
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  goToQueue: function () {
    wx.navigateTo({ url: '/pages/queue/queue' });
  },

  goToReservation: function () {
    wx.navigateTo({ url: '/pages/reservation/reservation' });
  },

  onRecommendAdd: function (e) {
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  onRecommendSelect: function (e) {
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  startScan: function () {
    wx.scanCode({
      onlyFromCamera: false,
      success: function (res) {
        var scene = res.result || '';
        if (scene.indexOf('store_id=') >= 0 || scene.indexOf('table=') >= 0) {
          app._parseScene(scene);
          wx.navigateTo({
            url: '/pages/scan-order/index?scene=' + encodeURIComponent(scene),
          });
        } else {
          wx.showToast({ title: '无法识别二维码', icon: 'none' });
        }
      },
    });
  },
});
