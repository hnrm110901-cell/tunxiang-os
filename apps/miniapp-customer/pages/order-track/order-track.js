// 订单状态追踪页 — 出餐进度轮询 + 叫服务员 + 加菜 + 继续点餐
var app = getApp();
var api = require('../../utils/api.js');

var PAYMENT_METHOD_MAP = {
  wechat: '微信支付',
  stored_value: '储值卡',
  enterprise: '企业挂账',
  cash: '现金',
};

Page({
  data: {
    orderId: '',
    orderNo: '',
    orderStatus: '',
    paymentMethodText: '',
    // 出餐进度
    steps: [],
    currentStep: 0,
    currentDish: '',
    remainingSeconds: 0,
    estimatedReadyAt: '',
    isReady: false,
    // 订单详情
    items: [],
    totalYuan: '0.00',
    storeName: '',
    tableNo: '',
    createdAt: '',
    canAppend: false,
    // 催菜
    canRush: true,
    rushCooldown: 0,
    // 叫服务员冷却
    serviceBellCooldown: 0,
  },

  // 内部非响应式变量（避免 setData timer）
  _pollTimer: null,
  _rushCooldownTimer: null,
  _serviceBellTimer: null,

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
    this._clearRushTimer();
    this._clearServiceBellTimer();
  },

  onShareAppMessage: function () {
    return {
      title: '我的订单进度',
      path: '/pages/order-track/order-track?order_id=' + this.data.orderId,
    };
  },

  // ─── 数据加载 ───

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
            remark: item.remark || item.notes || '',
            status: item.status || 'pending',
          };
        });

        var paymentMethod = data.payment_method || 'wechat';
        self.setData({
          orderNo: data.order_no || '',
          orderStatus: data.status || '',
          paymentMethodText: PAYMENT_METHOD_MAP[paymentMethod] || paymentMethod,
          items: items,
          totalYuan: ((data.final_total_fen || data.total_amount_fen || 0) / 100).toFixed(2),
          storeName: data.store_name || '',
          tableNo: data.table_no || '',
          createdAt: (data.created_at || '').slice(0, 16).replace('T', ' '),
          canAppend: data.status === 'cooking' || data.status === 'paid' || data.status === 'accepted',
        });

        // 已完成 / 就绪 → 停止轮询
        if (data.status === 'ready' || data.status === 'completed') {
          self._stopPolling();
          if (!self.data.isReady) {
            self.setData({ isReady: true });
            wx.showToast({ title: '您的餐品已准备好，请取餐！', icon: 'success', duration: 3000 });
          }
        }
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '加载失败', icon: 'none' });
      });
  },

  _loadProgress: function () {
    var self = this;
    var status = self.data.orderStatus || 'accepted';
    api.fetchCookingProgress(status)
      .then(function (data) {
        self.setData({
          steps: data.steps || [],
          currentStep: data.current_step || 0,
          currentDish: data.current_dish || '',
          remainingSeconds: data.remaining_seconds || 0,
          estimatedReadyAt: data.estimated_ready_at || '',
        });
      })
      .catch(function (err) {
        console.warn('加载出餐进度失败', err);
      });
  },

  // ─── 轮询（每5秒） ───

  _startPolling: function () {
    var self = this;
    self._stopPolling();
    self._pollTimer = setInterval(function () {
      self._loadOrderDetail();
      self._loadProgress();
    }, 5000);
  },

  _stopPolling: function () {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },

  // ─── 催菜 ───

  onRush: function () {
    var self = this;
    if (!self.data.canRush) {
      wx.showToast({ title: '3分钟内只能催一次', icon: 'none' });
      return;
    }

    api.rushOrder(self.data.orderId)
      .then(function (data) {
        wx.showToast({ title: data.message || '已通知厨房加急', icon: 'success' });
        self.setData({ canRush: false, rushCooldown: 180 });
        self._startRushCooldown();
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '催菜失败', icon: 'none' });
      });
  },

  _startRushCooldown: function () {
    var self = this;
    self._clearRushTimer();
    self._rushCooldownTimer = setInterval(function () {
      var cd = self.data.rushCooldown - 1;
      if (cd <= 0) {
        self._clearRushTimer();
        self.setData({ canRush: true, rushCooldown: 0 });
      } else {
        self.setData({ rushCooldown: cd });
      }
    }, 1000);
  },

  _clearRushTimer: function () {
    if (this._rushCooldownTimer) {
      clearInterval(this._rushCooldownTimer);
      this._rushCooldownTimer = null;
    }
  },

  // ─── 叫服务员 ───

  callServiceBell: function () {
    var self = this;
    if (self.data.serviceBellCooldown > 0) {
      wx.showToast({ title: '请稍后再呼叫', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '呼叫中...' });
    api.callServiceBell(
      self.data.orderId,
      app.globalData.storeId || '',
      self.data.tableNo
    )
      .then(function () {
        wx.hideLoading();
        wx.showToast({ title: '服务员已收到呼叫', icon: 'success' });
        self.setData({ serviceBellCooldown: 60 });
        self._startServiceBellCooldown();
      })
      .catch(function (err) {
        wx.hideLoading();
        wx.showToast({ title: err.message || '呼叫失败，请重试', icon: 'none' });
      });
  },

  _startServiceBellCooldown: function () {
    var self = this;
    self._clearServiceBellTimer();
    self._serviceBellTimer = setInterval(function () {
      var cd = self.data.serviceBellCooldown - 1;
      if (cd <= 0) {
        self._clearServiceBellTimer();
        self.setData({ serviceBellCooldown: 0 });
      } else {
        self.setData({ serviceBellCooldown: cd });
      }
    }, 1000);
  },

  _clearServiceBellTimer: function () {
    if (this._serviceBellTimer) {
      clearInterval(this._serviceBellTimer);
      this._serviceBellTimer = null;
    }
  },

  // ─── 加菜 ───

  goToAppend: function () {
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  // ─── 继续点餐（返回菜单） ───

  goToMenu: function () {
    wx.switchTab({ url: '/pages/menu/menu' });
  },
});
