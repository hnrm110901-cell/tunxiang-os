// 储值卡充值页
// API:
//   GET  /api/v1/member/stored-value/balance/{card_id}  余额查询
//   GET  /api/v1/member/stored-value/plans              充值方案列表
//   POST /api/v1/member/stored-value/recharge           发起充值

var api = require('../../utils/api.js');

// Mock 充值方案（API 失败时降级）
var MOCK_PLANS = [
  { id: 'p1', amountYuan: 100, bonusYuan: 0, isCustom: false },
  { id: 'p2', amountYuan: 200, bonusYuan: 10, isCustom: false },
  { id: 'p3', amountYuan: 300, bonusYuan: 30, isCustom: false },
  { id: 'p4', amountYuan: 500, bonusYuan: 60, isCustom: false },
  { id: 'p5', amountYuan: 1000, bonusYuan: 150, isCustom: false },
  { id: 'custom', amountYuan: 0, bonusYuan: 0, isCustom: true },
];

Page({
  data: {
    // 余额
    balanceYuan: '0.00',
    levelName: '普通会员',
    // 充值方案
    plans: [],
    selectedIndex: -1,
    // 自定义金额
    showCustomInput: false,
    customAmount: '',
    // 充值金额
    rechargeAmountYuan: '0',
    canRecharge: false,
    // 充值说明
    showRules: false,
    // 状态
    loading: false,
  },

  onLoad: function () {
    this.loadBalance();
    this.loadPlans();
  },

  // ---------- 数据加载 ----------

  loadBalance: function () {
    var that = this;
    var memberId = wx.getStorageSync('tx_customer_id') || '';
    api.txRequest('/api/v1/member/stored-value/balance/' + memberId).then(function (data) {
      that.setData({
        balanceYuan: (data.balance_fen / 100).toFixed(2),
        levelName: data.level_name || '普通会员',
      });
    }).catch(function () {
      // 降级：从会员缓存取余额
      var profile = wx.getStorageSync('tx_member_profile') || {};
      that.setData({
        balanceYuan: profile.balanceYuan || '0.00',
        levelName: profile.levelName || '普通会员',
      });
    });
  },

  loadPlans: function () {
    var that = this;
    api.txRequest('/api/v1/member/stored-value/plans').then(function (data) {
      var list = (data.items || data || []).map(function (item) {
        return {
          id: item.id || item.plan_id,
          amountYuan: item.amount_fen ? item.amount_fen / 100 : item.amountYuan || 0,
          bonusYuan: item.bonus_fen ? item.bonus_fen / 100 : item.bonusYuan || 0,
          isCustom: false,
        };
      });
      // 追加自定义选项
      list.push({ id: 'custom', amountYuan: 0, bonusYuan: 0, isCustom: true });
      that.setData({ plans: list });
    }).catch(function () {
      that.setData({ plans: MOCK_PLANS });
    });
  },

  // ---------- 面额选择 ----------

  selectPlan: function (e) {
    var index = e.currentTarget.dataset.index;
    var plan = this.data.plans[index];
    if (plan.isCustom) {
      this.setData({
        selectedIndex: index,
        showCustomInput: true,
        rechargeAmountYuan: this.data.customAmount || '0',
        canRecharge: parseFloat(this.data.customAmount) >= 10,
      });
    } else {
      this.setData({
        selectedIndex: index,
        showCustomInput: false,
        customAmount: '',
        rechargeAmountYuan: String(plan.amountYuan),
        canRecharge: true,
      });
    }
  },

  onCustomInput: function (e) {
    var val = e.detail.value;
    var num = parseFloat(val) || 0;
    this.setData({
      customAmount: val,
      rechargeAmountYuan: num >= 10 ? String(num) : '0',
      canRecharge: num >= 10,
    });
  },

  // ---------- 充值 ----------

  doRecharge: function () {
    if (this.data.loading || !this.data.canRecharge) return;
    var that = this;
    var amount = parseFloat(that.data.rechargeAmountYuan);
    if (isNaN(amount) || amount < 10) {
      wx.showToast({ title: '请选择充值金额', icon: 'none' });
      return;
    }

    var plan = that.data.plans[that.data.selectedIndex] || {};
    that.setData({ loading: true });

    var memberId = wx.getStorageSync('tx_customer_id') || '';
    api.txRequest('/api/v1/member/stored-value/recharge', 'POST', {
      member_id: memberId,
      plan_id: plan.id || null,
      amount_fen: Math.round(amount * 100),
    }).then(function (data) {
      // 调用微信支付
      that.callWxPay(data);
    }).catch(function () {
      // Mock 模式：直接模拟支付成功
      that.mockPaySuccess(amount);
    });
  },

  callWxPay: function (payData) {
    var that = this;
    if (!payData || !payData.timeStamp) {
      // 后端未返回支付参数，走 Mock
      that.mockPaySuccess(parseFloat(that.data.rechargeAmountYuan));
      return;
    }
    wx.requestPayment({
      timeStamp: payData.timeStamp,
      nonceStr: payData.nonceStr,
      package: payData.package,
      signType: payData.signType || 'MD5',
      paySign: payData.paySign,
      success: function () {
        that.onPaySuccess();
      },
      fail: function () {
        that.setData({ loading: false });
        wx.showToast({ title: '支付已取消', icon: 'none' });
      },
    });
  },

  mockPaySuccess: function (amount) {
    var that = this;
    wx.showLoading({ title: '处理中...' });
    setTimeout(function () {
      wx.hideLoading();
      that.onPaySuccess();
    }, 800);
  },

  onPaySuccess: function () {
    var that = this;
    that.setData({ loading: false });
    wx.showToast({ title: '充值成功', icon: 'success' });
    // 刷新余额
    that.loadBalance();
    // 重置选择
    that.setData({
      selectedIndex: -1,
      showCustomInput: false,
      customAmount: '',
      rechargeAmountYuan: '0',
      canRecharge: false,
    });
  },

  // ---------- 导航 ----------

  goDetail: function () {
    wx.navigateTo({ url: '/pages/stored-value-detail/stored-value-detail' });
  },

  // ---------- 充值说明 ----------

  toggleRules: function () {
    this.setData({ showRules: !this.data.showRules });
  },
});
