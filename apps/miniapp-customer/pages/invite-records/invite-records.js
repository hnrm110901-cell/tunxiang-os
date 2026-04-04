// 我的邀请记录页
// API:
//   GET /api/v1/member/invite/records?member_id={id}&page=1&size=20
//     → { summary: { invited_count, earned_points, pending_points }, items: [...], total: int }
// 功能：下拉刷新 + 上拉加载更多

var api = require('../../utils/api.js');

// 降级 Mock 数据
var MOCK_SUMMARY = {
  invited_count: 3,
  earned_points: 150,
  pending_points: 50,
};

var MOCK_RECORDS = [
  {
    id: 'mock-1',
    nickname: '王小明',
    register_time: '2026-03-25 14:32',
    reward_points: 50,
    status: 'credited',
  },
  {
    id: 'mock-2',
    nickname: '李小花',
    register_time: '2026-03-27 09:15',
    reward_points: 50,
    status: 'credited',
  },
  {
    id: 'mock-3',
    nickname: '张小红',
    register_time: '2026-03-30 19:48',
    reward_points: 50,
    status: 'pending',
  },
];

Page({
  data: {
    summary: {
      invited_count: 0,
      earned_points: 0,
      pending_points: 0,
    },
    records: [],
    page: 1,
    hasMore: false,
    loading: true,
    loadingMore: false,
  },

  onLoad: function () {
    this._loadRecords(1, true);
  },

  onPullDownRefresh: function () {
    var self = this;
    self.setData({ page: 1, records: [], hasMore: false });
    self._loadRecords(1, true).then(function () {
      wx.stopPullDownRefresh();
    }).catch(function () {
      wx.stopPullDownRefresh();
    });
  },

  onReachBottom: function () {
    if (this.data.hasMore && !this.data.loadingMore) {
      var nextPage = this.data.page + 1;
      this.setData({ page: nextPage, loadingMore: true });
      this._loadRecords(nextPage, false);
    }
  },

  onShareAppMessage: function () {
    return {
      title: '我的邀请记录 — 屯象点餐',
      path: '/pages/invite/invite',
    };
  },

  // ─── 加载记录 ───

  _loadRecords: function (page, isRefresh) {
    var self = this;
    var memberId = wx.getStorageSync('tx_customer_id') || '';

    if (isRefresh) {
      self.setData({ loading: true });
    }

    return api.txRequest(
      '/api/v1/member/invite/records?member_id=' + encodeURIComponent(memberId) +
      '&page=' + (page || 1) + '&size=20'
    ).then(function (data) {
      self._applyRecords(data, page, isRefresh);
    }).catch(function () {
      // 降级 Mock（仅首页展示 mock）
      if (page === 1) {
        self._applyMock();
      } else {
        self.setData({ loadingMore: false, hasMore: false });
      }
    });
  },

  _applyRecords: function (data, page, isRefresh) {
    var items = (data.items || []).map(function (r) {
      return {
        id: r.id || r.record_id || String(Math.random()),
        nickname: r.nickname || r.invitee_name || '好友',
        register_time: (r.register_time || r.created_at || '').slice(0, 16).replace('T', ' '),
        reward_points: r.reward_points || 50,
        status: r.status || 'pending',
      };
    });

    var merged = isRefresh ? items : this.data.records.concat(items);

    var summary = data.summary || {};
    var updates = {
      records: merged,
      hasMore: items.length >= 20,
      loading: false,
      loadingMore: false,
    };

    if (isRefresh || page === 1) {
      updates.summary = {
        invited_count: summary.invited_count || 0,
        earned_points: summary.earned_points || 0,
        pending_points: summary.pending_points || 0,
      };
    }

    this.setData(updates);
  },

  _applyMock: function () {
    this.setData({
      summary: MOCK_SUMMARY,
      records: MOCK_RECORDS,
      hasMore: false,
      loading: false,
      loadingMore: false,
    });
  },

  // ─── 手动加载更多 ───

  loadMore: function () {
    if (this.data.hasMore && !this.data.loadingMore) {
      var nextPage = this.data.page + 1;
      this.setData({ page: nextPage, loadingMore: true });
      this._loadRecords(nextPage, false);
    }
  },

  // ─── 跳转邀请页 ───

  goToInvite: function () {
    wx.navigateBack({
      delta: 1,
      fail: function () {
        wx.switchTab({ url: '/pages/member/member' });
      },
    });
  },
});
