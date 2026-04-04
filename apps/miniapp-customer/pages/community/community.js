const app = getApp();
const api = require('../../utils/api.js');

// Mock数据
const MOCK_POSTS = [
  { id: '1', title: '探店丨徐记海鲜的椒盐虾绝了！', cover_url: '', tags: ['探店', '海鲜'], author_name: '美食家小王', author_avatar: '', like_count: 128, liked: false, created_at: '2026-04-02' },
  { id: '2', title: '在家复刻网红菜 | 超简单夫妻肺片', cover_url: '', tags: ['自制', '川菜'], author_name: '厨房小白', author_avatar: '', like_count: 89, liked: true, created_at: '2026-04-01' },
  { id: '3', title: '长沙必吃榜，这10家不能错过', cover_url: '', tags: ['长沙', '必吃'], author_name: '长沙吃货联盟', author_avatar: '', like_count: 356, liked: false, created_at: '2026-04-01' },
  { id: '4', title: '私藏！三文鱼的6种吃法', cover_url: '', tags: ['三文鱼', '日料'], author_name: 'Foodie同学', author_avatar: '', like_count: 201, liked: false, created_at: '2026-03-31' },
  { id: '5', title: '老长沙人推荐，这碗猪脚饭我吃了10年', cover_url: '', tags: ['长沙', '猪脚饭'], author_name: '本地老饕', author_avatar: '', like_count: 445, liked: true, created_at: '2026-03-31' },
  { id: '6', title: '网红卤鹅翅做法公开，比外卖便宜3倍', cover_url: '', tags: ['家常', '卤味'], author_name: '家常厨娘', author_avatar: '', like_count: 167, liked: false, created_at: '2026-03-30' },
];

Page({
  data: {
    activeTab: 'recommend',
    leftPosts: [],
    rightPosts: [],
    page: 1,
    loading: false,
    noMore: false,
  },

  onLoad() {
    this.loadPosts(true);
  },

  onShow() {
    // 从发布页返回时刷新
    if (this._needRefresh) {
      this._needRefresh = false;
      this.loadPosts(true);
    }
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    this.setData({ activeTab: tab, leftPosts: [], rightPosts: [], page: 1, noMore: false });
    this.loadPosts(true);
  },

  async loadPosts(reset = false) {
    if (this.data.loading || this.data.noMore) return;
    const page = reset ? 1 : this.data.page;
    this.setData({ loading: true });

    try {
      const data = await api.txRequest(
        `/api/v1/growth/community/posts?tab=${this.data.activeTab}&page=${page}&size=10`
      );

      let posts = (data && data.items) || MOCK_POSTS;
      if (reset) {
        this._allPosts = posts;
      } else {
        this._allPosts = [...(this._allPosts || []), ...posts];
      }

      // 分配到左右两列
      const left = [], right = [];
      this._allPosts.forEach((p, i) => {
        if (i % 2 === 0) left.push(p); else right.push(p);
      });

      this.setData({
        leftPosts: left,
        rightPosts: right,
        page: page + 1,
        loading: false,
        noMore: posts.length < 10,
      });
    } catch (err) {
      // 降级mock
      const left = [], right = [];
      MOCK_POSTS.forEach((p, i) => { if (i % 2 === 0) left.push(p); else right.push(p); });
      this.setData({ leftPosts: left, rightPosts: right, loading: false, noMore: true });
    }
  },

  loadMore() {
    this.loadPosts(false);
  },

  async toggleLike(e) {
    const { id, col, index } = e.currentTarget.dataset;
    const key = col === 'left' ? 'leftPosts' : 'rightPosts';
    const posts = this.data[key];
    const post = posts[index];
    const newLiked = !post.liked;

    // 乐观更新
    const updated = [...posts];
    updated[index] = { ...post, liked: newLiked, like_count: post.like_count + (newLiked ? 1 : -1) };
    this.setData({ [key]: updated });

    // 调接口（fire-and-forget，静默失败）
    api.txRequest(
      `/api/v1/growth/community/posts/${id}/like`,
      newLiked ? 'POST' : 'DELETE'
    ).catch(function() { /* 静默失败 */ });
  },

  goDetail(e) {
    wx.navigateTo({ url: `/pages/community-detail/community-detail?id=${e.currentTarget.dataset.id}` });
  },

  goPublish() {
    wx.navigateTo({ url: '/pages/community-publish/community-publish' });
  },
});
