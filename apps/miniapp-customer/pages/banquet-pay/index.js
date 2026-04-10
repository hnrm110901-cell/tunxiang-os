/**
 * 宴席支付闭环页 — 定金/尾款状态机
 *
 * 路由参数：
 *   orderId  — 宴席订单 ID（必传）
 *
 * 流程：
 *   进入页面 → 拉取订单详情 → 展示支付进度
 *   → 选支付方式 → 支付定金 / 支付尾款
 *   → 微信 JSAPI 支付 → 回调刷新状态
 */

var api = require('../../utils/api.js');

// 支付方式中文标签
var METHOD_LABELS = {
  wechat: '微信支付',
  alipay: '支付宝',
  cash: '现金',
  card: '刷卡',
  transfer: '对公转账',
};

// 支付状态中文标签
var PAYMENT_STATUS_LABELS = {
  unpaid: '未支付',
  deposit_paid: '已付定金',
  fully_paid: '已全额付清',
  refunded: '已退款',
};

Page({
  data: {
    orderId: '',
    order: null,
    payments: [],
    loading: false,
    errorMsg: '',

    // 支付相关
    selectedMethod: 'wechat',
    paying: false,

    // 计算字段（在 setOrderData 中填充）
    totalYuan: '0.00',
    depositYuan: '0.00',
    balanceYuan: '0.00',
    depositRatePct: '30',
    paymentStatusLabel: '未支付',
    showPaySection: false,

    // 方法标签（传给 wxml）
    methodLabels: METHOD_LABELS,
  },

  // ─── 生命周期 ─────────────────────────────────────────────────────────────

  onLoad: function (options) {
    var orderId = options.orderId || '';
    if (!orderId) {
      this.setData({ errorMsg: '缺少订单号，请从预订列表进入' });
      return;
    }
    this.setData({ orderId: orderId });
    this.loadOrder();
  },

  onShow: function () {
    // 从支付结果页返回时刷新
    if (this.data.orderId) {
      this.loadOrder();
    }
  },

  onShareAppMessage: function () {
    return {
      title: '宴席预订支付',
      path: '/pages/banquet-pay/index?orderId=' + this.data.orderId,
    };
  },

  // ─── 数据加载 ─────────────────────────────────────────────────────────────

  loadOrder: function () {
    var self = this;
    var orderId = self.data.orderId;
    if (!orderId) return;

    self.setData({ loading: true, errorMsg: '' });

    api.txRequest('/api/v1/trade/banquet/orders/' + encodeURIComponent(orderId))
      .then(function (data) {
        self.setOrderData(data, data.payments || []);
        self.setData({ loading: false });
      })
      .catch(function (err) {
        self.setData({
          loading: false,
          errorMsg: err.message || '订单加载失败，请重试',
        });
      });
  },

  /**
   * 将订单数据写入 data，同时计算展示字段。
   * @param {object} order
   * @param {Array}  payments
   */
  setOrderData: function (order, payments) {
    var totalYuan = (order.total_fen / 100).toFixed(2);
    var depositYuan = (order.deposit_fen / 100).toFixed(2);
    var balanceYuan = (order.balance_fen / 100).toFixed(2);
    var depositRatePct = Math.round(parseFloat(order.deposit_rate) * 100).toString();
    var paymentStatusLabel = PAYMENT_STATUS_LABELS[order.payment_status] || order.payment_status;

    // 是否显示支付方式选择区
    var showPaySection =
      order.status !== 'cancelled' &&
      order.payment_status !== 'refunded' &&
      order.payment_status !== 'fully_paid';

    this.setData({
      order: order,
      payments: payments,
      totalYuan: totalYuan,
      depositYuan: depositYuan,
      balanceYuan: balanceYuan,
      depositRatePct: depositRatePct,
      paymentStatusLabel: paymentStatusLabel,
      showPaySection: showPaySection,
    });
  },

  // ─── 支付方式选择 ─────────────────────────────────────────────────────────

  selectMethod: function (e) {
    this.setData({ selectedMethod: e.currentTarget.dataset.method });
  },

  // ─── 支付定金 ─────────────────────────────────────────────────────────────

  onPayDeposit: function () {
    var self = this;
    if (self.data.paying) return;

    var order = self.data.order;
    if (!order) return;

    wx.showModal({
      title: '确认支付定金',
      content: '定金 ¥' + self.data.depositYuan + '（' + self.data.selectedMethod === 'wechat' ? '微信支付' : '支付宝' + '）',
      confirmText: '立即支付',
      confirmColor: '#FF6B35',
      success: function (res) {
        if (!res.confirm) return;

        if (self.data.selectedMethod === 'wechat') {
          self._payViaWechat('deposit', order.deposit_fen);
        } else {
          self._payMock('deposit', order.deposit_fen, self.data.selectedMethod);
        }
      },
    });
  },

  // ─── 支付尾款 ─────────────────────────────────────────────────────────────

  onPayBalance: function () {
    var self = this;
    if (self.data.paying) return;

    var order = self.data.order;
    if (!order) return;

    if (order.deposit_status !== 'paid') {
      wx.showToast({ title: '请先支付定金', icon: 'none' });
      return;
    }

    wx.showModal({
      title: '确认支付尾款',
      content: '尾款 ¥' + self.data.balanceYuan,
      confirmText: '立即支付',
      confirmColor: '#0F6E56',
      success: function (res) {
        if (!res.confirm) return;

        if (self.data.selectedMethod === 'wechat') {
          self._payViaWechat('balance', order.balance_fen);
        } else {
          self._payMock('balance', order.balance_fen, self.data.selectedMethod);
        }
      },
    });
  },

  // ─── 微信 JSAPI 支付（核心支付入口） ────────────────────────────────────

  _payViaWechat: function (stage, amountFen) {
    var self = this;
    var orderId = self.data.orderId;

    self.setData({ paying: true });
    wx.showLoading({ title: '支付准备中…', mask: true });

    // Step 1: 后端下单，获取 jsapi_params
    var endpoint = stage === 'deposit'
      ? '/api/v1/banquet/' + encodeURIComponent(orderId) + '/deposit/wechat-pay'
      : '/api/v1/trade/banquet/orders/' + encodeURIComponent(orderId) + '/pay-balance';

    // 获取 openid（已登录用户从缓存读取）
    var openid = wx.getStorageSync('tx_openid') || '';
    if (!openid) {
      wx.hideLoading();
      self.setData({ paying: false });
      wx.showToast({ title: '请先完成微信授权登录', icon: 'none' });
      return;
    }

    api.txRequest(endpoint, 'POST', {
      openid: openid,
      notify_url: 'https://api.tunxiang.com/api/v1/banquet/deposit/callback',
      payment_method: 'wechat',
      amount_fen: amountFen,
    })
      .then(function (data) {
        wx.hideLoading();
        // data.jsapi_params 由后端微信支付模块返回
        var params = data.jsapi_params || data;
        return new Promise(function (resolve, reject) {
          wx.requestPayment({
            timeStamp: params.timeStamp || params.timestamp || '',
            nonceStr: params.nonceStr || params.nonce_str || '',
            package: params.package || '',
            signType: params.signType || 'RSA',
            paySign: params.paySign || params.pay_sign || '',
            success: resolve,
            fail: reject,
          });
        });
      })
      .then(function () {
        // 支付成功
        self.setData({ paying: false });
        self._onPaySuccess(stage);
      })
      .catch(function (err) {
        self.setData({ paying: false });
        wx.hideLoading();
        var msg = err.errMsg || err.message || '支付失败';
        if (msg.indexOf('cancel') !== -1) {
          wx.showToast({ title: '已取消支付', icon: 'none' });
        } else {
          wx.showToast({ title: '支付失败：' + msg, icon: 'none', duration: 3000 });
        }
      });
  },

  /**
   * Mock 支付（非微信支付方式，直接调用状态机接口）
   * 生产环境中线下收款后由收银员操作后台完成，此处供开发测试。
   */
  _payMock: function (stage, amountFen, method) {
    var self = this;
    var orderId = self.data.orderId;

    self.setData({ paying: true });
    wx.showLoading({ title: '处理中…', mask: true });

    var endpoint = stage === 'deposit'
      ? '/api/v1/trade/banquet/orders/' + encodeURIComponent(orderId) + '/pay-deposit'
      : '/api/v1/trade/banquet/orders/' + encodeURIComponent(orderId) + '/pay-balance';

    api.txRequest(endpoint, 'POST', {
      payment_method: method,
      amount_fen: amountFen,
    })
      .then(function () {
        wx.hideLoading();
        self.setData({ paying: false });
        self._onPaySuccess(stage);
      })
      .catch(function (err) {
        wx.hideLoading();
        self.setData({ paying: false });
        wx.showToast({
          title: err.message || '支付失败',
          icon: 'none',
          duration: 3000,
        });
      });
  },

  // ─── 支付成功回调 ─────────────────────────────────────────────────────────

  _onPaySuccess: function (stage) {
    var label = stage === 'deposit' ? '定金' : '尾款';
    wx.showToast({
      title: label + '支付成功 ✓',
      icon: 'success',
      duration: 2000,
    });
    // 刷新订单状态
    this.loadOrder();
  },
});
