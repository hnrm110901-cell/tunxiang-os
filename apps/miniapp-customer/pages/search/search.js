// 搜索页 — 搜索框(自动获焦) + 搜索历史 + 热门搜索 + 结果(菜品/门店Tab)
// 500ms防抖 + 本地存储历史(最多10条)

var app = getApp();
var api = require('../../utils/api.js');

var STORAGE_KEY = 'tx_search_history';

var MOCK_HOT_WORDS = [
  '剁椒鱼头', '小炒黄牛肉', '口味虾', '臭豆腐',
  '糖油粑粑', '农家小炒肉', '外卖', '套餐',
  '团购', '预约'
];

Page({
  data: {
    keyword: '',
    hasSearched: false,
    searching: false,
    resultTab: 'dish',

    // 搜索历史
    historyList: [],

    // 热门搜索
    hotWords: MOCK_HOT_WORDS,

    // 搜索结果
    dishResults: [],
    storeResults: [],
  },

  // 防抖定时器
  _debounceTimer: null,

  onLoad: function () {
    this._loadHistory();
    this._loadHotWords();
  },

  onUnload: function () {
    if (this._debounceTimer) {
      clearTimeout(this._debounceTimer);
      this._debounceTimer = null;
    }
  },

  // ─── 输入事件 (500ms防抖) ───

  onInput: function (e) {
    var self = this;
    var val = e.detail.value || '';
    self.setData({ keyword: val });

    if (self._debounceTimer) {
      clearTimeout(self._debounceTimer);
    }

    if (!val.trim()) {
      self.setData({ hasSearched: false, dishResults: [], storeResults: [] });
      return;
    }

    self._debounceTimer = setTimeout(function () {
      self.doSearch();
    }, 500);
  },

  doSearch: function () {
    var self = this;
    var kw = self.data.keyword.trim();
    if (!kw) return;

    self._saveHistory(kw);
    self.setData({ hasSearched: true, searching: true });

    var storeId = app.globalData.storeId || '';

    // 并行搜索菜品和门店
    var dishPromise = api.txRequest('/api/v1/customer/search/dishes?q=' + encodeURIComponent(kw) + '&store_id=' + encodeURIComponent(storeId))
      .then(function (data) {
        return (data.items || data || []).map(function (d) {
          return {
            id: d.id || '',
            name: d.name || '',
            imageUrl: d.image_url || d.imageUrl || '',
            priceYuan: d.price_fen ? (d.price_fen / 100).toFixed(0) + '元' : (d.price || ''),
            storeName: d.store_name || '',
          };
        });
      })
      .catch(function () { return []; });

    var storePromise = api.txRequest('/api/v1/customer/search/stores?q=' + encodeURIComponent(kw))
      .then(function (data) {
        return (data.items || data || []).map(function (s) {
          return {
            id: s.id || '',
            name: s.name || '',
            address: s.address || '',
            distance: s.distance ? (s.distance < 1000 ? s.distance + 'm' : (s.distance / 1000).toFixed(1) + 'km') : '',
            rating: s.rating || '',
          };
        });
      })
      .catch(function () { return []; });

    Promise.all([dishPromise, storePromise]).then(function (results) {
      self.setData({
        dishResults: results[0],
        storeResults: results[1],
        searching: false,
      });
    });
  },

  // ─── Tab切换 ───

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ resultTab: tab });
  },

  // ─── 搜索历史 ───

  _loadHistory: function () {
    var list = [];
    try {
      list = JSON.parse(wx.getStorageSync(STORAGE_KEY) || '[]');
    } catch (e) {
      list = [];
    }
    this.setData({ historyList: list });
  },

  _saveHistory: function (word) {
    var list = this.data.historyList.slice();
    // 去重
    var idx = list.indexOf(word);
    if (idx >= 0) {
      list.splice(idx, 1);
    }
    list.unshift(word);
    // 最多10条
    if (list.length > 10) {
      list = list.slice(0, 10);
    }
    this.setData({ historyList: list });
    wx.setStorageSync(STORAGE_KEY, JSON.stringify(list));
  },

  clearHistory: function () {
    this.setData({ historyList: [] });
    wx.removeStorageSync(STORAGE_KEY);
  },

  // ─── 热门搜索 ───

  _loadHotWords: function () {
    var self = this;
    api.txRequest('/api/v1/customer/search/hot-words')
      .then(function (data) {
        var words = data.items || data || [];
        if (words.length > 0) {
          self.setData({ hotWords: words.slice(0, 10) });
        }
      })
      .catch(function () {
        // 降级用 Mock
      });
  },

  // ─── 标签点击 ───

  onTagTap: function (e) {
    var word = e.currentTarget.dataset.word;
    this.setData({ keyword: word });
    this.doSearch();
  },

  // ─── 清除关键词 ───

  clearKeyword: function () {
    this.setData({ keyword: '', hasSearched: false, dishResults: [], storeResults: [] });
  },

  // ─── 导航 ───

  goBack: function () {
    wx.navigateBack();
  },

  goToDish: function (e) {
    var dishId = e.currentTarget.dataset.id;
    if (dishId) {
      wx.navigateTo({
        url: '/pages/dish-detail/dish-detail?id=' + dishId,
      });
    }
  },

  goToStore: function (e) {
    var storeId = e.currentTarget.dataset.id;
    if (storeId) {
      app.globalData.storeId = storeId;
      wx.switchTab({ url: '/pages/menu/menu' });
    }
  },
});
