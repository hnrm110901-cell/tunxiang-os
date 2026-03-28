// 会员中心 — 积分/余额/等级/权益
var app = getApp();
var api = require('../../utils/api.js');
var auth = require('../../utils/auth.js');

Page({
  data: {
    // 会员信息
    isLoggedIn: false,
    profile: {
      nickname: '',
      avatarUrl: '',
      phone: '',
      level: 'normal',
      pointsBalance: 0,
      balanceFen: 0,
      balanceYuan: '0.00',
      totalSpentYuan: '0.00',
      orderCount: 0,
    },
    // 菜单项
    menuItems: [
      { icon: '🎫', label: '我的优惠券', route: '/pages/coupon/coupon' },
      { icon: '📅', label: '我的预订', route: '/pages/reservation/reservation' },
      { icon: '🎫', label: '排队取号', route: '/pages/queue/queue' },
      { icon: '🏢', label: '企业团餐', route: '/pages/extra/corporate/corporate' },
      { icon: '⭐', label: '我的评价', route: '/pages/feedback/feedback' },
    ],
    // 积分明细
    showPointsLog: false,
    pointsLog: [],
    pointsPage: 1,
    // 余额明细
    showBalanceLog: false,
    balanceLog: [],
    balancePage: 1,
  },

  onShow: function () {
    this.setData({ isLoggedIn: auth.isLoggedIn() });
    if (auth.isLoggedIn()) {
      this._loadProfile();
    }
  },

  onPullDownRefresh: function () {
    var self = this;
    this._loadProfile().then(function () {
      wx.stopPullDownRefresh();
    }).catch(function () {
      wx.stopPullDownRefresh();
    });
  },

  onShareAppMessage: function () {
    return { title: '屯象点餐 - 会员中心', path: '/pages/member/member' };
  },

  // ─── 数据加载 ───

  _loadProfile: function () {
    var self = this;
    return api.fetchMemberProfile()
      .then(function (data) {
        self.setData({
          'profile.nickname': data.nickname || data.phone || '未设置昵称',
          'profile.avatarUrl': data.avatar_url || '',
          'profile.phone': data.phone || '',
          'profile.level': data.level || 'normal',
          'profile.pointsBalance': data.points_balance || 0,
          'profile.balanceFen': data.balance_fen || 0,
          'profile.balanceYuan': ((data.balance_fen || 0) / 100).toFixed(2),
          'profile.totalSpentYuan': ((data.total_spent_fen || 0) / 100).toFixed(2),
          'profile.orderCount': data.order_count || 0,
        });
      })
      .catch(function (err) {
        console.warn('加载会员信息失败', err);
      });
  },

  // ─── 登录 ───

  onGetPhoneNumber: function (e) {
    var self = this;
    auth.bindPhone(e)
      .then(function () {
        wx.showToast({ title: '登录成功', icon: 'success' });
        self.setData({ isLoggedIn: true });
        self._loadProfile();
      })
      .catch(function (err) {
        if (err.message && err.message.indexOf('拒绝') >= 0) {
          wx.showToast({ title: '需要授权手机号', icon: 'none' });
        } else {
          wx.showToast({ title: '登录失败', icon: 'none' });
        }
      });
  },

  // ─── 导航 ───

  goToRoute: function (e) {
    var route = e.currentTarget.dataset.route;
    wx.navigateTo({ url: route });
  },

  // ─── 积分明细 ───

  showPointsDetail: function () {
    this.setData({ showPointsLog: true, pointsLog: [], pointsPage: 1 });
    this._loadPointsLog();
  },

  closePointsLog: function () {
    this.setData({ showPointsLog: false });
  },

  _loadPointsLog: function () {
    var self = this;
    api.fetchPointsLog(self.data.pointsPage)
      .then(function (data) {
        var items = (data.items || []).map(function (p) {
          return {
            id: p.id,
            description: p.description || '',
            points: p.points || 0,
            createdAt: (p.created_at || '').slice(0, 16).replace('T', ' '),
          };
        });
        self.setData({
          pointsLog: self.data.pointsLog.concat(items),
        });
      })
      .catch(function (err) {
        console.warn('加载积分明细失败', err);
      });
  },

  // ─── 余额明细 ───

  showBalanceDetail: function () {
    this.setData({ showBalanceLog: true, balanceLog: [], balancePage: 1 });
    this._loadBalanceLog();
  },

  closeBalanceLog: function () {
    this.setData({ showBalanceLog: false });
  },

  _loadBalanceLog: function () {
    var self = this;
    api.fetchBalanceLog(self.data.balancePage)
      .then(function (data) {
        var items = (data.items || []).map(function (b) {
          return {
            id: b.id,
            description: b.description || '',
            amountFen: b.amount_fen || 0,
            amountYuan: (Math.abs(b.amount_fen || 0) / 100).toFixed(2),
            createdAt: (b.created_at || '').slice(0, 16).replace('T', ' '),
          };
        });
        self.setData({
          balanceLog: self.data.balanceLog.concat(items),
        });
      })
      .catch(function (err) {
        console.warn('加载余额明细失败', err);
      });
  },
});
