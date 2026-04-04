// 支付选择页
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 订单信息（从上一页传入）
    orderId: '',
    totalFen: 0,
    totalCount: 0,
    totalYuan: '0.00',

    // 支付方式
    payMethod: 'wechat', // wechat / stored_value / mixed

    // 储值卡
    storedValueBalance: 0,
    svBalanceYuan: '0.00',

    // 混合支付：微信补足部分
    mixWechatFen: 0,
    mixWechatYuan: '0.00',

    // 优惠券
    availableCoupons: [],
    selectedCoupon: null,
    couponDiscountFen: 0,
    couponDiscountYuan: '0.00',
    showCouponPopup: false,

    // 积分
    availablePoints: 0,
    pointsDeductFen: 0,
    pointsDeductYuan: '0.00',
    pointsRate: 100, // 100积分=1元
    usePoints: false,

    // 最终支付金额
    finalTotalFen: 0,
    payAmountYuan: '0.00',

    // 状态
    submitting: false,
  },

  onLoad: function (options) {
    var orderId = options.order_id || '';
    var totalFen = parseInt(options.total_fen, 10) || 0;
    var totalCount = parseInt(options.total_count, 10) || 0;
    var couponId = options.coupon_id || '';
    var discountFen = parseInt(options.discount_fen, 10) || 0;

    this.setData({
      orderId: orderId,
      totalFen: totalFen,
      totalCount: totalCount,
      totalYuan: (totalFen / 100).toFixed(2),
      couponDiscountFen: discountFen,
      couponDiscountYuan: (discountFen / 100).toFixed(2),
    });

    this._loadMemberInfo();
    this._loadCoupons(totalFen, couponId);
    this._recalc();
  },

  // ─── 加载会员信息 ───

  _loadMemberInfo: function () {
    var self = this;
    api.fetchMemberProfile()
      .then(function (data) {
        var balance = data.stored_value_balance_fen || 0;
        var points = data.points || data.available_points || 0;
        var pointsRate = data.points_rate || 100;
        var maxDeductFen = Math.floor(points / pointsRate) * 100;
        // 积分抵扣上限：不超过订单总额的50%
        var maxAllow = Math.floor(self.data.totalFen * 0.5);
        var deductFen = Math.min(maxDeductFen, maxAllow);

        self.setData({
          storedValueBalance: balance,
          svBalanceYuan: (balance / 100).toFixed(2),
          availablePoints: points,
          pointsRate: pointsRate,
          pointsDeductFen: deductFen,
          pointsDeductYuan: (deductFen / 100).toFixed(2),
        });
        self._recalc();
      })
      .catch(function () {
        // Mock 降级
        self.setData({
          storedValueBalance: 8800,
          svBalanceYuan: '88.00',
          availablePoints: 520,
          pointsDeductFen: 500,
          pointsDeductYuan: '5.00',
        });
        self._recalc();
      });
  },

  // ─── 加载优惠券 ───

  _loadCoupons: function (totalFen, preSelectedCouponId) {
    var self = this;
    api.fetchCoupons('available')
      .then(function (data) {
        var coupons = (data.items || data || []).filter(function (c) {
          return totalFen >= (c.min_amount_fen || 0);
        });

        var selected = null;
        var discount = 0;
        if (preSelectedCouponId) {
          for (var i = 0; i < coupons.length; i++) {
            if (coupons[i].id === preSelectedCouponId) {
              selected = coupons[i];
              discount = coupons[i].discount_fen || coupons[i].amount_fen || 0;
              break;
            }
          }
        }
        // 如果传了 discount_fen 但没匹配到券，保留从上一页传入的折扣
        if (!selected && self.data.couponDiscountFen > 0) {
          discount = self.data.couponDiscountFen;
        }

        self.setData({
          availableCoupons: coupons,
          selectedCoupon: selected,
          couponDiscountFen: discount,
          couponDiscountYuan: (discount / 100).toFixed(2),
        });
        self._recalc();
      })
      .catch(function () {
        // 保留上一页传入的折扣
        self._recalc();
      });
  },

  // ─── 支付方式选择 ───

  onSelectMethod: function (e) {
    var method = e.currentTarget.dataset.method;
    // 储值卡余额不足时不可选
    if (method === 'stored_value' && this.data.storedValueBalance < this.data.finalTotalFen) {
      wx.showToast({ title: '储值卡余额不足', icon: 'none' });
      return;
    }
    this.setData({ payMethod: method });
    this._recalc();
  },

  // ─── 优惠券操作 ───

  onChangeCoupon: function () {
    this.setData({ showCouponPopup: true });
  },

  onCloseCouponPopup: function () {
    this.setData({ showCouponPopup: false });
  },

  onPickCoupon: function (e) {
    var idx = e.currentTarget.dataset.index;
    var coupon = this.data.availableCoupons[idx];
    var discount = coupon ? (coupon.discount_fen || coupon.amount_fen || 0) : 0;
    this.setData({
      selectedCoupon: coupon || null,
      couponDiscountFen: discount,
      couponDiscountYuan: (discount / 100).toFixed(2),
      showCouponPopup: false,
    });
    this._recalc();
  },

  onClearCoupon: function () {
    this.setData({
      selectedCoupon: null,
      couponDiscountFen: 0,
      couponDiscountYuan: '0.00',
    });
    this._recalc();
  },

  // ─── 积分开关 ───

  onTogglePoints: function (e) {
    this.setData({ usePoints: e.detail.value });
    this._recalc();
  },

  // ─── 重新计算金额 ───

  _recalc: function () {
    var total = this.data.totalFen;
    var discount = this.data.couponDiscountFen;
    var pointsDeduct = this.data.usePoints ? this.data.pointsDeductFen : 0;
    var finalTotal = Math.max(0, total - discount - pointsDeduct);

    // 混合支付：微信补足
    var mixWechatFen = 0;
    if (this.data.payMethod === 'mixed') {
      mixWechatFen = Math.max(0, finalTotal - this.data.storedValueBalance);
    }

    this.setData({
      finalTotalFen: finalTotal,
      payAmountYuan: (finalTotal / 100).toFixed(2),
      mixWechatFen: mixWechatFen,
      mixWechatYuan: (mixWechatFen / 100).toFixed(2),
    });
  },

  // ─── 确认支付 ───

  onConfirmPay: function () {
    var self = this;
    if (self.data.submitting) return;
    if (self.data.finalTotalFen <= 0) {
      // 0元订单直接完成
      self._doZeroPay();
      return;
    }

    self.setData({ submitting: true });
    wx.showLoading({ title: '支付中...' });

    var method = self.data.payMethod;
    var orderId = self.data.orderId;
    var amountFen = self.data.finalTotalFen;

    // 调用后端创建支付
    api.createPayment(orderId, method, amountFen)
      .then(function (payData) {
        wx.hideLoading();

        if (method === 'wechat' || method === 'mixed') {
          // 调用微信支付
          self._callWxPay(payData, orderId);
        } else if (method === 'stored_value') {
          // 储值卡直接扣款成功
          self._onPaySuccess(orderId, payData);
        }
      })
      .catch(function (err) {
        wx.hideLoading();
        self.setData({ submitting: false });
        // Mock 降级：模拟支付成功
        self._mockPay(orderId);
      });
  },

  // ─── 微信支付调用 ───

  _callWxPay: function (payData, orderId) {
    var self = this;
    wx.requestPayment({
      timeStamp: payData.timeStamp || payData.timestamp || '',
      nonceStr: payData.nonceStr || payData.nonce_str || '',
      package: payData.package || payData.prepay_id || '',
      signType: payData.signType || 'MD5',
      paySign: payData.paySign || payData.pay_sign || '',
      success: function () {
        self._onPaySuccess(orderId, payData);
      },
      fail: function (err) {
        self.setData({ submitting: false });
        if (err.errMsg && err.errMsg.indexOf('cancel') !== -1) {
          wx.showToast({ title: '已取消支付', icon: 'none' });
        } else {
          self._onPayFail(orderId, err.errMsg || '支付失败');
        }
      },
    });
  },

  // ─── 0元支付 ───

  _doZeroPay: function () {
    var self = this;
    self.setData({ submitting: true });
    // 0元订单不需调微信支付，直接标记成功
    api.createPayment(self.data.orderId, 'zero', 0)
      .then(function (data) {
        self._onPaySuccess(self.data.orderId, data);
      })
      .catch(function () {
        // Mock 降级
        self._onPaySuccess(self.data.orderId, {});
      });
  },

  // ─── Mock 降级支付 ───

  _mockPay: function (orderId) {
    var self = this;
    wx.showModal({
      title: '开发模式',
      content: '后端暂未对接，模拟支付成功？',
      confirmText: '模拟成功',
      cancelText: '模拟失败',
      success: function (res) {
        if (res.confirm) {
          self._onPaySuccess(orderId, {});
        } else {
          self._onPayFail(orderId, '模拟支付失败');
        }
      },
    });
  },

  // ─── 支付成功 ───

  _onPaySuccess: function (orderId, payData) {
    // 清空购物车
    if (app.globalData) app.globalData.cart = [];
    wx.removeStorageSync('tx_cart');

    var earnedPoints = payData.earned_points || Math.floor(this.data.finalTotalFen / 100);

    wx.redirectTo({
      url: '/pages/pay-result/pay-result?status=success'
        + '&order_id=' + encodeURIComponent(orderId)
        + '&amount_fen=' + this.data.finalTotalFen
        + '&method=' + this.data.payMethod
        + '&earned_points=' + earnedPoints,
    });
  },

  // ─── 支付失败 ───

  _onPayFail: function (orderId, reason) {
    this.setData({ submitting: false });
    wx.redirectTo({
      url: '/pages/pay-result/pay-result?status=fail'
        + '&order_id=' + encodeURIComponent(orderId)
        + '&reason=' + encodeURIComponent(reason || '支付失败'),
    });
  },
});
