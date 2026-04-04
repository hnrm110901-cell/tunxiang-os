// 储值明细页
// API:
//   GET /api/v1/member/stored-value/transactions/{card_id}?type=&page=&size=

var api = require('../../utils/api.js');

// Mock 数据（API 失败时降级）
var MOCK_RECORDS = [
  { id: '1', type: 'recharge', description: '充值 ¥300 送 ¥30', amount_fen: 30000, created_at: '2026-03-28T10:30:00Z' },
  { id: '2', type: 'consume', description: '门店消费 - 订单#20260328001', amount_fen: -8800, created_at: '2026-03-28T12:15:00Z' },
  { id: '3', type: 'bonus', description: '充值赠送到账', amount_fen: 3000, created_at: '2026-03-28T10:30:00Z' },
  { id: '4', type: 'recharge', description: '充值 ¥500 送 ¥60', amount_fen: 50000, created_at: '2026-03-25T09:00:00Z' },
  { id: '5', type: 'consume', description: '门店消费 - 订单#20260325002', amount_fen: -15600, created_at: '2026-03-25T13:20:00Z' },
];

Page({
  data: {
    balanceYuan: '0.00',
    activeTab: 'all',
    records: [],
    page: 1,
    pageSize: 20,
    loading: false,
    noMore: false,
  },

  onLoad: function () {
    this.loadBalance();
    this.loadRecords(true);
  },

  onPullDownRefresh: function () {
    this.loadRecords(true);
  },

  onReachBottom: function () {
    if (!this.data.noMore && !this.data.loading) {
      this.loadRecords(false);
    }
  },

  // ---------- 数据加载 ----------

  loadBalance: function () {
    var that = this;
    var memberId = wx.getStorageSync('tx_customer_id') || '';
    api.txRequest('/api/v1/member/stored-value/balance/' + memberId).then(function (data) {
      that.setData({ balanceYuan: (data.balance_fen / 100).toFixed(2) });
    }).catch(function () {
      var profile = wx.getStorageSync('tx_member_profile') || {};
      that.setData({ balanceYuan: profile.balanceYuan || '0.00' });
    });
  },

  loadRecords: function (refresh) {
    var that = this;
    if (that.data.loading) return;

    var page = refresh ? 1 : that.data.page;
    that.setData({ loading: true });

    var memberId = wx.getStorageSync('tx_customer_id') || '';
    var tab = that.data.activeTab;
    var typeParam = tab === 'all' ? '' : tab;

    api.txRequest('/api/v1/member/stored-value/transactions/' + memberId + '?type=' + typeParam + '&page=' + page + '&size=' + that.data.pageSize).then(function (data) {
      var items = (data.items || []).map(function (item) {
        return that.formatRecord(item);
      });
      that.applyRecords(items, data.total || 0, refresh, page);
    }).catch(function () {
      // 降级 Mock
      var items = MOCK_RECORDS.filter(function (r) {
        return tab === 'all' || r.type === tab;
      }).map(function (item) {
        return that.formatRecord(item);
      });
      that.applyRecords(items, items.length, true, 1);
    });
  },

  applyRecords: function (items, total, refresh, page) {
    var that = this;
    var list = refresh ? items : that.data.records.concat(items);
    that.setData({
      records: list,
      page: page + 1,
      loading: false,
      noMore: list.length >= total || items.length === 0,
    });
    if (refresh) wx.stopPullDownRefresh();
  },

  formatRecord: function (item) {
    var fen = item.amount_fen || 0;
    var isPositive = fen >= 0;
    var yuan = (Math.abs(fen) / 100).toFixed(2);
    var timeStr = '';
    if (item.created_at) {
      var d = new Date(item.created_at);
      timeStr = d.getFullYear() + '-' +
        ('0' + (d.getMonth() + 1)).slice(-2) + '-' +
        ('0' + d.getDate()).slice(-2) + ' ' +
        ('0' + d.getHours()).slice(-2) + ':' +
        ('0' + d.getMinutes()).slice(-2);
    }
    return {
      id: item.id,
      type: item.type || 'recharge',
      description: item.description || item.remark || '储值交易',
      amountYuan: yuan,
      amountPrefix: isPositive ? '+' : '-',
      amountClass: isPositive ? 'amount-positive' : 'amount-negative',
      timeStr: timeStr,
    };
  },

  // ---------- Tab 切换 ----------

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    this.setData({ activeTab: tab, records: [], page: 1, noMore: false });
    this.loadRecords(true);
  },
});
