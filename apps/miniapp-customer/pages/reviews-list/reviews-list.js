var app = getApp();
var api = require('../../utils/api.js');

// Mock 数据：5条评价
var MOCK_REVIEWS = [
  {
    id: 'r001',
    nickname: '食客小王',
    avatarUrl: '',
    isAnonymous: false,
    overallRating: 5,
    tags: ['味道棒极了', '服务热情', '会再来'],
    content: '菜品非常新鲜，口味地道，服务员很热情，环境也很舒适。强烈推荐招牌红烧肉，入口即化！',
    imageUrls: [],
    merchantReply: '感谢您的好评！我们会继续努力，期待您下次光临~',
    createdAt: '2026-03-30',
  },
  {
    id: 'r002',
    nickname: '美食达人',
    avatarUrl: '',
    isAnonymous: false,
    overallRating: 4,
    tags: ['性价比高', '分量充足'],
    content: '分量很足，价格实惠，就是高峰期上菜稍慢了点，整体还是很满意的。',
    imageUrls: [],
    merchantReply: '',
    createdAt: '2026-03-28',
  },
  {
    id: 'r003',
    nickname: '',
    avatarUrl: '',
    isAnonymous: true,
    overallRating: 5,
    tags: ['摆盘精致', '环境优雅'],
    content: '环境非常棒，适合商务宴请。菜品摆盘很精致，朋友都说好。',
    imageUrls: [],
    merchantReply: '',
    createdAt: '2026-03-25',
  },
  {
    id: 'r004',
    nickname: '长沙吃货',
    avatarUrl: '',
    isAnonymous: false,
    overallRating: 3,
    tags: [],
    content: '味道一般，感觉没有之前好吃了，希望保持以前的水准。',
    imageUrls: [],
    merchantReply: '感谢您的反馈！我们已将您的意见反馈给厨房团队，会努力改进的。',
    createdAt: '2026-03-22',
  },
  {
    id: 'r005',
    nickname: '湘菜爱好者',
    avatarUrl: '',
    isAnonymous: false,
    overallRating: 5,
    tags: ['上菜及时', '味道棒极了', '会再来'],
    content: '每次来都不失望，招牌菜每道都值得推荐。这次带了外地朋友来，他们都说要再来！',
    imageUrls: [],
    merchantReply: '',
    createdAt: '2026-03-20',
  },
];

Page({
  data: {
    storeId: '',
    storeName: '',
    avgScore: '4.6',
    totalCount: 0,
    ratingDist: [],
    subScores: [
      { label: '口味', value: '4.7' },
      { label: '服务', value: '4.5' },
      { label: '环境', value: '4.6' },
      { label: '速度', value: '4.4' },
    ],
    filterTabs: [
      { key: 'all', label: '全部' },
      { key: 'good', label: '好评' },
      { key: 'neutral', label: '中评' },
      { key: 'bad', label: '差评' },
      { key: 'image', label: '有图' },
    ],
    activeFilter: 'all',
    allReviews: [],
    filteredReviews: [],
    loading: false,
    hasMore: false,
  },

  onLoad: function(options) {
    var storeId = options.store_id || wx.getStorageSync('tx_store_id') || 'demo-store';
    var storeName = options.store_name || wx.getStorageSync('tx_store_name') || '屯象餐厅';
    this.setData({ storeId: storeId, storeName: storeName });
    this._loadReviews(storeId);
  },

  onPullDownRefresh: function() {
    var storeId = this.data.storeId;
    this._loadReviews(storeId, true);
  },

  _loadReviews: function(storeId, refresh) {
    var that = this;
    that.setData({ loading: true });

    api.txRequest('/api/v1/trade/reviews?store_id=' + storeId)
      .then(function(data) {
        var reviews = (data && data.items) ? data.items : MOCK_REVIEWS;
        that._processReviews(reviews);
      })
      .catch(function() {
        // 网络失败使用 Mock 数据
        that._processReviews(MOCK_REVIEWS);
      })
      .finally(function() {
        that.setData({ loading: false });
        if (refresh) { wx.stopPullDownRefresh(); }
      });
  },

  _processReviews: function(reviews) {
    var total = reviews.length;

    // 计算各星评分分布
    var starCount = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
    var totalScore = 0;
    reviews.forEach(function(r) {
      var s = r.overallRating || r.overall_rating || 5;
      starCount[s] = (starCount[s] || 0) + 1;
      totalScore += s;
    });

    var avgScore = total > 0 ? (totalScore / total).toFixed(1) : '5.0';

    var ratingDist = [5, 4, 3, 2, 1].map(function(s) {
      var cnt = starCount[s] || 0;
      return {
        star: s,
        count: cnt,
        percent: total > 0 ? Math.round(cnt / total * 100) : 0,
      };
    });

    // 标准化字段（兼容后端真实数据和Mock数据）
    var normalized = reviews.map(function(r) {
      return {
        id: r.id || r.review_id || '',
        nickname: r.nickname || r.customer_nickname || '',
        avatarUrl: r.avatarUrl || r.avatar_url || '',
        isAnonymous: r.isAnonymous || r.is_anonymous || false,
        overallRating: r.overallRating || r.overall_rating || 5,
        tags: r.tags || [],
        content: r.content || '',
        imageUrls: r.imageUrls || r.image_urls || [],
        merchantReply: r.merchantReply || r.merchant_reply || '',
        createdAt: (r.createdAt || r.created_at || '').slice(0, 10),
      };
    });

    this.setData({
      allReviews: normalized,
      totalCount: total,
      avgScore: avgScore,
      ratingDist: ratingDist,
      hasMore: false,
    });
    this._applyFilter(this.data.activeFilter, normalized);
  },

  switchFilter: function(e) {
    var key = e.currentTarget.dataset.key;
    this.setData({ activeFilter: key });
    this._applyFilter(key, this.data.allReviews);
  },

  _applyFilter: function(key, reviews) {
    var filtered;
    if (key === 'all') {
      filtered = reviews;
    } else if (key === 'good') {
      filtered = reviews.filter(function(r) { return r.overallRating >= 4; });
    } else if (key === 'neutral') {
      filtered = reviews.filter(function(r) { return r.overallRating === 3; });
    } else if (key === 'bad') {
      filtered = reviews.filter(function(r) { return r.overallRating <= 2; });
    } else if (key === 'image') {
      filtered = reviews.filter(function(r) { return r.imageUrls && r.imageUrls.length > 0; });
    } else {
      filtered = reviews;
    }
    this.setData({ filteredReviews: filtered });
  },

  previewImage: function(e) {
    var src = e.currentTarget.dataset.src;
    var list = e.currentTarget.dataset.list || [src];
    wx.previewImage({ current: src, urls: list });
  },

  loadMore: function() {
    // 当前 Mock 数据不需要分页，真实接入后实现
  },
});
