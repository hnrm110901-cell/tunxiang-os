// Order Tracking -- real-time 4-step cooking progress (Domino's-style)
// Steps: Accepted -> Cooking -> Plating -> Ready
// Features: countdown, rush button, append items

var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    orderId: '',
    orderNo: '',
    orderStatus: '',
    // Progress
    steps: [],
    currentStep: 0,
    remainingSeconds: 0,
    estimatedReadyAt: '',
    // Order details
    items: [],
    totalYuan: '0.00',
    storeName: '',
    tableNo: '',
    createdAt: '',
    // Rush
    canRush: true,
    rushCooldown: 0,
    // Append
    canAppend: false,
    // Polling
    _pollTimer: null,
  },

  onLoad: function (options) {
    var orderId = options.order_id || '';
    this.setData({ orderId: orderId });
    if (orderId) {
      this._loadOrderDetail();
      this._loadProgress();
      this._startPolling();
    }
  },

  onUnload: function () {
    this._stopPolling();
  },

  onShareAppMessage: function () {
    return {
      title: '我的订单进度',
      path: '/pages/order-track/order-track?order_id=' + this.data.orderId,
    };
  },

  // ─── Data loading ───

  _loadOrderDetail: function () {
    var self = this;
    api.fetchOrderDetail(self.data.orderId)
      .then(function (data) {
        var items = (data.items || []).map(function (item) {
          return {
            name: item.dish_name || item.name,
            quantity: item.quantity || 1,
            priceYuan: ((item.unit_price_fen || 0) / 100).toFixed(2),
            imageUrl: item.image_url || '',
            status: item.status || 'pending',
          };
        });

        self.setData({
          orderNo: data.order_no || '',
          orderStatus: data.status || '',
          items: items,
          totalYuan: ((data.total_amount_fen || 0) / 100).toFixed(2),
          storeName: data.store_name || '',
          tableNo: data.table_no || '',
          createdAt: (data.created_at || '').slice(0, 16).replace('T', ' '),
          canAppend: data.status === 'cooking' || data.status === 'paid',
        });
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '加载失败', icon: 'none' });
      });
  },

  _loadProgress: function () {
    var self = this;
    api.fetchCookingProgress(self.data.orderStatus || 'accepted')
      .then(function (data) {
        self.setData({
          steps: data.steps || [],
          currentStep: data.current_step || 0,
          remainingSeconds: data.remaining_seconds || 0,
          estimatedReadyAt: data.estimated_ready_at || '',
        });

        // If ready, show notification
        if (data.current_step >= 4) {
          self._stopPolling();
          wx.showModal({
            title: '出餐通知',
            content: '您的菜品已备好，请前往取餐！',
            showCancel: false,
          });
        }
      })
      .catch(function (err) {
        console.warn('加载进度失败', err);
      });
  },

  // ─── Polling ───

  _startPolling: function () {
    var self = this;
    self._stopPolling();
    var timer = setInterval(function () {
      self._loadOrderDetail();
      self._loadProgress();
    }, 10000); // Poll every 10 seconds
    self.setData({ _pollTimer: timer });
  },

  _stopPolling: function () {
    if (this.data._pollTimer) {
      clearInterval(this.data._pollTimer);
      this.setData({ _pollTimer: null });
    }
  },

  // ─── Rush (催菜) ───

  onRush: function () {
    var self = this;
    if (!self.data.canRush) {
      wx.showToast({ title: '3分钟内只能催一次', icon: 'none' });
      return;
    }

    api.rushOrder(self.data.orderId)
      .then(function (data) {
        wx.showToast({ title: data.message || '已通知厨房', icon: 'success' });
        self.setData({ canRush: false, rushCooldown: 180 });
        // Cooldown timer
        var cooldownTimer = setInterval(function () {
          var cd = self.data.rushCooldown - 1;
          if (cd <= 0) {
            clearInterval(cooldownTimer);
            self.setData({ canRush: true, rushCooldown: 0 });
          } else {
            self.setData({ rushCooldown: cd });
          }
        }, 1000);
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '催菜失败', icon: 'none' });
      });
  },

  // ─── Append items (加菜) ───

  goToAppend: function () {
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  // ─── Navigation ───

  goBack: function () {
    wx.navigateBack();
  },
});
