// 积分中心 — 兑换商城 + 积分明细
// API:
//   GET  /api/v1/member/profile?customer_id=      会员信息（含积分）
//   GET  /api/v1/member/points/history?customer_id= 积分流水
//   GET  /api/v1/member/rewards                   兑换商品列表
//   POST /api/v1/member/rewards/redeem            积分兑换

var api = require('../../utils/api.js');

// Mock兑换商品（API失败时降级展示）
var MOCK_REWARDS = [
  {
    id: 'mock-1',
    name: '感谢券',
    pointsCost: 100,
    imageUrl: '',
    description: '专属感谢礼遇',
  },
  {
    id: 'mock-2',
    name: '优先排队',
    pointsCost: 200,
    imageUrl: '',
    description: '享受优先叫号特权',
  },
  {
    id: 'mock-3',
    name: '免配送费券',
    pointsCost: 150,
    imageUrl: '',
    description: '外卖免配送费一次',
  },
  {
    id: 'mock-4',
    name: '9折优惠券',
    pointsCost: 300,
    imageUrl: '',
    description: '全场菜品9折使用',
  },
];

Page({
  data: {
    // 积分数据
    pointsBalance: 0,
    monthEarned: 0,
    monthUsed: 0,

    // Tab
    activeTab: 'redeem',

    // 兑换商城
    rewards: [],
    rewardLoading: false,

    // 积分明细
    history: [],
    historyLoading: false,
    historyPage: 1,
    historyHasMore: false,

    // 兑换确认弹层
    showConfirm: false,
    confirmItem: {},
  },

  onLoad: function () {
    this._loadProfile();
    this._loadRewards();
  },

  onShow: function () {
    this._loadProfile();
  },

  onPullDownRefresh: function () {
    var self = this;
    var promises = [self._loadProfile(), self._loadRewards()];
    if (self.data.activeTab === 'history') {
      self.setData({ history: [], historyPage: 1 });
      promises.push(self._loadHistory(1));
    }
    Promise.all(promises)
      .then(function () { wx.stopPullDownRefresh(); })
      .catch(function () { wx.stopPullDownRefresh(); });
  },

  onReachBottom: function () {
    if (this.data.activeTab === 'history' && this.data.historyHasMore) {
      var nextPage = this.data.historyPage + 1;
      this.setData({ historyPage: nextPage });
      this._loadHistory(nextPage);
    }
  },

  onShareAppMessage: function () {
    return { title: '积分中心 — 屯象点餐', path: '/pages/points/points' };
  },

  // ─── Tab切换 ───

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    this.setData({ activeTab: tab });
    if (tab === 'history' && this.data.history.length === 0) {
      this.setData({ historyPage: 1 });
      this._loadHistory(1);
    }
  },

  // ─── 加载会员信息（积分余额 + 本月统计）───

  _loadProfile: function () {
    var self = this;
    var customerId = wx.getStorageSync('tx_customer_id') || '';
    return api.txRequest(
      '/api/v1/member/profile?customer_id=' + encodeURIComponent(customerId)
    ).then(function (data) {
      self.setData({
        pointsBalance: data.points_balance || 0,
        monthEarned: data.month_earned || 0,
        monthUsed: data.month_used || 0,
      });
    }).catch(function () {
      // 降级：从本地已有的 memberProfile 接口读取
      return api.fetchMemberProfile()
        .then(function (data) {
          self.setData({ pointsBalance: data.points_balance || 0 });
        })
        .catch(function () {});
    });
  },

  // ─── 加载兑换商品 ───

  _loadRewards: function () {
    var self = this;
    self.setData({ rewardLoading: true });
    return api.txRequest('/api/v1/member/rewards')
      .then(function (data) {
        var items = (data.items || data || []).map(function (r) {
          return {
            id: r.reward_id || r.id,
            name: r.name,
            pointsCost: r.points_cost || r.pointsCost || 0,
            imageUrl: r.image_url || r.imageUrl || '',
            description: r.description || '',
          };
        });
        self.setData({ rewards: items.length > 0 ? items : MOCK_REWARDS, rewardLoading: false });
      })
      .catch(function () {
        self.setData({ rewards: MOCK_REWARDS, rewardLoading: false });
      });
  },

  // ─── 加载积分明细 ───

  _loadHistory: function (page) {
    var self = this;
    var customerId = wx.getStorageSync('tx_customer_id') || '';
    self.setData({ historyLoading: true });
    return api.txRequest(
      '/api/v1/member/points/history?customer_id=' + encodeURIComponent(customerId) + '&page=' + (page || 1)
    ).then(function (data) {
      var items = (data.items || []).map(function (p) {
        return {
          id: p.id,
          description: p.description || p.remark || '',
          points: p.points || p.change || 0,
          createdAt: (p.created_at || '').slice(0, 16).replace('T', ' '),
        };
      });
      var merged = page > 1 ? self.data.history.concat(items) : items;
      self.setData({
        history: merged,
        historyHasMore: items.length >= 20,
        historyLoading: false,
      });
    }).catch(function () {
      // 降级：使用旧的 fetchPointsLog 接口
      return api.fetchPointsLog(page || 1)
        .then(function (data) {
          var items = (data.items || []).map(function (p) {
            return {
              id: p.id,
              description: p.description || '',
              points: p.points || 0,
              createdAt: (p.created_at || '').slice(0, 16).replace('T', ' '),
            };
          });
          var merged = page > 1 ? self.data.history.concat(items) : items;
          self.setData({
            history: merged,
            historyHasMore: items.length >= 20,
            historyLoading: false,
          });
        })
        .catch(function () {
          self.setData({ historyLoading: false });
        });
    });
  },

  // ─── 兑换流程 ───

  onTapRedeem: function (e) {
    var item = e.currentTarget.dataset.item;
    if (!item) return;
    if (this.data.pointsBalance < item.pointsCost) {
      wx.showToast({ title: '积分不足，无法兑换', icon: 'none' });
      return;
    }
    this.setData({ showConfirm: true, confirmItem: item });
  },

  closeConfirm: function () {
    this.setData({ showConfirm: false });
  },

  doRedeem: function () {
    var self = this;
    var item = self.data.confirmItem;
    if (!item || !item.id) return;

    var customerId = wx.getStorageSync('tx_customer_id') || '';

    wx.showLoading({ title: '兑换中...' });
    api.txRequest('/api/v1/member/rewards/redeem', 'POST', {
      reward_id: item.id,
      customer_id: customerId,
    }).then(function () {
      wx.hideLoading();
      wx.showToast({ title: '兑换成功！', icon: 'success' });
      self.setData({ showConfirm: false });
      // 刷新积分余额
      self._loadProfile();
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({
        title: (err && err.message) || '兑换失败，请稍后重试',
        icon: 'none',
      });
    });
  },
});
