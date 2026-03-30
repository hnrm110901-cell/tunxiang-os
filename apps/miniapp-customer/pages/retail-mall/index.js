// 甄选商城首页 — 分类+推荐+促销（海味礼盒/预制菜/调味品/周边）
// 独立于堂食订单系统的线上零售

var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // ─── 分类Tab ───
    categories: [
      { key: 'all', label: '全部' },
      { key: 'seafood_gift', label: '海味礼盒' },
      { key: 'prepared_dish', label: '预制菜' },
      { key: 'seasoning', label: '调味品' },
      { key: 'merchandise', label: '周边' },
    ],
    activeCategory: 'all',

    // ─── 轮播促销 ───
    banners: [],

    // ─── 商品列表 ───
    products: [],
    loading: false,
    page: 1,
    size: 20,
    total: 0,
    hasMore: true,

    // ─── 购物车角标 ───
    cartCount: 0,

    // ─── 搜索 ───
    searchKeyword: '',
  },

  onLoad: function () {
    this.loadBanners();
    this.loadProducts();
    this.loadCartCount();
  },

  onPullDownRefresh: function () {
    this.setData({ page: 1, products: [], hasMore: true });
    this.loadProducts().then(function () {
      wx.stopPullDownRefresh();
    });
  },

  onReachBottom: function () {
    if (this.data.hasMore && !this.data.loading) {
      this.loadProducts();
    }
  },

  // ─── 加载轮播 ───
  loadBanners: function () {
    var self = this;
    api.get('/api/v1/retail/banners').then(function (res) {
      if (res.ok) {
        self.setData({ banners: res.data.items || [] });
      }
    });
  },

  // ─── 加载商品列表 ───
  loadProducts: function () {
    var self = this;
    if (self.data.loading) return Promise.resolve();

    self.setData({ loading: true });
    var category = self.data.activeCategory === 'all' ? '' : self.data.activeCategory;

    return api.get('/api/v1/retail/products', {
      category: category,
      page: self.data.page,
      size: self.data.size,
    }).then(function (res) {
      if (res.ok) {
        var newProducts = self.data.products.concat(res.data.items || []);
        var hasMore = newProducts.length < (res.data.total || 0);
        self.setData({
          products: newProducts,
          total: res.data.total || 0,
          page: self.data.page + 1,
          hasMore: hasMore,
          loading: false,
        });
      } else {
        self.setData({ loading: false });
      }
    });
  },

  // ─── 加载购物车数量 ───
  loadCartCount: function () {
    var self = this;
    var cart = wx.getStorageSync('retail_cart') || [];
    var count = 0;
    cart.forEach(function (item) { count += item.quantity; });
    self.setData({ cartCount: count });
  },

  // ─── 切换分类 ───
  switchCategory: function (e) {
    var key = e.currentTarget.dataset.key;
    this.setData({
      activeCategory: key,
      page: 1,
      products: [],
      hasMore: true,
    });
    this.loadProducts();
  },

  // ─── 跳转商品详情 ───
  goToProduct: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/retail-mall/product?id=' + id });
  },

  // ─── 跳转购物车 ───
  goToCart: function () {
    wx.navigateTo({ url: '/pages/retail-mall/cart' });
  },

  // ─── 搜索 ───
  onSearchInput: function (e) {
    this.setData({ searchKeyword: e.detail.value });
  },

  doSearch: function () {
    // TODO: 实现搜索逻辑
    wx.showToast({ title: '搜索: ' + this.data.searchKeyword, icon: 'none' });
  },
});
