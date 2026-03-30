// 智能购物车 — 已选清单 + 凑单提示 + AA分摊 + 优惠自动匹配 + 下单
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 已选菜品
    items: [],
    totalFen: 0,
    tableNo: '',

    // 凑单提示
    addonTip: '',
    addonThreshold: 0,
    addonGapFen: 0,

    // AA分摊
    showAASplit: false,
    partySize: 2,
    perPersonFen: 0,

    // 可用优惠
    availableCoupons: [],
    selectedCoupon: null,
    discountFen: 0,
    finalTotalFen: 0,

    // 备注
    orderNotes: '',
  },

  onLoad: function (options) {
    var tableNo = options.table || '';
    var total = parseInt(options.total, 10) || 0;
    var items = [];

    try {
      items = JSON.parse(decodeURIComponent(options.items || '[]'));
    } catch (e) {
      items = [];
    }

    this.setData({
      items: items,
      totalFen: total,
      finalTotalFen: total,
      tableNo: tableNo,
    });

    this._checkAddonTip(total);
    this._loadCoupons(total);
  },

  // ─── 凑单提示 ───

  _checkAddonTip: function (total) {
    var thresholds = [5000, 8000, 10000, 15000];
    for (var i = 0; i < thresholds.length; i++) {
      var gap = thresholds[i] - total;
      if (gap > 0 && gap <= 2000) {
        this.setData({
          addonTip: '再点¥' + (gap / 100).toFixed(0) + '享满' + (thresholds[i] / 100) + '减优惠',
          addonThreshold: thresholds[i],
          addonGapFen: gap,
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
          var minAmount = c.min_amount_fen || 0;
          return total >= minAmount;
        });
        // Auto-select best coupon
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
    var item = items[idx];
    if (!item) return;

    item.quantity = Math.max(0, item.quantity + delta);
    if (item.quantity === 0) {
      items.splice(idx, 1);
    }

    var total = 0;
    items.forEach(function (it) {
      total += (it.unitPriceFen || 0) * it.quantity;
    });

    this.setData({
      items: items,
      totalFen: total,
      finalTotalFen: Math.max(0, total - this.data.discountFen),
    });
    this._checkAddonTip(total);
  },

  removeItem: function (e) {
    var idx = e.currentTarget.dataset.index;
    var items = this.data.items.slice();
    items.splice(idx, 1);

    var total = 0;
    items.forEach(function (it) {
      total += (it.unitPriceFen || 0) * it.quantity;
    });

    this.setData({
      items: items,
      totalFen: total,
      finalTotalFen: Math.max(0, total - this.data.discountFen),
    });
    this._checkAddonTip(total);
  },

  // ─── AA分摊 ───

  toggleAASplit: function () {
    var show = !this.data.showAASplit;
    this.setData({ showAASplit: show });
    if (show) {
      this._calcPerPerson();
    }
  },

  changePartySize: function (e) {
    var delta = parseInt(e.currentTarget.dataset.delta, 10);
    var size = Math.max(2, this.data.partySize + delta);
    this.setData({ partySize: size });
    this._calcPerPerson();
  },

  _calcPerPerson: function () {
    var total = this.data.finalTotalFen;
    var perPerson = Math.ceil(total / this.data.partySize);
    this.setData({ perPersonFen: perPerson });
  },

  // ─── 备注 ───

  onNotesInput: function (e) {
    this.setData({ orderNotes: e.detail.value });
  },

  // ─── 继续点菜 ───

  goBackToMenu: function () {
    wx.navigateBack();
  },

  // ─── 下单 ───

  submitOrder: function () {
    var self = this;
    if (self.data.items.length === 0) {
      wx.showToast({ title: '购物车为空', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '下单中...' });

    var orderData = {
      store_id: app.globalData.storeId,
      customer_id: wx.getStorageSync('tx_customer_id') || '',
      table_no: self.data.tableNo,
      items: self.data.items.map(function (item) {
        return {
          dish_id: item.dishId,
          dish_name: item.dishName,
          quantity: item.quantity,
          unit_price_fen: item.unitPriceFen,
          notes: item.notes || '',
        };
      }),
      total_fen: self.data.totalFen,
      discount_fen: self.data.discountFen,
      final_total_fen: self.data.finalTotalFen,
      coupon_id: self.data.selectedCoupon ? self.data.selectedCoupon.id : '',
      notes: self.data.orderNotes,
      party_size: self.data.showAASplit ? self.data.partySize : 1,
    };

    api.createOrder(orderData)
      .then(function (data) {
        wx.hideLoading();
        var orderId = data.id || data.order_id;
        wx.redirectTo({
          url: '/pages/order-track/order-track?order_id=' + orderId,
        });
      })
      .catch(function (err) {
        wx.hideLoading();
        wx.showToast({ title: err.message || '下单失败', icon: 'none' });
      });
  },
});
