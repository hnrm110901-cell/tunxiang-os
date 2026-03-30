// 订单状态 — 制作进度 + 出餐提醒
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    orderId: '',
    orderNo: '',
    orderStatus: '',
    orderStatusText: '',
    items: [],
    summary: {
      total: 0,
      done: 0,
      cooking: 0,
      pending: 0,
    },
    loading: true,
    _pollTimer: null,
  },

  onLoad: function (options) {
    this.setData({
      orderId: options.order_id || '',
      orderNo: options.order_no || '',
    });

    if (this.data.orderId) {
      this._loadStatus();
      this._startPolling();
    }
  },

  onUnload: function () {
    if (this.data._pollTimer) {
      clearInterval(this.data._pollTimer);
    }
  },

  onPullDownRefresh: function () {
    var self = this;
    self._loadStatus().then(function () {
      wx.stopPullDownRefresh();
    });
  },

  // ─── 加载状态 ───

  _loadStatus: function () {
    var self = this;
    self.setData({ loading: true });

    return api.scanOrderStatus(self.data.orderId).then(function (data) {
      var statusMap = {
        pending: '待处理',
        open: '进行中',
        dining: '用餐中',
        confirmed: '已确认',
        cooking: '制作中',
        ready: '待出餐',
        completed: '已完成',
        cancelled: '已取消',
        pending_checkout: '待结账',
      };

      var kdsStatusMap = {
        not_submitted: '未提交',
        pending: '待制作',
        cooking: '制作中',
        done: '已出餐',
      };

      var items = (data.items || []).map(function (item) {
        return {
          itemId: item.item_id,
          dishName: item.dish_name,
          quantity: item.quantity,
          kdsStatus: item.kds_status,
          kdsStatusText: kdsStatusMap[item.kds_status] || item.kds_status,
          kdsStation: item.kds_station || '',
          isDone: item.kds_status === 'done',
          isCooking: item.kds_status === 'cooking',
        };
      });

      self.setData({
        orderNo: data.order_no || self.data.orderNo,
        orderStatus: data.order_status,
        orderStatusText: statusMap[data.order_status] || data.order_status,
        items: items,
        summary: data.summary || { total: 0, done: 0, cooking: 0, pending: 0 },
        loading: false,
      });

      // 如果全部出餐完毕，停止轮询
      if (data.summary && data.summary.total > 0 && data.summary.done === data.summary.total) {
        self._stopPolling();
      }
    }).catch(function (err) {
      self.setData({ loading: false });
      wx.showToast({ title: err.message || '查询失败', icon: 'none' });
    });
  },

  // ─── 轮询（每10秒刷新） ───

  _startPolling: function () {
    var self = this;
    if (self.data._pollTimer) clearInterval(self.data._pollTimer);

    var timer = setInterval(function () {
      self._loadStatus();
    }, 10000);
    self.setData({ _pollTimer: timer });
  },

  _stopPolling: function () {
    if (this.data._pollTimer) {
      clearInterval(this.data._pollTimer);
      this.setData({ _pollTimer: null });
    }
  },

  // ─── 请求结账 ───

  requestCheckout: function () {
    var self = this;
    if (!self.data.orderId) return;

    wx.showModal({
      title: '确认结账',
      content: '确定要请求结账吗？服务员将会过来为您结算。',
      confirmColor: '#FF6B2C',
      success: function (res) {
        if (!res.confirm) return;

        wx.showLoading({ title: '请求中...' });
        api.txRequest('/api/v1/scan-order/checkout', 'POST', {
          order_id: self.data.orderId,
        }).then(function () {
          wx.hideLoading();
          wx.showToast({ title: '已通知收银台', icon: 'success' });
          self._loadStatus();
        }).catch(function (err) {
          wx.hideLoading();
          wx.showToast({ title: err.message || '请求失败', icon: 'none' });
        });
      },
    });
  },

  // ─── 继续点餐 ───

  continueOrder: function () {
    wx.navigateBack();
  },
});
