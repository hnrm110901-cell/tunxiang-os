// 企事业用餐首页 — 企业账户/快速点餐/预订会议餐/月度账单/多身份切换
// 复用 enterprise_account 后端

var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // ─── 多企业身份切换 ───
    enterprises: [],       // 用户所属企业列表
    currentEnterprise: null, // 当前选中企业
    showSwitcher: false,

    // ─── 企业账户概览 ───
    account: {
      balance_fen: 0,
      credit_limit_fen: 0,
      used_fen: 0,
      available_fen: 0,
      billing_cycle: 'monthly',
    },

    // ─── 快捷入口 ───
    quickActions: [
      { key: 'quick_order', icon: '/assets/icon-quick-order.png', label: '快速点餐', desc: '企业套餐' },
      { key: 'meeting_meal', icon: '/assets/icon-meeting.png', label: '预订会议餐', desc: '提前预约' },
      { key: 'monthly_bill', icon: '/assets/icon-bill.png', label: '月度账单', desc: '对账查询' },
      { key: 'sign_records', icon: '/assets/icon-sign.png', label: '签单记录', desc: '授权明细' },
    ],

    // ─── 企业套餐推荐 ───
    packageList: [],
    loadingPackages: false,

    // ─── 最近订单 ───
    recentOrders: [],
  },

  onLoad: function () {
    this.loadEnterprises();
  },

  onShow: function () {
    if (this.data.currentEnterprise) {
      this.loadAccount();
      this.loadPackages();
      this.loadRecentOrders();
    }
  },

  onPullDownRefresh: function () {
    this.loadAccount();
    this.loadPackages();
    this.loadRecentOrders();
    wx.stopPullDownRefresh();
  },

  // ─── 加载用户所属企业列表（多身份） ───
  loadEnterprises: function () {
    var self = this;
    api.get('/api/v1/enterprise/my-enterprises').then(function (res) {
      if (res.ok && res.data.items && res.data.items.length > 0) {
        var enterprises = res.data.items;
        var current = enterprises[0]; // 默认第一个
        self.setData({
          enterprises: enterprises,
          currentEnterprise: current,
        });
        self.loadAccount();
        self.loadPackages();
        self.loadRecentOrders();
      } else {
        // 没有企业身份
        self.setData({ enterprises: [], currentEnterprise: null });
      }
    });
  },

  // ─── 加载企业账户信息 ───
  loadAccount: function () {
    var self = this;
    if (!self.data.currentEnterprise) return;

    api.get('/api/v1/enterprise/' + self.data.currentEnterprise.id + '/account').then(function (res) {
      if (res.ok) {
        self.setData({ account: res.data });
      }
    });
  },

  // ─── 加载企业套餐 ───
  loadPackages: function () {
    var self = this;
    if (!self.data.currentEnterprise) return;

    self.setData({ loadingPackages: true });
    api.get('/api/v1/enterprise/' + self.data.currentEnterprise.id + '/packages').then(function (res) {
      if (res.ok) {
        self.setData({ packageList: res.data.items || [], loadingPackages: false });
      } else {
        self.setData({ loadingPackages: false });
      }
    });
  },

  // ─── 加载最近订单 ───
  loadRecentOrders: function () {
    var self = this;
    if (!self.data.currentEnterprise) return;

    api.get('/api/v1/enterprise/' + self.data.currentEnterprise.id + '/orders', {
      page: 1, size: 5,
    }).then(function (res) {
      if (res.ok) {
        self.setData({ recentOrders: res.data.items || [] });
      }
    });
  },

  // ─── 切换企业身份 ───
  toggleSwitcher: function () {
    this.setData({ showSwitcher: !this.data.showSwitcher });
  },

  switchEnterprise: function (e) {
    var enterprise = e.currentTarget.dataset.enterprise;
    this.setData({
      currentEnterprise: enterprise,
      showSwitcher: false,
    });
    this.loadAccount();
    this.loadPackages();
    this.loadRecentOrders();
  },

  // ─── 快捷入口跳转 ───
  onQuickAction: function (e) {
    var key = e.currentTarget.dataset.key;
    var eid = this.data.currentEnterprise ? this.data.currentEnterprise.id : '';

    switch (key) {
      case 'quick_order':
        wx.navigateTo({ url: '/pages/menu/menu?enterprise_id=' + eid + '&mode=corporate' });
        break;
      case 'meeting_meal':
        wx.navigateTo({ url: '/pages/reservation/reservation?enterprise_id=' + eid + '&type=meeting' });
        break;
      case 'monthly_bill':
        wx.navigateTo({ url: '/pages/extra/invoice/invoice?enterprise_id=' + eid });
        break;
      case 'sign_records':
        wx.navigateTo({ url: '/pages/extra/corporate/corporate?enterprise_id=' + eid });
        break;
    }
  },

  // ─── 查看全部订单 ───
  goToAllOrders: function () {
    var eid = this.data.currentEnterprise ? this.data.currentEnterprise.id : '';
    wx.navigateTo({ url: '/pages/order/order?enterprise_id=' + eid });
  },

  // ─── 选择套餐 ───
  selectPackage: function (e) {
    var pkg = e.currentTarget.dataset.pkg;
    var eid = this.data.currentEnterprise ? this.data.currentEnterprise.id : '';
    wx.navigateTo({
      url: '/pages/menu/menu?enterprise_id=' + eid + '&package_id=' + pkg.id + '&mode=corporate',
    });
  },
});
