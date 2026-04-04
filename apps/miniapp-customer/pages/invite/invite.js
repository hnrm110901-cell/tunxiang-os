// 邀请有礼页
// API:
//   GET /api/v1/member/invite/my-code?member_id={id}  → 邀请码 + 邀请人数 + 奖励规则
// 降级 Mock：{ code: "TX8A3F9K", invited_count: 3, reward_rules: [...] }

var api = require('../../utils/api.js');

// 降级 Mock 数据
var MOCK_INVITE_DATA = {
  code: 'TX8A3F9K',
  invited_count: 3,
  reward_rules: [
    { id: '1', title: '邀请1位好友', desc: '好友完成首次消费后到账', points: 50 },
    { id: '2', title: '邀请5位好友', desc: '累计邀请5人，额外赠送积分', points: 300 },
    { id: '3', title: '邀请10位好友', desc: '达成邀请达人，解锁专属奖励', points: 800 },
    { id: '4', title: '被邀请好友', desc: '使用邀请码注册，立得积分', points: 50 },
  ],
};

// 下一个里程碑阈值
var MILESTONES = [1, 5, 10, 20, 50];

Page({
  data: {
    inviteCode: '',
    invitedCount: 0,
    rewardRules: [],
    nextMilestone: 0,
    storeName: '',
    loading: true,
  },

  onLoad: function () {
    var app = getApp();
    this.setData({
      storeName: (app.globalData && app.globalData.storeName) || '',
    });
    this._loadInviteData();
  },

  onShow: function () {
    // 每次进入刷新，确保邀请人数最新
    this._loadInviteData();
  },

  onShareAppMessage: function () {
    var code = this.data.inviteCode || 'TX8A3F9K';
    return {
      title: '来屯象点餐，用我的邀请码注册，双方各得积分！',
      path: '/pages/index/index?invite_code=' + code,
      imageUrl: '',   // 留空使用默认截图，或后续替换为实际海报 CDN 地址
    };
  },

  onShareTimeline: function () {
    var code = this.data.inviteCode || 'TX8A3F9K';
    return {
      title: '邀请你来屯象点餐，邀请码：' + code,
      query: 'invite_code=' + code,
    };
  },

  // ─── 加载邀请数据 ───

  _loadInviteData: function () {
    var self = this;
    var memberId = wx.getStorageSync('tx_customer_id') || '';

    self.setData({ loading: true });

    api.txRequest(
      '/api/v1/member/invite/my-code?member_id=' + encodeURIComponent(memberId)
    ).then(function (data) {
      self._applyInviteData(data);
    }).catch(function () {
      // 降级 Mock
      self._applyInviteData(MOCK_INVITE_DATA);
    });
  },

  _applyInviteData: function (data) {
    var invitedCount = data.invited_count || 0;
    var nextMilestone = this._calcNextMilestone(invitedCount);

    var rules = (data.reward_rules || []).map(function (r) {
      return {
        id: r.id || String(Math.random()),
        title: r.title || '',
        desc: r.desc || r.description || '',
        points: r.points || r.reward_points || 0,
      };
    });

    this.setData({
      inviteCode: data.code || data.invite_code || '',
      invitedCount: invitedCount,
      rewardRules: rules.length > 0 ? rules : MOCK_INVITE_DATA.reward_rules,
      nextMilestone: nextMilestone,
      loading: false,
    });
  },

  _calcNextMilestone: function (count) {
    for (var i = 0; i < MILESTONES.length; i++) {
      if (count < MILESTONES[i]) return MILESTONES[i] - count;
    }
    return 0;
  },

  // ─── 复制邀请码 ───

  copyCode: function () {
    var code = this.data.inviteCode;
    if (!code) {
      wx.showToast({ title: '邀请码加载中', icon: 'none' });
      return;
    }
    wx.setClipboardData({
      data: code,
      success: function () {
        wx.showToast({ title: '已复制邀请码', icon: 'success', duration: 1500 });
      },
      fail: function () {
        wx.showToast({ title: '复制失败，请手动长按复制', icon: 'none' });
      },
    });
  },

  // ─── 跳转邀请记录 ───

  goToRecords: function () {
    wx.navigateTo({ url: '/pages/invite-records/invite-records' });
  },
});
