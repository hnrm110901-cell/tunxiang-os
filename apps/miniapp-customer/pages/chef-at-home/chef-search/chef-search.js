// 大厨搜索页 — 历史记录 + 实时搜索（防抖500ms）
// API: GET /api/v1/trade/chef-at-home/chefs?q=xxx&page=1
var api = require('../../../utils/api.js');

var HISTORY_KEY = 'chef_search_history';
var MAX_HISTORY = 10;

var MOCK_CHEFS = [
  { id: 'chef001', name: '李大厨', specialty: '湘菜', rating: 4.9, orders: 328, price_fen: 28800, badges: ['米其林学徒', '10年经验'], avatar: '' },
  { id: 'chef002', name: '王海涛', specialty: '海鲜', rating: 4.8, orders: 256, price_fen: 35800, badges: ['海鲜专家'], avatar: '' },
  { id: 'chef003', name: '张小燕', specialty: '粤菜', rating: 4.7, orders: 189, price_fen: 24800, badges: ['甜品达人'], avatar: '' },
  { id: 'chef004', name: '陈国华', specialty: '川菜', rating: 4.9, orders: 412, price_fen: 26800, badges: ['辣菜宗师', '5年经验'], avatar: '' },
  { id: 'chef005', name: '刘芳', specialty: '西餐', rating: 4.6, orders: 98, price_fen: 48800, badges: ['法餐学员'], avatar: '' },
  { id: 'chef006', name: '赵明', specialty: '烧烤', rating: 4.8, orders: 203, price_fen: 19800, badges: ['炭火大师'], avatar: '' },
];

function normalizeChef(chef) {
  return {
    id: chef.id || '',
    name: chef.name || '',
    specialty: chef.specialty || chef.cuisine_type || '',
    rating: chef.rating || 0,
    orders: chef.orders || chef.total_services || 0,
    price_fen: chef.price_fen || chef.base_fee_fen || 0,
    priceYuan: Math.round((chef.price_fen || chef.base_fee_fen || 0) / 100),
    badges: chef.badges || chef.honors || [],
    avatar: chef.avatar || '',
  };
}

function mockSearch(keyword) {
  if (!keyword) return [];
  var kw = keyword.toLowerCase();
  return MOCK_CHEFS.filter(function (c) {
    return c.name.indexOf(keyword) >= 0 ||
      c.specialty.indexOf(keyword) >= 0 ||
      (c.badges && c.badges.some(function (b) { return b.indexOf(keyword) >= 0; }));
  }).map(normalizeChef);
}

Page({
  data: {
    keyword: '',
    autoFocus: true,
    searching: false,
    hasSearched: false,
    results: [],
    history: [],
  },

  // 防抖定时器
  _debounceTimer: null,

  onLoad: function () {
    this._loadHistory();
  },

  // ─── 历史记录 ───

  _loadHistory: function () {
    try {
      var h = wx.getStorageSync(HISTORY_KEY);
      this.setData({ history: Array.isArray(h) ? h : [] });
    } catch (e) {
      this.setData({ history: [] });
    }
  },

  _saveHistory: function (keyword) {
    if (!keyword || !keyword.trim()) return;
    var kw = keyword.trim();
    try {
      var h = this.data.history.filter(function (item) { return item !== kw; });
      h.unshift(kw);
      if (h.length > MAX_HISTORY) h = h.slice(0, MAX_HISTORY);
      wx.setStorageSync(HISTORY_KEY, h);
      this.setData({ history: h });
    } catch (e) { /* ignore */ }
  },

  clearHistory: function () {
    wx.removeStorageSync(HISTORY_KEY);
    this.setData({ history: [] });
  },

  searchFromHistory: function (e) {
    var keyword = e.currentTarget.dataset.keyword;
    this.setData({ keyword: keyword });
    this.doSearch();
  },

  // ─── 输入防抖搜索 ───

  onInput: function (e) {
    var keyword = e.detail.value;
    this.setData({ keyword: keyword });

    if (this._debounceTimer) {
      clearTimeout(this._debounceTimer);
    }

    if (!keyword || !keyword.trim()) {
      this.setData({ hasSearched: false, results: [], searching: false });
      return;
    }

    var self = this;
    this._debounceTimer = setTimeout(function () {
      self._search(keyword.trim());
    }, 500);
  },

  // ─── 确认搜索（键盘 search 键） ───

  doSearch: function () {
    var kw = this.data.keyword.trim();
    if (!kw) return;
    if (this._debounceTimer) {
      clearTimeout(this._debounceTimer);
    }
    this._search(kw);
  },

  // ─── 执行搜索 ───

  _search: function (keyword) {
    var self = this;
    self.setData({ searching: true, hasSearched: false });

    api.txRequest('/api/v1/trade/chef-at-home/chefs?q=' + encodeURIComponent(keyword) + '&page=1&size=20')
      .then(function (data) {
        var items = Array.isArray(data) ? data : (data && data.items ? data.items : []);
        var normalized = items.map(normalizeChef);
        self.setData({ searching: false, hasSearched: true, results: normalized });
        self._saveHistory(keyword);
      })
      .catch(function (err) {
        console.warn('[chef-search] search failed, using mock', err);
        var results = mockSearch(keyword);
        self.setData({ searching: false, hasSearched: true, results: results });
        self._saveHistory(keyword);
      });
  },

  // ─── 清除关键词 ───

  clearKeyword: function () {
    if (this._debounceTimer) {
      clearTimeout(this._debounceTimer);
    }
    this.setData({ keyword: '', hasSearched: false, results: [], searching: false });
  },

  // ─── 跳转厨师详情 ───

  goDetail: function (e) {
    var id = e.currentTarget.dataset.id;
    if (!id) return;
    wx.navigateTo({
      url: '/pages/chef-at-home/chef-detail/chef-detail?chef_id=' + encodeURIComponent(id),
    });
  },

  // ─── 返回 ───

  goBack: function () {
    wx.navigateBack({ delta: 1 });
  },
});
