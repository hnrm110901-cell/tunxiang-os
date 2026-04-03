// 购物车结算页 — 菜品清单 + 单品备注 + 优惠匹配 + 支付方式 + 下单
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 菜品列表
    items: [],
    totalFen: 0,
    totalCount: 0,
    tableNo: '',

    // 凑单提示
    addonTip: '',

    // AA分摊
    showAASplit: false,
    partySize: 2,
    perPersonFen: 0,

    // 优惠券
    availableCoupons: [],
    selectedCoupon: null,
    discountFen: 0,
    finalTotalFen: 0,

    // 备注
    orderNotes: '',

    // 储值卡 / 企业账户
    storedValueBalance: 0,
    hasEnterpriseAccount: false,

    // 支付方式
    paymentMethod: 'wechat', // wechat / stored_value / enterprise

    // 结算弹层
    showCheckoutSheet: false,
    submitting: false,
  },

  onLoad: function (options) {
    var tableNo = options.table || '';
    this.setData({ tableNo: tableNo });
    this._loadCartFromGlobal();
    this._loadMemberInfo();
  },

  onShow: function () {
    // 每次进入页面刷新购物车（防止从菜单页加菜后数据不同步）
    this._loadCartFromGlobal();
  },

  // ─── 从 globalData 读取购物车 ───

  _loadCartFromGlobal: function () {
    var cart = (app.globalData && app.globalData.cart) || [];
    // 兼容旧格式：URL 传参
    if (cart.length === 0) {
      var stored = wx.getStorageSync('tx_cart');
      if (stored) {
        try { cart = JSON.parse(stored); } catch (e) { cart = []; }
      }
    }

    var total = 0;
    var count = 0;
    cart.forEach(function (it) {
      total += (it.unitPriceFen || 0) * (it.quantity || 0);
      count += (it.quantity || 0);
    });

    this.setData({
      items: cart,
      totalFen: total,
      totalCount: count,
      finalTotalFen: Math.max(0, total - this.data.discountFen),
    });

    this._checkAddonTip(total);
    this._loadCoupons(total);
  },

  // ─── 会员信息（储值卡/企业账户）───

  _loadMemberInfo: function () {
    var self = this;
    api.fetchMemberProfile()
      .then(function (data) {
        self.setData({
          storedValueBalance: data.stored_value_balance_fen || 0,
          hasEnterpriseAccount: !!(data.enterprise_account_id),
        });
      })
      .catch(function () {});
  },

  // ─── 凑单提示 ───

  _checkAddonTip: function (total) {
    var thresholds = [5000, 8000, 10000, 15000];
    for (var i = 0; i < thresholds.length; i++) {
      var gap = thresholds[i] - total;
      if (gap > 0 && gap <= 2000) {
        this.setData({
          addonTip: '再点¥' + (gap / 100).toFixed(0) + '享满¥' + (thresholds[i] / 100) + '减优惠',
        });
        return;
      }
    }
    this.setData({ addonTip: '' });
  },

  // ─── 优惠券 ───

  _loadCoupons: function (total) {
    var self = this;
    api.fetchCoupons('available')
      .then(function (data) {
        var coupons = (data.items || data || []).filter(function (c) {
          return total >= (c.min_amount_fen || 0);
        });
        // 自动选最优券
        var best = null;
        var bestDiscount = 0;
        coupons.forEach(function (c) {
          var discount = c.discount_fen || c.amount_fen || 0;
          if (discount > bestDiscount) {
            bestDiscount = discount;
            best = c;
          }
        });
        self.setData({
          availableCoupons: coupons,
          selectedCoupon: best,
          discountFen: bestDiscount,
          finalTotalFen: Math.max(0, total - bestDiscount),
        });
      })
      .catch(function () {});
  },

  selectCoupon: function (e) {
    var idx = e.currentTarget.dataset.index;
    var coupon = this.data.availableCoupons[idx];
    var discount = coupon ? (coupon.discount_fen || coupon.amount_fen || 0) : 0;
    this.setData({
      selectedCoupon: coupon || null,
      discountFen: discount,
      finalTotalFen: Math.max(0, this.data.totalFen - discount),
    });
  },

  clearCoupon: function () {
    this.setData({
      selectedCoupon: null,
      discountFen: 0,
      finalTotalFen: this.data.totalFen,
    });
  },

  // ─── 数量修改 ───

  changeQty: function (e) {
    var idx = e.currentTarget.dataset.index;
    var delta = parseInt(e.currentTarget.dataset.delta, 10);
    var items = this.data.items.slice();
    var item = Object.assign({}, items[idx]);
    if (!item) return;

    item.quantity = Math.max(0, (item.quantity || 0) + delta);
    if (item.quantity === 0) {
      items.splice(idx, 1);
    } else {
      items[idx] = item;
    }

    var total = 0;
    var count = 0;
    items.forEach(function (it) {
      total += (it.unitPriceFen || 0) * (it.quantity || 0);
      count += (it.quantity || 0);
    });

    // 同步到 globalData 和 Storage
    if (app.globalData) app.globalData.cart = items;
    wx.setStorageSync('tx_cart', JSON.stringify(items));

    this.setData({
      items: items,
      totalFen: total,
      totalCount: count,
      finalTotalFen: Math.max(0, total - this.data.discountFen),
    });
    this._checkAddonTip(total);
  },

  // ─── 单品备注 ───

  onItemRemarkInput: function (e) {
    var idx = e.currentTarget.dataset.index;
    var value = e.detail.value;
    var items = this.data.items.slice();
    if (items[idx]) {
      items[idx] = Object.assign({}, items[idx], { notes: value });
      this.setData({ items: items });
      if (app.globalData) app.globalData.cart = items;
      wx.setStorageSync('tx_cart', JSON.stringify(items));
    }
  },

  // ─── 整单备注 ───

  onNotesInput: function (e) {
    this.setData({ orderNotes: e.detail.value });
  },

  // ─── AA分摊 ───

  toggleAASplit: function () {
    var show = !this.data.showAASplit;
    this.setData({ showAASplit: show });
    if (show) this._calcPerPerson();
  },

  changePartySize: function (e) {
    var delta = parseInt(e.currentTarget.dataset.delta, 10);
    var size = Math.max(2, this.data.partySize + delta);
    this.setData({ partySize: size });
    this._calcPerPerson();
  },

  _calcPerPerson: function () {
    var perPerson = Math.ceil(this.data.finalTotalFen / this.data.partySize);
    this.setData({ perPersonFen: perPerson });
  },

  // ─── 支付方式 ───

  selectPayment: function (e) {
    var method = e.currentTarget.dataset.method;
    this.setData({ paymentMethod: method });
  },

  // ─── 结算弹层 ───

  openCheckoutSheet: function () {
    if (this.data.items.length === 0) {
      wx.showToast({ title: '购物车为空', icon: 'none' });
      return;
    }
    this.setData({ showCheckoutSheet: true });
  },

  closeCheckoutSheet: function () {
    this.setData({ showCheckoutSheet: false });
  },

  // ─── 继续点菜 ───

  goBackToMenu: function () {
    wx.navigateBack({ delta: 1 });
  },

  // ─── 确认下单 ───

  submitOrder: function () {
    var self = this;
    if (self.data.submitting) return;
    if (self.data.items.length === 0) {
      wx.showToast({ title: '购物车为空', icon: 'none' });
      return;
    }

    self.setData({ submitting: true });
    wx.showLoading({ title: '下单中...' });

    var orderData = {
      store_id: app.globalData.storeId || '',
      table_id: app.globalData.tableId || '',
      table_no: self.data.tableNo,
      customer_id: wx.getStorageSync('tx_customer_id') || '',
      items: self.data.items.map(function (item) {
        return {
          dish_id: item.dishId,
          dish_name: item.dishName,
          quantity: item.quantity,
          unit_price_fen: item.unitPriceFen,
          remark: item.notes || '',
        };
      }),
      coupon_id: self.data.selectedCoupon ? self.data.selectedCoupon.id : '',
      payment_method: self.data.paymentMethod,
      total_amount_fen: self.data.totalFen,
      discount_fen: self.data.discountFen,
      final_total_fen: self.data.finalTotalFen,
      remark: self.data.orderNotes,
      party_size: self.data.showAASplit ? self.data.partySize : 1,
    };

    api.createOrder(orderData)
      .then(function (data) {
        wx.hideLoading();
        // 清空购物车
        if (app.globalData) app.globalData.cart = [];
        wx.removeStorageSync('tx_cart');

        var orderId = data.id || data.order_id;
        wx.redirectTo({
          url: '/pages/order-track/order-track?order_id=' + encodeURIComponent(orderId),
        });
      })
      .catch(function (err) {
        wx.hideLoading();
        self.setData({ submitting: false });
        wx.showToast({ title: err.message || '下单失败，请重试', icon: 'none' });
      });
  },

  onShareAppMessage: function () {
    return {
      title: '快来一起点餐！',
      path: '/pages/menu/menu',
    };
  },
});
