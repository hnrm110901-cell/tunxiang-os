// 确认下单 — 提交菜品到厨房
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    storeId: '',
    tableId: '',
    orderId: '',
    orderItems: [],
    totalFen: 0,
    totalYuan: '0.00',
    remark: '',
    submitting: false,
    submitted: false,
  },

  onLoad: function (options) {
    var storeId = options.store_id || '';
    var tableId = options.table_id || '';
    var orderId = options.order_id || '';
    var total = Number(options.total) || 0;

    var items = [];
    if (options.items) {
      try {
        items = JSON.parse(decodeURIComponent(options.items));
      } catch (e) {
        console.error('解析菜品数据失败', e);
      }
    }

    // 计算每项的小计
    items.forEach(function (item) {
      item.subtotalFen = (item.unitPriceFen || 0) * (item.quantity || 1);
      item.subtotalYuan = (item.subtotalFen / 100).toFixed(2);
      item.unitPriceYuan = ((item.unitPriceFen || 0) / 100).toFixed(2);
    });

    this.setData({
      storeId: storeId,
      tableId: tableId,
      orderId: orderId,
      orderItems: items,
      totalFen: total,
      totalYuan: (total / 100).toFixed(2),
    });
  },

  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value });
  },

  // ─── 提交到厨房 ───

  submitOrder: function () {
    var self = this;
    if (self.data.submitting || self.data.submitted) return;
    if (self.data.orderItems.length === 0) {
      wx.showToast({ title: '请先选择菜品', icon: 'none' });
      return;
    }

    self.setData({ submitting: true });
    wx.showLoading({ title: '提交中...' });

    // 构造请求数据
    var items = self.data.orderItems.map(function (item) {
      return {
        dish_id: item.dishId,
        quantity: item.quantity,
        notes: self.data.remark || '',
      };
    });

    var submitFn;
    if (self.data.orderId) {
      // 已有订单：加菜
      submitFn = api.txRequest('/api/v1/scan-order/add-items', 'POST', {
        order_id: self.data.orderId,
        items: items,
      });
    } else {
      // 新订单：创建
      submitFn = api.txRequest('/api/v1/scan-order/create', 'POST', {
        store_id: self.data.storeId,
        table_id: self.data.tableId,
        items: items,
        customer_id: wx.getStorageSync('tx_customer_id') || '',
      });
    }

    submitFn.then(function (data) {
      wx.hideLoading();
      self.setData({
        submitting: false,
        submitted: true,
        orderId: data.order_id || self.data.orderId,
      });

      wx.showToast({ title: '已提交厨房', icon: 'success' });
    }).catch(function (err) {
      wx.hideLoading();
      self.setData({ submitting: false });
      wx.showToast({ title: err.message || '提交失败', icon: 'none' });
    });
  },

  // ─── 查看订单状态 ───

  viewStatus: function () {
    if (!this.data.orderId) return;
    wx.redirectTo({
      url: '/pages/scan-order/status?order_id=' + this.data.orderId,
    });
  },

  // ─── 继续点餐 ───

  continueOrder: function () {
    wx.navigateBack();
  },

  // ─── 请求结账 ───

  requestCheckout: function () {
    var self = this;
    if (!self.data.orderId) return;

    wx.showLoading({ title: '请求结账...' });
    api.txRequest('/api/v1/scan-order/checkout', 'POST', {
      order_id: self.data.orderId,
    }).then(function () {
      wx.hideLoading();
      wx.showToast({ title: '已通知收银台', icon: 'success' });
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({ title: err.message || '请求失败', icon: 'none' });
    });
  },
});
