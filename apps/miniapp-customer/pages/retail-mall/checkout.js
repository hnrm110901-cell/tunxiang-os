var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    items: [],
    address: null,
    deliveryType: 'express',
    totalFen: 0,
    freightFen: 0,
    submitting: false,
    coupon: null,
    remark: '',
  },

  onLoad: function (options) {
    if (options.product_id) {
      this.setData({
        items: [{
          product_id: options.product_id,
          sku_id: options.sku_id || '',
          quantity: parseInt(options.quantity, 10) || 1,
          name: '加载中...',
          price_fen: 0,
        }],
      });
      this._loadProductInfo(options.product_id);
    } else {
      this._loadCartItems();
    }
    this._loadDefaultAddress();
  },

  _loadProductInfo: function (productId) {
    var self = this;
    api.get('/api/v1/retail/products/' + productId).then(function (res) {
      var p = res.data;
      var item = self.data.items[0];
      item.name = p.name;
      item.price_fen = p.price_fen;
      item.image_url = p.image_url;
      self.setData({ items: [item] });
      self._calcTotal();
    });
  },

  _loadCartItems: function () {
    var self = this;
    api.get('/api/v1/retail/cart').then(function (res) {
      self.setData({ items: res.data.items || [] });
      self._calcTotal();
    });
  },

  _loadDefaultAddress: function () {
    var self = this;
    api.get('/api/v1/member/addresses/default').then(function (res) {
      if (res.data) self.setData({ address: res.data });
    }).catch(function () {});
  },

  _calcTotal: function () {
    var total = 0;
    this.data.items.forEach(function (item) {
      total += (item.price_fen || 0) * (item.quantity || 1);
    });
    var freight = this.data.deliveryType === 'express' ? (total >= 9900 ? 0 : 800) : 0;
    this.setData({ totalFen: total, freightFen: freight });
  },

  switchDelivery: function (e) {
    var type = e.currentTarget.dataset.type;
    this.setData({ deliveryType: type });
    this._calcTotal();
  },

  onInputRemark: function (e) {
    this.setData({ remark: e.detail.value });
  },

  onSubmitOrder: function () {
    var self = this;
    if (self.data.submitting) return;

    if (self.data.deliveryType === 'express' && !self.data.address) {
      wx.showToast({ title: '请填写收货地址', icon: 'none' });
      return;
    }
    if (self.data.items.length === 0) {
      wx.showToast({ title: '没有可结算的商品', icon: 'none' });
      return;
    }

    self.setData({ submitting: true });

    var orderData = {
      items: self.data.items.map(function (i) {
        return { product_id: i.product_id, sku_id: i.sku_id, quantity: i.quantity };
      }),
      delivery_type: self.data.deliveryType,
      address: self.data.address,
      remark: self.data.remark,
      coupon_id: self.data.coupon ? self.data.coupon.id : null,
    };

    api.post('/api/v1/retail/orders', orderData).then(function (res) {
      self.setData({ submitting: false });
      wx.showToast({ title: '下单成功', icon: 'success' });
      wx.redirectTo({ url: '/pages/retail-mall/order?id=' + res.data.order_id });
    }).catch(function (err) {
      self.setData({ submitting: false });
      wx.showToast({ title: (err && err.message) || '下单失败', icon: 'none' });
    });
  },
});
