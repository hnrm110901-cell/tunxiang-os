var app = getApp();
var api = require('../../utils/api.js');

// Mock 数据：API 失败时降级使用
var MOCK_ORDERS = {
  active: [
    {
      id: 'mock-order-001',
      campaign_id: 'mock-campaign-001',
      name: '招牌酸菜鱼拼团特惠',
      image_url: '',
      group_price_fen: 6800,
      target_size: 5,
      current_size: 3,
      status: 'active',
      _is_mock: true
    },
    {
      id: 'mock-order-002',
      campaign_id: 'mock-campaign-002',
      name: '双人烤鱼套餐',
      image_url: '',
      group_price_fen: 12800,
      target_size: 3,
      current_size: 1,
      status: 'active',
      _is_mock: true
    }
  ],
  completed: [
    {
      id: 'mock-order-003',
      campaign_id: 'mock-campaign-003',
      name: '小龙虾3人拼团',
      image_url: '',
      group_price_fen: 8800,
      target_size: 3,
      current_size: 3,
      status: 'completed',
      _is_mock: true
    }
  ],
  cancelled: [
    {
      id: 'mock-order-004',
      campaign_id: 'mock-campaign-004',
      name: '火锅4人拼团',
      image_url: '',
      group_price_fen: 15800,
      target_size: 4,
      current_size: 1,
      status: 'cancelled',
      _is_mock: true
    }
  ]
};

Page({
  data: {
    currentTab: 'active',
    orders: [],
    loading: false,
    loadingMore: false,
    noMore: false,
    page: 1,
    pageSize: 10
  },

  onLoad: function () {
    this._loadOrders(true);
  },

  onShow: function () {
    // 页面显示时刷新
    this._loadOrders(true);
  },

  onPullDownRefresh: function () {
    var self = this;
    self._loadOrders(true, function () {
      wx.stopPullDownRefresh();
    });
  },

  onReachBottom: function () {
    if (this.data.loadingMore || this.data.noMore) return;
    this._loadMore();
  },

  onShareAppMessage: function (res) {
    var target = res.target;
    if (target && target.dataset && target.dataset.id) {
      return {
        title: '超值拼团，一起来拼',
        path: '/pages/group-buy-detail/group-buy-detail?id=' + target.dataset.id
      };
    }
    return {
      title: '超值拼团，人多更划算',
      path: '/pages/group-buy/index'
    };
  },

  // ─── 切换 Tab ───
  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    if (tab === this.data.currentTab) return;
    this.setData({ currentTab: tab, orders: [], page: 1, noMore: false });
    this._loadOrders(true);
  },

  // ─── 加载订单 ───
  _loadOrders: function (reset, callback) {
    var self = this;
    var page = reset ? 1 : self.data.page;
    var memberId = wx.getStorageSync('tx_customer_id') || '';

    self.setData({ loading: reset, loadingMore: !reset });

    api.txRequest(
      '/api/v1/group-buy/my-orders?member_id=' + encodeURIComponent(memberId) +
      '&status=' + encodeURIComponent(self.data.currentTab) +
      '&page=' + page +
      '&size=' + self.data.pageSize
    ).then(function (data) {
      var items = data.items || data || [];
      var total = data.total || items.length;
      var currentList = reset ? items : self.data.orders.concat(items);

      self.setData({
        orders: currentList,
        page: page + 1,
        loading: false,
        loadingMore: false,
        noMore: currentList.length >= total
      });
      if (typeof callback === 'function') callback();
    }).catch(function () {
      // API 降级 Mock
      var mockItems = MOCK_ORDERS[self.data.currentTab] || [];
      self.setData({
        orders: mockItems,
        loading: false,
        loadingMore: false,
        noMore: true
      });
      wx.showToast({ title: '已加载演示数据', icon: 'none' });
      if (typeof callback === 'function') callback();
    });
  },

  // ─── 加载更多 ───
  _loadMore: function () {
    this._loadOrders(false);
  },

  // ─── 跳转详情 ───
  goDetail: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: '/pages/group-buy-detail/group-buy-detail?id=' + id
    });
  },

  // ─── 再来一单 ───
  reorder: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: '/pages/group-buy-detail/group-buy-detail?id=' + id
    });
  },

  // ─── 重新参团 ───
  rejoin: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: '/pages/group-buy-detail/group-buy-detail?id=' + id
    });
  },

  // ─── 去看看 ───
  goGroupBuy: function () {
    wx.navigateTo({
      url: '/pages/group-buy/index'
    });
  }
});
