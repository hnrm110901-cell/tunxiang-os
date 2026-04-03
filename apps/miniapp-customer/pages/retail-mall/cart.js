// 购物车 + 收货地址管理
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // ─── 购物车商品 ───
    cartItems: [],
    selectAll: true,

    // ─── 收货地址 ───
    selectedAddress: null,
    addressList: [],
    showAddressPicker: false,

    // ─── 汇总 ───
    totalFen: 0,
    selectedCount: 0,
  },

  onShow: function () {
    this.loadCart();
    this.loadAddresses();
  },

  // ─── 加载购物车 ───
  loadCart: function () {
    var cart = wx.getStorageSync('retail_cart') || [];
    cart.forEach(function (item) {
      item.selected = item.selected !== false;
    });
    this.setData({ cartItems: cart });
    this.calcTotal();
  },

  // ─── 加载地址列表 ───
  loadAddresses: function () {
    var self = this;
    var addresses = wx.getStorageSync('retail_addresses') || [];
    var selected = addresses.find(function (a) { return a.is_default; }) || addresses[0] || null;
    self.setData({ addressList: addresses, selectedAddress: selected });
  },

  // ─── 选择/取消单个商品 ───
  toggleItem: function (e) {
    var idx = e.currentTarget.dataset.index;
    var key = 'cartItems[' + idx + '].selected';
    this.setData({ [key]: !this.data.cartItems[idx].selected });
    this.checkSelectAll();
    this.calcTotal();
  },

  // ─── 全选/取消全选 ───
  toggleSelectAll: function () {
    var newVal = !this.data.selectAll;
    var items = this.data.cartItems;
    items.forEach(function (item) { item.selected = newVal; });
    this.setData({ cartItems: items, selectAll: newVal });
    this.calcTotal();
  },

  checkSelectAll: function () {
    var all = this.data.cartItems.every(function (item) { return item.selected; });
    this.setData({ selectAll: all });
  },

  // ─── 修改数量 ───
  changeQuantity: function (e) {
    var idx = e.currentTarget.dataset.index;
    var delta = e.currentTarget.dataset.delta;
    var item = this.data.cartItems[idx];
    var newQty = item.quantity + delta;
    if (newQty < 1) return;
    var key = 'cartItems[' + idx + '].quantity';
    this.setData({ [key]: newQty });
    this.saveCart();
    this.calcTotal();
  },

  // ─── 删除商品 ───
  removeItem: function (e) {
    var idx = e.currentTarget.dataset.index;
    var items = this.data.cartItems;
    items.splice(idx, 1);
    this.setData({ cartItems: items });
    this.saveCart();
    this.calcTotal();
  },

  // ─── 计算总价 ───
  calcTotal: function () {
    var total = 0;
    var count = 0;
    this.data.cartItems.forEach(function (item) {
      if (item.selected) {
        total += item.price_fen * item.quantity;
        count += item.quantity;
      }
    });
    this.setData({ totalFen: total, selectedCount: count });
  },

  // ─── 保存购物车到本地 ───
  saveCart: function () {
    wx.setStorageSync('retail_cart', this.data.cartItems);
  },

  // ─── 选择地址 ───
  chooseAddress: function () {
    this.setData({ showAddressPicker: true });
  },

  selectAddress: function (e) {
    var addr = e.currentTarget.dataset.addr;
    this.setData({ selectedAddress: addr, showAddressPicker: false });
  },

  // ─── 使用微信地址 ───
  useWxAddress: function () {
    var self = this;
    wx.chooseAddress({
      success: function (res) {
        var addr = {
          name: res.userName,
          phone: res.telNumber,
          province: res.provinceName,
          city: res.cityName,
          district: res.countyName,
          detail: res.detailInfo,
          is_default: true,
        };
        self.setData({ selectedAddress: addr, showAddressPicker: false });
      },
    });
  },

  // ─── 去结算 ───
  goToCheckout: function () {
    if (this.data.selectedCount === 0) {
      wx.showToast({ title: '请选择商品', icon: 'none' });
      return;
    }
    if (!this.data.selectedAddress) {
      wx.showToast({ title: '请选择收货地址', icon: 'none' });
      return;
    }
    // 将选中商品和地址存入临时存储
    var selectedItems = this.data.cartItems.filter(function (item) { return item.selected; });
    wx.setStorageSync('retail_checkout', {
      items: selectedItems,
      address: this.data.selectedAddress,
      total_fen: this.data.totalFen,
    });
    wx.navigateTo({ url: '/pages/retail-mall/order' });
  },
});
