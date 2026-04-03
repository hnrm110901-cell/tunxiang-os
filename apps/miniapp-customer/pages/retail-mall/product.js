// 商品详情 — 大图轮播+规格选择+评价+加入购物车
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    productId: '',
    product: null,
    loading: true,

    // ─── 规格选择 ───
    selectedSku: null,
    quantity: 1,

    // ─── 图片预览 ───
    currentImageIndex: 0,

    // ─── 底部操作栏 ───
    showSkuPicker: false,
  },

  onLoad: function (options) {
    if (options.id) {
      this.setData({ productId: options.id });
      this.loadProduct(options.id);
    }
  },

  loadProduct: function (id) {
    var self = this;
    api.get('/api/v1/retail/products/' + id).then(function (res) {
      if (res.ok) {
        var product = res.data;
        // 默认选中第一个SKU
        var defaultSku = product.skus && product.skus.length > 0 ? product.skus[0] : null;
        self.setData({
          product: product,
          selectedSku: defaultSku,
          loading: false,
        });
        wx.setNavigationBarTitle({ title: product.name || '商品详情' });
      } else {
        self.setData({ loading: false });
        wx.showToast({ title: '商品不存在', icon: 'none' });
      }
    });
  },

  // ─── 图片轮播切换 ───
  onSwiperChange: function (e) {
    this.setData({ currentImageIndex: e.detail.current });
  },

  previewImage: function (e) {
    var images = this.data.product.images || [];
    wx.previewImage({
      current: images[this.data.currentImageIndex],
      urls: images,
    });
  },

  // ─── 规格选择 ───
  selectSku: function (e) {
    var sku = e.currentTarget.dataset.sku;
    this.setData({ selectedSku: sku });
  },

  toggleSkuPicker: function () {
    this.setData({ showSkuPicker: !this.data.showSkuPicker });
  },

  // ─── 数量调整 ───
  decreaseQty: function () {
    if (this.data.quantity > 1) {
      this.setData({ quantity: this.data.quantity - 1 });
    }
  },

  increaseQty: function () {
    this.setData({ quantity: this.data.quantity + 1 });
  },

  // ─── 加入购物车 ───
  addToCart: function () {
    if (!this.data.selectedSku) {
      wx.showToast({ title: '请选择规格', icon: 'none' });
      return;
    }
    var cart = wx.getStorageSync('retail_cart') || [];
    var existing = cart.find(function (item) {
      return item.product_id === this.data.productId && item.sku_id === this.data.selectedSku.id;
    }.bind(this));

    if (existing) {
      existing.quantity += this.data.quantity;
    } else {
      cart.push({
        product_id: this.data.productId,
        sku_id: this.data.selectedSku.id,
        sku_name: this.data.selectedSku.name,
        product_name: this.data.product.name,
        cover_image: this.data.product.cover_image,
        price_fen: this.data.selectedSku.price_fen || this.data.product.price_fen,
        quantity: this.data.quantity,
      });
    }
    wx.setStorageSync('retail_cart', cart);
    wx.showToast({ title: '已加入购物车', icon: 'success' });
    this.setData({ showSkuPicker: false });
  },

  // ─── 立即购买 ───
  buyNow: function () {
    if (!this.data.selectedSku) {
      wx.showToast({ title: '请选择规格', icon: 'none' });
      return;
    }
    this.addToCart();
    wx.navigateTo({ url: '/pages/retail-mall/cart' });
  },
});
