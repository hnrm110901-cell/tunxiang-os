var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    product: null,
    loading: true,
    quantity: 1,
    selectedSku: null,
    addingToCart: false,
  },

  onLoad: function (options) {
    if (options.id) {
      this._loadProduct(options.id);
    }
  },

  _loadProduct: function (productId) {
    var self = this;
    api.get('/api/v1/retail/products/' + productId).then(function (res) {
      self.setData({
        product: res.data,
        selectedSku: res.data.skus ? res.data.skus[0] : null,
        loading: false,
      });
    }).catch(function () {
      self.setData({ loading: false });
      wx.showToast({ title: '商品不存在', icon: 'none' });
    });
  },

  onSelectSku: function (e) {
    var skuId = e.currentTarget.dataset.id;
    var product = this.data.product;
    if (!product || !product.skus) return;
    var sku = product.skus.find(function (s) { return s.sku_id === skuId; });
    if (sku) this.setData({ selectedSku: sku });
  },

  onChangeQuantity: function (e) {
    var delta = e.currentTarget.dataset.delta;
    var qty = this.data.quantity + delta;
    if (qty < 1) qty = 1;
    if (qty > 99) qty = 99;
    this.setData({ quantity: qty });
  },

  onAddToCart: function () {
    var self = this;
    if (self.data.addingToCart) return;
    var product = self.data.product;
    var sku = self.data.selectedSku;

    self.setData({ addingToCart: true });
    api.post('/api/v1/retail/cart/add', {
      product_id: product.product_id,
      sku_id: sku ? sku.sku_id : '',
      quantity: self.data.quantity,
    }).then(function () {
      self.setData({ addingToCart: false });
      wx.showToast({ title: '已加入购物车', icon: 'success' });
    }).catch(function () {
      self.setData({ addingToCart: false });
      wx.showToast({ title: '加入失败', icon: 'none' });
    });
  },

  onBuyNow: function () {
    var product = this.data.product;
    var sku = this.data.selectedSku;
    wx.navigateTo({
      url: '/pages/retail-mall/checkout?product_id=' + product.product_id
        + '&sku_id=' + (sku ? sku.sku_id : '')
        + '&quantity=' + this.data.quantity,
    });
  },

  onShareAppMessage: function () {
    var product = this.data.product;
    return {
      title: product ? product.name : '好物推荐',
      path: '/pages/retail-mall/product-detail?id=' + (product ? product.product_id : ''),
      imageUrl: product ? product.image_url : '',
    };
  },
});
