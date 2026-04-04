// 支付结果页
var app = getApp();

Page({
  data: {
    status: 'success', // success / fail
    orderId: '',
    amountFen: 0,
    amountYuan: '0.00',
    method: 'wechat',
    methodLabel: '微信支付',
    earnedPoints: 0,
    reason: '',

    // 出餐提示
    estimatedMinutes: 15,
    showCookTip: true,
    showProgressHint: false,
  },

  _hintTimer: null,

  onLoad: function (options) {
    var status = options.status || 'success';
    var orderId = options.order_id || '';
    var amountFen = parseInt(options.amount_fen, 10) || 0;
    var method = options.method || 'wechat';
    var earnedPoints = parseInt(options.earned_points, 10) || 0;
    var reason = decodeURIComponent(options.reason || '');

    var methodLabels = {
      wechat: '微信支付',
      stored_value: '储值卡支付',
      mixed: '混合支付',
      zero: '优惠抵扣',
    };

    this.setData({
      status: status,
      orderId: orderId,
      amountFen: amountFen,
      amountYuan: (amountFen / 100).toFixed(2),
      method: method,
      methodLabel: methodLabels[method] || '微信支付',
      earnedPoints: earnedPoints,
      reason: reason,
      showCookTip: status === 'success',
    });

    // 成功页 5 秒后提示查看出餐进度
    if (status === 'success') {
      var self = this;
      this._hintTimer = setTimeout(function () {
        self.setData({ showProgressHint: true });
      }, 5000);
    }
  },

  onUnload: function () {
    if (this._hintTimer) {
      clearTimeout(this._hintTimer);
      this._hintTimer = null;
    }
  },

  // ─── 查看订单 ───

  goOrderDetail: function () {
    wx.redirectTo({
      url: '/pages/order-track/order-track?order_id=' + encodeURIComponent(this.data.orderId),
    });
  },

  // ─── 返回首页 ───

  goHome: function () {
    wx.switchTab({ url: '/pages/index/index' });
  },

  // ─── 重新支付 ───

  goRetryPay: function () {
    wx.navigateBack({ delta: 1 });
  },

  // ─── 返回修改 ───

  goBack: function () {
    wx.navigateBack({ delta: 2 });
  },
});
