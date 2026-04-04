// 外卖结算页
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 地址
    address: null,
    // 菜品
    items: [],
    storeId: '',
    // 配送时间
    deliveryType: 'now', // now | schedule
    deliveryTimeText: '立即配送',
    estimatedTime: '',
    scheduleTime: '',
    scheduleStart: '',
    showTimeSelect: false,
    // 餐具
    utensilCount: 1,
    // 优惠券
    coupon: null,
    couponYuan: '0.00',
    couponCount: 0,
    // 备注
    remark: '',
    // 费用
    dishTotalFen: 0,
    dishTotalYuan: '0.00',
    deliveryFeeFen: 500, // 5元配送费
    deliveryFeeYuan: '5.00',
    packFeeFen: 0,
    packFeeYuan: '0.00',
    payTotalFen: 0,
    payTotalYuan: '0.00',
    // 提交
    submitting: false,
  },

  onLoad: function () {
    var cartData = app.globalData.takeawayCart || {};
    var items = (cartData.items || []).map(function (item) {
      var sub = item.priceFen * item.quantity;
      return {
        id: item.id,
        name: item.name,
        priceFen: item.priceFen,
        displayPrice: item.displayPrice,
        quantity: item.quantity,
        subtotalFen: sub,
        subtotalYuan: (sub / 100).toFixed(2),
      };
    });

    // 包装费：每个菜品1元
    var packFen = items.length * 100;

    this.setData({
      address: cartData.address || null,
      storeId: cartData.storeId || '',
      items: items,
      packFeeFen: packFen,
      packFeeYuan: (packFen / 100).toFixed(2),
    });

    this._calcEstimatedTime();
    this._calcTotal();
    this._loadCoupons();
  },

  // ─── 地址 ───

  changeAddress: function () {
    wx.navigateTo({ url: '/pages/address/address?select=1' });
  },

  onShow: function () {
    var pages = getCurrentPages();
    var curr = pages[pages.length - 1];
    if (curr._selectedAddress) {
      this.setData({ address: curr._selectedAddress });
      curr._selectedAddress = null;
    }
  },

  // ─── 配送时间 ───

  _calcEstimatedTime: function () {
    var now = new Date();
    var min = now.getMinutes() + 35;
    var h = now.getHours();
    if (min >= 60) { h += 1; min -= 60; }
    if (h >= 24) h -= 24;
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    var t = pad(h) + ':' + pad(min);
    var startMin = min + 15;
    var startH = h;
    if (startMin >= 60) { startH += 1; startMin -= 60; }
    this.setData({
      estimatedTime: t,
      scheduleStart: pad(startH) + ':' + pad(startMin),
    });
  },

  showTimePicker: function () {
    this.setData({ showTimeSelect: true });
  },

  hideTimePicker: function () {
    this.setData({ showTimeSelect: false });
  },

  selectDeliveryType: function (e) {
    this.setData({ deliveryType: e.currentTarget.dataset.type });
  },

  onScheduleTimeChange: function (e) {
    this.setData({ scheduleTime: e.detail.value });
  },

  confirmTimePicker: function () {
    var text = '立即配送';
    if (this.data.deliveryType === 'schedule' && this.data.scheduleTime) {
      text = '预约 ' + this.data.scheduleTime + ' 送达';
    }
    this.setData({ deliveryTimeText: text, showTimeSelect: false });
  },

  // ─── 菜品数量编辑 ───

  plusItem: function (e) {
    var idx = e.currentTarget.dataset.idx;
    var items = this.data.items;
    items[idx].quantity += 1;
    items[idx].subtotalFen = items[idx].priceFen * items[idx].quantity;
    items[idx].subtotalYuan = (items[idx].subtotalFen / 100).toFixed(2);
    this.setData({ items: items });
    this._calcTotal();
  },

  minusItem: function (e) {
    var idx = e.currentTarget.dataset.idx;
    var items = this.data.items;
    if (items[idx].quantity <= 1) {
      // 最后一件，确认移除
      var self = this;
      wx.showModal({
        title: '提示',
        content: '确定移除该菜品？',
        success: function (res) {
          if (res.confirm) {
            items.splice(idx, 1);
            self.setData({ items: items });
            self._calcTotal();
            if (items.length === 0) {
              wx.navigateBack();
            }
          }
        },
      });
      return;
    }
    items[idx].quantity -= 1;
    items[idx].subtotalFen = items[idx].priceFen * items[idx].quantity;
    items[idx].subtotalYuan = (items[idx].subtotalFen / 100).toFixed(2);
    this.setData({ items: items });
    this._calcTotal();
  },

  // ─── 餐具 ───

  plusUten: function () {
    this.setData({ utensilCount: this.data.utensilCount + 1 });
  },

  minusUten: function () {
    if (this.data.utensilCount <= 0) return;
    this.setData({ utensilCount: this.data.utensilCount - 1 });
  },

  // ─── 优惠券 ───

  _loadCoupons: function () {
    var self = this;
    api.fetchMyCoupons()
      .then(function (data) {
        var count = (data.items || data || []).length;
        self.setData({ couponCount: count });
      })
      .catch(function () {
        self.setData({ couponCount: 2 }); // Mock
      });
  },

  chooseCoupon: function () {
    // 简化：跳到优惠券页选择
    wx.navigateTo({ url: '/pages/coupon/coupon?select=1' });
  },

  // ─── 备注 ───

  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value });
  },

  // ─── 费用计算 ───

  _calcTotal: function () {
    var dishFen = 0;
    var items = this.data.items;
    for (var i = 0; i < items.length; i++) {
      dishFen += items[i].subtotalFen;
    }
    var couponFen = this.data.coupon ? this.data.coupon.amountFen : 0;
    var total = dishFen + this.data.deliveryFeeFen + this.data.packFeeFen - couponFen;
    if (total < 0) total = 0;
    this.setData({
      dishTotalFen: dishFen,
      dishTotalYuan: (dishFen / 100).toFixed(2),
      payTotalFen: total,
      payTotalYuan: (total / 100).toFixed(2),
    });
  },

  // ─── 提交订单 ───

  submitOrder: function () {
    if (this.data.submitting) return;
    if (!this.data.address) {
      wx.showToast({ title: '请选择配送地址', icon: 'none' });
      return;
    }
    if (this.data.items.length === 0) {
      wx.showToast({ title: '请添加菜品', icon: 'none' });
      return;
    }

    var self = this;
    self.setData({ submitting: true });

    var orderItems = self.data.items.map(function (item) {
      return { dish_id: item.id, quantity: item.quantity, price_fen: item.priceFen };
    });

    var orderData = {
      store_id: self.data.storeId,
      order_type: 'takeaway',
      address_id: self.data.address.id,
      items: orderItems,
      delivery_type: self.data.deliveryType,
      schedule_time: self.data.deliveryType === 'schedule' ? self.data.scheduleTime : '',
      utensil_count: self.data.utensilCount,
      coupon_id: self.data.coupon ? self.data.coupon.id : '',
      remark: self.data.remark,
      delivery_fee_fen: self.data.deliveryFeeFen,
      pack_fee_fen: self.data.packFeeFen,
      total_fen: self.data.payTotalFen,
    };

    api.createTakeawayOrder(orderData)
      .then(function (data) {
        var orderId = data.order_id || data.id || 'mock_order_001';
        // 调起微信支付
        self._requestPayment(orderId, self.data.payTotalFen);
      })
      .catch(function (err) {
        console.warn('创建外卖订单失败，Mock跳转', err);
        // Mock：直接跳转订单跟踪
        self.setData({ submitting: false });
        wx.redirectTo({ url: '/pages/takeaway-track/takeaway-track?order_id=mock_order_001' });
      });
  },

  _requestPayment: function (orderId, totalFen) {
    var self = this;
    api.createPayment(orderId, 'wechat', totalFen)
      .then(function (payData) {
        wx.requestPayment({
          timeStamp: payData.timeStamp || '',
          nonceStr: payData.nonceStr || '',
          package: payData.package || '',
          signType: payData.signType || 'MD5',
          paySign: payData.paySign || '',
          success: function () {
            wx.redirectTo({ url: '/pages/takeaway-track/takeaway-track?order_id=' + orderId });
          },
          fail: function () {
            self.setData({ submitting: false });
            wx.showToast({ title: '支付取消', icon: 'none' });
          },
        });
      })
      .catch(function () {
        // Mock：直接跳转
        self.setData({ submitting: false });
        wx.redirectTo({ url: '/pages/takeaway-track/takeaway-track?order_id=' + orderId });
      });
  },
});
