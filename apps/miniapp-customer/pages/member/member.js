// 会员中心 — 等级/积分/余额/优惠券/消费记录/个人信息编辑
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
      birthday: '',
      level: 'normal',
      levelName: '普通会员',
      pointsBalance: 0,
      balanceFen: 0,
      balanceYuan: '0.00',
      totalSpentYuan: '0.00',
      orderCount: 0,
    },
    // Member card level visual
    levelConfig: {
      normal: { name: '普通会员', gradient: 'linear-gradient(135deg, #1a2a33, #112228)' },
      silver: { name: '白银会员', gradient: 'linear-gradient(135deg, #4a5568, #2d3748)' },
      gold: { name: '黄金会员', gradient: 'linear-gradient(135deg, #d69e2e, #b7791f)' },
      diamond: { name: '钻石会员', gradient: 'linear-gradient(135deg, #667eea, #764ba2)' },
    },
    // 菜单项
    menuItems: [
      { icon: '\ud83c\udf81', label: '积分商城', route: '/pages/points-mall/points-mall' },
      { icon: '\ud83c\udf9f\ufe0f', label: '我的优惠券', route: '/pages/coupon/coupon' },
      { icon: '\ud83d\udc65', label: '拼单/请客', route: '/pages/social/social' },
      { icon: '\ud83d\udcc5', label: '我的预订', route: '/pages/reservation/reservation' },
      { icon: '\ud83c\udf9f\ufe0f', label: '排队取号', route: '/pages/queue/queue' },
      { icon: '\ud83c\udfe2', label: '企业团餐', route: '/pages/extra/corporate/corporate' },
      { icon: '\u2b50', label: '我的评价', route: '/pages/feedback/feedback' },
    ],
    // 积分明细
    showPointsLog: false,
    pointsLog: [],
    pointsPage: 1,
    // 余额明细
    showBalanceLog: false,
    balanceLog: [],
    balancePage: 1,
    // 优惠券面板
    showCouponPanel: false,
    couponTab: 'available',
    coupons: [],
    loadingCoupons: false,
    // 消费记录
    showConsumeLog: false,
    consumeRecords: [],
    loadingConsume: false,
    consumePage: 1,
    // 个人信息编辑
    showProfileEdit: false,
    editNickname: '',
    editPhone: '',
    editBirthday: '',
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

  // --- 数据加载 ---

  _loadProfile: function () {
    var self = this;
    return api.fetchMemberProfile()
      .then(function (data) {
        var level = data.level || 'normal';
        var config = self.data.levelConfig[level] || self.data.levelConfig.normal;
        self.setData({
          'profile.nickname': data.nickname || data.phone || '未设置昵称',
          'profile.avatarUrl': data.avatar_url || '',
          'profile.phone': data.phone || '',
          'profile.birthday': data.birthday || '',
          'profile.level': level,
          'profile.levelName': config.name,
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

  // --- 登录 ---

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

  // --- 导航 ---

  goToRoute: function (e) {
    var route = e.currentTarget.dataset.route;
    wx.navigateTo({ url: route });
  },

  // --- 积分明细 ---

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

  // --- 余额明细 ---

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

  // --- 优惠券面板 ---

  openCouponPanel: function () {
    this.setData({ showCouponPanel: true, couponTab: 'available', coupons: [] });
    this._loadCoupons('available');
  },

  closeCouponPanel: function () {
    this.setData({ showCouponPanel: false });
  },

  switchCouponTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ couponTab: tab, coupons: [] });
    this._loadCoupons(tab);
  },

  _loadCoupons: function (status) {
    var self = this;
    self.setData({ loadingCoupons: true });

    api.fetchCoupons(status)
      .then(function (data) {
        var items = (data.items || data || []).map(function (c) {
          return {
            id: c.id,
            name: c.name || c.coupon_name || '',
            description: c.description || '',
            discountText: c.discount_text || '',
            expireAt: (c.expire_at || '').slice(0, 10),
            status: c.status || status,
          };
        });
        self.setData({ coupons: items, loadingCoupons: false });
      })
      .catch(function (err) {
        console.warn('加载优惠券失败', err);
        self.setData({ loadingCoupons: false });
      });
  },

  // --- 消费记录 ---

  showConsumeHistory: function () {
    this.setData({ showConsumeLog: true, consumeRecords: [], consumePage: 1 });
    this._loadConsumeRecords();
  },

  closeConsumeLog: function () {
    this.setData({ showConsumeLog: false });
  },

  _loadConsumeRecords: function () {
    var self = this;
    self.setData({ loadingConsume: true });

    api.fetchMyOrders(self.data.consumePage, 20)
      .then(function (data) {
        var items = (data.items || []).map(function (o) {
          return {
            id: o.id || o.order_id,
            orderNo: o.order_no || '',
            totalYuan: ((o.total_amount_fen || 0) / 100).toFixed(2),
            itemCount: o.item_count || 0,
            firstDishName: o.first_dish_name || '',
            createdAt: (o.created_at || '').slice(0, 16).replace('T', ' '),
          };
        });
        self.setData({
          consumeRecords: self.data.consumeRecords.concat(items),
          loadingConsume: false,
        });
      })
      .catch(function (err) {
        console.warn('加载消费记录失败', err);
        self.setData({ loadingConsume: false });
      });
  },

  // --- 个人信息编辑 ---

  openProfileEdit: function () {
    this.setData({
      showProfileEdit: true,
      editNickname: this.data.profile.nickname,
      editPhone: this.data.profile.phone,
      editBirthday: this.data.profile.birthday,
    });
  },

  closeProfileEdit: function () {
    this.setData({ showProfileEdit: false });
  },

  onEditNickname: function (e) {
    this.setData({ editNickname: e.detail.value });
  },

  onEditPhone: function (e) {
    this.setData({ editPhone: e.detail.value });
  },

  onEditBirthday: function (e) {
    this.setData({ editBirthday: e.detail.value });
  },

  saveProfile: function () {
    var self = this;
    var customerId = wx.getStorageSync('tx_customer_id') || '';
    if (!customerId) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '保存中...' });
    api.txRequest('/api/v1/member/customers/' + encodeURIComponent(customerId), 'PUT', {
      nickname: self.data.editNickname,
      phone: self.data.editPhone,
      birthday: self.data.editBirthday,
    }).then(function () {
      wx.hideLoading();
      wx.showToast({ title: '保存成功', icon: 'success' });
      self.setData({ showProfileEdit: false });
      self._loadProfile();
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({ title: err.message || '保存失败', icon: 'none' });
    });
  },
});
