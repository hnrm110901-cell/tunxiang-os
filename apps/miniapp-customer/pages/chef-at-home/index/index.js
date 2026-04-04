// 大厨到家首页 — Banner + 菜系筛选 + 主厨推荐 + 全部厨师（分页）
// API: GET /api/v1/trade/chef-at-home/chefs?cuisine=&page=
var api = require('../../../utils/api.js');

var MOCK_CHEFS = [
  { id: 'chef001', name: '李大厨', specialty: '湘菜', rating: 4.9, orders: 328, price_fen: 28800, badges: ['米其林学徒', '10年经验'], avatar: '', featured: true },
  { id: 'chef002', name: '王海涛', specialty: '海鲜', rating: 4.8, orders: 256, price_fen: 35800, badges: ['海鲜专家'], avatar: '', featured: true },
  { id: 'chef003', name: '张小燕', specialty: '粤菜', rating: 4.7, orders: 189, price_fen: 24800, badges: ['甜品达人'], avatar: '', featured: false },
  { id: 'chef004', name: '陈国华', specialty: '川菜', rating: 4.9, orders: 412, price_fen: 26800, badges: ['辣菜宗师', '5年经验'], avatar: '', featured: true },
  { id: 'chef005', name: '刘芳', specialty: '西餐', rating: 4.6, orders: 98, price_fen: 48800, badges: ['法餐学员'], avatar: '', featured: false },
  { id: 'chef006', name: '赵明', specialty: '烧烤', rating: 4.8, orders: 203, price_fen: 19800, badges: ['炭火大师'], avatar: '', featured: false },
];

var BANNERS = [
  { id: 'b1', title: '新春特惠·首单5折', subtitle: '限时活动，先到先得', bg: 'linear-gradient(135deg, #FF6B35 0%, #FF8C60 100%)' },
  { id: 'b2', title: '米其林大厨·到家烹制', subtitle: '专业厨师，让家宴更精彩', bg: 'linear-gradient(135deg, #1E2A3A 0%, #2C3E50 100%)' },
  { id: 'b3', title: '节庆宴席·定制方案', subtitle: '婚寿宴/团圆饭，一键预约', bg: 'linear-gradient(135deg, #0F6E56 0%, #1A9B7A 100%)' },
];

var CUISINES = ['全部', '湘菜', '粤菜', '川菜', '海鲜', '西餐', '烧烤', '甜品'];

// 将后端数据字段归一化（统一 priceYuan 字段用于模板展示）
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
    featured: !!chef.featured,
  };
}

Page({
  data: {
    banners: BANNERS,
    cuisines: CUISINES,
    activeCuisine: '全部',

    // 主厨推荐（横向）
    featuredChefs: [],

    // 全部厨师（分页）
    chefs: [],
    loadingChefs: false,
    loadingMore: false,
    noMore: false,
    currentPage: 1,
    pageSize: 10,
  },

  onLoad: function () {
    this._loadFeatured();
    this._loadChefs(true);
  },

  onShow: function () {
    // 从预约/详情返回时刷新
  },

  onShareAppMessage: function () {
    return {
      title: '大厨到家 — 专业大厨上门烹制',
      path: '/pages/chef-at-home/index/index',
    };
  },

  onShareTimeline: function () {
    return { title: '大厨到家 — 专业大厨上门烹制' };
  },

  // ─── 加载主厨推荐 ───

  _loadFeatured: function () {
    var self = this;
    api.txRequest('/api/v1/trade/chef-at-home/chefs?featured=true&page=1&size=5')
      .then(function (data) {
        var list = Array.isArray(data) ? data : (data && data.items ? data.items : []);
        var featured = list.filter(function (c) { return c.featured; }).map(normalizeChef);
        if (featured.length === 0) {
          // 后端可能不区分 featured，直接取前几条
          featured = list.slice(0, 3).map(normalizeChef);
        }
        self.setData({ featuredChefs: featured });
      })
      .catch(function (err) {
        console.warn('[index] loadFeatured failed, using mock', err);
        var featured = MOCK_CHEFS.filter(function (c) { return c.featured; }).map(normalizeChef);
        self.setData({ featuredChefs: featured });
      });
  },

  // ─── 加载厨师列表（支持分页） ───

  _loadChefs: function (reset) {
    var self = this;
    var cuisine = self.data.activeCuisine;
    var page = reset ? 1 : self.data.currentPage;
    var size = self.data.pageSize;

    if (reset) {
      self.setData({ loadingChefs: true, noMore: false, currentPage: 1 });
    } else {
      self.setData({ loadingMore: true });
    }

    var cuisineParam = cuisine === '全部' ? '' : cuisine;
    var url = '/api/v1/trade/chef-at-home/chefs?page=' + page + '&size=' + size;
    if (cuisineParam) {
      url += '&cuisine=' + encodeURIComponent(cuisineParam);
    }

    api.txRequest(url)
      .then(function (data) {
        var items = Array.isArray(data) ? data : (data && data.items ? data.items : []);
        var normalized = items.map(normalizeChef);
        var noMore = normalized.length < size;

        if (reset) {
          self.setData({
            chefs: normalized,
            loadingChefs: false,
            loadingMore: false,
            noMore: noMore,
            currentPage: 2,
          });
        } else {
          self.setData({
            chefs: self.data.chefs.concat(normalized),
            loadingMore: false,
            noMore: noMore,
            currentPage: page + 1,
          });
        }
      })
      .catch(function (err) {
        console.warn('[index] loadChefs failed, using mock', err);
        // 降级到 Mock 数据
        var cuisine = self.data.activeCuisine;
        var filtered = cuisine === '全部'
          ? MOCK_CHEFS
          : MOCK_CHEFS.filter(function (c) { return c.specialty === cuisine; });
        var normalized = filtered.map(normalizeChef);

        if (reset) {
          self.setData({
            chefs: normalized,
            loadingChefs: false,
            loadingMore: false,
            noMore: true,
          });
        } else {
          self.setData({ loadingMore: false, noMore: true });
        }
      });
  },

  // ─── 菜系筛选切换 ───

  selectCuisine: function (e) {
    var cuisine = e.currentTarget.dataset.cuisine;
    if (cuisine === this.data.activeCuisine) return;
    this.setData({ activeCuisine: cuisine });
    this._loadChefs(true);
    // 同步刷新推荐区（筛选后推荐也按菜系）
    this._reloadFeaturedByCuisine(cuisine);
  },

  _reloadFeaturedByCuisine: function (cuisine) {
    if (cuisine === '全部') {
      this._loadFeatured();
      return;
    }
    var filtered = MOCK_CHEFS.filter(function (c) { return c.specialty === cuisine && c.featured; });
    if (filtered.length === 0) {
      filtered = MOCK_CHEFS.filter(function (c) { return c.specialty === cuisine; });
    }
    var normalized = filtered.slice(0, 4).map(normalizeChef);
    this.setData({ featuredChefs: normalized });
  },

  // ─── 无限滚动加载更多 ───

  loadMore: function () {
    if (this.data.loadingMore || this.data.noMore) return;
    this._loadChefs(false);
  },

  // ─── 跳转厨师详情 ───

  goDetail: function (e) {
    var id = e.currentTarget.dataset.id;
    if (!id) return;
    wx.navigateTo({
      url: '/pages/chef-at-home/chef-detail/chef-detail?chef_id=' + encodeURIComponent(id),
    });
  },

  // ─── 直接预约（跳预约表单，先写草稿） ───

  goBook: function (e) {
    var id = e.currentTarget.dataset.id;
    if (!id) return;

    // 在厨师列表卡片上点击「立即预约」时，先跳详情让用户选菜再预约
    wx.navigateTo({
      url: '/pages/chef-at-home/chef-detail/chef-detail?chef_id=' + encodeURIComponent(id),
    });
  },

  // ─── 跳转搜索页 ───

  goSearch: function () {
    wx.navigateTo({
      url: '/pages/chef-at-home/chef-search/chef-search',
    });
  },

  // ─── 筛选面板（暂时用 Toast 占位，后续可接抽屉组件） ───

  showFilter: function () {
    wx.showActionSheet({
      itemList: CUISINES.slice(1), // 去掉"全部"
      success: function (res) {
        var selected = CUISINES[res.tapIndex + 1];
        if (selected) {
          this.setData({ activeCuisine: selected });
          this._loadChefs(true);
        }
      }.bind(this),
      fail: function () {},
    });
  },

  // ─── 我的预约入口（可从右上角角标触发） ───

  goMyBookings: function () {
    wx.navigateTo({
      url: '/pages/chef-at-home/my-bookings/my-bookings',
    });
  },
});
