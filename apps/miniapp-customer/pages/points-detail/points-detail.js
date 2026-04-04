// 积分明细 — 按月分组展示
var api = require('../../utils/api.js');

// Mock积分明细
var MOCK_HISTORY = [
  { id: 'h1', description: '消费获得积分', points: 58, created_at: '2026-03-30T14:20:00' },
  { id: 'h2', description: '兑换满50减10券', points: -200, created_at: '2026-03-28T14:30:00' },
  { id: 'h3', description: '签到奖励', points: 10, created_at: '2026-03-28T08:00:00' },
  { id: 'h4', description: '消费获得积分', points: 126, created_at: '2026-03-25T19:10:00' },
  { id: 'h5', description: '兑换9折券', points: -300, created_at: '2026-03-25T10:15:00' },
  { id: 'h6', description: '邀请好友奖励', points: 200, created_at: '2026-03-22T16:00:00' },
  { id: 'h7', description: '消费获得积分', points: 89, created_at: '2026-03-20T12:30:00' },
  { id: 'h8', description: '生日礼赠积分', points: 500, created_at: '2026-03-15T00:00:00' },
  { id: 'h9', description: '消费获得积分', points: 45, created_at: '2026-02-28T20:00:00' },
  { id: 'h10', description: '兑换免配送费券', points: -150, created_at: '2026-02-20T09:00:00' },
  { id: 'h11', description: '消费获得积分', points: 220, created_at: '2026-02-14T18:30:00' },
  { id: 'h12', description: '签到奖励', points: 10, created_at: '2026-02-10T08:00:00' },
];

Page({
  data: {
    pointsBalance: 0,
    groups: [],        // [{ month: '2026年03月', totalEarn: x, totalSpend: x, items: [...] }]
    rawHistory: [],    // 原始平铺列表
    loading: false,
    page: 1,
    hasMore: false,
  },

  onLoad: function () {
    this._loadBalance();
    this._loadHistory(1);
  },

  onPullDownRefresh: function () {
    var self = this;
    self.setData({ page: 1, rawHistory: [], groups: [] });
    Promise.all([self._loadBalance(), self._loadHistory(1)])
      .then(function () { wx.stopPullDownRefresh(); })
      .catch(function () { wx.stopPullDownRefresh(); });
  },

  onReachBottom: function () {
    if (this.data.hasMore && !this.data.loading) {
      var nextPage = this.data.page + 1;
      this.setData({ page: nextPage });
      this._loadHistory(nextPage);
    }
  },

  // ─── 数据加载 ───

  _loadBalance: function () {
    var self = this;
    return api.fetchMemberProfile()
      .then(function (data) {
        self.setData({ pointsBalance: data.points_balance || 0 });
      })
      .catch(function () {
        self.setData({ pointsBalance: 2580 });
      });
  },

  _loadHistory: function (page) {
    var self = this;
    self.setData({ loading: true });

    return api.fetchPointsLog(page)
      .then(function (data) {
        var items = (data.items || []).map(function (p) {
          return {
            id: p.id,
            description: p.description || p.remark || '',
            points: p.points || p.change || 0,
            created_at: p.created_at || '',
          };
        });
        if (items.length === 0 && page === 1) {
          items = MOCK_HISTORY;
        }
        var merged = page > 1 ? self.data.rawHistory.concat(items) : items;
        self.setData({
          rawHistory: merged,
          hasMore: items.length >= 20,
          loading: false,
        });
        self._groupByMonth(merged);
      })
      .catch(function () {
        // 降级Mock
        self.setData({
          rawHistory: MOCK_HISTORY,
          hasMore: false,
          loading: false,
        });
        self._groupByMonth(MOCK_HISTORY);
      });
  },

  // ─── 按月分组 ───

  _groupByMonth: function (items) {
    var monthMap = {};
    var monthOrder = [];

    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var dt = item.created_at || '';
      // 提取年月
      var yearMonth = dt.slice(0, 7); // "2026-03"
      if (!yearMonth) continue;

      var parts = yearMonth.split('-');
      var label = parts[0] + '年' + parts[1] + '月';

      if (!monthMap[label]) {
        monthMap[label] = { month: label, totalEarn: 0, totalSpend: 0, items: [] };
        monthOrder.push(label);
      }

      var pts = item.points || 0;
      if (pts > 0) {
        monthMap[label].totalEarn += pts;
      } else {
        monthMap[label].totalSpend += Math.abs(pts);
      }

      monthMap[label].items.push({
        id: item.id,
        description: item.description,
        points: pts,
        time: dt.slice(5, 16).replace('T', ' '),  // "03-30 14:20"
      });
    }

    var groups = [];
    for (var j = 0; j < monthOrder.length; j++) {
      groups.push(monthMap[monthOrder[j]]);
    }

    this.setData({ groups: groups });
  },
});
