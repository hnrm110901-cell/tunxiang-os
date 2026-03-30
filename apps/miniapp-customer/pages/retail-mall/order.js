// 订单确认 + 支付（零售订单，独立于堂食）
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // ─── 结算数据（从购物车传入） ───
    items: [],
    address: null,
    totalFen: 0,

    // ─── 会员折扣 ───
    hasCard: false,
    cardId: '',
    discountFen: 0,
    finalFen: 0,
    discountRate: 100,

    // ─── 备注 ───
    remark: '',

    // ─── 提交状态 ───
    submitting: false,
  },

  onLoad: function () {
    var checkout = wx.getStorageSync('retail_checkout');
    if (!checkout || !checkout.items || checkout.items.length === 0) {
      wx.showToast({ title: '订单数据异常', icon: 'none' });
      wx.navigateBack();
      return;
    }
    this.setData({
      items: checkout.items,
      address: checkout.address,
      totalFen: checkout.total_fen,
      finalFen: checkout.total_fen,
    });
    this.checkMemberCard();
  },

  // ─── 检查会员卡 ───
  checkMemberCard: function () {
    var self = this;
    api.get('/api/v1/member/premium/my-card').then(function (res) {
      if (res.ok && res.data && res.data.card_id) {
        self.setData({
          hasCard: true,
          cardId: res.data.card_id,
        });
      }
    });
  },

  // ─── 应用会员折扣 ───
  applyDiscount: function () {
    var self = this;
    if (!self.data.cardId) return;

    // 模拟折扣计算（实际由后端完成）
    api.post('/api/v1/retail/orders/temp/discount', {
      card_id: self.data.cardId,
      total_fen: self.data.totalFen,
    }).then(function (res) {
      if (res.ok) {
        self.setData({
          discountFen: res.data.discount_fen || 0,
          finalFen: self.data.totalFen - (res.data.discount_fen || 0),
          discountRate: res.data.discount_rate || 100,
        });
      }
    });
  },

  // ─── 备注 ───
  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value });
  },

  // ─── 提交订单 ───
  submitOrder: function () {
    var self = this;
    if (self.data.submitting) return;
    self.setData({ submitting: true });

    var orderItems = self.data.items.map(function (item) {
      return {
        product_id: item.product_id,
        sku_id: item.sku_id,
        quantity: item.quantity,
      };
    });

    api.post('/api/v1/retail/orders', {
      customer_id: app.globalData.customerId || '',
      items: orderItems,
      address: self.data.address,
      remark: self.data.remark,
    }).then(function (res) {
      if (res.ok) {
        // 清除购物车中已结算的商品
        wx.removeStorageSync('retail_checkout');
        self.removeOrderedItems();

        // 发起支付
        self.requestPayment(res.data.order_id, self.data.finalFen);
      } else {
        wx.showToast({ title: res.error || '下单失败', icon: 'none' });
        self.setData({ submitting: false });
      }
    });
  },

  // ─── 发起微信支付 ───
  requestPayment: function (orderId, amountFen) {
    var self = this;
    api.post('/api/v1/payment/wx-pay', {
      order_id: orderId,
      amount_fen: amountFen,
      order_type: 'retail',
    }).then(function (res) {
      if (res.ok && res.data.payment_params) {
        wx.requestPayment({
          timeStamp: res.data.payment_params.timeStamp,
          nonceStr: res.data.payment_params.nonceStr,
          package: res.data.payment_params.package,
          signType: res.data.payment_params.signType,
          paySign: res.data.payment_params.paySign,
          success: function () {
            wx.showToast({ title: '支付成功', icon: 'success' });
            wx.redirectTo({ url: '/pages/order/order?tab=retail' });
          },
          fail: function () {
            wx.showToast({ title: '支付取消', icon: 'none' });
            self.setData({ submitting: false });
          },
        });
      } else {
        self.setData({ submitting: false });
      }
    });
  },

  // ─── 从购物车移除已下单商品 ───
  removeOrderedItems: function () {
    var orderedIds = {};
    this.data.items.forEach(function (item) {
      orderedIds[item.product_id + ':' + item.sku_id] = true;
    });
    var cart = wx.getStorageSync('retail_cart') || [];
    cart = cart.filter(function (item) {
      return !orderedIds[item.product_id + ':' + item.sku_id];
    });
    wx.setStorageSync('retail_cart', cart);
  },
});
