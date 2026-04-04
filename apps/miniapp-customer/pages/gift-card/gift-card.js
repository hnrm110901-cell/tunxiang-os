// 礼品卡 — 购买 + 我的礼品卡
// API:
//   POST /api/v1/member/gift-cards/purchase    购买礼品卡
//   GET  /api/v1/member/gift-cards/list        我的礼品卡列表

var api = require('../../utils/api.js');

// Mock 我的礼品卡
var MOCK_CARDS = {
  received: [
    { id: 'gc1', amount_fen: 20000, theme: 'birthday', bless_msg: '生日快乐！', status: 'unused', sender_phone: '138****8888', created_at: '2026-03-20T08:00:00Z' },
    { id: 'gc2', amount_fen: 10000, theme: 'thanks', bless_msg: '谢谢你的帮助', status: 'used', sender_phone: '139****9999', created_at: '2026-03-10T12:00:00Z' },
  ],
  sent: [
    { id: 'gc3', amount_fen: 50000, theme: 'holiday', bless_msg: '节日快乐，多吃好的', status: 'unused', recipient_phone: '137****7777', created_at: '2026-03-25T15:00:00Z' },
  ],
};

var STATUS_MAP = {
  unused: '未使用',
  used: '已使用',
  expired: '已过期',
};

Page({
  data: {
    // 主 Tab
    mainTab: 'buy',
    // 购买
    amounts: [100, 200, 500, 1000],
    selectedAmount: 0,
    themes: [
      { id: 'birthday', name: '生日祝福', icon: '🎂' },
      { id: 'thanks', name: '感谢有你', icon: '💐' },
      { id: 'holiday', name: '节日快乐', icon: '🎉' },
      { id: 'love', name: '心意满满', icon: '❤️' },
    ],
    selectedTheme: '',
    blessMsg: '',
    recipientPhone: '',
    canBuy: false,
    // 我的礼品卡
    mineTab: 'received',
    myCards: [],
    loading: false,
  },

  onLoad: function () {
    // 默认购买页，无需加载列表
  },

  // ---------- 主 Tab ----------

  switchMainTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    if (tab === this.data.mainTab) return;
    this.setData({ mainTab: tab });
    if (tab === 'mine') {
      this.loadMyCards();
    }
  },

  // ---------- 购买逻辑 ----------

  selectAmount: function (e) {
    var val = e.currentTarget.dataset.val;
    this.setData({ selectedAmount: val });
    this.checkCanBuy();
  },

  selectTheme: function (e) {
    var id = e.currentTarget.dataset.id;
    this.setData({ selectedTheme: id });
    this.checkCanBuy();
  },

  onBlessInput: function (e) {
    this.setData({ blessMsg: e.detail.value });
  },

  onPhoneInput: function (e) {
    this.setData({ recipientPhone: e.detail.value });
    this.checkCanBuy();
  },

  checkCanBuy: function () {
    var d = this.data;
    var phoneOk = /^1\d{10}$/.test(d.recipientPhone);
    this.setData({ canBuy: d.selectedAmount > 0 && d.selectedTheme && phoneOk });
  },

  doBuy: function () {
    if (!this.data.canBuy || this.data.loading) return;
    var that = this;
    that.setData({ loading: true });

    var memberId = wx.getStorageSync('tx_customer_id') || '';
    api.txRequest('/api/v1/member/gift-cards/purchase', 'POST', {
      member_id: memberId,
      amount_fen: that.data.selectedAmount * 100,
      theme: that.data.selectedTheme,
      bless_msg: that.data.blessMsg,
      recipient_phone: that.data.recipientPhone,
    }).then(function (data) {
      that.callWxPay(data);
    }).catch(function () {
      // Mock 支付成功
      that.mockPaySuccess();
    });
  },

  callWxPay: function (payData) {
    var that = this;
    if (!payData || !payData.timeStamp) {
      that.mockPaySuccess();
      return;
    }
    wx.requestPayment({
      timeStamp: payData.timeStamp,
      nonceStr: payData.nonceStr,
      package: payData.package,
      signType: payData.signType || 'MD5',
      paySign: payData.paySign,
      success: function () {
        that.onBuySuccess();
      },
      fail: function () {
        that.setData({ loading: false });
        wx.showToast({ title: '支付已取消', icon: 'none' });
      },
    });
  },

  mockPaySuccess: function () {
    var that = this;
    wx.showLoading({ title: '处理中...' });
    setTimeout(function () {
      wx.hideLoading();
      that.onBuySuccess();
    }, 800);
  },

  onBuySuccess: function () {
    this.setData({ loading: false });
    wx.showToast({ title: '购买成功', icon: 'success' });
    // 重置表单
    this.setData({
      selectedAmount: 0,
      selectedTheme: '',
      blessMsg: '',
      recipientPhone: '',
      canBuy: false,
    });
  },

  // ---------- 我的礼品卡 ----------

  switchMineTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    if (tab === this.data.mineTab) return;
    this.setData({ mineTab: tab });
    this.loadMyCards();
  },

  loadMyCards: function () {
    var that = this;
    that.setData({ loading: true, myCards: [] });

    var memberId = wx.getStorageSync('tx_customer_id') || '';
    var direction = that.data.mineTab; // received / sent

    api.txRequest('/api/v1/member/gift-cards/list?member_id=' + memberId + '&direction=' + direction).then(function (data) {
      var items = (data.items || []).map(function (item) {
        return that.formatCard(item);
      });
      that.setData({ myCards: items, loading: false });
    }).catch(function () {
      // 降级 Mock
      var items = (MOCK_CARDS[direction] || []).map(function (item) {
        return that.formatCard(item);
      });
      that.setData({ myCards: items, loading: false });
    });
  },

  formatCard: function (item) {
    var timeStr = '';
    if (item.created_at) {
      var d = new Date(item.created_at);
      timeStr = d.getFullYear() + '-' +
        ('0' + (d.getMonth() + 1)).slice(-2) + '-' +
        ('0' + d.getDate()).slice(-2);
    }
    return {
      id: item.id,
      amountYuan: ((item.amount_fen || 0) / 100).toFixed(0),
      theme: item.theme || 'birthday',
      blessMsg: item.bless_msg || '',
      status: item.status || 'unused',
      statusText: STATUS_MAP[item.status] || '未使用',
      senderPhone: item.sender_phone || '',
      senderName: item.sender_name || '',
      recipientPhone: item.recipient_phone || '',
      timeStr: timeStr,
    };
  },
});
